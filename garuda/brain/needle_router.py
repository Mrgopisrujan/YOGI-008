"""Needle 2 router via its self-contained native function-calling engine.

A tiny deterministic parser handles only emergency/direct commands. Every other
utterance is classified by the local 45M Needle 2 model; low confidence,
unsupported, or empty calls delegate to the local LFM brain. There is no cloud
path and no generic Cactus-bundle fallback.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .tools_schema import ToolProposalV1, validate_tool_proposal

logger = logging.getLogger(__name__)

NEEDLE2_VERSION = "2.0.0"
NEEDLE2_HF_REPO = "Cactus-Compute/needle2"
NEEDLE2_HF_REVISION = "231364ff02542c4060afb5f4795801e0a09f5107"
NEEDLE2_LICENSE = "Apache-2.0"
NEEDLE2_PI_WHEEL_SHA256 = "6660386292916935188edfe8eef94fbf24712085d7c84f80b0698f79509edde3"
DIRECT_COMMANDS = {
    "hover": "hover",
    "hover in place": "hover",
    "stop": "stop",
    "halt": "stop",
    "hold": "hover",
    "land": "land",
    "land now": "land",
    "land the drone": "land",
    "rtl": "rtl",
    "return home": "rtl",
    "go home": "rtl",
}
NEEDLE_TOOLS = [
    {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    for name, description in {
        "hover": "Stop motion and hover.",
        "stop": "Stop current autonomous motion.",
        "land": "Land at the current location.",
        "rtl": "Return to launch.",
        "delegate_to_lfm": "The command needs detailed cinematography or framing reasoning.",
    }.items()
]


@dataclass
class NeedleResult:
    proposal: ToolProposalV1
    delegated_to_lfm: bool
    confidence: float
    latency_ms: float
    error: str | None = None


class NeedleRouter:
    def __init__(self, agent_factory: Callable[..., Any] | None = None) -> None:
        self._agent_factory = agent_factory
        self._agent: Any = None
        self._loaded = False
        self._load_error: str | None = None

    def load(self) -> bool:
        try:
            factory = self._agent_factory
            if factory is None:
                import needle

                if needle.__version__ != NEEDLE2_VERSION:
                    raise RuntimeError(
                        f"Needle version mismatch: expected {NEEDLE2_VERSION}, "
                        f"got {needle.__version__}"
                    )
                factory = needle.Needle
            self._agent = factory(
                tools=NEEDLE_TOOLS,
                system="device: Raspberry Pi 5; network: offline; assistant: GarudaOne",
            )
            self._loaded = True
            self._load_error = None
            return True
        except Exception as exc:
            self._load_error = str(exc)
            logger.error("Needle unavailable: %s", exc)
            return False

    def unload(self) -> None:
        if self._agent is not None:
            try:
                self._agent.reset()
            except Exception:
                logger.exception("Needle 2 reset failed during unload")
        self._agent = None
        self._loaded = False

    def route(self, text: str) -> NeedleResult:
        start = time.monotonic()
        normalized = " ".join(text.lower().strip().split())
        direct = DIRECT_COMMANDS.get(normalized)
        if direct is not None:
            return NeedleResult(
                ToolProposalV1(tool=direct, source="operator", confidence=1.0),
                False,
                1.0,
                (time.monotonic() - start) * 1000,
            )

        if not self._loaded or self._agent is None:
            return self._delegate(start, f"needle_unavailable: {self._load_error or 'not loaded'}")

        try:
            self._agent.reset()
            result = self._agent.complete(text, max_new_tokens=64)
            if not isinstance(result, dict):
                raise RuntimeError(
                    f"unexpected Needle 2 response type: {type(result).__name__}"
                )
            if result.get("success") is False:
                raise RuntimeError(str(result.get("error") or "Needle completion failed"))

            confidence = float(result.get("confidence", 0.0))
            calls = result.get("function_calls") or []
            if len(calls) != 1:
                return self._delegate(start, "needle_low_confidence")
            name = str(calls[0].get("name", ""))
            if name == "delegate_to_lfm":
                return self._delegate(start, None, confidence)
            if confidence < 0.7:
                return self._delegate(start, "needle_low_confidence", confidence)
            proposal = validate_tool_proposal(
                {
                    "schema_version": "v1",
                    "tool": name,
                    "kwargs": calls[0].get("arguments") or {},
                    "source": "needle",
                    "confidence": confidence,
                }
            )
            return NeedleResult(
                proposal,
                False,
                confidence,
                (time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            logger.error("Needle inference failed: %s", exc)
            return self._delegate(start, f"needle_inference_failed: {exc}")

    @staticmethod
    def _delegate(start: float, error: str | None, confidence: float = 0.0) -> NeedleResult:
        return NeedleResult(
            ToolProposalV1(tool="hover", source="operator", confidence=1.0),
            True,
            confidence,
            (time.monotonic() - start) * 1000,
            error=error,
        )

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def load_error(self) -> str | None:
        return self._load_error
