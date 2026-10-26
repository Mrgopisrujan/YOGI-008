"""Multi-zone Time-of-Flight sensor interfaces.

The selected FlyLens profile uses one forward VL53L5CX at 8x8/15 Hz. Legacy
VL53L8CX and experimental three-sensor aggregation remain available, but are
not the active hardware profile. The governor consumes measured range and
confidence; missing/failed measurements remain blind rather than clear.

Protocol: TofSource with read_grid() and heartbeat_ok().
MultiSensorTof aggregates 3 sensors into a unified 360° view.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TofZone:
    """A single ToF zone measurement."""
    distance_m: float = 10.0
    confidence: float = 1.0
    zone_row: int = 0
    zone_col: int = 0


@dataclass
class TofGrid:
    """A full ToF grid reading (e.g. 8×8 or 48×32)."""
    zones: list[TofZone] = field(default_factory=list)
    timestamp: float = field(default_factory=time.monotonic)
    rows: int = 0
    cols: int = 0
    sensor: str = "unknown"

    @property
    def min_distance_m(self) -> float:
        if not self.zones:
            return 10.0
        center_r = self.rows // 2
        center_c = self.cols // 2
        center_zones = [
            z for z in self.zones
            if abs(z.zone_row - center_r) <= 1 and abs(z.zone_col - center_c) <= 1
            and z.confidence > 0.3
        ]
        if not center_zones:
            return 10.0
        return min(z.distance_m for z in center_zones)

    @property
    def left_distance_m(self) -> float:
        if not self.zones:
            return 10.0
        left = [z for z in self.zones if z.zone_col < self.cols // 3 and z.confidence > 0.3]
        return min((z.distance_m for z in left), default=10.0)

    @property
    def center_distance_m(self) -> float:
        if not self.zones:
            return 10.0
        center = [z for z in self.zones if self.cols // 3 <= z.zone_col < 2 * self.cols // 3 and z.confidence > 0.3]
        return min((z.distance_m for z in center), default=10.0)

    @property
    def right_distance_m(self) -> float:
        if not self.zones:
            return 10.0
        right = [z for z in self.zones if z.zone_col >= 2 * self.cols // 3 and z.confidence > 0.3]
        return min((z.distance_m for z in right), default=10.0)

    @property
    def mean_confidence(self) -> float:
        if not self.zones:
            return 0.0
        return sum(z.confidence for z in self.zones) / len(self.zones)

    def to_cfc_input_fields(self) -> dict[str, float]:
        return {
            "tof_min_m": self.min_distance_m,
            "tof_left_m": self.left_distance_m,
            "tof_center_m": self.center_distance_m,
            "tof_right_m": self.right_distance_m,
            "tof_conf": self.mean_confidence,
        }


@dataclass
class Tof360Reading:
    """Unified 360° ToF reading from 3 sensors (front + back + top)."""
    front: TofGrid = field(default_factory=TofGrid)
    back: TofGrid = field(default_factory=TofGrid)
    top: TofGrid = field(default_factory=TofGrid)
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def front_min_m(self) -> float:
        return self.front.min_distance_m

    @property
    def back_min_m(self) -> float:
        return self.back.min_distance_m

    @property
    def top_min_m(self) -> float:
        return self.top.min_distance_m

    @property
    def all_clear(self) -> bool:
        """True only when every sensor is healthy and reports safe clearance."""
        return (not self.any_blind and
                self.front_min_m > 1.0 and
                self.back_min_m > 1.0 and
                self.top_min_m > 1.0)

    @property
    def any_blind(self) -> bool:
        """True when any direction lacks a trustworthy ToF measurement."""
        return any(
            not grid.zones or grid.mean_confidence <= 0.3
            for grid in (self.front, self.back, self.top)
        )

    @property
    def any_critical(self) -> bool:
        """True if any obstacle within 0.5m in any direction."""
        return (self.front_min_m < 0.5 or
                self.back_min_m < 0.5 or
                self.top_min_m < 0.5)


class TofSource(ABC):
    """Abstract ToF sensor."""

    @abstractmethod
    def read_grid(self) -> TofGrid:
        ...

    @abstractmethod
    def heartbeat_ok(self) -> bool:
        ...

    def load(self) -> bool:
        """Initialize hardware. Test/null sources are ready immediately."""
        return True

    def close(self) -> None:
        """Release hardware resources when present."""
        return None


class MockTof(TofSource):
    """Mock ToF for CI/SITL."""

    def __init__(
        self,
        rows: int = 8,
        cols: int = 8,
        default_distance: float = 5.0,
        default_confidence: float = 0.9,
    ) -> None:
        self.rows = rows
        self.cols = cols
        self.default_distance = default_distance
        self.default_confidence = default_confidence
        self._obstacle_distance: float | None = None

    def set_obstacle(self, distance_m: float) -> None:
        self._obstacle_distance = distance_m

    def clear_obstacle(self) -> None:
        self._obstacle_distance = None

    def read_grid(self) -> TofGrid:
        zones = []
        center_r = self.rows // 2
        center_c = self.cols // 2
        for r in range(self.rows):
            for c in range(self.cols):
                if self._obstacle_distance is not None and abs(r - center_r) <= 1 and abs(c - center_c) <= 1:
                    dist = self._obstacle_distance
                else:
                    dist = self.default_distance
                zones.append(TofZone(
                    distance_m=dist,
                    confidence=self.default_confidence,
                    zone_row=r,
                    zone_col=c,
                ))
        return TofGrid(zones=zones, rows=self.rows, cols=self.cols, sensor="mock")

    def heartbeat_ok(self) -> bool:
        return True


class NullTof(TofSource):
    """No ToF sensor — returns full-range with low confidence."""

    def read_grid(self) -> TofGrid:
        return TofGrid(
            zones=[TofZone(distance_m=10.0, confidence=0.0) for _ in range(64)],
            rows=8, cols=8, sensor="null",
        )

    def heartbeat_ok(self) -> bool:
        return False


class MultiSensorTof:
    """360° ToF aggregation from 3 VL53L8CX sensors.

    Sensors:
      - Front (0x52): forward obstacle detection + subject distance
      - Back (0x53): rear obstacle detection (backward flight safety)
      - Top (0x54): ceiling/fan detection (ascending safety)

    The Arbiter reads all_clear and any_critical for safety clamps.
    The CfC reads front grid for smooth avoidance.
    """

    def __init__(
        self,
        front: TofSource | None = None,
        back: TofSource | None = None,
        top: TofSource | None = None,
    ) -> None:
        self.front = front if front is not None else NullTof()
        self.back = back if back is not None else NullTof()
        self.top = top if top is not None else NullTof()

    def read_360(self) -> Tof360Reading:
        """Read all 3 sensors and return unified 360° reading."""
        return Tof360Reading(
            front=self.front.read_grid(),
            back=self.back.read_grid(),
            top=self.top.read_grid(),
            timestamp=time.monotonic(),
        )

    def read_front(self) -> TofGrid:
        """Read just the front sensor (for CfC input)."""
        return self.front.read_grid()

    def heartbeat_ok(self) -> bool:
        """All sensors must be alive for 360° safety."""
        return (self.front.heartbeat_ok() and
                self.back.heartbeat_ok() and
                self.top.heartbeat_ok())

    @property
    def all_clear(self) -> bool:
        """True if no obstacle in any direction."""
        reading = self.read_360()
        return reading.all_clear

    @property
    def any_critical(self) -> bool:
        """True if any obstacle within 0.5m."""
        reading = self.read_360()
        return reading.any_critical


def create_tof(backend: str = "mock", **kwargs) -> TofSource:
    """Factory for single ToF sources."""
    match backend:
        case "vl53l5cx":
            from .vl53l5cx_driver import VL53L5CXDriver
            return VL53L5CXDriver(**kwargs)
        case "vl53l8cx":
            from .vl53l8cx_driver import VL53L8CXDriver
            return VL53L8CXDriver(**kwargs)
        case "mock":
            return MockTof(**kwargs)
        case "null":
            return NullTof()
        case "tmf8829":
            # Production PCB (SPI) — not yet supported, raise error
            raise RuntimeError("TMF8829 SPI driver not implemented. Use VL53L8CX (I2C) for prototype.")
        case _:
            raise ValueError(f"Unknown ToF backend: {backend}")


def create_360_tof(
    front_addr: int = 0x29,
    back_addr: int = 0x2A,
    top_addr: int = 0x2B,
    i2c_bus: int = 1,
    use_real: bool = False,
) -> MultiSensorTof:
    """Factory for 360° 3-sensor ToF setup.

    Args:
        front_addr: Linux 7-bit I2C address for the front sensor (default 0x29)
        back_addr: Linux 7-bit address after XSHUT/multiplexer provisioning
        top_addr: Linux 7-bit address after XSHUT/multiplexer provisioning
        i2c_bus: I2C bus number (1 = default on Pi 5)
        use_real: If True, initialize ST ULD-backed sensors. The caller must
            provision unique addresses first; three sensors power up at 0x29.

    Returns:
        MultiSensorTof with 3 sensors.
    """
    if use_real:
        from .vl53l8cx_driver import VL53L8CXDriver

        front = VL53L8CXDriver(i2c_bus=i2c_bus, address=front_addr, label="front")
        back = VL53L8CXDriver(i2c_bus=i2c_bus, address=back_addr, label="back")
        top = VL53L8CXDriver(i2c_bus=i2c_bus, address=top_addr, label="top")
        failed: list[str] = []
        for sensor in (front, back, top):
            if not sensor.load():
                failed.append(sensor.label)
        if failed:
            for sensor in (front, back, top):
                sensor.close()
            raise RuntimeError(
                "Failed to initialize real VL53L8CX sensor(s): " + ", ".join(failed)
            )
    else:
        front = MockTof(default_distance=5.0)
        back = MockTof(default_distance=5.0)
        top = MockTof(default_distance=5.0)

    return MultiSensorTof(front=front, back=back, top=top)
