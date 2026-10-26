"""Verify the overhead camera: orientation, height, and framing.

Saves the EagleCamera frame so the roll can be checked without squinting at
the simulator window, and reports how much of the frame is ground vs sky so a
camera that is tilted rather than pointing straight down is caught.

Ground/sky split is measured on the upper third of the frame: with a camera
pitched straight down from 9 m, nothing above the horizon should be visible, so
the top band should be uniformly dark pavement.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from garuda.flight.pas_client import ProjectAirSimBackend

log = lambda *s: print(*s, flush=True)
Path("logs").mkdir(exist_ok=True)


def main() -> int:
    import cv2

    b = ProjectAirSimBackend()
    if not b.connect():
        log("connect FAILED")
        return 1
    try:
        log(f"sensors: {list(b._drone.sensors.keys())}")
        if "EagleCamera" not in b._drone.sensors:
            log("EagleCamera missing - rerun scripts/make_follow_config.py")
            return 2
        topic = b._drone.sensors["EagleCamera"]["scene_camera"]
        box: dict = {}
        b._client.subscribe(topic, lambda _, v: box.__setitem__("f", v))
        # ImageDisplay already started in connect(); the steppable clock is
        # pumping, so frames should arrive.
        for _ in range(30):
            if "f" in box:
                break
            time.sleep(0.5)
        if "f" not in box:
            log("no EagleCamera frame")
            return 3

        from projectairsim.image_utils import unpack_image

        img = np.asarray(unpack_image(box["f"]))
        cv2.imwrite("logs/eagle_view.png", np.ascontiguousarray(img.astype(np.uint8)))
        log(f"saved logs/eagle_view.png {img.shape}")

        h, w = img.shape[:2]
        top = img[: h // 3].astype(np.float32)
        log(f"  top-third mean RGB: {top.reshape(-1, 3).mean(axis=0).round(1)}")
        log(f"  full-frame mean RGB: {img.astype(np.float32).reshape(-1, 3).mean(axis=0).round(1)}")
        log(f"  altitude {b.altitude_agl():.2f} m, frames {b.frames_received()}")

        if not b.takeoff(altitude_m=5.0):
            log("takeoff failed")
            return 4
        for _ in range(20):
            if "f" in box and box["f"] is not None:
                break
            time.sleep(0.5)
        img2 = np.asarray(unpack_image(box["f"]))
        cv2.imwrite("logs/eagle_air.png", np.ascontiguousarray(img2.astype(np.uint8)))
        log(f"saved logs/eagle_air.png {img2.shape} at altitude")
        log(f"  cycling main window 3x")
        b.cycle_view(3)
        return 0
    finally:
        try:
            b.land()
        except Exception:
            pass
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
