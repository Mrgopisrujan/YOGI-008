"""
GarudaOne DroneOS — Valdrada (Boundless NYC) Flight Backend
============================================================

Adapter that lets GarudaOS run its cinematic follow loop inside the
Valdrada NYC digital twin
(https://github.com/mkturkcan/boundless-nyc), rendered through
Unreal Engine 5.8.4.

Valdrada speaks its own CARLA-style Python API over TCP port 2000 — it is
NOT an AirSim/RPC server. This module wraps the ``valdrada`` Python client so
the rest of GarudaOS (FollowController, SubjectLock, ObstacleAvoider, shot
planner) keeps talking the transport-agnostic ``FlightBackend`` protocol and
needs no changes.

Why Valdrada instead of CityEnviron / AirSim:
  * The city is already populated: pedestrians, taxis, buses, school buses,
    MTA buses, emergency vehicles — no need to spawn rigged humans (the
    open blocker that killed person-following in CityEnviron).
  * Pixel-exact perception ground truth: RGB + instance segmentation +
    semantic segmentation + metric depth, all synchronised.
  * Full five-borough NYC at building-level detail, compiled from public
    municipal records.

Coordinate frames
-----------------
Valdrada uses ENU metres (x east, y north, z up). Garuda's control law and
the FlightBackend contract use NED (+z down, camera forward +X at yaw 0,
bearing = atan2(dy, dx), positive yaw turns right). This backend converts
every value at the boundary so the control loop never sees ENU.

The "drone"
-----------
Valdrada is a streetscape twin, not a drone simulator, so it may not ship a
quadrotor blueprint. We therefore fly kinematically: a platform actor (a
possessed vehicle if one exists, otherwise the spectator camera) is the
drone's camera platform and its transform is updated each tick from the
body-frame velocity command. Both code paths expose a transform, so the
backend is identical either way.

Traps (re-learned from the AirSim port, repeated here to avoid re-learning):
  * Synchronous mode: ``apply_settings(WorldSettings(synchronous_mode=True,
    fixed_delta_seconds=...))`` then ``world.tick()`` drives the sim. Frames
    only publish when the clock is stepped.
  * Cameras are pub/sub: ``cam.listen(callback)``. The callback must not
    block — frame buffers are written, not parsed, on the socket thread.
  * Valdrada images are BGRA uint8; drop the alpha channel to get BGR for YOLO.
  * Depth is encoded as a 24-bit integer across R/G/B; decode to metres.
  * NED is +z down: climbing is negative vz in the control law.
  * Any sustained yaw disengages the altitude hold (same failure as Project
    AirSim) — yaw is pulsed in short bursts with a hover between them.
"""

from __future__ import annotations

import atexit
import logging
import math
import threading
from typing import Any, Optional

import numpy as np

log = logging.getLogger("valdrada_client")

try:
    import valdrada
    from valdrada import (
        Client,
        Location,
        Rotation,
        Transform,
        WorldSettings,
    )
    VALDRADA_AVAILABLE = True
except ImportError:  # pragma: no cover - client is optional
    valdrada = None
    Client = Location = Rotation = Transform = WorldSettings = None
    VALDRADA_AVAILABLE = False

# Valdrada simulation server (CARLA-style TCP API).
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 2000

# Control tick the follow loop expects (s).
TICK_S = 0.20

# Yaw burst parameters mirroring garuda/flight/pas_client.py. Sustained yaw
# disengages the hover controller; short pulses do not.
BURST_S = 0.12
DEG_PER_BURST = 20.0
MAX_BURSTS = 4

# Candidate quadrotor blueprint IDs, in case Valdrada ships one.
_DRONE_BLUEPRINTS = ("vehicle.drone.quadrotor", "vehicle.quadrotor", "vehicle.drone")


def clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


class _FrameBuffer:
    """Thread-safe latest-frame holder for pub/sub camera callbacks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rgb: Optional[np.ndarray] = None
        self._depth: Optional[np.ndarray] = None

    def put_rgb(self, arr: np.ndarray) -> None:
        with self._lock:
            self._rgb = arr

    def put_depth(self, arr: np.ndarray) -> None:
        with self._lock:
            self._depth = arr

    def get_rgb(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._rgb

    def get_depth(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._depth


class ValdradaBackend:
    """
    FlightBackend implementation on top of the Valdrada (Boundless NYC)
    Python client.

    Mirrors ``garuda.flight.airsim_client.AirSimClient`` and
    ``garuda.flight.pas_client.ProjectAirSimBackend`` so the follow loop
    stays transport-agnostic. Every public method is blocking and serialised
    by one re-entrant lock.

    Example::

        from garuda.flight.valdrada_client import ValdradaBackend
        b = ValdradaBackend()
        b.connect()
        b.takeoff(altitude_m=4.0)
        frame = b.get_forward_camera()
        b.move_velocity_body(vx=1.0, vy=0.0, vz=0.0, yaw_rate_dps=20.0)
        b.close()
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        synchronous: bool = True,
        fixed_delta_seconds: float = 0.05,
        camera_width: int = 640,
        camera_height: int = 480,
        camera_fov: float = 90.0,
    ) -> None:
        if not VALDRADA_AVAILABLE:
            raise RuntimeError(
                "valdrada is not installed. Install the PythonAPI from "
                "https://github.com/mkturkcan/boundless-nyc (PythonAPI/) "
                "(or pip install the published valdrada wheel)."
            )
        self.host = host
        self.port = port
        self.synchronous = synchronous
        self.fixed_delta_seconds = fixed_delta_seconds
        self.camera_width = camera_width
        self.camera_height = camera_height
        self.camera_fov = camera_fov

        self._client: Any = None
        self._world: Any = None
        self._map: Any = None
        self._spectator: Any = None
        self._drone_actor: Any = None  # possessed vehicle, if one exists
        self._rgb_cam: Any = None
        self._depth_cam: Any = None
        self._frames = _FrameBuffer()
        self._lock = threading.RLock()

        # Latest platform transform (ENU), refreshed each tick.
        self._location: Any = None
        self._rotation: Any = None

        self.is_connected = False
        self._in_air = False
        self._target_alt: Optional[float] = None
        self._altitude_m: float = 0.0

        atexit.register(self.close)

    # ── lifecycle ──────────────────────────────────────────────────────
    def connect(self, timeout: float = 60.0) -> bool:
        """Connect to the Valdrada server, load the NYC world, and open cameras."""
        with self._lock:
            if self.is_connected:
                return True
            try:
                self._client = Client(self.host, self.port)
                self._client.set_timeout(timeout)
                self._world = self._client.get_world()

                if self.synchronous:
                    settings = self._world.get_settings()
                    settings.synchronous_mode = True
                    settings.fixed_delta_seconds = self.fixed_delta_seconds
                    self._world.apply_settings(settings)

                self._map = self._world.get_map()
                self._spectator = self._world.get_spectator()

                # Possess a quadrotor blueprint if Valdrada ships one; otherwise
                # fall back to kinematic spectator movement.
                self._possess_drone()

                self._spawn_cameras()

                # Start at a sensible follow pose: 4 m AGL over a street.
                self._set_platform_transform(east=0.0, north=0.0, up=4.0, yaw_deg=0.0)

                if self.synchronous:
                    self._world.tick()

                self.is_connected = True
                self._in_air = True
                self._target_alt = 4.0
                self._altitude_m = 4.0
                log.info(
                    "Valdrada connected: host=%s:%d map=%s",
                    self.host, self.port,
                    getattr(self._map, "name", "NYC"),
                )
                return True
            except Exception as e:
                log.error("Valdrada connect failed: %s: %s", type(e).__name__, e)
                self.is_connected = False
                return False

    def _possess_drone(self) -> None:
        """Possess a quadrotor blueprint if Valdrada ships one; else None."""
        try:
            lib = self._world.get_blueprint_library()
            spawns = self._map.get_spawn_points() if self._map is not None else []
            spawn = spawns[0] if spawns else None
            for bp_id in _DRONE_BLUEPRINTS:
                try:
                    bp = lib.find(bp_id)
                except Exception:
                    continue
                if spawn is None:
                    continue
                actor = self._world.try_spawn_actor(bp, spawn)
                if actor is not None:
                    self._drone_actor = actor
                    log.info("Possessed Valdrada vehicle %s", bp_id)
                    return
        except Exception as e:
            log.debug(
                "No possessable drone blueprint (%s); flying spectator kinematically", e
            )
        self._drone_actor = None

    def _platform_actor(self) -> Any:
        """The actor the cameras attach to: the drone, or the spectator."""
        return self._drone_actor if self._drone_actor is not None else self._spectator

    def _spawn_cameras(self) -> None:
        """Spawn RGB + depth cameras attached to the platform."""
        lib = self._world.get_blueprint_library()
        # Mount matches the verified CityEnviron geometry: forward of the props,
        # slightly pitched down, out of the airframe.
        cam_transform = Transform(
            Location(x=0.48, y=0.0, z=-0.08),
            Rotation(pitch=-3.0, roll=0.0, yaw=0.0),
        )

        rgb_bp = lib.find("sensor.camera.rgb")
        rgb_bp.set_attribute("image_size_x", str(self.camera_width))
        rgb_bp.set_attribute("image_size_y", str(self.camera_height))
        rgb_bp.set_attribute("fov", str(self.camera_fov))
        self._rgb_cam = self._world.spawn_actor(
            rgb_bp, cam_transform, attach_to=self._platform_actor()
        )
        self._rgb_cam.listen(lambda image: self._on_rgb(image))

        depth_bp = lib.find("sensor.camera.depth")
        depth_bp.set_attribute("image_size_x", str(self.camera_width))
        depth_bp.set_attribute("image_size_y", str(self.camera_height))
        depth_bp.set_attribute("fov", str(self.camera_fov))
        self._depth_cam = self._world.spawn_actor(
            depth_bp, cam_transform, attach_to=self._platform_actor()
        )
        self._depth_cam.listen(lambda image: self._on_depth(image))

    def _on_rgb(self, image: Any) -> None:
        """Pub/sub callback: decode a Valdrada BGRA frame to BGR uint8."""
        try:
            arr = np.frombuffer(image.raw_data, dtype=np.uint8)
            arr = arr.reshape((image.height, image.width, 4))
            bgr = arr[:, :, :3]  # Valdrada is BGRA; drop alpha
            self._frames.put_rgb(np.ascontiguousarray(bgr))
        except Exception as e:
            log.debug("rgb frame decode failed: %s", e)

    def _on_depth(self, image: Any) -> None:
        """Pub/sub callback: decode metric depth to float32 metres."""
        try:
            arr = np.frombuffer(image.raw_data, dtype=np.uint8)
            arr = arr.reshape((image.height, image.width, 4))
            # Valdrada depth encodes a 24-bit integer across R/G/B.
            raw = (
                arr[:, :, 0].astype(np.float32)
                + arr[:, :, 1].astype(np.float32) * 256.0
                + arr[:, :, 2].astype(np.float32) * 65536.0
            )
            metres = (raw / 16777216.0) * 1000.0
            self._frames.put_depth(np.ascontiguousarray(metres))
        except Exception as e:
            log.debug("depth frame decode failed: %s", e)

    def close(self) -> None:
        with self._lock:
            try:
                for cam in (self._rgb_cam, self._depth_cam):
                    if cam is not None:
                        try:
                            cam.destroy()
                        except Exception:
                            pass
                if self._drone_actor is not None:
                    try:
                        self._drone_actor.destroy()
                    except Exception:
                        pass
                if self.synchronous and self._world is not None:
                    settings = self._world.get_settings()
                    settings.synchronous_mode = False
                    self._world.apply_settings(settings)
            except Exception as e:
                log.debug("close error: %s", e)
            finally:
                self.is_connected = False
                self._in_air = False

    # ── clock ──────────────────────────────────────────────────────────
    def tick(self) -> None:
        """Step the simulation clock once. Call once per control tick in sync mode."""
        if self.synchronous and self._world is not None:
            self._world.tick()

    # ── FlightBackend surface ──────────────────────────────────────────
    def get_forward_camera(self) -> Optional[np.ndarray]:
        """Forward-facing RGB frame (BGR uint8), or None."""
        return self._frames.get_rgb()

    def get_forward_depth(self) -> Optional[np.ndarray]:
        """Metric depth map (h, w) float32 metres, or None."""
        return self._frames.get_depth()

    def get_telemetry(self) -> dict[str, Any]:
        with self._lock:
            if not self.is_connected:
                return {"connected": False}
            try:
                t = self._platform_actor().get_location()
                r = self._platform_actor().get_rotation()
                # ENU (x=east, y=north, z=up) -> NED (x=north, y=east, z=down)
                ned_x = float(t.y)
                ned_y = float(t.x)
                ned_z = -float(t.z)
                return {
                    "connected": True,
                    "x": ned_x,
                    "y": ned_y,
                    "z": ned_z,
                    "alt_agl": self._altitude_m,
                    "in_air": self._in_air,
                    "yaw_deg": float(r.yaw) % 360.0,
                }
            except Exception as e:
                log.debug("telemetry failed: %s", e)
                return {"connected": True, "in_air": self._in_air}

    def is_in_air(self) -> bool:
        return self._in_air

    def takeoff(self, altitude_m: float = 4.0) -> bool:
        """Kinematic takeoff: lift the platform to ``altitude_m`` AGL."""
        with self._lock:
            if not self.is_connected:
                return False
            try:
                t = self._platform_actor().get_location()
                r = self._platform_actor().get_rotation()
                steps = max(1, int(abs(float(altitude_m) - float(t.z)) / 0.5))
                for i in range(1, steps + 1):
                    frac = i / steps
                    self._set_platform_transform(
                        east=float(t.y),
                        north=float(t.x),
                        up=float(t.z) + (float(altitude_m) - float(t.z)) * frac,
                        yaw_deg=float(r.yaw),
                    )
                    if self.synchronous:
                        self._world.tick()
                self._in_air = True
                self._target_alt = float(altitude_m)
                self._altitude_m = float(altitude_m)
                log.info("Valdrada takeoff complete, %.2f m AGL", altitude_m)
                return True
            except Exception as e:
                log.error("takeoff failed: %s: %s", type(e).__name__, e)
                return False

    def hover(self) -> bool:
        """Hold station: re-issue the current position with zero velocity."""
        with self._lock:
            if not self.is_connected:
                return False
            try:
                self._hold_position()
                return True
            except Exception as e:
                log.debug("hover failed: %s", e)
                return False

    def move_velocity_body(
        self,
        vx: float = 0.0,
        vy: float = 0.0,
        vz: float = 0.0,
        yaw_rate_dps: float = 0.0,
        duration_s: float = 0.2,
    ) -> bool:
        """
        Body-frame velocity for one tick, kinematically applied to the platform.

        Garuda uses NED: vx forward, vy right, vz positive-down, yaw_rate
        deg/s. Valdrada platform uses ENU. Convert body-frame forward/right
        (rotated by yaw) into ENU east/north; vz down => -up.

        Altitude-hold trim mirrors pas_client.py: the caller's ``vz`` is a
        trim bias on top of a proportional altitude-hold term, clamped so it
        cannot drive the platform into the ground.

        Yaw is pulsed (never sustained) because a sustained yaw-rate command
        disengages the hover controller and the platform free-falls.
        """
        with self._lock:
            if not self.is_connected:
                return False
            try:
                t = self._platform_actor().get_location()
                r = self._platform_actor().get_rotation()
                yaw = math.radians(float(r.yaw))

                # Body-frame (forward, right) -> world (east, north).
                east = vx * math.cos(yaw) - vy * math.sin(yaw)
                north = vx * math.sin(yaw) + vy * math.cos(yaw)
                # vz is positive-down in NED; Valdrada up is positive => -vz.
                up = -vz

                new_east = float(t.x) + east * duration_s
                new_north = float(t.y) + north * duration_s
                new_up = float(t.z) + up * duration_s

                # Altitude-hold trim so a bare velocity command cannot drift into
                # the pavement (three consecutive ticks previously sank 6.36 ->
                # 3.23 -> -0.56 m).
                if self._target_alt is not None:
                    err = self._target_alt - new_up  # >0 = below target
                    new_up += clamp(err * 1.2, -1.5, 1.5)
                new_up = clamp(new_up, 0.5, 200.0)

                new_yaw = float(r.yaw)
                if abs(float(yaw_rate_dps)) >= 6.0:
                    # Translate first, then pulse the yaw. Running them
                    # concurrently does not help: the yaw path drops the vehicle.
                    self._yaw_burst(float(yaw_rate_dps), duration_s)
                    new_yaw = float(r.yaw)  # re-read after the burst

                self._set_platform_transform(
                    east=new_east, north=new_north, up=new_up, yaw_deg=new_yaw
                )
                if self.synchronous:
                    self._world.tick()

                self._altitude_m = new_up
                return True
            except Exception as e:
                log.debug("move_velocity_body failed: %s", e)
                return False

    def _hold_position(self) -> None:
        """Re-issue the current transform (zero movement) and tick."""
        t = self._platform_actor().get_location()
        r = self._platform_actor().get_rotation()
        self._set_platform_transform(
            east=float(t.y), north=float(t.x), up=float(t.z), yaw_deg=float(r.yaw)
        )
        if self.synchronous:
            self._world.tick()

    def _yaw_burst(self, rate_dps: float, duration_s: float) -> None:
        """Pulse yaw briefly then re-hold, to avoid the free-fall failure."""
        t = self._platform_actor().get_location()
        r = self._platform_actor().get_rotation()
        steps = max(1, int(duration_s / BURST_S))
        for _ in range(steps):
            new_yaw = (float(r.yaw) + rate_dps * BURST_S) % 360.0
            self._set_platform_transform(
                east=float(t.y), north=float(t.x), up=float(t.z), yaw_deg=new_yaw
            )
            if self.synchronous:
                self._world.tick()
            r = self._platform_actor().get_rotation()

    def _set_platform_transform(
        self, east: float, north: float, up: float, yaw_deg: float
    ) -> None:
        """Teleport the drone platform to an ENU transform."""
        transform = Transform(
            Location(x=east, y=north, z=up),
            Rotation(yaw=yaw_deg, pitch=0.0, roll=0.0),
        )
        actor = self._drone_actor if self._drone_actor is not None else self._spectator
        actor.set_transform(transform)
        self._location = transform.location
        self._rotation = transform.rotation

    # ── optional shot-pitch bias (used by FollowController) ──────────────
    def set_camera_pitch(self, pitch_deg: float, camera_name: str = "front_center") -> bool:
        """Tilt the camera without moving the airframe (low/high angle shots)."""
        try:
            cam = self._rgb_cam
            tr = cam.get_transform()
            tr.rotation.pitch = float(pitch_deg)
            cam.set_transform(tr)
            return True
        except Exception as e:
            log.debug("set_camera_pitch failed: %s", e)
            return False
