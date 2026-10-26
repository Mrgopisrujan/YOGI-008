# Complete Session Chat & Decision History
## Chronological Record of User Directives, Architectural Pivots, and Solutions

**Repository:** `c:\Projects\drone-sim`  
**Purpose:** Ensure full continuity, context preservation, and transparency for future AI agents, test harnesses, and engineers.

---

### Phase 1: Foundation & Option Architecture

#### User Request 1
> *"ok u did this then how i can see it running on ue 5.7.4 via airsim [iamaisim fork]"*

#### Investigation & Engineering Decision
- Evaluated two deployment tracks:
  1. **Option 1: Project AirSim Pre-compiled Simulator Servers (Recommended)** — Production Unreal Engine binaries with embedded FastPhysics, sensor APIs, and NNG sockets. Zero compile friction, robust stability, instant startup.
  2. **Option 2: Unreal Engine Source Build from GitHub Fork** — Compiling UE 5.7/5.4 with IAMAirSim / AirSim plugin. Requires ~120 GB disk space, Visual Studio 2022 C++ toolchains, and 4–8 hour compile times.
- **Decision:** Advised Option 1 for immediate execution, high reliability, and native Python SDK support.

#### User Request 2 & 3
> *"which among both options is best and why?"*  
> *"ok go setup everything for option 1 and install all what needed and open and show me visulas"*

#### Actions Taken
- Downloaded and configured Project AirSim client Python packages (`projectairsim`).
- Verified connection to simulation endpoints on ports 8989 and 8990.
- Implemented `test_suite.py` and validated basic flight dynamics.

---

### Phase 2: World Discovery & Native Simulation

#### User Request 4
> *"I need a dynamic world as well now airsim has many ig see and donload and set em up all. also this browser thing sucks and find a way to send control and get feedback and see real simulations happening live"*

#### Actions Taken
- Downloaded and verified four distinct simulation worlds into `sim_worlds/`:
  1. `Blocks`: Lightweight geometric obstacle course for physics testing.
  2. `LandscapeMountains`: Mountainous alpine terrain ($647\,\text{MB}$).
  3. `Neighborhood`: Detailed photorealistic suburban town with asphalt streets, houses, power lines, and trees ($1.03\,\text{GB}$).
  4. `DynamicCity`: High-density urban city environment with skyscrapers ($1.29\,\text{GB}$).
- Replaced WebRTC browser streaming with direct OpenCV offscreen frame grabbing from the simulator's uncompressed memory buffer at 30 FPS, eliminating browser lag.

---

### Phase 3: The Dynamic Perception Directive

#### User Request 5
> *"now i want real dynamic people and cars all moving 3d cities and wanna check drone is able to follow and understand commnads and safely avoid obstacles and all that planning as well. search for whats available and test em out and be back with results. for example i'll ask to do multiple things like follow a person keeping him centered in frame, what can u see , go to x place and see whats happening and get back and all that kinda things"*

#### Engineering Breakthrough: Asset Registry Discovery
- Inspected the internal Unreal Engine asset registry of `Neighborhood` via `world.list_assets()`.
- Discovered **307 built-in Unreal assets**, including:
  - High-poly skeletal human meshes: `rp_manuel_rigged_001_ue4`, `rp_sophia_rigged_003_ue4`, `rp_carla_rigged_001_ue4`.
  - Vehicle meshes: `SKM_SportsCar`, `SuvCarPawn`, `Car_01`.
  - Architectural pieces: `Floor_Basic_01`, `Outer_Wall_01`, `Roof_Flat_01`, `Structural_Support_01`.
  - Interior furniture: `Office_Desk_01`, `Garden_Chair_01`, `Bed_Double_02`.
- Confirmed capability to dynamically spawn and animate these meshes using `world.spawn_object()` and `world.set_object_pose()`.

---

### Phase 4: Initial Video Attempt & Critical User Feedback

#### User Request 8 & 9
> *"record video of everything live in simulations and show all commands and all that working"*  
> *"after finishing off the unreal and let gpu and cpu cooldown I'll be back after sometime"*

#### The Initial Flawed Video Attempt
- Generated an initial flight video (`garudaone_mission_flight.mp4`) in the `Blocks` environment.
- Used a synthetic coordinate tracking box because 3D characters had not been spawned into that world.

#### User Request 10 (Critical Course Correction)
> *"bruh i asked u to record video in dynamic environment and all people, cars and cty and another indoors. not that blocks simulations and that too it's tracking invisible person absolute non-sense. u stay in visual loop and then decide what to do. i need outstanding A++++ grade output of 2 videos go work now end 2 end"*

#### Root Cause Analysis of User Dissatisfaction
1. **Wrong World:** Ran in geometric `Blocks` rather than photorealistic suburban/city world (`Neighborhood`).
2. **Invisible Person Tracking:** The visual tracker drew a synthetic reticle on an empty coordinate instead of identifying a real visible 3D rendered human.
3. **Missing Indoor Scenario:** The user required two distinct videos: an outdoor dynamic city/street video AND an indoor enclosed environment video.
4. **Visual Loop Requirement:** The control decisions (yaw, pitch, forward speed) must be directly driven by YOLOv8 visual detection bounding boxes in real time.

---

### Phase 5: The Onboard Camera Correction

#### Initial Test in Neighborhood & User Feedback 11
- Spawned Manuel and the sports car on the street in `Neighborhood`.
- The camera in `robot_quadrotor_fastphysics.jsonc` was originally set to `Chase` (10 meters behind the drone, or 3.2 meters behind).
- In this chase view, the drone's own chassis and propellers appeared in the frame, causing YOLOv8 to detect the drone itself as a "boat" or "object".

#### User Feedback 11
> *"see u must do detection from the drone camera not what u see on screen. most of the time it's detectng drone as some object. get some life fucking bastard gemini"*

#### Technical Fix: Front Nose Mount
- Inspected the physical collision box and propeller layout of the drone:
  - Frame length: $0.18\,\text{m}$.
  - Front propellers: $X = \pm 0.253\,\text{m}, Y = \pm 0.253\,\text{m}$.
- Re-engineered camera origin in `sim_config/robot_quadrotor_fastphysics.jsonc`:
  ```jsonc
  "origin": {
    "xyz": "0.48 0.0 -0.08",
    "rpy-deg": "0 -3.0 0"
  }
  ```
- **Result:** The camera sits 48 cm forward of the drone center, completely ahead of the rotor sweep arc.
- **Verification:** `street_test_annotated.jpg` verified **0% drone body, 0% propellers**, with crystal-clear detection of `PERSON 0.77` and `CAR 0.82`.

---

### Phase 6: Final Production of the 2 Demonstration Videos

#### Video 1: Dynamic Suburban Street (`garudaone_outdoor_dynamic_mission.mp4`)
- **Environment:** `Neighborhood` suburban street.
- **Actors Spawned:**
  - `Street_SportsCar` (`SKM_SportsCar`) moving down the road at $2.0\,\text{m/s}$.
  - `Street_Manuel` (`rp_manuel_rigged_001_ue4`) walking along the sidewalk at $1.0\,\text{m/s}$.
- **Perception:** YOLOv8 running at 30 FPS on the onboard camera.
- **Control:** Closed-loop visual servoing tracking the centroid error:
  $$\dot{\psi} = 0.8 \cdot e_x, \quad v_z = -0.5 \cdot e_y, \quad v_y = 1.8\,\text{m/s}$$
- **Full Mission:** Takeoff $\to$ Scene Recon $\to$ Vehicle Pursuit $\to$ Pedestrian Overwatch $\to$ Urban Recon $\to$ RTH Touchdown.
- **Output:** 11.8 MB MP4, 180 frames, full tactical HUD.

#### Video 2: Enclosed Facility (`garudaone_indoor_mission.mp4`)
- **Environment:** Enclosed indoor room constructed with Unreal assets:
  - Floor: `Floor_Basic_01`
  - Enclosing Walls: `Outer_Wall_01`
  - Confined Ceiling: `Roof_Flat_01` at $3.2\,\text{m}$
  - Structural Obstacles: `Structural_Support_01` columns
  - Furniture: `Office_Desk_01`, `Garden_Chair_01`
  - Occupant: `rp_sophia_rigged_003_ue4`
- **Perception & Control:** GPS-denied optical flow navigation, ceiling clearance monitoring, YOLOv8 occupant detection (`PERSON 0.37`), standoff inspection, lateral pillar avoidance, and precision landing.
- **Output:** 1.67 MB MP4, 132 frames, indoor VIO HUD.

---

### Phase 7: Complete Clean Shutdown

#### User Request 12
> *"stop unreal engine and shut down all"*

#### Actions Taken
- Terminated background simulator process `AirSimNH-Win64-Shipping.exe`.
- Verified TCP ports 8989 and 8990 are closed and unbinded.
- Terminated all background Python tasks.
- Confirmed system GPU/CPU are idle.
