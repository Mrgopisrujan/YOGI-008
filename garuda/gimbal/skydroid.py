"""Skydroid C10 Pro gimbal control — real UDP protocol.

Uses the confirmed UDP command protocol (not MAVLink) to control the
Skydroid/Topotek C10 gimbal camera over Ethernet.

Network:
  Camera IP: 192.168.144.108
  Control port: UDP 5000
  RTSP video: rtsp://192.168.144.108:554/stream=0

Protocol: ASCII commands with checksum, sent as UDP datagrams.
Command format: #TP{TYPE}{RW}{CMD}{PARAMS}{CHECKSUM}

Based on https://github.com/aatonovaz/skydroid-c10-gimbal-control
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_HOST = "192.168.144.108"
DEFAULT_PORT = 5000
HEARTBEAT_TIMEOUT_S = 1.0
STATUS_QUERY_BASE = "#TPUD2rSDC00"


def _checksum(text: str) -> str:
    """Compute UDP protocol checksum (sum of ASCII bytes & 0xFF)."""
    return f"{sum(text.encode('ascii')) & 0xFF:02X}"


def _frame(base: str) -> bytes:
    """Build a complete command packet with checksum."""
    return f"{base}{_checksum(base)}".encode("ascii")


def _speed_hex(speed: int) -> str:
    """Convert speed (-99..99) to hex byte."""
    if speed < -99 or speed > 99:
        raise ValueError("speed must be in -99..99")
    return f"{speed & 0xFF:02X}"


# Feature command bases (from APK reverse engineering)
FEATURE_BASES = {
    "photo": "#TPUD2wCAP01",
    "record-start": "#TPUD2wREC01",
    "record-stop": "#TPUD2wREC00",
    "record-toggle": "#TPUD2wREC0A",
    "zoom-stop": "#TPUM2wZMC00",
    "zoom-in": "#TPUM2wZMC01",
    "zoom-out": "#TPUM2wZMC02",
    "focus-stop": "#TPUM2wFCC00",
    "focus-add": "#TPUM2wFCC01",
    "focus-reduce": "#TPUM2wFCC02",
    "ptz-follow": "#TPUG2wPTZ06",
    "ptz-lock-head": "#TPUG2wPTZ07",
    "ptz-follow-switch": "#TPUG2wPTZ08",
    "ptz-calibration": "#TPUG2wPTZ09",
}


@dataclass
class GimbalState:
    """Current gimbal state."""
    yaw_speed: int = 0  # -99..99
    pitch_speed: int = 0  # -99..99
    last_heartbeat: float = 0.0
    last_command: float = 0.0
    recording: bool = False
    zoom_level: int = 0  # 0=1x, 1=zoom in, 2=zoom out
    mode: str = "follow"  # follow, lock-head


class SkydroidGimbal:
    """Real Skydroid C10 gimbal control via UDP.

    Sends movement, recording, zoom, and PTZ mode commands over UDP.
    A local UDP socket or successful send is not device evidence. The backend
    reports connected/heartbeat only after an inbound device response is
    supplied via ``mark_device_response``.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        socket_factory: Callable[..., socket.socket] = socket.socket,
    ):
        self._host = host
        self._port = port
        self._socket_factory = socket_factory
        self._sock: socket.socket | None = None
        self._state = GimbalState()
        self._lock = threading.Lock()
        self._transport_ready = False
        self._device_verified = False

    def connect(self) -> bool:
        """Create the local UDP transport without claiming device presence."""
        try:
            self._sock = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(0.5)
            self._transport_ready = True
            self._device_verified = False
            self._state.last_heartbeat = 0.0
            logger.info("Skydroid UDP transport ready: %s:%s", self._host, self._port)
            return True
        except Exception as e:
            logger.error(f"Skydroid connect failed: {e}")
            return False

    def disconnect(self):
        """Close the UDP socket."""
        if self._sock:
            self.stop()
            self._sock.close()
            self._sock = None
        self._transport_ready = False
        self._device_verified = False
        self._state.last_heartbeat = 0.0

    @property
    def transport_ready(self) -> bool:
        return self._transport_ready and self._sock is not None

    @property
    def is_connected(self) -> bool:
        return self.transport_ready and self._device_verified

    @property
    def heartbeat_ok(self) -> bool:
        """Check if gimbal heartbeat is recent."""
        return (
            self.is_connected
            and self._state.last_heartbeat > 0.0
            and time.monotonic() - self._state.last_heartbeat < HEARTBEAT_TIMEOUT_S
        )

    def mark_device_response(self, payload: bytes) -> None:
        """Record independently observed inbound device evidence."""
        if not self.transport_ready:
            raise RuntimeError("Skydroid UDP transport is not ready")
        if not payload:
            raise ValueError("empty payload is not device evidence")
        self._device_verified = True
        self._state.last_heartbeat = time.monotonic()

    @staticmethod
    def _valid_reply(payload: bytes) -> bool:
        try:
            text = payload.decode("ascii")
        except UnicodeDecodeError:
            return False
        if len(text) < 3 or "SDC" not in text.upper():
            return False
        return _checksum(text[:-2]) == text[-2:].upper()

    def probe_device(self, timeout_s: float = 0.5) -> bool:
        """Send the benign SD/status query and require a checksummed reply."""
        if not self.transport_ready or self._sock is None:
            return False
        try:
            self._sock.settimeout(timeout_s)
            self._sock.sendto(_frame(STATUS_QUERY_BASE), (self._host, self._port))
            payload, address = self._sock.recvfrom(2048)
            if address[0] != self._host or not self._valid_reply(payload):
                return False
            self.mark_device_response(payload)
            return True
        except (TimeoutError, OSError):
            return False

    def poll_status(self, timeout_s: float = 0.05) -> bool:
        """Refresh checksummed inbound device evidence during runtime."""
        return self.probe_device(timeout_s=timeout_s)

    @property
    def name(self) -> str:
        return "skydroid_c10_udp"

    @property
    def state(self) -> GimbalState:
        return self._state

    def _send(self, payload: bytes):
        """Send a UDP packet to the gimbal."""
        if not self._sock:
            logger.warning("Skydroid not connected — command dropped")
            return
        with self._lock:
            try:
                self._sock.sendto(payload, (self._host, self._port))
                self._state.last_command = time.monotonic()
            except Exception as e:
                logger.error(f"Skydroid send error: {e}")

    def set_yaw_speed(self, speed: int):
        """Set yaw rotation speed (-99..99, 0=stop)."""
        self._state.yaw_speed = max(-99, min(99, speed))
        self._send(_frame(f"#TPUG2wGSY{_speed_hex(self._state.yaw_speed)}"))

    def set_pitch_speed(self, speed: int):
        """Set pitch rotation speed (-99..99, 0=stop)."""
        self._state.pitch_speed = max(-99, min(99, speed))
        self._send(_frame(f"#TPUG2wGSP{_speed_hex(self._state.pitch_speed)}"))

    def set_pitch_yaw(self, pitch_speed: int, yaw_speed: int):
        """Set both pitch and yaw speeds simultaneously."""
        self.set_yaw_speed(yaw_speed)
        self.set_pitch_speed(pitch_speed)

    def stop(self):
        """Stop all gimbal movement."""
        self._state.yaw_speed = 0
        self._state.pitch_speed = 0
        self._send(_frame("#TPUG2wPTZ00"))

    def center(self):
        """Center the gimbal (go to neutral position)."""
        self._send(_frame("#TPUG2wPTZ05"))
        self._state.yaw_speed = 0
        self._state.pitch_speed = 0

    def set_mode_follow(self):
        """Set gimbal to follow mode (stabilized, follows drone heading)."""
        self._send(_frame(FEATURE_BASES["ptz-follow"]))
        self._state.mode = "follow"

    def set_mode_lock(self):
        """Set gimbal to lock-head mode (stays pointed at target regardless of drone heading)."""
        self._send(_frame(FEATURE_BASES["ptz-lock-head"]))
        self._state.mode = "lock-head"

    def start_recording(self):
        """Start video recording."""
        self._send(_frame(FEATURE_BASES["record-start"]))
        self._state.recording = True

    def stop_recording(self):
        """Stop video recording."""
        self._send(_frame(FEATURE_BASES["record-stop"]))
        self._state.recording = False

    def zoom_in(self, hold_s: float = 0.5):
        """Zoom in for a duration."""
        self._send(_frame(FEATURE_BASES["zoom-in"]))
        if hold_s > 0:
            time.sleep(hold_s)
            self.zoom_stop()

    def zoom_out(self, hold_s: float = 0.5):
        """Zoom out for a duration."""
        self._send(_frame(FEATURE_BASES["zoom-out"]))
        if hold_s > 0:
            time.sleep(hold_s)
            self.zoom_stop()

    def zoom_stop(self):
        """Stop zooming."""
        self._send(_frame(FEATURE_BASES["zoom-stop"]))

    def take_photo(self):
        """Capture a single photo."""
        self._send(_frame(FEATURE_BASES["photo"]))

    def calibrate(self):
        """Run gimbal calibration."""
        self._send(_frame(FEATURE_BASES["ptz-calibration"]))

    def get_status(self) -> dict:
        """Get current gimbal status."""
        return {
            "transport_ready": self.transport_ready,
            "connected": self.is_connected,
            "heartbeat_ok": self.heartbeat_ok,
            "yaw_speed": self._state.yaw_speed,
            "pitch_speed": self._state.pitch_speed,
            "mode": self._state.mode,
            "recording": self._state.recording,
        }
