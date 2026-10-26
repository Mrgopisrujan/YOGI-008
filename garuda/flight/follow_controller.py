"""
GarudaOne DroneOS — Cinematic Follow Controller
==============================================
The closed loop that makes "hey Garuda, follow that man" actually work:

    frame -> YOLO persons -> SubjectLock (identity) -> ShotSpec (framing)
          -> control law (body velocity) -> ObstacleAvoider (veto)
          -> airsim velocity command -> ShotRecorder (video + telemetry)

Kept free of AirSim imports on purpose: the controller talks to a
``FlightBackend`` protocol, so the whole loop can be exercised in tests with
a stub backend and synthetic frames. AirSimClient satisfies the protocol
without knowing this module exists.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

import numpy as np

from garuda.flight.avoidance import AvoidanceDecision, ObstacleAvoider
from garuda.flight.shot_planner import FOLLOW, ShotDirector, ShotSpec
from garuda.flight.shot_recorder import FrameTelemetry, ShotRecorder, ShotStats
from garuda.perception.subject_lock import SubjectLock

log = logging.getLogger("follow_controller")


class FlightBackend(Protocol):
    """Minimal surface the follow loop needs from a flight layer."""

    def get_forward_camera(self) -> Optional[np.ndarray]: ...
    def get_forward_depth(self) -> Optional[np.ndarray]: ...
    def get_telemetry(self) -> dict[str, Any]: ...
    def is_in_air(self) -> bool: ...
    def takeoff(self, altitude_m: float = 3.0) -> Any: ...
    def move_velocity_body(
        self, vx: float, vy: float, vz: float, yaw_rate_dps: float, duration_s: float = 0.2
    ) -> Any: ...
    def hover(self) -> Any: ...


@dataclass
class FollowGains:
    """Control-law gains. Defaults tuned for a 90° FOV 640x480 camera."""

    yaw_kp: float = 2.6              # deg/s per unit normalised x error
    yaw_max_dps: float = 32.0
    yaw_deadband: float = 0.04
    vz_kp: float = 1.1               # m/s per unit normalised y error
    vz_max: float = 0.9
    vz_deadband: float = 0.05
    # Distance control: proportional approach on apparent size error.
    approach_kp: float = 3.2         # m/s per unit size error
    approach_max: float = 2.5
    # Vertical framing bias: hold the subject slightly above centre.
    framing_y_offset: float = -0.10
    # Orbit tangential speed cap (m/s).
    orbit_max: float = 1.6
    # Command duration per control tick (s).
    tick_s: float = 0.20


@dataclass
class FollowTelemetry:
    """Everything the loop measured on its most recent tick."""

    tick: int = 0
    elapsed_s: float = 0.0
    shot: str = "follow"
    locked: bool = False
    conf: float = 0.0
    bbox: Optional[list[int]] = None
    err_x: float = 0.0
    err_y: float = 0.0
    h_ratio: float = 0.0
    size_error: float = 0.0
    standoff_m: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    yaw_rate: float = 0.0
    avoidance: str = "CLEAR"
    clear_m: float = 99.0
    lock_ratio: float = 0.0
    reacquisitions: int = 0
    identity_switches: int = 0
    events: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "elapsed_s": round(self.elapsed_s, 2),
            "shot": self.shot,
            "locked": self.locked,
            "conf": round(self.conf, 3),
            "err_x": round(self.err_x, 3),
            "err_y": round(self.err_y, 3),
            "h_ratio": round(self.h_ratio, 3),
            "standoff_m": round(self.standoff_m, 2),
            "cmd": {
                "vx": round(self.vx, 2),
                "vy": round(self.vy, 2),
                "vz": round(self.vz, 2),
                "yaw_rate": round(self.yaw_rate, 1),
            },
            "avoidance": self.avoidance,
            "clear_m": round(self.clear_m, 2),
            "lock_ratio": round(self.lock_ratio, 3),
        }


class FollowController:
    """
    Drives a drone to follow a person, framed as a cinematic shot, while
    avoiding obstacles and recording the result.

    Example::

        fc = FollowController(backend=AirSimClient(), detector=YoloDetector())
        fc.begin("follow", ShotSpec(name="follow"))
        while fc.active:
            tel = fc.tick()
    """

    def __init__(
        self,
        backend: FlightBackend,
        detector: Any,
        spec: ShotSpec = FOLLOW,
        avoider: Optional[ObstacleAvoider] = None,
        lock: Optional[SubjectLock] = None,
        recorder: Optional[ShotRecorder] = None,
        director: Optional[ShotDirector] = None,
        gains: Optional[FollowGains] = None,
        on_event: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.backend = backend
        self.detector = detector
        self.spec = spec
        self.avoider = avoider or ObstacleAvoider()
        self.lock = lock or SubjectLock()
        self.recorder = recorder or ShotRecorder()
        self.director = director or ShotDirector()
        self.gains = gains or FollowGains()
        self._on_event = on_event

        self._active = False
        self._t0 = 0.0
        self._tick = 0
        self._locked_ticks = 0
        self._events: list[str] = []
        self._last_tel = FollowTelemetry()

    # ── Lifecycle ──────────────────────────────────────────────────────

    def begin(
        self,
        command: str = "",
        spec: Optional[ShotSpec] = None,
        duration_s: float = 20.0,
        auto_takeoff: bool = True,
        takeoff_altitude_m: float = 3.0,
        record: Optional[bool] = None,
    ) -> ShotSpec:
        """
        Start a follow shot.

        Shot resolution order: explicit ``spec`` > ``command`` text > the spec
        the controller was constructed with. Passing ``command=""`` therefore
        reuses the construction-time shot instead of silently reverting to the
        default follow shot.
        """
        if spec is not None:
            self.spec = spec
        elif command:
            self.spec = self.director.parse(command)
        self.lock.reset()
        self._t0 = time.time()
        self._tick = 0
        self._locked_ticks = 0
        self._events = []
        self._active = True

        if auto_takeoff and not self.backend.is_in_air():
            self._emit(f"auto-takeoff to {takeoff_altitude_m:.1f}m")
            self.backend.takeoff(altitude_m=takeoff_altitude_m)
            time.sleep(2.0)  # let the airframe settle before the first frame

        should_record = self.spec.record if record is None else record
        if should_record:
            path = self.recorder.begin(self.spec.name)
            if path:
                self._emit(f"recording -> {path}")
            else:
                self._emit("recording unavailable (OpenCV missing) — flying unrecorded")

        self._emit(f"shot armed: {self.spec.describe()}")
        log.info(f"FollowController: begin '{command}' -> {self.spec.describe()}")
        return self.spec

    def end(self, reason: str = "complete") -> ShotStats:
        """Stop the shot, hover, and close the recording."""
        self._active = False
        stats = self.recorder.end()
        try:
            self.backend.hover()
        except Exception as e:
            log.debug(f"FollowController: hover on stop failed ({e})")
        st = self.lock.state()
        self._emit(
            f"{reason}: {self._tick} ticks, lock ratio "
            f"{self._locked_ticks/max(1,self._tick)*100:.0f}%, {st.switches} identity switches"
        )
        return stats

    @property
    def active(self) -> bool:
        return self._active

    @property
    def telemetry(self) -> FollowTelemetry:
        return self._last_tel

    def elapsed(self) -> float:
        return time.time() - self._t0 if self._t0 else 0.0

    # ── Control tick ───────────────────────────────────────────────────

    def tick(self) -> FollowTelemetry:
        """Run one perception→control iteration. Returns its telemetry."""
        if not self._active:
            return self._last_tel

        self._tick += 1
        now = time.time()
        tel = FollowTelemetry(tick=self._tick, elapsed_s=now - self._t0, shot=self.spec.name)

        # 1 ── Perception
        frame = self.backend.get_forward_camera()
        detections = []
        if frame is not None and self.detector is not None:
            try:
                detections = self.detector.detect_persons(frame) or []
            except Exception as e:
                log.warning(f"FollowController: detector failure ({e})")
                detections = []

        # 2 ── Identity: which of these is "that man"?
        target = self.lock.select(detections, frame)

        if target is None:
            # 3a ── Search: hold position and sweep, do not servo a ghost.
            tel.locked = False
            tel.avoidance = self._safe_hover(tel)
            self._maybe_record(frame, tel)
            self._last_tel = tel
            return tel

        self._locked_ticks += 1
        tel.locked = True
        tel.conf = float(target.get("confidence", 0.0))
        tel.bbox = [int(v) for v in target["bbox"]]
        tel.err_x = float(target.get("err_x", 0.0))
        tel.err_y = float(target.get("err_y", 0.0))
        tel.h_ratio = float(target.get("h_ratio", 0.0))

        # 4 ── Control law in the camera frame.
        vx, vy, vz, yaw_rate = self._control_law(tel)

        # 5 ── Avoidance veto.
        depth = None
        try:
            depth = self.backend.get_forward_depth()
        except Exception as e:
            log.debug(f"FollowController: depth read failed ({e})")
        decision: AvoidanceDecision = (
            self.avoider.evaluate_depth(depth) if depth is not None else self.avoider.evaluate_distance(99.0)
        )
        tel.avoidance = decision.status
        tel.clear_m = decision.clear_m
        if decision.status != "CLEAR":
            self._emit(f"{decision.status}: {decision.reason}")

        vx, vy, vz = self.avoider.apply(vx, vy, vz, decision)

        # 6 ── Command the airframe.
        try:
            self.backend.move_velocity_body(
                vx=vx, vy=vy, vz=vz, yaw_rate_dps=yaw_rate, duration_s=self.gains.tick_s
            )
        except Exception as e:
            log.warning(f"FollowController: velocity command failed ({e})")

        # 6b ── Shot pitch bias (low/high angle shots). Optional on the backend.
        if abs(self.spec.pitch_bias_deg) > 1e-3:
            try:
                self.backend.set_camera_pitch(self.spec.pitch_bias_deg)  # type: ignore[attr-defined]
            except Exception:
                pass

        tel.vx, tel.vy, tel.vz, tel.yaw_rate = vx, vy, vz, yaw_rate
        tel.size_error = tel.h_ratio - self.spec.target_h_ratio
        st = self.lock.state(target)
        tel.reacquisitions = st.reacquired
        tel.identity_switches = st.switches
        tel.lock_ratio = self._locked_ticks / max(1, self._tick)

        self._maybe_record(frame, tel)
        self._last_tel = tel
        return tel

    # ── Internals ──────────────────────────────────────────────────────

    def _control_law(self, tel: FollowTelemetry) -> tuple[float, float, float, float]:
        g = self.gains
        spec = self.spec

        # Yaw: centre the subject horizontally. Deadband first so a
        # perfectly framed subject does not induce constant micro-yawing.
        ex = tel.err_x
        ex_eff = ex - math.copysign(g.yaw_deadband, ex) if abs(ex) > g.yaw_deadband else 0.0
        yaw = float(np.clip(ex_eff * g.yaw_kp, -g.yaw_max_dps, g.yaw_max_dps))

        # Vertical: hold the subject slightly above centre so there is headroom
        # in frame — the classic cinematic framing rule.
        ey = tel.err_y - g.framing_y_offset
        vz = float(np.clip(ey * g.vz_kp, -g.vz_max, g.vz_max))
        if abs(ey) < g.vz_deadband:
            vz = 0.0

        # Forward: close the gap on apparent size.
        size_err = spec.target_h_ratio - tel.h_ratio   # >0 => too far => advance
        vx = float(np.clip(size_err * g.approach_kp, -g.approach_max, g.approach_max))
        if size_err > 0:
            vx = min(vx, spec.max_speed_mps)
        else:
            vx = max(vx, -min(g.approach_max, 1.0))     # never reverse hard

        # Orbit tangential component.
        if abs(spec.orbit_rate_dps) > 1e-3:
            omega = np.deg2rad(spec.orbit_rate_dps)
            radius = max(1.0, self._standoff_estimate(tel))
            vy_orbit = float(np.clip(omega * radius, -g.orbit_max, g.orbit_max))
        else:
            vy_orbit = 0.0

        # Composition: lateral bias + orbit.
        vy = vy_orbit + spec.lateral_bias

        return vx, float(vy), float(vz), yaw

    def _standoff_estimate(self, tel: FollowTelemetry) -> float:
        """
        Rough metric distance from apparent size, calibrated for a 1.7 m
        standing adult filling ``h_ratio`` of a 90°-FOV frame.
        """
        if tel.h_ratio <= 1e-3:
            return self.spec.standoff_m
        return float(np.clip(1.7 / (tel.h_ratio * 2.0), 0.8, 40.0))

    def _safe_hover(self, tel: FollowTelemetry) -> str:
        """No target: hold station. Never keep the last velocity."""
        try:
            self.backend.move_velocity_body(
                vx=0.0, vy=0.0, vz=0.0, yaw_rate_dps=0.0, duration_s=self.gains.tick_s
            )
        except Exception:
            try:
                self.backend.hover()
            except Exception:
                pass
        tel.vx = tel.vy = tel.vz = tel.yaw_rate = 0.0
        return "CLEAR"

    def _maybe_record(self, frame: Optional[np.ndarray], tel: FollowTelemetry) -> None:
        if not self.recorder.recording or frame is None:
            return
        self.recorder.capture(
            frame,
            FrameTelemetry(
                t=tel.elapsed_s,
                locked=tel.locked,
                bbox=tel.bbox,
                confidence=tel.conf,
                err_x=tel.err_x,
                err_y=tel.err_y,
                h_ratio=tel.h_ratio,
                vx=tel.vx,
                vy=tel.vy,
                vz=tel.vz,
                yaw_rate=tel.yaw_rate,
                avoidance=tel.avoidance,
                clear_m=tel.clear_m,
            ),
        )

    def _emit(self, message: str) -> None:
        line = f"[{self.elapsed():6.1f}s] {message}"
        self._events.append(line)
        log.info(f"FollowController: {message}")
        if self._on_event:
            try:
                self._on_event(line)
            except Exception:
                pass
