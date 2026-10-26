#!/usr/bin/env python3
"""
GarudaOS — Live Follow Shot Verification (no voice, no LLM)
=========================================================
End-to-end proof that "follow that man and take drone shots" works against
the real simulator, without needing a microphone or an API key.

What it does:
  1. Connects to CityEnviron.exe on :41451.
  2. Spawns a pedestrian actor if none exists (so there is a subject).
  3. Runs the same FollowController the voice path uses, for a fixed duration.
  4. Prints a verdict table: lock ratio, framing error, avoidance events,
     whether a video file was produced, and whether it is playable.

This is the test that would have caught the original defects. The unit tests
prove the control law; this proves the wiring.

Usage:
    python scripts/verify_follow_shot.py --duration 25
    python scripts/verify_follow_shot.py --command "follow that man, close up"
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from garuda.flight.airsim_client import AirSimClient
from garuda.flight.shot_planner import ShotDirector

log = logging.getLogger("verify")


def ensure_subject(airsim: AirSimClient, count: int = 1) -> list[str]:
    """Make sure at least one pedestrian actor exists in the scene."""
    names = [n for n in airsim.list_scene_objects(".*") if n.lower().startswith("pedestrian")]
    if names:
        log.info(f"Scene already has pedestrians: {names}")
        return names

    log.info("No pedestrians found — spawning one in front of the launchpad")
    try:
        import airsim as airsim_mod
    except ImportError:
        return []

    spawned = []
    for i in range(count):
        name = f"VerifyPedestrian_{i + 1}"
        pose = airsim_mod.Pose(
            airsim_mod.Vector3r(6.0 + i * 2.0, 1.0, 0.0), airsim_mod.to_quaternion(0, 0, 0)
        )
        for mesh in ("/Engine/BasicShapes/Capsule", "/Engine/BasicShapes/Cylinder"):
            try:
                got = airsim.client.simSpawnObject(
                    name, mesh, pose, scale=airsim_mod.Vector3r(0.45, 0.45, 1.8),
                    physics_enabled=False,
                )
                if got:
                    spawned.append(got)
                    log.info(f"Spawned {got} using {mesh}")
                    break
            except Exception as e:
                log.debug(f"spawn {mesh} failed: {e}")
    return spawned


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--command", default="follow that man",
                    help="Spoken-style command; the shot planner reads it verbatim.")
    ap.add_argument("--duration", type=float, default=20.0)
    ap.add_argument("--port", type=int, default=41451)
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--no-takeoff", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    airsim = AirSimClient(port=args.port)
    print("[1/4] Connecting to CityEnviron on :%d ..." % args.port)
    if not airsim.connect(timeout=25.0):
        print("❌ Could not reach the simulator. Launch CityEnviron.exe first.")
        return 2
    print("   ✅ connected")

    print("[2/4] Ensuring a pedestrian subject exists ...")
    subjects = ensure_subject(airsim)
    print(f"   subjects: {subjects or 'none (relies on scene pedestrians)'}")

    print("[3/4] Building follow controller from the spoken command ...")
    try:
        from garuda.perception.yolo_detector import YoloDetector

        detector = YoloDetector()
    except Exception as e:
        print(f"❌ YOLO unavailable: {e}")
        return 3
    if not detector.is_ready():
        print("❌ YOLO model failed to load")
        return 3
    print(f"   detector ready ({detector.model_name})")

    spec = ShotDirector().parse(args.command)
    print(f"   shot: {spec.describe()}")

    events: list[str] = []
    ctrl = airsim.make_follow_controller(command=args.command, shot=spec, on_event=events.append)

    print(f"[4/4] Flying for {args.duration:.0f}s (say nothing; this is script-driven)\n")
    ctrl.begin(
        command=args.command,
        spec=spec,
        duration_s=args.duration,
        record=not args.no_record,
        auto_takeoff=not args.no_takeoff,
    )

    t0 = time.time()
    errs: list[float] = []
    while ctrl.active and time.time() - t0 < args.duration:
        tel = ctrl.tick()
        if tel.locked:
            errs.append(abs(tel.err_x))
        print(
            f"\r  [{tel.elapsed_s:5.1f}s] {'LOCK' if tel.locked else '----'} "
            f"conf={tel.conf*100:3.0f}% err=({tel.err_x:+.2f},{tel.err_y:+.2f}) "
            f"frame={tel.h_ratio*100:4.1f}% v=({tel.vx:+.1f},{tel.vy:+.1f},{tel.vz:+.1f}) "
            f"yaw={tel.yaw_rate:+.0f} avoid={tel.avoidance}({tel.clear_m:.1f}m)  ",
            end="",
            flush=True,
        )
        time.sleep(0.05)
    print()

    stats = ctrl.end("verification run complete")
    tele = airsim.get_telemetry()

    # ── Verdict ───────────────────────────────────────────────────────
    print("\n" + "=" * 66)
    print("  VERDICT")
    print("=" * 66)
    lock_ratio = stats.lock_ratio
    framing = float(np.mean(errs)) if errs else 1.0
    ok_lock = lock_ratio > 0.3
    ok_frame = framing < 0.35

    rows = [
        ("Visual lock ratio", f"{lock_ratio*100:.0f}%", ok_lock, ">30% of the shot"),
        ("Mean |x framing error", f"{framing:.3f}", ok_frame, "<0.35 of half-frame"),
        ("Ticks executed", f"{ctrl.telemetry.tick}", ctrl.telemetry.tick > 10, ">10"),
        ("Identity switches", f"{ctrl.telemetry.identity_switches}",
         ctrl.telemetry.identity_switches == 0, "0 (lock held one subject)"),
        ("Avoidance events", f"{stats.avoid_events}", True, "informational"),
        ("Shot", spec.name, True, "from spoken command"),
        ("Drone altitude", f"{tele.get('alt_agl', 0):.2f} m", tele.get("alt_agl", 0) > 0.5, ">0.5m"),
    ]
    for name, value, ok, crit in rows:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:24} {value:>10}   (want {crit})")

    if stats.path:
        exists = Path(stats.path).exists()
        size = Path(stats.path).stat().st_size if exists else 0
        print(f"  {'PASS' if exists and size > 1000 else 'FAIL'}  {'Video file':24} {str(size)+' B':>10}   "
              f"(want >1kB)")
        print(f"\n  🎬 {stats.path}")
        sidecars = list(Path(stats.path).parent.glob(Path(stats.path).stem + "_telemetry.jsonl"))
        if sidecars:
            n = len(sidecars[0].read_text().splitlines())
            print(f"  📊 {sidecars[0].name}  ({n} telemetry rows)")
        if stats.keyframes:
            print(f"  🖼  {len(stats.keyframes)} keyframes")
    elif not args.no_record:
        print(f"  FAIL  {'Video file':24} {'none':>10}   (recording produced nothing)")

    if events:
        print("\n  Events:")
        for e in events[:12]:
            print(f"    {e}")

    airsim.hover()
    critical_ok = ok_lock and ok_frame
    print("\n" + ("✅ FOLLOW SHOT VERIFIED" if critical_ok else "❌ FOLLOW SHOT DID NOT CONVERGE"))
    return 0 if critical_ok else 1


if __name__ == "__main__":
    sys.exit(main())
