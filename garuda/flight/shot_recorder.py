"""
GarudaOne DroneOS — Cinematic Shot Recorder
==========================================
Turns the front camera stream into an actual movie file with a telemetry
burn-in, so "follow that man and take drone shots" produces something the
user can watch at the end.

Why this exists: the previous follow loop fetched a frame for YOLO and threw
it away. Detection frames ARE the shot frames — recording them costs one
cv2.imencode per frame and gives a synced, annotated, cinematic artifact.

Output per shot:
  shots/<session>/<shot_name>_<timestamp>.mp4   H.264-less (mp4v) video
  shots/<session>/<shot_name>_<timestamp>_telemetry.jsonl
                                                    one JSON line per frame

The telemetry sidecar is what makes the footage useful for debugging: bbox,
errors, avoidance decision, velocity actually commanded.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

log = logging.getLogger("shot_recorder")


@dataclass
class FrameTelemetry:
    """One recorded frame's worth of state."""

    t: float = 0.0
    locked: bool = False
    bbox: Optional[list[int]] = None
    confidence: float = 0.0
    err_x: float = 0.0
    err_y: float = 0.0
    h_ratio: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    yaw_rate: float = 0.0
    avoidance: str = "CLEAR"
    clear_m: float = 99.0
    locked_seconds: float = 0.0


@dataclass
class ShotStats:
    """Summary returned when a shot closes."""

    path: Optional[str] = None
    frames: int = 0
    seconds: float = 0.0
    lock_ratio: float = 0.0
    avoid_events: int = 0
    keyframes: list[str] = field(default_factory=list)


def _draw_hud(frame: np.ndarray, tel: FrameTelemetry, shot: str) -> np.ndarray:
    """Burn a compact telemetry overlay into the frame (best effort)."""
    try:
        import cv2
    except ImportError:
        return frame

    out = frame.copy()
    h, w = out.shape[:2]
    scale = max(0.4, w / 1280.0)
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = 1

    # Reticle
    cv2.drawMarker(out, (w // 2, h // 2), (0, 255, 255), cv2.MARKER_CROSS, 18, 1)

    # Target box
    if tel.bbox:
        x1, y1, x2, y2 = [int(v) for v in tel.bbox]
        colour = (0, 255, 0) if tel.locked else (0, 140, 255)
        cv2.rectangle(out, (x1, y1), (x2, y2), colour, 2)
        cv2.circle(out, ((x1 + x2) // 2, (y1 + y2) // 2), 4, colour, -1)
        cv2.putText(
            out, f"SUBJECT {tel.confidence*100:.0f}%", (x1, max(12, y1 - 8)),
            font, 0.45 * scale, colour, thickness, cv2.LINE_AA,
        )

    # Avoidance banner
    if tel.avoidance != "CLEAR":
        banner = f"AVOID {tel.avoidance}  {tel.clear_m:.1f}m"
        cv2.rectangle(out, (0, h - 26), (int(240 * scale), h), (0, 0, 180), -1)
        cv2.putText(
            out, banner, (6, h - 8), font, 0.45 * scale, (255, 255, 255),
            thickness, cv2.LINE_AA,
        )

    # Top strip: shot name, clock, lock, velocity
    strip = (
        f"{shot}  T{tel.t:6.1f}s  "
        f"{'LOCK' if tel.locked else 'SEARCH'} {tel.locked_seconds:5.1f}s  "
        f"v=({tel.vx:+.1f},{tel.vy:+.1f},{tel.vz:+.1f}) y={tel.yaw_rate:+.0f}"
    )
    cv2.rectangle(out, (0, 0), (w, int(20 * scale)), (0, 0, 0), -1)
    cv2.putText(
        out, strip, (6, int(15 * scale)), font, 0.42 * scale,
        (255, 255, 255), thickness, cv2.LINE_AA,
    )
    return out


class ShotRecorder:
    """
    Thread-unsafe, call-from-the-control-loop recorder.

    Usage per frame::

        rec.begin("follow_pedestrian_1")
        rec.capture(frame, telemetry)     # returns True if written
        stats = rec.end()
    """

    def __init__(
        self,
        out_dir: str | os.PathLike[str] = "shots",
        fps: int = 20,
        jpeg_quality: int = 88,
        keyframe_interval_s: float = 2.0,
    ) -> None:
        self.out_dir = Path(out_dir)
        self.fps = int(fps)
        self.jpeg_quality = int(jpeg_quality)
        self.keyframe_interval_s = float(keyframe_interval_s)

        self._writer: Any = None
        self._telemetry_fh: Any = None
        self._shot: Optional[str] = None
        self._path: Optional[Path] = None
        self._tel_path: Optional[Path] = None
        self._t0 = 0.0
        self._frames = 0
        self._locked_frames = 0
        self._last_lock_time: Optional[float] = None
        self._locked_seconds = 0.0
        self._avoid_events = 0
        self._last_avoid: Optional[str] = None
        self._last_keyframe = 0.0
        self._keyframes: list[str] = []
        self._session: Optional[str] = None

    # ── Lifecycle ──────────────────────────────────────────────────────

    def begin(self, shot: str, session: Optional[str] = None) -> Optional[str]:
        """Open a new shot. Returns the video path, or None if unavailable."""
        if self._writer is not None:
            log.warning("ShotRecorder.begin called while a shot is open — closing the previous one")
            self.end()

        try:
            import cv2  # noqa: F401
        except ImportError as e:
            log.error(f"ShotRecorder: OpenCV unavailable ({e}) — no video will be written")
            return None

        self._session = session or time.strftime("session_%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in shot) or "shot"
        stem = f"{safe}_{time.strftime('%H%M%S')}"
        shot_dir = self.out_dir / self._session
        shot_dir.mkdir(parents=True, exist_ok=True)

        self._path = shot_dir / f"{stem}.mp4"
        self._tel_path = shot_dir / f"{stem}_telemetry.jsonl"
        self._shot = shot
        self._t0 = time.time()
        self._frames = 0
        self._locked_frames = 0
        self._locked_seconds = 0.0
        self._last_lock_time = None
        self._avoid_events = 0
        self._last_avoid = None
        self._last_keyframe = 0.0
        self._keyframes = []
        self._writer = None
        self._telemetry_fh = None

        try:
            self._telemetry_fh = open(self._tel_path, "w", encoding="utf-8")
        except OSError as e:
            log.warning(f"ShotRecorder: cannot open telemetry sidecar ({e})")

        log.info(f"ShotRecorder: recording shot '{shot}' -> {self._path}")
        return str(self._path)

    def capture(self, frame: Optional[np.ndarray], tel: Optional[FrameTelemetry] = None) -> bool:
        """Encode and write one frame. Lazy-opens the writer on frame 0."""
        if self._shot is None or frame is None or getattr(frame, "size", 0) == 0:
            return False
        try:
            import cv2
        except ImportError:
            return False

        tel = tel or FrameTelemetry()
        tel.t = time.time() - self._t0
        tel.locked_seconds = self._locked_seconds

        if tel.locked:
            self._locked_frames += 1
            if self._last_lock_time is not None:
                self._locked_seconds += tel.t - self._last_lock_time
            self._last_lock_time = tel.t
        else:
            self._last_lock_time = None

        if tel.avoidance != "CLEAR":
            if self._last_avoid != tel.avoidance:
                self._avoid_events += 1
            self._last_avoid = tel.avoidance
        else:
            self._last_avoid = None

        if self._telemetry_fh is not None:
            try:
                self._telemetry_fh.write(json.dumps(asdict(tel), default=float) + "\n")
            except (OSError, TypeError, ValueError):
                pass

        annotated = _draw_hud(frame, tel, self._shot)

        if self._writer is None:
            h, w = annotated.shape[:2]
            # Even dimensions required by most codecs.
            w -= w % 2
            h -= h % 2
            fps = self.fps or 20
            self._writer = cv2.VideoWriter(
                str(self._path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                float(fps),
                (w, h),
            )
            if not self._writer.isOpened():
                log.error(f"ShotRecorder: VideoWriter failed to open {self._path}")
                self._writer = None
                return False
            log.info(f"ShotRecorder: writer opened {w}x{h} @ {fps}fps")

        try:
            self._writer.write(annotated)
        except Exception as e:  # codec hiccups must not kill the flight loop
            log.warning(f"ShotRecorder: frame write failed ({e})")
            return False

        self._frames += 1

        # Periodic keyframe so a good still is always recoverable.
        if tel.t - self._last_keyframe >= self.keyframe_interval_s:
            self._last_keyframe = tel.t
            try:
                kf = self._path.with_name(f"{self._path.stem}_t{tel.t:06.1f}.jpg")
                cv2.imwrite(str(kf), annotated, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                self._keyframes.append(str(kf))
            except Exception as e:
                log.debug(f"ShotRecorder: keyframe write failed ({e})")

        return True

    def end(self) -> ShotStats:
        """Close the shot and return its statistics."""
        if self._shot is None:
            return ShotStats()

        seconds = time.time() - self._t0
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception as e:
                log.debug(f"ShotRecorder: release failed ({e})")
        if self._telemetry_fh is not None:
            try:
                self._telemetry_fh.close()
            except OSError:
                pass

        stats = ShotStats(
            path=str(self._path) if self._path else None,
            frames=self._frames,
            seconds=round(seconds, 2),
            lock_ratio=round(self._locked_frames / self._frames, 3) if self._frames else 0.0,
            avoid_events=self._avoid_events,
            keyframes=self._keyframes,
        )
        log.info(
            f"ShotRecorder: shot '{self._shot}' closed — {stats.frames} frames / {stats.seconds}s, "
            f"lock ratio {stats.lock_ratio*100:.0f}%, {stats.avoid_events} avoidance events"
        )

        self._writer = None
        self._telemetry_fh = None
        self._shot = None
        self._path = None
        self._tel_path = None
        return stats

    @property
    def recording(self) -> bool:
        return self._shot is not None
