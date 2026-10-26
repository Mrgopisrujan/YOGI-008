"""CfC LNN controller — NumPy-only inference (no PyTorch on Pi 5).

Exports the trained CfC weights to a NumPy .npz file and runs inference
using pure NumPy matrix operations. No PyTorch, no ncps, no GPU.

The CfC (Closed-form Continuous-time) RNN has 3 layers:
  Layer 0: input_size=21 (12 input + 9 hidden), output=9
  Layer 1: input_size=14 (9 + 5 hidden), output=5
  Layer 2: input_size=10 (5 + 5 hidden), output=5

Each ncps CfC layer computes (with elapsed time ``ts``):
  ff1_out = tanh((ff1_weight * sparsity_mask) @ input + ff1_bias)
  ff2_out = tanh((ff2_weight * sparsity_mask) @ input + ff2_bias)
  t_interp = sigmoid((time_a @ input + time_a_bias) * ts
                     + time_b @ input + time_b_bias)
  output = ff1_out * (1 - t_interp) + t_interp * ff2_out

Architecture: cfc_v1_n19_i12_o5
  19 neurons, 12 inputs, 5 outputs, 1,621 params
  Wiring: AutoNCP(19, 5, seed=22222, sparsity=0.5)
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..arbiter.safety_limits import CfCContract

logger = logging.getLogger(__name__)


# ─── Checkpoint metadata ──────────────────────────────────────────────────────

@dataclass
class CheckpointMeta:
    """Metadata embedded in or alongside a CfC checkpoint."""
    arch_id: str = ""
    input_size: int = 0
    output_size: int = 0
    num_neurons: int = 0
    status: str = "not_loaded"
    git_sha: str = ""
    dataset_id: str = ""
    created_utc: str = ""
    sha256: str = ""


@dataclass(frozen=True)
class CfcQualificationReceipt:
    """Result of validating a checkpoint against external qualification evidence."""

    verified: bool
    errors: tuple[str, ...]
    checkpoint_sha256: str
    dataset_id: str
    dataset_sha256: str
    qualification_path: str


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _load_strict_json(path: Path) -> dict[str, object]:
    data = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contained_path(base: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("path must be a non-empty string")
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError("path escapes qualification directory") from exc
    return candidate


def verify_cfc_qualification(
    checkpoint_path: str | Path,
    qualification_path: str | Path,
) -> CfcQualificationReceipt:
    """Verify external expert-data and validation evidence for one checkpoint."""
    checkpoint = Path(checkpoint_path).resolve()
    qualification = Path(qualification_path).resolve()
    errors: list[str] = []
    checkpoint_digest = ""
    dataset_id = ""
    dataset_digest = ""
    try:
        checkpoint_digest = _sha256(checkpoint)
        manifest = _load_strict_json(qualification)
    except Exception as exc:
        return CfcQualificationReceipt(
            verified=False,
            errors=(f"qualification input invalid: {exc}",),
            checkpoint_sha256=checkpoint_digest,
            dataset_id=dataset_id,
            dataset_sha256=dataset_digest,
            qualification_path=str(qualification),
        )

    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if manifest.get("arch_id") != "cfc_v1_n19_i12_o5":
        errors.append("arch_id mismatch")
    try:
        referenced = _contained_path(qualification.parent, manifest.get("checkpoint_path"))
        if referenced != checkpoint:
            errors.append("checkpoint_path does not reference the supplied checkpoint")
    except ValueError as exc:
        errors.append(f"checkpoint_path invalid: {exc}")

    expected_checkpoint_hash = manifest.get("checkpoint_sha256")
    if not isinstance(expected_checkpoint_hash, str) or len(expected_checkpoint_hash) != 64:
        errors.append("checkpoint_sha256 must be a 64-character digest")
    elif expected_checkpoint_hash.lower() != checkpoint_digest:
        errors.append("checkpoint SHA-256 mismatch")

    value = manifest.get("dataset_id")
    if isinstance(value, str):
        dataset_id = value
    if not dataset_id or "synthetic" in dataset_id.lower():
        errors.append("dataset_id must identify non-synthetic expert data")
    dataset_hash = manifest.get("dataset_sha256")
    if not isinstance(dataset_hash, str) or len(dataset_hash) != 64:
        errors.append("dataset_sha256 must be a 64-character digest")
    else:
        try:
            dataset_path = _contained_path(qualification.parent, manifest.get("dataset_path"))
            dataset_digest = _sha256(dataset_path)
            if dataset_digest != dataset_hash.lower():
                errors.append("dataset SHA-256 mismatch")
        except Exception as exc:
            errors.append(f"dataset path invalid: {exc}")
    if manifest.get("expert_source") not in {"human_pilot", "tethered_flight"}:
        errors.append("expert_source must be human_pilot or tethered_flight")
    if not isinstance(manifest.get("approved_by"), str) or not manifest.get("approved_by"):
        errors.append("approved_by is required")
    if not isinstance(manifest.get("approved_utc"), str) or not manifest.get("approved_utc"):
        errors.append("approved_utc is required")

    validation_ref = manifest.get("validation_report")
    if not isinstance(validation_ref, dict):
        errors.append("validation_report must be an object")
    else:
        try:
            report_path = _contained_path(qualification.parent, validation_ref.get("path"))
            expected_report_hash = validation_ref.get("sha256")
            if not isinstance(expected_report_hash, str) or len(expected_report_hash) != 64:
                raise ValueError("validation report sha256 must be a 64-character digest")
            if _sha256(report_path) != expected_report_hash.lower():
                raise ValueError("validation report SHA-256 mismatch")
            report = _load_strict_json(report_path)
            if report.get("passed") is not True:
                errors.append("validation report did not pass")
            held_out = report.get("held_out_sequences")
            if isinstance(held_out, bool) or not isinstance(held_out, int) or held_out <= 0:
                errors.append("validation report held_out_sequences must be positive")
            for key in (
                "output_bounds_verified",
                "temporal_smoothness_verified",
                "closed_loop_sitl_passed",
                "independent_review_passed",
            ):
                if report.get(key) is not True:
                    errors.append(f"validation report {key} must be true")
            for report_value in report.values():
                if isinstance(report_value, float) and not math.isfinite(report_value):
                    errors.append("validation report contains a non-finite value")
        except Exception as exc:
            errors.append(f"validation report invalid: {exc}")

    return CfcQualificationReceipt(
        verified=not errors,
        errors=tuple(errors),
        checkpoint_sha256=checkpoint_digest,
        dataset_id=dataset_id,
        dataset_sha256=dataset_digest,
        qualification_path=str(qualification),
    )


# ─── Toy detection ────────────────────────────────────────────────────────────

# A real trained checkpoint has 1621 params (AutoNCP 19,5).
# A toy file has 480 params (4/2/4 wiring).
_REAL_PARAM_COUNT = 1621
_TOY_PARAM_COUNT = 480


def is_toy_checkpoint(param_count: int) -> bool:
    """Detect toy/random weights that must never fly."""
    return param_count == _TOY_PARAM_COUNT or param_count < 1000


# ─── NumPy CfC model ──────────────────────────────────────────────────────────

class NumpyCfC:
    """Pure NumPy CfC inference — no PyTorch needed.

    The CfC has 3 stacked layers. Each layer follows ncps' default mode:
    - ff1/ff2: masked affine transforms followed by tanh
    - time_a/time_b: interpolate the two candidates using elapsed time

    The default elapsed time is 1.0, matching ``ncps.torch.CfC`` when no
    explicit ``timespans`` tensor is supplied.
    """

    def __init__(self, weights: dict[str, np.ndarray], sparsity_masks: list[np.ndarray]):
        """Initialize with extracted weights.

        Args:
            weights: dict of {name: np.ndarray} for ff1/ff2/time_a/time_b
            sparsity_masks: list of sparsity mask arrays per layer
        """
        self.layers = []
        for i in range(3):
            prefix = f"rnn_cell.layer_{i}."
            layer = {
                "ff1_w": weights[prefix + "ff1.weight"],
                "ff1_b": weights[prefix + "ff1.bias"],
                "ff2_w": weights[prefix + "ff2.weight"],
                "ff2_b": weights[prefix + "ff2.bias"],
                "time_a_w": weights[prefix + "time_a.weight"],
                "time_a_b": weights[prefix + "time_a.bias"],
                "time_b_w": weights[prefix + "time_b.weight"],
                "time_b_b": weights[prefix + "time_b.bias"],
                "mask": sparsity_masks[i] if i < len(sparsity_masks) else None,
            }
            self.layers.append(layer)

    def forward(
        self,
        x: np.ndarray,
        hx: np.ndarray,
        elapsed_time: float = 1.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Run one CfC forward step, equivalent to ncps' default-mode cell.

        Args:
            x: input vector (input_size,)
            hx: hidden state (num_neurons,) — split across 3 layers
            elapsed_time: CfC timespan. ncps uses 1.0 when omitted.

        Returns:
            (output, new_hx) — output (output_size,), new_hx (num_neurons,)
        """
        # Split hidden state across 3 layers
        # Layer 0: 9 hidden, Layer 1: 5 hidden, Layer 2: 5 hidden = 19 total
        h0 = hx[0:9]
        h1 = hx[9:14]
        h2 = hx[14:19]

        outputs = []
        new_hidden = []

        for i, layer in enumerate(self.layers):
            h_prev = [h0, h1, h2][i]
            # Concatenate input + hidden state
            combined = np.concatenate([x, h_prev]) if i == 0 else \
                       np.concatenate([outputs[-1], h_prev])

            mask = layer["mask"]
            ff1_w = layer["ff1_w"] * mask if mask is not None else layer["ff1_w"]
            ff2_w = layer["ff2_w"] * mask if mask is not None else layer["ff2_w"]

            # Exact ncps default-mode CfC equations.
            ff1_out = np.tanh(ff1_w @ combined + layer["ff1_b"])
            ff2_out = np.tanh(ff2_w @ combined + layer["ff2_b"])
            time_a = layer["time_a_w"] @ combined + layer["time_a_b"]
            time_b = layer["time_b_w"] @ combined + layer["time_b_b"]
            t_interp = 1.0 / (1.0 + np.exp(-(time_a * elapsed_time + time_b)))
            out = ff1_out * (1.0 - t_interp) + t_interp * ff2_out

            outputs.append(out)
            new_hidden.append(out)

        # Concatenate new hidden states
        new_hx = np.concatenate(new_hidden)
        return outputs[-1], new_hx


# ─── Controller ───────────────────────────────────────────────────────────────

class CfcController:
    """CfC LNN controller — NumPy inference (no PyTorch on Pi 5).

    Loads weights from either:
    - PyTorch checkpoint (.pt) → extracts to NumPy arrays
    - NumPy export (.npz) → direct load (preferred for Pi 5)

    The .npz format is ~16KB (same as .pt) but loads in 0.1ms
    vs PyTorch's ~500ms import + 5ms forward.
    """

    def __init__(
        self,
        contract: Any = None,
        *,
        allow_synthetic_checkpoint: bool = False,
    ) -> None:
        """Initialize CfC controller.

        Args:
            contract: Optional CfCContract (ignored — uses hardcoded contract).
            allow_synthetic_checkpoint: Development/audit-only override. Real
                flight code must leave this False so synthetic checkpoints are
                rejected until expert-pilot data has been used for training.
        """
        self.arch_id = "cfc_v1_n19_i12_o5"
        self.input_size = 12
        self.output_size = 5
        self.num_neurons = 19
        self.contract = contract if contract is not None else CfCContract()
        self.allow_synthetic_checkpoint = allow_synthetic_checkpoint

        self._model: NumpyCfC | None = None
        self.weights_loaded: bool = False
        self.weights_status: str = "not_loaded"  # "flight" | "smoke" | "toy" | "not_loaded"
        self.weights_arch_id: str = ""
        self.weights_sha256: str = ""
        self._qualification: CfcQualificationReceipt | None = None

        self.hx: np.ndarray = np.zeros(self.num_neurons, dtype=np.float32)

        # Last inference time for benchmarking
        self._last_inference_ms: float = 0.0

    def reset_hx(self) -> None:
        """Reset hidden state to zeros."""
        self.hx = np.zeros(self.num_neurons, dtype=np.float32)

    def load_checkpoint_from_file(self, path: str | Path) -> bool:
        """Load checkpoint from .pt (PyTorch) or .npz (NumPy) file.

        Tries .npz first (preferred, no PyTorch needed).
        Falls back to .pt (requires torch).
        """
        path = Path(path)
        self.weights_loaded = False
        self._model = None
        if self._qualification is None and not self.allow_synthetic_checkpoint:
            self.weights_status = "unqualified"
            logger.error("Refusing unqualified CfC checkpoint: %s", path)
            return False

        # Load the exact hash-qualified artifact. Never substitute a sibling
        # file with the same stem after qualification has verified this path.
        if path.suffix == ".npz" and path.exists():
            return self._load_numpy(path)
        if path.suffix == ".pt" and path.exists():
            return self._load_pytorch(path)

        logger.warning(f"No CfC checkpoint found at {path}")
        return False

    def load_qualified_checkpoint(
        self,
        checkpoint_path: str | Path,
        qualification_path: str | Path,
    ) -> bool:
        """Load only after independent hash-bound qualification succeeds."""
        receipt = verify_cfc_qualification(checkpoint_path, qualification_path)
        if not receipt.verified:
            self.weights_status = "qualification_failed"
            logger.error("CfC qualification failed: %s", list(receipt.errors))
            return False
        self._qualification = receipt
        loaded = self.load_checkpoint_from_file(checkpoint_path)
        if not loaded:
            self._qualification = None
        return loaded

    def _load_numpy(self, path: Path) -> bool:
        """Load from NumPy .npz file (preferred — no PyTorch needed)."""
        try:
            data = np.load(path, allow_pickle=True)

            # Extract metadata from meta__ keys
            meta = {}
            for key in data.files:
                if key.startswith("meta__"):
                    val = data[key]
                    # Extract scalar from 0-d array
                    if hasattr(val, 'item'):
                        val = val.item()
                    meta[key.replace("meta__", "")] = val

            # Validate
            param_count = int(meta.get("param_count", 0))
            if is_toy_checkpoint(param_count):
                logger.warning("CfC checkpoint is TOY — refusing to load for flight")
                self.weights_status = "toy"
                return False

            if meta.get("arch_id", "") != self.arch_id:
                logger.warning(f"CfC arch mismatch: {meta.get('arch_id')} != {self.arch_id}")
                return False

            if meta.get("status", "") not in {"flight", "candidate"}:
                logger.warning(f"CfC status is not loadable: {meta.get('status')}")
                return False

            dataset_id = str(meta.get("dataset_id", ""))
            if "synthetic" in dataset_id.lower() and not self.allow_synthetic_checkpoint:
                logger.error(
                    "Refusing synthetic CfC checkpoint for flight: dataset_id=%s. "
                    "Retrain on expert pilot data first.", dataset_id,
                )
                self.weights_status = "synthetic"
                return False
            if self._qualification is not None and dataset_id != self._qualification.dataset_id:
                logger.error("CfC dataset_id does not match qualification receipt")
                self.weights_status = "qualification_mismatch"
                return False
            if (
                self._qualification is not None
                and str(meta.get("dataset_sha256", "")) != self._qualification.dataset_sha256
            ):
                logger.error("CfC dataset_sha256 does not match qualification receipt")
                self.weights_status = "qualification_mismatch"
                return False

            # Extract weights
            weights = {}
            sparsity_masks: dict[int, np.ndarray] = {}
            for key in data.files:
                if key.startswith("rnn_cell."):
                    if "sparsity_mask" in key:
                        layer_idx = int(key.split("layer_")[1].split(".")[0])
                        sparsity_masks[layer_idx] = data[key]
                    elif any(x in key for x in ["ff1", "ff2", "time_a", "time_b"]):
                        weights[key] = data[key]

            masks = [sparsity_masks[i] for i in range(3)]

            self._model = NumpyCfC(weights, masks)
            self.weights_loaded = True
            self.weights_status = str(meta.get("status", ""))
            self.weights_arch_id = meta.get("arch_id", "")
            self.weights_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            self.reset_hx()

            logger.info(f"CfC loaded (NumPy): {len(weights)} weight arrays, "
                       f"{sum(w.size for w in weights.values())} params")
            return True

        except Exception as e:
            logger.error(f"CfC NumPy load error: {e}")
            return False

    def _load_pytorch(self, path: Path) -> bool:
        """Load from PyTorch .pt checkpoint (fallback — requires torch)."""
        try:
            import torch

            ckpt = torch.load(path, map_location="cpu", weights_only=False)

            # Validate
            param_count = ckpt.get("param_count", 0)
            if is_toy_checkpoint(param_count):
                logger.warning("CfC checkpoint is TOY — refusing to load for flight")
                self.weights_status = "toy"
                return False

            if ckpt.get("arch_id", "") != self.arch_id:
                logger.warning(f"CfC arch mismatch: {ckpt.get('arch_id')} != {self.arch_id}")
                return False

            if ckpt.get("status", "") not in {"flight", "candidate"}:
                logger.warning(f"CfC status is not loadable: {ckpt.get('status')}")
                return False

            dataset_id = str(ckpt.get("dataset_id", ""))
            if "synthetic" in dataset_id.lower() and not self.allow_synthetic_checkpoint:
                logger.error(
                    "Refusing synthetic CfC checkpoint for flight: dataset_id=%s. "
                    "Retrain on expert pilot data first.", dataset_id,
                )
                self.weights_status = "synthetic"
                return False
            if self._qualification is not None and dataset_id != self._qualification.dataset_id:
                logger.error("CfC dataset_id does not match qualification receipt")
                self.weights_status = "qualification_mismatch"
                return False
            if (
                self._qualification is not None
                and str(ckpt.get("dataset_sha256", "")) != self._qualification.dataset_sha256
            ):
                logger.error("CfC dataset_sha256 does not match qualification receipt")
                self.weights_status = "qualification_mismatch"
                return False

            # Convert PyTorch tensors to NumPy arrays
            sd = ckpt["model_state_dict"]
            weights = {}
            sparsity_masks: dict[int, np.ndarray] = {}
            for key, tensor in sd.items():
                if "sparsity_mask" in key:
                    layer_idx = int(key.split("layer_")[1].split(".")[0])
                    sparsity_masks[layer_idx] = tensor.numpy()
                else:
                    weights[key] = tensor.numpy()

            masks = [sparsity_masks[i] for i in range(3)]

            self._model = NumpyCfC(weights, masks)
            self.weights_loaded = True
            self.weights_status = str(ckpt.get("status", ""))
            self.weights_arch_id = ckpt.get("arch_id", "")
            self.weights_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            self.reset_hx()

            logger.info(f"CfC loaded (PyTorch→NumPy): {len(weights)} weight arrays, "
                       f"{param_count} params")
            return True

        except ImportError:
            logger.warning("PyTorch not installed — cannot load .pt checkpoint")
            return False
        except Exception as e:
            logger.error(f"CfC PyTorch load error: {e}")
            return False

    def forward(self, input_vec: list[float] | np.ndarray) -> list[float]:
        """Run one CfC forward step.

        Args:
            input_vec: 12-element input vector

        Returns:
            [body_forward, body_right, ned_down, body_yaw_rate,
            gimbal_yaw_speed_command]
        """
        x = np.asarray(input_vec, dtype=np.float32)
        if x.shape != (self.input_size,):
            raise ValueError(f"CfC input must have exactly {self.input_size} values")
        if not np.isfinite(x).all():
            raise ValueError("CfC input must contain only finite values")
        if not self.weights_loaded or self._model is None:
            return [0.0] * self.output_size

        t_start = time.monotonic()

        output, new_hx = self._model.forward(x, self.hx.copy())
        output = np.asarray(output, dtype=np.float32)
        new_hx = np.asarray(new_hx, dtype=np.float32)
        if output.shape != (self.output_size,) or new_hx.shape != (self.num_neurons,):
            raise RuntimeError("CfC model returned an invalid tensor shape")
        if not np.isfinite(output).all() or not np.isfinite(new_hx).all():
            raise RuntimeError("CfC model returned non-finite state or output")

        # Clamp output to safety limits
        output = self._clamp_output(output)
        if not np.isfinite(output).all():
            raise RuntimeError("CfC clamp produced non-finite output")
        self.hx = new_hx

        self._last_inference_ms = (time.monotonic() - t_start) * 1000

        return output.tolist()

    def _clamp_output(self, output: np.ndarray) -> np.ndarray:
        """Clamp output to contract safety limits."""
        limits = np.array(
            [
                5.0,
                5.0,
                self.contract.vz_max_mps,
                self.contract.yaw_rate_max_rad_s,
                self.contract.gimbal_yaw_max_deg,
            ],
            dtype=np.float32,
        )
        return np.clip(output, -limits, limits)

    @property
    def inference_ms(self) -> float:
        """Last inference time in milliseconds."""
        return self._last_inference_ms

    @property
    def is_loaded(self) -> bool:
        return self.weights_loaded

    def load_checkpoint(self, path: str | Path | None = None) -> bool:
        """Load checkpoint (legacy API — delegates to load_checkpoint_from_file)."""
        if path is None:
            default = Path(__file__).resolve().parent.parent.parent.parent / "models" / "cfc_v1_n19_i12_o5.pt"
            path = default
        return self.load_checkpoint_from_file(path)


# ─── Backward compatibility (old PyTorch API) ─────────────────────────────────

# Old test/API compatibility — these are kept so existing tests pass
CfcInput = list  # Input is just a list of 12 floats
CfcOutput = list  # Output is just a list of 5 floats
TOY_PARAMS = _TOY_PARAM_COUNT
TOY_LAYERS = 3  # 4/2/4 wiring


def validate_checkpoint(meta: dict | CheckpointMeta) -> bool:
    """Validate checkpoint metadata (legacy API)."""
    if isinstance(meta, dict):
        if is_toy_checkpoint(meta.get("param_count", 0)):
            return False
        return meta.get("arch_id", "") == "cfc_v1_n19_i12_o5"
    if is_toy_checkpoint(meta.num_neurons if meta.num_neurons else 0):
        return False
    return meta.arch_id == "cfc_v1_n19_i12_o5"


def export_pytorch_to_numpy(pt_path: str | Path, npz_path: str | Path | None = None) -> Path:
    """Export PyTorch checkpoint to NumPy .npz format.

    This eliminates the PyTorch dependency for Pi 5 deployment.
    The .npz file contains the same weights as .pt but loads
    with np.load() instead of torch.load().

    Usage:
        from garudaone.control.cfc_controller import export_pytorch_to_numpy
        export_pytorch_to_numpy("models/cfc_v1_n19_i12_o5.pt")
        # → models/cfc_v1_n19_i12_o5.npz (16KB, no torch needed)
    """
    pt_path = Path(pt_path)
    if npz_path is None:
        npz_path = pt_path.with_suffix(".npz")
    else:
        npz_path = Path(npz_path)

    import numpy as np
    import torch

    ckpt = torch.load(pt_path, map_location="cpu", weights_only=False)
    sd = ckpt["model_state_dict"]

    # Convert all tensors to numpy
    arrays = {}
    for key, tensor in sd.items():
        arrays[key] = tensor.numpy()

    # Add metadata
    for meta_key in ["arch_id", "input_size", "output_size", "num_neurons",
                     "status", "git_sha", "dataset_id", "dataset_sha256", "created_utc",
                     "sha256", "param_count", "wiring_seed", "wiring_sparsity",
                     "final_loss"]:
        if meta_key in ckpt:
            arrays[f"meta__{meta_key}"] = np.array(str(ckpt[meta_key]))

    np.savez(npz_path, **arrays)
    logger.info(f"Exported CfC: {pt_path.name} → {npz_path.name} ({npz_path.stat().st_size} bytes)")
    return npz_path
