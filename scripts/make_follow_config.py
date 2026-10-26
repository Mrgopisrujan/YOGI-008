"""Derive a follow-specific Project AirSim config with a forward depth camera.

The stock scene only mounts a chase camera (scene only) and a belly camera
(scene + depth). The chase camera has no depth, and the belly depth points
straight down, so a forward-looking avoider has nothing to read: feeding belly
depth to ``ObstacleAvoider`` would report the pavement ~4 m below as the
obstacle in the flight path and veto every forward command.

This adds a ``FrontCamera`` on the nose with a scene stream and a
depth-perspective stream, which is what the follow loop actually needs.

Run once; writes:
    sim_config/robot_quadrotor_fastphysics_follow.jsonc
    sim_config/scene_follow.jsonc

Both are derived rather than hand-edited so the stock configs stay untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import commentjson

log = lambda *a: print(*a, flush=True)

SRC = Path("sim_config/robot_quadrotor_fastphysics.jsonc")
DST_ROBOT = Path("sim_config/robot_quadrotor_fastphysics_follow.jsonc")
DST_SCENE = Path("sim_config/scene_follow.jsonc")

# Nose-mounted, level, just ahead of the airframe.
FRONT_ORIGIN = {"xyz": "0.45 0.0 0.0", "rpy-deg": "0 0 0"}


def main() -> int:
    cfg = commentjson.loads(SRC.read_text(encoding="utf-8"))

    if any(s.get("id") == "FrontCamera" for s in cfg.get("sensors", [])):
        log("FrontCamera already present; leaving config as-is")
        return 0

    cfg["sensors"].append(
        {
            "id": "FrontCamera",
            "type": "camera",
            "enabled": True,
            "parent-link": "Frame",
            "capture-interval": 0.02,
            "capture-settings": [
                {
                    # 0 = scene camera, streamed so the detector gets frames.
                    "image-type": 0,
                    "width": 640,
                    "height": 360,
                    "fov-degrees": 90,
                    "capture-enabled": True,
                    "streaming-enabled": True,
                    "pixels-as-float": False,
                    "compress": False,
                    "target-gamma": 2.5,
                },
                {
                    # 2 = depth perspective, streamed so the avoider reads metres.
                    "image-type": 2,
                    "width": 640,
                    "height": 360,
                    "fov-degrees": 90,
                    "capture-enabled": True,
                    "streaming-enabled": True,
                    "pixels-as-float": True,
                    "compress": False,
                },
            ],
            "gimbal": {"lock-roll": True, "lock-pitch": True, "lock-yaw": False},
            "origin": dict(FRONT_ORIGIN),
        }
    )

    # Eagle view: mounted above the vehicle, pitched straight down. This exists
    # for the *observer*, not for perception -- the follow loop reads
    # FrontCamera only. The stock main window is a side/chase view, which makes
    # it impossible to judge framing or see what the drone is flying at;
    # ``World.switch_streaming_view()`` cycles the window between the cameras
    # with streaming-enabled, so enabling this adds an overhead view to the
    # cycle.
    #
    # UE camera forward is +X at identity and pitch is about +Y, so -90 looks
    # down. Verified from the simulator window, not assumed.
    cfg["sensors"].append(
        {
            "id": "EagleCamera",
            "type": "camera",
            "enabled": True,
            "parent-link": "Frame",
            "capture-interval": 0.05,
            "capture-settings": [
                {
                    "image-type": 0,
                    "width": 960,
                    "height": 720,
                    # Wider than 90 so the subject and its surroundings both fit.
                    "fov-degrees": 110,
                    "capture-enabled": True,
                    "streaming-enabled": True,
                    "pixels-as-float": False,
                    "compress": False,
                    "target-gamma": 2.5,
                }
            ],
            "gimbal": {"lock-roll": True, "lock-pitch": True, "lock-yaw": False},
            # roll 90 puts the image upright. Without it the overhead frame is
            # rotated a quarter turn sideways -- the plaza reads correctly but
            # the horizon runs down the side of the screen.
            "origin": {"xyz": "0.0 0.0 9.0", "rpy-deg": "90 -90 0"},
        }
    )

    DST_ROBOT.write_text(commentjson.dumps(cfg, indent=2), encoding="utf-8")
    log(f"wrote {DST_ROBOT} ({len(cfg['sensors'])} sensors)")

    scene = {
        "id": "SceneFollow",
        "actors": [
            {
                "type": "robot",
                "name": "Drone1",
                "origin": {"xyz": "-1.0 8.0 -4.0", "rpy-deg": "0 0 90"},
                "robot-config": DST_ROBOT.name,
            }
        ],
        "clock": {
            "type": "steppable",
            "step-ns": 3000000,
            "real-time-update-rate": 3000000,
            "pause-on-start": False,
        },
        "home-geo-point": {
            "latitude": 47.641468,
            "longitude": -122.140165,
            "altitude": 122.0,
        },
        "segmentation": {
            "initialize-ids": True,
            "ignore-existing": False,
            "use-owner-name": True,
        },
        "scene-type": "UnrealNative",
    }
    DST_SCENE.write_text(commentjson.dumps(scene, indent=2), encoding="utf-8")
    log(f"wrote {DST_SCENE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
