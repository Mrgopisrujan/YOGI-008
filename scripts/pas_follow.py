"""Live person-following on the Project AirSim environment.

This is the demo the stock scene could not support: it has no people, so the
follow loop had nothing to lock onto. The subject is a generated humanoid
(``garuda.flight.humanoid_glb``) spawned into the scene over NNG and walked
along a closed NED path with ``import_ned_trajectory``.

What is exercised for real, nothing simulated:
  * YOLO person detection on the nose camera stream
  * SubjectLock identity, with switch counting
  * Smooth lateral strafe (vy) and distance servoing (vx) without camera whip
  * ObstacleAvoider veto with tracked target masking
  * real flight dynamics through ProjectAirSimBackend
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from garuda.flight.avoidance import ObstacleAvoider
from garuda.flight.humanoid_glb import humanoid_bytes
from garuda.flight.pas_client import ProjectAirSimBackend
from garuda.flight.shot_planner import ShotDirector
from garuda.perception.subject_lock import SubjectLock
from garuda.perception.yolo_detector import YoloDetector

KP_YAW = 28.0
YAW_MAX = 25.0
KP_VY = 1.0
KP_VZ = 1.1
KP_VX = 2.4
VY_MAX = 0.85
VZ_MAX = 0.8
VX_MAX = 2.8
DT = 0.15

# Search sweep parameters
SEARCH_YAW_BASE_DPS = 10.0
SEARCH_YAW_MAX_DPS = 15.0
SEARCH_SWEEP_DEG = 20.0


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=40.0)
    ap.add_argument("--conf", type=float, default=0.12)
    ap.add_argument("--command", default="follow that man")
    ap.add_argument("--altitude", type=float, default=2.4)
    ap.add_argument("--record", default="pas_follow")
    ap.add_argument(
        "--eagle-views",
        type=int,
        default=0,
        help="cycle the main window N times to reach the overhead camera",
    )
    a = ap.parse_args()

    log = lambda *s: print(*s, flush=True)

    spec = ShotDirector().parse(a.command)
    log(f"[1/5] shot: {spec.describe()}")

    b = ProjectAirSimBackend()
    if not b.connect():
        log("connect FAILED - is CityEnviron running?")
        return 1
    log(f"      scene={b.scene} drone={b.drone_name}")

    out = Path("logs/rec") / a.record
    out.mkdir(parents=True, exist_ok=True)

    try:
        # ── subject ─────────────────────────────────────────────────────
        # Walker1 starts on the main road in front of the drone.
        # Drone starts on the avenue at (6.5, 8.0) heading 90° (+Y).
        # Main road avenue extends to the left (+X from 6.5 up to 16.0).
        # Buildings are on the right (-X <= 5.5).
        spawn = (7.0, 14.0)
        actor = b.spawn_glb("Walker1", humanoid_bytes(), (spawn[0], spawn[1], 0.0), scale=(1.25, 1.25, 1.25))
        if not actor:
            log("could not spawn the humanoid")
            return 2
        log(f"[2/5] spawned {actor} on main road")

        # Main road walking route -> Weaves across road lanes to the left -> Crosses intersection -> Turns into other street
        loop = [
            (7.0, 14.0),   # 1. Main road in front of drone
            (7.5, 18.0),   # 2. Main road moving forward
            (8.5, 22.0),   # 3. Weaving towards center lanes of main road
            (10.0, 26.0),  # 4. Across intersection zebra crossing
            (12.0, 30.0),  # 5. Across road approaching other street on left
            (14.0, 34.0),  # 6. Turning into intersecting other street on left
            (16.0, 38.0),  # 7. Down the road of the other street
            (16.0, 42.0),  # 8. Further into the other street
            (14.0, 42.0),  # 9. Smooth turn in other street
            (12.0, 38.0),  # 10. Heading back towards intersection
            (10.0, 34.0),  # 11.
            (8.5, 28.0),   # 12.
            (7.5, 20.0),   # 13.
            (7.0, 14.0),   # 14. Back to start
        ]

        det = YoloDetector(conf_threshold=a.conf)
        if not det.is_ready():
            log("detector unavailable")
            return 3
        log(f"      detector {det.model_name}")

        if not b.takeoff(altitude_m=a.altitude):
            log("takeoff failed")
            return 3
        log(f"[3/5] airborne at {b.altitude_agl():.2f} m AGL")

        drone_actor = None
        for _ in range(20):
            if b.get_forward_camera() is not None:
                break
            time.sleep(0.5)
        log(f"      camera topics: {b.frames_received()}")
        log(f"      heading: {b.heading_deg():.1f} deg (facing East along avenue)")

        if a.eagle_views:
            log(f"      cycling the window {a.eagle_views}x for the overhead view")
            b.cycle_view(a.eagle_views)

        lock = SubjectLock(
            min_confidence=0.10,
            low_confidence=0.06,
            max_lost_frames=25,
            max_coast_frames=25,
        )
        avoider = ObstacleAvoider(
            stop_distance_m=1.0,
            warning_distance_m=2.5,
            max_strafe_mps=1.5,
        )
        from garuda.flight.actor_stepper import ActorStepper
        WALK_SPEED = 0.75
        stepper = ActorStepper(b._world, actor, loop, speed_mps=WALK_SPEED)

        # Bootstrap initial visual lock before starting follow timer
        log("      bootstrapping initial visual lock...")
        last_target = None
        for _ in range(25):
            f_init = b.get_forward_camera()
            if f_init is not None:
                d_init = det.detect_persons(f_init, conf=a.conf)
                t_init = lock.update(d_init, f_init)
                if t_init is not None:
                    last_target = t_init
                    log(f"      initial lock acquired (conf={t_init['confidence']:.2f})")
                    break
            time.sleep(0.2)

        log(f"[4/5] running {a.duration:.0f}s - WATCH THE SIM WINDOW\n")
        logfile = open(out / "follow_telemetry.csv", "w", newline="")
        w = csv.writer(logfile)
        w.writerow(
            ["t", "x", "y", "alt", "heading", "locked", "tracking_state", "conf",
             "h_ratio", "err_x", "err_y", "vx", "vy", "vz", "yaw_rate", "avoid", "clear_m",
             "switches"]
        )

        t0 = time.time()
        last_step_t = t0
        tick = 0
        lock_ticks = 0
        switches = 0
        last_id = None
        errs: list[float] = []
        avoid_hits: dict[str, int] = {}
        lost_ticks = 0
        search_sign = 1.0
        search_sweep_deg = 0.0
        tel = b.get_telemetry()

        # Dead-reckoning drone world position for DroneVisual GLB sync.
        # get_ground_truth_pose() returns the body-frame spawn origin every tick.
        # Integrate commanded body-frame velocity into world frame instead.
        dr_x: float = 6.5   # drone spawn X
        dr_y: float = 8.0   # drone spawn Y
        dr_z: float = float(a.altitude)

        while time.time() - t0 < a.duration:
            now = time.time()
            dt_step = min(0.35, max(0.05, now - last_step_t))
            last_step_t = now
            stepper.step(dt=dt_step)
            frame = b.get_forward_camera()
            if frame is not None:
                detections = det.detect_persons(frame, conf=a.conf)
                if tick < 5:
                    log(f"  [DEBUG tick {tick}] detections={len(detections)} confs={[round(d['confidence'], 2) for d in detections]}")
                last_target = lock.update(detections, frame)

            target = last_target
            tracking_state = "SEARCH" if target is None else target.get("tracking_state", "LOCKED")
            is_real_lock = (target is not None and not target.get("predicted", False))

            # Proportional heading hold to avenue direction (90.0 deg East).
            # Smoothly dampens any yaw drift without large bursts or spinning.
            cur_hdg = tel.get("heading", 90.0)
            hdg_err = (90.0 - cur_hdg + 180.0) % 360.0 - 180.0
            stabilize_yaw = clamp(0.35 * hdg_err, -2.5, 2.5)

            if is_real_lock:
                # Real visual detection confirmed
                lost_ticks = 0
                search_sweep_deg = 0.0
                if last_id is not None and target.get("identity") not in (None, last_id):
                    switches += 1
                last_id = target.get("identity", last_id)
                lock_ticks += 1

                err_x = float(target["err_x"])
                err_y = float(target["err_y"])
                h_ratio = float(target["h_ratio"])
                errs.append(abs(err_x))

                # Active visual yaw tracking: turn camera towards subject as they change direction
                yaw_rate = clamp(KP_YAW * err_x, -YAW_MAX, YAW_MAX)

                # Smooth lateral strafe (vy) to match subject lateral movement
                vy = clamp(KP_VY * err_x, -VY_MAX, VY_MAX)

                alt_err = a.altitude - tel.get("alt_agl", a.altitude)
                vz = clamp(-1.0 * alt_err, -0.6, 0.6)

                # Target framing: 0.28 maintains 6.0-7.5m standoff so full human
                # is always visible and framed cleanly without overrunning.
                TARGET_H_RATIO = 0.28
                vx = clamp(WALK_SPEED + 2.5 * (TARGET_H_RATIO - h_ratio), 0.1, 1.25)

                depth = b.get_forward_depth()
                if depth is None:
                    dec = avoider.evaluate_distance(0.0)
                else:
                    x1, y1, x2, y2 = target["bbox"]
                    ih, iw = depth.shape[:2]
                    bx1, by1 = max(0, int(x1)), max(0, int(y1))
                    bx2, by2 = min(iw, int(x2)), min(ih, int(y2))
                    if bx2 > bx1 and by2 > by1:
                        target_dist = float(np.nanmedian(depth[by1:by2, bx1:bx2]))
                        if 0.5 < target_dist < 4.5:
                            vx = min(vx, 0.4)
                        if 0.5 < target_dist < 3.6:
                            vx = 0.0  # Stop forward motion and let subject open up distance

                    # Mask tracked target bbox so obstacle avoider doesn't treat the person as a wall
                    depth_masked = depth.copy()
                    mx1, my1 = max(0, int(x1) - 20), max(0, int(y1) - 20)
                    mx2, my2 = min(iw, int(x2) + 20), min(ih, int(y2) + 20)
                    depth_masked[my1:my2, mx1:mx2] = 25.0
                    # Mask bottom 40% of frame — the DroneVisual GLB body appears
                    # at the bottom of the forward camera and causes false obstacle stops.
                    self_mask_y = int(ih * 0.60)
                    depth_masked[self_mask_y:, :] = 25.0
                    dec = avoider.evaluate_depth(depth_masked)
                avoid, clear_m = dec.reason, dec.clear_m
                avoid_hits[dec.reason] = avoid_hits.get(dec.reason, 0) + 1
                vx, vy, vz = avoider.apply(vx, vy, vz, dec)

            elif target is not None and target.get("predicted", False):
                # Coasting (brief occlusion): hold course and match walking speed along avenue
                lost_ticks += 1
                lock_ticks += 1
                vx = min(WALK_SPEED * 0.85, 0.72)
                vy = 0.0
                alt_err = a.altitude - tel.get("alt_agl", a.altitude)
                vz = clamp(-1.0 * alt_err, -0.6, 0.6)
                yaw_rate = clamp(18.0 * float(target.get("err_x", 0.0)), -14.0, 14.0)
                avoid, clear_m = "COAST", float("nan")
                depth = b.get_forward_depth()
                if depth is not None:
                    d_coast = depth.copy()
                    d_coast[int(d_coast.shape[0] * 0.60):, :] = 25.0  # mask drone body
                    dec = avoider.evaluate_depth(d_coast)
                    avoid_hits[dec.reason] = avoid_hits.get(dec.reason, 0) + 1
                    vx, vy, vz = avoider.apply(vx, vy, vz, dec)
                    clear_m = dec.clear_m

            else:
                # Fully lost: cruise gently forward to reacquire
                lost_ticks += 1
                vx = 0.35
                vy = 0.0
                alt_err = a.altitude - tel.get("alt_agl", a.altitude)
                vz = clamp(-1.0 * alt_err, -0.6, 0.6)
                yaw_rate = 0.0
                avoid, clear_m = "SEARCH", float("nan")
                depth = b.get_forward_depth()
                if depth is not None:
                    d_srch = depth.copy()
                    d_srch[int(d_srch.shape[0] * 0.60):, :] = 25.0  # mask drone body
                    dec = avoider.evaluate_depth(d_srch)
                    avoid_hits[dec.reason] = avoid_hits.get(dec.reason, 0) + 1
                    vx, vy, vz = avoider.apply(vx, 0.0, vz, dec)
                    clear_m = dec.clear_m

            ok = b.move_velocity_body(
                vx=vx, vy=vy, vz=vz, yaw_rate_dps=yaw_rate, duration_s=DT
            )
            tel = b.get_telemetry()
            tel["heading"] = b.heading_deg()

            # Dead-reckoning: integrate body-frame velocity → world frame
            cur_hdg_rad = math.radians(tel.get("heading", 90.0))
            dr_x += (vx * math.cos(cur_hdg_rad) - vy * math.sin(cur_hdg_rad)) * dt_step
            dr_y += (vx * math.sin(cur_hdg_rad) + vy * math.cos(cur_hdg_rad)) * dt_step
            dr_z = float(tel.get("alt_agl", a.altitude))

            if drone_actor and b._world is not None:
                try:
                    from projectairsim.types import Pose
                    dhdg = tel.get("heading", 90.0)
                    h_ang = math.radians(dhdg) * 0.5
                    d_pose = Pose({
                        "frame_id": "DEFAULT_ID",
                        "translation": {"x": dr_x, "y": dr_y, "z": -dr_z},
                        "rotation": {"w": math.cos(h_ang), "x": 0.0, "y": 0.0, "z": math.sin(h_ang)}
                    })
                    b._world.set_object_pose(drone_actor, d_pose, teleport=True)
                except Exception:
                    pass

            conf = 0.0 if target is None else float(target["confidence"])
            hr = 0.0 if target is None else float(target["h_ratio"])
            ex = 0.0 if target is None else float(target["err_x"])
            ey = 0.0 if target is None else float(target["err_y"])
            w.writerow(
                [round(now - t0, 2), round(dr_x, 2), round(dr_y, 2),
                 round(dr_z, 2), round(tel.get("heading", float("nan")), 2),
                 int(is_real_lock), tracking_state, round(conf, 3),
                 round(hr, 4), round(ex, 3), round(ey, 3), round(vx, 3), round(vy, 3), round(vz, 3),
                 round(yaw_rate, 1), avoid, round(clear_m, 2), switches]
            )


            if frame is not None:
                vis = frame.copy()
                ih, iw = vis.shape[:2]

                # Top broadcast HUD banner
                cv2.rectangle(vis, (0, 0), (iw, 28), (15, 15, 15), -1)
                cv2.line(vis, (0, 28), (iw, 28), (0, 255, 180), 1)
                cv2.putText(
                    vis,
                    f"GARUDA DRONE-OS  |  TARGET: WALKER1  |  MODE: {spec.name.upper()}",
                    (12, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 180), 1, cv2.LINE_AA,
                )

                if is_real_lock:
                    # Draw target box ONLY when the person is actually detected
                    x1, y1, x2, y2 = target["bbox"]
                    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.line(vis, (x1, y1), (x2, y2), (0, 255, 0), 1)
                    cv2.line(vis, (x1, y2), (x2, y1), (0, 255, 0), 1)
                    cv2.putText(vis, f"LOCK {conf:.2f}", (x1, max(38, y1 - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2, cv2.LINE_AA)
                elif tracking_state == "LOCKED_PREDICTED":
                    # Coasting: do not draw an empty phantom box; show clean status
                    cv2.putText(vis, "COASTING (HOLDING COURSE)", (12, 50), cv2.FONT_HERSHEY_SIMPLEX,
                                0.65, (0, 200, 255), 2, cv2.LINE_AA)
                else:
                    cv2.putText(vis, "SEARCHING...", (12, 50), cv2.FONT_HERSHEY_SIMPLEX,
                                0.65, (0, 200, 255), 2, cv2.LINE_AA)

                # Bottom telemetry strip
                cv2.rectangle(vis, (0, ih - 26), (iw, ih), (15, 15, 15), -1)
                cv2.line(vis, (0, ih - 26), (iw, ih - 26), (0, 255, 180), 1)
                ratio_pct = int(100.0 * lock_ticks / max(tick, 1))
                hud_txt = (
                    f"T:{now-t0:.1f}s | ALT:{tel.get('alt_agl',0):.1f}m | "
                    f"HDG:{tel.get('heading',0):.0f}° | "
                    f"LOCK:{ratio_pct}% | SWITCH:{switches} | AVOID:{avoid[:14]}"
                )
                cv2.putText(
                    vis, hud_txt, (10, ih - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA,
                )

                if tick % 2 == 0:
                    cv2.imwrite(str(out / f"f_{tick:04d}.jpg"), vis,
                                [cv2.IMWRITE_JPEG_QUALITY, 90])

            eagle_frame = b.get_eagle_camera()
            if eagle_frame is not None and tick % 2 == 0:
                evis = eagle_frame.copy()
                eh, ew = evis.shape[:2]
                cv2.rectangle(evis, (0, 0), (ew, 28), (15, 15, 15), -1)
                cv2.line(evis, (0, 28), (ew, 28), (0, 200, 255), 1)
                cv2.putText(
                    evis,
                    "GARUDA DRONE-OS  |  EAGLE EYE OVERHEAD VIEW  |  TARGET: WALKER1",
                    (12, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1, cv2.LINE_AA,
                )
                ratio_pct = int(100.0 * lock_ticks / max(tick, 1))
                ehud = (
                    f"T:{now-t0:.1f}s | ALT:{tel.get('alt_agl',0):.1f}m | "
                    f"HDG:{tel.get('heading',0):.0f}° | "
                    f"LOCK:{ratio_pct}% | SWITCH:{switches} | AVOID:{avoid[:14]}"
                )
                cv2.putText(
                    evis, ehud, (10, eh - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA,
                )
                cv2.imwrite(str(out / f"eagle_{tick:04d}.jpg"), evis,
                            [cv2.IMWRITE_JPEG_QUALITY, 90])
            if tick % 8 == 0:
                log(f"  t={now-t0:5.1f}s {tracking_state:16s} "
                    f"conf={conf:.2f} h={hr:.3f} err=({ex:+.2f},{ey:+.2f}) "
                    f"v=({vx:+.1f},{vy:+.1f},{vz:+.1f}) yaw={yaw_rate:+5.1f} "
                    f"alt={tel.get('alt_agl',0):4.1f} {avoid[:20]:20} d={clear_m}")
            tick += 1
            time.sleep(DT)

        logfile.close()
        log(f"\n[5/5] done. {tick} ticks, locked or predicted {lock_ticks} "
            f"({100 * lock_ticks / max(tick, 1):.0f}%), identity switches={switches}")
        if errs:
            log(f"    mean |err_x| while locked: {sum(errs)/len(errs):.3f}")
        log(f"    avoidance outcomes: {avoid_hits}")
        log(f"    frames: {b.frames_received()}")
        log(f"    telemetry + frames -> {out}")
        return 0 if lock_ticks > 0 else 4
    finally:
        try:
            b.hover()
        except Exception:
            pass
        b.close()


if __name__ == "__main__":
    ret = main()
    os._exit(ret)

