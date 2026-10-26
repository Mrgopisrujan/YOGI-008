#!/usr/bin/env python3
"""
GarudaOS — Live Unreal Engine 5.7.4 & AirSim Voice Pilot
========================================================
Interactive mission controller connecting:
  1. Unreal Engine 5.7.4 AirSim simulation (RPC :41451).
  2. Dual onboard cameras (Camera 1: Front, Camera 2: Belly).
  3. Eagle-Eye 3rd-person observer chase view.
  4. OpenAI GPT-4o decision engine + Smallest.ai Speech synthesis.
"""

from __future__ import annotations

import os
import sys
import time
import logging
import math
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import queue
import threading
try:
    import speech_recognition as sr
except ImportError:
    sr = None

from dotenv import load_dotenv
load_dotenv()

from garuda.flight.airsim_client import AirSimClient, AIRSIM_AVAILABLE
from garuda.brain.copilot_brain import CopilotBrain

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("UnrealPilot")


def print_banner(has_openai: bool, has_smallest: bool, has_mic: bool):
    print("\n" + "=" * 68)
    print("      🦅 GARUDA OS — LIVE VOICE & UNREAL ENGINE 5.7.4 COPILOT       ")
    print("=" * 68)
    print(" [1] Camera 1 (Front)      : Subject tracking, framing & obstacle depth")
    print(" [2] Camera 2 (Downward)   : Optical flow & ground landing view")
    print(" [3] Observer View         : Eagle-Eye 3rd-person chase camera")
    mic_status = "ACTIVE (Speak into your microphone anytime)" if has_mic else "OFFLINE (Keyboard mode)"
    ai_status = "GPT-4o ACTIVE (Natural Language enabled)" if has_openai else "Local NLP Fast Parser"
    tts_status = "Smallest.ai Lightning TTS" if has_smallest else "Native Windows Audio"
    print(f" [4] Microphone Input      : {mic_status}")
    print(f" [5] AI Copilot NLU        : {ai_status}")
    print(f" [6] Voice Synthesis       : {tts_status}")
    print("=" * 68)
    print(" Speak naturally into your mic OR type in console:")
    print("   * 'Take off and hover at three meters'")
    print("   * 'Hey Garuda, follow that man'")
    print("   * 'Follow that man, close up, from the left'")
    print("   * 'Orbit him for 30 seconds'")
    print("   * 'Fly forward 25 meters down the road'")
    print("   * 'Climb high above that rooftop'")
    print("   * 'Check your surroundings and scan for obstacles'")
    print("   * 'Return to launch and land'")
    print("   * 'quit' / 'reset'")
    print(" " + "=" * 68 + "\n")


def mic_listener_worker(cmd_queue: queue.Queue, stop_event: threading.Event):
    """Continuously listens to microphone and transcribes spoken flight commands."""
    if sr is None:
        return

    try:
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 450
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.8
        mic = sr.Microphone()
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.8)
    except Exception as e:
        log.warning(f"[MIC] Microphone setup notice: {e}")
        return

    while not stop_event.is_set():
        try:
            with mic as source:
                audio = recognizer.listen(source, timeout=2.0, phrase_time_limit=7.0)
            try:
                text = recognizer.recognize_google(audio).strip()
                if text:
                    print(f"\n🎙️ [MICROPHONE HEARD]: \"{text}\"")
                    cmd_queue.put(text)
            except sr.UnknownValueError:
                pass
            except sr.RequestError as e:
                log.debug(f"Speech recognition network notice: {e}")
        except sr.WaitTimeoutError:
            continue
        except Exception:
            time.sleep(0.5)


def keyboard_worker(cmd_queue: queue.Queue, stop_event: threading.Event):
    """Accepts console input without blocking the voice listener."""
    while not stop_event.is_set():
        try:
            cmd = input("Garuda-Command > ").strip()
            if cmd:
                cmd_queue.put(cmd)
        except (EOFError, KeyboardInterrupt):
            stop_event.set()
            cmd_queue.put("quit")
            break


def main():
    # Load keys
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    smallest_key = os.environ.get("SMALLEST_API_KEY", "")
    has_mic = sr is not None

    print_banner(bool(openai_key), bool(smallest_key), has_mic)

    brain = CopilotBrain(openai_api_key=openai_key, smallest_api_key=smallest_key)
    airsim = AirSimClient()

    print("[1/3] Connecting to Unreal Engine 5...")
    if not airsim.connect(timeout=5.0):
        print("\n⚠️  [Notice] Unreal Engine is not yet streaming on port 41451.")
        print("   Make sure your Unreal project is open and you clicked 'Play'.")
        print("   Running in Virtual Copilot / Demonstration Mode.\n")
    else:
        print("✅ Connected to Unreal Engine 5.7.4!")
        airsim.set_eagle_eye_camera(distance=3.5, height=2.0)
        brain.speak("Garuda OS connected to Unreal Engine. Ready for flight.")

    cmd_queue = queue.Queue()
    stop_event = threading.Event()

    # Launch background microphone listener
    mic_thread = threading.Thread(target=mic_listener_worker, args=(cmd_queue, stop_event), daemon=True)
    mic_thread.start()

    # Launch keyboard thread
    kb_thread = threading.Thread(target=keyboard_worker, args=(cmd_queue, stop_event), daemon=True)
    kb_thread.start()

    while not stop_event.is_set():
        try:
            try:
                cmd = cmd_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if not cmd:
                continue
            if cmd.lower() in ["quit", "exit"]:
                print("Exiting Garuda Pilot.")
                stop_event.set()
                break

            decision = brain.understand_command(cmd)
            action = decision.get("action", "UNKNOWN")
            print(f"👉 Action Decided: {action}")

            # Pre-Flight Safety Verification: Block in-flight commands when drone is still on the ground
            AIRBORNE_ACTIONS = [
                "MOVE_FORWARD", "MOVE_BACKWARD", "MOVE_LEFT", "MOVE_RIGHT",
                "TURN_AND_MOVE", "ROTATE", "CLIMB", "DESCEND", "INSPECT_ROOFTOP",
                "RTL", "HOVER", "STOP"
            ]
            if action in AIRBORNE_ACTIONS:
                if not airsim.is_in_air():
                    print("\n⚠️ [PRE-FLIGHT SAFETY] Drone is currently on the ground! Please command 'takeoff' first.\n")
                    brain.speak("Drone is on the ground. Please command takeoff first.")
                    continue

            if action == "TAKEOFF":
                if airsim.is_in_air():
                    telem = airsim.get_telemetry()
                    alt = telem.get("alt_agl", 3.0)
                    print(f"\n⚠️ [TAKEOFF REJECTED] Drone is already airborne at {alt:.1f}m altitude!\n")
                    brain.speak(f"Drone is already airborne at {alt:.1f} meters. Holding position.")
                    continue
                alt = decision.get("altitude_m", 3.0)
                brain.speak(f"Taking off to {alt} meters.")
                airsim.takeoff(altitude_m=alt)

            elif action == "MOVE_FORWARD":
                dist = decision.get("distance_m", 5.0)
                brain.speak(f"Moving forward {dist} meters with collision guard.")
                res = airsim.move_direction("FORWARD", distance_m=dist, speed_mps=3.5, collision_guard=True)
                if res.get("status") == "OBSTACLE_AVOIDED":
                    obs_m = res.get("distance_m", 0.0)
                    print(f"\n🛑 [COLLISION GUARD ACTIVATED] Obstacle detected {obs_m:.2f}m ahead! Auto-braked to hover.")
                    brain.speak(f"Obstacle detected {obs_m:.1f} meters ahead. Auto-braking to hover.")
                elif res.get("status") == "OBSTACLE_DETECTED":
                    obs_m = res.get("distance_m", 0.0)
                    print(f"\n⚠️ Cannot move forward: Obstacle right in path at {obs_m:.2f}m.")
                    brain.speak("Obstacle directly ahead. Flight path blocked.")

            elif action == "CHECK_SURROUNDINGS":
                print("\n📡 Scanning surroundings with onboard depth camera & radar...")
                brain.speak("Scanning surroundings.")
                radar = airsim.check_surroundings()
                f_dist = radar["forward_obstacle_m"]
                clear_str = "CLEAR ✅" if radar["clear_ahead"] else "OBSTACLE NEARBY ⚠️"
                print(f"   - Forward Obstacle Distance: {f_dist}m ({clear_str})")
                print(f"   - Current Altitude: {radar['altitude_m']}m")
                print(f"   - Collision Flag: {radar['has_collided']}\n")
                if radar["clear_ahead"]:
                    brain.speak(f"Surroundings scanned. Path ahead is clear for {f_dist} meters.")
                else:
                    brain.speak(f"Caution: Obstacle detected {f_dist} meters ahead.")

            elif action == "RESET":
                print("\n🔄 Respawning drone on launchpad...")
                brain.speak("Resetting drone to launchpad.")
                airsim.reset_to_home()
                print("✅ Drone reset upright on launchpad. Ready for takeoff.\n")

            elif action == "RTL":
                if not airsim.is_in_air():
                    print("\n⚠️ [RTL REJECTED] Drone is already on the launchpad.\n")
                    brain.speak("Drone is already on the launchpad.")
                    continue
                telem = airsim.get_telemetry()
                dist_to_pad = math.hypot(telem.get("x", 0.0), telem.get("y", 0.0))
                if dist_to_pad < 1.2:
                    print(f"\n🏠 Drone is already directly over launchpad ({dist_to_pad:.2f}m error). Landing directly...")
                    brain.speak("Already above launchpad. Descending for landing.")
                    airsim.land()
                    continue
                print("\n🏠 Initiating Return to Launch (RTL)...")
                brain.speak("Returning to launch coordinates. Ascending to 16 meters clearance altitude.")
                success = airsim.return_to_launch(safe_altitude_m=16.0)
                if success:
                    print("✅ Successfully returned to launchpad and landed.\n")
                    brain.speak("Touchdown confirmed at launchpad. Motors disarmed.")
                else:
                    print("⚠️ RTL descent warning: Touchdown not verified on pad.\n")
                    brain.speak("Return to launch incomplete. Please check telemetry.")

            elif action == "MOVE_BACKWARD":
                dist = decision.get("distance_m", 5.0)
                brain.speak(f"Moving backward {dist} meters.")
                res = airsim.move_direction("BACKWARD", distance_m=dist, speed_mps=3.0)
                if res.get("status") == "OBSTACLE_AVOIDED":
                    print("\n🛑 [OBSTACLE GUARD] Spatial barrier encountered while moving backward. Auto-braked.")
                    brain.speak("Obstacle detected behind. Holding position.")

            elif action == "MOVE_LEFT":
                dist = decision.get("distance_m", 5.0)
                brain.speak(f"Translating left {dist} meters.")
                res = airsim.move_direction("LEFT", distance_m=dist, speed_mps=3.0)
                if res.get("status") == "OBSTACLE_AVOIDED":
                    print("\n🛑 [OBSTACLE GUARD] Spatial barrier encountered while moving left. Auto-braked.")
                    brain.speak("Obstacle detected on left. Holding position.")

            elif action == "MOVE_RIGHT":
                dist = decision.get("distance_m", 5.0)
                brain.speak(f"Translating right {dist} meters.")
                res = airsim.move_direction("RIGHT", distance_m=dist, speed_mps=3.0)
                if res.get("status") == "OBSTACLE_AVOIDED":
                    print("\n🛑 [OBSTACLE GUARD] Spatial barrier encountered while moving right. Auto-braked.")
                    brain.speak("Obstacle detected on right. Holding position.")

            elif action == "TURN_AND_MOVE":
                angle = decision.get("yaw_change_deg", 0.0)
                dist = decision.get("distance_m", 5.0)
                dir_str = "left" if angle < 0 else "right"
                brain.speak(f"Turning {dir_str} {abs(angle):.0f} degrees and advancing {dist:.1f} meters.")
                res = airsim.turn_and_move(yaw_change_deg=angle, distance_m=dist, speed_mps=3.0)
                if res.get("status") == "OBSTACLE_AVOIDED":
                    obs_m = res.get("distance_m", 0.0)
                    print(f"\n🛑 [SPATIAL SENTRY] Obstacle detected {obs_m:.1f}m ahead along trajectory! Auto-braked to hover.")
                    brain.speak(f"Obstacle detected {obs_m:.1f} meters ahead. Auto-braking to hover.")

            elif action == "ROTATE":
                angle = decision.get("yaw_change_deg", 45.0)
                dir_str = "left" if angle < 0 else "right"
                brain.speak(f"Rotating {dir_str} {abs(angle):.0f} degrees.")
                airsim.rotate_yaw(yaw_change_deg=angle)

            elif action == "HOVER" or action == "STOP":
                brain.speak("Holding position and hovering.")
                airsim.move_velocity(vx=0.0, vy=0.0, vz=0.0, yaw_rate=0.0, duration_s=0.1)

            elif action == "FOLLOW_PERSON":
                # Cinematic subject follow: identity lock + shot framing +
                # obstacle veto + video recording, all in one closed loop.
                spoken = decision.get("command") or cmd
                spec = decision.get("shot_spec")
                duration = float(decision.get("duration_s", 20.0))
                want_record = bool(decision.get("record", True))

                print(f"\n🚶 [TARGET LOCK] Acquiring visual lock — shot: {decision.get('shot', 'follow')}")
                print(f"   Command heard: \"{spoken}\"")
                brain.speak("Acquiring target. Following.")

                ctrl = airsim.make_follow_controller(
                    command=spoken,
                    shot=spec,
                    on_event=lambda m: print(f"   {m}"),
                )
                if getattr(ctrl, "detector", None) is None:
                    print("❌ [SAFETY] YOLO detector unavailable — refusing to fly an unguided follow shot.")
                    brain.speak("Vision system unavailable. I cannot safely follow a person.")
                    continue

                ctrl.begin(
                    command=spoken,
                    spec=ctrl.spec,
                    duration_s=duration,
                    record=want_record,
                )
                print(f"   Shot: {ctrl.spec.describe()}")
                print(f"   Recording: {'ON' if want_record else 'OFF'}  |  stopping early: say 'stop'\n")

                t0 = time.time()
                interrupted = False
                while ctrl.active and time.time() - t0 < duration:
                    # Drain any speech that arrived mid-shot.
                    try:
                        while True:
                            nxt = cmd_queue.get_nowait()
                            if nxt.lower().strip() in ("stop", "halt", "hover", "cancel", "quit", "exit"):
                                interrupted = True
                            elif nxt.lower().strip():
                                print(f"   ⏸ mid-shot command queued: \"{nxt}\"")
                    except queue.Empty:
                        pass
                    if interrupted:
                        break

                    tel = ctrl.tick()
                    # Live HUD line.
                    if tel.locked:
                        hud = (
                            f"   [{tel.elapsed_s:5.1f}s] LOCK {tel.conf*100:3.0f}%  "
                            f"err=({tel.err_x:+.2f},{tel.err_y:+.2f})  "
                            f"v=({tel.vx:+.1f},{tel.vy:+.1f},{tel.vz:+.1f})  "
                            f"yaw={tel.yaw_rate:+.0f}  avoid={tel.avoidance}   "
                        )
                        print(chr(13) + hud, end="", flush=True)
                    time.sleep(0.05)
                print()

                stats = ctrl.end("interrupted by operator" if interrupted else "duration elapsed")
                if not interrupted and tel.lock_ratio < 0.2:
                    print(f"⚠️  Target never acquired (lock ratio {tel.lock_ratio*100:.0f}%). "
                          "Is anyone visible in the front camera?")
                    brain.speak("I could not see anyone. Adjusting position.")
                else:
                    print(f"✅ Shot complete: {stats.frames} frames / {stats.seconds}s, "
                          f"lock {stats.lock_ratio*100:.0f}%, {stats.avoid_events} avoidance events")
                    if stats.path:
                        print(f"🎬 Saved: {stats.path}")
                    brain.speak("Shot complete. Holding position.")
                if interrupted:
                    stop_event.set()
                    break

            elif action == "LAND":
                if not airsim.is_in_air():
                    print("\n⚠️ [LAND REJECTED] Drone is already safely landed on the ground.\n")
                    brain.speak("Drone is already safely landed on the ground.")
                    continue
                brain.speak("Landing drone and disarming motors.")
                airsim.land()

            elif action == "INSPECT_ROOFTOP":
                alt = min(decision.get("altitude_m", 25.0), 45.0)
                brain.speak(f"Climbing to {alt:.0f} meters for rooftop and skyline inspection.")
                airsim.client.moveToZAsync(-alt, 3.0, vehicle_name=airsim.vehicle_name).join()

            elif action == "CLIMB":
                gain = decision.get("altitude_gain_m", 5.0)
                telem = airsim.get_telemetry()
                curr_alt = telem.get("alt_agl", 3.0)
                if curr_alt + gain > 45.0:
                    gain = max(0.0, 45.0 - curr_alt)
                    if gain < 0.5:
                        print("\n⚠️ [CEILING LIMIT] Drone is at maximum safe urban altitude of 45 meters!\n")
                        brain.speak("Maximum safe altitude reached. Climb rejected.")
                        continue
                    print(f"\n⚠️ [CEILING LIMIT] Clamping climb gain to {gain:.1f}m to stay below 45m ceiling.\n")
                brain.speak(f"Climbing {gain:.1f} meters.")
                curr_z = telem.get("z", 3.0)
                airsim.client.moveToZAsync(-(curr_z + gain), 2.0, vehicle_name=airsim.vehicle_name).join()

            elif action == "DESCEND":
                drop = decision.get("altitude_drop_m", 3.0)
                telem = airsim.get_telemetry()
                curr_alt = telem.get("alt_agl", 3.0)
                if curr_alt - drop < 1.0:
                    print(f"\n⚠️ [TERRAIN WARNING] Requested descent of {drop:.1f}m would impact ground (current altitude: {curr_alt:.1f}m)!\n")
                    brain.speak(f"Descent of {drop:.0f} meters would impact the ground. Initiating landing instead.")
                    airsim.land()
                    continue
                brain.speak(f"Descending {drop:.1f} meters.")
                curr_z = telem.get("z", 3.0)
                airsim.client.moveToZAsync(-(curr_z - drop), 2.0, vehicle_name=airsim.vehicle_name).join()

            elif action == "INSPECT_GROUND":
                brain.speak("Engaging downward camera for ground survey.")
                img = airsim.get_downward_camera()
                if img is not None:
                    print(f"📷 Downward Camera Frame Captured: {img.shape}")
                else:
                    print("📷 Downward Camera standby (waiting for Unreal Play mode).")



            else:
                print(f"⚠️ Unrecognized command: '{cmd}'. Try 'forward 20m', 'climb 10m', 'inspect rooftop', 'inspect ground', 'land'.")
                brain.speak("Command not recognized. Please specify a flight instruction.")

        except (KeyboardInterrupt, EOFError):
            print("\nShutting down controller.")
            break


if __name__ == "__main__":
    main()
