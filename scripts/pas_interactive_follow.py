#!/usr/bin/env python3
"""
GarudaOne DroneOS — Interactive Humanoid Keyboard Control + Autonomous Drone Follow.

Gives the operator direct, real-time keyboard control over the spawned walking
humanoid (Walker1) using WASD or Arrow keys. The drone stays in the air, actively
tracking, pursuing, and following the human through the streets of CityEnviron
while avoiding obstacles.

Controls work whether you click/focus the live video feed window OR the terminal!

Usage:
    ./venv/bin/python scripts/pas_interactive_follow.py
    ./venv/bin/python scripts/pas_interactive_follow.py --altitude 3.5

Controls:
    [W] or [↑] Up Arrow    : Walk Forward (0.7m)
    [S] or [↓] Down Arrow  : Walk Backward (0.7m)
    [A] or [←] Left Arrow  : Turn Left (15°)
    [D] or [→] Right Arrow : Turn Right (15°)
    [SPACE]                : Stand Still
    [H]                    : Toggle Drone Hover in Place
    [L]                    : Land Drone & Exit
    [Q] / [ESC]            : Quit & Land
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import cv2
import numpy as np

from garuda.flight.avoidance import ObstacleAvoider
from garuda.flight.humanoid_glb import humanoid_bytes
from garuda.flight.manual_actor import ManualActorController, TerminalKeyReader
from garuda.flight.pas_client import ProjectAirSimBackend
from garuda.flight.shot_planner import ShotDirector
from garuda.perception.subject_lock import SubjectLock
from garuda.perception.yolo_detector import YoloDetector

# Visual styles
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"

# Servo gains
KP_YAW = 34.0
KP_VZ = 1.1
KP_VX = 2.6
YAW_MAX = 40.0
VZ_MAX = 0.9
VX_MAX = 3.0
DT = 0.08

SEARCH_YAW_BASE_DPS = 14.0
SEARCH_YAW_MAX_DPS = 20.0
SEARCH_SWEEP_DEG = 35.0
SEARCH_VX = 0.35

WINDOW_TITLE = "Garuda Drone Tracking — [CLICK HERE OR TERMINAL TO DRIVE WITH WASD]"


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def normalize_cv_key(k: int) -> Optional[str]:
    """Map OpenCV keycodes (including Linux X11 arrow keys) to standard action strings."""
    if k == -1:
        return None
    # Linux X11 arrow keys
    if k in (65362, 82, 0xFF52):
        return "UP"
    if k in (65364, 84, 0xFF54):
        return "DOWN"
    if k in (65361, 81, 0xFF51):
        return "LEFT"
    if k in (65363, 83, 0xFF53):
        return "RIGHT"
    if k in (27,):
        return "ESC"
    if k == 32:
        return "SPACE"
    try:
        ch = chr(k & 0xFF).upper()
        if ch in ("W", "S", "A", "D", "H", "L", "Q"):
            return ch
    except Exception:
        pass
    return None


def print_banner(step_size: float, turn_angle: float):
    print(f"\n{BOLD}{CYAN}{'=' * 76}{RESET}")
    print(f"{BOLD}{CYAN}  🎮 GARUDAONE — Interactive Keyboard Humanoid & Autonomous Drone Follow{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 76}{RESET}")
    print(f"  {BOLD}Direct real-time keyboard control of Walker1 is ACTIVE!{RESET}")
    print(f"  You can drive the man either from this terminal OR the camera window.")
    print(f"  The drone will pursue, frame, and follow him as he walks through the city.")
    print(f"{BOLD}{CYAN}{'-' * 76}{RESET}")
    print(f"  {BOLD}KEYBOARD CONTROLS:{RESET}")
    print(f"    {GREEN}[W]{RESET} or {GREEN}[↑] Up Arrow{RESET}    : Walk Forward (+{step_size:.1f}m)")
    print(f"    {GREEN}[S]{RESET} or {GREEN}[↓] Down Arrow{RESET}  : Walk Backward (-{step_size:.1f}m)")
    print(f"    {GREEN}[A]{RESET} or {GREEN}[←] Left Arrow{RESET}  : Turn Left ({turn_angle:.0f}°)")
    print(f"    {GREEN}[D]{RESET} or {GREEN}[→] Right Arrow{RESET} : Turn Right ({turn_angle:.0f}°)")
    print(f"    {YELLOW}[SPACE]{RESET}                : Stand Still")
    print(f"    {CYAN}[H]{RESET}                    : Toggle Drone Hover")
    print(f"    {RED}[L]{RESET}                    : Land Drone & Exit")
    print(f"    {RED}[Q]{RESET} or {RED}[ESC]{RESET}            : Quit & Land")
    print(f"{BOLD}{CYAN}{'=' * 76}{RESET}\n")


def draw_hud(
    frame: np.ndarray,
    target: Optional[dict],
    tracking_state: str,
    man_ctrl: ManualActorController,
    drone_tel: dict,
    dist_m: float,
    avoid_reason: str,
    last_action: str,
    hover_mode: bool,
) -> np.ndarray:
    """Render a clean, professional broadcast HUD on the drone camera frame."""
    vis = frame.copy()
    h, w = vis.shape[:2]

    # Semi-transparent top bar
    overlay = vis.copy()
    cv2.rectangle(overlay, (0, 0), (w, 52), (15, 15, 20), -1)
    cv2.rectangle(overlay, (0, h - 42), (w, h), (15, 15, 20), -1)
    cv2.addWeighted(overlay, 0.72, vis, 0.28, 0, vis)

    # Target bounding box
    if target is not None:
        x1, y1, x2, y2 = target["bbox"]
        color = (0, 255, 0) if tracking_state == "LOCKED" else (0, 180, 255)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
        # Target center cross
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        cv2.drawMarker(vis, (cx, cy), color, cv2.MARKER_CROSS, 16, 2)
        conf_val = float(target.get("confidence", 0.0))
        label = f"SUBJECT LOCKED ({conf_val:.2f})" if tracking_state == "LOCKED" else "PREDICTED TRAJECTORY"
        cv2.rectangle(vis, (x1, max(0, y1 - 22)), (x1 + 180, max(0, y1)), color, -1)
        cv2.putText(vis, label, (x1 + 4, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
    else:
        cv2.putText(vis, "SEARCHING TARGET...", (14, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2, cv2.LINE_AA)

    # Top Status Text
    state_color = (0, 255, 0) if tracking_state == "LOCKED" else (0, 200, 255)
    cv2.putText(
        vis,
        f"GARUDAONE TRACKING | STATUS: {tracking_state}",
        (12, 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        state_color,
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        vis,
        f"Walker: ({man_ctrl.x:.1f}, {man_ctrl.y:.1f}) {man_ctrl.yaw_deg:.0f} deg | Drone: ({drone_tel.get('x', 0):.1f}, {drone_tel.get('y', 0):.1f}) Alt:{drone_tel.get('alt_agl', 0):.1f}m | Dist: {dist_m:.1f}m",
        (12, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.44,
        (220, 220, 220),
        1,
        cv2.LINE_AA,
    )

    # Center-left action box
    action_color = (0, 255, 255) if "Turn" in last_action else (0, 255, 0) if "Forward" in last_action else (200, 200, 200)
    cv2.putText(
        vis,
        f"MAN ACTION: {last_action}",
        (14, 82 if target is not None else 115),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        action_color,
        2,
        cv2.LINE_AA,
    )

    if hover_mode:
        cv2.putText(vis, "[DRONE HOVER HOLD ACTIVE]", (w - 240, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    # Bottom helper bar
    cv2.putText(
        vis,
        "CONTROLS: [W/S] Walk  [A/D] Turn  [SPACE] Stop  [H] Hover  [L/Q] Land & Exit",
        (12, h - 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (200, 255, 200),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        vis,
        f"Obstacle: {avoid_reason[:22]} | Total Walked: {man_ctrl.total_distance_m:.1f}m",
        (12, h - 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        (170, 170, 170),
        1,
        cv2.LINE_AA,
    )

    return vis


def main() -> int:
    ap = argparse.ArgumentParser(description="Interactive Humanoid & Drone Follow")
    ap.add_argument("--altitude", type=float, default=3.5, help="Drone altitude (m AGL)")
    ap.add_argument("--conf", type=float, default=0.15, help="YOLO confidence threshold")
    ap.add_argument("--record", default="interactive_demo", help="Recording directory name")
    ap.add_argument("--step-size", type=float, default=0.7, help="Man walking step size (m)")
    ap.add_argument("--turn-angle", type=float, default=15.0, help="Man turn angle (deg)")
    args = ap.parse_args()

    print_banner(args.step_size, args.turn_angle)

    # 1. Connect to Project AirSim / CityEnviron
    print(f"{CYAN}[1/4] Connecting to Project AirSim / CityEnviron...{RESET}")
    backend = ProjectAirSimBackend()
    if not backend.connect():
        print(f"{RED}[FAIL] Could not connect to simulator — is CityEnviron running?{RESET}")
        return 1
    print(f"{GREEN}[OK] Connected: scene={backend.scene} drone={backend.drone_name}{RESET}")

    # 2. Spawn humanoid subject (Walker1)
    spawn = (-1.0, 15.0, 0.0)
    print(f"{CYAN}[2/4] Spawning humanoid subject (Walker1) at {spawn[:2]}...{RESET}")
    actor = backend.spawn_glb("Walker1", humanoid_bytes(), spawn)
    if not actor:
        print(f"{RED}[FAIL] Could not spawn humanoid subject{RESET}")
        backend.close()
        return 2

    man_ctrl = ManualActorController(
        world=backend._world,
        actor_name=actor,
        initial_pos=spawn,
        initial_yaw_deg=90.0,
        step_distance_m=args.step_size,
        turn_angle_deg=args.turn_angle,
        lock=backend._lock,
    )
    print(f"{GREEN}[OK] Walker1 ready at position ({man_ctrl.x:.1f}, {man_ctrl.y:.1f}) heading {man_ctrl.yaw_deg:.0f}°{RESET}")

    # 3. Vision & tracking systems
    print(f"{CYAN}[3/4] Initializing YOLO detector & flight systems...{RESET}")
    det = YoloDetector()
    if not det.is_ready():
        print(f"{RED}[FAIL] YOLO model not available{RESET}")
        backend.close()
        return 3
    print(f"{GREEN}[OK] YOLO detector loaded: {det.model_name}{RESET}")

    spec = ShotDirector().parse("follow that man")
    lock = SubjectLock(min_confidence=args.conf, low_confidence=args.conf * 0.7)
    avoider = ObstacleAvoider(stop_distance_m=2.0, warning_distance_m=4.5, max_strafe_mps=1.5)

    # 4. Takeoff and point at subject
    print(f"{CYAN}[4/4] Launching drone to {args.altitude:.1f}m AGL...{RESET}")
    if not backend.takeoff(altitude_m=args.altitude):
        print(f"{RED}[FAIL] Drone takeoff failed{RESET}")
        backend.close()
        return 4

    # Wait for camera frames
    for _ in range(25):
        if backend.get_forward_camera() is not None:
            break
        time.sleep(0.4)

    # Rotate drone to face the humanoid
    tel0 = backend.get_telemetry()
    brg = math.degrees(math.atan2(man_ctrl.y - tel0.get("y", 0.0), man_ctrl.x - tel0.get("x", 0.0)))
    print(f"  Turning drone {brg:+.0f}° to face Walker1...")
    backend.rotate_to_heading(brg)
    time.sleep(0.8)
    print(f"{GREEN}✅ Drone airborne at {backend.altitude_agl():.1f}m AGL. Tracking active!{RESET}")

    # Prepare GUI window
    gui_available = False
    try:
        cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_TITLE, 960, 540)
        gui_available = True
    except Exception as e:
        print(f"{YELLOW}[WARN] Could not initialize OpenCV GUI window ({e}). Running in terminal-only mode.{RESET}")

    print(f"\n{BOLD}{GREEN}👉 START WALKING! Press [W] / [↑] to move forward, [A] / [D] to turn.{RESET}")
    print(f"{DIM}   (You can click on the camera window OR keep typing in the terminal!){RESET}\n")

    # Logging setup
    rec_dir = Path("logs/rec") / args.record
    rec_dir.mkdir(parents=True, exist_ok=True)
    telemetry_file = rec_dir / "interactive_telemetry.csv"
    logfile = open(telemetry_file, "w", newline="")
    w = csv.writer(logfile)
    w.writerow(
        ["t", "man_x", "man_y", "man_yaw", "drone_x", "drone_y", "drone_alt",
         "drone_heading", "state", "conf", "standoff_est", "vx", "vy", "vz", "yaw_rate", "avoid"]
    )

    t0 = time.time()
    tick = 0
    lock_ticks = 0
    last_frame_count = backend.frames_received().get("forward", 0)
    last_target = None
    lost_ticks = 0
    search_sign = 1.0
    search_sweep_deg = 0.0
    drone_hover_mode = False
    last_action_str = "Standing"

    try:
        with TerminalKeyReader() as term_reader:
            while True:
                t_now = time.time() - t0

                # ── Capture keyboard input from GUI window AND/OR Terminal ──
                cv_k = -1
                if gui_available:
                    cv_k = cv2.waitKeyEx(1)

                key = term_reader.get_key() or normalize_cv_key(cv_k)

                if key is not None:
                    if key in ("Q", "ESC"):
                        print(f"\n{CYAN}Operator requested exit. Landing drone...{RESET}")
                        break
                    elif key == "L":
                        print(f"\n{YELLOW}Operator commanded land. Landing drone...{RESET}")
                        break
                    elif key == "H":
                        drone_hover_mode = not drone_hover_mode
                        state_msg = "ENGAGED" if drone_hover_mode else "DISENGAGED (Resuming follow)"
                        last_action_str = f"Hover {state_msg}"
                        print(f"\n{CYAN}🚁 Drone hover hold: {state_msg}{RESET}")
                    elif key == "SPACE":
                        last_action_str = "Standing Still"
                        print(f"⏸️  [MAN] Stand still at ({man_ctrl.x:.1f}, {man_ctrl.y:.1f})")
                    elif key in ("W", "UP"):
                        man_ctrl.move_forward()
                        last_action_str = f"Forward ({man_ctrl.x:.1f}, {man_ctrl.y:.1f})"
                        print(f"🚶 [MAN] Forward ➜ ({man_ctrl.x:.1f}, {man_ctrl.y:.1f}) hdg={man_ctrl.yaw_deg:.0f}°  tot={man_ctrl.total_distance_m:.1f}m")
                    elif key in ("S", "DOWN"):
                        man_ctrl.move_backward()
                        last_action_str = f"Backward ({man_ctrl.x:.1f}, {man_ctrl.y:.1f})"
                        print(f"🚶 [MAN] Backward ➜ ({man_ctrl.x:.1f}, {man_ctrl.y:.1f}) hdg={man_ctrl.yaw_deg:.0f}°")
                    elif key in ("A", "LEFT"):
                        man_ctrl.turn_left()
                        last_action_str = f"Turn Left ({man_ctrl.yaw_deg:.0f}°)"
                        print(f"🔄 [MAN] Turn Left ➜ hdg={man_ctrl.yaw_deg:.0f}°")
                    elif key in ("D", "RIGHT"):
                        man_ctrl.turn_right()
                        last_action_str = f"Turn Right ({man_ctrl.yaw_deg:.0f}°)"
                        print(f"🔄 [MAN] Turn Right ➜ hdg={man_ctrl.yaw_deg:.0f}°")

                # ── Camera & YOLO Tracking ─────────────────────────────
                frame = backend.get_forward_camera()
                frame_count = backend.frames_received().get("forward", last_frame_count)
                if frame is not None and frame_count != last_frame_count:
                    detections = det.detect_persons(frame, conf=args.conf)
                    last_target = lock.update(detections, frame)
                    last_frame_count = frame_count

                target = last_target
                tracking_state = "SEARCH" if target is None else target.get("tracking_state", "LOCKED")

                # ── Flight Control Law ─────────────────────────────────
                if drone_hover_mode:
                    vx, vy, vz, yaw_rate = 0.0, 0.0, 0.0, 0.0
                    avoid = "HOVER_HOLD"
                elif target is None:
                    lost_ticks += 1
                    vx = SEARCH_VX
                    vy = 0.0
                    vz = 0.0
                    if lost_ticks == 1:
                        tel_cur = backend.get_telemetry()
                        desired_hdg = math.degrees(math.atan2(man_ctrl.y - tel_cur.get("y", 0.0), man_ctrl.x - tel_cur.get("x", 0.0)))
                        cur_hdg = backend.heading_deg()
                        d_hdg = (desired_hdg - cur_hdg + 180.0) % 360.0 - 180.0
                        search_sign = 1.0 if d_hdg >= 0 else -1.0
                        search_sweep_deg = 0.0

                    yaw_rate = search_sign * clamp(
                        SEARCH_YAW_BASE_DPS + 0.25 * abs(search_sweep_deg),
                        SEARCH_YAW_BASE_DPS, SEARCH_YAW_MAX_DPS,
                    )
                    search_sweep_deg += yaw_rate * DT
                    if abs(search_sweep_deg) >= SEARCH_SWEEP_DEG:
                        search_sign *= -1.0
                        search_sweep_deg = math.copysign(SEARCH_SWEEP_DEG, search_sweep_deg)

                    depth = backend.get_forward_depth()
                    if depth is not None:
                        dec = avoider.evaluate_depth(depth)
                        vx, vy, vz = avoider.apply(vx, 0.0, vz, dec)
                        avoid = dec.reason
                    else:
                        vx = 0.0
                        avoid = "NO_DEPTH"
                else:
                    lost_ticks = 0
                    lock_ticks += 1
                    err_x = float(target["err_x"])
                    err_y = float(target["err_y"])
                    h_ratio = float(target["h_ratio"])

                    if abs(err_x) < 0.08:
                        yaw_rate = 0.0
                    else:
                        yaw_rate = clamp(KP_YAW * err_x, -YAW_MAX, YAW_MAX)

                    vz = clamp(KP_VZ * err_y, -VZ_MAX, VZ_MAX)
                    vx = clamp(KP_VX * (spec.target_h_ratio - h_ratio), -1.0, VX_MAX)
                    vy = 0.0

                    depth = backend.get_forward_depth()
                    if depth is not None:
                        dec = avoider.evaluate_depth(depth)
                        vx, vy, vz = avoider.apply(vx, 0.0, vz, dec)
                        avoid = dec.reason
                    else:
                        avoid = "CLEAR"

                # Send velocity command to drone
                backend.move_velocity_body(vx=vx, vy=vy, vz=vz, yaw_rate_dps=yaw_rate, duration_s=DT)

                # ── Telemetry & Logging ────────────────────────────────
                tel = backend.get_telemetry()
                drone_hdg = backend.heading_deg()
                conf_val = float(target.get("confidence", 0.0)) if target else 0.0
                dist_est = math.hypot(man_ctrl.x - tel.get("x", 0.0), man_ctrl.y - tel.get("y", 0.0))

                w.writerow([
                    round(t_now, 2), round(man_ctrl.x, 2), round(man_ctrl.y, 2), round(man_ctrl.yaw_deg, 1),
                    round(tel.get("x", 0), 2), round(tel.get("y", 0), 2), round(tel.get("alt_agl", 0), 2),
                    round(drone_hdg, 1), tracking_state, round(conf_val, 2), round(dist_est, 2),
                    round(vx, 2), round(vy, 2), round(vz, 2), round(yaw_rate, 1), avoid,
                ])

                # ── Visual Rendering & GUI ─────────────────────────────
                if frame is not None:
                    vis = draw_hud(
                        frame=frame,
                        target=target,
                        tracking_state=tracking_state,
                        man_ctrl=man_ctrl,
                        drone_tel=tel,
                        dist_m=dist_est,
                        avoid_reason=avoid,
                        last_action=last_action_str,
                        hover_mode=drone_hover_mode,
                    )
                    if gui_available:
                        try:
                            cv2.imshow(WINDOW_TITLE, vis)
                        except Exception:
                            gui_available = False

                    if tick % 4 == 0:
                        cv2.imwrite(str(rec_dir / f"frame_{tick:04d}.jpg"), vis)

                tick += 1
                time.sleep(DT)

    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted by Ctrl+C.{RESET}")
    finally:
        logfile.close()
        if gui_available:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        print(f"\n{CYAN}Landing drone safely...{RESET}")
        try:
            backend.land()
        except Exception:
            pass
        backend.close()

    total_ticks = max(1, tick)
    lock_pct = 100.0 * lock_ticks / total_ticks
    print(f"\n{BOLD}{GREEN}{'=' * 76}{RESET}")
    print(f"{BOLD}{GREEN}  🏁 SESSION FINISHED{RESET}")
    print(f"  • Total Duration        : {t_now:.1f} s")
    print(f"  • Subject Distance Moved: {man_ctrl.total_distance_m:.1f} m")
    print(f"  • Tracking Lock Ratio   : {lock_ticks}/{total_ticks} ({lock_pct:.0f}%)")
    print(f"  • Telemetry Log         : {telemetry_file}")
    print(f"{BOLD}{GREEN}{'=' * 76}{RESET}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
