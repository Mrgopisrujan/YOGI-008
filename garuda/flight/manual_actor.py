"""
Manual actor controller for Project AirSim.

Allows direct interactive keyboard control of a spawned humanoid actor
(e.g. Walker1) in real-time. The user can steer the subject with WASD or
Arrow keys while an autonomous drone tracks and follows him.
"""
from __future__ import annotations

import logging
import math
import select
import sys
from typing import Any, Optional

log = logging.getLogger(__name__)


class ManualActorController:
    """
    Manages manual positioning and steering of a scene actor in Project AirSim.
    """

    def __init__(
        self,
        world: Any,
        actor_name: str,
        initial_pos: tuple[float, float, float] = (-1.0, 15.0, 0.0),
        initial_yaw_deg: float = 90.0,
        step_distance_m: float = 0.5,
        turn_angle_deg: float = 15.0,
    ) -> None:
        self.world = world
        self.actor_name = actor_name
        self.x = float(initial_pos[0])
        self.y = float(initial_pos[1])
        self.z = float(initial_pos[2])
        self.yaw_deg = float(initial_yaw_deg) % 360.0
        self.step_distance_m = float(step_distance_m)
        self.turn_angle_deg = float(turn_angle_deg)
        self.total_distance_m: float = 0.0
        self.sync_pose()

    def sync_pose(self) -> bool:
        """Send current position and orientation to the Project AirSim simulator."""
        if self.world is None:
            return False
        try:
            from projectairsim.types import Pose

            half = math.radians(self.yaw_deg) * 0.5
            pose = Pose(
                {
                    "frame_id": "DEFAULT_ID",
                    "translation": {"x": self.x, "y": self.y, "z": self.z},
                    "rotation": {"w": math.cos(half), "x": 0.0, "y": 0.0, "z": math.sin(half)},
                }
            )
            self.world.set_object_pose(self.actor_name, pose, teleport=True)
            return True
        except Exception as e:
            log.debug("ManualActorController.sync_pose failed: %s", e)
            return False

    def move_forward(self, distance: Optional[float] = None) -> tuple[float, float, float]:
        """Move the actor forward in the direction he is currently facing."""
        d = self.step_distance_m if distance is None else float(distance)
        rad = math.radians(self.yaw_deg)
        self.x += d * math.cos(rad)
        self.y += d * math.sin(rad)
        self.total_distance_m += abs(d)
        self.sync_pose()
        return (self.x, self.y, self.z)

    def move_backward(self, distance: Optional[float] = None) -> tuple[float, float, float]:
        """Move the actor backward relative to current heading."""
        d = self.step_distance_m if distance is None else float(distance)
        rad = math.radians(self.yaw_deg)
        self.x -= d * math.cos(rad)
        self.y -= d * math.sin(rad)
        self.total_distance_m += abs(d)
        self.sync_pose()
        return (self.x, self.y, self.z)

    def turn_left(self, angle: Optional[float] = None) -> float:
        """Turn the actor to the left (counter-clockwise)."""
        a = self.turn_angle_deg if angle is None else float(angle)
        self.yaw_deg = (self.yaw_deg - a) % 360.0
        self.sync_pose()
        return self.yaw_deg

    def turn_right(self, angle: Optional[float] = None) -> float:
        """Turn the actor to the right (clockwise)."""
        a = self.turn_angle_deg if angle is None else float(angle)
        self.yaw_deg = (self.yaw_deg + a) % 360.0
        self.sync_pose()
        return self.yaw_deg

    def handle_command(self, cmd: str) -> bool:
        """
        Process a key or direction string ('UP', 'DOWN', 'LEFT', 'RIGHT', 'W', 'S', 'A', 'D').
        Returns True if the actor moved or turned.
        """
        c = cmd.upper().strip()
        if c in ("UP", "W", "FORWARD"):
            self.move_forward()
            return True
        elif c in ("DOWN", "S", "BACKWARD", "BACK"):
            self.move_backward()
            return True
        elif c in ("LEFT", "A"):
            self.turn_left()
            return True
        elif c in ("RIGHT", "D"):
            self.turn_right()
            return True
        return False

    @property
    def pose(self) -> dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "yaw_deg": self.yaw_deg,
            "distance_m": self.total_distance_m,
        }


def read_single_key(timeout: float = 0.05) -> Optional[str]:
    """
    Non-blocking read of a single key from standard input on POSIX.
    Handles standard letters ('w', 's', 'a', 'd', 'q', ' ') and arrow keys.
    Returns normalized string like 'UP', 'DOWN', 'LEFT', 'RIGHT', 'W', 'S', etc.
    """
    if not sys.stdin.isatty():
        return None

    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            rlist, _, _ = select.select([sys.stdin], [], [], timeout)
            if not rlist:
                return None
            ch = sys.stdin.read(1)
            # Handle ANSI escape sequence for arrow keys: \x1b[A, \x1b[B, \x1b[C, \x1b[D
            if ch == "\x1b":
                r2, _, _ = select.select([sys.stdin], [], [], 0.02)
                if r2:
                    ch2 = sys.stdin.read(1)
                    if ch2 == "[":
                        ch3 = sys.stdin.read(1)
                        if ch3 == "A":
                            return "UP"
                        elif ch3 == "B":
                            return "DOWN"
                        elif ch3 == "C":
                            return "RIGHT"
                        elif ch3 == "D":
                            return "LEFT"
                return "ESC"
            if ch == " ":
                return "SPACE"
            return ch.upper()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except Exception as e:
        log.debug("read_single_key error: %s", e)
        return None


class TerminalKeyReader:
    """Context manager for asynchronous terminal key reading."""

    def __init__(self, poll_interval: float = 0.05) -> None:
        import queue
        self.poll_interval = poll_interval
        self._key_queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> TerminalKeyReader:
        import threading
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)

    def _worker(self) -> None:
        while self._running:
            k = read_single_key(timeout=self.poll_interval)
            if k:
                self._key_queue.put(k)

    def get_key(self) -> Optional[str]:
        import queue
        try:
            return self._key_queue.get_nowait()
        except queue.Empty:
            return None

