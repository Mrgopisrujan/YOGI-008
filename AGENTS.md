# AGENTS.md — GarudaOne DroneOS

Read this before touching the repo. It records facts that took cross-reading
`config/`, `garuda/`, `scripts/`, and the simulator to establish. The rest of
`docs/` is mostly research prose — see **Docs are unreliable** below.

Host is Windows 11 + PowerShell. **GNU `make` is not installed**, so the
`Makefile` is documentation, not a workflow. All commands below are native.

---

## 1. Commands

```powershell
# Tests (fast, no simulator, no GPU) — currently 191 passed / 1 skipped
venv\Scripts\python.exe -m pytest -q

# One file / one test
venv\Scripts\python.exe -m pytest tests/test_cinematic_follow.py -v
venv\Scripts\python.exe -m pytest tests/test_digital_twin_physics.py::test_x -v

# Production runtime (asyncio, PX4 via MAVSDK). Falls back to stub telemetry
# if no heartbeat arrives within simulation.yaml px4_sitl.connection_timeout_s.
$env:GARUDA_MODE = "simulation"      # or "hardware" (default)
venv\Scripts\python.exe -m garuda.main

# Digital-twin physics HUD (no drone) — READ-ONLY, safe to run any time
venv\Scripts\python.exe scripts\terminal_dashboard.py --scenario crosswind
venv\Scripts\python.exe scripts\scenarios.py --scenario all --fast
```

The `Makefile` uses POSIX `VAR=value cmd` prefixes, which do **not** work in
PowerShell or `cmd.exe`. Set env vars with `$env:NAME = "value"`.

### Simulation launch order (Valdrada / Boundless NYC, UE 5.8.4)

```powershell
.\scripts\launch_valdrada.bat        # Valdrada UE 5.8.4 server, binds TCP :2000
                                      # Edit VALDRADA_DIR in the bat first.
venv\Scripts\python.exe scripts\valdrada_follow.py --duration 30 --conf 0.15
```

`launch_valdrada.bat` starts the Valdrada server and holds port 2000. Run
exactly one instance — a second instance cannot bind :2000.

`run_city.bat` is the *other* stack — PX4 SITL + Gazebo in WSL2, unrelated to
Unreal. Do not run both sims at once; they fight over MAVLink ports.

### Proving the follow stack works

```powershell
venv\Scripts\python.exe -m pytest tests/test_cinematic_follow.py -v   # control law, no sim
venv\Scripts\python.exe scripts\valdrada_follow.py --duration 25      # wiring, needs Valdrada
```

`valdrada_follow.py` needs no API key and no microphone. It prints a verdict
table: **lock ratio > 30 %, mean |x framing error| < 0.35, identity switches == 0**,
plus whether an mp4 was written.

---

## 2. Two runtimes, and one simulation environment

| Entry point | Transport | Perception | Used by |
|---|---|---|---|
| `garuda/main.py` → `core/orchestrator.py` | PX4 / MAVSDK, `udpin://…:14540` | `perception/detector.py` (PicoDetector / AerialDetector, ncnn or OpenCV-ONNX) | `python -m garuda.main` |
| `scripts/valdrada_follow.py` | Valdrada TCP :2000 | `perception/yolo_detector.py` (ultralytics YOLOv8, `yolov8n.pt`) | `valdrada_follow.py` |
| `scripts/terminal_dashboard.py` | none — synthetic telemetry | `digital_twin/*` physics models | `scenarios.py` |

The old AirSim / CityEnviron / Project AirSim stack has been **removed** — see
the migration note in `docs/planning/UNREAL_SIMULATION_PLAN.md`. GarudaOS now
targets **Valdrada (Boundless NYC)** on **Unreal Engine 5.8.4** as its
simulation environment.

Consequences an agent will otherwise get wrong:

- `garuda/main.py` does **not** import `garuda/digital_twin/*`, `garuda/fdr/`,
  `garuda/gimbal/`, or `garuda/arbiter/safety_limits.py` (the last only via
  `control/cfc_numpy.py`). Editing those changes nothing observable at runtime;
  their only executable coverage is `tests/` and the docstrings.
- `digital_twin/*` is a self-contained physics library. Nothing but
  `terminal_dashboard.py`, `scenarios.py`, and `tests/test_digital_twin_physics.py`
  ever drives it.
- The orchestrator's cinematic states (`ORBIT`, `CHASE`, `REVEAL`) call
  `control/cfc_controller.py`. The Valdrada path implements the same vocabulary
  in `flight/shot_planner.py`. Don't conflate them.

---

## 3. Valdrada wiring

- RPC: `127.0.0.1:2000` (Valdrada simulation server, CARLA-style Python API).
- Vehicle name: there is no named vehicle in Valdrada by default —
  `ValdradaBackend` kinematically teleports a platform actor (a possessed
  quadrotor blueprint if Valdrada ships one, otherwise the spectator camera).
  The platform transform is updated each control tick from the body-frame
  velocity command.
- Camera names are **hardcoded** in `garuda/flight/valdrada_client.py` as the
  nose-mounted RGB + depth pair (`sensor.camera.rgb` /
  `sensor.camera.depth`). Renaming them breaks the client.
- **Coordinate frames:** Valdrada uses ENU (x east, y north, z up). Garuda's
  control law and the `FlightBackend` contract use NED (+z down). `ValdradaBackend`
  converts every value at the boundary — the control loop never sees ENU.
- `garuda/flight/follow_controller.py` holds **no simulator imports** on purpose
  — it talks to a `FlightBackend` protocol. `ValdradaBackend` satisfies it
  without knowing the module exists. Keep it that way; it is what makes the
  control law testable without a simulator.

`garuda/flight/valdrada_client.py` defines a `FlightBackend` `Protocol` with
**no simulator import anywhere in the module**:

```python
class FlightBackend(Protocol):
    def get_forward_camera(self) -> Optional[np.ndarray]: ...
    def get_forward_depth(self) -> Optional[np.ndarray]: ...
    def get_telemetry(self) -> dict[str, Any]: ...
    def is_in_air(self) -> bool: ...
    def takeoff(self, altitude_m: float = 3.0) -> Any: ...
    def move_velocity_body(self, vx, vy, vz, yaw_rate_dps, duration_s=0.2) -> Any: ...
    def hover(self) -> Any: ...
```

Because it is a `Protocol`, nothing validates the method names at import time.
That already caused one silent failure (the old `AirSimClient` defined
`get_front_camera` while the protocol asked for `get_forward_camera`), now
fixed and guarded by
`tests/test_cinematic_follow.py::test_backend_contract_matches_real_client`.
Whenever you add a new `FlightBackend` implementation, run that test.

---

## 4. Pedestrians and cameras (Valdrada)

### People ARE in the map — detection works on them

Unlike CityEnviron (which baked its crowd as static meshes with no actor names),
Valdrada simulates pedestrians, taxis, buses, MTA buses, and emergency vehicles
as addressable actors. YOLO detects them normally.

**Camera pitch sign: negative looks DOWN.** `pitch_deg=+3` pointed the camera at
the sky and rendered the frame upside down. The verified mount is `X = 0.48,
Z = -0.08, Pitch = -3°` (forward of the propeller guards, out of frame).

**YOLO threshold:** NYC pedestrians are small and distant (`h_ratio` ≈ 0.06), so
**0.15–0.25 is the working threshold**, not the 0.35 default. Closer approach is
the single biggest recall win available.

**Never track from ground truth.** The control loop must consume real
`front_center` frames: RGB → YOLO → filter class `person` → normalized centroid
error → control law. Calling actor poses to steer is "cheating" and invalidates
any demo. `SubjectLock` re-establishes identity itself through three gates:
motion-gated centroid proximity → colour-histogram re-ID → largest-box fallback.

**Servoing law** (implemented in `follow_controller.py`):

```
e_x = (cx - W/2) / (W/2)      e_y = (cy - H/2) / (H/2)
yaw_rate = 0.8 · e_x          (rad/s)
v_down   = -0.5 · e_y         (m/s)
```

Forward speed is driven by target bbox height: below ~35 % of frame height
advance at 1.5–2.5 m/s; above ~45 % hold hover.
`shot_planner.py` expresses framing as `target_h_ratio` (0.75 close-up, 0.55
medium, 0.30 wide) plus `standoff_m`, `orbit_rate_dps`, `lateral_bias`,
`lead_room_frac`, `pitch_bias_deg`.

**Obstacle avoidance is a veto, not a planner.** `flight/avoidance.py` fails
safe: on a missing or malformed depth map it scales *down*, never up. Keep that
direction; an inverted fail-safe is a crash.

**Known trap:** any sustained yaw command disengages the altitude hold and the
platform sinks. `ValdradaBackend` pulses yaw in `0.12 s` bursts with a re-hold
between them (measured: 0.15 s × 4 @ 40 dps → +95.6°, −0.02 m altitude).

---

## 5. Cinematic follow stack

`garuda/flight/follow_controller.py` · `shot_planner.py` · `shot_recorder.py` ·
`avoidance.py` and `garuda/perception/subject_lock.py` · `yolo_detector.py` are
the active follow stack, all transport-agnostic.

Pipeline: `frame → YOLO → SubjectLock → ShotSpec → control law → ObstacleAvoider
→ velocity cmd → ShotRecorder`.

- `ShotDirector.parse(text)` maps keywords to `FOLLOW / CHASE / ORBIT / CLOSE_UP
  / WIDE / OVER_SHOULDER / LOW_ANGLE / HIGH_ANGLE / REVEAL`. Deliberately no LLM
  and no network — keep the fallback path working offline.
- `shot_recorder.py` writes `shots/<session>/<shot>_<ts>.mp4` (mp4v) plus a
  `_telemetry.jsonl` sidecar with one row per frame. The sidecar is the
  debugging artifact; treat the mp4 as a by-product. `shots/` and `yolov8n.pt`
  are **not** in `.gitignore`.
- Detection frames *are* the shot frames. Do not add a second fetch path.

---

## 6. Configuration

`garuda/core/config.py` deep-merges, in order, letting later files win:
`drone.yaml` → `models.yaml` → `mission.yaml` → `simulation.yaml`.
`simulation.yaml` is loaded in **both** modes, so `config.get("px4_sitl.…")`
resolves even on hardware. Access with `config.get("dotted.path", default)`.

- **`px4_sitl.connection_url` must be `udpin://0.0.0.0:14540`.** PX4 sends its
  onboard MAVLink stream *to* the API port, so the companion has to listen.
  `udpout://` binds nothing, fails silently, and drops you into stub telemetry
  where takeoff appears to work and no aircraft is involved.
- `simulation.yaml` → `valdrada.*` configures the Valdrada backend (host, port,
  camera settings, takeoff altitude).
- `models.yaml` → `detector.variant` selects the class in
  `main.py::_make_detector`: `picodet` (default) or `aerial` / `yolo`.
- `mission.yaml` → `control.main_loop_hz` (50) is the orchestrator rate.
  `control.pid_fallback` is what actually flies until CfC weights exist.

---

## 7. Voice: input is blocked, output works

### Voice input is blocked at the account level (verified)

The microphone works: 16 input devices, default mic opens, real speech captured
at −38.9 dBFS RMS. The blocker is the API key, not the hardware or the code.

`/v1/models` returns exactly **3 models** for this key, and the only usable one
is `gpt-5-nano`. There is no transcription model:

```
whisper-1              no
gpt-4o-transcribe      no
gpt-4o-mini-transcribe no
gpt-5-nano             YES
```

Posting audio to `/v1/audio/transcriptions` returns:

```
403  Project `proj_dN7OcSonYIiVu9RORQKVZ80L` does not have access to model `whisper-1`
     type: model_not_found
```

So **speech-to-text cannot work on this key** until the project is granted a
transcription model. Text-in is unaffected: `CopilotBrain.understand_command`
handles every command offline, and `_query_gpt` works for the non-audio cases.
When adding STT, check `/v1/models` first rather than assuming a 403 is a bug.

Verified working offline, no key needed (`tests/test_voice_follow_intent.py`,
53 tests): wake-word stripping, 20+ follow phrasings → `FOLLOW_PERSON`, shot
modifiers (`close up` → framing 72% / standoff 2.2 m), spoken number words,
duration parsing and clamping, and non-follow commands not being hijacked.

### TTS

`speak()` falls back to Windows SAPI via `win32com`, so voice-out works without
`SMALLEST_API_KEY`. Smallest.ai TTS is untested — treat as unverified.

---

## 8. Dependencies

`requirements.txt` targets the Raspberry Pi 5 and is **not** a description of
this host's venv. Installed here but absent from it: `python-dotenv`,
`speech_recognition`, `pyaudio`, `websockets`, `fastapi`. Absent here and needed
by some code paths: `ncnn`, `ncps`, `llama_cpp`, `faster_whisper`, `piper`,
`sounddevice`, `openwakeword`, `openai`.

Practical results on this host:

- `PicoDetector` / `AerialDetector` load the **stub** backend and emit synthetic
  detections. Never treat their output as perception evidence.
- `FlightController.load_cfc_model()` returns `False` and the controller stays
  in PID fallback mode (real control, `control.pid_fallback` gains).
- `ToolRouter.load_needle_model()` returns `False`; `main.py` ignores the return
  value, so the deterministic parser handles commands.
- `CopilotBrain` always takes its offline regex branch because `openai` is not
  installed. Voice degrades to Windows SAPI.

**Do not add a dependency to `requirements.txt` and assume the feature is live**
— verify with `venv\Scripts\python.exe -c "import <mod>"`, and confirm the
caller degrades safely rather than only having a happy path.

`.env` (gitignored) supplies `OPENAI_API_KEY` and `SMALLEST_API_KEY`; see
`.env.example`. Every consumer must keep working without them.

---

## 9. Docs are unreliable — verify against code

`docs/CURRENT_CAPABILITIES.md`, `docs/DOCUMENTATION_INDEX.md`, and
`docs/DOCUMENTATION_POLICY.md` describe a **different, much larger system**.
None of that exists in this repo. Trust, in order: the code, the tests,
`config/`, then `docs/plan/` and `docs/chats/` for the reasoning behind recent
decisions. `README.md` and this file are the only prose that tracks the code.

---

## 10. Conventions and safety

- Python 3.11 (`pyproject.toml` `requires-python`). Type hints on public
  signatures; `from __future__ import annotations` in newer modules.
- Async everywhere in the runtime path; a blocking call in a loop will stall
  the 50 Hz orchestrator. `main.py` handles `SIGTERM` in a `try/except` because
  Windows lacks it.
- Logging via `garuda/utils/logger.py::get_logger(name)`. Scripts that predate
  the package use `logging.getLogger` instead; match the file you are in.
- Never let a failure path become permissive. Stubs, absent depth, absent
  detections, and lost heartbeats must all reduce authority (hover, slow down,
  veto) — never widen it. Every subsystem here has a documented "fails closed"
  contract; keep them.
- Physical flight is out of scope. The airframe, battery, and PX4 hardware in
  `config/drone.yaml` are design targets, and no flight in this repo has been
  physically qualified. `scripts/gps_denied_test.py` must be run inside WSL
  against PX4 SITL and it *arms and flies* a simulated vehicle — confirm the
  target before running it.
- Branch is `main`; remote is `Mrgopisrujan/YOGI-008`. Keep commits
  behaviour-scoped.
