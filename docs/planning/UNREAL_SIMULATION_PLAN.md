# GarudaOS — Unreal Engine 5.8.4 & Valdrada (Boundless NYC) Migration Plan

> **Status:** Active Blueprint & Architecture  
> **Target Simulation:** Unreal Engine 5.8.4 + Valdrada (Boundless NYC)  
> **Flight Stack:** GarudaOS Decision Brain + kinematic Valdrada platform  
> **AI Engine:** OpenAI GPT API (Natural Language Copilot & Decision Making)  
> **Replaces:** Unreal Engine 5.7.4 + AirSim / CityEnviron

---

## 1. Why move to Valdrada (Boundless NYC) on UE 5.8.4

The current Unreal stack targets UE 5.7.4 with AirSim and the `CityEnviron.exe`
build. That path has two independent, verified blockers:

1. **No addressable person.** `CityEnviron` bakes its crowd as static mesh
   instances with no actor names or poses, and `simSpawnObject` terminates the
   simulator process (verified in isolation). Person-following cannot be
   demonstrated there, and no Python-side change can fix it.
2. **Crippled AirSim surface.** The UE 4.27 `CityEnviron` exposes no
   `takeoff`/`land`/`moveBy*` family, and its `simSpawnObject` crashes the
   process. The IAMAI Project AirSim v1.0.1 (UE 5.x) fixes flight but still
   ships an empty scene with no spawnable rigged humans.

**Valdrada** (https://github.com/mkturkcan/boundless-nyc) is a city-scale
digital twin of New York City compiled from public municipal records. It solves
both blockers:

| Capability | CityEnviron / AirSim | Valdrada (Boundless NYC) UE 5.8.4 |
|---|---|---|
| Populated city | Static meshes, no actors | Pedestrians, taxis, buses, MTA buses, emergency vehicles |
| Person addressable by name | No | Yes (simulated actors) |
| `spawn_object` | Crashes the sim | Native actor spawning (CARLA-style API) |
| RGB camera | Yes | Yes |
| Metric depth | Yes (limited) | Yes (synchronised) |
| Semantic / instance segmentation | No | Yes (Cityscapes-compatible) |
| Engine | UE 5.7.4 | UE 5.8.4 |
| Transport | msgpack-rpc 41451 / NNG 8989/8990 | TCP 2000 (CARLA-style Python API) |

GarudaOS's `FlightBackend` Protocol already decouples the follow loop from any
particular simulator. We add a `ValdradaBackend` (`garuda/flight/valdrada_client.py`)
that satisfies the same protocol, so `FollowController`, `SubjectLock`,
`ObstacleAvoider` and the shot planner need no changes.

---

## 2. Live connection architecture (Valdrada)

```mermaid
graph TD
    subgraph UE_584 ["Unreal Engine 5.8.4 (Valdrada / Boundless NYC)"]
        NYC["NYC Digital Twin<br/>(5 boroughs, 1,085,937 buildings)"]
        PEDS["Pedestrians & Vehicles<br/>(simulated actors)"]
        AIRSIM["Valdrada Server<br/>(TCP :2000)"]
        CAM_FWD["Camera 1: Forward RGB + Depth"]
        CAM_SEG["Instance / Semantic Segmentation"]
        NYC --> AIRSIM
        PEDS --> AIRSIM
        AIRSIM --> CAM_FWD
        AIRSIM --> CAM_SEG
    end

    subgraph GARUDA_OS ["GarudaOS Companion Brain (Python)"]
        VOICE["Natural Language Pilot"]
        GPT["GPT API Engine"]
        TWIN["Digital Twin Engine"]
        VISION["Perception Stack<br/>(YOLO + SubjectLock)"]
        FC["Follow Controller<br/>(FlightBackend Protocol)"]
        VOICE --> GPT
        GPT --> TWIN
        TWIN --> VISION
        VISION --> FC
    end

    %% Network Connections
    AIRSIM <-->|TCP :2000 (Valdrada Python API)| FC
```

### How data moves live:

1. **Valdrada server → GarudaOS**: GarudaOS connects to the Valdrada Python API
   on TCP port `2000`, subscribes to the forward RGB + depth camera topics and
   reads the platform transform as telemetry.
2. **GarudaOS → Valdrada server**: The follow loop issues kinematic body-frame
   velocity commands; the backend teleports the platform actor each tick
   (NED → ENU conversion at the boundary).
3. **Human → Unreal**: The operator watches the follow run through the
   annotated frames GarudaOS records (`shots/<session>/<shot>_<ts>.mp4`).

---

## 3. Camera rig specification (unchanged framing, new backend)

| Viewpoint | Purpose | Backend mapping |
|---|---|---|
| **Forward perception** | Obstacle avoidance, subject tracking | `valdrada_backend.get_forward_camera()` (RGB) + `get_forward_depth()` |
| **Downward odometry** | VIO / precision landing | Not streamed by default; spawn an additional belly depth camera if needed |
| **Observer POV** | Eagle-Eye spectator view | Cycle the Valdrada spectator / a mounted chase camera |

Camera mount (verified geometry from CityEnviron, carried forward):

- `X = 0.48, Y = 0.0, Z = -0.08` (forward of the propeller guards, out of frame)
- `Pitch = -3°` (slightly down; `+3°` pointed at the sky and inverted the frame)

---

## 4. Backend contract (`FlightBackend`)

`garuda/flight/follow_controller.py` defines the protocol with no simulator
import:

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

`ValdradaBackend` (`garuda/flight/valdrada_client.py`) implements all seven
methods on top of the `valdrada` Python client. Whichever backend is
instantiated (`AirSimClient`, `ProjectAirSimBackend`, or `ValdradaBackend`),
the follow loop is identical.

### Guard test

`tests/test_cinematic_follow.py::test_backend_contract_matches_real_client`
compares the Protocol against every real client by name. Run it whenever a new
backend is added:

```powershell
venv\Scripts\python.exe -m pytest tests/test_cinematic_follow.py::test_backend_contract_matches_real_client -v
```

---

## 5. Coordinate conversion (ENU ↔ NED)

Valdrada uses ENU metres (x east, y north, z up). Garuda uses NED (+z down,
camera forward +X at yaw 0, bearing `atan2(dy, dx)`, positive yaw turns right).

The boundary conversion in `ValdradaBackend`:

| Quantity | ENU (Valdrada) | NED (Garuda) |
|---|---|---|
| Forward axis | — | camera +X at yaw 0 |
| Position x | east | **north** (`t.y`) |
| Position y | north | **east** (`t.x`) |
| Position z | up | **down** (`-t.z`) |
| Velocity vx | forward | forward |
| Velocity vy | right | right |
| Velocity vz | up | **down** (`-vz`) |
| Altitude AGL | `z` | `z` (reported directly) |

Climbing in Garuda = negative `vz` (NED down). In Valdrada that is positive `up`
(`-vz`), handled inside `move_velocity_body`.

---

## 6. Known traps (carried over from AirSim port)

1. **Synchronous clock.** Valdrada frames only publish when `world.tick()`
   steps the sim. The backend ticks once per control loop iteration.
2. **Sustained yaw free-falls.** A sustained yaw-rate command disengages the
   altitude hold. The backend pulses yaw in `BURST_S = 0.12 s` bursts with a
   re-hold between them (measured: 0.15 s × 4 @ 40 dps → +95.6°, −0.02 m alt;
   0.30 s × 4 → −4.00 m alt).
3. **BGRA → BGR.** Valdrada images are BGRA uint8; YOLO expects BGR. Drop the
   alpha channel, do not `flipud` (depth rows are already in image order).
4. **Depth is 24-bit encoded.** Decode R/G/B to a 24-bit integer, then to
   metres (`raw / 16777216 * 1000`).
5. **Run one instance.** The Valdrada server holds port 2000; a second instance
   cannot bind and silently fails. Check the port before launching.

---

## 7. Workspace changes

| File | Action | Reason |
|---|---|---|
| `garuda/flight/valdrada_client.py` | **Add** | New `ValdradaBackend` satisfying `FlightBackend` |
| `docs/planning/UNREAL_SIMULATION_PLAN.md` | **Rewrite** | UE 5.8.4 + Valdrada, replacing UE 5.7.4 + AirSim/CityEnviron |
| `scripts/launch_valdrada.bat` | **Add** | Windows launcher for the Valdrada UE 5.8.4 environment |
| `scripts/valdrada_follow.py` | **Add** | Follow-demo entry point using `ValdradaBackend` |
| `config/simulation.yaml` | **Edit** | Add `valdrada` section (host, port, camera settings) |
| `config/airsim_settings.json` | **Keep** | Retained for the legacy AirSim path; not read by Valdrada |

Nothing in `garuda/flight/follow_controller.py`, `shot_planner.py`,
`avoidance.py`, `subject_lock.py`, or `yolo_detector.py` changes — they are
transport-agnostic.

---

## 8. Pending checklist & roadmap

- [ ] **Step 1: Backend** — `garuda/flight/valdrada_client.py` (done)
- [ ] **Step 2: Launch script** — `scripts/launch_valdrada.bat` (done)
- [ ] **Step 3: Follow demo** — `scripts/valdrada_follow.py` (done)
- [ ] **Step 4: Config** — `valdrada` section in `config/simulation.yaml` (done)
- [ ] **Step 5: Verify contract test** — run `test_backend_contract_matches_real_client`
- [ ] **Step 6: End-to-end follow** — launch Valdrada UE 5.8.4, run
  `scripts/valdrada_follow.py --duration 30`, confirm lock ratio > 30 %

### Running the follow demo (Valdrada)

```powershell
# 1. Launch the Valdrada UE 5.8.4 environment (holds TCP :2000)
.\scripts\launch_valdrada.bat

# 2. Run the GarudaOS follow loop against it
$env:GARUDA_MODE = "simulation"
venv\Scripts\python.exe scripts\valdrada_follow.py --duration 30 --conf 0.15
```

Valdrada already contains pedestrians, so no subject-spawning step is required
— the open blocker from CityEnviron is removed.
