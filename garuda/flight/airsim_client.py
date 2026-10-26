"""
GarudaOS — Live Unreal Engine & AirSim Client
=============================================
Manages the real-time RPC connection to Unreal Engine 5 via AirSim / Colosseum.

Capabilities:
  1. Live telemetry streaming (Position, Velocity, Orientation).
  2. Multi-camera frame retrieval:
     - Camera 1: 'front_center' (Forward Perception)
     - Camera 2: 'bottom_center' (Downward Odometry / Landing)
  3. Eagle-Eye 3rd-Person Observer Camera control.
  4. Autonomous flight commands (Takeoff, Position Waypoints, Velocity Vectors, Land).
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Optional

import numpy as np

log = logging.getLogger("airsim_client")

try:
    import airsim
    AIRSIM_AVAILABLE = True
except ImportError:
    airsim = None
    AIRSIM_AVAILABLE = False


class AirSimClient:
    """Interface to the Unreal Engine AirSim / Colosseum simulation environment."""

    def __init__(self, ip: str = "127.0.0.1", port: int = 41451, vehicle_name: str = "GarudaDrone"):
        self.ip = ip
        self.port = port
        self.vehicle_name = vehicle_name
        self.client: Optional[Any] = None
        self.is_connected = False
        self.home_position: tuple[float, float, float] = (0.0, 0.0, 1.60)

    def connect(self, timeout: float = 10.0) -> bool:
        """Connects to AirSim inside Unreal Engine."""
        if not AIRSIM_AVAILABLE:
            log.warning("[AirSimClient] 'airsim' package not installed. Run: pip install airsim")
            return False

        log.info(f"Connecting to Unreal Engine AirSim on {self.ip}:{self.port}...")
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                self.client = airsim.MultirotorClient(ip=self.ip, port=self.port)
                self.client.confirmConnection()
                self.client.enableApiControl(True, vehicle_name=self.vehicle_name)
                self.client.armDisarm(True, vehicle_name=self.vehicle_name)
                self.is_connected = True
                log.info(f"Connected to Unreal Engine! Vehicle [{self.vehicle_name}] armed & API control enabled.")
                return True
            except Exception as e:
                time.sleep(1.0)

        log.error("Failed to connect to Unreal Engine within timeout.")
        return False

    def get_forward_camera(self) -> Optional[np.ndarray]:
        """Fetches RGB image frame from Camera 1 ('front_center')."""
        return self._fetch_camera_frame("front_center")

    def get_downward_camera(self) -> Optional[np.ndarray]:
        """Fetches RGB image frame from Camera 2 ('bottom_center')."""
        return self._fetch_camera_frame("bottom_center")

    def _fetch_camera_frame(self, camera_name: str) -> Optional[np.ndarray]:
        if not self.is_connected or not self.client:
            return None
        try:
            responses = self.client.simGetImages(
                [airsim.ImageRequest(camera_name, airsim.ImageType.Scene, False, False)],
                vehicle_name=self.vehicle_name
            )
            if not responses or len(responses) == 0:
                return None
            response = responses[0]
            img1d = np.frombuffer(response.image_data_uint8, dtype=np.uint8)
            if img1d.size == 0:
                return None
            img_rgb = img1d.reshape(response.height, response.width, 3)
            return img_rgb
        except Exception as err:
            log.debug(f"Camera fetch error [{camera_name}]: {err}")
            return None

    def get_telemetry(self) -> dict[str, Any]:
        """Reads drone state from AirSim including 3D orientation Euler angles."""
        if not self.is_connected or not self.client:
            return {
                "connected": False,
                "x": 0.0, "y": 0.0, "z": 0.0,
                "vx": 0.0, "vy": 0.0, "vz": 0.0,
                "pitch": 0.0, "roll": 0.0, "yaw": 0.0, "yaw_deg": 0.0,
                "in_air": False
            }
        try:
            state = self.client.getMultirotorState(vehicle_name=self.vehicle_name)
            pos = state.kinematics_estimated.position
            vel = state.kinematics_estimated.linear_velocity
            orient = state.kinematics_estimated.orientation
            pitch, roll, yaw = airsim.to_eularian_angles(orient)
            landed = state.landed_state
            is_flying = bool(landed == airsim.LandedState.Flying and pos.z_val < 1.3)
            return {
                "connected": True,
                "x": pos.x_val,
                "y": pos.y_val,
                "z": -pos.z_val,  # AirSim NED coordinates: invert Z for altitude
                "alt_agl": round(1.60 - pos.z_val, 2),  # Altitude Above Ground Level
                "vx": vel.x_val,
                "vy": vel.y_val,
                "vz": -vel.z_val,
                "pitch": pitch,
                "roll": roll,
                "yaw": yaw,
                "yaw_deg": math.degrees(yaw),
                "in_air": is_flying
            }
        except Exception as e:
            log.warning(f"Error fetching telemetry: {e}")
            return {"connected": False}

    def is_in_air(self) -> bool:
        """Returns True if the drone is actively airborne and cleared of ground."""
        if not self.is_connected or not self.client:
            return False
        try:
            s = self.client.getMultirotorState(vehicle_name=self.vehicle_name)
            return bool(s.landed_state == airsim.LandedState.Flying and s.kinematics_estimated.position.z_val < 1.3)
        except Exception:
            return False

    def takeoff(self, altitude_m: float = 3.0):
        """Commands drone takeoff and hover at target altitude, re-arming motors if needed."""
        if not self.is_connected or not self.client:
            return
        log.info(f"Commanding takeoff to {altitude_m}m...")
        try:
            self.client.enableApiControl(True, vehicle_name=self.vehicle_name)
            self.client.armDisarm(True, vehicle_name=self.vehicle_name)
        except Exception:
            pass

        self.client.takeoffAsync(vehicle_name=self.vehicle_name).join()
        self.client.moveToZAsync(-altitude_m, velocity=2.0, vehicle_name=self.vehicle_name).join()

    def get_forward_depth(self, camera_name: str = "front_center") -> Optional[np.ndarray]:
        """
        Full DepthPerspective map from the front camera, shaped (h, w) metres.

        The obstacle avoider needs the whole image (not just a scalar) so it
        can tell left from right and decide which way to yield.
        """
        if not self.is_connected or not self.client:
            return None
        try:
            req = airsim.ImageRequest(camera_name, airsim.ImageType.DepthPerspective, True, False)
            responses = self.client.simGetImages([req], vehicle_name=self.vehicle_name)
            if not responses:
                return None
            res = responses[0]
            depth = np.array(res.image_data_float, dtype=np.float32).reshape(res.height, res.width)
            if depth.size == 0:
                return None
            return depth
        except Exception as e:
            log.debug(f"Depth map fetch error [{camera_name}]: {e}")
            return None

    def get_forward_obstacle_distance(self) -> float:
        """
        Calculates distance in meters to nearest obstacle in front center FOV
        using the onboard DepthPerspective camera sensor.
        """
        depth = self.get_forward_depth()
        if depth is None:
            return 999.0
        h, w = depth.shape[:2]
        # Central 50% sector of field of view
        center_box = depth[h//4:3*h//4, w//4:3*w//4]
        valid = center_box[(center_box > 0.3) & (center_box < 80.0)]
        if valid.size == 0:
            return 999.0
        return float(np.min(valid))

    def move_velocity_body(
        self,
        vx: float = 0.0,
        vy: float = 0.0,
        vz: float = 0.0,
        yaw_rate_dps: float = 0.0,
        duration_s: float = 0.2,
    ) -> bool:
        """
        Non-blocking body-frame velocity command. Used by the follow control
        loop, which issues one of these per tick; a blocking ``.join()`` here
        would cap the loop at the tick period and stall perception.
        """
        if not self.is_connected or not self.client:
            return False
        try:
            self.client.moveByVelocityBodyFrameAsync(
                vx=float(vx), vy=float(vy), vz=float(vz),
                duration=float(duration_s),
                yaw_mode=airsim.YawMode(is_rate=True, yaw_or_rate=float(yaw_rate_dps)),
                vehicle_name=self.vehicle_name,
            )
            return True
        except Exception as e:
            log.warning(f"Body velocity command failed: {e}")
            return False

    def hover(self) -> bool:
        """Stop all motion and hold station (non-blocking)."""
        if not self.is_connected or not self.client:
            return False
        try:
            self.client.hoverAsync(vehicle_name=self.vehicle_name)
            return True
        except Exception as e:
            log.debug(f"hoverAsync failed: {e}")
            return False

    def set_camera_pose(
        self,
        pitch_deg: float = -3.0,
        yaw_deg: float = 0.0,
        camera_name: str = "front_center",
    ) -> bool:
        """
        Aim the camera without moving or arming the airframe.

        ``simSetCameraPose`` is a pure camera transform: unlike ``rotate_yaw``
        it does not enable API control or arm the vehicle, so it is safe on the
        ground. Use it to point a camera at a scene object for calibration or
        marker validation.
        """
        if not self.is_connected or not self.client:
            return False
        try:
            # The pose offset must NOT move the camera: simSetCameraPose's
            # translation is relative to the settings.json mount, and supplying
            # one drags the sensor back inside the airframe. Pass zero so only
            # the rotation is overridden.
            self.client.simSetCameraPose(
                camera_name,
                airsim.Pose(
                    airsim.Vector3r(0.0, 0.0, 0.0),
                    airsim.to_quaternion(
                        pitch=float(pitch_deg), roll=0.0, yaw=float(yaw_deg)
                    ),
                ),
                vehicle_name=self.vehicle_name,
            )
            return True
        except Exception as e:
            log.debug(f"set_camera_pose failed: {e}")
            return False

    def aim_camera_at(
        self,
        target_name: str,
        pitch_deg: float | None = None,
        camera_name: str = "front_center",
    ) -> tuple[bool, float, float]:
        """
        Point the camera at a named scene object from the current pose.

        Returns ``(ok, bearing_deg, distance_m)``. Does not move or arm the
        airframe, so it is safe to call while grounded.
        """
        if not self.is_connected or not self.client:
            return False, 0.0, 0.0
        try:
            self_pos = self.client.simGetVehiclePose(
                vehicle_name=self.vehicle_name
            ).position
            tgt = self.client.simGetObjectPose(target_name).position
        except Exception as e:
            log.debug(f"aim_camera_at could not read poses: {e}")
            return False, 0.0, 0.0

        dx = tgt.x_val - self_pos.x_val
        dy = tgt.y_val - self_pos.y_val
        dist = math.hypot(dx, dy)
        # +0 deg is the camera's forward axis; positive yaw turns right (east).
        yaw = math.degrees(math.atan2(dy, dx))

        pitch = pitch_deg
        if pitch is None:
            # NED: +Z is DOWN, so an object below the drone (larger z) needs a
            # positive pitch to look down at it. Positive pitch = nose down.
            dz = tgt.z_val - self_pos.z_val
            # Verified empirically in CityEnviron: simSetCameraPitch takes a
            # POSITIVE value to look UP, so invert the geometric angle. An
            # object below the drone (larger z_val) needs negative pitch.
            pitch = -math.degrees(math.atan2(dz, max(dist, 1e-3)))

        ok = self.set_camera_pose(pitch_deg=pitch, yaw_deg=yaw, camera_name=camera_name)
        return ok, yaw, dist

    def set_camera_pitch(self, pitch_deg: float, camera_name: str = "front_center") -> bool:
        """
        Tilt the simulated camera. This is how low-angle / high-angle cinematic
        shots are realised — the airframe stays level, the camera does not.
        """
        return self.set_camera_pose(
            pitch_deg=pitch_deg, yaw_deg=0.0, camera_name=camera_name
        )

    def list_scene_objects(self, name_regex: str = ".*") -> list[str]:
        """Names of actors currently in the scene (e.g. spawned pedestrians)."""
        if not self.is_connected or not self.client:
            return []
        try:
            return list(self.client.simListSceneObjects(name_regex))
        except Exception as e:
            log.debug(f"simListSceneObjects failed: {e}")
            return []

    def check_surroundings(self) -> dict[str, Any]:
        """
        Performs radar survey of immediate surroundings using depth and collision telemetry.
        """
        dist_ahead = self.get_forward_obstacle_distance()
        telemetry = self.get_telemetry()
        has_collided = False
        try:
            col = self.client.simGetCollisionInfo(vehicle_name=self.vehicle_name)
            has_collided = col.has_collided
        except Exception:
            pass

        return {
            "forward_obstacle_m": round(dist_ahead, 2),
            "altitude_m": round(telemetry.get("z", 0.0), 2),
            "clear_ahead": bool(dist_ahead > 4.0),
            "has_collided": has_collided
        }

    def move_direction(
        self,
        direction: str,
        distance_m: float = 5.0,
        speed_mps: float = 3.0,
        collision_guard: bool = True
    ) -> dict[str, Any]:
        """
        Physics-Aware Closed-Loop Directional Movement:
        Dynamically senses real-time heading (yaw angle) and current (x, y, z) position.
        Calculates exact target coordinates in world NED frame so wind, aerodynamic drag,
        and angular disturbances are continuously compensated by the closed-loop position controller.

        Directions supported: 'FORWARD', 'BACKWARD', 'LEFT', 'RIGHT'
        """
        if not self.is_connected or not self.client:
            return {"status": "NOT_CONNECTED"}

        # Ensure API control and armed state
        self.client.enableApiControl(True, vehicle_name=self.vehicle_name)
        self.client.armDisarm(True, vehicle_name=self.vehicle_name)

        # 1. Forward collision guard
        dir_key = direction.strip().upper()
        if collision_guard and dir_key in ["FORWARD", "FRONT"]:
            obs_dist = self.get_forward_obstacle_distance()
            if obs_dist < 3.5:
                log.warning(f"⚠️ [CollisionGuard] Obstacle detected {obs_dist:.2f}m ahead! Cannot proceed forward.")
                return {"status": "OBSTACLE_AVOIDED", "distance_m": obs_dist}
            elif obs_dist < distance_m + 2.0:
                adjusted = max(0.5, obs_dist - 2.5)
                log.info(f"⚠️ Obstacle at {obs_dist:.1f}m. Clamping forward flight from {distance_m}m to {adjusted:.1f}m.")
                distance_m = adjusted

        # 2. Read real-time kinematics and heading angle
        state = self.client.getMultirotorState(vehicle_name=self.vehicle_name)
        pos = state.kinematics_estimated.position
        _, _, yaw = airsim.to_eularian_angles(state.kinematics_estimated.orientation)

        # 3. Compute heading-relative displacement vectors
        if dir_key in ["FORWARD", "FRONT"]:
            dx = distance_m * math.cos(yaw)
            dy = distance_m * math.sin(yaw)
        elif dir_key in ["BACKWARD", "BACK"]:
            dx = -distance_m * math.cos(yaw)
            dy = -distance_m * math.sin(yaw)
        elif dir_key == "RIGHT":
            # 90 degrees clockwise from nose
            dx = -distance_m * math.sin(yaw)
            dy = distance_m * math.cos(yaw)
        elif dir_key == "LEFT":
            # 90 degrees counter-clockwise from nose
            dx = distance_m * math.sin(yaw)
            dy = -distance_m * math.cos(yaw)
        else:
            dx, dy = 0.0, 0.0

        # Preserve current altitude, but ensure minimum clearance over low hedges
        # Ground is at z=1.60 in CityEnviron. If altitude is too low (< 2.5m AGL, i.e. z > -0.9), clamp to -2.0m
        target_z = min(pos.z_val, -2.0)

        target_x = pos.x_val + dx
        target_y = pos.y_val + dy

        yaw_mode = airsim.YawMode(is_rate=False, yaw_or_rate=math.degrees(yaw))
        log.info(f"Executing closed-loop {dir_key} flight of {distance_m:.1f}m -> Target: ({target_x:.2f}, {target_y:.2f}, z={target_z:.1f})")

        # 4. Asynchronous trajectory execution with Active In-Flight Radar Sentry
        future = self.client.moveToPositionAsync(
            target_x, target_y, target_z, velocity=speed_mps, yaw_mode=yaw_mode, vehicle_name=self.vehicle_name
        )

        # Sentry monitors surroundings at 12Hz during entire flight
        total_timeout = (distance_m / max(speed_mps, 0.5)) + 4.0
        t0 = time.time()
        while time.time() - t0 < total_timeout:
            time.sleep(0.08)

            # A. Continuous forward depth perception check
            if dir_key in ["FORWARD", "FRONT"]:
                obs_dist = self.get_forward_obstacle_distance()
                if obs_dist < 3.2:
                    log.warning(f"🛑 [SpatialSentry] Obstacle detected {obs_dist:.2f}m ahead! Auto-braking to hover.")
                    self.client.moveByVelocityAsync(0.0, 0.0, 0.0, duration=0.5, vehicle_name=self.vehicle_name).join()
                    self.client.hoverAsync(vehicle_name=self.vehicle_name)
                    return {"status": "OBSTACLE_AVOIDED", "distance_m": obs_dist}

            # B. Continuous physical collision check with auto-recovery
            col = self.client.simGetCollisionInfo(vehicle_name=self.vehicle_name)
            if col.has_collided and "Landscape" not in col.object_name:
                log.warning(f"🛑 [SpatialSentry] Physical barrier contact with [{col.object_name}]! Emergency brake and climb.")
                self.client.moveByVelocityAsync(0.0, 0.0, 0.0, duration=0.5, vehicle_name=self.vehicle_name).join()
                curr_s = self.client.getMultirotorState(vehicle_name=self.vehicle_name)
                curr_z = curr_s.kinematics_estimated.position.z_val
                self.client.moveToZAsync(curr_z - 2.5, velocity=2.0, vehicle_name=self.vehicle_name).join()
                self.client.hoverAsync(vehicle_name=self.vehicle_name)
                return {"status": "OBSTACLE_AVOIDED", "distance_m": 0.5, "object": col.object_name}

            # C. Check arrival at target waypoint
            curr_pos = self.client.getMultirotorState(vehicle_name=self.vehicle_name).kinematics_estimated.position
            dist_remaining = math.hypot(target_x - curr_pos.x_val, target_y - curr_pos.y_val)
            if dist_remaining < 0.4:
                break

        # Lock into rock-solid hover when motion completes (prevents falling)
        self.client.hoverAsync(vehicle_name=self.vehicle_name)
        return {"status": "COMPLETED", "distance_m": distance_m}

    def rotate_yaw(self, yaw_change_deg: float) -> bool:
        """Rotates the multirotor by a relative yaw angle in degrees (negative=left, positive=right)."""
        if not self.is_connected or not self.client:
            return False
        self.client.enableApiControl(True, vehicle_name=self.vehicle_name)
        self.client.armDisarm(True, vehicle_name=self.vehicle_name)
        state = self.client.getMultirotorState(vehicle_name=self.vehicle_name)
        _, _, curr_yaw = airsim.to_eularian_angles(state.kinematics_estimated.orientation)
        curr_deg = math.degrees(curr_yaw)
        target_deg = (curr_deg + yaw_change_deg) % 360.0
        log.info(f"Rotating heading from {curr_deg:.1f}° by {yaw_change_deg:+.1f}° -> Target: {target_deg:.1f}°")
        self.client.rotateToYawAsync(target_deg, vehicle_name=self.vehicle_name).join()
        return True

    def turn_and_move(
        self,
        yaw_change_deg: float,
        distance_m: float,
        speed_mps: float = 3.0
    ) -> dict[str, Any]:
        """
        Rotates multirotor to new heading angle, then translates forward along that trajectory
        with active spatial radar sentry.
        """
        log.info(f"Executing TURN_AND_MOVE: Turn {yaw_change_deg:+.1f}° then fly {distance_m:.1f}m...")
        self.rotate_yaw(yaw_change_deg)
        return self.move_direction("FORWARD", distance_m=distance_m, speed_mps=speed_mps, collision_guard=True)

    def move_velocity(
        self,
        vx: float,
        vy: float,
        vz: float,
        yaw_rate: float,
        duration_s: float,
        collision_guard: bool = True
    ) -> dict[str, Any]:
        """
        Commands translational body velocity with MaxDegreeOfFreedom for multirotor strafing.
        If moving forward and an obstacle is within 3.5m, halts immediately.
        """
        if not self.is_connected or not self.client:
            return {"status": "NOT_CONNECTED"}

        # Active forward collision guard
        if collision_guard and vx > 0:
            obs_dist = self.get_forward_obstacle_distance()
            if obs_dist < 3.5:
                log.warning(f"⚠️ [CollisionGuard] Obstacle detected {obs_dist:.2f}m ahead! Auto-braking to hover.")
                return {"status": "OBSTACLE_AVOIDED", "distance_m": obs_dist}

        drivetrain = airsim.DrivetrainType.MaxDegreeOfFreedom
        yaw_mode = airsim.YawMode(is_rate=False)

        self.client.moveByVelocityBodyFrameAsync(
            vx, vy, -vz, duration_s, drivetrain=drivetrain, yaw_mode=yaw_mode, vehicle_name=self.vehicle_name
        ).join()

        return {"status": "COMPLETED"}

    def return_to_launch(self, safe_altitude_m: float = 16.0) -> bool:
        """
        Physics-Aware Closed-Loop Return to Launch (RTL):
        1. Reads real-time position (x, y, z) and orientation (yaw).
        2. Calculates displacement vector and bearing angle to true launchpad origin (0.0, 0.0).
        3. Ascends to safe clearance altitude (16m) to clear buildings and trees.
        4. Turns nose towards home and flies closed-loop to (0.0, 0.0) — wind drift is continuously corrected.
        5. Performs station-keeping check over launchpad to ensure horizontal error < 0.5m.
        6. Controlled approach descent to z = 0.0 (~1.6m above asphalt).
        7. Smooth touchdown descent onto asphalt pavement and settles.
        8. Verifies physical landing, disarms motors, and releases API control.
        """
        if not self.is_connected or not self.client:
            return False

        try:
            self.client.enableApiControl(True, vehicle_name=self.vehicle_name)
            self.client.armDisarm(True, vehicle_name=self.vehicle_name)

            # Step 1: Read current position and determine climb clearance
            curr_state = self.client.getMultirotorState(vehicle_name=self.vehicle_name)
            curr_pos = curr_state.kinematics_estimated.position
            climb_alt = max(safe_altitude_m, -curr_pos.z_val + 5.0)

            log.info(f"[RTL] Step 1: Ascending to safe clearance altitude of {climb_alt:.1f}m...")
            self.client.moveToZAsync(-climb_alt, velocity=3.0, vehicle_name=self.vehicle_name).join()

            # Step 2: Compute bearing to launchpad origin (0, 0)
            mid_state = self.client.getMultirotorState(vehicle_name=self.vehicle_name)
            mid_pos = mid_state.kinematics_estimated.position
            bearing = math.atan2(0.0 - mid_pos.y_val, 0.0 - mid_pos.x_val)
            bearing_deg = math.degrees(bearing)

            log.info(f"[RTL] Step 2: Facing bearing {bearing_deg:.1f}° and flying home to launchpad (0.0, 0.0)...")
            yaw_mode = airsim.YawMode(is_rate=False, yaw_or_rate=bearing_deg)
            self.client.moveToPositionAsync(
                0.0, 0.0, -climb_alt, velocity=5.0, yaw_mode=yaw_mode, vehicle_name=self.vehicle_name
            ).join()

            # Step 3: Verify arrival over pad (wind compensation station-keeping)
            pad_state = self.client.getMultirotorState(vehicle_name=self.vehicle_name)
            pad_pos = pad_state.kinematics_estimated.position
            horiz_err = math.hypot(pad_pos.x_val, pad_pos.y_val)
            log.info(f"[RTL] Step 3: Arrived over launchpad. Horizontal error: {horiz_err:.2f}m")
            if horiz_err > 0.5:
                self.client.moveToPositionAsync(0.0, 0.0, -climb_alt, velocity=2.0, vehicle_name=self.vehicle_name).join()

            # Step 4: Controlled approach descent to z = 0.0 (~1.6m above asphalt)
            log.info("[RTL] Step 4: Descent to launchpad approach altitude (1.6m above pavement)...")
            self.client.moveToPositionAsync(0.0, 0.0, 0.0, velocity=3.0, vehicle_name=self.vehicle_name).join()

            # Step 5: Controlled touchdown on pavement
            log.info("[RTL] Step 5: Final touchdown on asphalt pavement...")
            self.client.moveByVelocityAsync(0.0, 0.0, 1.2, duration=3.0, vehicle_name=self.vehicle_name).join()
            self.client.landAsync(vehicle_name=self.vehicle_name).join()

            # Step 6: Disarm motors and release API control so drone rests landed
            self.client.armDisarm(False, vehicle_name=self.vehicle_name)
            self.client.enableApiControl(False, vehicle_name=self.vehicle_name)
            time.sleep(0.5)

            # Step 7: Verify physical touchdown
            final_state = self.client.getMultirotorState(vehicle_name=self.vehicle_name)
            final_pos = final_state.kinematics_estimated.position
            is_landed = (final_state.landed_state == airsim.LandedState.Landed) or (final_pos.z_val >= 1.3)

            if is_landed:
                log.info(f"[RTL] Touchdown verified on launchpad at ({final_pos.x_val:.2f}, {final_pos.y_val:.2f}, z={final_pos.z_val:.2f}). Motors disarmed.")
                return True
            else:
                log.warning(f"[RTL] Touchdown unverified. Drone at z={final_pos.z_val:.2f}")
                return False

        except Exception as e:
            log.error(f"[RTL] Error during return to launch: {e}")
            return False

    def make_follow_controller(
        self,
        command: str = "follow",
        shot: Any = None,
        duration_s: float = 20.0,
        record: Optional[bool] = None,
        on_event: Any = None,
    ) -> Any:
        """
        Build a FollowController bound to this client as its flight backend.

        Prefer this over :meth:`follow_target` — the controller keeps identity
        across frames, applies the shot framing, vetoes velocity on obstacle
        proximity, and records the shot.
        """
        from garuda.flight.follow_controller import FollowController
        from garuda.flight.shot_planner import ShotDirector

        if getattr(self, "detector", None) is None:
            try:
                from garuda.perception.yolo_detector import YoloDetector

                self.detector = YoloDetector()
            except Exception as e:
                log.warning(f"Could not load YOLO detector: {e}")
                self.detector = None

        director = ShotDirector()
        spec = shot if shot is not None else director.parse(command)
        return FollowController(
            backend=self,
            detector=self.detector,
            spec=spec,
            director=director,
            on_event=on_event,
        )

    def follow_target(
        self,
        target_name: str = "Pedestrian_1",
        duration_s: float = 15.0,
        standoff_dist_m: float = 4.5,
        speed_mps: float = 2.5,
        command: Optional[str] = None,
        shot: Any = None,
    ) -> dict[str, Any]:
        """
        Autonomous Dynamic Escort & Visual Tracking.

        Thin wrapper around :class:`FollowController`, which owns the actual
        control law. ``command`` lets callers pass the raw spoken text so the
        cinematic shot ("follow that man, close up, from the left") is honoured.

        ``target_name`` is retained for backwards compatibility and is used
        only as a *hint* for scene-actor reacquisition when vision is lost —
        identity itself is resolved by appearance from the camera, which is
        what makes "that man" work when the actor is called something else.
        """
        if not self.is_connected or not self.client:
            return {"status": "NOT_CONNECTED"}

        self.client.enableApiControl(True, vehicle_name=self.vehicle_name)
        self.client.armDisarm(True, vehicle_name=self.vehicle_name)

        from garuda.flight.shot_planner import ShotSpec
        from dataclasses import replace as _replace

        base = shot if shot is not None else ShotSpec(
            name="follow",
            target_h_ratio=0.42,
            standoff_m=standoff_dist_m,
            max_speed_mps=speed_mps,
        )

        ctrl = self.make_follow_controller(command=command or "follow", shot=base)
        if getattr(self, "detector", None) is None:
            return {
                "status": "DETECTOR_UNAVAILABLE",
                "target": target_name,
                "detail": "YOLO model could not be loaded; refusing to fly blind on a person",
            }

        ctrl.begin(command=command or "follow", spec=base, duration_s=duration_s)
        t_start = time.time()
        last = None
        while time.time() - t_start < duration_s:
            last = ctrl.tick()
            time.sleep(max(0.02, ctrl.gains.tick_s * 0.5))
        stats = ctrl.end("duration elapsed")

        lock_ratio = (ctrl.telemetry.lock_ratio if ctrl.telemetry else 0.0)
        return {
            "status": "SUCCESS" if lock_ratio > 0.2 else "LOCK_NOT_ACQUIRED",
            "target": target_name,
            "cycles": ctrl.telemetry.tick if ctrl.telemetry else 0,
            "visual_locks": int(lock_ratio * (ctrl.telemetry.tick if ctrl.telemetry else 0)),
            "lock_ratio": lock_ratio,
            "shot": ctrl.spec.name,
            "shot_path": stats.path,
            "avoid_events": stats.avoid_events,
        }

    def reset_to_home(self):
        """Instantaneously respawns drone upright on the launchpad."""
        if not self.is_connected or not self.client:
            return
        log.info("Resetting simulation to launchpad...")
        self.client.reset()
        time.sleep(0.5)
        self.client.enableApiControl(True, vehicle_name=self.vehicle_name)
        self.client.armDisarm(True, vehicle_name=self.vehicle_name)
        self.home_position = (0.0, 0.0, 1.60)

    def land(self):
        """Commands smooth automated landing to pavement and disarms."""
        if not self.is_connected or not self.client:
            return
        log.info("Commanding precision landing...")
        self.client.moveByVelocityAsync(0.0, 0.0, 1.2, duration=3.0, vehicle_name=self.vehicle_name).join()
        self.client.landAsync(vehicle_name=self.vehicle_name).join()
        self.client.armDisarm(False, vehicle_name=self.vehicle_name)
        self.client.enableApiControl(False, vehicle_name=self.vehicle_name)

    def set_eagle_eye_camera(self, distance: float = 3.5, height: float = 2.0):
        """Sets the spectator view in Unreal Engine to an Eagle-Eye chase view."""
        if not self.is_connected or not self.client:
            return
        try:
            self.client.simSetCameraPose(
                "0",
                airsim.Pose(
                    airsim.Vector3r(-distance, 0, -height),
                    airsim.to_quaternion(pitch=-0.2, roll=0, yaw=0)
                )
            )
            log.info("Eagle-Eye observer view set in Unreal Engine.")
        except Exception as e:
            log.debug(f"Observer camera set warning: {e}")
