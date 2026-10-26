# AGENTS.md — GarudaOne DroneOS

Read this before touching the repo. It records facts that took cross-reading
`config/`, `garuda/`, `scripts/`, and the simulator to establish. The rest of
`docs/` is mostly research prose — see **Docs are unreliable** below.

Host is Windows 11 + PowerShell. **GNU `make` is not installed**, so the
`Makefile` is documentation, not a workflow. All commands below are native.

---

## 1. Commands

```powershell
# Tests (fast, no simulator, no hardware) — currently 191 passed / 1 skipped
venv\Scripts\python.exe -m pytest -q

# One file / one test
venv\Scripts\python.exe -m pytest tests/test_cinematic_follow.py -v
venv\Scripts\python.exe -m pytest tests/test_digital_twin_physics.py::test_x -v

# SITL-marked tests need PX4 SITL already running (marker defined in pyproject.toml)
venv\Scripts\python.exe -m pytest -m sitl -v

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

### Simulation launch order

```powershell
.\launch_city_sim.bat        # Unreal CityEnviron.exe, hardcoded to
                             # D:\Aatonovaz\Garuda\CityEnviron\WindowsNoEditor
.\spawn_pedestrians.bat      # 3 rigged pedestrians walking sidewalks
.\run_unreal.bat             # voice copilot (microphone + GPT + TTS)
```

Order matters: pedestrians must exist before the follow loop, or the subject
lock has nothing to lock onto. `spawn_pedestrians.bat` runs until Ctrl+C.

`.\run_city.bat` is the *other* stack — PX4 SITL + Gazebo in WSL2, unrelated to
Unreal. Do not run both sims at once; they fight over MAVLink ports.

### Proving the follow stack works

```powershell
venv\Scripts\python.exe -m pytest tests/test_cinematic_follow.py -v   # control law, no sim
venv\Scripts\python.exe scripts\verify_follow_shot.py --duration 25  # wiring, needs sim
```

`verify_follow_shot.py` needs no API key and no microphone. It prints a verdict
table: **lock ratio > 30 %, mean |x framing error| < 0.35, identity switches == 0**,
plus whether an mp4 was written. If lock ratio is 0 %, the subject is
undetectable — see **Pedestrians and cameras** below.

---

## 2. Two runtimes, and two incompatible AirSim stacks

### Root cause of the spawn crash: client/server fork mismatch

This is the single most important thing to know about the sim layer. The repo
carries **two different AirSim client libraries**, on **two incompatible
transports**, and `CityEnviron.exe` only speaks one of them.

| | `airsim` 1.8.1 | `projectairsim` 1.0.2 (IAMAI fork) |
|---|---|---|
| Transport | msgpack-rpc, port **41451** | NNG, ports **8989** / **8990** |
| Spawn API | `VehicleClient.simSpawnObject(name, asset, pose, scale, physics_enabled, is_blueprint)` | `World.spawn_object(name, asset_path, transform, scale, enable_physics)` |
| Matches server? | **Yes** — CityEnviron listens on 41451 | No — nothing listens on 8989/8990 |

- `garuda/flight/airsim_client.py` uses **`airsim`**, port 41451. This is what
  actually connects.
- `scripts/fly_airsim.py` uses `projectairsim`, ports 8989/8990. It cannot talk
  to CityEnviron at all and is effectively dead code.
- The installed `airsim` is the **Project AirSim 1.8.1** package (UE5-era API:
  `simSpawnObject` is attached dynamically, `Multirotor` is gone, the signature
  carries an extra `is_blueprint`). The server is a **UE4** AirSim 1.8.1 plugin
  (`UE4CC` crash reporter, `SimplygonUE4` + `PhysXVehicles` in the plugin list).
  Client and server are from different forks of the same version number.

Reads survive this mismatch because their signatures are stable across forks —
that is why `simGetVehiclePose`, `simGetImages` and `simListSceneObjects` all
work while spawning does not. Calling the raw RPC directly shows the server
rejecting the wrapper's arity cleanly (`RPCError ... invalid number of
arguments`), so the crash is in argument/asset marshalling, not the network.

To use the IAMAI fork properly, run a sim build that serves **NNG on
8989/8990** and drive it with `projectairsim`; do not mix it with the 41451
msgpack path. `sim_worlds/` and the `Neighborhood`/`DynamicCity` references in
older docs assume exactly that NNG layout.

### Two independent flight stacks, plus one physics-only library

This is the other thing that misleads people. There are two independent flight
stacks plus one physics-only library:

| Entry point | Transport | Perception | Used by |
|---|---|---|---|
| `garuda/main.py` → `core/orchestrator.py` | PX4 / MAVSDK, `udpin://…:14540` | `perception/detector.py` (PicoDetector / AerialDetector, ncnn or OpenCV-ONNX) | `python -m garuda.main` |
| `scripts/run_unreal_pilot.py` | Unreal AirSim RPC, port **41451** | `perception/yolo_detector.py` (ultralytics YOLOv8, `yolov8n.pt`) | `run_unreal.bat`, `verify_follow_shot.py` |
| `scripts/terminal_dashboard.py` | none — synthetic telemetry | `digital_twin/*` physics models | `scenarios.py` |

Consequences an agent will otherwise get wrong:

- `garuda/main.py` does **not** import `garuda/digital_twin/*`, `garuda/fdr/`,
  `garuda/gimbal/`, or `garuda/arbiter/safety_limits.py` (the last only via
  `control/cfc_numpy.py`). Editing those changes nothing observable at runtime;
  their only executable coverage is `tests/` and the docstrings.
- `digital_twin/*` is a self-contained physics library. Nothing but
  `terminal_dashboard.py`, `scenarios.py`, and `tests/test_digital_twin_physics.py`
  ever drives it. Don't assume README's "6-tier failsafe state machine" gates
  any real flight path — it gates the dashboard.
- `garuda/brain/tools_schema.py::to_arbiter_proposal` is dead code: its lazy
  `from ..arbiter.arbiter import ToolProposal` targets a module that does not
  exist (`garuda/arbiter/` holds only `safety_limits.py`). It imports fine and
  raises only if called.
- The orchestrator's cinematic states (`ORBIT`, `CHASE`, `REVEAL`) call
  `control/cfc_controller.py`. The AirSim path implements the same vocabulary
  in `flight/shot_planner.py` instead. Don't conflate them.

---

## 3. AirSim wiring (easy to get silently wrong)

- RPC: `127.0.0.1:41451`, vehicle name `GarudaDrone`.
- Camera names are **hardcoded** in `garuda/flight/airsim_client.py` as
  `front_center` and `bottom_center`. Renaming them in config breaks the
  client — there is no config lookup.
- **The simulator does not read `config/airsim_settings.json`.** It reads
  `%USERPROFILE%\Documents\AirSim\settings.json`. The two currently **differ**:
  the live copy uses `VehicleType: "SimpleFlight"` with
  `DefaultVehicleState: "Armed"`, while the repo copy says `PX4Multirotor` with
  no default state. Editing the repo copy changes nothing until you copy it
  across and restart the sim. When a camera or vehicle setting "doesn't take
  effect", check that file first.
- `garuda/flight/follow_controller.py` holds **no AirSim imports** on purpose —
  it talks to a `FlightBackend` protocol. `AirSimClient` satisfies it without
  knowing the module exists. Keep it that way; it is what makes the control law
  testable in 32 s without a 60 s simulator round-trip.

---

## 4. Pedestrians and cameras

These are observed failure modes from real runs, not preferences.

### The simulator is now Project AirSim (IAMAI v1.0.1), and it flies

`D:\ProjectAirSim\CityEnviron.exe` (UE 5.x) replaces the UE 4.27 build. Download
links, SHA-256s, and the full API table are in `README.md` §1a. The old
environment is still at `D:\Aatonovaz\Garuda\CityEnviron` and still works for
perception work — it is **not** a candidate for flight.

Verified live on the new build through `scripts/pas_backend_check.py`:

| | Result |
|---|---|
| NNG 8989/8990 | connected |
| `enable_api_control()` + `arm()` | `True` / `True` (plain methods) |
| `takeoff` to 6 m | reached **5.98 m AGL** |
| body-frame velocity / yaw / strafe | position moved x=-1.0→5.0, y=8.0→7.2 |
| chase camera | 1280×720 BGR, 84 frames |
| belly + depth camera | 400×225, `16FC1`, **6.71–10.21 m** |
| `hover` / `land` | both OK |

`garuda/flight/pas_client.py` is the repo backend. It runs the client's
coroutines on a background `_LoopThread` so the blocking `FlightBackend` surface
works unchanged.

**Four traps that each cost a full run.** All four fail *silently* — no
exception, plausible return value, nothing happens:

1. **`await (await ...)` is mandatory.** The `*_async` methods are coroutines
   that *return a Task*. `await method()` yields the Task without running it, so
   the command is submitted and abandoned. The first live backend run "succeeded"
   at every call while the drone never moved a centimetre. `_run_task()` exists
   solely to wrap this.
2. **`ImageDisplay.start()` is mandatory.** The stock scene runs a *steppable*
   clock. Without the display object pumping it, subscriptions are accepted and
   no frames ever publish — which looks exactly like a camera failure.
3. **NED is +z down.** Climbing is a *negative* `v_down`. The sign error sank
   the drone to −0.86 m AGL while `takeoff()` returned `True`.
4. **`unpack_image` already returns bottom-up rows.** Adding a `flipud` inverts
   the frame and manufactures "detections" that are just the sky.

**A fifth, and the one that matters most: any yaw command free-falls the
drone.** Measured on `robot_quadrotor_fastphysics`:

| Command | Altitude |
|---|---|
| idle body-frame, no yaw | 0.00 m/s — holds |
| idle body-frame + `yaw_rate=26` | −1.17 m/s — free fall |
| after `rotate_to_yaw_async` | −1.48 m/s — free fall |

The yaw control path disengages the hover controller. It is not the nonzero yaw
value (passing `yaw=0` alongside a *separate* `rotate_by_yaw_rate_async` still
fell), and issuing a concurrent altitude-holding velocity command does not help.

**Fix: pulsed yaw.** `ProjectAirSimBackend._yaw_burst` rotates 0.12 s at a time
and re-issues `hover_async` between bursts; heading accumulates while altitude
recovers.

| Burst | Heading | Altitude |
|---|---|---|
| 0.15 s × 4 @ 40 dps | +95.6° | **−0.02 m** |
| 0.30 s × 4 @ 40 dps | +66.1° | −4.00 m |
| 1.00 s × 2 @ 40 dps | −5.0° | −2.93 m |

Three 40 s follow runs were lost to this before it was found — the drone fell
to the pavement at the spawn point and sat there, so the loop reported 1% lock
on a scene it could not fly in. After the fix a 45 s run held 2.8 m for the
whole flight. `rotate_to_heading()` also closes a loop on *measured* heading
because the sign of a positive yaw rate is not the one you would guess.

Other things that cost a run: `Pose`/`Transform` want **`translation`** (not
`position`) and carry **no `scale`** — scale is a separate spawn argument, and
`position` raises `TypeError: 'NoneType' object is not subscriptable` inside the
client, which reads like a server rejection. `payload["data"]` is raw `bytes`.
`get_ground_truth_pose()` returns a plain dict. There is **no**
`get_ground_truth_velocity`, no `close()`, and `list_actors()` (no arguments) /
`destroy_object()` replace the guessed `list_scene_objects(regex)` /
`delete_actor()`. `ImageDisplay.start()` spawns a **non-daemon** thread, so a
script that raises hangs at exit instead of failing.

**The stock scene has no people, but one can be generated.**
`spawn_object` serves only packaged assets (`/Engine/BasicShapes/Cube` returns
`None`); `spawn_object_from_file` takes raw bytes and accepts `gltf` only.
`garuda/flight/humanoid_glb.py` writes a 1.895 m humanoid glTF from scratch with
no dependencies — this box has `AnimatedCharacter.fbx` and
`Mikkt_SkeletalMesh.fbx` in the UE 5.7.4 content but no FBX→glTF converter.
YOLO recognises the result at **conf 0.33–0.81** in live frames.
`move_actor_along()` (`import_ned_trajectory`) walks it. Walk the subject along
the drone's line of sight (constant y) — a loop that varies y puts it behind a
facade within seconds, which reads as a lock failure but is a scenario fault.

**Watch from above.** `scripts/make_follow_config.py` adds a `FrontCamera`
(nose, scene + depth perspective — the stock scene has *no* forward depth, so
the avoider would otherwise read the pavement as an obstacle) and an
`EagleCamera` 9 m up pitched down. `b.cycle_view()` walks the main window to it
via `World.switch_streaming_view()`, which advances to the next
`streaming-enabled` camera. The client cannot report which camera is active —
confirm visually. The overhead frame needs `roll = 90` or it renders a quarter
turn sideways.

**Run one instance.** The launcher is `CityEnviron.exe`; the real process is
**`CityEnviron-Win64-Shipping.exe`** and needs ~1.6–2.4 GB. Filtering on
`CityEnviron` alone matches only the 7 MB launcher stub and reports "0 running"
while a fully-booted instance holds the ports — which is how a second instance
gets launched on top of the first. Always check with
`Get-Process *CityEnviron*`.

### No people in the Project AirSim stock scene — do not assume otherwise

A 12-step yaw sweep at 6 m altitude over the fountain plaza returned 8 "person"
detections. **All 8 were false positives**, drawn and inspected:

```
conf=0.39  bbox=[462, 75, 504, 130]   <- tree canopy
conf=0.28  bbox=[198, 209, 235, 283]  <- gap in a stone railing
```

Frames are in `logs/survey_person_*.png` and `logs/person_boxes_0.25.png`. The
old UE4 build had a crowd baked into the level as static mesh instances; this
scene does not. **A zero lock ratio on the new environment is a missing-subject
problem, not a control-law failure** — same conclusion as for the old build,
reached independently.

So the migration status is split, and it matters which half you are looking at:

- **Flight, cameras, depth: proven.** Every capability the UE4 build lacked.
- **Person-following: not proven here.** It still needs a scene with people, and
  `spawn_object` returned `None` for `/Engine/BasicShapes/Cube` — a packaged
  environment only contains assets it was packaged with. Finding a spawnable
  rigged-human asset is the open task.

Do not delete `D:\Aatonovaz\Garuda\CityEnviron` until that is closed: it is the
only verified place the follow demo has ever run.

### The UE 4.27 CityEnviron build (retained, perception-only)

### `simSpawnObject` crashes the simulator — do not call it

**Verified in isolation.** Any call to `simSpawnObject` kills `CityEnviron.exe`;
the RPC never returns and the process exits with a fatal error. Minimal repro,
one call, one process, nothing else running:

```python
airsim.VehicleClient(ip="127.0.0.1", port=41451).confirmConnection()
client.simListSceneObjects(".*")          # fine -> 5709
client.simSpawnObject("T", "/Engine/BasicShapes/Sphere", pose,
                      airsim.Vector3r(1,1,1), physics_enabled=False,
                      is_blueprint=False)   # <-- sim is dead here
```

`/Engine/BasicShapes/Sphere` cannot be missing — it ships with the engine — so
this is not an asset-path or argument problem. The RPC layer itself is fine
(`simListSceneObjects`, `simGetVehiclePose`, `simGetImages` all work). The spawn
path is simply broken in this build. Note the installed package is **Project
AirSim 1.8.1**, not classic AirSim: `simSpawnObject` is attached dynamically,
`Multirotor` does not exist, and the signature carries an extra
`is_blueprint: bool = False` argument. Check `dir()` before assuming an API.

Consequences:

- **No dynamic spawning of any kind.** No pedestrians, no test props, no
  `VerifyPedestrian_*` fallback in `verify_follow_shot.py`. That fallback will
  crash the sim, so the script only works if the scene *already* has subjects.
- Always time-box any future spawn attempt in a child process; killing the
  Python client does **not** bring the simulator back.
- The rig is instead whatever the map already contains. Use those objects.

### The real fix: IAMAI Project AirSim env, not a port of this one

**CityEnviron cannot be converted to UE 5.x.** It is a cooked 4.27 binary with
2,124 loose `.uasset` files in a pre-5.0 format. There is no conversion tool.
The fix is a *different* build of the same city, not a port of this one.

The IAMAI fork publishes one, and it is a download rather than a build:

```
https://github.com/iamaisim/ProjectAirSim/releases/download/v1.0.1/CityEnviron-Windows-1.0.1.zip.001
https://github.com/iamaisim/ProjectAirSim/releases/download/v1.0.1/CityEnviron-Windows-1.0.1.zip.002
```

Also available in v1.0.1: `Blocks`, `Neighborhood`, `LandscapeMountains`
(Windows + Linux each). Two-part zips need 7-Zip, which joins them
automatically. Official SHA-256 for the CityEnviron parts:

```
.001  f45defee160ec2d05245ed45051c43abee8651ffede59b2f8c6cc978cfa513ba
.002  20bcffcd41c3327ff36cac83af12353fcffda66de00e636202c83570a543b4d5
```

- **Use v1.0.1, not v1.1.0.** v1.1.0 (24 Sep) is a pre-release whose
  "pre-built environment and plugin packages ... are pending verification and
  attachment" — no Windows zips. v1.0.1's client is `projectairsim==1.0.2`,
  which is **already installed** in this venv.
- The env starts with an **empty scene**; the client loads the scene and spawns
  the vehicle explicitly. That is normal, not a failure.
- No VS2022 is installed here, so the `build.cmd simlibs_debug` route is
  unavailable. Use the prebuilt environment; you do not need to compile.
- v1.0.1 ships prebuilt **UE plugins for Linux** only. The Windows environment
  zip carries what it needs, so a separate plugin download should be unnecessary
  — verify on first launch before assuming.

**`garuda/flight/pas_client.py` is the adapter.** It implements the same
`FlightBackend` Protocol as `AirSimClient` on top of `projectairsim`, so
`FollowController`, `SubjectLock`, `ObstacleAvoider` and the shot planner need
no changes. Verified: the backend satisfies all seven Protocol methods.

The IAMAI client has exactly the API the UE4 build lacks:

| Missing on UE4 CityEnviron | Available in `projectairsim` |
|---|---|
| `takeoffAsync`, `landAsync`, `hoverAsync` | `takeoff_async`, `land_async`, `hover_async` |
| `moveByVelocityBodyFrameAsync` | `move_by_velocity_body_frame_async` |
| `rotateToYawAsync` | `rotate_by_yaw_rate_async`, `rotate_to_yaw_async` |
| `simSetVehiclePose` (kinematic hack) | `set_pose` (real dynamics) |
| `simSpawnObject` — **crashes the sim** | `World.spawn_object` |

Transport also changes: **NNG on 8989 (topics) / 8990 (services)**, not msgpack
on 41451. `scripts/fly_airsim.py` was already written against this API — it is
not dead code, it was waiting for a server that speaks it.

### There are NO movement APIs — fly kinematically

`VehicleClient` in this build has **99 methods and not one of them moves the
vehicle**. There is no `takeoff`, no `land`, no `hoverAsync`, no `moveBy*`.
`AirSimClient` calls **twelve** methods that do not exist:

```
takeoffAsync  landAsync  hoverAsync  moveByVelocityAsync
moveByVelocityBodyFrameAsync  moveToPositionAsync  moveToZAsync
rotateToYawAsync  getMultirotorState  ...
```

This is why `rotate_yaw` hung: it calls `enableApiControl` + `armDisarm` and
then a method that isn't there. **Never call those methods.** Check `dir()`
first.

What *does* work for flight:

```python
client.simSetVehiclePose(airsim.Pose(airsim.Vector3r(x, y, z), quat), ignore_collision=True)
```

`simSetVehiclePose` is the only way to fly. `ignore_collision=True` is a
**required** positional/keyword argument. Yaw written this way *does* take
effect (unlike `simSetCameraPose` yaw, which is ignored), so a heading survey by
teleporting the vehicle is a reliable way to find a target.

### Verified working: live person-following

`scripts/follow_live.py` runs the real loop — YOLO → `SubjectLock` → shot
framing → control law → `ObstacleAvoider` → pose write — with kinematic flight
substituted for the missing movement API.

```powershell
venv\Scripts\python.exe scripts\follow_live.py --duration 30 --conf 0.12 --start-yaw 300
```

Real measured output from a 28 s run:

```
t= 7.5  conf=0.60  h=0.132  err=(-0.94,-0.23) yaw_rate=-32.0  braking_obstacle_2.26m
t=12.8  conf=0.86  h=0.160  err=(-0.41,-0.27) yaw_rate=-13.8  braking_obstacle_2.13m
t=18.6  conf=0.88  h=0.161  err=(+0.81,-0.37) yaw_rate=+27.7  obstacle_0.39m_within_stop
t=19.1  conf=0.85  h=0.146  err=(+0.84,-0.28) vx=+0.714                              clear
```

Everything in the chain is live: confidence up to **0.88**, the control law
responding to `err_x` with correct sign, yaw integrating, the depth veto firing
on real obstacles (`2.08–2.62 m` braking, one hard stop at `0.39 m`), and
**0 identity switches** — the lock held one subject. `logs/rec/follow_run/`
keeps per-tick CSV plus annotated frames.

Practical notes for that script:

- Start pose matters more than anything else. The surveyed pose (origin, 4 m
  AGL, yaw ≈ 300°) is the only one that has reliably detected people; a 14 m
  back-off points the camera at bare road and locks nothing.
- `--conf 0.12` beats the 0.35 default by a wide margin (see the recall table).
- Lock ratio is low (~12 %) because the crowd is far away and only visible in
  some headings. Approaching is the main recall lever, and that needs the
  kinematic velocity loop to close distance.
- Overlay frames show `LOCK <conf>` in green or `HOLD`, so the visual check is
  unambiguous.

### People ARE in the map — and detection works on them

Correction to an earlier claim in this file: the map **does** contain people.
They are baked into the level as static mesh instances, so they have **no actor
names and no poses** — which is why a scene-graph search finds nothing. But they
are ordinary visible geometry, and YOLO detects them normally.

**Verified end to end, offline from a recording:**

```powershell
# 1. record (sim needed only for capture)
venv\Scripts\python.exe scripts\record_frames.py mysession 30 3
# 2. detect + audit, no simulator required
venv\Scripts\python.exe scripts\detect_offline.py mysession 0.15
```

| Recording | conf≥0.35 | conf≥0.15 | conf≥0.08 | conf≥0.03 |
|---|---|---|---|---|
| `crowd2` (65 frames) | 8 | 25 | 39 | 55 |

A real detection, masked for the airframe:

```
conf=0.31  bbox=[372,226,403,254]  h_ratio=0.058  err_x=+0.21
```

10 of 65 frames at conf≥0.15, 4 vehicle false positives removed by masking. The
targets are small and distant (`h_ratio` ≈ 0.06), so **0.15–0.25 is the working
threshold**, not the 0.35 default — the people read weakly because they are
far away. Closer approach is the single biggest recall win available.

Recording to disk is the right way to iterate here: the simulator's control APIs
are broken (see above) but capture works fine, so perception can be tuned with
zero RPC latency and zero crash risk.

**Camera pitch sign: negative looks DOWN.** `pitch_deg=+3` pointed the camera at
the sky and rendered the frame upside down. Also, `simSetCameraPose`'s translation
is *relative to the settings.json mount* — passing an offset drags the sensor
back into the hull, so pass `Vector3r(0,0,0)` to rotate without moving, or an
explicit forward offset to clear the props. Either way the nose camera sees a
large wedge of drone body; `detect_offline.py` masks it.

### CityEnviron has no *addressable* person in it

`simListAssets()` returns 479 assets and **zero** of `rp_manuel_rigged_001_ue4`,
`rp_sophia_rigged_003_ue4`, or `rp_carla_rigged_001_ue4`. The only
character-named entries are Blueprints and path splines:

- `CharacterPaths` ×4 — instanced path splines sitting **790–816 m** from the drone
- `BasePedestrianPath_BP`, `BasePedestrianPath_Crosswalk_BP` — sidewalk splines

`simSpawnObject` *accepts* a Blueprint and returns a name, so the old spawner
logged `✅ Spawned 3D pedestrian character` and never reached its fallback. The
subject existed, was not a person, and YOLO saw nothing. `find_best_pedestrian_asset`
now returns `None` and the log says `⚠️ Spawned PRIMITIVE MARKER (not a person)`.

**Consequence: person-following cannot be demonstrated in this sim, and no
Python-side change can fix it.** Two independent blockers: there is no person in
the map, and `simSpawnObject` cannot add one. Do not report a 0 % lock ratio as
a control-law failure — there is no subject. The cinematic control law, identity
lock, and avoidance are all covered offline by `tests/test_cinematic_follow.py`
(40 tests, synthetic pedestrians + moving wall). The parked cars and trucks YOLO
*does* see are the only detectable subjects available; proving the loop on a
vehicle needs the class filter widened.

### The map has no rigged humans, but the files exist on disk

`Content/Building_99/Characters/FuseCharacters/` holds four rigged humans with
walk animations (`Male`/`Female_Fuse`, Caucasian and African, `MixamoWalk`,
`Female_WalkAnim`), but they are loose `.uasset`/`.uexp` pairs in a packaged
build with no `.pak` files. They cannot be spawned (see above) and are not
placed in the map. Adding one requires an Unreal Editor session against the
source project, not this binary.

### Camera geometry (verified by frame capture)

`front_center` was at `X = 0.25, Z = -0.05, Pitch = -15°`, which put the camera
**inside the drone's own propeller guards**. Every frame was ~35 % occluded by
black airframe shapes, and YOLO returned a false `person` at conf 0.415 on a car
at the frame edge. Now `X = 0.48, Z = -0.08, Pitch = -3°` in both
`config/airsim_settings.json` and the live settings file; the body is fully out of
frame and the false positive dropped to zero. Props sit at ±0.253 m, so anything
at or below `X = 0.25` is inside the rotor arc — see §3 for why editing the repo
copy alone does nothing.

**YOLO cannot detect primitives.** `Cylinder`/`Cube` markers are never classified
as people. Only rigged skeletons work, and this build has none spawnable.

**Actor Z and the sign question — resolved.** Older notes claim actors must sit
at `Z ≤ -0.5` or their collision mesh penetrates the asphalt and
`simSetObjectPose` silently fails. In *this* build that is not what happens:
`DEFAULT_SIDEWALK_PATHS` uses `z = +1.2` and the markers walk correctly (verified
moving ~3 m per 3 s). The failure mode is real in other AirSim worlds with a
raised terrain origin, so leave the `+1.2` alone here and only revisit it if a
pedestrian spawns and refuses to move. `simGetCollisionInfo()` does report
`Landscape_1` contact for spawned markers, which is cosmetic in this world.

**Never track from ground truth.** The control loop must consume real
`front_center` frames: `simGetImages` → YOLO → filter class `person`
(conf ≥ 0.35–0.40) → normalized centroid error → control law. Calling
`simGetObjectPose(actor_name)` to steer is "cheating" and invalidates any
demo. `SubjectLock` deliberately re-establishes identity itself (the detector is
stateless) through three gates: motion-gated centroid proximity → colour-histogram
re-ID → largest-box fallback.

**Servoing law** (implemented in `follow_controller.py`):

```
e_x = (cx - W/2) / (W/2)      e_y = (cy - H/2) / (H/2)
yaw_rate = 0.8 · e_x          (rad/s)
v_down   = -0.5 · e_y         (m/s)
```

Forward speed is driven by target bbox height, not by a fixed standoff:
below ~35 % of frame height advance at 1.5–2.5 m/s; above ~45 % hold hover.
`shot_planner.py` expresses framing as `target_h_ratio` (0.75 close-up, 0.55
medium, 0.30 wide) plus `standoff_m`, `orbit_rate_dps`, `lateral_bias`,
`lead_room_frac`, `pitch_bias_deg`.

**Obstacle avoidance is a veto, not a planner.** `flight/avoidance.py` fails
safe: on a missing or malformed depth map it scales *down*, never up. Keep that
direction; an inverted fail-safe is a crash.

---

### The process split, and the seam that makes it possible

The intended architecture is: **camera frames leave the simulator, detection and
tracking run as a separate process, and the drone is driven from outside.** The
seam for that already exists in your own code.

`garuda/flight/follow_controller.py` defines a `FlightBackend` `Protocol` with
**no AirSim import anywhere in the module**:

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
That already caused one silent failure, now fixed and guarded by
`tests/test_cinematic_follow.py::test_backend_contract_matches_real_client`:

- The protocol asked for `get_front_camera`
- `AirSimClient` defined `get_forward_camera`
- `StubBackend` implemented `get_front_camera`

So all 40 cinematic tests passed while `AirSimClient` **could not be used as a
real backend** — it would have raised `AttributeError` on the first tick. The
follow loop had never actually flown against the simulator. Whenever you add a
new `FlightBackend` implementation, run that test; it compares the protocol
against both the stub and the real client by name.

Implication for the split: the perception process should depend on the
`FlightBackend` protocol and a frame source, never on `airsim` itself. That
keeps `follow_controller`, `subject_lock`, `avoidance`, `yolo_detector` and
`shot_planner` importable and testable with no simulator present, which is
exactly what the 41 cinematic tests already do.

### Marker-based identification: ArUco works, but you cannot place markers

**The good news.** ArUco is available in this venv (OpenCV 5.0) and is fast
enough to replace YOLO for identity. Verified on this machine, no simulator:

| Check | Result |
|---|---|
| Single marker detected | ✅ |
| Three IDs separable in one frame | ✅ `[3, 17, 42]` — "follow person 3" is exact |
| 40 px marker + 7 px blur + 30° rotation | ✅ still read |
| Cost | **3.6 ms/frame → ~276 fps on CPU** |

The marker ID *is* the identity, so `SubjectLock`'s three-gate re-ID heuristic
and any confidence score become unnecessary. Note the OpenCV 5 API:
`generateImageMarker(dictionary, id, sidePixels, img)` — the old
`borderBits` arguments were removed.

**The blocker: you cannot put a marker on anything.** `simSetObjectMaterialFromTexture`
is a **no-op that always reports success**:

```python
c.simSetObjectMaterialFromTexture("Hedge_03_14", r"logs\aruco_23.png")  # -> True
c.simSetObjectMaterialFromTexture("Hedge_03_14", r"C:\nonexistent\foo.png")  # -> True
```

A nonexistent file returning `True` proves the retexturing path is disabled in
this packaged build. Sweeping camera pitch over `[0, ±4, ±45, ±90]` produced no
marker at any angle. `simSwapTextures` and `simSetObjectMaterial` share the
fate. So ArUco is a viable *detector* but there is no way to *mark* an object,
which leaves it no better than YOLO for this simulator.

Do not spend more time here. If markers become possible (a sim built with
retexturing enabled, or a physical demo with printed tags), the detection half
is already proven.

### Safe camera aiming (added, no arming)

`AirSimClient.aim_camera_at(name)` and `set_camera_pose(pitch_deg, yaw_deg)` use
`simSetCameraPose`, which only transforms the camera — it does **not** enable API
control or arm the vehicle, so it is safe while grounded. Use these, not
`rotate_yaw`, for calibration: `rotate_yaw` calls `enableApiControl` + `armDisarm`
and **hangs** in this build.

Two sign conventions that cost real time to find:

- NED has **+Z down**, so an object below the drone (larger `z_val`) needs a
  **positive** pitch to look down at it.
- Camera forward is **+X** at yaw 0, so bearing is `atan2(dy, dx)` in degrees,
  and positive yaw turns right.

## 5. Cinematic follow stack (current uncommitted work)

`garuda/flight/follow_controller.py` · `shot_planner.py` · `shot_recorder.py` ·
`avoidance.py` and `garuda/perception/subject_lock.py` · `yolo_detector.py` are
all **untracked**, along with `tests/test_cinematic_follow.py` and
`scripts/verify_follow_shot.py`. Check `git status` before editing — the most
recent work in this repo is not in git history yet.

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
  where takeoff appears to work and no aircraft is involved. This is the most
  expensive trap in the config file — check `connection_mode` before trusting
  any flight result.
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
this host's venv. Installed here but absent from it: `airsim`, `ultralytics`,
`python-dotenv`, `speech_recognition`, `pyaudio`, `projectairsim`, `websockets`,
`fastapi`. Absent here and needed by some code paths: `ncnn`, `ncps`,
`llama_cpp`, `faster_whisper`, `piper`, `sounddevice`, `openwakeword`,
`openai`.

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
`docs/DOCUMENTATION_POLICY.md` describe a **different, much larger system**:
`GarudaOneRuntime`, `DroneLink`, a WebSocket on :8765, a browser UI on :8080,
Cactus Needle-2, "800 passed, 3 skipped", pinned submodules, `cad/`, `skills/`,
`GOAL.md`, `LOOP.md`, `assets/*.md`. None of that exists in this repo.

Concretely, **none of the enforcement those docs mandate is present**:
`scripts/check_docs_consistency.py`, `scripts/install_git_hooks.sh`,
`.githooks/`, `.github/workflows/` — none exist. There is no CI, no pre-commit
hook, no linter, no formatter, and no typechecker anywhere in the repo. The
`Makefile` `lint` target is just `py_compile` on two files.

So do not treat a doc edit as a required companion to a code change, and do not
believe a capability claim in those files. Trust, in order: the code, the tests,
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
- Branch is `main`; remote is `sameerreddy789/Garuda_OS`. Keep commits
  behaviour-scoped.
