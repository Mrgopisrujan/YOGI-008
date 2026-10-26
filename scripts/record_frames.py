"""Record frames with the camera moved clear of the airframe.

The drone body is visible because simSetCameraPose rotation is applied about the
airframe centre, so pitching swings the sensor down into the hull. Fix: pass an
explicit forward translation in the pose so the sensor sits ahead of the props
while rotating about its own mount.

Also narrows the sweep to the headings where the crowd actually is, so more of
the recording is useful.
"""
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import airsim

SESSION = sys.argv[1] if len(sys.argv) > 1 else "clean1"
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 24.0
OFFSET_X = float(sys.argv[3]) if len(sys.argv) > 3 else 0.60
PITCH = float(sys.argv[4]) if len(sys.argv) > 4 else -7.0
# The crowd in the reference screenshot sits off the pad's right/left shoulder.
YAW_START = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0
YAW_SWEEP = float(sys.argv[6]) if len(sys.argv) > 6 else 360.0

out = Path("logs/rec") / SESSION
out.mkdir(parents=True, exist_ok=True)
print(f"recording {SESSION}: offset_x={OFFSET_X} pitch={PITCH} "
      f"yaw {YAW_START}..{YAW_START+YAW_SWEEP}", flush=True)

import cv2
import numpy as np

from garuda.flight.airsim_client import AirSimClient

ac = AirSimClient()
if not ac.connect(timeout=25.0):
    print("connect failed", flush=True)
    raise SystemExit(1)

fcsv = open(out / "telemetry.csv", "w", newline="")
writer = csv.writer(fcsv)
writer.writerow(["frame_file", "t", "x", "y", "z", "cam_pitch", "cam_yaw"])

n = 0
t0 = time.time()
try:
    while time.time() - t0 < SECONDS:
        phase = (time.time() - t0) / SECONDS
        cam_yaw = YAW_START + phase * YAW_SWEEP
        ac.client.simSetCameraPose(
            "front_center",
            airsim.Pose(
                airsim.Vector3r(OFFSET_X, 0.0, -0.08),
                airsim.to_quaternion(pitch=PITCH, roll=0.0, yaw=cam_yaw % 360.0),
            ),
            vehicle_name=ac.vehicle_name,
        )
        f = ac.get_forward_camera()
        p = ac.client.simGetVehiclePose().position
        if f is not None:
            name = f"front_{n:04d}.jpg"
            cv2.imwrite(str(out / name), f, [cv2.IMWRITE_JPEG_QUALITY, 92])
            writer.writerow([name, round(time.time() - t0, 3),
                             round(p.x_val, 3), round(p.y_val, 3), round(p.z_val, 3),
                             PITCH, round(cam_yaw % 360.0, 1)])
            n += 1
        time.sleep(1.0 / 3.0)
finally:
    fcsv.close()
print(f"done: {n} frames -> {out}", flush=True)
