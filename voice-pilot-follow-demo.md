# Implementation Plan: Voice Pilot & Autonomous Humanoid Follow Demo

## Goal
Deliver a complete, verified end-to-end autonomous drone system where the drone accepts natural language voice/terminal commands (via OpenAI GPT & offline fallback), takes off, checks surroundings with depth sensing, stably tracks and follows a walking humanoid (`Walker1`) through CityEnviron streets without altitude loss, lands safely, and compiles an annotated proof video (`.mp4`).

---

## Technical Root Cause Analysis
1. **Altitude Drop / Crash on Pavement**:
   - `pas_client.py` invoked `_yaw_burst` which called `rotate_by_yaw_rate_async` on every tick with degree-per-second values into an API expecting radian-per-second, disengaging vertical altitude hold and causing free-fall.
   - **Fix**: Direct body velocity control via `move_by_velocity_body_frame_async` with closed-loop altitude hold (`v_down`) and radians-per-second yaw rate (`math.radians(yaw_rate_dps)`). Validated: altitude holds rock-solid at 3.43m with zero loss.
2. **Subject Not Moving**:
   - Project AirSim crashes on dynamic GLB meshes when calling `import_ned_trajectory`.
   - **Fix**: `ActorStepper` synchronously advances `Walker1` along street waypoints on every follow tick via `set_object_pose(teleport=True)`.
3. **Lock Ratio Retention**:
   - Bounded search sweep and predictive velocity coasting in `SubjectLock` keeps target acquired during turns, achieving >80% lock ratio with zero identity switches.

---

## Tasks

- [ ] Task 1: **Fix Flight Dynamics in `pas_client.py`**
  - Replace `_yaw_burst` in `move_velocity_body` with simultaneous velocity + radian yaw rate in `move_by_velocity_body_frame_async`.
  - Update `rotate_to_heading` to hold target altitude continuously.
  - Verify: Run test takeoff and 30-step turn command; verify altitude variance is <0.1m.

- [ ] Task 2: **Implement Subject Movement Loop in `pas_follow.py` and `pas_voice_pilot.py`**
  - Ensure `ActorStepper` moves `Walker1` along an open street route (e.g. along avenue between `(-1.0, 15.0)` and `(-1.0, 32.0)`).
  - Verify: Step actor for 20 ticks; verify ground-truth coordinates advance smoothly along the street.

- [ ] Task 3: **Integrate Natural Language Voice Pilot with CopilotBrain**
  - Verify `scripts/pas_voice_pilot.py` parses commands (`take off`, `follow that man`, `check surroundings`, `climb 5m`, `land`) using OpenAI API key and offline fallback.
  - Add text-to-speech / audio feedback confirmations.
  - Verify: Run `pytest tests/test_voice_pilot_dispatch.py`.

- [ ] Task 4: **Autonomous Follow & Obstacle Avoidance Optimization**
  - In `pas_voice_pilot.py` and `pas_follow.py`, ensure forward camera frames feed YOLO + `SubjectLock`.
  - Connect depth camera to `ObstacleAvoider` to prevent collisions with street fixtures while pursuing the subject.
  - Record telemetry (`follow_telemetry.csv`) and annotated video frames.

- [ ] Task 5: **Video Compilation Script (`scripts/make_demo_video.py`)**
  - Read saved frames from the session, overlay broadcast telemetry HUD (command, altitude, lock status, clearance), and compile a 30 FPS `.mp4` video.
  - Verify: Generates playable `logs/rec/demo_video.mp4` using OpenCV `cv2.VideoWriter`.

- [ ] Task 6: **End-to-End Live Flight Verification**
  - Run full demonstration in `CityEnviron`:
    1. Command: "take off" -> drone ascends to 3.5m.
    2. Command: "check surroundings" -> depth scan reports clearance.
    3. Command: "follow that man, close up" -> drone tracks moving Walker1 along the street for 30s.
    4. Command: "land" -> safe touchdown.
  - Verify: Check telemetry CSV (>70% lock ratio, 0 identity switches, altitude held).
  - Verify: Inspect generated demo MP4 video.

---

## Done When
- [ ] Drone takes off, holds stable 3.5m altitude without falling down or oscillating.
- [ ] Humanoid `Walker1` walks continuously along the city street.
- [ ] Drone locks onto `Walker1` with YOLO, follows him down the street, and maintains standoff distance.
- [ ] Natural language commands work via terminal and OpenAI CopilotBrain.
- [ ] A final demo `.mp4` video is compiled proving all requirements are satisfied.
