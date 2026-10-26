"""Detection over recorded frames, ignoring the drone's own airframe.

The nose camera sits close enough to the hull that props/arms occupy a large
part of the frame whenever the camera is pitched. YOLO scores those black shapes
as 'car'/'truck', which both pollutes results and costs a chunk of the image.

Masking the lower-centre region where the airframe always appears removes those
false positives and lets us measure real pedestrian recall honestly.

  python scripts/detect_offline.py <session> [conf]
"""
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from garuda.perception.yolo_detector import YoloDetector

SESSION = sys.argv[1] if len(sys.argv) > 1 else "crowd2"
CONF = float(sys.argv[2]) if len(sys.argv) > 2 else 0.15

root = Path("logs/rec") / SESSION
frames = sorted(root.glob("front_*.jpg"))
if not frames:
    print(f"no frames in {root}")
    raise SystemExit(1)


def airframe_mask(h, w):
    """Mask the lower-centre wedge the drone hull always occupies."""
    m = np.zeros((h, w), np.uint8)
    cv2.ellipse(m, (int(w * 0.5), int(h * 1.15)), (int(w * 0.62), int(h * 0.52)),
                0, 180, 360, 255, -1)
    m[: int(h * 0.20), :] = 0            # never mask the top (sky/buildings)
    return m


det = YoloDetector()
print(f"session={SESSION}  frames={len(frames)}  conf>={CONF}\n")

rows = []
tot = {"person": 0, "vehicle": 0}
per_frame = []
for f in frames:
    im = cv2.imread(str(f))
    if im is None:
        continue
    h, w = im.shape[:2]
    masked = cv2.bitwise_and(im, im, mask=255 - airframe_mask(h, w))

    persons = det.detect_persons(masked, conf=CONF)
    raw = det.model(masked, conf=CONF, verbose=False)
    names = det.model.names
    veh = [names[int(c)] for c in raw[0].boxes.cls.tolist()] if len(raw) else []
    veh = [v for v in veh if v in ("car", "truck", "bus", "motorcycle", "bicycle")]

    tot["person"] += len(persons)
    tot["vehicle"] += len(veh)
    per_frame.append(len(persons))
    rows.append((f.name, len(persons), len(veh)))

hits = sum(1 for _, p, _ in rows if p > 0)
print(f"frames with >=1 person: {hits}/{len(rows)}")
print(f"total person detections: {tot['person']}  (max in one frame: {max(per_frame) if per_frame else 0})")
print(f"vehicle detections (masked region removed): {tot['vehicle']}")

print("\ntop frames by person count:")
for name, p, v in sorted(rows, key=lambda r: -r[1])[:8]:
    if p:
        print(f"  {name}  persons={p} vehicles={v}")

# Visualise the best frame with only person boxes drawn.
best = max(rows, key=lambda r: r[1]) if rows else None
if best and best[1] > 0:
    im = cv2.imread(str(root / best[0]))
    h, w = im.shape[:2]
    masked = cv2.bitwise_and(im, im, mask=255 - airframe_mask(h, w))
    persons = det.detect_persons(masked, conf=CONF)
    for p in persons:
        x1, y1, x2, y2 = p["bbox"]
        cv2.rectangle(masked, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(masked, f'{p["confidence"]:.2f}', (x1, max(10, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    outp = root / f"masked_best_{best[0]}"
    cv2.imwrite(str(outp), masked, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"\nmasked best frame -> {outp}")
    for p in persons:
        print(f"   conf={p['confidence']:.2f} bbox={p['bbox']} "
              f"h_ratio={p['h_ratio']:.3f} err_x={p['err_x']:+.2f} err_y={p['err_y']:+.2f}")
