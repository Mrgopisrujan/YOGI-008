"""Gimbal backend protocol — pitch/yaw and ROI control abstraction.

GarudaOne controls a Skydroid C10 Pro 1080p25 gimbal camera (MAVLink),
with an alternative SIYI UART path and a no-op NullGimbal for SITL/dev.

Protocol contract (GimbalBackend):
    - set_pitch_yaw(pitch_deg, yaw_rate_dps): body-frame pointing
    - set_roi(lat, lon, alt): earth-frame point to track
    - get_status(): GimbalStatus snapshot (angles, mode, heartbeat)
    - heartbeat_ok: alive indicator for the FSM watchdog
    - name: backend identifier for diagnostics

Safety contract (from arbiter/safety_limits.py GimbalLimits):
    heartbeat_timeout_s = 1.0
    on_loss             = "freeze_and_disable_counter_rotation"

On heartbeat loss, the arbiter FSM (fsm.py event "gimbal_heartbeat_lost")
transitions to HOVER and disables counter-rotation. Each backend's
heartbeat_ok() must return False once no telemetry has arrived within
heartbeat_timeout_s. The arbiter is the sole authority for the freeze
action — backends only report health and stop sending new setpoints.

Pattern follows perception/detector.py (DetectorBackend) and
perception/tof.py (TofSource ABC + heartbeat_ok).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class GimbalStatus:
    """Snapshot of gimbal state reported by get_status()."""
    pitch_deg: float = 0.0          # current pitch angle (deg)
    yaw_deg: float = 0.0            # current yaw angle relative to vehicle body (deg)
    yaw_rate_dps: float = 0.0       # last commanded yaw rate (deg/s)
    mode: str = "idle"              # "idle" | "pitch_yaw" | "roi" | "follow" | "lost"
    roi_active: bool = False        # True if a ROI lock command is in effect
    heartbeat_ok: bool = False      # last evaluated heartbeat
    last_heartbeat_ts: float = field(default_factory=time.monotonic)
    backend: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "pitch_deg": self.pitch_deg,
            "yaw_deg": self.yaw_deg,
            "yaw_rate_dps": self.yaw_rate_dps,
            "mode": self.mode,
            "roi_active": self.roi_active,
            "heartbeat_ok": self.heartbeat_ok,
            "last_heartbeat_ts": self.last_heartbeat_ts,
            "backend": self.backend,
        }


@runtime_checkable
class GimbalBackendProtocol(Protocol):
    """Structural protocol all gimbal backends satisfy (runtime-checkable)."""

    def set_pitch_yaw(self, pitch_deg: float, yaw_rate_dps: float = 0.0) -> None:
        ...

    def set_roi(self, lat: float, lon: float, alt: float) -> None:
        ...

    def get_status(self) -> GimbalStatus:
        ...

    def heartbeat_ok(self) -> bool:
        ...

    @property
    def name(self) -> str:
        ...


class GimbalBackend(ABC):
    """Abstract base class for gimbal backends.

    Subclasses implement the hardware-specific transport (MAVLink, UART,
    none). The base provides the heartbeat bookkeeping helpers so every
    backend uses the same timeout semantics, matching the
    safety_limits.GimbalLimits contract (default 1.0 s).

    Implementations:
    - NullGimbal:   no-op for SITL/dev (heartbeat always True)
    - SkydroidGimbal: MAVLink gimbal manager (Skydroid C10 Pro)
    - SiyiGimbal:   SIYI UART serial protocol (alternative hardware)
    """

    #: Heartbeat timeout in seconds — defaults to GimbalLimits.heartbeat_timeout_s.
    #: Override per backend or via constructor if a vendor specifies otherwise.
    HEARTBEAT_TIMEOUT_S: float = 1.0

    def __init__(self, heartbeat_timeout_s: float | None = None) -> None:
        self._heartbeat_timeout_s: float = (
            heartbeat_timeout_s if heartbeat_timeout_s is not None
            else self.HEARTBEAT_TIMEOUT_S
        )
        self._last_heartbeat_ts: float = time.monotonic()
        self._last_pitch_deg: float = 0.0
        self._last_yaw_rate_dps: float = 0.0
        self._mode: str = "idle"
        self._roi_active: bool = False

    # ─── Abstract API ────────────────────────────────────────────────────

    @abstractmethod
    def set_pitch_yaw(self, pitch_deg: float, yaw_rate_dps: float = 0.0) -> None:
        """Point the gimbal. Body-frame pitch (deg) + yaw rate (deg/s).

        pitch_deg:   -90 (straight down) to +30 (above horizon). Clamped by backend.
        yaw_rate_dps: body-frame yaw rate command. 0 = hold current heading.
        """
        ...

    @abstractmethod
    def set_roi(self, lat: float, lon: float, alt: float) -> None:
        """Point the gimbal at an earth-frame coordinate (ROI lock).

        lat, lon: WGS84 decimal degrees.
        alt:      altitude AMSL in meters.
        """
        ...

    @abstractmethod
    def get_status(self) -> GimbalStatus:
        """Return a snapshot of current gimbal state."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier, e.g. 'null', 'skydroid', 'siyi'."""
        ...

    # ─── Heartbeat bookkeeping (shared) ──────────────────────────────────

    def _mark_heartbeat(self) -> None:
        """Call from a subclass when a valid telemetry/ack arrives."""
        self._last_heartbeat_ts = time.monotonic()

    def heartbeat_ok(self) -> bool:
        """True if a heartbeat has arrived within the timeout window.

        Default implementation uses monotonic time since _mark_heartbeat().
        Subclasses with no telemetry source (NullGimbal) override this.
        """
        age = time.monotonic() - self._last_heartbeat_ts
        return age <= self._heartbeat_timeout_s

    # ─── Convenience for subclasses ──────────────────────────────────────

    def _freeze(self) -> None:
        """On heartbeat loss: stop accepting new motion commands.

        Per safety_limits GimbalLimits.on_loss =
        "freeze_and_disable_counter_rotation": the gimbal holds its last
        attitude and stops issuing yaw-rate commands that would counter
        vehicle rotation. The arbiter additionally forces HOVER; this
        method only freezes the gimbal itself.
        """
        self._mode = "lost"
        self._roi_active = False
        self._last_yaw_rate_dps = 0.0

    @property
    def heartbeat_timeout_s(self) -> float:
        return self._heartbeat_timeout_s
