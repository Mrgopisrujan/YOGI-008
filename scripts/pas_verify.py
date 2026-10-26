"""Final verification of the IAMAI Project AirSim environment.

Decides whether the follow stack can run here:
  1. decode scene + depth frames (payload['data'] is raw bytes)
  2. run the real YOLO person detector on the chase frame
  3. enumerate scene objects and probe spawnable assets
  4. confirm avoidance gets metric depth

Frames arrive late, so this waits properly rather than assuming a fixed delay.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import projectairsim as pas
from projectairsim.image_utils import unpack_image
from projectairsim.types import Pose
from projectairsim.utils import projectairsim_log

log = lambda *a: print(*a, flush=True)
projectairsim_log().setLevel(60)
Path("logs").mkdir(exist_ok=True)

CAM = {}


def decode(payload):
    """(pixels HxW float32, h, w) using the library's own unpack_image."""
    if not isinstance(payload, dict) or not payload.get("height"):
        return None
    try:
        img = unpack_image(payload)
    except Exception as e:
        log(f"    unpack_image failed: {type(e).__name__}: {e}")
        return None
    if img is None:
        return None
    a = np.asarray(img)
    h, w = int(payload["height"]), int(payload["width"])
    if a.ndim == 3 and a.shape[2] >= 3:
        a = a[:, :, :3]
    return a.astype(np.float32), h, w


async def wait_for(key, timeout=25.0):
    """Wait for a camera payload; they publish lazily and late."""
    t0 = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - t0 < timeout:
        if key in CAM:
            return True
        await asyncio.sleep(0.25)
    return False


async def main():
    client = pas.ProjectAirSimClient(address="127.0.0.1", port_topics=8989, port_services=8990)
    client.connect()
    world = pas.World(client, "scene_basic_drone.jsonc", delay_after_load_sec=3.0)
    drone = pas.Drone(client, world, "Drone1")
    log("scene + drone ready | sensors:", list(drone.sensors.keys()))

    # The stock scene uses a steppable clock; camera topics only publish once
    # the simulation clock is actually ticking, so start ImageDisplay to pump
    # them the way hello_drone.py does.
    from projectairsim.image_utils import ImageDisplay

    disp = ImageDisplay()
    disp.add_chase_cam("Chase")
    disp.add_image("Belly", subwin_idx=0)
    disp.add_image("Depth", subwin_idx=2)
    disp.start()
    log("ImageDisplay started (pumps the sim clock)")

    for cam, key, label in (
        ("Chase", "scene_camera", "chase"),
        ("DownCamera", "scene_camera", "belly"),
        ("DownCamera", "depth_camera", "depth"),
    ):
        client.subscribe(
            drone.sensors[cam][key], lambda _, v, w=label: CAM.__setitem__(w, v)
        )
    log("subscribed to 3 camera topics")

    drone.enable_api_control()
    drone.arm()
    await (await drone.takeoff_async())
    log("takeoff done; hovering at spawn altitude")
    await asyncio.sleep(1.0)
    t = drone.get_ground_truth_pose()["translation"]
    log(f"  position x={t['x']:.2f} y={t['y']:.2f} z={t['z']:.2f}")

    import cv2

    log("\n=== 1. camera frames ===")
    got = {}
    for k in ("chase", "belly", "depth"):
        ok = await wait_for(k, 20.0)
        d = decode(CAM.get(k)) if ok else None
        if d is None:
            log(f"  {k:6} NO FRAME")
            continue
        px, h, w = d
        got[k] = (px, h, w)
        if k == "depth":
            g = np.clip(px / 30.0, 0, 1)
            img = cv2.applyColorMap((g * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
            log(f"  {k:6} {w}x{h} depth {px.min():.2f}..{px.max():.2f} m  "
                f"median={np.median(px):.2f} m")
        else:
            # unpack_image already returns bottom-up rows; do NOT flip again.
            img = np.ascontiguousarray(px.astype(np.uint8))
            log(f"  {k:6} {w}x{h} mean={px.mean():.1f}")
        cv2.imwrite(f"logs/pas5_{k}.png", img)
        log(f"         saved logs/pas5_{k}.png")

    log("\n=== 2. YOLO person detection on the live frame ===")
    if "chase" in got or "belly" in got:
        from garuda.perception.yolo_detector import YoloDetector

        det = YoloDetector()
        for k in ("chase", "belly"):
            if k not in got:
                continue
            px, h, w = got[k]
            bgr = np.ascontiguousarray(px.astype(np.uint8))
            for thr in (0.35, 0.15):
                persons = det.detect_persons(bgr, conf=thr)
                log(f"  {k:6} persons@conf>={thr}: {len(persons)}")
                for p in persons[:4]:
                    log(f"       conf={p['confidence']:.2f} bbox={p['bbox']} "
                        f"h_ratio={p['h_ratio']:.3f}")
            raw = det.model(bgr, conf=0.15, verbose=False)
            if len(raw):
                names = det.model.names
                counts = {}
                for c in raw[0].boxes.cls.tolist():
                    counts[names[int(c)]] = counts.get(names[int(c)], 0) + 1
                log(f"  {k:6} all classes@0.15: {counts}")
    else:
        log("  no frames to run detection on")

    log("\n=== 3. scene objects ===")
    lister = None
    for meth in ("list_scene_objects", "list_actors", "get_scene_objects"):
        if hasattr(world, meth):
            lister = getattr(world, meth)
            log(f"  using World.{meth}")
            break
    if lister is None:
        log(f"  World has no scene-object lister; available: "
            f"{[m for m in dir(world) if not m.startswith('_') and 'list' in m.lower() or 'actor' in m.lower()]}")
    else:
        try:
            objs = lister(".*")
            log(f"  {len(objs)} objects; sample: {objs[:12]}")
        except Exception as e:
            log(f"  {lister.__name__} failed: {type(e).__name__}: {e}")

    log("\n=== 4. spawnable assets ===")
    for asset in ("/Engine/BasicShapes/Cube", "/Engine/BasicShapes/Sphere"):
        p = Pose({
            "position": {"x": 4.0, "y": 4.0, "z": 0.0},
            "orientation": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
            "scale": {"w": 1.0, "x": 1.0, "y": 1.0, "z": 1.0},
        })
        try:
            r = world.spawn_object(f"Pr_{asset.split('/')[-1]}", asset, p, [1.0, 1.0, 1.0], False)
            log(f"  {asset:32} -> {r!r}")
            if r:
                try:
                    world.delete_actor(r)
                except Exception:
                    pass
        except Exception as e:
            log(f"  {asset:32} -> EXC {type(e).__name__}: {str(e)[:60]}")

    await (await drone.land_async())
    log("\nFINAL VERIFICATION DONE")
    try:
        client.close()
    except Exception:
        pass


asyncio.run(main())
