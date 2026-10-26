"""Tool schema v1 — the ONLY tools L1 can propose.

NO arm and NO model-generated takeoff. These are the tools the GBNF grammar
constrains to. Exact authenticated operator takeoff bypasses this model schema.
The arbiter receives ToolProposal objects and decides whether to grant.

This module is imported by both cognition (to generate proposals) and
arbiter (to validate them). It is the contract between L1 and L2a.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

# ─── Tool names (must match arbiter/fsm.py ToolName enum) ─────────────────────

ToolNameStr = Literal["hover", "land", "rtl", "track_subject", "set_framing", "stop"]

# Explicitly BANNED tool names — these must NEVER appear in any schema
BANNED_TOOLS = frozenset({
    "arm", "takeoff", "disarm", "kill", "fly", "shoot",
    "mission_start", "mission_upload", "set_mode",
})

# All valid tool names
VALID_TOOLS = frozenset({
    "hover", "land", "rtl", "track_subject", "set_framing", "stop",
})

# ─── Tool argument schemas ────────────────────────────────────────────────────

# track_subject kwargs
TRACK_SUBJECT_KWARGS = {
    "distance_m": float,        # desired subject distance in meters
    "framing": str,             # "wide" | "medium" | "close"
    "yaw_rate_max": float,      # optional: max yaw rate (rad/s)
    "subject_id": int,          # optional: specific tracked subject ID
}

# set_framing kwargs
SET_FRAMING_KWARGS = {
    "framing": str,             # "wide" | "medium" | "close"
    "distance_m": float,        # optional: adjust distance
}

# Operator-only takeoff kwargs. Takeoff remains in BANNED_TOOLS so model output
# cannot propose it; TextCommandServer parses the exact authenticated route.
TAKEOFF_KWARGS = {
    "altitude_m": float,
}

# Tools that accept no kwargs
NO_KWARG_TOOLS = frozenset({"hover", "land", "rtl", "stop"})

SUPPORTED_FRAMING = frozenset({"wide", "medium", "close"})


def validate_tool_kwargs(tool: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize tool arguments used by deterministic runtime code."""
    if tool in NO_KWARG_TOOLS:
        if kwargs:
            raise ValueError(f"{tool} does not accept kwargs")
        return {}
    if tool == "track_subject":
        schema = TRACK_SUBJECT_KWARGS
    elif tool == "takeoff":
        schema = TAKEOFF_KWARGS
    else:
        schema = SET_FRAMING_KWARGS
    unknown = set(kwargs) - set(schema)
    if unknown:
        raise ValueError(f"Unknown {tool} kwargs: {sorted(unknown)}")
    normalized: dict[str, Any] = {}
    for key, value in kwargs.items():
        expected = schema[key]
        if expected is float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"{key} must be finite")
            normalized[key] = number
        elif expected is int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be an integer")
            normalized[key] = value
        elif not isinstance(value, expected):
            raise ValueError(f"{key} must be {expected.__name__}")
        else:
            normalized[key] = value
    if "distance_m" in normalized and not 0.5 <= normalized["distance_m"] <= 20.0:
        raise ValueError("distance_m must be within [0.5, 20.0]")
    if "altitude_m" in normalized and not 0.5 <= normalized["altitude_m"] <= 3.0:
        raise ValueError("altitude_m must be within [0.5, 3.0]")
    if "yaw_rate_max" in normalized and not 0.1 <= normalized["yaw_rate_max"] <= 1.0:
        raise ValueError("yaw_rate_max must be within [0.1, 1.0]")
    if "subject_id" in normalized and normalized["subject_id"] < 1:
        raise ValueError("subject_id must be positive")
    if "framing" in normalized and normalized["framing"] not in SUPPORTED_FRAMING:
        raise ValueError(f"framing must be one of {sorted(SUPPORTED_FRAMING)}")
    return normalized

# ─── ToolProposal (L1 → L2a) ──────────────────────────────────────────────────

@dataclass
class ToolProposalV1:
    """Tool proposal from L1 (Needle/LFM/operator) — schema v1.

    This is the GBNF-constrained output format. The grammar guarantees
    structurally valid JSON. The arbiter validates the semantic content.

    schema_version is always "v1" — unknown versions are rejected.
    """
    schema_version: str = "v1"
    tool: str = ""              # ToolNameStr
    kwargs: dict[str, Any] = field(default_factory=dict)
    source: str = "operator"    # "needle" | "lfm" | "vlm" | "operator"
    confidence: float = 1.0     # 0.0-1.0

    def __post_init__(self) -> None:
        """Validate the proposal at construction time."""
        if self.schema_version != "v1":
            raise ValueError(f"Unsupported schema_version: {self.schema_version}")
        if self.tool not in VALID_TOOLS:
            raise ValueError(f"Invalid tool: {self.tool}. Valid: {VALID_TOOLS}")
        if self.tool in BANNED_TOOLS:
            raise ValueError(f"BANNED tool: {self.tool}")

    def to_arbiter_proposal(self):
        """Convert to arbiter's ToolProposal format."""
        from ..arbiter.arbiter import ToolProposal
        return ToolProposal(
            tool=self.tool,
            kwargs=self.kwargs,
            source=self.source,
            confidence=self.confidence,
        )


# ─── Validation helpers ───────────────────────────────────────────────────────

def validate_tool_proposal(data: dict) -> ToolProposalV1:
    """Validate a raw dict (e.g. parsed JSON from LFM/Needle) into a ToolProposalV1.

    Raises ValueError for invalid proposals.
    """
    if not isinstance(data, dict):
        raise ValueError("Tool proposal must be a dict")

    schema_version = data.get("schema_version", "")
    if schema_version != "v1":
        raise ValueError(f"schema_version must be 'v1', got: {schema_version}")

    tool = data.get("tool", "")
    if tool not in VALID_TOOLS:
        raise ValueError(f"Invalid tool '{tool}'. Valid: {VALID_TOOLS}")

    kwargs = data.get("kwargs", {})
    if not isinstance(kwargs, dict):
        raise ValueError("kwargs must be a dict")
    kwargs = validate_tool_kwargs(tool, kwargs)

    source = data.get("source", "operator")
    if source not in ("needle", "lfm", "vlm", "operator"):
        raise ValueError(f"Invalid source: {source}")

    confidence = data.get("confidence", 1.0)
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError(f"confidence must be 0-1, got: {confidence}")

    return ToolProposalV1(
        schema_version="v1",
        tool=tool,
        kwargs=kwargs,
        source=source,
        confidence=float(confidence),
    )


def is_banned_tool(name: str) -> bool:
    """Check if a tool name is explicitly banned."""
    return name in BANNED_TOOLS
