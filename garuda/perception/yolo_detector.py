"""
GarudaOne DroneOS — Real-time YOLOv8 Perception Engine
======================================================
Provides onboard object detection and visual tracking for the autonomous drone.
Directly interfaces with the live camera stream from Unreal Engine AirSim to
detect people (class 0), vehicles, and scene obstacles with high frame rate.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
import numpy as np

log = logging.getLogger("YoloDetector")


class YoloDetector:
    """
    Onboard YOLOv8 detector for autonomous closed-loop visual tracking.
    """

    def __init__(self, model_name: str = "yolov8n.pt", conf_threshold: float = 0.35):
        self.model_name = model_name
        self.conf_threshold = conf_threshold
        self.model = None
        self._is_loaded = False
        self._load_model()

    def _load_model(self) -> bool:
        try:
            from ultralytics import YOLO  # type: ignore
            log.info(f"Loading YOLO model: {self.model_name}...")
            self.model = YOLO(self.model_name)
            self._is_loaded = True
            log.info(f"✅ YOLO model [{self.model_name}] loaded successfully.")
            return True
        except ImportError:
            log.warning("Ultralytics package not installed. Run: pip install ultralytics")
            return False
        except Exception as e:
            log.warning(f"Error loading YOLO model ({e})")
            return False

    def is_ready(self) -> bool:
        return self._is_loaded and self.model is not None

    def detect_persons(
        self,
        frame: np.ndarray,
        conf: Optional[float] = None
    ) -> list[dict[str, Any]]:
        """
        Runs inference on RGB/BGR frame and returns detected persons with
        normalized tracking error metrics for visual servoing.
        """
        if not self.is_ready():
            return []

        h, w = frame.shape[:2]
        # Keep a permissive proposal floor; SubjectLock applies the motion and
        # covariance gate before accepting sub-threshold-confidence proposals.
        threshold = max(0.05, conf if conf is not None else self.conf_threshold)
        detections: list[dict[str, Any]] = []

        try:
            # Run inference; class 0 is 'person' in standard COCO
            results = self.model(frame, classes=[0], conf=threshold, verbose=False)
            if not results:
                return []

            result = results[0]
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                return []

            for box in boxes:
                xyxy = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3])
                score = float(box.conf[0].cpu().numpy())

                # Centroid & scale calculations
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                box_w = x2 - x1
                box_h = y2 - y1

                # Normalized screen errors (-1.0 to +1.0)
                err_x = (cx - (w / 2.0)) / (w / 2.0)
                err_y = (cy - (h / 2.0)) / (h / 2.0)

                # Height ratio (distance proxy: smaller ratio = further away)
                h_ratio = box_h / float(h)
                w_ratio = box_w / float(w)

                detections.append({
                    "class": "person",
                    "confidence": score,
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "centroid": (cx, cy),
                    "err_x": err_x,
                    "err_y": err_y,
                    "h_ratio": h_ratio,
                    "w_ratio": w_ratio,
                    "area_ratio": (box_w * box_h) / float(w * h)
                })

            # Sort by confidence descending
            detections.sort(key=lambda d: d["confidence"], reverse=True)
            return detections

        except Exception as e:
            log.warning(f"YOLO inference error: {e}")
            return []

    def annotate_frame(
        self,
        frame: np.ndarray,
        detections: list[dict[str, Any]],
        target_index: int = 0
    ) -> np.ndarray:
        """
        Draws visual servoing tactical HUD boxes, crosshairs, and tracking vectors on the frame.
        """
        import cv2

        annotated = frame.copy()
        h, w = frame.shape[:2]
        center_x, center_y = w // 2, h // 2

        # Draw center optical reticle
        cv2.drawMarker(annotated, (center_x, center_y), (0, 255, 255), cv2.MARKER_CROSS, 20, 1)

        for i, det in enumerate(detections):
            x1, y1, x2, y2 = det["bbox"]
            is_locked_target = (i == target_index)
            color = (0, 255, 0) if is_locked_target else (0, 165, 255)
            thickness = 2 if is_locked_target else 1

            # Bounding box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)

            # Centroid point
            cx, cy = int(det["centroid"][0]), int(det["centroid"][1])
            cv2.circle(annotated, (cx, cy), 4, color, -1)

            # Error vector line from center screen to target centroid
            if is_locked_target:
                cv2.line(annotated, (center_x, center_y), (cx, cy), (0, 255, 255), 1)

            # Label banner
            label = f"PERSON {det['confidence']*100:.0f}% [e_x:{det['err_x']:+.2f}]"
            cv2.putText(
                annotated,
                label,
                (x1, max(y1 - 6, 15)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv2.LINE_AA
            )

        return annotated
