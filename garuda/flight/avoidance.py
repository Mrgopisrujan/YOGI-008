"""
GarudaOne DroneOS — Reactive Obstacle Avoidance
==============================================
Converts a depth map (or a coarse distance reading) into a safe velocity
command. This is the layer that makes "follow that man" survivable in a city:
subject tracking will happily steer the drone into a wall if nothing vetoes
the command.

Design constraints:
  * Works on a depth image at ~10 Hz, so it must be cheap NumPy only.
  * Must be *reactive*, not a path planner — it vetoes and biases the
    tracking velocity rather than replacing it.
  * Must fail safe: if the depth map is missing or malformed, it returns a
    conservative command (slow down), never a permissive one.

Three behaviours, in priority order:
  1. STOP   — obstacle inside the hard stop distance: kill forward velocity,
     keep the drone stable so the subject can walk out of the way.
  2. BRAKE  — obstacle inside the warning distance: scale forward velocity
     down proportionally to the clearance.
  3. YIELD  — obstacle in the approach cone but outside the stop distance:
     bias the drone to strafe toward the clearer side instead of forward.

The ``sector`` split (left / centre / right) is what makes YIELD possible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

log = logging.getLogger("avoidance")


@dataclass
class AvoidanceDecision:
    """Result of one avoidance evaluation."""

    forward_scale: float = 1.0      # multiplier on commanded forward speed
    strafe_bias: float = 0.0        # -1 = strafe left, +1 = strafe right
    vertical_bias: float = 0.0      # -1 = descend, +1 = climb
    hard_stop: bool = False         # full stop asserted
    reason: str = "clear"
    clear_m: float = 99.0           # nearest obstacle in the approach cone
    left_m: float = 99.0
    right_m: float = 99.0
    depth_valid: bool = True

    @property
    def status(self) -> str:
        if self.hard_stop:
            return "STOP"
        if self.forward_scale < 0.999:
            return "BRAKE"
        if abs(self.strafe_bias) > 1e-3 or abs(self.vertical_bias) > 1e-3:
            return "YIELD"
        return "CLEAR"


def _sector_min(
    depth: np.ndarray, x0: float, x1: float, y0: float, y1: float, zmax: float = 80.0
) -> float:
    """Min valid depth inside a fractional sector; 99.0 when empty/invalid."""
    if depth is None or depth.size == 0:
        return 99.0
    h, w = depth.shape[:2]
    xs, xe = int(x0 * w), int(x1 * w)
    ys, ye = int(y0 * h), int(y1 * h)
    xs, xe = max(0, min(xs, w - 1)), max(0, min(xe, w - 1))
    ys, ye = max(0, min(ys, h - 1)), max(0, min(ye, h - 1))
    if xe <= xs or ye <= ys:
        return 99.0
    sector = depth[ys:ye, xs:xe]
    valid = sector[(sector > 0.2) & (sector < zmax)]
    if valid.size == 0:
        return 99.0
    return float(np.min(valid))


class ObstacleAvoider:
    """
    Depth-based reactive avoidance for close-quarters urban flight.

    Parameters mirror physical airframe limits:
      stop_distance_m    — below this, forward motion is forbidden
      warning_distance_m — below this, forward motion is progressively cut
      corridor_frac      — horizontal fraction of the FOV treated as the
                            "approach cone" ahead of the nose
    """

    def __init__(
        self,
        stop_distance_m: float = 1.8,
        warning_distance_m: float = 4.0,
        corridor_frac: float = 0.34,
        max_strafe_mps: float = 1.5,
        max_vertical_mps: float = 0.8,
    ) -> None:
        if stop_distance_m >= warning_distance_m:
            raise ValueError("stop_distance_m must be < warning_distance_m")
        self.stop_m = float(stop_distance_m)
        self.warn_m = float(warning_distance_m)
        self.corridor = float(corridor_frac)
        self.max_strafe = float(max_strafe_mps)
        self.max_vertical = float(max_vertical_mps)

    # ── Depth-map API (preferred) ──────────────────────────────────────

    def evaluate_depth(self, depth: np.ndarray) -> AvoidanceDecision:
        """
        Evaluate a full depth image. Sectors are horizontal thirds of the
        central vertical band (the band where real obstacles live; the very
        top rows are usually sky/ceiling and the bottom rows are usually the
        ground directly under the drone).
        """
        if depth is None or getattr(depth, "size", 0) == 0:
            return self._invalid()

        c = self.corridor
        centre = _sector_min(depth, 0.5 - c / 2, 0.5 + c / 2, 0.25, 0.75)
        left = _sector_min(depth, 0.0, 0.5 - c / 2, 0.25, 0.75)
        right = _sector_min(depth, 0.5 + c / 2, 1.0, 0.25, 0.75)

        if centre >= 98.0 and left >= 98.0 and right >= 98.0:
            # Nothing valid in the band at all — treat as unusable, not clear.
            return self._invalid(clear=centre, left=left, right=right)

        return self._decide(centre, left, right)

    # ── Scalar API (fallback when only a coarse distance is available) ──

    def evaluate_distance(self, forward_m: float) -> AvoidanceDecision:
        """Evaluate from a single forward distance reading (e.g. ToF)."""
        d = float(forward_m) if forward_m is not None else 99.0
        if d >= 98.0:
            return self._invalid(clear=d)
        return self._decide(d, 99.0, 99.0)

    # ── Internals ──────────────────────────────────────────────────────

    def _invalid(self, clear: float = 99.0, left: float = 99.0, right: float = 99.0) -> AvoidanceDecision:
        # Fail safe: assume an obstacle just outside the stop threshold and
        # creep forward, so a dead depth sensor degrades to a slow cautious
        # hover rather than a full-speed crash.
        log.warning("Avoidance: depth data invalid — falling back to cautious creep")
        return AvoidanceDecision(
            forward_scale=0.0,
            hard_stop=True,
            reason="depth_invalid",
            clear_m=clear,
            left_m=left,
            right_m=right,
            depth_valid=False,
        )

    def _decide(self, centre: float, left: float, right: float) -> AvoidanceDecision:
        dec = AvoidanceDecision(clear_m=round(centre, 2), left_m=round(left, 2), right_m=round(right, 2))

        if centre < self.stop_m:
            dec.hard_stop = True
            dec.forward_scale = 0.0
            dec.reason = f"obstacle_{centre:.2f}m_within_stop_{self.stop_m:.2f}m"
            # Bias away from the closer flank so the drone slides around the
            # obstacle instead of stalling dead in front of it.
            if right > left:
                dec.strafe_bias = 1.0
            elif left > right:
                dec.strafe_bias = -1.0
            return dec

        if centre < self.warn_m:
            span = max(1e-3, self.warn_m - self.stop_m)
            scale = (centre - self.stop_m) / span      # 0 at stop, 1 at warn
            dec.forward_scale = float(np.clip(scale, 0.0, 1.0))
            dec.reason = f"braking_obstacle_{centre:.2f}m"
            if right > left + 0.8:
                dec.strafe_bias = 0.5
            elif left > right + 0.8:
                dec.strafe_bias = -0.5
            return dec

        dec.forward_scale = 1.0
        dec.reason = "clear"
        return dec

    def apply(
        self,
        vx: float,
        vy: float = 0.0,
        vz: float = 0.0,
        decision: Optional[AvoidanceDecision] = None,
    ) -> tuple[float, float, float]:
        """Scale a body-frame velocity command by an avoidance decision."""
        if decision is None:
            return vx, vy, vz
        out_vx = vx * decision.forward_scale
        out_vy = vy + decision.strafe_bias * self.max_strafe * (0.35 if not decision.hard_stop else 1.0)
        out_vz = vz + decision.vertical_bias * self.max_vertical
        return float(out_vx), float(out_vy), float(out_vz)
