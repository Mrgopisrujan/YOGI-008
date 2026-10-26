"""
GarudaOne DroneOS — Cinematic Shot Planner
=========================================
Translates "follow that man" into a *shot*, not just a control loop. A shot
specifies framing, standoff, and the smooth dolly/orbit behaviour that makes
the result look filmed rather than flown.

Why a planner instead of hard-coded constants in the control loop: the user
asked for "drone shots". A drone that servos a person to screen centre from a
fixed 4.5 m is a tracking camera, not cinematography. The shot parameters are
what separate them.

Each ShotSpec maps to concrete control gains used by FollowController:
  target_h_ratio   — desired subject height as a fraction of frame height.
                     This is the framing dial: 0.55 = tight medium,
                     0.30 = loose wide, 0.75 = close-up.
  standoff_m       — geometric distance to hold when depth is unavailable.
  orbit_rate_dps   — degrees per second of orbit around the subject.
                     0 = pure follow; nonzero = circling.
  lateral_bias     — metres of continuous sideways drift, for
                     over-the-shoulder / lead-room framing.
  lead_room_frac   — fraction of frame the subject should sit off-centre
                     (negative = subject left of centre, so the drone
                     "leads" into the direction of travel).
  pitch_bias_deg   — nose/camera tilt bias for a low or high angle.

The director converts a spoken request into a ShotSpec via keyword rules, so
it works with no LLM and no network.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, replace
from typing import Optional

log = logging.getLogger("shot_planner")


@dataclass(frozen=True)
class ShotSpec:
    """Immutable description of one cinematic shot."""

    name: str = "follow"
    target_h_ratio: float = 0.42      # framing: subject height / frame height
    standoff_m: float = 4.5           # desired geometric separation
    orbit_rate_dps: float = 0.0       # >0 clockwise orbit, <0 counter-clockwise
    lateral_bias: float = 0.0         # metres/frame of continuous strafe
    lead_room_frac: float = 0.0       # subject offset from centre (-1..1)
    pitch_bias_deg: float = 0.0       # camera tilt bias
    follow_distance: float = 5.0      # CF feed (nominal, metres)
    max_speed_mps: float = 2.5
    record: bool = True               # should this shot write video?

    def describe(self) -> str:
        bits = [f"framing {self.target_h_ratio*100:.0f}%", f"standoff {self.standoff_m:.1f}m"]
        if abs(self.orbit_rate_dps) > 1e-3:
            bits.append(f"orbit {self.orbit_rate_dps:+.1f}°/s")
        if abs(self.lateral_bias) > 1e-3:
            bits.append(f"strafe {self.lateral_bias:+.1f}m")
        if abs(self.lead_room_frac) > 1e-3:
            bits.append(f"lead room {self.lead_room_frac:+.2f}")
        return f"{self.name} ({', '.join(bits)})"


# ── Shot library ───────────────────────────────────────────────────────
# Defaults are tuned for a 640x480 90° FOV front camera at 2-5 m standoff.

FOLLOW: ShotSpec = ShotSpec(
    name="follow",
    target_h_ratio=0.42,
    standoff_m=4.5,
)

CHASE: ShotSpec = ShotSpec(
    name="chase",
    target_h_ratio=0.30,
    standoff_m=6.0,
    max_speed_mps=3.0,
)

ORBIT: ShotSpec = ShotSpec(
    name="orbit",
    target_h_ratio=0.38,
    standoff_m=6.0,
    orbit_rate_dps=14.0,
    max_speed_mps=2.0,
)

ORBIT_CCW: ShotSpec = replace(ORBIT, name="orbit_ccw", orbit_rate_dps=-14.0)

CLOSE_UP: ShotSpec = ShotSpec(
    name="close_up",
    target_h_ratio=0.72,
    standoff_m=2.2,
    max_speed_mps=1.6,
)

WIDE: ShotSpec = ShotSpec(
    name="wide",
    target_h_ratio=0.22,
    standoff_m=9.0,
    max_speed_mps=2.0,
)

OVER_SHOULDER: ShotSpec = ShotSpec(
    name="over_shoulder",
    target_h_ratio=0.45,
    standoff_m=3.2,
    lateral_bias=0.9,
    lead_room_frac=-0.18,
)

LOW_ANGLE: ShotSpec = ShotSpec(
    name="low_angle",
    target_h_ratio=0.50,
    standoff_m=4.0,
    pitch_bias_deg=-12.0,
)

HIGH_ANGLE: ShotSpec = ShotSpec(
    name="high_angle",
    target_h_ratio=0.35,
    standoff_m=6.5,
    pitch_bias_deg=10.0,
)

REVEAL: ShotSpec = ShotSpec(
    name="reveal",
    target_h_ratio=0.30,
    standoff_m=8.0,
    max_speed_mps=3.0,
)

# Ordered longest-phrase-first so "close up" beats "up", "over the shoulder"
# beats "shoulder".
_MODIFIERS: list[tuple[str, ShotSpec]] = [
    ("over the shoulder", OVER_SHOULDER),
    ("over shoulder", OVER_SHOULDER),
    ("ots", OVER_SHOULDER),
    ("close up", CLOSE_UP),
    ("closeup", CLOSE_UP),
    ("tight", CLOSE_UP),
    ("portrait", CLOSE_UP),
    ("chase", CHASE),
    ("follow behind", CHASE),
    ("from behind", CHASE),
    ("stay behind", CHASE),
    ("trail", CHASE),
    ("orbit counter", ORBIT_CCW),
    ("orbit anticlockwise", ORBIT_CCW),
    ("orbit left", ORBIT_CCW),
    ("orbit", ORBIT),
    ("circle", ORBIT),
    ("reveal", REVEAL),
    ("pull back", REVEAL),
    ("pull away", REVEAL),
    ("wide", WIDE),
    ("establishing", WIDE),
    ("low angle", LOW_ANGLE),
    ("worm", LOW_ANGLE),
    ("ground level", LOW_ANGLE),
    ("high angle", HIGH_ANGLE),
    ("birds eye", HIGH_ANGLE),
    ("top down", HIGH_ANGLE),
]

# Free-text shot modifiers applied on top of a base shot.
_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


class ShotDirector:
    """
    Rule-based shot selection from a spoken command.

    Deliberately deterministic and offline: the point of the exercise is that
    "follow that man, close up, from the left" produces a specific shot
    without a network round-trip.
    """

    def __init__(self, default: ShotSpec = FOLLOW) -> None:
        self.default = default
        self._distance_override: Optional[float] = None

    def parse(self, text: str) -> ShotSpec:
        """Return the ShotSpec described by ``text`` (defaults to FOLLOW)."""
        low = (text or "").lower().strip()
        if not low:
            return self.default

        spec = self.default
        for phrase, shot in _MODIFIERS:
            if re.search(r"\b" + re.escape(phrase) + r"\b", low):
                spec = shot
                break

        spec = self._apply_direction(spec, low)
        spec = self._apply_numbers(spec, low)
        return spec

    # ── Internals ──────────────────────────────────────────────────────

    def _apply_direction(self, spec: ShotSpec, low: str) -> ShotSpec:
        """Set orbit direction / strafe side from left-right wording.

        The modifier library encodes an explicit direction for the variants
        that have one ("orbit left" is counter-clockwise). This pass only
        applies when the caller stated a side in the sentence itself.
        """
        going_left = bool(re.search(r"\b(from |on |to )?(the )?left\b", low))
        going_right = bool(re.search(r"\b(from |on |to )?(the )?right\b", low))
        if going_left == going_right:      # neither, or contradictory
            return spec

        side_left = going_left

        if abs(spec.orbit_rate_dps) > 1e-3:
            # ORBIT ships clockwise-positive; left means counter-clockwise.
            if spec.name == "orbit":
                return replace(spec, orbit_rate_dps=-abs(spec.orbit_rate_dps) if side_left
                               else abs(spec.orbit_rate_dps))
            return replace(spec, orbit_rate_dps=abs(spec.orbit_rate_dps) if side_left
                           else -abs(spec.orbit_rate_dps))
        if abs(spec.lateral_bias) > 1e-3:
            return replace(spec, lateral_bias=-abs(spec.lateral_bias) if side_left
                           else abs(spec.lateral_bias))
        if "lead" in low or "over" in low or "shoulder" in low:
            return replace(spec, lateral_bias=0.9 if side_left else -0.9)
        return spec

    def _apply_numbers(self, spec: ShotSpec, low: str) -> ShotSpec:
        """Honour an explicit 'keep 3 metres away' style instruction."""
        m = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:m|met(?:re|er)s?)\b(?:\s*(?:away|off|distance|back))?", low
        )
        if not m:
            return spec
        try:
            dist = float(m.group(1))
        except ValueError:
            return spec
        if not (1.0 <= dist <= 30.0):
            return spec
        # A distance request reframes the shot: closer distance => tighter frame.
        ratio = float(max(0.18, min(0.80, 0.62 - 0.045 * dist)))
        return replace(spec, standoff_m=dist, target_h_ratio=ratio, follow_distance=dist)

    @staticmethod
    def describe(spec: ShotSpec) -> str:
        return spec.describe()

    @staticmethod
    def orbit_step(spec: ShotSpec, dt: float, radius_m: float) -> tuple[float, float]:
        """
        Tangential velocity (right, forward) for the orbit component of a shot.

        Returns body-frame (vy, vx) contributions in m/s.
        """
        if abs(spec.orbit_rate_dps) < 1e-3 or radius_m <= 0.1:
            return 0.0, 0.0
        omega = math.radians(spec.orbit_rate_dps)
        return float(spec.orbit_rate_dps * math.pi / 180.0) * radius_m, 0.0
