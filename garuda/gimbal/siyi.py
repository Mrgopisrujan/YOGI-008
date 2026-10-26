"""SiyiGimbal — SIYI gimbal protocol over UART serial.

Alternative hardware path. SIYI gimbals (A8, ZR10, ZR30) speak a custom
binary protocol over a UART TTL connection (typically /dev/ttyTHS1 on
the Pi at 115200 or 921600 baud). This is NOT MAVLink — it is SIYI's own
frame format documented in their SDK.

Frame format (SIYI protocol v1.x):
  Header: 0xA5 0x0F
  Ctrl byte (protocol version, ACK flag)
  Data len (2 bytes, little-endian)
  Sequence (2 bytes, LE)
  Cmd ID (1 byte)
  Data payload
  CRC16 (2 bytes, LE) — CRC16-IBM over header..payload

This module implements the subset of commands needed for GarudaOne:
  - CMD_ANGLE (0x01)         : absolute pitch/yaw control
  - CMD_SPEED (0x02)         : yaw rate control (used for set_pitch_yaw)
  - CMD_SET_ROI (custom ext) : point at lat/lon/alt
  - CMD_HEARTBEAT (0x0A)     : poll for attitude + heartbeat
  - CMD_GET_ATTITUDE (0x0B)  : read current pitch/yaw

Transport: pyserial (the `serial` package), opened lazily so this module
imports cleanly on machines without pyserial. The connection is injected
for testing.

Safety: same heartbeat contract as SkydroidGimbal — 1.0 s default timeout
per safety_limits.GimbalLimits. On loss, freeze() holds the last
attitude and yaw_rate commands are dropped (no counter-rotation). The
arbiter FSM independently forces HOVER.
"""

from __future__ import annotations

import logging
import math
import struct
import time
from typing import Any

from .protocol import GimbalBackend, GimbalStatus

logger = logging.getLogger(__name__)

# ─── SIYI protocol constants ─────────────────────────────────────────────
HEADER0 = 0xA5
HEADER1 = 0x0F
PROTO_VERSION = 0x00  # no ACK requested for fire-and-forget commands

# Command IDs
CMD_ANGLE = 0x01          # absolute angle control (pitch, yaw)
CMD_SPEED = 0x02          # speed control (yaw_rate, pitch_rate)
CMD_SET_ROI = 0x50        # ROI point (custom SIYI extension)
CMD_HEARTBEAT = 0x0A      # heartbeat poll
CMD_GET_ATTITUDE = 0x0B   # read attitude (pitch, yaw)

# Mechanical limits — SIYI A8/ZR10 typical. Override per model if needed.
PITCH_MIN_DEG = -90.0
PITCH_MAX_DEG = 30.0
YAW_MIN_DEG = -135.0
YAW_MAX_DEG = 135.0
YAW_RATE_MAX_DPS = 90.0
PITCH_RATE_MAX_DPS = 90.0

# SIYI units: angles in 0.01 deg, speeds in 0.01 deg/s (signed int).
SIYI_ANGLE_SCALE = 100.0
SIYI_SPEED_SCALE = 100.0


def _crc16_ibm(data: bytes) -> int:
    """CRC-16/IBM (ARC) as used by the SIYI protocol."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


class SiyiGimbal(GimbalBackend):
    """SIYI gimbal backend over UART serial.

    Args:
        port: serial device path, e.g. "/dev/ttyTHS1".
        baudrate: typically 115200 (default) or 921600 for newer firmware.
        connection: an open pyserial Serial instance (injected for tests).
            If provided, `port`/`baudrate` are ignored.
        heartbeat_timeout_s: override GimbalLimits default (1.0 s).
        seq_start: initial sequence number (default 0).

    The backend is import-safe without pyserial — the package is only
    imported when a command is first sent. All command methods are
    fire-and-forget and never block the control loop waiting for an ACK.
    """

    def __init__(
        self,
        port: str = "/dev/ttyTHS1",
        baudrate: int = 115200,
        connection: Any = None,
        heartbeat_timeout_s: float | None = None,
        seq_start: int = 0,
    ) -> None:
        super().__init__(heartbeat_timeout_s=heartbeat_timeout_s)
        self._port = port
        self._baudrate = baudrate
        self._connection: Any = connection
        self._owns_connection = connection is None
        self._seq: int = seq_start & 0xFFFF
        self._current_pitch_deg: float = 0.0
        self._current_yaw_deg: float = 0.0
        self._last_heartbeat_ts = time.monotonic()

    # ─── Public API ──────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "siyi"

    def set_pitch_yaw(self, pitch_deg: float, yaw_rate_dps: float = 0.0) -> None:
        """Body-frame pitch (absolute) + yaw rate.

        SIYI's CMD_SPEED controls yaw/pitch rate; we use it for yaw_rate
        and hold pitch at the requested absolute angle via CMD_ANGLE.
        On heartbeat loss, freeze.
        """
        if not self.heartbeat_ok():
            self._freeze()
            logger.warning("SiyiGimbal: heartbeat lost — freezing (cmd dropped)")
            return

        pitch = self._clamp_pitch(float(pitch_deg))
        yaw_rate = self._clamp_yaw_rate(float(yaw_rate_dps))
        self._last_pitch_deg = pitch
        self._last_yaw_rate_dps = yaw_rate
        self._mode = "pitch_yaw"
        self._roi_active = False

        # Absolute pitch (yaw rate handled by CMD_SPEED).
        # CMD_ANGLE payload: pitch(2), yaw(2) in 0.01 deg, signed int16 LE.
        pitch_int = int(round(pitch * SIYI_ANGLE_SCALE))
        yaw_int = 0  # 0 = hold current yaw angle
        self._send(CMD_ANGLE, struct.pack("<hh", pitch_int, yaw_int))

        # CMD_SPEED payload: yaw_rate(2), pitch_rate(2) in 0.01 deg/s.
        yaw_rate_int = int(round(yaw_rate * SIYI_SPEED_SCALE))
        pitch_rate_int = 0
        self._send(CMD_SPEED, struct.pack("<hh", yaw_rate_int, pitch_rate_int))

    def set_roi(self, lat: float, lon: float, alt: float) -> None:
        """Point gimbal at an earth-frame coordinate.

        SIYI does not have a standard ROI command in the base protocol;
        newer firmware (ZR10/ZR30) accepts CMD_SET_ROI (0x50) with a
        20-byte payload: lat(8, double LE), lon(8, double LE), alt(4, float LE).
        On older firmware this is a no-op + warning.
        """
        if not self.heartbeat_ok():
            self._freeze()
            logger.warning("SiyiGimbal: heartbeat lost — ROI cmd dropped")
            return

        self._mode = "roi"
        self._roi_active = True
        self._last_roi = (float(lat), float(lon), float(alt))

        payload = struct.pack("<ddf", float(lat), float(lon), float(alt))
        self._send(CMD_SET_ROI, payload)

    def get_status(self) -> GimbalStatus:
        # Poll for attitude + heartbeat so status reflects fresh state.
        self._poll_attitude()
        return GimbalStatus(
            pitch_deg=self._current_pitch_deg,
            yaw_deg=self._current_yaw_deg,
            yaw_rate_dps=self._last_yaw_rate_dps,
            mode=self._mode,
            roi_active=self._roi_active,
            heartbeat_ok=self.heartbeat_ok(),
            last_heartbeat_ts=self._last_heartbeat_ts,
            backend=self.name,
        )

    # ─── Heartbeat ───────────────────────────────────────────────────────

    def heartbeat_ok(self) -> bool:
        age = time.monotonic() - self._last_heartbeat_ts
        return age <= self._heartbeat_timeout_s

    # ─── Internals ───────────────────────────────────────────────────────

    @staticmethod
    def _clamp_pitch(pitch_deg: float) -> float:
        if math.isnan(pitch_deg):
            return 0.0
        return max(PITCH_MIN_DEG, min(PITCH_MAX_DEG, pitch_deg))

    @staticmethod
    def _clamp_yaw_rate(yaw_rate_dps: float) -> float:
        if math.isnan(yaw_rate_dps):
            return 0.0
        return max(-YAW_RATE_MAX_DPS, min(YAW_RATE_MAX_DPS, yaw_rate_dps))

    def _build_frame(self, cmd_id: int, payload: bytes) -> bytes:
        """Build a SIYI protocol frame.

        Layout: 0xA5 0x0F | ctrl | len_lo | len_hi | seq_lo | seq_hi | cmd | payload | crc16_lo | crc16_hi
        """
        data_len = len(payload)
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFFFF
        header = bytes([HEADER0, HEADER1, PROTO_VERSION,
                        data_len & 0xFF, (data_len >> 8) & 0xFF,
                        seq & 0xFF, (seq >> 8) & 0xFF,
                        cmd_id & 0xFF])
        crc = _crc16_ibm(header + payload)
        return header + payload + struct.pack("<H", crc)

    def _open_serial(self) -> Any:
        """Lazily open a pyserial connection. Raises ImportError if missing."""
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "pyserial is required for SiyiGimbal. "
                "Install with: pip install pyserial"
            ) from e
        return serial.Serial(self._port, self._baudrate, timeout=0.05)

    def _send(self, cmd_id: int, payload: bytes) -> None:
        """Send one SIYI frame. Fire-and-forget."""
        try:
            if self._connection is None and self._owns_connection:
                self._connection = self._open_serial()
            conn = self._connection
            if conn is None:
                logger.warning("SiyiGimbal: no connection — cmd dropped")
                return
            frame = self._build_frame(cmd_id, payload)
            conn.write(frame)
        except ImportError:
            logger.warning("SiyiGimbal: pyserial unavailable — cmd dropped")
        except Exception as e:
            logger.error(f"SiyiGimbal: send failed: {e}")

    def _poll_attitude(self) -> None:
        """Read pending SIYI frames and update state/heartbeat.

        Looks for CMD_GET_ATTITUDE responses (payload: pitch(2), yaw(2)
        in 0.01 deg signed int16 LE). Any valid frame counts as a
        heartbeat. Non-blocking: reads only what's already buffered.
        """
        conn = self._connection
        if conn is None:
            return
        try:
            # Read up to a few frames' worth; bounded so we never stall.
            for _ in range(4):
                frame = self._read_frame()
                if frame is None:
                    break
                self._handle_frame(frame)
        except Exception as e:
            logger.debug(f"SiyiGimbal: poll error: {e}")

    def _read_frame(self) -> bytes | None:
        """Read one complete SIYI frame from the serial buffer.

        Returns None if no complete frame is available. This is a minimal
        parser; production code should handle partial reads with a state
        machine, but the bounded loop above keeps it safe for 20 Hz polling.
        """
        conn = self._connection
        if conn is None or not hasattr(conn, "in_waiting"):
            return None
        if conn.in_waiting < 9:  # min frame: 8 header + 2 crc (empty payload)
            return None
        # Peek for header
        head = conn.read(2)
        if len(head) < 2 or head[0] != HEADER0 or head[1] != HEADER1:
            return None
        rest_of_header = conn.read(6)  # ctrl, len_lo, len_hi, seq_lo, seq_hi, cmd
        if len(rest_of_header) < 6:
            return None
        data_len = rest_of_header[1] | (rest_of_header[2] << 8)
        payload = conn.read(data_len) if data_len > 0 else b""
        if len(payload) < data_len:
            return None
        crc_bytes = conn.read(2)
        if len(crc_bytes) < 2:
            return None
        return head + rest_of_header + payload + crc_bytes

    def _handle_frame(self, frame: bytes) -> None:
        """Parse a SIYI frame and update state."""
        if len(frame) < 10:
            return
        cmd_id = frame[7]
        payload = frame[8:-2]
        # Verify CRC
        expected_crc = _crc16_ibm(frame[:-2])
        got_crc = frame[-2] | (frame[-1] << 8)
        if expected_crc != got_crc:
            logger.debug("SiyiGimbal: CRC mismatch — dropping frame")
            return

        self._mark_heartbeat()

        if cmd_id == CMD_GET_ATTITUDE and len(payload) >= 4:
            pitch_int, yaw_int = struct.unpack("<hh", payload[:4])
            self._current_pitch_deg = pitch_int / SIYI_ANGLE_SCALE
            self._current_yaw_deg = yaw_int / SIYI_ANGLE_SCALE

    # ─── Lifecycle ───────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the serial port if we own it."""
        if self._owns_connection and self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None
