"""
GarudaOS — AI Copilot & Speech Brain
====================================
Integrates:
  1. OpenAI GPT API (GPT-4o / GPT-4o-mini) for deep command comprehension,
     spatial reasoning, and autonomous flight planning.
  2. Smallest.ai Lightning TTS for voice response generation (with offline
     Windows SAPI fallback).
  3. Direct fast-path regex intent parser for zero-latency emergency commands.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import urllib.request
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

log = logging.getLogger("copilot_brain")

FAST_KEYWORDS = {
    "RTL": ["return home", "return to launch", "go home", "come back", "rtl", "return to base"],
    "CHECK_SURROUNDINGS": ["check surroundings", "surroundings", "scan surroundings", "scan", "check obstacles", "obstacle scan", "radar"],
    "RESET": ["reset", "respawn", "reset drone", "reposition", "restart simulation"],
    "STOP": ["stop", "halt", "hold", "hover", "brake", "pause", "wait"],
    "TAKEOFF": ["takeoff", "take off", "lift off"],
    "LAND": ["land", "touchdown", "come down", "bring it down"],
    "EMERGENCY": ["emergency", "abort", "kill motors", "mayday", "disarm"],
}

# Subject-following is matched with a dedicated pass rather than a flat
# keyword list: the trigger words are broad ("follow that man") but the
# instruction that follows carries the shot ("close up", "from the left",
# "keep 3 metres away"), which must survive into the flight command.
SUBJECT_REF = r"(?:that|the|this|my)?\s*(?:man|woman|person|guy|lady|pedestrian|human|target|subject|dude|folks?)"
# Bare pronouns refer to whoever the operator is already looking at, so they
# are follow triggers on their own ("orbit him", "get closer").
PRONOUN_REF = r"(?:him|her|them|him\/her|that one|the one)"
FOLLOW_TRIGGERS = [
    rf"follow\s+{SUBJECT_REF}",
    rf"track\s+{SUBJECT_REF}",
    rf"chase\s+{SUBJECT_REF}",
    rf"escort\s+{SUBJECT_REF}",
    rf"pursue\s+{SUBJECT_REF}",
    rf"stay\s+with\s+{SUBJECT_REF}",
    rf"keep\s+following\s+{SUBJECT_REF}",
    rf"(?:orbit|circle)\s+{PRONOUN_REF}",
    rf"(?:shoot|film|record)\s+{PRONOUN_REF}",
    rf"(?:follow|track|chase|escort)\s+{PRONOUN_REF}",
    rf"(?:stay|come)\s+with\s+{PRONOUN_REF}",
    "follow me",
    "track me",
    "follow him",
    "follow her",
    "follow them",
    "come with me",
    "stay with me",
    "follow behind me",
    "stay behind me",
    "shoot me",
    "film me",
]

# Words that mean "keep doing the follow shot", not "start a new command".
FOLLOW_SHOT_HINTS = [
    "close up", "closeup", "tight", "portrait", "wide", "establishing",
    "orbit", "circle", "chase", "reveal", "pull back", "over the shoulder",
    "over shoulder", "low angle", "high angle", "from the left", "from the right",
    "on the left", "on the right", "record", "film", "shoot", "drone shot",
]

# Wake-word / filler stripped before intent matching.
WAKE_PREFIXES = [
    r"^\s*(?:hey\s+|ok(?:ay)?\s+|computer\s+|garuda\s*)+",
    r"^\s*(?:garuda|hey garuda)\s*[,!\.]?\s*",
]


def strip_wake_word(text: str) -> str:
    """
    Remove a leading 'hey garuda' style wake phrase and tidy the punctuation
    it leaves behind, so the shot planner never sees ", follow that man".
    """
    out = (text or "").strip()
    for pat in WAKE_PREFIXES:
        out = re.sub(pat, "", out, flags=re.IGNORECASE)
    return out.strip().strip(",!.;:").strip()


# Leading verbs that win over a trailing verb in a compound utterance.
# Ordered longest-phrase-first so "take off" beats a bare "take".
COMPOUND_HEAD_VERBS = [
    ("take off", "TAKEOFF"),
    ("takeoff", "TAKEOFF"),
    ("lift off", "TAKEOFF"),
    ("touch down", "LAND"),
    ("come down", "DESCEND"),
    ("bring it down", "DESCEND"),
    ("go down", "DESCEND"),
    ("go up", "CLIMB"),
    ("ascend", "CLIMB"),
    ("climb", "CLIMB"),
    ("descend", "DESCEND"),
]

# Spoken number words: STT transcribes "4 m" as "four meters" often enough
# that ignoring them silently drops the operator's altitude request.
_SPOKEN_NUMBERS = {
    "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0,
    "six": 6.0, "seven": 7.0, "eight": 8.0, "nine": 9.0, "ten": 10.0,
    "eleven": 11.0, "twelve": 12.0, "fifteen": 15.0, "twenty": 20.0,
    "twenty five": 25.0, "thirty": 30.0, "forty": 40.0, "fifty": 50.0,
}


def _spoken_number(text: str) -> Optional[float]:
    """First numeric quantity in the utterance, digits or number words."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m\b|meters?\b|metres?\b|feet\b|ft\b|deg|degrees?|°)", text)
    if not m:
        m = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    for word in sorted(_SPOKEN_NUMBERS, key=len, reverse=True):
        if re.search(r"\b" + word + r"\b", text):
            return _SPOKEN_NUMBERS[word]
    return None


def is_follow_request(text: str) -> bool:
    """True when the utterance asks to follow/track/escort a subject."""
    low = strip_wake_word(text).lower()
    return any(re.search(r"\b" + t + r"\b", low) for t in FOLLOW_TRIGGERS)



class CopilotBrain:
    """Unified AI Flight Copilot with GPT-4o and Speech Synthesis."""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        smallest_api_key: Optional[str] = None
    ):
        self.openai_key = openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        self.smallest_key = smallest_api_key or os.environ.get("SMALLEST_API_KEY", "")
        self.audio_cache: dict[str, bytes] = {}
        self.is_speaking = False

    def understand_command(self, user_text: str) -> dict[str, Any]:
        """
        Parses user intent using OpenAI GPT as the primary natural language brain.
        Supports complex spatial reasoning, compound angles, colloquial speech, and multi-step tasks.
        Falls back to rule-based parser only if offline or API key is unavailable.
        """
        clean_text = user_text.lower().strip()
        if not clean_text:
            return {"action": "NONE"}

        # 0. Subject follow is handled first and offline, on purpose: it is
        # the flagship command and it must never depend on network latency.
        # The full utterance is passed through as `command` so the shot
        # planner can read modifiers ("close up", "from the left").
        spoken = strip_wake_word(user_text)
        if is_follow_request(spoken):
            from garuda.flight.shot_planner import ShotDirector

            spec = ShotDirector().parse(spoken)
            out = {
                "action": "FOLLOW_PERSON",
                "command": spoken,
                "shot": spec.name,
                "shot_spec": spec,
                "target_name": "",          # resolved visually, not by actor name
                "duration_s": 20.0,
                "record": True,
                "offline": True,
            }
            m = re.search(r"(\d+(?:\.\d+)?)\s*seconds?\b", spoken)
            if m:
                try:
                    out["duration_s"] = max(3.0, min(300.0, float(m.group(1))))
                except ValueError:
                    pass
            return out

        # 1. Instant emergency & reflex stops (sub-millisecond safety brake)
        if clean_text in ["stop", "halt", "hover", "brake", "hold", "stay"]:
            return {"action": "HOVER", "direct": True}
        if clean_text in ["land now", "emergency land"]:
            return {"action": "LAND", "direct": True}
        if clean_text in ["reset", "respawn"]:
            return {"action": "RESET", "direct": True}

        # 2. Primary Natural Language Brain: OpenAI GPT (parses all natural language & angles)
        if self.openai_key:
            res = self._query_gpt(clean_text)
            if res.get("action") not in ["UNKNOWN", "NONE"]:
                return res

        # 3. Offline rule-based fallback (if OpenAI key missing or network fails)
        log.info("[CopilotBrain] Running offline fallback parser...")

        # 3a. Compound commands: "take off and hover at four meters" must be a
        # TAKEOFF, not the HOVER that the trailing verb would otherwise select.
        # The leading verb is the operator's primary intent.
        for verb, action in COMPOUND_HEAD_VERBS:
            if re.search(r"\b" + verb + r"\b", clean_text):
                alt = _spoken_number(clean_text)
                out = {"action": action}
                if action == "TAKEOFF":
                    out["altitude_m"] = alt if alt else 2.4
                if alt and action == "CLIMB":
                    out["altitude_gain_m"] = alt
                if alt and action == "DESCEND":
                    out["altitude_drop_m"] = alt
                return out

        # Compound angular navigation ("turn left 45 deg for 5m", "left to an angle of 45 degrees for 5 metres")
        angle_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:deg|degrees?|°)\b', clean_text)
        dist_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:m|meters|metres|meter|metre)\b', clean_text)

        if angle_match and dist_match:
            angle_val = float(angle_match.group(1))
            dist_val = float(dist_match.group(1))
            is_left = "left" in clean_text
            yaw_change = -angle_val if is_left else angle_val
            return {"action": "TURN_AND_MOVE", "yaw_change_deg": yaw_change, "distance_m": dist_val}

        if angle_match and any(k in clean_text for k in ["turn", "rotate", "face", "heading", "angle"]):
            angle_val = float(angle_match.group(1))
            is_left = "left" in clean_text
            yaw_change = -angle_val if is_left else angle_val
            return {"action": "ROTATE", "yaw_change_deg": yaw_change}

        num_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:m|meters|metres|meter|metre|feet|ft)\b', clean_text)
        if not num_match:
            num_match = re.search(r'\b(\d+(?:\.\d+)?)\b(?!\s*(?:deg|degree|degrees|°))', clean_text)
        val = float(num_match.group(1)) if num_match else None

        if any(k in clean_text for k in ["rooftop", "roof", "skyline", "high altitude"]):
            target_alt = val if val and val > 10 else 25.0
            return {"action": "INSPECT_ROOFTOP", "altitude_m": target_alt}

        if any(k in clean_text for k in ["ground", "downward", "street scan", "down camera", "look down"]):
            return {"action": "INSPECT_GROUND"}

        if any(k in clean_text for k in ["climb", "ascend", "go up", "higher", "altitude"]):
            gain = val if val else 5.0
            return {"action": "CLIMB", "altitude_gain_m": gain}

        if any(k in clean_text for k in ["descend", "go down", "lower"]):
            drop = val if val else 3.0
            return {"action": "DESCEND", "altitude_drop_m": drop}

        if any(k in clean_text for k in ["forward", "ahead", "straight", "front"]):
            dist = val if val else 10.0
            return {"action": "MOVE_FORWARD", "distance_m": dist}

        if any(k in clean_text for k in ["backward", "back", "reverse"]):
            dist = val if val else 10.0
            return {"action": "MOVE_BACKWARD", "distance_m": dist}

        if "left" in clean_text:
            dist = val if val else 5.0
            return {"action": "MOVE_LEFT", "distance_m": dist}

        if "right" in clean_text:
            dist = val if val else 5.0
            return {"action": "MOVE_RIGHT", "distance_m": dist}

        for action, patterns in FAST_KEYWORDS.items():
            for p in patterns:
                if re.search(r'\b' + re.escape(p) + r'\b', clean_text):
                    if action == "TAKEOFF" and val:
                        return {"action": action, "altitude_m": val}
                    return {"action": action, "direct": True}

        return {"action": "UNKNOWN", "raw_text": user_text}

    def _query_gpt(self, text: str) -> dict[str, Any]:
        """Calls OpenAI Chat Completions API with rich natural language drone flight schema."""
        system_prompt = (
            "You are GarudaOS, an AI drone flight copilot in Unreal Engine simulation. "
            "Analyze the operator's natural language command and return a single valid JSON object representing the action.\n\n"
            "Available actions:\n"
            "- 'TAKEOFF' (altitude_m: float)\n"
            "- 'LAND'\n"
            "- 'HOVER'\n"
            "- 'RTL' (return to launchpad origin)\n"
            "- 'MOVE_FORWARD' (distance_m: float, speed_mps: float)\n"
            "- 'MOVE_BACKWARD' (distance_m: float, speed_mps: float)\n"
            "- 'MOVE_LEFT' (distance_m: float)\n"
            "- 'MOVE_RIGHT' (distance_m: float)\n"
            "- 'CLIMB' (altitude_gain_m: float)\n"
            "- 'DESCEND' (altitude_drop_m: float)\n"
            "- 'ROTATE' (yaw_change_deg: float, negative=left, positive=right)\n"
            "- 'TURN_AND_MOVE' (yaw_change_deg: float, distance_m: float, speed_mps: float)\n"
            "- 'INSPECT_ROOFTOP' (building_name: str, altitude_m: float)\n"
            "- 'INSPECT_GROUND' (duration_s: float)\n"
            "- 'FOLLOW_PERSON' (target_name: str, duration_s: float)\n"
            "- 'CHECK_SURROUNDINGS'\n"
            "- 'RESET'\n\n"
            "Examples:\n"
            "- 'left to an angle of 45 degrees for 5 metres' -> {\"action\": \"TURN_AND_MOVE\", \"yaw_change_deg\": -45.0, \"distance_m\": 5.0}\n"
            "- 'turn right 90 degrees and go 10 meters' -> {\"action\": \"TURN_AND_MOVE\", \"yaw_change_deg\": 90.0, \"distance_m\": 10.0}\n"
            "- 'follow the person walking on the sidewalk' -> {\"action\": \"FOLLOW_PERSON\", \"target_name\": \"Pedestrian_1\", \"duration_s\": 15.0}\n"
            "- 'what is in front of me' or 'scan surroundings' -> {\"action\": \"CHECK_SURROUNDINGS\"}\n"
            "- 'take off and hover at 4m' -> {\"action\": \"TAKEOFF\", \"altitude_m\": 4.0}\n"
            "- 'return to launch' -> {\"action\": \"RTL\"}\n"
            "Respond ONLY with raw JSON."
        )

        model_name = os.environ.get("OPENAI_MODEL", "gpt-5-nano")
        try:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json"
                },
                data=json.dumps({
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ],
                    "response_format": {"type": "json_object"}
                }).encode("utf-8")
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                result_json = data["choices"][0]["message"]["content"]
                parsed = json.loads(result_json)
                log.info(f"[GPT Natural Language Decision]: {parsed}")
                # Normalize action string
                act = str(parsed.get("action", "")).upper()
                if "TURN" in act and "MOVE" in act or act == "TURN_AND_MOVE":
                    parsed["action"] = "TURN_AND_MOVE"
                elif "ROTATE" in act or "TURN" in act or "YAW" in act:
                    parsed["action"] = "ROTATE"
                elif "FORWARD" in act or "CRUISE" in act or "AHEAD" in act:
                    parsed["action"] = "MOVE_FORWARD"
                elif "BACK" in act or "REVERSE" in act:
                    parsed["action"] = "MOVE_BACKWARD"
                elif "ROOF" in act or "SKYLINE" in act:
                    parsed["action"] = "INSPECT_ROOFTOP"
                elif "GROUND" in act or "DOWN" in act and "MOVE" not in act:
                    parsed["action"] = "INSPECT_GROUND"
                elif "FOLLOW" in act or "TRACK" in act or "PURSUE" in act or "ESCORT" in act:
                    parsed["action"] = "FOLLOW_PERSON"
                elif "SURROUND" in act or "RADAR" in act or "SCAN" in act:
                    parsed["action"] = "CHECK_SURROUNDINGS"
                elif "RTL" in act or "RETURN" in act or "HOME" in act:
                    parsed["action"] = "RTL"
                elif "LAND" in act:
                    parsed["action"] = "LAND"
                elif "TAKEOFF" in act or "LAUNCH" in act or "FLY" in act:
                    parsed["action"] = "TAKEOFF"
                else:
                    parsed["action"] = act
                return parsed
        except Exception as e:
            log.warning(f"GPT API query failed: {e}. Falling back to offline logic.")
            return {"action": "UNKNOWN", "raw_text": text}

    def speak(self, text: str):
        """Asynchronously synthesizes and plays speech through speakers."""
        if not text:
            return

        def _play():
            try:
                self.is_speaking = True
                audio_bytes = self._generate_smallest_tts(text) if self.smallest_key else None

                if audio_bytes:
                    try:
                        import winsound
                        winsound.PlaySound(audio_bytes, winsound.SND_MEMORY)
                        return
                    except Exception:
                        pass

                # Offline Windows SAPI fallback (non-blocking, full audio without cutoff)
                try:
                    clean_text = text.replace("'", "").replace('"', "").replace("\n", " ")
                    try:
                        import win32com.client
                        speaker = win32com.client.Dispatch("SAPI.SpVoice")
                        speaker.Speak(clean_text, 1)  # 1 = SVSFlagsAsync (instant non-blocking)
                        return
                    except Exception:
                        pass

                    if sys.platform == "win32":
                        # Launch via Popen in background so it finishes talking and never gets cut off
                        subprocess.Popen(
                            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             f"(New-Object -ComObject SAPI.SpVoice).Speak('{clean_text}')"],
                            creationflags=0x08000000,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                except Exception:
                    pass
            finally:
                self.is_speaking = False

        threading.Thread(target=_play, daemon=True).start()

    def _generate_smallest_tts(self, text: str) -> Optional[bytes]:
        """Calls Smallest.ai Lightning TTS API."""
        if not self.smallest_key:
            return None
        try:
            req = urllib.request.Request(
                "https://api.smallest.ai/waves/v1/tts",
                headers={
                    "Authorization": f"Bearer {self.smallest_key}",
                    "Content-Type": "application/json",
                    "Accept": "audio/wav"
                },
                data=json.dumps({
                    "text": text,
                    "voice_id": "meher",
                    "model": "lightning_v3.1_pro",
                    "sample_rate": 24000,
                    "output_format": "wav"
                }).encode("utf-8")
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                return resp.read()
        except Exception as e:
            log.debug(f"Smallest TTS failed: {e}")
            return None
