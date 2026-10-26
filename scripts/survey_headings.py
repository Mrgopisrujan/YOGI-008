"""Find the heading with the most people, using kinematic yaw + a live count.

simSetCameraPose yaw does not take effect in this build, but the vehicle yaw
written by simSetVehiclePose does. So rotate the airframe to survey, count
people with YOLO at each heading, then report the best heading to face.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import airsim
import cv2
import numpy as np

from garuda.perception.yolo_detector import YoloDetector


def quat_yaw(q):
    import math

    return math.degrees(
        math.atan2(
            2.0 * (q.w_val * q.z_val + q.x_val * q.y_val),
            1.0 - 2.0 * (q.y_val**2 + q.z_val**2),
        )
    )


def quat(yaw_deg):
    import math

    r = math.radians(yaw_deg) / 2.0
    return airsim.Quaternionr(w_val=math.cos(r), x_val=0.0, y_val=0.0, z_val=math.sin(r))


client = airsim.VehicleClient(ip="127.0.0.1", port=41451)
client.confirmConnection()
det = YoloDetector()

p = client.simGetVehiclePose()
x, y, z = p.position.x_val, p.position.y_val, p.position.z_val
ground = z
x, y, z = 0.0, 0.0, ground - 4.0   # 4 m up, looking slightly down
print(f"drone lifted to z={z:.2f} (4.0 m AGL)", flush=True)

Path("logs/rec").mkdir(parents=True, exist_ok=True)
results = []
for yaw in range(0, 360, 20):
    try:
        client.simSetVehiclePose(
            airsim.Pose(airsim.Vector3r(x, y, z), quat(yaw)), ignore_collision=True
        )
    except Exception as e:
        print(f"  yaw {yaw}: pose failed {e}")
        continue
    time.sleep(0.7)
    try:
        r = client.simGetImages(
            [airsim.ImageRequest("front_center", airsim.ImageType.Scene, False, False)]
        )
        if not r:
            continue
        img = np.frombuffer(r[0].image_data_uint8, np.uint8).reshape(
            r[0].height, r[0].width, 3
        )
    except Exception as e:
        print(f"  yaw {yaw}: image failed {e}")
        continue

    persons = det.detect_persons(img, conf=0.10)
    best = max((d["confidence"] for d in persons), default=0.0)
    besth = max((d["h_ratio"] for d in persons), default=0.0)
    results.append((len(persons), yaw, best, besth))
    print(
        f"  yaw {yaw:3d}: persons={len(persons):2d}  maxconf={best:.2f}  "
        f"max_h_ratio={besth:.3f}",
        flush=True,
    )
    if len(persons) > 0:
        cv2.imwrite(f"logs/rec/survey_{yaw:03d}.jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])

results.sort(reverse=True)
print("\n=== best headings by person count ===")
for n, yaw, c, h in results[:6]:
    print(f"  yaw {yaw:3d}: {n} persons, maxconf={c:.2f}, max_h={h:.3f}")
print(f"\nTOTAL persons seen across sweep: {sum(r[0] for r in results)}")
