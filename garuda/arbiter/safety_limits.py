"""SafetyLimits — pydantic model loaded from configs/default.yaml.

This is the single policy source. Only the arbiter applies policy.
control/clamps.py mirrors these values (defense-in-depth, not second policy).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, Field, model_validator

from ..hardware_contract import HardwareContract


class VModeCap(BaseModel):
    """Per-mode speed caps in m/s."""
    hover: float = 0.0
    hold: float = 0.5
    track: float = 5.0
    land: float = 1.5
    rtl: float = 3.0
    search: float = 1.0
    takeoff: float = 0.5


class TakeoffLimits(BaseModel):
    """Operator takeoff altitude and climb envelope."""
    default_altitude_m: float = Field(default=1.5, ge=0.5, le=3.0)
    min_altitude_m: float = Field(default=0.5, ge=0.2, le=1.0)
    max_altitude_m: float = Field(default=3.0, ge=1.0, le=5.0)
    climb_rate_mps: float = Field(default=0.5, ge=0.1, le=1.0)
    altitude_tolerance_m: float = Field(default=0.15, ge=0.05, le=0.5)
    timeout_s: float = Field(default=20.0, ge=2.0, le=30.0)
    position_freshness_s: float = Field(default=0.5, gt=0.0, le=2.0)
    evidence_reacquire_s: float = Field(default=1.0, gt=0.0, le=2.0)
    sitl_min_battery_remaining_pct: float = Field(default=20.0, ge=5.0, le=95.0)
    landed_freshness_s: float = Field(default=2.0, gt=0.0, le=5.0)
    battery_freshness_s: float = Field(default=2.0, gt=0.0, le=5.0)
    ekf_freshness_s: float = Field(default=2.0, gt=0.0, le=5.0)
    heartbeat_freshness_s: float = Field(default=2.0, gt=0.0, le=5.0)


class VToF(BaseModel):
    """ToF-based speed limiting."""
    min_confidence: float = 0.4
    range_full_mps: float = 5.0
    v_at_full_range_mps: float = 3.0
    v_if_blind_mps: float = 0.5


class ThermalC(BaseModel):
    """Thermal thresholds in Celsius."""
    warn: int = 80
    land: int = 85


class BatteryLimits(BaseModel):
    """Battery voltage thresholds per cell."""
    land_v_per_cell_under_load: float = 3.5
    never_below_v_per_cell: float = 3.4
    cells: int = 3


class TargetLostTimers(BaseModel):
    """Target-lost FSM timers in seconds."""
    hover_s: float = 2.0
    search_s: float = 10.0
    rtl_s: float = 30.0


class GimbalLimits(BaseModel):
    """Gimbal heartbeat and fail modes."""
    heartbeat_timeout_s: float = 1.0
    on_loss: str = "freeze_and_disable_counter_rotation"


class GeofenceLimits(BaseModel):
    """Geofence radius and altitude limits."""
    max_horiz_m: float = 50.0
    max_alt_m: float = 30.0


class CommandWsLimits(BaseModel):
    """Command WebSocket rate limiting and auth."""
    rate_limit_hz: int = 5
    require_token_in_flight_yaml: bool = True


class SafetyLimits(BaseModel):
    """All safety thresholds. Loaded from configs/default.yaml.

    This is THE policy source. No other module invents safety numbers.
    """

    setpoint_hz: int = 20
    setpoint_age_warn_ms: int = 100
    setpoint_age_hold_ms: int = 250
    com_of_loss_t_s: float = 0.5
    com_obl_rc_act: int = 4

    v_mode_cap_mps: VModeCap = Field(default_factory=VModeCap)
    v_tof: VToF = Field(default_factory=VToF)
    v_semantic_open_air_mps: float = 5.0
    v_gps_degraded_mps: float = 2.0

    thermal_c: ThermalC = Field(default_factory=ThermalC)
    battery: BatteryLimits = Field(default_factory=BatteryLimits)
    target_lost: TargetLostTimers = Field(default_factory=TargetLostTimers)
    gimbal: GimbalLimits = Field(default_factory=GimbalLimits)
    geofence: GeofenceLimits = Field(default_factory=GeofenceLimits)
    command_ws: CommandWsLimits = Field(default_factory=CommandWsLimits)
    takeoff: TakeoffLimits = Field(default_factory=TakeoffLimits)


class FeatureFlags(BaseModel):
    """Feature flags controlling mode availability."""
    enable_track_mode: bool = False
    allow_track_without_gimbal: bool = False
    tof_mock_allowed: bool = True
    telemetry_mock_allowed: bool = True
    enable_vlm_eye: bool = False
    enable_needle: bool = False
    enable_perception: bool = False
    enable_c10: bool = False
    enable_voice: bool = False
    enable_takeoff: bool = True
    require_token_in_flight_yaml: bool = True


class CfCContract(BaseModel):
    """CfC LNN architecture contract (frozen — cfc_v1_n19_i12_o5)."""
    arch_id: str = "cfc_v1_n19_i12_o5"
    num_neurons: int = 19
    input_size: int = 12
    output_size: int = 5
    yaw_rate_max_rad_s: float = 1.0
    gimbal_yaw_max_deg: float = 45.0
    vz_max_mps: float = 1.5
    checkpoint_path: str = ""
    qualification_path: str = ""


class TrackingConfig(BaseModel):
    """Validated perception and identity timing policy."""
    camera_backend: Literal["file", "webcam", "picam", "skydroid", "synthetic", "null"] = (
        "synthetic"
    )
    camera_source: str = ""
    target_fps: int = Field(default=20, ge=1, le=60)
    detector_interval: int = Field(default=2, ge=1, le=20)
    depth_interval: int = Field(default=4, ge=1, le=40)
    thermal_detector_interval: int = Field(default=4, ge=1, le=40)
    freshness_s: float = Field(default=0.25, gt=0.0, le=1.0)
    startup_timeout_s: float = Field(default=15.0, gt=0.0, le=60.0)
    search_yaw_rate_rad_s: float = Field(default=0.2, ge=0.0, le=1.0)
    min_confirm_hits: int = Field(default=3, ge=1, le=20)
    max_lost_frames: int = Field(default=30, ge=1, le=300)

    @model_validator(mode="after")
    def validate_camera_source(self) -> TrackingConfig:
        if self.camera_backend != "skydroid":
            return self
        parsed = urlsplit(self.camera_source)
        if (
            parsed.scheme.lower() != "rtsp"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.query)
            or bool(parsed.fragment)
        ):
            raise ValueError("skydroid camera_source must be a credential-free rtsp:// URL")
        return self

    @property
    def max_flow_frames(self) -> int:
        """Maximum flow-only frames before the next scheduled detector run."""
        return max(self.detector_interval, self.thermal_detector_interval) - 1


class Config(BaseModel):
    """Top-level config loaded from yaml files."""

    safety: SafetyLimits = Field(default_factory=SafetyLimits)
    flags: FeatureFlags = Field(default_factory=FeatureFlags)
    cfc: CfCContract = Field(default_factory=CfCContract)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    hardware: HardwareContract = Field(default_factory=HardwareContract)

    @model_validator(mode="after")
    def reject_mock_camera_in_physical_perception(self) -> Config:
        physical_profile = (
            not self.flags.tof_mock_allowed
            or not self.flags.telemetry_mock_allowed
        )
        if (
            physical_profile
            and self.flags.enable_perception
            and self.tracking.camera_backend in {"synthetic", "null", "file"}
        ):
            raise ValueError(
                "physical perception requires a live camera backend"
            )
        return self


def load_config(config_dir: str | Path = "configs") -> Config:
    """Load default.yaml from a directory and return a Config object.

    Args:
        config_dir: Path to directory containing default.yaml.
                    Can be absolute or relative to CWD.

    Returns:
        Config with safety limits, flags, and CfC contract.
    """
    config_dir = Path(config_dir)
    default_path = config_dir / "default.yaml"

    if not default_path.exists():
        # Try relative to this package
        pkg_root = Path(__file__).resolve().parent.parent.parent
        default_path = pkg_root / "configs" / "default.yaml"

    with open(default_path) as f:
        raw = yaml.safe_load(f)

    return Config.model_validate(raw)


def merge_overrides(base: Config, override_path: str | Path) -> Config:
    """Merge an override yaml (sitl.yaml, flight.yaml) into a base config.

    Only top-level keys present in the override are replaced.
    """
    override_path = Path(override_path)
    if not override_path.exists():
        return base

    with open(override_path) as f:
        override_raw = yaml.safe_load(f)

    base_dict = base.model_dump()
    for key, val in override_raw.items():
        if key in base_dict and isinstance(val, dict) and isinstance(base_dict[key], dict):
            base_dict[key].update(val)
        else:
            base_dict[key] = val

    return Config.model_validate(base_dict)
