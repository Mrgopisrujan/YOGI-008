"""Coverage for image-space motion prediction and bounded coasting."""

import numpy as np

from garuda.perception.subject_lock import BoxKinematicEstimator, SubjectLock


def det(x, confidence=0.9, y=80, width=30, height=70):
    return {"class": "person", "confidence": confidence,
            "bbox": [x, y, x + width, y + height],
            "h_ratio": height / 240, "err_x": 0.0, "err_y": 0.0}


def test_box_estimator_tracks_velocity_and_extrapolates():
    estimator = BoxKinematicEstimator()
    estimator.update([100, 80, 130, 150])
    estimator.update([110, 80, 140, 150])

    predicted = estimator.predict()

    assert estimator.velocity[0] > 0
    assert predicted[0] > 110
    assert estimator.contains(predicted)


def test_subject_lock_coasts_then_enters_search():
    frame = np.full((240, 320, 3), (30, 80, 160), dtype=np.uint8)
    lock = SubjectLock(max_coast_frames=2)
    assert lock.update([det(100)], frame)["tracking_state"] == "LOCKED"
    assert lock.update([det(110)], frame)["tracking_state"] == "LOCKED"

    coast1 = lock.update([], frame)
    coast2 = lock.update([], frame)
    expired = lock.update([], frame)

    assert coast1["tracking_state"] == "LOCKED_PREDICTED"
    assert coast2["tracking_state"] == "LOCKED_PREDICTED"
    assert coast2["bbox"][0] > coast1["bbox"][0]
    assert expired is None
    assert lock.tracking_state == "SEARCH"


def test_low_confidence_proposal_requires_predicted_gate():
    frame = np.full((240, 320, 3), (30, 80, 160), dtype=np.uint8)
    lock = SubjectLock(max_coast_frames=5)
    lock.update([det(100)], frame)
    lock.update([], frame)

    near = lock.update([det(101, confidence=0.2)], frame)
    assert near is not None
    assert near["tracking_state"] == "LOCKED"

    lock.update([], frame)
    far = lock.update([det(270, confidence=0.2)], frame)
    assert far is not None
    assert far["tracking_state"] == "LOCKED_PREDICTED"


def test_reacquisition_rejects_different_appearance():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[70:160, 95:145] = (20, 40, 220)
    lock = SubjectLock(max_coast_frames=1)
    lock.update([det(100)], frame)
    lock.update([], frame)
    lock.update([], frame)  # SEARCH

    impostor_frame = frame.copy()
    impostor_frame[70:160, 200:250] = (220, 40, 20)
    result = lock.update([det(205, confidence=0.9)], impostor_frame)

    assert result is None
    assert lock.state().switches == 0

