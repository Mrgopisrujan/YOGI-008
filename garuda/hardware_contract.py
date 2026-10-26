"""Evidence-backed hardware contract and physical attestation gates.

The contract records the selected design target. An attestation records measured
as-built evidence. Loading the contract never self-certifies physical hardware.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class FlightControllerContract(BaseModel):
    model: str = "MicoAir743-AIO-35A"
    revision: str = "original"
    px4_target: str = "micoair_h743-aio_default"
    board_marker: str = "MICOAIR_H743_AIO"
    firmware_candidate_sha256: str = (
        "85d5b667354e0868b7d0f92d4f4d0c34959dd10753ea10f34c245d120614aa25"
    )


class CompanionContract(BaseModel):
    model: str = "Raspberry Pi 5 8GB"
    supply_min_v: float = 5.0
    supply_min_a: float = 5.0
    dedicated_regulator_required: bool = True


class BatteryContract(BaseModel):
    model: str = "BETAFPV LAVA 3S 450mAh LiHV"
    cells: int = 3
    max_voltage_v: float = 13.05
    topology: Literal["single_pack_only"] = "single_pack_only"
    series_forbidden: bool = True


class TofContract(BaseModel):
    model: Literal["VL53L5CX", "VL53L8CX"] = "VL53L5CX"
    backend: Literal["vl53l5cx", "vl53l8cx"] = "vl53l5cx"
    i2c_bus: int = Field(default=1, ge=0)
    addresses: list[int] = Field(default_factory=lambda: [0x29], min_length=1)
    directions: list[str] = Field(default_factory=lambda: ["forward"], min_length=1)
    resolution: Literal[16, 64] = 64
    frequency_hz: int = Field(default=15, ge=1, le=60)
    max_range_m: float = Field(default=4.0, gt=0.0, le=4.0)

    @model_validator(mode="after")
    def validate_part_contract(self) -> TofContract:
        expected_backend = self.model.lower()
        if self.backend != expected_backend:
            raise ValueError(f"{self.model} requires backend {expected_backend}")
        if len(self.addresses) != len(self.directions):
            raise ValueError("ToF addresses and directions must have equal lengths")
        if len(set(self.addresses)) != len(self.addresses):
            raise ValueError("ToF I2C addresses must be unique")
        if any(not 0x08 <= address <= 0x77 for address in self.addresses):
            raise ValueError("ToF addresses must be Linux 7-bit I2C addresses")
        if self.resolution == 64 and self.frequency_hz > 15:
            raise ValueError("VL53L5CX/8CX 8x8 mode is limited to 15 Hz")
        return self


class HardwareContract(BaseModel):
    schema_version: int = 1
    profile: str = "flylens85-pi5-micoair743-aio"
    evidence_repository: str = "https://github.com/SREESAIARJUN/hardware-datasheets-docs"
    evidence_commit: str = "43a5a33d88baddca57245422b1cbe953010ffdc5"
    frame_model: str = "Flywoo FlyLens 85"
    flight_controller: FlightControllerContract = Field(default_factory=FlightControllerContract)
    companion: CompanionContract = Field(default_factory=CompanionContract)
    battery: BatteryContract = Field(default_factory=BatteryContract)
    tof: TofContract = Field(default_factory=TofContract)
    gnss_model: str = "MicoAir MG-A01"
    optical_flow_model: str = "MicoAir MTF-01"
    receiver_model: str = "Zerodrag Nexus1 2.4GHz ELRS"
    transmitter_model: str = "RadioMaster Pocket ELRS 2.4GHz"
    gimbal_model: str = "SkyDroid C10 Pro"


REQUIRED_EVIDENCE_GATES = (
    "firmware",
    "power",
    "mavlink",
    "tof",
    "propulsion",
    "rc_failsafe",
    "gimbal",
    "pi_runtime",
)


@dataclass(frozen=True)
class HardwareAttestationReceipt:
    """Immutable result of validating one attestation file and its reports."""

    verified: bool
    errors: tuple[str, ...]
    attestation_path: str
    attestation_sha256: str
    contract_profile: str


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonstandard_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


class EvidenceReference(BaseModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class HardwareAttestation(BaseModel):
    """As-built evidence produced from labels/photos and bench measurements."""

    flight_controller_px4_target: str
    flight_controller_board_marker: str
    flight_controller_revision: str
    companion_model: str
    tof_model: str
    frame_revision: str
    radio_variant: str
    evidence: dict[str, EvidenceReference] = Field(default_factory=dict)


def load_hardware_contract(path: str | Path) -> HardwareContract:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Hardware contract must be a YAML mapping: {path}")
    if "hardware" in data:
        data = data["hardware"]
    return HardwareContract.model_validate(data)


def load_hardware_attestation(path: str | Path) -> HardwareAttestation:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Hardware attestation must be a YAML mapping: {path}")
    return HardwareAttestation.model_validate(data)


def _validate_gate_report(
    gate: str,
    report: dict[str, object],
    contract: HardwareContract,
) -> list[str]:
    errors: list[str] = []

    def number(mapping: dict[str, object], key: str) -> float:
        value = mapping.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"{key} must be numeric")
            return float("-inf")
        numeric = float(value)
        if not math.isfinite(numeric):
            errors.append(f"{key} must be finite")
            return float("-inf")
        return numeric

    def require_true(key: str) -> None:
        if report.get(key) is not True:
            errors.append(f"{key} must be true")

    if gate == "firmware":
        if report.get("sha256") != contract.flight_controller.firmware_candidate_sha256:
            errors.append("sha256 does not match the selected firmware candidate")
        if report.get("required_marker") != contract.flight_controller.board_marker:
            errors.append("required_marker does not match the selected board")
        require_true("dfu_recovery_verified")
        require_true("flash_verified")
        if report.get("post_flash_board_marker") != contract.flight_controller.board_marker:
            errors.append("post_flash_board_marker does not match the selected board")
    elif gate == "power":
        minimum_v = number(report, "minimum_v")
        maximum_v = number(report, "maximum_v")
        ripple_mv_pp = number(report, "ripple_mv_pp")
        if minimum_v < 4.75:
            errors.append("minimum_v is below 4.75 V")
        if maximum_v > 5.25:
            errors.append("maximum_v exceeds 5.25 V")
        if minimum_v > maximum_v:
            errors.append("minimum_v exceeds maximum_v")
        if ripple_mv_pp < 0.0:
            errors.append("ripple_mv_pp cannot be negative")
        elif ripple_mv_pp > 100.0:
            errors.append("ripple_mv_pp exceeds 100 mVpp")
        if number(report, "duration_s") < 600.0:
            errors.append("duration_s is below 600 s")
    elif gate == "mavlink":
        if number(report, "duration_s") < 600.0:
            errors.append("duration_s is below 600 s")
        rates = report.get("rates_hz")
        if not isinstance(rates, dict):
            errors.append("rates_hz must be an object")
            rates = {}
        for message, minimum in {
            "HEARTBEAT": 1.0,
            "SYS_STATUS": 0.5,
            "OPTICAL_FLOW_RAD": 5.0,
            "DISTANCE_SENSOR": 5.0,
            "GPS_RAW_INT": 5.0,
            "RC_CHANNELS": 2.0,
        }.items():
            if number(rates, message) < minimum:
                errors.append(f"{message} rate is below {minimum:g} Hz")
        estimator_rates = [
            number(rates, message)
            for message in ("ESTIMATOR_STATUS", "EKF_STATUS_REPORT")
            if message in rates
        ]
        if max(estimator_rates, default=0.0) < 1.0:
            errors.append("estimator rate is below 1 Hz")
        gps = report.get("gps")
        if not isinstance(gps, dict):
            errors.append("gps must be an object")
            gps = {}
        if number(gps, "max_fix_type") < 3:
            errors.append("GNSS did not reach a 3D fix")
        if number(gps, "max_satellites") < 8:
            errors.append("GNSS did not observe at least 8 satellites")
    elif gate == "tof":
        if number(report, "valid_frames") < 9000:
            errors.append("valid_frames is below 9000")
        if number(report, "duration_s") < 600.0:
            errors.append("duration_s is below 600 s")
        if number(report, "frame_rate_hz") < 10.0:
            errors.append("frame_rate_hz is below 10 Hz")
        error_fraction = number(report, "error_fraction")
        if error_fraction < 0.0:
            errors.append("error_fraction cannot be negative")
        elif error_fraction > 0.01:
            errors.append("error_fraction exceeds 0.01")
    elif gate == "propulsion":
        require_true("motor_order_verified")
        require_true("rotation_verified")
        require_true("vibration_review_passed")
        if not str(report.get("propeller_model") or "").strip():
            errors.append("propeller_model is required")
        if number(report, "thrust_to_weight_ratio") < 2.0:
            errors.append("thrust_to_weight_ratio is below 2.0")
    elif gate == "rc_failsafe":
        require_true("rc_loss_land_observed")
        require_true("kill_switch_verified")
        require_true("pilot_override_verified")
    elif gate == "gimbal":
        require_true("rtsp_video_verified")
        require_true("control_response_verified")
        require_true("motion_limits_verified")
    elif gate == "pi_runtime":
        if number(report, "needle2_decode_tps") < 200.0:
            errors.append("needle2_decode_tps is below 200")
        require_true("cactus_lfm_smoke_passed")
        if number(report, "duration_s") < 600.0:
            errors.append("duration_s is below 600 s")
        if number(report, "max_cpu_temp_c") >= 80.0:
            errors.append("max_cpu_temp_c must remain below 80 C")
    return errors


def verify_hardware_attestation(
    contract: HardwareContract,
    attestation: HardwareAttestation,
    *,
    evidence_base: str | Path | None = None,
) -> list[str]:
    errors: list[str] = []
    exact_fields = {
        "flight_controller_px4_target": contract.flight_controller.px4_target,
        "flight_controller_board_marker": contract.flight_controller.board_marker,
        "flight_controller_revision": contract.flight_controller.revision,
        "companion_model": contract.companion.model,
        "tof_model": contract.tof.model,
        "radio_variant": contract.transmitter_model,
    }
    for field_name, expected in exact_fields.items():
        actual = getattr(attestation, field_name)
        if actual != expected:
            errors.append(f"{field_name}: expected {expected!r}, got {actual!r}")

    if not attestation.frame_revision.strip() or attestation.frame_revision.lower() == "unknown":
        errors.append("frame_revision: exact physical frame revision is required")
    if not attestation.radio_variant.strip() or attestation.radio_variant.lower() == "unknown":
        errors.append("radio_variant: exact physical transmitter variant is required")

    base = Path(evidence_base).resolve() if evidence_base is not None else None
    for gate in REQUIRED_EVIDENCE_GATES:
        reference = attestation.evidence.get(gate)
        if reference is None:
            errors.append(f"{gate}: evidence report is required")
            continue
        if base is None:
            errors.append(f"{gate}: evidence_base is required to verify the report")
            continue
        report_path = (base / reference.path).resolve()
        try:
            report_path.relative_to(base)
        except ValueError:
            errors.append(f"{gate}: path escapes the attestation directory")
            continue
        try:
            payload = report_path.read_bytes()
        except OSError as exc:
            errors.append(f"{gate}: cannot read report: {exc}")
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if digest.lower() != reference.sha256.lower():
            errors.append(f"{gate}: SHA-256 mismatch")
            continue
        try:
            report = json.loads(
                payload,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_nonstandard_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{gate}: invalid JSON report: {exc}")
            continue
        if not isinstance(report, dict) or report.get("passed") is not True:
            errors.append(f"{gate}: report did not pass")
            continue
        errors.extend(f"{gate}: {error}" for error in _validate_gate_report(gate, report, contract))
    return errors


def verify_hardware_attestation_path(
    contract_path: str | Path,
    attestation_path: str | Path,
) -> HardwareAttestationReceipt:
    """Verify an on-disk attestation and bind the result to its exact bytes."""
    resolved_attestation = Path(attestation_path).resolve()
    digest = ""
    profile = ""
    errors: list[str] = []
    try:
        contract = load_hardware_contract(contract_path)
        profile = contract.profile
    except Exception as exc:
        return HardwareAttestationReceipt(
            verified=False,
            errors=(f"hardware contract invalid: {exc}",),
            attestation_path=str(resolved_attestation),
            attestation_sha256=digest,
            contract_profile=profile,
        )

    try:
        payload = resolved_attestation.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        data = yaml.safe_load(payload)
        if not isinstance(data, dict):
            raise ValueError("hardware attestation must be a YAML mapping")
        attestation = HardwareAttestation.model_validate(data)
    except Exception as exc:
        errors.append(f"hardware attestation invalid: {exc}")
    else:
        errors.extend(
            verify_hardware_attestation(
                contract,
                attestation,
                evidence_base=resolved_attestation.parent,
            )
        )

    return HardwareAttestationReceipt(
        verified=not errors,
        errors=tuple(errors),
        attestation_path=str(resolved_attestation),
        attestation_sha256=digest,
        contract_profile=profile,
    )
