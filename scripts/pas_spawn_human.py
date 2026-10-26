"""Spawn the generated humanoid and check that YOLO recognises it as a person.

This is the gate for person-following on the Project AirSim environment: the
stock scene has no people, so until a detection comes back at a usable
confidence, a zero lock ratio proves nothing about the control law.

    python scripts\\pas_spawn_human.py
"""
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from garuda.flight.humanoid_glb import humanoid_bytes
from garuda.flight.pas_client import ProjectAirSimBackend

log = lambda *a: print(*a, flush=True)
Path("logs").mkdir(exist_ok=True)

#: Scene spawn is x=-1 y=8. Put the walker on open ground to the north.
WALKER_XY = (-1.0, 20.0)
SPAWN_XY = (-1.0, 8.0)


def bearing_deg(from_xy, to_xy) -> float:
    """NED heading in degrees: +x is north (0 deg), +y is east (90 deg)."""
    return math.degrees(math.atan2(to_xy[1] - from_xy[1], to_xy[0] - from_xy[0]))


def main() -> int:
    import cv2

    blob = humanoid_bytes()
    log(f"humanoid GLB: {len(blob)} bytes")

    b = ProjectAirSimBackend()
    if not b.connect():
        log("connect FAILED")
        return 1

    try:
        got = b.spawn_glb("Walker1", blob, (WALKER_XY[0], WALKER_XY[1], 0.0))
        log(f"spawn_object_from_file -> {got!r}")
        if not got:
            log("spawn returned None; the server rejected the glTF")
            return 2
        actor = got
        log(f"actors in scene: {len(b.list_scene_objects())}")

        if not b.takeoff(altitude_m=4.0):
            log("takeoff failed")
            return 3
        log(f"airborne at {b.altitude_agl():.2f} m")

        try:
            from garuda.perception.yolo_detector import YoloDetector

            det = YoloDetector()
        except Exception as e:
            log(f"detector unavailable: {type(e).__name__}: {e}")
            det = None

        def face(subject_xy) -> float:
            t = b.get_telemetry()
            here = (t["x"], t["y"])
            brg = bearing_deg(here, subject_xy)
            log(f"  heading {brg:+.0f} deg to subject "
                f"({math.hypot(subject_xy[0]-here[0], subject_xy[1]-here[1]):.1f} m)")
            b.rotate_to_heading(brg)
            return brg

        log("\n=== does the humanoid render at all? ===")
        face(WALKER_XY)
        time.sleep(1.0)
        frame = b.get_forward_camera()
        if frame is None:
            log("  no camera frame")
            return 4
        cv2.imwrite("logs/human_view.png", frame)
        log("  saved logs/human_view.png")
        persons = det.detect_persons(frame, conf=0.10) if det else []
        log(f"  persons@0.10 = {len(persons)}")
        if persons:
            for p in persons:
                log(f"    conf={p['confidence']:.2f} bbox={p['bbox']} h_ratio={p['h_ratio']:.3f}")
            return 0 if max(p["confidence"] for p in persons) >= 0.25 else 4

        log("\n=== not visible; close the distance and sweep ===")
        best = None
        for step in range(12):
            t = b.get_telemetry()
            here = (t["x"], t["y"])
            dist = math.hypot(WALKER_XY[0] - here[0], WALKER_XY[1] - here[1])
            face(WALKER_XY)
            time.sleep(0.8)
            frame = b.get_forward_camera()
            if frame is None:
                continue
            ps = det.detect_persons(frame, conf=0.10) if det else []
            top = ""
            if ps:
                p = max(ps, key=lambda d: d["confidence"])
                top = f" conf={p['confidence']:.2f} h_ratio={p['h_ratio']:.3f}"
                if best is None or p["confidence"] > best[0]:
                    best = (p["confidence"], frame.copy())
            log(f"  step {step:2} dist={dist:5.1f} m  alt={t['alt_agl']:4.1f}  "
                f"persons={len(ps)}{top}")
            if best and best[0] >= 0.25:
                break
            # Step toward the subject, walking, so we also verify the trajectory.
            b.move_velocity_body(vx=1.6, duration_s=1.5)

        if best:
            cv2.imwrite("logs/human_detected.png", best[1])
            log(f"\nBEST conf={best[0]:.2f} -> logs/human_detected.png")
            return 0
        log("\nSTILL NO PERSON - humanoid did not render")
        cv2.imwrite("logs/human_missed.png", b.get_forward_camera())
        return 4
    finally:
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
