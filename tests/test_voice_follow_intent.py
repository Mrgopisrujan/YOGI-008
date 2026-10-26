"""
Tests for the voice -> intent -> shot path.

The contract under test is the user's actual goal: say "hey garuda follow
that man" and get a FOLLOW_PERSON intent carrying a usable cinematic shot.

Every test here runs with the GPT call stubbed out, which is deliberate: the
flagship command must resolve offline. If a change ever makes the follow path
depend on the network, these tests fail — which is the point.
"""

from __future__ import annotations

import pytest

import garuda.brain.copilot_brain as cb
from garuda.brain.copilot_brain import (
    CopilotBrain,
    is_follow_request,
    strip_wake_word,
)


@pytest.fixture(autouse=True)
def offline_brain(monkeypatch):
    """A brain that can never reach the network."""
    monkeypatch.setattr(
        CopilotBrain, "_query_gpt", lambda self, text: {"action": "UNKNOWN"}
    )
    return CopilotBrain(openai_api_key="", smallest_api_key="")


# ── Wake word ──────────────────────────────────────────────────────────

class TestWakeWord:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("hey garuda follow that man", "follow that man"),
            ("Hey Garuda, follow that man", "follow that man"),
            ("garuda follow that man", "follow that man"),
            ("Garuda, follow that man", "follow that man"),
            ("okay garuda follow that man", "follow that man"),
            ("follow that man", "follow that man"),
            ("", ""),
        ],
    )
    def test_strips_wake_phrase(self, raw, expected):
        assert strip_wake_word(raw) == expected

    def test_command_text_handed_to_shot_planner_is_clean(self, offline_brain):
        d = offline_brain.understand_command("hey garuda, follow that man")
        assert d["command"] == "follow that man"
        assert not d["command"].startswith(",")


# ── Follow intent ──────────────────────────────────────────────────────

class TestFollowIntent:
    @pytest.mark.parametrize(
        "utterance",
        [
            "hey garuda follow that man",
            "follow that man",
            "follow the man",
            "track that guy",
            "chase that woman",
            "escort that person",
            "stay with him",
            "follow me",
            "follow him",
            "orbit him",
            "shoot her",
            "keep following that pedestrian",
        ],
    )
    def test_recognised_as_follow(self, utterance, offline_brain):
        assert is_follow_request(strip_wake_word(utterance))
        assert offline_brain.understand_command(utterance)["action"] == "FOLLOW_PERSON"

    @pytest.mark.parametrize(
        "utterance",
        [
            "stop",
            "land now",
            "return to launch",
            "climb 10 meters",
            "check surroundings",
            "reset",
            "take off",
        ],
    )
    def test_non_follow_commands_not_hijacked(self, utterance, offline_brain):
        assert not is_follow_request(strip_wake_word(utterance))
        assert offline_brain.understand_command(utterance)["action"] != "FOLLOW_PERSON"

    def test_resolves_offline_without_api_key(self, offline_brain):
        d = offline_brain.understand_command("hey garuda follow that man")
        assert d["offline"] is True
        assert d["action"] == "FOLLOW_PERSON"

    def test_identity_is_visual_not_actor_name(self, offline_brain):
        """The actor in the sim is called Pedestrian_N; the user said 'that man'."""
        d = offline_brain.understand_command("follow that man")
        assert d["target_name"] == ""      # resolved by the camera, not the scene graph

    def test_duration_parsed_from_speech(self, offline_brain):
        assert offline_brain.understand_command("follow that man for 45 seconds")["duration_s"] == 45.0

    def test_duration_is_clamped(self, offline_brain):
        d = offline_brain.understand_command("follow that man for 99999 seconds")
        assert d["duration_s"] == 300.0

    def test_default_duration_when_unspecified(self, offline_brain):
        assert offline_brain.understand_command("follow that man")["duration_s"] == 20.0


# ── Shot selection through the voice path ──────────────────────────────

class TestVoiceShotSelection:
    @pytest.mark.parametrize(
        "utterance,shot",
        [
            ("follow that man", "follow"),
            ("follow that man close up", "close_up"),
            ("orbit him", "orbit"),
            ("chase that man", "chase"),
            ("follow him in a wide shot", "wide"),
            ("shoot him from a low angle", "low_angle"),
        ],
    )
    def test_spoken_modifiers_pick_the_shot(self, utterance, shot, offline_brain):
        d = offline_brain.understand_command(utterance)
        assert d["shot"] == shot
        assert d["shot_spec"].name == shot

    def test_recording_is_on_by_default(self, offline_brain):
        assert offline_brain.understand_command("follow that man")["record"] is True

    def test_standoff_requested_in_speech_is_honoured(self, offline_brain):
        spec = offline_brain.understand_command("follow that man keep 3 metres away")["shot_spec"]
        assert spec.standoff_m == pytest.approx(3.0)


# ── Other command regression cover ─────────────────────────────────────

class TestOtherCommands:
    @pytest.mark.parametrize(
        "utterance,action",
        [
            ("stop", "HOVER"),
            ("land now", "LAND"),
            ("reset", "RESET"),
            ("return to launch", "RTL"),
            ("check surroundings", "CHECK_SURROUNDINGS"),
            ("climb 10 meters", "CLIMB"),
        ],
    )
    def test_baseline_commands_still_parse(self, utterance, action, offline_brain):
        assert offline_brain.understand_command(utterance)["action"] == action

    def test_compound_takeoff_wins_over_trailing_hover(self, offline_brain):
        d = offline_brain.understand_command("take off and hover at four meters")
        assert d["action"] == "TAKEOFF"
        assert d["altitude_m"] == pytest.approx(4.0)

    def test_spoken_number_words_are_understood(self, offline_brain):
        assert offline_brain.understand_command("take off and hover at six meters")["altitude_m"] == 6.0


# ── The garuda/voice pipeline's own parser (main.py path) ──────────────

class TestVoicePipelineIntentParser:
    def _parser(self):
        from garuda.core.config import Config
        from garuda.voice.pipeline import IntentParser

        return IntentParser(Config())

    def test_follow_that_man_maps_to_follow(self):
        assert self._parser().classify("follow that man") == "follow"

    def test_wake_word_does_not_break_matching(self):
        assert self._parser().classify("hey garuda follow that man") == "follow"

    def test_longer_phrase_wins_over_shorter(self):
        assert self._parser().classify("stop recording") == "recording_stop"
        assert self._parser().classify("stop") == "stop"

    def test_unknown_utterance_returns_none(self):
        assert self._parser().classify("what is the weather like") is None


def test_follow_triggers_are_exported():
    """Guard against a refactor silently emptying the trigger list."""
    assert len(cb.FOLLOW_TRIGGERS) >= 10
    assert "follow me" in cb.FOLLOW_TRIGGERS
