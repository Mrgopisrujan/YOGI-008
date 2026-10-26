"""
Actor stepping utility for Project AirSim.

Moves spawned GLB actors (e.g. humanoid subjects) smoothly along arbitrary
waypoints using direct world object pose updates (`set_object_pose`).
Avoids the Unreal Engine SIGSEGV crash caused by calling EnvActor APIs
on dynamic GLB static meshes.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Optional, Sequence

log = logging.getLogger(__name__)


class ActorStepper:
    """
    Synchronous and background stepper for dynamic actors in Project AirSim.
    Steps an actor forward along a waypoint loop at a specified ground speed.
    """

    def __init__(
        self,
        world: Any,
        actor_name: str,
        waypoints: Sequence[tuple[float, ...]],
        speed_mps: float = 1.0,
        z: float = 0.0,
        lock: Optional[Any] = None,
    ) -> None:
        self.world = world
        self.actor_name = actor_name
        self.speed_mps = float(speed_mps)
        self.z = float(z)
        self.lock = lock

        self._running: bool = False
        self._thread: Optional[threading.Thread] = None

        # Ensure waypoints are 3D tuples and closed
        self.pts = [
            tuple(w) + (self.z,) if len(w) == 2 else (float(w[0]), float(w[1]), float(w[2]))
            for w in waypoints
        ]
        if len(self.pts) < 2:
            raise ValueError("ActorStepper requires at least 2 waypoints")
        if self.pts[-1][:2] != self.pts[0][:2]:
            self.pts.append(self.pts[0])

        self.cur_x = float(self.pts[0][0])
        self.cur_y = float(self.pts[0][1])
        self.cur_z = float(self.pts[0][2])
        self.seg_idx = 0

        # Position actor at starting point facing the first waypoint segment
        dx = self.pts[1][0] - self.cur_x
        dy = self.pts[1][1] - self.cur_y
        # glTF model coordinate system has a 90-degree offset in Unreal Engine importer.
        # Moving along +Y (dy > 0, dx = 0) corresponds to yaw_deg = 0.0 in the sim world.
        yaw_deg = (math.degrees(math.atan2(dy, dx)) - 90.0) % 360.0
        self._set_pose(self.cur_x, self.cur_y, self.cur_z, yaw_deg)
        log.info(
            "ActorStepper: initialized %s at (%.2f, %.2f) facing %.1f deg",
            actor_name, self.cur_x, self.cur_y, yaw_deg,
        )

    @property
    def is_running(self) -> bool:
        """True if the background stepping thread is currently active."""
        return self._running

    def _set_pose(self, x: float, y: float, z: float, yaw_deg: float) -> bool:
        if self.world is None:
            return False
        try:
            from projectairsim.types import Pose

            half = math.radians(yaw_deg) * 0.5
            pose = Pose(
                {
                    "frame_id": "DEFAULT_ID",
                    "translation": {"x": float(x), "y": float(y), "z": float(z)},
                    "rotation": {"w": math.cos(half), "x": 0.0, "y": 0.0, "z": math.sin(half)},
                }
            )
            if self.lock is not None:
                with self.lock:
                    self.world.set_object_pose(self.actor_name, pose, teleport=True)
            else:
                self.world.set_object_pose(self.actor_name, pose, teleport=True)
            return True
        except Exception as e:
            log.debug("ActorStepper._set_pose failed: %s", e)
            return False

    def step(self, dt: float = 0.15) -> tuple[float, float, float]:
        """
        Advance the actor forward along the route by `speed_mps * dt`.
        Updates position and yaw heading in the simulator world.
        """
        target = self.pts[self.seg_idx + 1]
        dx = target[0] - self.cur_x
        dy = target[1] - self.cur_y
        dist = math.hypot(dx, dy)

        step_dist = self.speed_mps * dt
        if dist <= step_dist or dist < 1e-4:
            self.cur_x = float(target[0])
            self.cur_y = float(target[1])
            self.seg_idx = (self.seg_idx + 1) % (len(self.pts) - 1)
        else:
            self.cur_x += (dx / dist) * step_dist
            self.cur_y += (dy / dist) * step_dist

        next_target = self.pts[self.seg_idx + 1]
        yaw_deg = (math.degrees(math.atan2(next_target[1] - self.cur_y, next_target[0] - self.cur_x)) - 90.0) % 360.0
        self._set_pose(self.cur_x, self.cur_y, self.cur_z, yaw_deg)
        return (self.cur_x, self.cur_y, self.cur_z)

    def start(self, update_rate_hz: float = 10.0) -> None:
        """Start background daemon thread for continuous autonomous walking."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(update_rate_hz,),
            daemon=True,
            name=f"ActorStepper-{self.actor_name}",
        )
        self._thread.start()
        log.info(
            "ActorStepper: background thread started for %s at %.1f Hz",
            self.actor_name, update_rate_hz,
        )

    def stop(self) -> None:
        """Stop background stepping thread."""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None
        log.info("ActorStepper: stopped background thread for %s", self.actor_name)

    def _run_loop(self, rate_hz: float) -> None:
        interval = 1.0 / max(1.0, rate_hz)
        last_t = time.time()
        while self._running:
            now = time.time()
            dt = max(1e-4, now - last_t)
            last_t = now
            try:
                self.step(dt=dt)
            except Exception as e:
                log.debug("ActorStepper._run_loop step error: %s", e)
            time.sleep(interval)
