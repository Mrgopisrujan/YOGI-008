"""VL53L5CX adapter backed by ST's official Ultra Lite Driver.

The selected FlyLens hardware profile uses the SmartElex VL53L5CX carrier.
Production loads Pimoroni's MIT ctypes wrapper around the pinned ST ULD. No
hand-written register map or synthetic distance fallback exists here.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .tof import TofGrid, TofSource, TofZone

logger = logging.getLogger(__name__)

# UM2884 Rev 2 section 5.5: 5 is fully valid; 6 and 9 are usable at
# approximately 50% confidence. Other statuses must not authorize clearance.
VALID_TARGET_STATUSES = frozenset({5, 6, 9})
MAX_RANGE_M = 4.0


class VL53L5CXDriver(TofSource):
    """Production VL53L5CX source using the official ST ULD wrapper."""

    def __init__(
        self,
        i2c_bus: int = 1,
        address: int = 0x29,
        label: str = "front",
        *,
        sensor_factory: Callable[..., Any] | None = None,
        data_timeout_s: float = 0.25,
        resolution: int = 64,
        frequency_hz: int = 15,
    ) -> None:
        if not 0x08 <= address <= 0x77:
            raise ValueError(f"Invalid 7-bit I2C address: 0x{address:02x}")
        if resolution not in {16, 64}:
            raise ValueError("VL53L5CX resolution must be 16 or 64 zones")
        max_frequency = 60 if resolution == 16 else 15
        if not 1 <= frequency_hz <= max_frequency:
            raise ValueError(
                f"VL53L5CX {resolution}-zone frequency must be 1-{max_frequency} Hz"
            )
        self.i2c_bus = i2c_bus
        self.address = address
        self.label = label
        self.data_timeout_s = data_timeout_s
        self.resolution = resolution
        self.frequency_hz = frequency_hz
        self._sensor_factory = sensor_factory
        self._sensor: Any = None
        self._loaded = False
        self._last_read_time = 0.0
        self._last_error: str | None = None

    @staticmethod
    def _default_factory() -> Callable[..., Any]:
        try:
            from vl53l5cx_ctypes import VL53L5CX
        except ImportError as exc:
            raise RuntimeError(
                "VL53L5CX ULD wrapper is not installed. Run "
                "`scripts/install_vl53l5cx_uld.sh` on the Raspberry Pi."
            ) from exc
        return VL53L5CX

    def load(self) -> bool:
        """Upload the ~84 KiB firmware through the ULD and start ranging."""
        try:
            factory = self._sensor_factory or self._default_factory()
            if self.i2c_bus != 1 and self._sensor_factory is None:
                raise RuntimeError(
                    "The packaged VL53L5CX wrapper defaults to /dev/i2c-1. "
                    "Inject a sensor_factory with an SMBus instance for another bus."
                )
            self._sensor = factory(i2c_addr=self.address)
            self._sensor.set_resolution(self.resolution)
            self._sensor.set_ranging_frequency_hz(self.frequency_hz)
            self._sensor.start_ranging()
            self._loaded = True
            self._last_error = None
            return True
        except Exception as exc:
            self._sensor = None
            self._loaded = False
            self._last_error = str(exc)
            logger.error("VL53L5CX [%s] initialization failed: %s", self.label, exc)
            return False

    def read_zones(self) -> TofGrid:
        if not self._loaded or self._sensor is None:
            raise RuntimeError(
                f"VL53L5CX [{self.label}] is not initialized: "
                f"{self._last_error or 'call load()'}"
            )
        deadline = time.monotonic() + self.data_timeout_s
        while time.monotonic() < deadline:
            if self._sensor.data_ready():
                return self._convert_result(self._sensor.get_data())
            time.sleep(0.002)
        self._last_error = "timed out waiting for ranging data"
        raise RuntimeError(f"VL53L5CX [{self.label}] {self._last_error}")

    read_grid = read_zones

    def _convert_result(self, result: Any) -> TofGrid:
        count = self.resolution
        side = 4 if count == 16 else 8
        distances = list(result.distance_mm)
        statuses = list(result.target_status)
        if len(distances) < count or len(statuses) < count:
            raise RuntimeError(
                f"VL53L5CX [{self.label}] ULD returned short frame: "
                f"{len(distances)} distances, {len(statuses)} statuses"
            )

        zones: list[TofZone] = []
        for index in range(count):
            status = int(statuses[index])
            distance_mm = int(distances[index])
            valid = status in VALID_TARGET_STATUSES and distance_mm > 0
            confidence = 1.0 if status == 5 and valid else (0.5 if valid else 0.0)
            # DS13754/UM2884: the lens flips the scene horizontally and vertically.
            row = side - 1 - (index // side)
            col = side - 1 - (index % side)
            zones.append(
                TofZone(
                    distance_m=(
                        min(distance_mm / 1000.0, MAX_RANGE_M)
                        if valid
                        else MAX_RANGE_M
                    ),
                    confidence=confidence,
                    zone_row=row,
                    zone_col=col,
                )
            )
        self._last_read_time = time.monotonic()
        self._last_error = None
        return TofGrid(
            zones=zones,
            rows=side,
            cols=side,
            sensor=f"vl53l5cx_{self.label}",
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
                logger.exception("VL53L5CX [%s] stop_ranging failed", self.label)
        self._sensor = None
        self._loaded = False


def create_vl53l5cx_driver(
    i2c_bus: int = 1,
    address: int = 0x29,
    label: str = "front",
    *,
    sensor_factory: Callable[..., Any] | None = None,
    auto_load: bool = True,
    resolution: int = 64,
    frequency_hz: int = 15,
) -> VL53L5CXDriver:
    driver = VL53L5CXDriver(
        i2c_bus=i2c_bus,
        address=address,
        label=label,
        sensor_factory=sensor_factory,
        resolution=resolution,
        frequency_hz=frequency_hz,
    )
    if auto_load and not driver.load():
        raise RuntimeError(
            f"Failed to initialize VL53L5CX [{label}] at 0x{address:02x}: "
            f"{driver.last_error}"
        )
    return driver
