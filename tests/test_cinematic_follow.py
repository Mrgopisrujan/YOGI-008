"""
Tests for the cinematic subject-follow stack.

These run without Valdrada, without a GPU, and without Unreal: a stub backend
renders a synthetic scene (coloured "pedestrians" on a canvas plus a depth
map) and a stub detector returns the ground-truth boxes. That makes the
control law, the identity lock, the avoidance veto and the shot planner
testable in isolation — which is the only way to iterate on framing gains
without a simulator round-trip per run.

The stub deliberately reproduces the two failure modes that matter:
  * two pedestrians in frame at once (identity must not flip-flop), and
  * a wall that walks into the depth map mid-shot (velocity must be vetoed).

NOTE: the stub's method names must match ``ValdradaBackend`` exactly. A mismatch
here (``get_front_camera`` vs ``get_forward_camera``) type-checks fine, passes
every test in this file, and then fails on the first real tick in the
simulator. ``TestBackendContractMatchesRealClient`` guards that.
"""

from __future__ import annotations

import numpy as np
import pytest

from garuda.flight.avoidance import ObstacleAvoider
from garuda.flight.follow_controller import FlightBackend, FollowController, FollowGains
from garuda.flight.shot_planner import ShotDirector, ShotSpec
from garuda.flight.shot_recorder import FrameTelemetry, ShotRecorder
from garuda.perception.subject_lock import SubjectLock


# ── Backend contract ───────────────────────────────────────────────────

def test_backend_contract_matches_real_client():
    """The stub and the real Valdrada client must expose identical method names.

    FlightBackend is a Protocol, so a missing method is not a type error and no
    test using a stub can catch it. This is the one place the two are compared.
    """
    from garuda.flight.valdrada_client import ValdradaBackend

    required = {m for m in dir(FlightBackend) if not m.startswith("_")}
    on_stub = {m for m in dir(StubBackend) if not m.startswith("_")}
    on_client = set(dir(ValdradaBackend))

    assert required <= on_stub, f"StubBackend missing: {sorted(required - on_stub)}"
    assert required <= on_client, (
        f"ValdradaBackend cannot satisfy FlightBackend, missing: "
        f"{sorted(required - on_client)}"
    )


# ── Fakes ──────────────────────────────────────────────────────────────

W, H = 640, 480


def _det(cx: float, cy: float, bw: float, bh: float, conf: float = 0.9) -> dict:
    """Build a detector-shaped dict from a pixel box."""
    x1, y1 = cx - bw / 2, cy - bh / 2
    x2, y2 = cx + bw / 2, cy + bh / 2
    return {
        "class": "person",
        "confidence": conf,
        "bbox": [int(x1), int(y1), int(x2), int(y2)],
        "centroid": (cx, cy),
        "err_x": (cx - W / 2) / (W / 2),
        "err_y": (cy - H / 2) / (H / 2),
        "h_ratio": bh / H,
        "w_ratio": bw / W,
        "area_ratio": (bw * bh) / (W * H),
    }


class Scene:
    """
    Minimal synthetic world: two pedestrians with distinct colours and a
    wall that the test can push into the depth map.
    """

    def __init__(self) -> None:
        self.subject = (0.45, 0.30)   # target position as a fraction of frame
        self.decoy = (0.62, 0.24)
        self.subject_colour = (200, 40, 40)     # red-ish
        self.decoy_colour = (40, 60, 220)       # blue-ish
        self.wall_m: float | None = None        # obstacle distance, None = clear
        self.with_decoy: bool = True            # disable to test a lone subject

    def render(self) -> np.ndarray:
        frame = np.zeros((H, W, 3), dtype=np.uint8)
        frame[:, :] = (30, 34, 40)
        actors = [(self.subject, self.subject_colour, 0.16)]
        if self.with_decoy:
            actors.append((self.decoy, self.decoy_colour, 0.14))
        for (fx, fh), colour, width in actors:
            cx, cy = fx * W, fh * H
            bh, bw = fh * H, width * W
            x1, y1 = int(cx - bw / 2), int(cy - bh / 2)
            x2, y2 = int(cx + bw / 2), int(cy + bh / 2)
            frame[max(0, y1):y2, max(0, x1):x2] = colour
        return frame

    def depth(self) -> np.ndarray:
        depth = np.full((H, W), 40.0, dtype=np.float32)
        if self.wall_m is not None:
            # Obstacle in the centre-left of frame: left flank is blocked.
            depth[int(H * 0.25):int(H * 0.75), int(W * 0.30):int(W * 0.55)] = self.wall_m
        return depth

    def detections(self) -> list[dict]:
        out = [_det(self.subject[0] * W, self.subject[1] * H, 0.16 * W, self.subject[1] * H, 0.92)]
        if self.with_decoy:
            out.append(_det(self.decoy[0] * W, self.decoy[1] * H, 0.14 * W, self.decoy[1] * H, 0.88))
        return out


class StubBackend:
    """FlightBackend implementation backed by Scene."""

    def __init__(self, scene: Scene) -> None:
        self.scene = scene
        self.airborne = True
        self.commands: list[dict] = []
        self.hovered = 0
        self.takeoffs = 0
        self.pitch: float | None = None

    def get_forward_camera(self):
        return self.scene.render()

    def get_forward_depth(self):
        return self.scene.depth()

    def get_telemetry(self) -> dict:
        return {"connected": True, "x": 0.0, "y": 0.0, "z": 3.0, "alt_agl": 3.0, "in_air": self.airborne}

    def is_in_air(self) -> bool:
        return self.airborne

    def takeoff(self, altitude_m: float = 3.0):
        self.takeoffs += 1
        self.airborne = True

    def move_velocity_body(self, vx=0.0, vy=0.0, vz=0.0, yaw_rate_dps=0.0, duration_s=0.2):
        self.commands.append(
            {"vx": vx, "vy": vy, "vz": vz, "yaw": yaw_rate_dps, "dt": duration_s}
        )
        return True

    def hover(self):
        self.hovered += 1
        return True

    def set_camera_pitch(self, pitch_deg: float):
        self.pitch = pitch_deg
        return True


class StubDetector:
    def __init__(self, scene: Scene) -> None:
        self.scene = scene
        self.calls = 0

    def detect_persons(self, frame):
        self.calls += 1
        return self.scene.detections()


def _controller(scene: Scene, spec: ShotSpec | None = None, **kw) -> FollowController:
    backend = StubBackend(scene)
    return FollowController(
        backend=backend,
        detector=StubDetector(scene),
        spec=spec or ShotSpec(),
        gains=kw.pop("gains", FollowGains()),
        **kw,
    )


# ── SubjectLock ────────────────────────────────────────────────────────

class TestSubjectLock:
    def test_bootstraps_most_confident(self):
        lock = SubjectLock()
        chosen = lock.select([_det(100, 200, 50, 150, 0.6), _det(400, 300, 90, 300, 0.95)])
        assert chosen["confidence"] == pytest.approx(0.95)

    def test_keeps_same_subject_across_frames(self):
        scene = Scene()
        lock = SubjectLock()
        first = lock.select(scene.detections(), scene.render())
        assert first["bbox"][0] < 0.5 * W  # the red subject, left of the decoy

        # Subject walks right and grows; decoy moves the other way.
        for _ in range(6):
            scene.subject = (min(0.8, scene.subject[0] + 0.03), scene.subject[1] + 0.01)
            scene.decoy = (max(0.1, scene.decoy[0] - 0.05), scene.decoy[1] - 0.01)
            chosen = lock.select(scene.detections(), scene.render())
            assert chosen is not None
            # The lock must not silently jump to the decoy.
            assert chosen["bbox"][0] < 0.5 * W or scene.subject[0] > 0.5

    def test_lost_target_returns_none_then_resets(self):
        lock = SubjectLock(max_lost_frames=2)
        lock.select([_det(320, 240, 80, 200, 0.9)], np.zeros((H, W, 3), np.uint8))
        assert lock.select([], None) is None
        assert lock.select([], None) is None
        assert lock.select([], None) is None
        # After the expiry, a fresh scene re-bootstraps.
        assert lock.select([_det(100, 100, 40, 80, 0.8)], None) is not None

    def test_ignores_low_confidence_noise(self):
        lock = SubjectLock(min_confidence=0.5)
        assert lock.select([_det(320, 240, 60, 150, 0.2)], None) is None


# ── ObstacleAvoider ────────────────────────────────────────────────────

class TestObstacleAvoider:
    def test_clear_scene_permits_full_speed(self):
        av = ObstacleAvoider()
        d = av.evaluate_depth(np.full((48, 64), 30.0, np.float32))
        assert d.status == "CLEAR"
        assert d.forward_scale == pytest.approx(1.0)

    def test_wall_inside_stop_distance_asserts_stop(self):
        av = ObstacleAvoider(stop_distance_m=2.0, warning_distance_m=5.0)
        depth = np.full((48, 64), 30.0, np.float32)
        depth[12:36, 28:36] = 1.0
        d = av.evaluate_depth(depth)
        assert d.hard_stop
        assert d.status == "STOP"
        assert d.forward_scale == 0.0

    def test_wall_in_warning_band_scales_speed(self):
        av = ObstacleAvoider(stop_distance_m=2.0, warning_distance_m=5.0)
        depth = np.full((48, 64), 30.0, np.float32)
        depth[12:36, 28:36] = 3.5
        d = av.evaluate_depth(depth)
        assert d.status == "BRAKE"
        assert 0.0 < d.forward_scale < 1.0

    def test_yields_toward_the_clearer_flank(self):
        av = ObstacleAvoider(stop_distance_m=2.0, warning_distance_m=5.0)
        depth = np.full((48, 64), 30.0, np.float32)
        # Block the left flank and the corridor; the right flank stays clear.
        depth[12:36, 6:36] = 1.0
        d = av.evaluate_depth(depth)
        assert d.hard_stop
        assert d.left_m < d.right_m
        assert d.strafe_bias > 0        # bias right, away from the blockage

    def test_missing_depth_fails_safe(self):
        av = ObstacleAvoider()
        d = av.evaluate_depth(None)
        assert d.hard_stop and not d.depth_valid
        vx, vy, vz = av.apply(3.0, 0.0, 0.0, d)
        assert vx == 0.0

    def test_scalar_distance_api(self):
        av = ObstacleAvoider(stop_distance_m=2.0, warning_distance_m=5.0)
        assert av.evaluate_distance(30.0).status == "CLEAR"
        assert av.evaluate_distance(1.0).status == "STOP"

    def test_rejects_inverted_thresholds(self):
        with pytest.raises(ValueError):
            ObstacleAvoider(stop_distance_m=5.0, warning_distance_m=2.0)


# ── ShotDirector ───────────────────────────────────────────────────────

class TestShotDirector:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("follow that man", "follow"),
            ("follow that man close up", "close_up"),
            ("orbit him", "orbit"),
            ("follow her from behind", "chase"),
            ("give me a wide shot", "wide"),
            ("shoot him from a low angle", "low_angle"),
            ("over the shoulder please", "over_shoulder"),
            ("pull back and reveal him", "reveal"),
        ],
    )
    def test_shot_selection(self, text, expected):
        assert ShotDirector().parse(text).name == expected

    def test_direction_flips_orbit(self):
        ccw = ShotDirector().parse("orbit him to the left")
        cw = ShotDirector().parse("orbit him to the right")
        assert ccw.orbit_rate_dps < 0 < cw.orbit_rate_dps

    def test_explicit_distance_reframes(self):
        spec = ShotDirector().parse("follow that man keep 3 metres away")
        assert spec.standoff_m == pytest.approx(3.0)
        assert spec.target_h_ratio > 0.45   # closer => tighter framing

    def test_ignores_nonsense_distance(self):
        spec = ShotDirector().parse("follow that man keep 900 metres away")
        assert spec.standoff_m == pytest.approx(4.5)

    def test_empty_defaults_to_follow(self):
        assert ShotDirector().parse("").name == "follow"


# ── FollowController ───────────────────────────────────────────────────

class TestFollowController:
    def test_closes_distance_when_subject_is_far(self):
        scene = Scene()
        scene.with_decoy = False
        scene.subject = (0.5, 0.12)      # small in frame => far away
        ctrl = _controller(scene)
        ctrl.begin(record=False, auto_takeoff=False)
        tel = ctrl.tick()
        assert tel.locked
        assert tel.vx > 0                  # advance
        assert tel.yaw_rate == pytest.approx(0.0, abs=1e-6)   # already centred

    def test_yaws_toward_an_offcentre_subject(self):
        scene = Scene()
        scene.subject = (0.85, 0.30)      # hard right
        ctrl = _controller(scene)
        ctrl.begin(record=False, auto_takeoff=False)
        tel = ctrl.tick()
        assert tel.yaw_rate > 0            # positive = turn right

    def test_backs_off_when_subject_is_too_large(self):
        scene = Scene()
        scene.with_decoy = False
        scene.subject = (0.5, 0.95)       # fills the frame => too close
        ctrl = _controller(scene)
        ctrl.begin(record=False, auto_takeoff=False)
        tel = ctrl.tick()
        assert tel.vx < 0                  # retreat

    def test_identifies_the_subject_not_the_decoy(self):
        scene = Scene()
        ctrl = _controller(scene)
        ctrl.begin(record=False, auto_takeoff=False)
        for _ in range(8):
            scene.subject = (min(0.85, scene.subject[0] + 0.04), scene.subject[1])
            tel = ctrl.tick()
        assert tel.identity_switches == 0

    def test_wall_stops_forward_motion(self):
        scene = Scene()
        scene.with_decoy = False
        scene.subject = (0.5, 0.12)       # far => would command vx > 0
        scene.wall_m = 1.0
        ctrl = _controller(scene)
        ctrl.begin(record=False, auto_takeoff=False)
        tel = ctrl.tick()
        assert tel.avoidance == "STOP"
        assert ctrl.backend.commands[-1]["vx"] == pytest.approx(0.0, abs=1e-6)
        assert ctrl.backend.commands[-1]["vy"] != 0.0   # yields sideways

    def test_no_target_holds_station(self):
        scene = Scene()
        scene.with_decoy = False
        scene.subject = (0.5, 0.12)
        ctrl = _controller(scene)

        class BlindDetector:
            def detect_persons(self, frame):
                return []

        ctrl.detector = BlindDetector()
        ctrl.begin(record=False, auto_takeoff=False)
        tel = ctrl.tick()
        assert not tel.locked
        assert tel.vx == 0.0 and tel.yaw_rate == 0.0

    def test_detector_exception_does_not_crash_the_loop(self):
        scene = Scene()
        ctrl = _controller(scene)

        class BrokenDetector:
            def detect_persons(self, frame):
                raise RuntimeError("inference blew up")

        ctrl.detector = BrokenDetector()
        ctrl.begin(record=False, auto_takeoff=False)
        tel = ctrl.tick()
        assert not tel.locked

    def test_orbit_shot_produces_lateral_velocity(self):
        scene = Scene()
        scene.with_decoy = False
        ctrl = _controller(scene, spec=ShotDirector().parse("orbit him"))
        ctrl.begin(record=False, auto_takeoff=False)
        ctrl.tick()
        assert abs(ctrl.backend.commands[-1]["vy"]) > 0.1

    def test_end_hovers_and_reports(self):
        scene = Scene()
        ctrl = _controller(scene)
        ctrl.begin(record=False, auto_takeoff=False)
        ctrl.tick()
        stats = ctrl.end("test")
        assert ctrl.backend.hovered >= 1
        assert not ctrl.active
        assert stats.frames == 0            # recording was off

    def test_auto_takeoff_only_when_grounded(self):
        scene = Scene()
        backend = StubBackend(scene)
        backend.airborne = False
        ctrl = FollowController(backend=backend, detector=StubDetector(scene))
        ctrl.begin(record=False, auto_takeoff=True)
        assert backend.takeoffs == 1
        ctrl.begin(record=False, auto_takeoff=True)
        assert backend.takeoffs == 1        # already flying, no second takeoff

    def test_camera_pitch_applied_for_low_angle(self):
        scene = Scene()
        scene.with_decoy = False
        ctrl = _controller(scene, spec=ShotDirector().parse("low angle on him"))
        ctrl.begin(record=False, auto_takeoff=False)
        ctrl.tick()
        assert ctrl.backend.pitch is not None
        assert ctrl.backend.pitch < 0

    def test_tick_before_begin_is_inert(self):
        scene = Scene()
        ctrl = _controller(scene)
        tel = ctrl.tick()
        assert tel.tick == 0


# ── ShotRecorder ───────────────────────────────────────────────────────

class TestShotRecorder:
    def test_writes_a_playable_video(self, tmp_path):
        rec = ShotRecorder(out_dir=tmp_path, fps=10, keyframe_interval_s=0.0)
        path = rec.begin("follow_test")
        assert path is not None
        for i in range(12):
            frame = np.full((H, W, 3), i * 10 % 255, np.uint8)
            rec.capture(frame, FrameTelemetry(t=i * 0.1, locked=True, confidence=0.9))
        stats = rec.end()

        assert stats.frames == 12
        assert stats.lock_ratio == pytest.approx(1.0)
        out = next(tmp_path.rglob("follow_test_*.mp4"))
        assert out.stat().st_size > 0

        import cv2

        cap = cv2.VideoCapture(str(out))
        assert cap.isOpened()
        read = 0
        while True:
            ok, _ = cap.read()
            if not ok:
                break
            read += 1
        cap.release()
        assert read >= 10

    def test_telemetry_sidecar_is_valid_jsonl(self, tmp_path):
        rec = ShotRecorder(out_dir=tmp_path, fps=10, keyframe_interval_s=1e9)
        rec.begin("tel")
        rec.capture(np.zeros((H, W, 3), np.uint8), FrameTelemetry(t=0.1, locked=True))
        rec.capture(np.zeros((H, W, 3), np.uint8), FrameTelemetry(t=0.2, locked=False))
        rec.end()

        import json

        path = next(tmp_path.rglob("*_telemetry.jsonl"))
        rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        assert len(rows) == 2
        assert rows[0]["locked"] is True and rows[1]["locked"] is False

    def test_capture_without_frame_is_a_noop(self, tmp_path):
        rec = ShotRecorder(out_dir=tmp_path)
        rec.begin("empty")
        assert rec.capture(None) is False
        rec.end()

    def test_double_begin_closes_previous(self, tmp_path):
        rec = ShotRecorder(out_dir=tmp_path, fps=10)
        rec.begin("a")
        rec.capture(np.zeros((H, W, 3), np.uint8))
        rec.begin("b")
        assert rec.recording
        rec.end()
        assert list(tmp_path.rglob("a_*.mp4"))

    def test_end_without_begin_is_safe(self, tmp_path):
        rec = ShotRecorder(out_dir=tmp_path)
        assert rec.end().frames == 0
