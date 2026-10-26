"""Kinematic person-following against the live city sim.

This build of the UE4 AirSim server exposes NO movement APIs: there is no
takeoff, no land, no hover, and no moveBy* family anywhere on VehicleClient.
Every call in AirSimClient (takeoffAsync, moveByVelocityAsync, hoverAsync,
rotateToYawAsync, ...) would raise AttributeError.

What DOES exist is simSetVehiclePose, which teleports the vehicle. So flight is
kinematic rather than dynamic: we integrate the same control law the real
backend uses and write the pose each tick. Detection, identity, framing and
avoidance are all exercised for real; only the airframe dynamics are simulated.

Control law per tick (body frame, then rotated into world):
  yaw_rate = clamp(Kp_yaw * err_x)          centring the target
  vx       = clamp(Kp_size * (h_target - h_actual))   distance/framing
  vz       = clamp(Kp_y * err_y)            vertical centring
  then depth veto scales vx forward
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

import airsim

from garuda.flight.avoidance import ObstacleAvoider
from garuda.flight.shot_planner import ShotDirector
from garuda.perception.subject_lock import SubjectLock
from garuda.perception.yolo_detector import YoloDetector

# Gains are per-second rates; dt is small so a ~20 Hz tick is stable.
KP_YAW = 34.0     # deg/s per unit normalised x error
KP_VZ = 1.1       # m/s  per unit normalised y error
KP_VX = 2.6       # m/s  per unit framing error
YAW_MAX = 40.0
VZ_MAX = 0.9
VX_MAX = 3.0
DT = 0.05


def quat_yaw(q) -> float:
    return math.degrees(
        math.atan2(
            2.0 * (q.w_val * q.z_val + q.x_val * q.y_val),
            1.0 - 2.0 * (q.y_val**2 + q.z_val**2),
        )
    )


def make_quat_yaw(yaw_deg: float) -> airsim.Quaternionr:
    r = math.radians(yaw_deg) / 2.0
    return airsim.Quaternionr(w_val=math.cos(r), x_val=0.0, y_val=0.0, z_val=math.sin(r))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--command", default="follow that man")
    ap.add_argument("--duration", type=float, default=25.0)
    ap.add_argument("--conf", type=float, default=0.15)
    ap.add_argument("--port", type=int, default=41451)
    ap.add_argument("--record", default="follow_run")
    ap.add_argument(
        "--start-yaw",
        type=float,
        default=300.0,
        help="initial heading; the crowd survey found people at 20/260/300/320 deg",
    )
    ap.add_argument(
        "--start-x",
        type=float,
        default=0.0,
    )
    ap.add_argument("--start-y", type=float, default=0.0)
    ap.add_argument(
        "--backoff",
        type=float,
        default=22.0,
        help="metres behind the aim point along the heading (negative = forward)",
    )
    ap.add_argument(
        "--aim-x",
        type=float,
        default=0.0,
        help="NED point to face toward; the drone is placed backoff metres behind it",
    )
    ap.add_argument("--aim-y", type=float, default=0.0)
    ap.add_argument("--altitude", type=float, default=4.0, help="metres AGL")
    ap.add_argument(
        "--fov",
        type=float,
        default=0.0,
        help="keep the current camera FOV (0 = leave alone)",
    )
    a = ap.parse_args()

    client = airsim.VehicleClient(ip="127.0.0.1", port=a.port)
    print("[1/4] connecting...", flush=True)
    client.confirmConnection()

    det = YoloDetector()
    if not det.is_ready():
        print("detector unavailable")
        return 3
    print(f"    detector ready: {det.model_name} conf>={a.conf}", flush=True)

    spec = ShotDirector().parse(a.command)
    print(f"[2/4] shot: {spec.describe()}", flush=True)

    lock = SubjectLock()
    avoider = ObstacleAvoider()

    out = Path("logs/rec") / a.record
    out.mkdir(parents=True, exist_ok=True)
    log = open(out / "follow_telemetry.csv", "w", newline="")
    w = csv.writer(log)
    w.writerow(
        ["t", "x", "y", "z", "yaw", "locked", "conf", "h_ratio", "err_x", "err_y",
         "vx", "vz", "yaw_rate", "avoid", "clear_m", "identity_switches"]
    )

    p = client.simGetVehiclePose()
    ground_z = p.position.z_val
    yaw = a.start_yaw % 360.0
    # Place the drone at the requested heading, offset back so the crowd is
    # ahead of the nose, at the requested height. The survey found people at
    # 20/260/300/320 deg; default start is pulled back along that heading.
    back = a.backoff
    r0 = math.radians(yaw)
    if a.aim_x is None or (a.aim_x == 0.0 and a.aim_y == 0.0 and a.backoff == 0.0):
        # Default: exactly the survey pose, which is the only condition under
        # which people have actually been detected in this sim.
        pos = [0.0, 0.0, ground_z - 4.0]
        print("    using the surveyed pose (origin, 4 m AGL)", flush=True)
    else:
        pos = [
            a.aim_x - math.cos(r0) * back,
            a.aim_y - math.sin(r0) * back,
            ground_z - a.altitude,
        ]
    print(
        f"    drone NED=({pos[0]:.2f},{pos[1]:.2f},{pos[2]:.2f}) "
        f"yaw={yaw:.0f}deg alt={a.altitude:.1f}m AGL (ground {ground_z:.2f})",
        flush=True,
    )
    try:
        client.simSetVehiclePose(
            airsim.Pose(airsim.Vector3r(*pos), make_quat_yaw(yaw)), ignore_collision=True
        )
        print("    pose written - you should see the drone lift and turn", flush=True)
    except Exception as e:
        print(f"    initial pose failed: {e}")
        return 2

    from garuda.flight.airsim_client import AirSimClient

    ac = AirSimClient()
    ac.connect(timeout=20.0)
    ac.client = client
    ac.is_connected = True

    print(f"[3/4] running {a.duration:.0f}s - WATCH THE SIM WINDOW\n", flush=True)
    t0 = time.time()
    tick = 0
    switches = 0
    last_id = None
    lock_ticks = 0
    while time.time() - t0 < a.duration:
        now = time.time()
        frame = ac.get_forward_camera()
        detections = det.detect_persons(frame, conf=a.conf) if frame is not None else []

        target = lock.select(detections, frame) if (frame is not None and detections) else None

        if target is None:
            # Lost target: hold, do not servo a ghost.
            vx = vz = yaw_rate = 0.0
            avoid, clear_m = "HOLD", 99.0
        else:
            if last_id is not None and target.get("identity") not in (None, last_id):
                switches += 1
            last_id = target.get("identity", last_id)
            lock_ticks += 1

            err_x = float(target["err_x"])
            err_y = float(target["err_y"])
            h_ratio = float(target["h_ratio"])

            yaw_rate = max(-YAW_MAX, min(YAW_MAX, KP_YAW * err_x))
            vz = max(-VZ_MAX, min(VZ_MAX, KP_VZ * err_y))
            vx = max(-1.0, min(VX_MAX, KP_VX * (spec.target_h_ratio - h_ratio)))

            depth = None
            try:
                depth = ac.get_forward_depth("front_center")
            except Exception:
                pass
            dec = (
                avoider.evaluate_depth(depth)
                if depth is not None
                else avoider.evaluate_distance(99.0)
            )
            avoid, clear_m = dec.reason, dec.clear_m
            vx, _vy, _vz = avoider.apply(vx, 0.0, vz, dec)

        # Integrate in the body frame, then write the pose (no moveBy* exists).
        yaw += yaw_rate * DT
        yaw = yaw % 360.0
        r = math.radians(yaw)
        pos[0] += vx * math.cos(r) * DT
        pos[1] += vx * math.sin(r) * DT
        # Hold the commanded altitude: vertical control only trims, it does
        # not drift the drone down over the run.
        pos[2] = min(ground_z - 0.8, max(ground_z - a.altitude, pos[2] - vz * DT))

        try:
            client.simSetVehiclePose(
                airsim.Pose(airsim.Vector3r(*pos), make_quat_yaw(yaw)),
                ignore_collision=True,
            )
        except Exception as e:
            print(f"    simSetVehiclePose failed: {type(e).__name__}: {e}")
            return 2

        conf = 0.0 if target is None else float(target["confidence"])
        hr = 0.0 if target is None else float(target["h_ratio"])
        ex = 0.0 if target is None else float(target["err_x"])
        ey = 0.0 if target is None else float(target["err_y"])
        w.writerow(
            [round(now - t0, 2), *[round(v, 2) for v in pos], round(yaw, 1),
             int(target is not None), round(conf, 3), round(hr, 4),
             round(ex, 3), round(ey, 3), round(vx, 3), round(vz, 3),
             round(yaw_rate, 1), avoid, round(clear_m, 2), switches]
        )
        if frame is not None:
            vis = frame.copy()
            if target is not None:
                x1, y1, x2, y2 = target["bbox"]
                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.line(vis, (x1, y1), (x2, y2), (0, 255, 0), 1)
                cv2.line(vis, (x1, y2), (x2, y1), (0, 255, 0), 1)
                cv2.putText(vis, f'LOCK {conf:.2f}', (x1, max(12, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            else:
                cv2.putText(vis, "HOLD", (8, 24),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
            cv2.putText(vis, f"t={now-t0:.1f}s yaw={yaw:.0f} alt={ground_z-pos[2]:.1f}m",
                        (8, vis.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (255, 255, 255), 1)
            if tick % 3 == 0:
                cv2.imwrite(str(out / f"f_{tick:04d}.jpg"), vis,
                            [cv2.IMWRITE_JPEG_QUALITY, 90])
        if tick % 10 == 0:
            print(
                f"  t={now-t0:5.1f}s {'LOCK' if target else '----'} "
                f"conf={conf:.2f} h={hr:.3f} err=({ex:+.2f},{ey:+.2f}) "
                f"v=({vx:+.1f},{vz:+.1f}) yaw={yaw:3.0f} {avoid[:22]:22} "
                f"z={pos[2]-ground_z:+.1f}",
                flush=True,
            )
        tick += 1
        time.sleep(DT)

    log.close()
    print(f"\n[4/4] done. {tick} ticks, locked {lock_ticks} "
          f"({100*lock_ticks/max(tick,1):.0f}%), identity switches={switches}")
    print(f"    telemetry -> {out/'follow_telemetry.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
