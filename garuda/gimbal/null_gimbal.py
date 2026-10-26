"""NullGimbal — no-op gimbal backend for SITL and dev.

Mirrors StubDetector (perception/detector.py) and NullTof
(perception/tof.py): every method is a no-op and heartbeat_ok is always
True so the FSM never trips the "gimbal_heartbeat_lost" watchdog. Used
when feature_flags.allow_track_without_gimbal is true or when no hardware
gimbal is attached (SITL, CI, bench dev).

This backend performs no I/O and holds no resources — safe to construct
on Windows dev machines and in pytest.
"""

from __future__ import annotations

import time

from .protocol import GimbalBackend, GimbalStatus


class NullGimbal(GimbalBackend):
    """No-op gimbal for SITL / dev / CI.

    - set_pitch_yaw / set_roi: discard the command, record last values
      so get_status() returns something sensible for diagnostics.
    - heartbeat_ok: always True (no hardware to lose).
    - get_status: returns a GimbalStatus reflecting the last command.
    """

    def __init__(self, heartbeat_timeout_s: float | None = None) -> None:
        # Pass through so the timeout attribute is set, though we never
        # actually use it — NullGimbal is always healthy.
        super().__init__(heartbeat_timeout_s=heartbeat_timeout_s)
        self._mode = "idle"
        self._call_count: int = 0

    @property
    def name(self) -> str:
        return "null"

    def set_pitch_yaw(self, pitch_deg: float, yaw_rate_dps: float = 0.0) -> None:
        # Record the requested values for status reporting; do nothing else.
        self._last_pitch_deg = float(pitch_deg)
        self._last_yaw_rate_dps = float(yaw_rate_dps)
        self._mode = "pitch_yaw"
        self._roi_active = False
        self._call_count += 1
        self._mark_heartbeat()

    def set_roi(self, lat: float, lon: float, alt: float) -> None:
        # No-op — but remember that a ROI was requested.
        self._mode = "roi"
        self._roi_active = True
        self._last_roi = (float(lat), float(lon), float(alt))
        self._call_count += 1
        self._mark_heartbeat()

    def get_status(self) -> GimbalStatus:
        return GimbalStatus(
            pitch_deg=self._last_pitch_deg,
            yaw_deg=0.0,  # NullGimbal has no yaw encoder
            yaw_rate_dps=self._last_yaw_rate_dps,
            mode=self._mode,
            roi_active=self._roi_active,
            heartbeat_ok=True,
            last_heartbeat_ts=time.monotonic(),
            backend=self.name,
        )

    def heartbeat_ok(self) -> bool:
        # Always healthy — there is no hardware to fail.
        return True
