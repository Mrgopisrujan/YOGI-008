"""Drive ProjectAirSimBackend against the live environment.

Exercises the real FlightBackend surface through the same class the follow loop
uses, so this is a wiring test rather than a parallel implementation:

  connect -> takeoff -> frames -> depth -> velocity -> telemetry -> hover -> land

Then it climbs and sweeps the chase camera looking for people, because the
stock scene spawns the drone over a fountain plaza and the old UE4 build had a
crowd baked into the level. Until a person is detected here, person-following
is not proven on the new environment.

One simulator instance only. RAM permitting.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from garuda.flight.pas_client import ProjectAirSimBackend

log = lambda *a: print(*a, flush=True)
Path("logs").mkdir(exist_ok=True)


def main() -> int:
    import cv2

    b = ProjectAirSimBackend()
    if not b.connect():
        log("connect FAILED - is CityEnviron running with 8989/8990 open?")
        return 1
    log("connected")

    ok = b.takeoff(altitude_m=6.0)
    log(f"takeoff -> {ok}; altitude {b.altitude_agl():.2f} m AGL")
    if not ok:
        b.close()
        return 1

    # Frames are pub/sub and publish on the sim clock; give them a moment.
    for _ in range(20):
        if b.get_forward_camera() is not None:
            break
        time.sleep(0.5)

    log("\n=== FlightBackend surface ===")
    frame = b.get_forward_camera()
    log(f"  get_forward_camera -> {None if frame is None else frame.shape}")
    depth = b.get_forward_depth()
    if depth is not None:
        finite = depth[np.isfinite(depth) & (depth > 0.1)]
        log(
            f"  get_forward_depth -> {depth.shape}, "
            f"{finite.size} valid, {finite.min():.2f}..{finite.max():.2f} m"
        )
    else:
        log("  get_forward_depth -> None (no frame yet)")
    log(f"  get_telemetry -> {b.get_telemetry()}")
    log(f"  is_in_air -> {b.is_in_air()}")
    log(f"  frames_received -> {b.frames_received()}")
    if frame is None:
        log("  NO FRAMES - check that ImageDisplay started and the topics exist")

    if frame is not None:
        cv2.imwrite("logs/backend_forward.png", frame)
        log("  saved logs/backend_forward.png")
    if depth is not None:
        g = np.clip(np.nan_to_num(depth, nan=30.0) / 30.0, 0, 1)
        cv2.imwrite("logs/backend_depth.png", cv2.applyColorMap((g * 255).astype(np.uint8), cv2.COLORMAP_TURBO))
        log("  saved logs/backend_depth.png")

    log("\n=== movement through the backend ===")
    for label, args in (
        ("forward 2 m/s", dict(vx=2.0, duration_s=2.0)),
        ("yaw right 25 dps", dict(yaw_rate_dps=25.0, duration_s=2.0)),
        ("strafe right 1 m/s", dict(vy=1.0, duration_s=1.5)),
    ):
        if b.move_velocity_body(**args):
            t = b.get_telemetry()
            log(f"  {label:22} -> x={t['x']:.2f} y={t['y']:.2f} alt={t['alt_agl']:.2f}")
        else:
            log(f"  {label:22} -> FAILED")
    b.hover()

    log("\n=== person survey (chase camera, low confidence) ===")
    try:
        from garuda.perception.yolo_detector import YoloDetector

        det = YoloDetector()
    except Exception as e:
        log(f"  detector unavailable: {type(e).__name__}: {e}")
        det = None

    hits = 0
    for step in range(12):
        # Rotate a full circle; the chase cam sweeps the whole plaza.
        b.move_velocity_body(vx=3.0, yaw_rate_dps=60.0, duration_s=2.5)
        f = b.get_forward_camera()
        if f is None:
            log(f"  step {step}: no frame")
            continue
        counts = {}
        if det is not None:
            raw = det.model(f, conf=0.05, verbose=False)
            if len(raw):
                names = det.model.names
                for c in raw[0].boxes.cls.tolist():
                    counts[names[int(c)]] = counts.get(names[int(c)], 0) + 1
        persons = counts.get("person", 0)
        hits += persons
        t = b.get_telemetry()
        top = ", ".join(f"{k}x{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:5])
        log(f"  step {step:2} yaw-sweep  x={t['x']:7.1f} y={t['y']:7.1f}  "
            f"persons={persons}  [{top}]")
        if persons:
            cv2.imwrite(f"logs/survey_person_{step}.png", f)
    log(f"\n  total person detections across sweep: {hits}")
    if hits == 0 and det is not None:
        log("  NO PEOPLE FOUND in the stock scene - person-following is NOT")
        log("  proven on this environment yet.")

    log(f"\nland -> {b.land()}")
    b.close()
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
