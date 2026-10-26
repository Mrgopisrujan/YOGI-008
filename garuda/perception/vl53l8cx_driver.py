"""VL53L8CX adapter backed by ST's official Ultra Lite Driver (ULD).

The sensor is not a simple register block device: every power cycle requires an
~80 KiB firmware/configuration upload and ST's ULD parses the ranging payload.
Production therefore uses the Linux ctypes wrapper built from the official ULD:
https://github.com/NamanVashishta/vl53l8cx-python

This module intentionally contains no hand-written fake register map.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .tof import TofGrid, TofSource, TofZone

logger = logging.getLogger(__name__)

VALID_TARGET_STATUSES = frozenset({5, 9})
MAX_RANGE_M = 10.0


class VL53L8CXDriver(TofSource):
    """Production VL53L8CX source using the official ST ULD wrapper."""

    def __init__(
        self,
        i2c_bus: int = 1,
        address: int = 0x29,
        label: str = "front",
        *,
        sensor_factory: Callable[..., Any] | None = None,
        data_timeout_s: float = 0.25,
    ) -> None:
        if not (0x08 <= address <= 0x77):
            raise ValueError(f"Invalid 7-bit I2C address: 0x{address:02x}")
        self.i2c_bus = i2c_bus
        self.address = address
        self.label = label
        self.data_timeout_s = data_timeout_s
        self._sensor_factory = sensor_factory
        self._sensor: Any = None
        self._loaded = False
        self._last_read_time = 0.0
        self._last_error: str | None = None

    @staticmethod
    def _default_factory() -> Callable[..., Any]:
        try:
            from vl53l8cx_ctypes import VL53L8CX
        except ImportError as exc:
            raise RuntimeError(
                "VL53L8CX official ULD wrapper is not installed. Run "
                "`scripts/install_vl53l8cx_uld.sh` on the Raspberry Pi."
            ) from exc
        return VL53L8CX

    def load(self) -> bool:
        """Upload sensor firmware through the ULD and start 8x8 ranging."""
        try:
            factory = self._sensor_factory or self._default_factory()
            # The wrapper accepts a 7-bit address and opens /dev/i2c-1 by
            # default. Custom bus selection is supported by injecting a factory.
            if self.i2c_bus != 1 and self._sensor_factory is None:
                raise RuntimeError(
                    "The packaged ULD wrapper defaults to /dev/i2c-1. Inject a "
                    "sensor_factory with an SMBus instance for another bus."
                )
            self._sensor = factory(i2c_addr=self.address)
            self._sensor.set_resolution(64)
            self._sensor.set_ranging_frequency_hz(15)
            self._sensor.start_ranging()
            self._loaded = True
            self._last_error = None
            return True
        except Exception as exc:
            self._sensor = None
            self._loaded = False
            self._last_error = str(exc)
            logger.error("VL53L8CX [%s] initialization failed: %s", self.label, exc)
            return False

    def read_zones(self) -> TofGrid:
        if not self._loaded or self._sensor is None:
            raise RuntimeError(
                f"VL53L8CX [{self.label}] is not initialized: {self._last_error or 'call load()'}"
            )

        deadline = time.monotonic() + self.data_timeout_s
        while time.monotonic() < deadline:
            if self._sensor.data_ready():
                result = self._sensor.get_data()
                return self._convert_result(result)
            time.sleep(0.002)
        self._last_error = "timed out waiting for ranging data"
        raise RuntimeError(f"VL53L8CX [{self.label}] {self._last_error}")

    read_grid = read_zones

    def _convert_result(self, result: Any) -> TofGrid:
        distances = list(result.distance_mm)
        statuses = list(result.target_status)
        if len(distances) < 64 or len(statuses) < 64:
            raise RuntimeError(
                f"VL53L8CX [{self.label}] ULD returned short frame: "
                f"{len(distances)} distances, {len(statuses)} statuses"
            )

        zones: list[TofZone] = []
        for i in range(64):
            status = int(statuses[i])
            distance_mm = int(distances[i])
            valid = status in VALID_TARGET_STATUSES and distance_mm > 0
            zones.append(
                TofZone(
                    distance_m=min(distance_mm / 1000.0, MAX_RANGE_M) if valid else MAX_RANGE_M,
                    confidence=0.9 if status == 5 and valid else (0.6 if valid else 0.0),
                    # ST's ULD enumerates from bottom-left; flip vertically to
                    # the image convention (row 0 = top).
                    zone_row=7 - (i // 8),
                    zone_col=i % 8,
                )
            )
        self._last_read_time = time.monotonic()
        self._last_error = None
        return TofGrid(
            zones=zones,
            rows=8,
            cols=8,
            sensor=f"vl53l8cx_{self.label}",
            timestamp=self._last_read_time,
        )

    def heartbeat_ok(self) -> bool:
        return (
            self._loaded
            and self._last_read_time > 0.0
            and time.monotonic() - self._last_read_time < 2.0
        )

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def close(self) -> None:
        if self._sensor is not None:
            try:
                self._sensor.stop_ranging()
            except Exception:
                logger.exception("VL53L8CX [%s] stop_ranging failed", self.label)
        self._sensor = None
        self._loaded = False


def create_vl53l8cx_driver(
    i2c_bus: int = 1,
    address: int = 0x29,
    label: str = "front",
    *,
    sensor_factory: Callable[..., Any] | None = None,
    auto_load: bool = True,
) -> VL53L8CXDriver:
    driver = VL53L8CXDriver(
        i2c_bus=i2c_bus,
        address=address,
        label=label,
        sensor_factory=sensor_factory,
    )
    if auto_load and not driver.load():
        raise RuntimeError(
            f"Failed to initialize VL53L8CX [{label}] at 0x{address:02x}: {driver.last_error}"
        )
    return driver
