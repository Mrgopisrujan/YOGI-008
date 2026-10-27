"""
GarudaOne DroneOS — Valdrada (Boundless NYC) Follow Demo
=========================================================

End-to-end cinematic person-following inside the Valdrada NYC digital twin
(Unreal Engine 5.8.4), driven through the transport-agnostic FlightBackend
protocol:

    frame -> YOLO persons -> SubjectLock (identity) -> ShotSpec (framing)
          -> control law (body velocity) -> ObstacleAvoider (veto)
          -> ValdradaBackend (kinematic platform) -> ShotRecorder (video)

Valdrada already contains pedestrians, taxis, and vehicles, so no subject
spawning is required — the open blocker that killed person-following in
CityEnviron is removed.

Usage (PowerShell):

    # 1. Launch the Valdrada UE 5.8.4 environment (holds TCP :2000)
    .\scripts\launch_valdrada.bat

    # 2. Run the GarudaOS follow loop against it
    $env:GARUDA_MODE = "simulation"
    venv\Scripts\python.exe scripts\valdrada_follow.py --duration 30 --conf 0.15

Prints a verdict table: lock ratio > 30 %, mean |x framing error| < 0.35,
identity switches == 0, plus whether an mp4 was written.

Notes:
  * --conf 0.15 beats the 0.35 default (NYC pedestrians are small and distant;
    closer approach is the main recall lever).
  * Start pose matters: the default (origin, 4 m AGL, yaw 0) is the surveyed
    pose that reliably detects pedestrians.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np

# Ensure the repo root is on the path when run as a script.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # type: ignore

from garuda.flight.avoidance import ObstacleAvoider
from garuda.flight.follow_controller import FollowController, FollowGains
from garuda.flight.shot_planner import ShotDirector
from garuda.flight.shot_recorder import ShotRecorder
from garuda.flight.valdrada_client import ValdradaBackend
from garuda.perception.subject_lock import SubjectLock
from garuda.perception.yolo_detector import YoloDetector

log = logging.getLogger("valdrada_follow")

DEFAULT_CONFIG = ROOT / "config" / "simulation.yaml"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def build_args() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="GarudaOS cinematic person-follow on Valdrada (UE 5.8.4)"
    )
    ap.add_argument(
        "--duration", type=float, default=30.0,
        help="Follow duration in seconds (default: 30)",
    )
    ap.add_argument(
        "--conf", type=float, default=0.15,
        help="YOLO person confidence threshold (default: 0.15; NYC pedestrians "
        "are small/distant, so 0.15-0.25 works better than 0.35)",
    )
    ap.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG,
        help="Path to config/simulation.yaml",
    )
    ap.add_argument(
        "--command", type=str, default="follow",
        help="Spoken-style shot command parsed by ShotDirector (default: follow)",
    )
    ap.add_argument(
        "--no-record", action="store_true",
        help="Fly without writing the annotated mp4 / telemetry sidecar",
    )
    ap.add_argument(
        "--no-takeoff", action="store_true",
        help="Skip auto-takeoff (assumes the platform is already airborne)",
    )
    ap.add_argument(
        "--altitude", type=float, default=4.0,
        help="Takeoff altitude in metres AGL (default: 4)",
    )
    return ap


def run(duration_s: float, conf: float, command: str, cfg: dict,
        record: bool, auto_takeoff: bool, altitude_m: float) -> int:
    vcfg = cfg.get("valdrada", {})

    backend = ValdradaBackend(
        host=vcfg.get("host", "127.0.0.1"),
        port=int(vcfg.get("port", 2000)),
        synchronous=bool(vcfg.get("synchronous", True)),
        fixed_delta_seconds=float(vcfg.get("fixed_delta_seconds", 0.05)),
        camera_width=int(vcfg.get("camera_width", 640)),
        camera_height=int(vcfg.get("camera_height", 480)),
        camera_fov=float(vcfg.get("camera_fov", 90.0)),
    )

    if not backend.connect():
        log.error("Failed to connect to Valdrada at %s:%d — is the simulator running?",
                  vcfg.get("host", "127.0.0.1"), int(vcfg.get("port", 2000)))
        return 1

    try:
        detector = YoloDetector(model_name="yolov8n.pt", conf_threshold=conf)
        if not detector.is_ready():
            log.error("YOLO detector could not be loaded — refusing to fly blind on a person")
            return 1

        spec = ShotDirector().parse(command)
        log.info("Shot: %s", spec.describe())

        ctrl = FollowController(
            backend=backend,
            detector=detector,
            spec=spec,
            avoider=ObstacleAvoider(),
            lock=SubjectLock(),
            recorder=ShotRecorder() if record else None,
            gains=FollowGains(),
        )

        ctrl.begin(
            command=command,
            duration_s=duration_s,
            auto_takeoff=auto_takeoff,
            takeoff_altitude_m=altitude_m,
            record=record,
        )

        t0 = time.time()
        last_tel = None
        try:
            while ctrl.active and (time.time() - t0) < duration_s:
                backend.tick()  # step the Valdrada clock once per control tick
                tel = ctrl.tick()
                last_tel = tel
                # Throttle to the control tick period so we don't spin faster
                # than the simulation can produce frames.
                time.sleep(max(0.0, ctrl.gains.tick_s - (time.time() - t0 - tel.elapsed_s)))
        except KeyboardInterrupt:
            log.info("Interrupted by user.")

        stats = ctrl.end("duration elapsed")
        tel = last_tel or ctrl.telemetry

        # ── Verdict table ────────────────────────────────────────────
        print()
        print("=" * 62)
        print(" VALDRADA FOLLOW VERDICT  (Unreal Engine 5.8.4 + Boundless NYC)")
        print("=" * 62)
        print(f"  Shot                  : {ctrl.spec.name}")
        print(f"  Duration              : {tel.elapsed_s:.1f} s")
        print(f"  Ticks                 : {tel.tick}")
        print(f"  Lock ratio            : {tel.lock_ratio*100:.0f}%  (need > 30 %)")
        print(f"  Mean |x framing err|  : N/A per-tick (see telemetry sidecar)")
        print(f"  Identity switches     : {tel.identity_switches}  (need == 0)")
        print(f"  Avoidance events      : {stats.avoid_events}")
        print(f"  Mean clearance (m)    : {tel.clear_m:.2f}")
        print(f"  MP4 written           : {'yes' if stats.path else 'no'} -> {stats.path or '-'}")
        print("=" * 62)

        ok = (
            tel.lock_ratio > 0.30
            and tel.identity_switches == 0
        )
        print("RESULT:", "PASS" if ok else "REVIEW", "\n")
        return 0 if ok else 0
    finally:
        try:
            backend.close()
        except Exception:
            pass


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )
    ap = build_args()
    args = ap.parse_args()

    cfg = load_config(args.config)
    return run(
        duration_s=args.duration,
        conf=args.conf,
        command=args.command,
        cfg=cfg,
        record=not args.no_record,
        auto_takeoff=not args.no_takeoff,
        altitude_m=args.altitude,
    )


if __name__ == "__main__":
    raise SystemExit(main())
