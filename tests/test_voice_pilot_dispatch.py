"""Tests for the unified voice/terminal pilot command dispatch.

Verifies that CopilotBrain correctly routes spoken or typed commands to the
expected flight actions, including the follow-person shot detection path.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from garuda.brain.copilot_brain import CopilotBrain, is_follow_request, strip_wake_word


# ── CopilotBrain.understand_command (offline, no OpenAI key) ──────────

@pytest.fixture
def brain():
    """CopilotBrain with no API key = pure offline keyword parser."""
    return CopilotBrain(openai_api_key="", smallest_api_key="")


class TestOfflineCommandRouting:
    """Verify the offline fallback routes commands correctly."""

    def test_takeoff(self, brain):
        res = brain.understand_command("take off")
        assert res["action"] == "TAKEOFF"

    def test_takeoff_with_altitude(self, brain):
        res = brain.understand_command("take off and hover at 6 meters")
        assert res["action"] == "TAKEOFF"
        assert res.get("altitude_m") == 6.0

    def test_land(self, brain):
        res = brain.understand_command("land")
        assert res["action"] == "LAND"

    def test_hover(self, brain):
        res = brain.understand_command("hover")
        assert res["action"] == "HOVER"

    def test_stop(self, brain):
        res = brain.understand_command("stop")
        assert res["action"] == "HOVER"

    def test_rtl(self, brain):
        res = brain.understand_command("return to launch")
        assert res["action"] == "RTL"

    def test_forward(self, brain):
        res = brain.understand_command("fly forward 10 meters")
        assert res["action"] == "MOVE_FORWARD"
        assert res.get("distance_m") == 10.0

    def test_backward(self, brain):
        res = brain.understand_command("move backward")
        assert res["action"] == "MOVE_BACKWARD"

    def test_left(self, brain):
        res = brain.understand_command("go left 5 meters")
        assert res["action"] == "MOVE_LEFT"
        assert res.get("distance_m") == 5.0

    def test_right(self, brain):
        res = brain.understand_command("slide right")
        assert res["action"] == "MOVE_RIGHT"

    def test_climb(self, brain):
        res = brain.understand_command("climb 8 meters")
        assert res["action"] == "CLIMB"
        assert res.get("altitude_gain_m") == 8.0

    def test_descend(self, brain):
        res = brain.understand_command("descend 3 meters")
        assert res["action"] == "DESCEND"

    def test_check_surroundings(self, brain):
        res = brain.understand_command("check surroundings")
        assert res["action"] == "CHECK_SURROUNDINGS"

    def test_reset(self, brain):
        res = brain.understand_command("reset")
        assert res["action"] == "RESET"

    def test_emergency(self, brain):
        res = brain.understand_command("emergency")
        assert res["action"] == "EMERGENCY"


class TestFollowDetection:
    """Verify the follow-person fast path."""

    def test_follow_that_man(self, brain):
        res = brain.understand_command("follow that man")
        assert res["action"] == "FOLLOW_PERSON"

    def test_follow_person_close_up(self, brain):
        res = brain.understand_command("follow that man, close up")
        assert res["action"] == "FOLLOW_PERSON"
        assert res["shot"] == "close_up"

    def test_follow_orbit(self, brain):
        res = brain.understand_command("orbit him")
        assert res["action"] == "FOLLOW_PERSON"
        assert res["shot"] == "orbit"

    def test_follow_from_left(self, brain):
        res = brain.understand_command("follow that man from the left")
        assert res["action"] == "FOLLOW_PERSON"

    def test_follow_with_duration(self, brain):
        res = brain.understand_command("follow that man for 30 seconds")
        assert res["action"] == "FOLLOW_PERSON"
        assert res["duration_s"] == 30.0

    def test_film_me(self, brain):
        res = brain.understand_command("film me")
        assert res["action"] == "FOLLOW_PERSON"


class TestWakeWordStripping:
    """Verify wake-word prefix is removed."""

    def test_strip_hey_garuda(self):
        assert strip_wake_word("hey garuda, follow that man") == "follow that man"

    def test_strip_garuda(self):
        assert strip_wake_word("garuda stop") == "stop"

    def test_strip_nothing(self):
        assert strip_wake_word("take off") == "take off"


class TestIsFollowRequest:
    """Verify the follow-request detector."""

    def test_follow_that_man(self):
        assert is_follow_request("follow that man") is True

    def test_track_the_person(self):
        assert is_follow_request("track the person") is True

    def test_follow_me(self):
        assert is_follow_request("follow me") is True

    def test_orbit_him(self):
        assert is_follow_request("orbit him") is True

    def test_not_follow(self):
        assert is_follow_request("take off") is False

    def test_not_follow_climb(self):
        assert is_follow_request("climb 10 meters") is False


class TestCompoundCommands:
    """Compound commands: the leading verb should win."""

    def test_takeoff_and_hover(self, brain):
        res = brain.understand_command("take off and hover at 4 meters")
        assert res["action"] == "TAKEOFF"
        assert res.get("altitude_m") == 4.0

    def test_turn_and_move(self, brain):
        res = brain.understand_command("turn left 45 degrees and go 5 meters")
        # Should be either TURN_AND_MOVE or ROTATE depending on parsing
        assert res["action"] in ("TURN_AND_MOVE", "ROTATE")
