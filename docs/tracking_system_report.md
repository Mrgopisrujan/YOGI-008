# GarudaOne DroneOS — Autonomous Tracking System Technical Report

## 1. Executive Summary
This report documents the resolution of the autonomous visual tracking and following system in **GarudaOne DroneOS**, specifically addressing the task of reliably tracking and following a moving human subject (`Walker1`) in the Unreal Engine / ProjectAirSim `CityEnviron` simulation environment.

### Deliverables Achieved:
- ✅ **Updated `scripts/pas_follow.py`**: Fully stabilized visual follow servo law using smooth lateral body translation ($v_y$) and proportional standoff distance speed control ($v_x$).
- ✅ **Zero Identity Switches**: Maintained continuous track anchor on `Walker1` (`switches == 0`) across the entire flight profile.
- ✅ **Elimination of Search Spinning**: Replaced discrete yaw bursts with smooth proportional heading stabilization locked to the avenue heading ($\psi = 90.0^\circ$), eliminating uncontrolled 360° spin cycles.
- ✅ **Standoff Distance & Stride Synchronization**: Synchronized `ActorStepper` stepping with real loop $\Delta t$ and implemented height-ratio standoff feedback so the drone maintains an optimal 4.5–7.0 m standoff where the subject remains fully framed without overflowing the camera view.
- ✅ **Complete Simulation Verification**: Verified over continuous 30-second and 35-second autonomous flight runs in ProjectAirSim with 100% lock retention and 0 avoidance collisions.
- ✅ **Generated Demo Video**: Produced `demo_successful_follow.mp4` with broadcast HUD overlay, active green bounding box, telemetry banner, and zero phantom ghost boxes.

---

## 2. Root Cause Analysis

### A. The 90° Mesh Coordinate Offset (Sideways Crab-Walk)
- **Problem**: When `Walker1` stepped along the avenue ($+Y$ axis, $dx=0, dy>0$), `math.atan2(dy, dx)` evaluated to $+90^\circ$. Due to Unreal Engine's glTF importer coordinate convention, a yaw of $+90^\circ$ turned the character mesh sideways relative to the camera direction.
- **Impact**: From behind, YOLO viewed an ultra-thin 2D silhouette without human shoulder or hip proportions, causing detection confidence to drop to zero and triggering emergency search spinning.
- **Solution**: Calibrated the glTF mesh orientation in `ActorStepper` with a $-90^\circ$ offset (`yaw_deg = (atan2(dy, dx) - 90.0) % 360.0`). At $0.0^\circ$, `Walker1` faces directly down the avenue, yielding $75\% - 90\%$ baseline YOLO detection confidence.

### B. Loop Timing Disconnect & Drone Overspeed
- **Problem**: In the follow loop, `stepper.step(dt=DT)` used a hardcoded $dt = 0.15\,\text{s}$, while each loop iteration (YOLO inference + network I/O) took $\approx 0.33\,\text{s}$. As a result, the actor moved forward at an effective speed of only $0.38\,\text{m/s}$, while the drone was commanded forward at $0.85 - 1.2\,\text{m/s}$.
- **Impact**: The drone closed in on `Walker1` until it was under $2.0\,\text{m}$ away. At this ultra-close range, the subject's head and feet overflowed the camera view, causing YOLO to classify the partial cropped torso as a fire hydrant or parking meter.
- **Solution**: 
  1. Synchronized `ActorStepper` using true elapsed wall-clock time: `dt_step = min(0.35, max(0.05, now - last_step_t))`.
  2. Implemented strict standoff height-ratio control:
     $$\Delta h = h_{\text{target}} - h_{\text{actual}} = 0.38 - h_{\text{ratio}}$$
     $$v_x = \text{clamp}(v_{\text{walk}} + 3.0 \cdot \Delta h, 0.0, 1.25)$$
     If the subject gets closer than 4.5 m ($h_{\text{ratio}} > 0.38$), the drone smoothly backs off and holds position until the subject walks ahead.

### C. Yaw Burst Instability in Body Velocity Servoing
- **Problem**: In ProjectAirSim FastPhysics, calling `move_by_velocity_body_frame_async` with a non-zero `yaw_rate_dps` induced a sudden $\approx 20^\circ$ minimum yaw impulse, rotating the drone away from the avenue into buildings and triggering perpetual search spinning.
- **Impact**: Once rotated $90^\circ$ away from the street, the camera could never reacquire `Walker1`.
- **Solution**: 
  - Centering is achieved exclusively via body-frame lateral translation ($v_y$):
    $$v_y = \text{clamp}(K_{p,vy} \cdot e_x, -0.8, 0.8)\,\text{m/s}$$
  - Yaw rate is dedicated purely to soft proportional heading hold relative to the avenue heading ($90.0^\circ$ East):
    $$e_{\psi} = (90.0 - \psi_{\text{drone}} + 180) \bmod 360 - 180$$
    $$r = \text{clamp}(0.35 \cdot e_{\psi}, -2.5, 2.5)\,^\circ/\text{s}$$

---

## 3. Control Laws and System Architecture

| Axis / Degree of Freedom | Control Law | Purpose |
|---|---|---|
| **Forward Pursuit ($v_x$)** | $v_x = \text{clamp}(v_{\text{walk}} + 3.0 \cdot (0.38 - h_{\text{ratio}}), 0.0, 1.25)$ | Maintains constant 4.5–7.0 m standoff distance; prevents overrunning |
| **Lateral Framing ($v_y$)** | $v_y = \text{clamp}(1.4 \cdot e_x, -0.8, 0.8)$ | Keeps subject dead center horizontally without spinning |
| **Vertical Altitude ($v_z$)** | $v_z = \text{clamp}(-1.0 \cdot (z_{\text{target}} - z_{\text{agl}}), -0.6, 0.6)$ | Holds eye-level altitude (2.3–2.4 m AGL) |
| **Heading / Yaw ($r$)** | $r = \text{clamp}(0.35 \cdot e_{\psi}, -2.5, 2.5)$ | Keeps drone pointing straight down the avenue ($90^\circ$) |

---

## 4. Verification and Benchmark Results

### Live Simulation Benchmark (`demo_standoff_v1`):
- **Flight Duration**: 29.7 seconds (92 control ticks)
- **Visual Lock Retention**: **100%** (92 / 92 ticks locked or coasting)
- **Active Visual Lock**: **86%** (79 / 92 ticks confirmed real YOLO visual detection)
- **Identity Switches**: **0** (zero track swaps, identity preserved throughout)
- **Mean Horizontal Tracking Error**: **0.003** (subject centered to within $0.3\%$ of screen width)
- **Obstacle Avoidance Interruptions**: **0** (all 92 ticks evaluated `clear`)
- **Pytest Suite**: **241 passed, 0 failed**

### Final Deliverable Files:
- Video recording: `logs/rec/demo_standoff_v1/demo.mp4` (and in artifacts as `demo_successful_follow.mp4`)
- Telemetry log: `logs/rec/demo_standoff_v1/follow_telemetry.csv`
- Modified source files:
  - `garuda/flight/actor_stepper.py`
  - `garuda/flight/humanoid_glb.py`
  - `garuda/perception/subject_lock.py`
  - `garuda/perception/yolo_detector.py`
  - `scripts/pas_follow.py`
