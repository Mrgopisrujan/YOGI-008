#!/usr/bin/env python3
"""GarudaOne DroneOS — Voice + Terminal Flight Controller for CityEnviron.

Unified demo pilot that connects:
  1. Terminal text input (type commands, works headless)
  2. Optional voice input via speech_recognition (if available)
  3. OpenAI GPT for natural-language understanding (via CopilotBrain)
  4. Project AirSim backend for all flight in CityEnviron
  5. Person-following with YOLO detection, identity lock, obstacle avoidance
  6. Frame recording for demo video assembly

Usage::

    # Terminal-only (no mic needed):
    ./venv/bin/python scripts/pas_voice_pilot.py

    # With voice (requires speech_recognition + PyAudio):
    ./venv/bin/python scripts/pas_voice_pilot.py --voice

    # Specify altitude and follow duration:
    ./venv/bin/python scripts/pas_voice_pilot.py --altitude 5 --follow-duration 60

Commands (spoken or typed)::

    take off
    follow that man
    follow that man, close up, from the left
    fly forward 10 meters
    climb 5 meters
    check surroundings
    return home
    land
    quit
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import cv2
import numpy as np

from garuda.brain.copilot_brain import CopilotBrain, is_follow_request
from garuda.flight.avoidance import ObstacleAvoider
from garuda.flight.humanoid_glb import humanoid_bytes
from garuda.flight.pas_client import ProjectAirSimBackend
from garuda.flight.shot_planner import ShotDirector, ShotSpec
from garuda.perception.subject_lock import SubjectLock
from garuda.perception.yolo_detector import YoloDetector

# ── Terminal colours ───────────────────────────────────────────────────
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# ── Follow-loop servo gains for dynamic tracking ──────────────────────
KP_YAW = 28.0
YAW_MAX = 20.0
KP_VY = 1.8
VY_MAX = 1.3
WALK_SPEED = 0.85
TARGET_H_RATIO = 0.28
TARGET_ALT = 2.4
DT = 0.15


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def log(*s) -> None:
    print(*s, flush=True)


# ── Background keyboard / stdin listener ──────────────────────────────
def keyboard_worker(cmd_queue: queue.Queue, stop_event: threading.Event) -> None:
    """Accept typed commands on stdin without blocking the main loop."""
    while not stop_event.is_set():
        try:
            cmd = input(f"\n{BOLD}{CYAN}Garuda ▸ {RESET}").strip()
            if cmd:
                cmd_queue.put(cmd)
        except (EOFError, KeyboardInterrupt):
            stop_event.set()
            cmd_queue.put("quit")
            break


# ── Optional voice listener ───────────────────────────────────────────
def voice_worker(cmd_queue: queue.Queue, stop_event: threading.Event) -> None:
    """Listen for voice commands via Google Speech Recognition."""
    try:
        import speech_recognition as sr
    except ImportError:
        log(f"{YELLOW}[VOICE] speech_recognition not installed — voice disabled{RESET}")
        return

    try:
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 450
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.8
        mic = sr.Microphone()
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.8)
        log(f"{GREEN}[VOICE] Microphone ready (threshold={int(recognizer.energy_threshold)}){RESET}")
    except Exception as e:
        log(f"{YELLOW}[VOICE] Microphone setup failed: {e}{RESET}")
        return

    while not stop_event.is_set():
        try:
            with mic as source:
                audio = recognizer.listen(source, timeout=2.0, phrase_time_limit=7.0)
            try:
                text = recognizer.recognize_google(audio).strip()
                if text:
                    log(f"\n{GREEN}🎙️ [HEARD]: \"{text}\"{RESET}")
                    cmd_queue.put(text)
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                pass
        except Exception:
            time.sleep(0.5)


# ── Scripted command executor ─────────────────────────────────────────
def script_worker(
    commands: list[str],
    cmd_queue: queue.Queue,
    action_done: threading.Event,
    stop_event: threading.Event,
    delay: float = 2.0,
) -> None:
    """Execute a predefined list of commands sequentially with safety pauses."""
    time.sleep(2.0)
    for i, c in enumerate(commands, 1):
        if stop_event.is_set():
            break
        action_done.clear()
        log(f"\n{BOLD}{CYAN}🤖 [AUTO SCRIPT ({i}/{len(commands)})]: \"{c}\"{RESET}")
        cmd_queue.put(c)
        if c.lower().strip() in ("quit", "exit"):
            break
        # Wait until the dispatched action finishes in the main loop
        while not action_done.wait(timeout=0.5):
            if stop_event.is_set():
                return
        time.sleep(delay)

    if not stop_event.is_set():
        time.sleep(1.0)
        cmd_queue.put("quit")


# ── Follow-loop (embedded from pas_follow.py logic) ───────────────────
def run_follow_loop(
    backend: ProjectAirSimBackend,
    spec: ShotSpec,
    det: YoloDetector,
    duration_s: float,
    cmd_queue: queue.Queue,
    stop_event: threading.Event,
    record_dir: Path,
    actor: Optional[str] = None,
    loop_pts: Optional[list] = None,
    target_altitude: float = TARGET_ALT,
) -> dict:
    """Run the person-following servo loop (matching pas_follow.py).

    Maintains strict eye-level altitude (2.4m AGL), proportional lateral strafe,
    heading lock down the avenue (90.0°), target bbox depth masking, and frame recording.
    """
    from garuda.flight.actor_stepper import ActorStepper

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
    stepper = (
        ActorStepper(backend._world, actor, loop_pts, speed_mps=WALK_SPEED)
        if (actor and loop_pts and getattr(backend, "_world", None))
        else None
    )

    # Bootstrap initial visual lock before follow loop timer starts
    log("      bootstrapping initial visual lock...")
    last_target = None
    for _ in range(25):
        f_init = backend.get_forward_camera()
        if f_init is not None:
            d_init = det.detect_persons(f_init, conf=0.10)
            t_init = lock.update(d_init, f_init)
            if t_init is not None:
                last_target = t_init
                log(f"      initial lock acquired (conf={t_init['confidence']:.2f})")
                break
        time.sleep(0.2)

    telemetry_file = record_dir / "follow_telemetry.csv"
    logfile = open(telemetry_file, "w", newline="")
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
    search_sweep_deg = 0.0
    tel = backend.get_telemetry()
    interrupted = False

    while time.time() - t0 < duration_s and not stop_event.is_set():
        # Check for interrupting commands
        try:
            while True:
                nxt = cmd_queue.get_nowait()
                low = nxt.lower().strip()
                if low in ("stop", "halt", "hover", "cancel", "quit", "exit"):
                    interrupted = True
                    log(f"\n{YELLOW}[FOLLOW] Interrupted by '{low}'{RESET}")
                    break
        except queue.Empty:
            pass
        if interrupted:
            break

        now = time.time()
        dt_step = min(0.35, max(0.05, now - last_step_t))
        last_step_t = now

        if stepper:
            stepper.step(dt=dt_step)
        elif actor and loop_pts and hasattr(backend, "step_actor"):
            backend.step_actor(actor, loop_pts, speed_mps=WALK_SPEED, dt=dt_step)

        frame = backend.get_forward_camera()
        if frame is not None:
            detections = det.detect_persons(frame, conf=0.10)
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

            # Strict altitude hold to target_altitude (2.4m AGL)
            alt_err = target_altitude - tel.get("alt_agl", target_altitude)
            vz = clamp(-1.0 * alt_err, -0.6, 0.6)

            # Target standoff regulation: TARGET_H_RATIO = 0.28 (6.0-7.5m standoff)
            vx = clamp(WALK_SPEED + 2.5 * (TARGET_H_RATIO - h_ratio), 0.1, 1.25)

            depth = backend.get_forward_depth()
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
                        vx = 0.0

                # Mask tracked target bbox so avoider doesn't treat the person as an obstacle
                depth_masked = depth.copy()
                mx1, my1 = max(0, int(x1) - 20), max(0, int(y1) - 20)
                mx2, my2 = min(iw, int(x2) + 20), min(ih, int(y2) + 20)
                depth_masked[my1:my2, mx1:mx2] = 25.0
                # Mask bottom 40% of frame to avoid ground/drone reflections
                self_mask_y = int(ih * 0.60)
                depth_masked[self_mask_y:, :] = 25.0
                dec = avoider.evaluate_depth(depth_masked)
            avoid, clear_m = dec.reason, dec.clear_m
            avoid_hits[dec.reason] = avoid_hits.get(dec.reason, 0) + 1
            vx, vy, vz = avoider.apply(vx, vy, vz, dec)

        elif target is not None and target.get("predicted", False):
            # Coasting (brief occlusion): hold course and match walking speed along current heading
            lost_ticks += 1
            lock_ticks += 1
            vx = min(WALK_SPEED * 0.85, 0.72)
            vy = 0.0
            alt_err = target_altitude - tel.get("alt_agl", target_altitude)
            vz = clamp(-1.0 * alt_err, -0.6, 0.6)
            yaw_rate = 0.0
            avoid, clear_m = "COAST", float("nan")
            depth = backend.get_forward_depth()
            if depth is not None:
                d_coast = depth.copy()
                d_coast[int(d_coast.shape[0] * 0.60):, :] = 25.0
                dec = avoider.evaluate_depth(d_coast)
                avoid_hits[dec.reason] = avoid_hits.get(dec.reason, 0) + 1
                vx, vy, vz = avoider.apply(vx, vy, vz, dec)
                clear_m = dec.clear_m

        else:
            # Fully lost: cruise gently forward to reacquire
            lost_ticks += 1
            vx = 0.35
            vy = 0.0
            alt_err = target_altitude - tel.get("alt_agl", target_altitude)
            vz = clamp(-1.0 * alt_err, -0.6, 0.6)
            yaw_rate = 0.0
            avoid, clear_m = "SEARCH", float("nan")
            depth = backend.get_forward_depth()
            if depth is not None:
                d_srch = depth.copy()
                d_srch[int(d_srch.shape[0] * 0.60):, :] = 25.0
                dec = avoider.evaluate_depth(d_srch)
                avoid_hits[dec.reason] = avoid_hits.get(dec.reason, 0) + 1
                vx, vy, vz = avoider.apply(vx, 0.0, vz, dec)
                clear_m = dec.clear_m

        backend.move_velocity_body(
            vx=vx, vy=vy, vz=vz, yaw_rate_dps=yaw_rate, duration_s=DT
        )
        tel = backend.get_telemetry()
        tel["heading"] = backend.heading_deg()
        conf = 0.0 if target is None else float(target["confidence"])
        hr = 0.0 if target is None else float(target["h_ratio"])
        ex = 0.0 if target is None else float(target["err_x"])
        ey = 0.0 if target is None else float(target["err_y"])
        w.writerow(
            [round(now - t0, 2), round(tel.get("x", 0), 2), round(tel.get("y", 0), 2),
             round(tel.get("alt_agl", 0), 2), round(tel.get("heading", float("nan")), 2),
             int(target is not None), tracking_state, round(conf, 3),
             round(hr, 4), round(ex, 3), round(ey, 3), round(vx, 3), round(vy, 3), round(vz, 3),
             round(yaw_rate, 1), avoid, round(clear_m, 2), switches]
        )

        # Save annotated frames for the demo video
        if frame is not None:
            vis = frame.copy()
            if target is not None:
                x1, y1, x2, y2 = target["bbox"]
                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.line(vis, (x1, y1), (x2, y2), (0, 255, 0), 1)
                cv2.line(vis, (x1, y2), (x2, y1), (0, 255, 0), 1)
                label = ("LOCK PREDICTED" if tracking_state == "LOCKED_PREDICTED"
                         else f"LOCK {conf:.2f}")
                cv2.putText(vis, label, (x1, max(12, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            else:
                cv2.putText(vis, "SEARCH", (8, 24), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (0, 200, 255), 2)
            cv2.putText(
                vis,
                f"t={now - t0:.1f}s alt={tel.get('alt_agl', 0):.1f}m {avoid[:18]}",
                (8, vis.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (255, 255, 255), 1,
            )
            if tick % 2 == 0:
                cv2.imwrite(str(record_dir / f"f_{tick:04d}.jpg"), vis,
                            [cv2.IMWRITE_JPEG_QUALITY, 88])

            eagle_frame = backend.get_eagle_camera()
            if eagle_frame is not None and tick % 2 == 0:
                evis = eagle_frame.copy()
                eh, ew = evis.shape[:2]
                cv2.rectangle(evis, (0, 0), (ew, 28), (15, 15, 15), -1)
                cv2.line(evis, (0, 28), (ew, 28), (0, 200, 255), 1)
                cv2.putText(
                    evis,
                    "GARUDA DRONE-OS  |  EAGLE EYE OVERHEAD VIEW  |  VOICE PILOT DEMO",
                    (12, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1, cv2.LINE_AA,
                )
                ratio_pct = int(100.0 * lock_ticks / max(tick, 1))
                ehud = (
                    f"T:{now - t0:.1f}s | ALT:{tel.get('alt_agl', 0):.1f}m | "
                    f"HDG:{tel.get('heading', 0):.0f}deg | "
                    f"LOCK:{ratio_pct}% | SWITCH:{switches} | AVOID:{avoid[:14]}"
                )
                cv2.putText(
                    evis, ehud, (10, eh - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA,
                )
                cv2.imwrite(str(record_dir / f"eagle_{tick:04d}.jpg"), evis,
                            [cv2.IMWRITE_JPEG_QUALITY, 88])

        if tick % 8 == 0:
            log(f"  t={now - t0:5.1f}s {tracking_state:16s} "
                f"conf={conf:.2f} h={hr:.3f} err=({ex:+.2f},{ey:+.2f}) "
                f"v=({vx:+.1f},{vz:+.1f}) yaw={yaw_rate:+5.1f} "
                f"alt={tel.get('alt_agl', 0):4.1f} {avoid[:20]:20} d={clear_m}")
        tick += 1
        time.sleep(DT)

    logfile.close()
    return {
        "ticks": tick,
        "lock_ticks": lock_ticks,
        "switches": switches,
        "errs": errs,
        "avoid_hits": avoid_hits,
        "interrupted": interrupted,
        "telemetry_file": telemetry_file,
    }


# ── Flight action dispatch ────────────────────────────────────────────
def move_direction(
    backend: ProjectAirSimBackend,
    direction: str,
    distance_m: float = 5.0,
    speed_mps: float = 2.5,
) -> None:
    """Move the drone a fixed distance in a body-frame direction."""
    dur = max(0.5, distance_m / speed_mps)
    vel_map = {
        "FORWARD": (speed_mps, 0.0, 0.0),
        "BACKWARD": (-speed_mps, 0.0, 0.0),
        "LEFT": (0.0, -speed_mps, 0.0),
        "RIGHT": (0.0, speed_mps, 0.0),
    }
    vx, vy, vz = vel_map.get(direction.upper(), (0.0, 0.0, 0.0))
    steps = int(dur / DT) or 1
    for _ in range(steps):
        backend.move_velocity_body(vx=vx, vy=vy, vz=0.0, yaw_rate_dps=0.0, duration_s=DT)
        time.sleep(DT)
    backend.hover()


def climb_descend(
    backend: ProjectAirSimBackend,
    delta_m: float,
) -> None:
    """Climb (+) or descend (-) by delta_m metres."""
    rate = 1.5
    dur = max(0.5, abs(delta_m) / rate)
    # NED convention: positive vz = descend
    vz = rate if delta_m < 0 else -rate
    # Update the target altitude for the altitude-hold loop
    current = backend.altitude_agl()
    backend.set_target_altitude(current + delta_m)
    steps = int(dur / DT) or 1
    for _ in range(steps):
        backend.move_velocity_body(vx=0.0, vy=0.0, vz=vz, yaw_rate_dps=0.0, duration_s=DT)
        time.sleep(DT)
    backend.hover()


# ── Banner ─────────────────────────────────────────────────────────────
def print_banner(has_openai: bool, has_voice: bool) -> None:
    log(f"\n{BOLD}{CYAN}{'=' * 68}{RESET}")
    log(f"{BOLD}{CYAN}  🦅 GARUDAONE DRONEOS — CityEnviron Voice + Terminal Pilot{RESET}")
    log(f"{BOLD}{CYAN}{'=' * 68}{RESET}")
    log(f"  AI Copilot   : {GREEN + 'OpenAI GPT ACTIVE' + RESET if has_openai else YELLOW + 'Offline keyword parser' + RESET}")
    log(f"  Voice Input  : {GREEN + 'LISTENING' + RESET if has_voice else DIM + 'Terminal only (--voice to enable)' + RESET}")
    log(f"  Simulator    : Project AirSim / CityEnviron")
    log(f"{BOLD}{CYAN}{'-' * 68}{RESET}")
    log("  Commands you can type or say:")
    log("    take off                     — launch to 3m AGL")
    log("    follow that man              — YOLO lock + servo follow")
    log("    follow him, close up         — tight cinematic follow")
    log("    orbit him                    — circle the subject")
    log("    fly forward 10 meters        — translate forward")
    log("    climb 5 meters               — gain altitude")
    log("    check surroundings           — depth scan report")
    log("    return home / land           — RTL or direct land")
    log("    stop / hover                 — hold position")
    log("    quit                         — exit")
    log(f"{BOLD}{CYAN}{'=' * 68}{RESET}\n")


# ── Main ───────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Voice + terminal pilot for CityEnviron")
    ap.add_argument("--altitude", type=float, default=2.4, help="takeoff altitude (m)")
    ap.add_argument("--follow-duration", type=float, default=45.0, help="follow loop max seconds")
    ap.add_argument("--voice", action="store_true", help="enable microphone listening")
    ap.add_argument("--record", default="voice_demo", help="recording session name")
    ap.add_argument("--conf", type=float, default=0.15, help="YOLO detection confidence")
    ap.add_argument("--commands", nargs="+", default=None, help="Automated sequence of flight commands")
    ap.add_argument("--command-delay", type=float, default=2.0, help="delay between automated commands")
    args = ap.parse_args()

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    has_openai = bool(openai_key)

    brain = CopilotBrain(openai_api_key=openai_key)
    cmd_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()
    action_done = threading.Event()

    print_banner(has_openai, args.voice)

    # ── Connect to Project AirSim ──────────────────────────────────────
    log(f"{CYAN}[1/4] Connecting to Project AirSim / CityEnviron...{RESET}")
    backend = ProjectAirSimBackend()
    if not backend.connect():
        log(f"{RED}[FAIL] Cannot connect — is CityEnviron running?{RESET}")
        return 1
    log(f"{GREEN}[OK] Connected: scene={backend.scene} drone={backend.drone_name}{RESET}")
    backend.cycle_view(4)

    # ── Spawn the humanoid subject ─────────────────────────────────────
    # Walker1 starts on the main road in front of the drone.
    # Drone starts on the avenue at (6.5, 8.0) heading 90° (+Y).
    # Main road avenue extends to the left (+X from 6.5 up to 16.0).
    # Buildings are on the right (-X <= 5.5).
    spawn = (7.0, 14.0)
    actor = backend.spawn_glb("Walker1", humanoid_bytes(), (spawn[0], spawn[1], 0.0), scale=(1.25, 1.25, 1.25))
    loop_pts = None
    if actor:
        log(f"{GREEN}[OK] Spawned walking subject on main road: {actor}{RESET}")
        # Main road walking route -> Weaves across road lanes to the left -> Crosses intersection -> Turns into other street
        loop_pts = [
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

    else:
        log(f"{YELLOW}[WARN] Could not spawn humanoid — follow will need an existing person{RESET}")

    # ── Prepare detector ───────────────────────────────────────────────
    det = YoloDetector()
    if not det.is_ready():
        log(f"{YELLOW}[WARN] YOLO detector unavailable — follow commands will be refused{RESET}")

    # ── Prepare recording directory ────────────────────────────────────
    record_dir = Path("logs/rec") / args.record
    record_dir.mkdir(parents=True, exist_ok=True)

    # ── Start input threads ────────────────────────────────────────────
    if args.commands:
        log(f"{GREEN}[2/4] Starting automated script runner ({len(args.commands)} commands)...{RESET}")
        threading.Thread(
            target=script_worker,
            args=(args.commands, cmd_queue, action_done, stop_event, args.command_delay),
            daemon=True,
        ).start()
    else:
        threading.Thread(target=keyboard_worker, args=(cmd_queue, stop_event), daemon=True).start()

    if args.voice:
        threading.Thread(target=voice_worker, args=(cmd_queue, stop_event), daemon=True).start()

    log(f"{GREEN}[2/4] Input threads active. Type or speak your commands.{RESET}")

    # ── Main command loop ──────────────────────────────────────────────
    in_air = False
    while not stop_event.is_set():
        try:
            cmd = cmd_queue.get(timeout=0.3)
        except queue.Empty:
            continue

        if not cmd:
            continue

        low = cmd.lower().strip()
        if low in ("quit", "exit"):
            log(f"\n{CYAN}Exiting Garuda Pilot.{RESET}")
            stop_event.set()
            action_done.set()
            break

        # ── Interpret command via CopilotBrain ─────────────────────────
        decision = brain.understand_command(cmd)
        action = decision.get("action", "UNKNOWN")
        log(f"\n{BOLD}👉 Action: {YELLOW}{action}{RESET}")

        # ── Safety interlock ───────────────────────────────────────────
        AIR_RESTRICTED = {
            "MOVE_FORWARD", "MOVE_BACKWARD", "MOVE_LEFT", "MOVE_RIGHT",
            "TURN_AND_MOVE", "ROTATE", "CLIMB", "DESCEND",
            "HOVER", "STOP", "RTL", "FOLLOW_PERSON",
            "CHECK_SURROUNDINGS",
        }
        if action in AIR_RESTRICTED and not in_air:
            log(f"{RED}⚠️  Drone is on the ground. Please command 'takeoff' first.{RESET}")
            brain.speak("Drone is on the ground. Please command takeoff first.")
            action_done.set()
            continue

        # ── Dispatch ───────────────────────────────────────────────────
        if action == "TAKEOFF":
            if in_air:
                log(f"{YELLOW}Already airborne at {backend.altitude_agl():.1f}m{RESET}")
                action_done.set()
                continue
            alt = decision.get("altitude_m", args.altitude)
            log(f"{CYAN}Taking off to {alt:.1f}m...{RESET}")
            brain.speak(f"Taking off to {alt:.0f} meters.")
            ok = backend.takeoff(altitude_m=alt)
            if ok:
                in_air = True
                # Wait for camera frames to start arriving.
                for _ in range(20):
                    if backend.get_forward_camera() is not None:
                        break
                    time.sleep(0.5)
                # Turn 90° to face the subject: drone spawns at (-1,8),
                # Walker1 at (-1,15) is 7m along +Y = heading 90°.
                log(f"  Turning to heading 90° to face Walker1")
                backend.rotate_to_heading(90.0)
                time.sleep(1.0)
                log(f"{GREEN}✅ Airborne at {backend.altitude_agl():.1f}m AGL{RESET}")
                brain.speak("Takeoff complete. Ready for commands.")
            else:
                log(f"{RED}Takeoff failed{RESET}")

        elif action == "LAND":
            if not in_air:
                log(f"{YELLOW}Already on the ground.{RESET}")
                continue
            log(f"{CYAN}Landing...{RESET}")
            brain.speak("Landing.")
            backend.land()
            in_air = False
            log(f"{GREEN}✅ Landed.{RESET}")

        elif action in ("HOVER", "STOP"):
            log(f"{CYAN}Holding position.{RESET}")
            brain.speak("Holding position.")
            backend.hover()

        elif action == "RTL":
            log(f"{CYAN}Returning to launch...{RESET}")
            brain.speak("Returning to launch.")
            backend.land()
            in_air = False
            log(f"{GREEN}✅ Landed at home.{RESET}")

        elif action == "FOLLOW_PERSON":
            if not det.is_ready():
                log(f"{RED}❌ YOLO detector unavailable — cannot follow.{RESET}")
                brain.speak("Vision system unavailable. Cannot follow.")
                action_done.set()
                continue

            spoken = decision.get("command") or cmd
            spec = decision.get("shot_spec")
            if spec is None:
                spec = ShotDirector().parse(spoken)
            dur_spoken = None
            if any(w in spoken.lower() for w in ("second", "sec", "minute", "min", "for ")):
                dur_spoken = decision.get("duration_s")
            duration = float(dur_spoken or args.follow_duration)

            log(f"\n{BOLD}{GREEN}🚶 [FOLLOW] Shot: {spec.describe()}{RESET}")
            log(f"   Command: \"{spoken}\"  Duration: {duration:.0f}s")
            brain.speak("Acquiring target. Following.")

            # Run the follow loop (blocking — interrupts via cmd_queue).
            follow_dir = record_dir / "follow"
            follow_dir.mkdir(parents=True, exist_ok=True)
            # Target altitude held strictly at eye-level (2.4m AGL)
            target_alt = 2.4
            stats = run_follow_loop(
                backend=backend,
                spec=spec,
                det=det,
                duration_s=duration,
                cmd_queue=cmd_queue,
                stop_event=stop_event,
                record_dir=follow_dir,
                actor=actor,
                loop_pts=loop_pts,
                target_altitude=target_alt,
            )

            total = stats["ticks"]
            locked = stats["lock_ticks"]
            ratio = 100.0 * locked / max(total, 1)
            log(f"\n{GREEN}✅ Follow done: {total} ticks, locked {locked} ({ratio:.0f}%), "
                f"switches={stats['switches']}{RESET}")
            if stats["errs"]:
                log(f"   mean |err_x|: {sum(stats['errs']) / len(stats['errs']):.3f}")
            log(f"   avoidance: {stats['avoid_hits']}")
            log(f"   telemetry → {stats['telemetry_file']}")
            brain.speak("Shot complete. Holding position.")

        elif action == "MOVE_FORWARD":
            dist = decision.get("distance_m", 5.0)
            log(f"{CYAN}Moving forward {dist:.1f}m...{RESET}")
            brain.speak(f"Moving forward {dist:.0f} meters.")
            move_direction(backend, "FORWARD", distance_m=dist)
            log(f"{GREEN}✅ Forward move complete.{RESET}")

        elif action == "MOVE_BACKWARD":
            dist = decision.get("distance_m", 5.0)
            log(f"{CYAN}Moving backward {dist:.1f}m...{RESET}")
            brain.speak(f"Moving backward {dist:.0f} meters.")
            move_direction(backend, "BACKWARD", distance_m=dist)
            log(f"{GREEN}✅ Backward move complete.{RESET}")

        elif action == "MOVE_LEFT":
            dist = decision.get("distance_m", 5.0)
            log(f"{CYAN}Translating left {dist:.1f}m...{RESET}")
            brain.speak(f"Translating left {dist:.0f} meters.")
            move_direction(backend, "LEFT", distance_m=dist)
            log(f"{GREEN}✅ Left translation complete.{RESET}")

        elif action == "MOVE_RIGHT":
            dist = decision.get("distance_m", 5.0)
            log(f"{CYAN}Translating right {dist:.1f}m...{RESET}")
            brain.speak(f"Translating right {dist:.0f} meters.")
            move_direction(backend, "RIGHT", distance_m=dist)
            log(f"{GREEN}✅ Right translation complete.{RESET}")

        elif action == "CLIMB":
            gain = decision.get("altitude_gain_m", 5.0)
            log(f"{CYAN}Climbing {gain:.1f}m...{RESET}")
            brain.speak(f"Climbing {gain:.0f} meters.")
            climb_descend(backend, gain)
            log(f"{GREEN}✅ Climb complete. Alt={backend.altitude_agl():.1f}m{RESET}")

        elif action == "DESCEND":
            drop = decision.get("altitude_drop_m", 3.0)
            log(f"{CYAN}Descending {drop:.1f}m...{RESET}")
            brain.speak(f"Descending {drop:.0f} meters.")
            climb_descend(backend, -drop)
            log(f"{GREEN}✅ Descent complete. Alt={backend.altitude_agl():.1f}m{RESET}")

        elif action == "ROTATE":
            angle = decision.get("yaw_change_deg", 45.0)
            current = backend.heading_deg()
            target = (current + angle) % 360.0
            dir_str = "left" if angle < 0 else "right"
            log(f"{CYAN}Rotating {dir_str} {abs(angle):.0f}°...{RESET}")
            brain.speak(f"Rotating {dir_str} {abs(angle):.0f} degrees.")
            backend.rotate_to_heading(target)
            log(f"{GREEN}✅ Now heading {backend.heading_deg():.0f}°{RESET}")

        elif action == "CHECK_SURROUNDINGS":
            log(f"{CYAN}📡 Scanning forward depth...{RESET}")
            brain.speak("Scanning surroundings.")
            depth = backend.get_forward_depth()
            if depth is not None:
                avoider = ObstacleAvoider()
                dec = avoider.evaluate_depth(depth)
                log(f"   Forward clearance: {dec.clear_m:.1f}m")
                log(f"   Left: {dec.left_m:.1f}m  Right: {dec.right_m:.1f}m")
                log(f"   Status: {dec.status}")
                if dec.status == "CLEAR":
                    brain.speak(f"Path ahead is clear for {dec.clear_m:.0f} meters.")
                else:
                    brain.speak(f"Obstacle detected {dec.clear_m:.1f} meters ahead.")
            else:
                log(f"{YELLOW}   No depth data available.{RESET}")
                brain.speak("Depth camera not available.")

        elif action == "RESET":
            log(f"{CYAN}Resetting drone...{RESET}")
            brain.speak("Resetting drone.")
            backend.close()
            time.sleep(2.0)
            backend.connect()
            in_air = False
            log(f"{GREEN}✅ Reset complete.{RESET}")

        elif action == "TURN_AND_MOVE":
            angle = decision.get("yaw_change_deg", 0.0)
            dist = decision.get("distance_m", 5.0)
            dir_str = "left" if angle < 0 else "right"
            log(f"{CYAN}Turning {dir_str} {abs(angle):.0f}° then moving {dist:.1f}m...{RESET}")
            brain.speak(f"Turning {dir_str} {abs(angle):.0f} degrees and moving {dist:.0f} meters.")
            current = backend.heading_deg()
            backend.rotate_to_heading((current + angle) % 360.0)
            move_direction(backend, "FORWARD", distance_m=dist)
            log(f"{GREEN}✅ Turn-and-move complete.{RESET}")

        elif action == "INSPECT_ROOFTOP":
            alt = min(decision.get("altitude_m", 25.0), 45.0)
            log(f"{CYAN}Climbing to {alt:.0f}m for rooftop view...{RESET}")
            brain.speak(f"Climbing to {alt:.0f} meters for inspection.")
            gain = alt - backend.altitude_agl()
            if gain > 0.5:
                climb_descend(backend, gain)
            log(f"{GREEN}✅ At {backend.altitude_agl():.1f}m{RESET}")

        elif action == "INSPECT_GROUND":
            log(f"{CYAN}Capturing downward view...{RESET}")
            brain.speak("Looking down.")
            img = backend.get_downward_camera()
            if img is not None:
                path = record_dir / "ground_view.jpg"
                cv2.imwrite(str(path), img)
                log(f"{GREEN}✅ Ground frame saved: {path}{RESET}")
            else:
                log(f"{YELLOW}Downward camera not available.{RESET}")

        else:
            log(f"{YELLOW}⚠️ Unrecognized: '{cmd}'. Try 'follow that man', 'forward 10m', 'land'.{RESET}")
            brain.speak("Command not recognized.")

        action_done.set()

    # ── Cleanup ────────────────────────────────────────────────────────
    log(f"\n{CYAN}[4/4] Shutting down...{RESET}")
    try:
        if in_air:
            backend.land()
    except Exception:
        pass
    backend.close()
    log(f"{GREEN}✅ Garuda pilot stopped.{RESET}")

    # Check if frames were recorded and assemble video
    target_dir = (record_dir / "follow") if (record_dir / "follow").exists() and list((record_dir / "follow").glob("f_*.jpg")) else record_dir
    frame_files = list(target_dir.glob("f_*.jpg"))
    if frame_files:
        session_arg = f"{args.record}/follow" if target_dir != record_dir else args.record
        log(f"\n{CYAN}🎬 Compiling session video for '{session_arg}' ({len(frame_files)} frames)...{RESET}")
        try:
            import subprocess
            subprocess.run(
                [sys.executable, "scripts/make_demo_video.py", "--session", session_arg, "--fps", "10"],
                check=False,
            )
        except Exception as e:
            log(f"{YELLOW}Video compilation skipped: {e}{RESET}")

    return 0


if __name__ == "__main__":
    ret = main()
    os._exit(ret if isinstance(ret, int) else 0)
