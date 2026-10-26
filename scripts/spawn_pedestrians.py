#!/usr/bin/env python3
"""
GarudaOS — Dynamic City Pedestrian Spawner for AirSim / Unreal Engine
====================================================================
Spawns and animates pedestrians and dynamic obstacles along sidewalks
in the Unreal Engine CityEnviron simulation for obstacle avoidance and
tracking evaluation.

Usage:
  python scripts/spawn_pedestrians.py --count 5 --speed 1.5
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("PedestrianSpawner")

try:
    import airsim
    AIRSIM_AVAILABLE = True
except ImportError:
    airsim = None
    AIRSIM_AVAILABLE = False


# Default sidewalk waypoints in CityEnviron near starting dronepad (in meters, NED frame)
DEFAULT_SIDEWALK_PATHS = [
    [
        (5.0, 3.0, 0.0),
        (25.0, 3.0, 0.0),
        (25.0, 8.0, 0.0),
        (5.0, 8.0, 0.0),
    ],
    [
        (10.0, -4.0, 0.0),
        (35.0, -4.0, 0.0),
        (35.0, -8.0, 0.0),
        (10.0, -8.0, 0.0),
    ],
    [
        (-5.0, 12.0, 0.0),
        (15.0, 12.0, 0.0),
        (15.0, 16.0, 0.0),
        (-5.0, 16.0, 0.0),
    ],
]


class PedestrianAgent:
    """Represents a simulated pedestrian moving along a waypoint circuit."""

    def __init__(self, name: str, waypoints: list[tuple[float, float, float]], speed: float = 1.4):
        self.name = name
        self.waypoints = waypoints
        self.speed = speed
        self.current_idx = 0
        self.x, self.y, self.z = waypoints[0]

    def update(self, dt: float) -> tuple[float, float, float, float]:
        """Calculates the new position and heading toward the next waypoint."""
        target_x, target_y, target_z = self.waypoints[self.current_idx]
        dx = target_x - self.x
        dy = target_y - self.y
        dist = math.hypot(dx, dy)

        if dist < 0.5:
            self.current_idx = (self.current_idx + 1) % len(self.waypoints)
            target_x, target_y, target_z = self.waypoints[self.current_idx]
            dx = target_x - self.x
            dy = target_y - self.y
            dist = math.hypot(dx, dy)

        heading = math.atan2(dy, dx)
        step = min(dist, self.speed * dt)

        if dist > 0.001:
            self.x += (dx / dist) * step
            self.y += (dy / dist) * step
            self.z = target_z

        return self.x, self.y, self.z, heading


def find_best_pedestrian_asset(client) -> Optional[str]:
    """Find a *spawnable, person-shaped* mesh in the Unreal asset registry.

    Returns ``None`` when the build has no human mesh. That is the honest
    answer for CityEnviron: its registry holds no ``rp_*_rigged_*`` skeleton
    meshes, and the only "character"-named entries are Blueprints and path
    helpers (``CharacterPaths``, ``BasePedestrianPath_BP``).

    Those Blueprints *accept* a spawn call and return a name, so the old code
    reported success and logged a green tick while producing an object YOLO can
    never classify as a person. Never trust a name match alone — a match must
    also be a real mesh, or the caller gets ``None`` and says so.

    Do NOT add the nested ``/Game/Building_99/Characters/FuseCharacters/...``
    meshes. They exist as loose .uasset files in this install, but they are not
    cooked into the packaged WindowsNoEditor build: ``simSpawnObject`` on those
    paths never returns and takes the whole simulator process down with it.
    Reproduced twice, verified in isolation.
    """
    # A registry name is only a candidate if it looks like a mesh, not a
    # Blueprint, path spline, or helper actor.
    _REJECT = ("path", "bp", "_bp", "manager", "pawn", "camera", "menu",
               "weather", "light", "mode", "actor", "track")

    candidates = [
        "rp_manuel_rigged_001_ue4",
        "rp_sophia_rigged_003_ue4",
        "rp_carla_rigged_001_ue4",
        "Mannequin",
    ]
    try:
        available_assets = client.simListAssets()
        log.info(f"Asset registry scan: found {len(available_assets)} assets in simulation.")
    except Exception as e:
        log.warning(f"Could not query asset registry via simListAssets: {e}")
        return None

    for c in candidates:
        if c in available_assets:
            log.info(f"Found 3D character asset in registry: '{c}'")
            return c

    for asset in available_assets:
        lower = asset.lower()
        if any(bad in lower for bad in _REJECT):
            continue
        if any(k in lower for k in ["pedestrian", "mannequin", "skeletal",
                                    "humanoid", "manuel", "sophia"]):
            log.info(f"Found pedestrian mesh in registry: '{asset}'")
            return asset

    log.warning(
        "No spawnable human mesh in this build. The scene's 'CharacterPaths' "
        "entries are path splines ~800 m away, not people. Person following "
        "cannot be verified until a rigged human mesh is added to the sim."
    )
    return None


# Sidewalk paths in front of drone launchpad in CityEnviron (NED frame)
DEFAULT_SIDEWALK_PATHS = [
    [
        (8.0, 3.5, 1.2),
        (28.0, 3.5, 1.2),
        (28.0, 7.5, 1.2),
        (8.0, 7.5, 1.2),
    ],
    [
        (12.0, -3.5, 1.2),
        (32.0, -3.5, 1.2),
        (32.0, -7.5, 1.2),
        (12.0, -7.5, 1.2),
    ],
    [
        (6.0, 10.0, 1.2),
        (22.0, 10.0, 1.2),
        (22.0, 14.0, 1.2),
        (6.0, 14.0, 1.2),
    ],
]


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Animate pedestrians already present in the CityEnviron map. "
            "NOTE: this script cannot create actors - simSpawnObject crashes "
            "the simulator in this build - so it only moves objects that "
            "already exist."
        )
    )
    parser.add_argument("--count", type=int, default=3, help="Number of pedestrians to simulate (default: 3)")
    parser.add_argument("--speed", type=float, default=1.4, help="Walking speed in m/s (default: 1.4)")
    parser.add_argument("--ip", type=str, default="127.0.0.1", help="AirSim RPC IP")
    parser.add_argument("--port", type=int, default=41451, help="AirSim RPC Port")
    args = parser.parse_args()

    if not AIRSIM_AVAILABLE:
        log.error("The 'airsim' Python package is required. Install via: pip install airsim")
        sys.exit(1)

    log.info(f"Connecting to AirSim on {args.ip}:{args.port}...")
    client = airsim.VehicleClient(ip=args.ip, port=args.port)

    try:
        client.confirmConnection()
        log.info("✅ Connected to AirSim Unreal Engine simulation!")
    except Exception as e:
        log.error(f"Failed to connect to AirSim: {e}")
        log.info("Ensure CityEnviron.exe is launched and running.")
        sys.exit(1)

    # simSpawnObject is broken in this build: any call kills CityEnviron.exe.
    # Verified with /Engine/BasicShapes/Sphere, so it is not an asset problem.
    # Therefore this script can only animate actors the map already contains.
    existing = []
    for pattern in (r".*[Pp]edestrian.*", r".*[Ff]use.*", r".*[Mm]ale_.*", r".*[Ff]emale_.*"):
        try:
            existing.extend(client.simListSceneObjects(pattern))
        except Exception:
            pass
    existing = sorted(set(existing))
    if existing:
        log.info(f"Existing pedestrian-like actors in the map: {existing}")
    else:
        log.warning(
            "No pedestrian actors exist in this map, and they cannot be created: "
            "simSpawnObject crashes the simulator. Person following cannot be "
            "demonstrated with CityEnviron as it ships. See AGENTS.md."
        )
        log.info("Exiting without touching the sim.")
        return

    if not find_best_pedestrian_asset(client):
        log.warning(
            "No person-shaped mesh in this build; any actors found above are "
            "likely path splines rather than people. YOLO will not detect them."
        )

    agents: list[PedestrianAgent] = []
    for i, name in enumerate(existing[: args.count]):
        path = DEFAULT_SIDEWALK_PATHS[i % len(DEFAULT_SIDEWALK_PATHS)]
        agents.append(PedestrianAgent(name, path, speed=args.speed + (i * 0.15)))

    log.info(f"\n🚶 Animating {len(agents)} pedestrians along city sidewalks (Press Ctrl+C to stop)...")

    dt = 0.05  # 20 Hz update loop
    try:
        while True:
            t0 = time.time()
            for agent in agents:
                x, y, z, yaw = agent.update(dt)
                pose = airsim.Pose(
                    airsim.Vector3r(x, y, z),
                    airsim.to_quaternion(0, 0, yaw),
                )
                try:
                    client.simSetObjectPose(agent.name, pose, teleport=True)
                except Exception:
                    pass

            elapsed = time.time() - t0
            sleep_time = max(0.0, dt - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        log.info("\nStopping pedestrian simulation...")
    finally:
        # Nothing is destroyed: this script never created anything, and
        # simDestroyObject is as unsafe as simSpawnObject in this build.
        log.info("Pedestrian animator shut down cleanly. No objects were created.")


if __name__ == "__main__":
    main()
