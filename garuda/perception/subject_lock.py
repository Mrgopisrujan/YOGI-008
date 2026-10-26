"""Identity preserving subject tracker with constant velocity coasting."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

log = logging.getLogger("subject_lock")


def _crop(frame: np.ndarray, bbox: list[int], pad: float = 0.15) -> Optional[np.ndarray]:
    if frame is None or frame.size == 0:
        return None
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = max(1, x2 - x1), max(1, y2 - y1)
    x1, x2 = int(max(0, x1 - pad * bw)), int(min(w, x2 + pad * bw))
    y1, y2 = int(max(0, y1 - pad * bh)), int(min(h, y2 + pad * bh))
    return frame[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else None


def _histogram(crop: Optional[np.ndarray], bins: int = 8) -> np.ndarray:
    if crop is None or crop.size == 0:
        return np.zeros(bins**3, dtype=np.float32)
    img = crop
    if img.ndim == 2:
        img = np.stack([img] * 3, axis=-1)
    hist = np.histogramdd(img.reshape(-1, 3), bins=bins,
                          range=[(0, 256)] * 3)[0]
    if hist.sum():
        hist /= hist.sum()
    return hist.astype(np.float32).ravel()


def _hist_distance(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0 or not a.any() or not b.any():
        return 1.0
    return float(np.sqrt(max(0.0, 1.0 - float(np.sum(np.sqrt(a * b))))))


def _centroid(bbox: list[int]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


class BoxKinematicEstimator:
    """Lightweight constant velocity estimator for image-space boxes.

    State is ``cx, cy, vx, vy, bw, bh`` in pixels and pixels per frame. The
    velocity and dimensions use exponential smoothing; ``position_variance``
    grows while coasting and defines the low-confidence detector gate.
    """

    def __init__(self, velocity_alpha: float = 0.55, size_alpha: float = 0.25):
        self.velocity_alpha = velocity_alpha
        self.size_alpha = size_alpha
        self.state: Optional[np.ndarray] = None
        self.position_variance = 16.0
        self._predicted = False

    @property
    def initialized(self) -> bool:
        return self.state is not None

    @property
    def velocity(self) -> tuple[float, float]:
        if self.state is None:
            return (0.0, 0.0)
        return float(self.state[2]), float(self.state[3])

    def predict(self) -> Optional[list[int]]:
        if self.state is None:
            return None
        self.state[0] += self.state[2]
        self.state[1] += self.state[3]
        self.position_variance = min(2500.0, self.position_variance + 12.0)
        self._predicted = True
        return self.bbox()

    def update(self, bbox: list[int]) -> None:
        x1, y1, x2, y2 = map(float, bbox)
        measured = np.array([(x1+x2)/2, (y1+y2)/2, 0., 0.,
                             max(1., x2-x1), max(1., y2-y1)], dtype=np.float64)
        if self.state is None:
            self.state = measured
        else:
            # If a prediction was made this frame, its center is the prior.
            # Otherwise use the previous filtered center as the prior.
            prior = self.state.copy()
            if not self._predicted:
                prior[0] += prior[2]
                prior[1] += prior[3]
            residual = measured[:2] - prior[:2]
            observed_velocity = residual
            self.state[0:2] = prior[0:2] + 0.72 * residual
            self.state[2:4] = ((1.0-self.velocity_alpha)*self.state[2:4]
                               + self.velocity_alpha*observed_velocity)
            self.state[4:6] = ((1.0-self.size_alpha)*self.state[4:6]
                               + self.size_alpha*measured[4:6])
        self.position_variance = max(9.0, self.position_variance * 0.45)
        self._predicted = False

    def bbox(self) -> Optional[list[int]]:
        if self.state is None:
            return None
        cx, cy, _, _, bw, bh = self.state
        return [int(round(cx-bw/2)), int(round(cy-bh/2)),
                int(round(cx+bw/2)), int(round(cy+bh/2))]

    def projected_bbox(self) -> Optional[list[int]]:
        """Return the next-frame box without mutating the estimator."""
        if self.state is None:
            return None
        state = self.state.copy()
        if not self._predicted:
            state[0] += state[2]
            state[1] += state[3]
        cx, cy, _, _, bw, bh = state
        return [int(round(cx-bw/2)), int(round(cy-bh/2)),
                int(round(cx+bw/2)), int(round(cy+bh/2))]

    def contains(self, bbox: list[int], sigma: float = 3.0) -> bool:
        if self.state is None:
            return False
        cx, cy = _centroid(bbox)
        projected = self.projected_bbox()
        assert projected is not None
        px, py = _centroid(projected)
        bh = max(1.0, float(self.state[5]))
        radius = max(80.0, 1.5 * bh, sigma * np.sqrt(self.position_variance))
        return bool(np.hypot(cx-px, cy-py) <= radius)


@dataclass
class LockState:
    locked: bool = False
    bbox: Optional[list[int]] = None
    confidence: float = 0.0
    lost_frames: int = 0
    reacquired: int = 0
    switches: int = 0
    err_x: float = 0.0
    err_y: float = 0.0
    h_ratio: float = 0.0
    lock_id: Optional[str] = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    tracking_state: str = "SEARCH"


class SubjectLock:
    """Single-target tracker; candidate association always preserves identity."""

    def __init__(self, max_motion_frac: float = 0.55,
                 max_hist_distance: float = 0.62, max_lost_frames: int = 10,
                 min_confidence: float = 0.30, max_coast_frames: Optional[int] = None,
                 low_confidence: float = 0.15, reid_hist_distance: float = 0.35):
        self._prev_bbox: Optional[list[int]] = None
        self._prev_hist: Optional[np.ndarray] = None
        self._anchor_hist: Optional[np.ndarray] = None
        self._anchor_aspect: Optional[float] = None
        self._prev_conf = 0.0
        self._lost = 0
        self._reacquired = 0
        self._switches = 0
        self._lock_id: Optional[str] = None
        self._max_motion_frac = max_motion_frac
        self._max_hist = max_hist_distance
        self._max_lost = max(0, max_lost_frames)
        self._max_coast = max(0, max_coast_frames if max_coast_frames is not None else max_lost_frames)
        self._min_conf = min_confidence
        self._low_conf = low_confidence
        self._reid_max = reid_hist_distance
        self.estimator = BoxKinematicEstimator()
        self._frame_shape: Optional[tuple[int, int]] = None
        self._mode = "SEARCH"
        self._last_result: Optional[dict[str, Any]] = None

    @property
    def tracking_state(self) -> str:
        return self._mode

    @property
    def velocity(self) -> tuple[float, float]:
        return self.estimator.velocity

    @property
    def lost_frames(self) -> int:
        return self._lost

    def reset(self) -> None:
        self._clear_track(clear_anchor=True)
        self._reacquired = 0
        self._switches = 0

    def _clear_track(self, clear_anchor: bool = False) -> None:
        self._prev_bbox = None
        self._prev_hist = None
        self._prev_conf = 0.0
        self._lost = 0
        self._lock_id = None
        self.estimator = BoxKinematicEstimator()
        self._mode = "SEARCH"
        self._last_result = None
        if clear_anchor:
            self._anchor_hist = None
            self._anchor_aspect = None

    def select(self, detections: list[dict[str, Any]],
               frame: Optional[np.ndarray] = None) -> Optional[dict[str, Any]]:
        """Legacy detection-only API. Use :meth:`update` to receive coast boxes."""
        result = self.update(detections, frame)
        if result is not None and result.get("tracking_state") == "LOCKED_PREDICTED":
            if self._lost > self._max_lost:
                self._clear_track(clear_anchor=True)
            return None
        if result is None and self._lost > self._max_lost:
            self._clear_track(clear_anchor=True)
        return result

    def update(self, detections: list[dict[str, Any]],
               frame: Optional[np.ndarray] = None) -> Optional[dict[str, Any]]:
        """Update from detections, returning a predicted result during COAST."""
        if frame is not None:
            self._frame_shape = frame.shape[:2]
        dets = [d for d in (detections or [])
                if float(d.get("confidence", 0.0)) >= self._low_conf]
        chosen = self._associate(dets, frame) if self.estimator.initialized else None
        if not self.estimator.initialized and dets:
            # Do not let a weak background proposal define the identity anchor.
            eligible = [d for d in dets
                        if float(d.get("confidence", 0.0)) >= self._min_conf]
            if eligible:
                chosen = self._bootstrap(eligible)

        if chosen is None:
            self._lost += 1
            predicted = self.estimator.predict()
            if predicted is not None and self._lost <= self._max_coast:
                self._mode = "COAST"
                result = dict(self._last_result or {})
                result.update(self._metrics(predicted))
                result["bbox"] = predicted
                result["confidence"] = self._prev_conf * max(0.0, 1.0-self._lost/(self._max_coast+1))
                result["tracking_state"] = "LOCKED_PREDICTED"
                result["predicted"] = True
                self._last_result = result
                return result
            self._mode = "SEARCH"
            return None

        reacquiring_from_search = self._mode == "SEARCH" and self._lost > self._max_coast
        if self._lost:
            self._reacquired += 1
        self._lost = 0
        self._mode = "LOCKED"
        self._prev_bbox = [int(v) for v in chosen["bbox"]]
        self._prev_conf = float(chosen.get("confidence", 0.0))
        if reacquiring_from_search:
            # Camera motion during a search sweep dominates image-space motion.
            # Start a fresh kinematic segment after appearance-verified re-ID.
            self.estimator = BoxKinematicEstimator()
        self.estimator.update(self._prev_bbox)
        hist = _histogram(_crop(frame, self._prev_bbox)) if frame is not None else None
        if hist is not None and hist.any():
            self._prev_hist = hist
            if self._anchor_hist is None and self._prev_conf >= self._min_conf:
                self._anchor_hist = hist.copy()
                x1, y1, x2, y2 = self._prev_bbox
                self._anchor_aspect = (x2-x1) / max(1.0, y2-y1)
        result = dict(chosen)
        result["identity"] = self._lock_id
        result["tracking_state"] = "LOCKED"
        result["predicted"] = False
        self._last_result = result
        return result

    def state(self, current: Optional[dict[str, Any]] = None) -> LockState:
        current = current or self._last_result
        if current is None:
            return LockState(lost_frames=self._lost, reacquired=self._reacquired,
                             switches=self._switches, lock_id=self._lock_id,
                             tracking_state=self._mode)
        return LockState(locked=True, bbox=list(current["bbox"]),
                         confidence=float(current.get("confidence", 0.0)),
                         lost_frames=self._lost, reacquired=self._reacquired,
                         switches=self._switches,
                         err_x=float(current.get("err_x", 0.0)),
                         err_y=float(current.get("err_y", 0.0)),
                         h_ratio=float(current.get("h_ratio", 0.0)),
                         lock_id=self._lock_id,
                         tracking_state=current.get("tracking_state", self._mode))

    def _bootstrap(self, dets: list[dict[str, Any]]) -> dict[str, Any]:
        chosen = max(dets, key=lambda d: float(d.get("confidence", 0.0)) *
                     (0.5 + float(d.get("h_ratio", 0.0))))
        self._lock_id = f"lock@{id(chosen) % 100000}"
        log.info("SubjectLock: initial acquisition")
        return chosen

    def _metrics(self, bbox: list[int]) -> dict[str, float]:
        x1, y1, x2, y2 = bbox
        h, w = self._frame_shape or (1, 1)
        cx, cy = (x1+x2)/2, (y1+y2)/2
        bw, bh = max(1, x2-x1), max(1, y2-y1)
        return {"centroid": (cx, cy), "err_x": (cx-w/2)/(w/2),
                "err_y": (cy-h/2)/(h/2), "h_ratio": bh/h,
                "w_ratio": bw/w, "area_ratio": bw*bh/(w*h)}

    def _associate(self, dets: list[dict[str, Any]],
                   frame: Optional[np.ndarray]) -> Optional[dict[str, Any]]:
        if not dets:
            return None
        was_lost = self._lost > 0 or self._mode == "SEARCH"
        scored: list[tuple[float, dict[str, Any]]] = []
        pred = self.estimator.projected_bbox()
        assert pred is not None
        pcx, pcy = _centroid(pred)
        pbw, pbh = max(1, pred[2]-pred[0]), max(1, pred[3]-pred[1])
        gate = max(80.0, 1.5 * pbh, 0.10*self._max_motion_frac*(pcx+pbh),
                   3.0*np.sqrt(self.estimator.position_variance))

        # Single candidate in scene: associate directly if within gate and appearance matches
        if len(dets) == 1:
            d = dets[0]
            bbox = [int(v) for v in d["bbox"]]
            cx, cy = _centroid(bbox)
            dist = float(np.hypot(cx-pcx, cy-pcy))
            low = float(d.get("confidence", 0.0)) < self._min_conf
            if not (low and not self.estimator.contains(bbox)):
                cand_hist = _histogram(_crop(frame, bbox)) if frame is not None else None
                hist_dist = (
                    _hist_distance(self._anchor_hist, cand_hist)
                    if (self._anchor_hist is not None and cand_hist is not None)
                    else 0.0
                )
                max_allowed_hist = max(0.50, self._reid_max) if was_lost else 0.85
                if dist <= max(gate, 350.0) and hist_dist <= max_allowed_hist:
                    return d

        for d in dets:
            bbox = [int(v) for v in d["bbox"]]
            cx, cy = _centroid(bbox)
            dist = float(np.hypot(cx-pcx, cy-pcy))
            low = float(d.get("confidence", 0.0)) < self._min_conf
            if low and not self.estimator.contains(bbox):
                continue
            if dist > gate and not (was_lost and self._anchor_hist is not None and not low):
                continue
            cand_hist = _histogram(_crop(frame, bbox)) if frame is not None else None
            if was_lost and self._anchor_hist is not None:
                if cand_hist is None or _hist_distance(self._anchor_hist, cand_hist) >= max(0.50, self._reid_max):
                    continue
                if self._anchor_aspect is not None:
                    aspect = (bbox[2]-bbox[0])/max(1., bbox[3]-bbox[1])
                    if abs(aspect-self._anchor_aspect) > 0.45:
                        continue
            elif cand_hist is not None and self._prev_hist is not None:
                if _hist_distance(self._prev_hist, cand_hist) > max(0.65, self._max_hist):
                    continue
            # Confidence is only a tie-breaker. Geometry selects the original track.
            score = -dist/max(gate, 1.0) + 0.08*float(d.get("confidence", 0.0))
            scored.append((score, d))
        return max(scored, key=lambda item: item[0])[1] if scored else None
