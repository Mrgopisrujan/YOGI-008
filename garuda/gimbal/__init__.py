"""Gimbal package — pitch/yaw + ROI control for GarudaOne.

Backends:
    NullGimbal      — no-op for SITL / dev / CI (heartbeat always True)
    SkydroidGimbal  — checksummed UDP protocol (Skydroid C10 Pro, primary)
    SiyiGimbal      — SIYI UART serial protocol (alternative hardware)

Use create_gimbal(backend="auto") to pick the best available backend for
the current environment. The arbiter treats the returned object as the
GimbalBackend protocol (see protocol.py).

Safety: heartbeat timeout (1.0 s per safety_limits.GimbalLimits) →
freeze + disable counter-rotation. The arbiter FSM independently forces
HOVER on the "gimbal_heartbeat_lost" watchdog event.
"""

from __future__ import annotations

import logging
from typing import Any

from .null_gimbal import NullGimbal
from .protocol import (
    GimbalBackend,
    GimbalBackendProtocol,
    GimbalStatus,
)
from .siyi import SiyiGimbal
from .skydroid import SkydroidGimbal

logger = logging.getLogger(__name__)

__all__ = [
    "GimbalBackend",
    "GimbalBackendProtocol",
    "GimbalStatus",
    "NullGimbal",
    "SkydroidGimbal",
    "SiyiGimbal",
    "create_gimbal",
]


def create_gimbal(
    backend: str = "auto",
    *,
    connection: Any = None,
    connection_string: str = "udp://:14540",
    port: str = "/dev/ttyTHS1",
    baudrate: int = 115200,
    heartbeat_timeout_s: float | None = None,
    allow_null_fallback: bool = True,
    **kwargs: Any,
) -> GimbalBackend:
    """Factory: create a gimbal backend.

    Args:
        backend: "auto" | "null" | "skydroid" | "siyi".
            "auto" tries skydroid → siyi → null (unless allow_null_fallback
            is False, in which case it raises on hardware unavailability).
        connection: an existing pyserial connection to inject for SIYI.
        connection_string: retained for API compatibility; Skydroid uses UDP host/port.
        port / baudrate: serial port config for siyi.
        heartbeat_timeout_s: override the 1.0 s GimbalLimits default.
        allow_null_fallback: if False, "auto" raises when no real backend
            can be constructed (e.g. flight.yaml forbids null gimbal).
        **kwargs: forwarded to the backend constructor.

    Returns:
        A GimbalBackend instance. For "auto", returns NullGimbal if no
        hardware backend is available (pymavlink/pyserial missing or
        connection fails) and allow_null_fallback is True.

    Raises:
        ValueError: unknown backend name.
        ImportError: "auto" with allow_null_fallback=False and no hardware.
    """
    if backend == "null":
        return NullGimbal(heartbeat_timeout_s=heartbeat_timeout_s)

    if backend == "skydroid":
        g = SkydroidGimbal(host=kwargs.pop("host", "192.168.144.108"),
                           port=kwargs.pop("gimbal_port", 5000))
        g.connect()
        return g

    if backend == "siyi":
        return SiyiGimbal(
            port=port,
            baudrate=baudrate,
            connection=connection,
            heartbeat_timeout_s=heartbeat_timeout_s,
            **kwargs,
        )

    if backend == "auto":
        # 1. Try Skydroid (primary hardware, UDP protocol)
        try:
            g = SkydroidGimbal(host=kwargs.pop("host", "192.168.144.108"),
                               port=kwargs.pop("gimbal_port", 5000))
            g.connect()
            if g.probe_device():
                return g
            g.disconnect()
            logger.info("create_gimbal: skydroid has no inbound device evidence — trying next")
        except Exception as e:
            logger.info(f"create_gimbal: skydroid unavailable ({e})")

        # 2. Try SIYI (alternative hardware).
        try:
            g = SiyiGimbal(
                port=port,
                baudrate=baudrate,
                connection=connection,
                heartbeat_timeout_s=heartbeat_timeout_s,
                **kwargs,
            )
            if connection is not None:
                return g
            import importlib
            if importlib.util.find_spec("serial") is not None:
                return g
            logger.info("create_gimbal: pyserial not installed — skipping siyi")
        except ImportError as e:
            logger.info(f"create_gimbal: siyi unavailable ({e})")
        except Exception as e:
            logger.warning(f"create_gimbal: siyi init failed ({e})")

        # 3. Fall back to NullGimbal (SITL/dev) or raise.
        if allow_null_fallback:
            logger.warning("create_gimbal: no hardware gimbal — using NullGimbal")
            return NullGimbal(heartbeat_timeout_s=heartbeat_timeout_s)
        raise ImportError(
            "No hardware gimbal backend available and allow_null_fallback=False. "
            "Install pymavlink (skydroid) or pyserial (siyi), or pass connection=."
        )

    raise ValueError(
        f"Unknown gimbal backend: {backend!r}. "
        "Expected one of: 'auto', 'null', 'skydroid', 'siyi'."
    )
