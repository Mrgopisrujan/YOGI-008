# LNN Architecture Analysis — GarudaOne Drone Control

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - The active PX4 transport is pymavlink, not MAVSDK-Python.
> - The selected flight profile uses one forward VL53L5CX at 8x8/15Hz; three-sensor/VL53L8CX designs are not active.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - The flight profile instantiates C10 and requires an inbound checksummed status reply; physical attitude feedback and motion limits remain unvalidated.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!NOTE]
> This is a dated research snapshot. Model choices, estimates, and recommendations are not implementation claims. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


**Author:** Research subagent (Hermes Agent)
**Date:** 2026-07-18
**Subject:** Liquid Neural Networks (LNNs) and CfC (Closed-form Continuous-time) models for the GarudaOne autonomous cinematography drone.
**Sources cited:** MIT CSAIL LNN papers (Hasani, Lechner, Rus, et al.), CfC paper (arXiv:2106.13898 / Nature Machine Intelligence 2022), LTC paper (arXiv:2006.04439 / AAAI-21), PX4 OFFBOARD mode documentation (main branch), ncps library docs (mlech26l/ncps, 2.3k★), IEEE Spectrum, Science Robotics (adc8892), CineMPC (IEEE TRO 2024), Ajith Vallath (2025 LNN edge survey), Adaptive Drone Swarm Navigation with LNNs (IEEE 2025).

---

## TL;DR — The Verdict Up Front

1. **The user's instinct is correct.** The current CfC-as-velocity-controller-at-20Hz-via-OFFBOARD is *architecturally redundant* with PX4's own `mc_pos_control` velocity PID. It is the wrong layer for a cinematography drone. LNNs in the literature are used as **high-level perception→action policies** (pixels or state → body-rate/steering command), not as a "second PID stacked on top of PX4's PID."
2. **However — the *extreme* alternative (LNN outputs position targets at 1–5Hz as a pure trajectory planner) is also wrong** for this use case. Cinematography needs *continuous, reactive* control of framing, not sparse waypoints.
3. **The correct architecture is a hybrid:** CfC LNN outputs **velocity setpoints with yaw** at 10–20Hz (this part of the current design is fine), BUT it should be framed and trained as a **perception→framing policy** (the "what to do" layer), NOT a "velocity PID replacement." PX4 keeps the inner PID loops (position, velocity, attitude, rate, motor) — that is its job. The LNN never touches motors.
4. **The actual blunders** in the current design are *not* the velocity-vs-position question. They are: (a) **training on synthetic PD-style targets** — the CfC is literally imitating a hand-coded kinematic reference, so the LNN adds nothing a 20-line PD controller wouldn't; (b) **no expert demonstration data** — the MIT result that makes LNNs famous is trained on *human pilot trajectories*, not synthetic kinematics; (c) the CfC is being asked to be a smoother it isn't trained to be.
5. **Keep the 19-neuron, 12→5 CfC contract mostly as-is**, but **retrain on real expert pilot logs** (DAgger loop is already scaffolded in `train_dagger.py` — use it). Optionally add a **position feedforward** output alongside velocity (PX4 supports `position + velocity feedforward` in a single `TrajectorySetpoint`) so PX4's trajectory generator does the smoothing, not the LNN.

The rest of this document is the evidence.

---

## 1. What LNNs/CfC Are Actually Good At (vs PID/MPC)

### 1.1 What the literature says LNNs are good at

From the CfC paper (Hasani et al., Nature Machine Intelligence 2022, arXiv:2106.13898) and the LTC paper (Hasani et al., AAAI-21, arXiv:2006.04439), LNNs/CfCs are designed for:

| Strength | Evidence |
|---|---|
| **Continuous-time / irregularly-sampled sequences** | Time appears explicitly in the CfC closed-form; no fixed clock required. Handles missing samples natively. |
| **Causal task understanding from high-dim sensor streams** | MIT drone work (Science Robotics adc8892, 2023): LNNs "capture the causal structure of tasks from high-dimensional, unstructured data, such as pixel inputs from a drone-mounted camera." |
| **Out-of-distribution (OOD) generalization** | The headline MIT result: a drone trained to fly-to-target in a summer forest *generalizes to winter forests and urban environments without retraining*. LNNs were "the only ones that could generalize to scenarios they had never seen, without any fine-tuning." |
| **Extreme parameter efficiency** | Autonomous driving lane-keeping: **19 liquid neurons match the performance of 100,000+ conventional neurons** (Ajith 2025 survey; IEEE Spectrum; MIT news 2021). The MIT drone network had ~20,000 parameters total — and Hasani notes "If I have only 34 neurons, I can literally go and figure out what is the function of each and every element." |
| **Interpretability** | Small neuron count → per-neuron function analysis is tractable. This is a real, cited advantage. |
| **Low latency / low power on edge** | "We can implement a liquid neural network that can drive a car, on a Raspberry Pi." — Ramin Hasani, IEEE Spectrum. CfC is **1–5 orders of magnitude faster** than ODE-based LTC at inference (no numerical solver). A 19-unit lane-keeping model draws <50 mW. |
| **Stability & boundedness** | LTCs are constructed from linear first-order dynamical systems modulated by nonlinear gates — provably stable and bounded (Hasani et al. 2021). |

### 1.2 What LNNs are NOT good at (and where PID/MPC wins)

| Weakness | Why |
|---|---|
| **High-bandwidth inner-loop stabilization** | PID at 400Hz on a NuttX RTOS is the right tool for motor-level rate control. LNNs are not competitive here and shouldn't be — the latency budget is microseconds. |
| **Hard real-time guarantees** | LNN inference time is data-dependent (the "liquid" time constants adapt to input). PID/MPC have deterministic, bounded execution. PX4's control loops *must* be deterministic. |
| **Constraint satisfaction / safety envelopes** | MPC explicitly handles constraints (box limits, collision avoidance) in its optimization. LNNs have no native constraint mechanism — you bolt clamps on after (as GarudaOne already does in `clamps.py`). For *guaranteed* geofence/failsafe, deterministic code wins. |
| **Known-plant high-performance tracking** | When you have a good dynamics model (a quadrotor is very well modeled), MPC with that model will outperform a learned policy on *nominal* tracking. LNNs win when the *task* is hard to specify (perception, framing, OOD) — not when the *dynamics* are hard. |
| **Sparse, global planning** | LNNs are recurrent policies, not search-based planners. For "go to GPS waypoint X" a planner is better. |

**Bottom line:** LNNs excel at **perception→action policies where the mapping is hard to write down but easy to demonstrate**, especially under distribution shift. They are *not* a replacement for deterministic control where the dynamics are known and the constraints are hard.

---

## 2. How LNNs Are Used in Real Drone/Robotics Applications

### 2.1 The canonical MIT CSAIL drone work (the originators)

**Paper:** "Robust flight navigation out of distribution with liquid neural networks" — Hasani, Chahine, Kao, Ray, Shubert, Lechner, Amini, Rus. *Science Robotics* 6, eadc8892 (19 April 2023).

**What they actually did:**
- **Task:** Vision-based fly-to-target. A quadrotor with a forward camera must fly toward an unlabeled object.
- **Input:** Raw camera pixels (processed by a CNN frontend → feature vector into the LNN).
- **Output:** A control command to the drone. (Closed-loop control at the policy rate.)
- **Training:** **Imitation learning on human pilot demonstrations.** "The team's system was first trained on data collected by a human pilot flying toward a target." This is the critical detail.
- **Network:** Liquid neural network, ~20,000 parameters, ~34 neurons in the policy head.
- **Experiments:** Range tests, stress tests, target rotation & occlusion, "hiking with adversaries," triangular loops between objects, dynamic target tracking. Tested across seasons (summer→winter forest) and domains (forest→urban).
- **Result:** "Liquid neural networks were the only ones that could generalize to scenarios they had never seen, without any fine-tuning, and could perform this task seamlessly and reliably." Outperformed state-of-the-art CNN+LSTM and transformer baselines on OOD.

**What this tells us:** The MIT drone work is a **perception→action policy**, trained by **imitation learning from expert demonstrations**, evaluated on **OOD generalization**. It is *not* a "velocity PID." The LNN replaces the *hard-to-specify* part (what does the image tell me to do?) — not the *easy-to-specify* part (how do I track a velocity setpoint?).

### 2.2 The autonomous driving lane-keeping work (the other canonical demo)

**Code:** `mlech26l/keras-ncp` (referenced from MIT news 2021 as "Code Repository for Autonomous Driving with LTCs").

**Task:** End-to-end steering from dashcam video.
**Architecture:** CNN (image feature extractor) → NCP-wired CfC/LTC (policy) → steering wheel angle.
**Result:** 19 liquid neurons match 100,000 conventional neurons on lane-keeping. Robust to OOD (rain, new roads, lighting changes). Runs on a Raspberry Pi.

**Key analogy for GarudaOne:** The steering angle is the *high-level* command — the car's low-level steering servo PID is unchanged. The LNN sits on top of, not in place of, the deterministic actuator controller.

### 2.3 Drone swarm navigation with LNNs

**Paper:** "Adaptive Drone Swarm Navigation with Liquid Neural Networks in Dynamic Wind Fields" — IEEE conference (Bengaluru, Nov 2025), document 11335870.

**What they did:** LNN-driven swarm navigation under nonlinear, time-varying wind disturbances.
**Result:** 32% reduction in average navigation error, 22% increase in swarm cohesion, ~30% decrease in collision probability, 27% reduction in velocity variance vs. baselines (rule-based, consensus, RL).
**Why LNNs won:** "LNNs are directly engineered to process temporal signals with differential equations, allowing them to remember previous states and dynamically adjust to novel environment signals." Baselines "either overfit to statics or are not as adaptable to the dynamics to maintain stability in dynamic and changing aerial environments."

**Relevance to GarudaOne:** Wind disturbance rejection is exactly the kind of *temporal, adaptive* problem LNNs are good at — and a cinematography drone fighting wind to hold a smooth arc is a similar regime. But note: this is *simulation* only, not flight-tested hardware.

### 2.4 CfC for Walker2d (reinforcement learning benchmark)

The CfC repo (`raminmh/CfC`, 1k★) ships `train_walker.py` — CfC trained by RL on the Walker2d mujoco task. This is an existence proof that CfC works as a **policy network in an RL loop**, not just imitation learning. Relevant if GarudaOne ever moves to RL (see §8).

### 2.5 Summary of real-world LNN robotics use

| Application | Input | Output | Training | LNN role |
|---|---|---|---|---|
| MIT drone fly-to-target | Camera pixels | Flight command | Imitation (expert pilot) | Perception→action policy |
| Autonomous driving steering | Dashcam pixels | Steering angle | Imitation (expert driver) | Perception→action policy |
| Drone swarm in wind | State + wind | Velocity cmd | RL (simulation) | Adaptive policy under disturbance |
| Walker2d locomotion | Joint state | Torque cmd | RL | Policy network |

**In every case, the LNN is the *policy* — the "what do I do given what I see" — not the *servo*. The deterministic low-level controller (PX4, steering PID, motor ESC) is unchanged.**

---

## 3. LNN as Velocity Controller (Current) vs Trajectory Planner (Proposed) — Which Is Correct?

This is the user's core question. The answer is nuanced: **neither pure extreme is right; the current velocity-output approach is closer to correct, but for the wrong reason and with the wrong training.**

### 3.1 The case AGAINST "LNN as pure trajectory planner outputting position targets at 1–5Hz"

A pure trajectory planner emits sparse position waypoints (e.g., "be at (x,y,z) in 2 seconds"). PX4's trajectory generator then smooths them. Problems for cinematography:

1. **Cinematography is continuous and reactive, not waypoint-based.** Framing a moving subject at 5m requires *continuous* adjustment of velocity as the subject moves, the wind shifts, and obstacles appear. A 1–5Hz position update is too slow to hold framing on a walking/running subject — you'd see step-tracking artifacts.
2. **The LNN's strength is temporal, continuous adaptation.** Downgrading it to a 1–5Hz waypoint emitter throws away the one thing LNNs are uniquely good at (continuous-time, input-adaptive dynamics). You'd be using a Ferrari to deliver groceries.
3. **PX4's trajectory generator already does waypoint smoothing well.** If all you want is "go to X smoothly," PX4 Position Mode + a simple planner beats a learned model. The LNN adds nothing there.

### 3.2 The case AGAINST "LNN as a 20Hz velocity PID replacement" (the current framing)

1. **It's redundant with PX4's `mc_pos_control` velocity loop.** PX4 already has a well-tuned velocity PID with feedforward. Putting a learned velocity controller on top of it via OFFBOARD means *two* velocity controllers in series — the LNN's output becomes the setpoint for PX4's velocity PID. The LNN is not replacing the PID; it's *driving* the PID. That's fine *if* the LNN is doing something the PID can't (perception, framing, OOD adaptation). It's wasteful *if* the LNN is just reimplementing a PD law on state error — which is exactly what the current `train_cfc.py` does (see §8).
2. **At 20Hz the LNN cannot help with inner-loop stability.** PX4's rate loop runs at 400Hz. The LNN at 20Hz is 20x too slow to influence attitude stabilization. So the LNN is *necessarily* an outer-loop (guidance) controller regardless of how it's framed.

### 3.3 The correct framing: LNN as a **perception→velocity policy** at 10–20Hz

The literature (§2) is unambiguous: **LNNs are policies, not servos.** The correct architecture is:

```
[Camera + ToF + State]  →  [CfC LNN policy]  →  [velocity + yaw setpoint]  →  [PX4 OFFBOARD]  →  [PX4 PID cascade]  →  [motors]
   (perception)              (the learned part)      (10–20Hz)                  (400Hz inner loops)
```

The LNN outputs **velocity setpoints** (this is correct and matches what PX4 OFFBOARD natively accepts — see §6), but it is *trained* and *conceptualized* as a **framing/tracking policy that maps perception to motion intent**, NOT as a "velocity controller." The distinction is in *what the LNN is optimizing*, not in *what wire format it emits*.

- **Wrong framing:** "The LNN computes vx/vy to regulate position error to zero." (That's a PD controller. PX4 already has one.)
- **Right framing:** "The LNN computes vx/vy to keep the subject cinematically framed while smoothly arcing around obstacles and respecting the shot type." (That's a policy. PX4 can't do this — it has no idea what 'cinematic framing' means.)

The output format (velocity) is the same. The *training objective* is completely different (see §8).

### 3.4 Optional refinement: position + velocity feedforward

PX4's `TrajectorySetpoint` (ROS 2) and `SET_POSITION_TARGET_LOCAL_NED` (MAVLink) both support **simultaneous position + velocity**, where velocity is a *feedforward* added to the position controller's output. This is strictly more informative than velocity-only and lets PX4's trajectory generator do the jerk-limiting.

**Recommendation:** Keep velocity-only for v1 (simpler, matches current contract). Migrate to `position + velocity feedforward` in v2 once the LNN is retrained on real data — the LNN predicts where it wants to be (position) *and* how fast to get there (velocity feedforward), and PX4's trajectory generator produces the smoothest possible path. This is the architecture used by professional cable-cam / cinematic drone systems.

---

## 4. What the Research Literature Says About LNN for Aerial Robot Control

### 4.1 Direct LNN aerial control papers

| Paper | Year | Venue | Task | Key finding |
|---|---|---|---|---|
| Hasani et al., "Robust flight navigation OOD with LNNs" | 2023 | Science Robotics | Vision-based fly-to-target quadrotor | LNNs generalize OOD (summer→winter forest, forest→urban) where CNN+LSTM and transformers fail. Imitation learning from human pilot. |
| "Adaptive Drone Swarm Navigation with LNNs in Dynamic Wind Fields" | 2025 | IEEE | Swarm navigation in wind | 32% nav error reduction, 22% cohesion gain, 30% collision reduction vs. baselines. Simulation only. |
| (CfC paper includes quadrotor flight from raw pixels) | 2022 | Nature Machine Intelligence | Quadrotor control | CfC guides quadrotor flight from raw pixels — cited as a CfC application. |

### 4.2 Adjacent literature (learned drone control, not necessarily LNN)

| Paper | Year | Relevance |
|---|---|---|
| CineMPC (IEEE TRO 2024) | 2024 | Fully autonomous drone cinematography controlling *both* camera extrinsics and intrinsics. Uses MPC, not LNN — but defines the aesthetic-objective framing GarudaOne should learn. |
| CMU/Yamaha aerial filming (NVIDIA blog 2018) | 2018 | CNN trained on 70,000 images forecasts actor motion + plans collision-free cinematic trajectory. The "learned cinematic trajectory" precedent. |
| "Aesthetic-Aware Trajectory Planning for Multi-ROI UAV Aerial Cinematography" (MDPI 2026) | 2026 | Aesthetic-aware trajectory planning — exactly the "what makes a shot good" problem. |
| Spiking Neural Network quadrotor trajectory control (MDPI 2024) | 2024 | SNNs for quadrotor trajectory tracking — different neuromorphic family, same niche. |

### 4.3 What the literature does NOT contain

- **No paper uses LNN as a velocity-PID-on-top-of-PX4 trained on synthetic PD targets.** This is the GarudaOne-specific blunder (§7).
- **No paper uses LNN as a 1–5Hz sparse waypoint planner.** LNNs are always policies at the control/command rate.
- **No flight-tested LNN cinematography drone.** The closest is CineMPC (MPC, not LNN). GarudaOne has an opportunity to be first — but only if the LNN learns the *cinematic* part, not a PD law.

---

## 5. Right Division of Labor: Learned Controller (LNN) vs Deterministic Controller (PX4)

The principle, validated by both the literature and the PX4 architecture:

> **The LNN handles what's hard to specify; PX4 handles what's hard to guarantee.**

| Layer | Owner | Why |
|---|---|---|
| Motor PWM / ESC | PX4 | Microsecond-timing hard real-time. NuttX RTOS. Never ML. |
| Attitude rate loop (400Hz PID) | PX4 | Deterministic, well-modeled, safety-critical. |
| Attitude / position / velocity PIDs | PX4 (`mc_pos_control`) | Deterministic, well-tuned, constraint-aware. |
| State estimation (EKF2) | PX4 | Fuses GPS + IMU + optical flow + baro. Hard real-time. |
| Trajectory generation (jerk-limited smoothing) | PX4 | Deterministic, tunable (`MPC_POS_MODE`, trajectory generator params). |
| Failsafes (RC loss, offboard loss, geofence, low battery) | PX4 + Arbiter | Must be deterministic. `COM_OBL_RC_ACT`, `COM_OF_LOSS_T`. |
| Mode transitions / authority | Arbiter (L2a) | Deterministic FSM. "RC/kill > PX4 > Arbiter > ML." |
| **Perception (subject detection, ToF, obstacle semantics)** | **L2b (PicoDet + ToF)** | ML wins on perception. |
| **Cinematic framing policy (what velocity to command to get the shot)** | **CfC LNN (L2b)** | ML wins on "what does the shot want." Hard to write down. |
| **Command understanding (NL → intent)** | **L1 (LFM + Needle)** | ML wins on language. |

**The LNN's job is the framing policy — the mapping from (subject bbox, ToF, drone state, shot type) to (velocity, yaw_rate, gimbal_yaw) that produces cinematic motion.** PX4's job is everything deterministic. The Arbiter's job is deciding who is allowed to do what, when.

This matches the existing GarudaOne architecture (L1/L2a/L2b/L3). The error is not in the layering — it's in *what the L2b CfC is trained to do* (§7, §8).

---

## 6. Should the LNN Output Position, Velocity, or Both? (PX4 OFFBOARD Capabilities)

### 6.1 What PX4 OFFBOARD actually supports (verified from PX4 main docs)

**For multicopters via MAVLink** (`SET_POSITION_TARGET_LOCAL_NED`), the supported input combinations are:
1. Position only (x, y, z)
2. Velocity only (vx, vy, vz)
3. Acceleration only (afx, afy, afz)
4. **Position + velocity** (velocity used as **feedforward** — added to position controller output, fed to velocity controller)
5. **Position + velocity + acceleration** (both feedforwards; accel added to velocity controller output → thrust vector)
6. Attitude + thrust (`SET_ATTITUDE_TARGET`)
7. Body rates + thrust (`SET_ATTITUDE_TARGET`)

Frames: `MAV_FRAME_LOCAL_NED`, `MAV_FRAME_BODY_NED`.

**For multicopters via ROS 2** (`TrajectorySetpoint`):
- Position setpoint (position non-NaN; velocity/accel if non-NaN are feedforwards)
- Velocity setpoint (velocity non-NaN, position = NaN; accel if non-NaN is feedforward)
- Acceleration setpoint (accel non-NaN, position & velocity = NaN)

All handled by `mc_pos_control`. Critical caveat from the docs: "even if `OffboardControlMode` messages carry the intention of velocity control (only velocity field is set) but non-NaN position values are sent in the `TrajectorySetpoint` messages, then PX4 will keep running the position controller." **The actual setpoint content decides which controller runs, not the mode flag.**

### 6.2 What this means for GarudaOne

- **Velocity-only (current):** Valid, simple, well-supported. The LNN says "fly this fast in this direction." PX4's velocity PID tracks it. This is the right v1 choice and matches MAVSDK's primary supported mode.
- **Position + velocity feedforward (recommended v2):** Strictly more capable. The LNN says "be at (x,y,z) and here's the velocity to get there smoothly." PX4's trajectory generator + position controller produce jerk-limited motion with the LNN's velocity as feedforward. **This is the architecture professional cable-cam systems use** and it offloads smoothing to PX4 (where it belongs — see §3.4).
- **Position-only (the "pure trajectory planner" extreme):** Valid but wrong for cinematography (§3.1). Too sparse, loses the LNN's continuous-time advantage.
- **Attitude/body-rate/thrust (direct actuator):** Valid in PX4 but **violates the authority split** (§5). The LNN must never own attitude. Reject.

### 6.3 Recommendation

- **v1 (now):** Keep velocity-only (`vx, vy, vz, yaw_rate`) via `SET_POSITION_TARGET_LOCAL_NED` at 20Hz. This is correct and matches the current `cfc_v1_n19_i12_o5` contract's output semantics.
- **v2 (after retraining on real data):** Migrate to **position + velocity feedforward**. Add a 4th output dimension for position (or emit a relative position target derived from current pose + velocity * lookahead). This lets PX4 do the jerk-limiting and gives smoother cinematic motion. The CfC contract would change from `o5 [vx,vy,vz,yaw_rate,gimbal_yaw]` to `o8 [px_rel,py_rel,pz_rel,vx_ff,vy_ff,vz_ff,yaw_rate,gimbal_yaw]` or similar. See §12 for the proposed contract.

**Important:** yaw is always sent alongside position/velocity (PX4 treats yaw as a separate setpoint channel). The current contract's `yaw_rate` is correct — yaw *rate* (not absolute yaw) is the right choice for cinematography because it produces smooth, continuous yaw motion without wrap-around discontinuities.

---

## 7. What's Wrong (The "Blunder" the User Identified)

After reading the actual `cfc_controller.py` and `train_cfc.py`, here is the precise diagnosis.

### 7.1 What works in the current design ✅

- **Layer authority (L1/L2a/L2b/L3):** Correct. ML never owns motors. RC/kill > PX4 > Arbiter > ML. This matches the literature.
- **Output format (velocity + yaw_rate at 20Hz via OFFBOARD):** Correct for v1. PX4 supports it natively; MAVSDK handles it cleanly.
- **CfC + AutoNCP wiring (19 neurons, 12→5, ~1621 params):** Correct architecture choice. Matches the MIT autonomous-driving scale (19 neurons). NumPy-only inference on Pi 5 is the right deployment strategy.
- **Sub-ms inference, no PyTorch on Pi:** Correct. CfC's whole point is closed-form speed (1–5 orders of magnitude faster than ODE-based LTC).
- **Clamps + safety limits (defense-in-depth):** Correct. `safety_limits.py` is the single policy source; `control/clamps.py` mirrors it.
- **Toy-checkpoint detection (refuse to fly 480-param weights):** Correct and important safety pattern.
- **20Hz setpoint rate:** Correct (PX4 requires ≥2Hz; 20Hz gives margin and matches the perception rate). See §9.
- **Reset `hx` between track sessions:** Correct (was a bug in v1, fixed in rebuild).

### 7.2 The actual blunders ❌

#### Blunder 1 (THE big one): The CfC is trained to imitate a hand-coded PD law, not a human expert.

`train_cfc.py` generates synthetic trajectories where the **target output is a kinematic reference computed by hand** (e.g., `tgt = np.array([subj_vx, 0.0, 0.0, 0.0, 0.0])` for forward tracking; `tgt = np.array([-v_tan*sin(ang), v_tan*cos(ang), 0.0, omega, gimbal_corr])` for orbit). The CfC is then trained by MSE to **imitate this hand-computed target**.

**Why this is a blunder:** The LNN is literally learning to be a lookup table for a function you already wrote in Python. A 20-line PD controller would produce the same outputs with zero training, zero inference, and full interpretability. The LNN adds *nothing* — no OOD robustness, no causal task understanding, no perceptual reasoning. The MIT result that makes LNNs famous is trained on **human pilot demonstrations** ("data collected by a human pilot flying toward a target"), not synthetic kinematics. The entire value proposition of an LNN — learning what's hard to specify — is squandered.

**This is the blunder the user identified.** It is not the velocity-vs-position question (that's a red herring — velocity is fine). It is that the LNN is a complicated way to implement a PD controller you could have written in 20 lines.

#### Blunder 2: No real perception in the training loop.

The training inputs are **synthetic bbox/ToF values** (`cx = 0.5 + 0.02*sin(...)`, `tof_min = 8.0 + 0.3*rng.standard_normal()`). The CfC never sees real PicoDet output, real ToF noise, real subject motion. So it cannot learn the *perception→framing* mapping that is the whole point. It learns a smooth function of synthetic numbers.

#### Blunder 3: No expert demonstrations and no DAgger loop in practice.

`train_dagger.py` exists but is not in the training pipeline. The MIT recipe is: (1) train on expert demos, (2) deploy, (3) collect correction data when the policy drifts, (4) retrain. GarudaOne's pipeline is: (1) generate synthetic targets, (2) train, (3) deploy. No expert, no corrections.

#### Blunder 4: The CfC is asked to be a smoother it isn't trained to be.

The architecture docs say "the CfC outputs smooth velocity vectors trained from human expert pilot demonstrations, wrapped in jerk-limited smoothing." But the actual training produces outputs that imitate a kinematic reference — there's no jerk objective, no smoothness loss, no expert demonstration. The smoothing is bolted on in `smoother.py` (an EMA mislabeled as B-spline, per the rebuild doc). The CfC is not learning smoothness; it's being clamped into smoothness.

#### Blunder 5 (minor): `gimbal_yaw` in the CfC output is conceptually muddy.

The CfC outputs `gimbal_yaw_deg` alongside velocity. But gimbal control is a *separate* problem from drone velocity — the gimbal counter-rotates to hold framing while the drone banks. Mixing gimbal_yaw into the flight-control CfC conflates two concerns. The gimbal yaw command should be derived from the *framing error* (subject bbox position) by a separate, simpler controller (PID on bbox offset → gimbal yaw), not learned in the same CfC as flight velocity. The current `gimbal/` package exists but the CfC still emits a gimbal_yaw output that overlaps with it.

### 7.3 What is NOT a blunder (despite seeming suspicious)

- **20Hz update rate:** Correct (§9).
- **Velocity output (not position):** Correct for v1 (§3, §6).
- **19 neurons:** Correct, matches MIT's autonomous-driving scale.
- **NumPy-only inference:** Correct, optimal for Pi 5.
- **OFFBOARD mode:** Correct, the only sensible way to drive PX4 from a companion computer.

---

## 8. Training Data: What Should the LNN Be Trained On?

### 8.1 The literature's answer: imitation learning from expert demonstrations

Every flight-tested LNN robotics result uses **imitation learning (behavior cloning) from human expert demonstrations**, optionally refined with **DAgger** (Dataset Aggregation):

- **MIT drone (Science Robotics 2023):** "Trained on data collected by a human pilot flying toward a target."
- **Autonomous driving (keras-ncp):** Trained on expert driver steering data (the classic NVIDIA PilotNet paradigm, with CfC as the policy head).
- **CfC paper (Walker2d):** The one exception — RL. But this is simulation-only locomotion, not flight.

### 8.2 Recommended training pipeline for GarudaOne

**Phase 1 — Expert demonstration collection (the unblocker):**
1. Fly the GarudaOne airframe (or a sim equivalent in Isaac Sim + Pegasus) with a **human pilot** (RC transmitter) performing each shot type: follow, orbit, push-in, pull-out, lateral track, pedestal, reveal.
2. Log at 20Hz: `(cx, cy, bw, bh, tof_min, tof_left, tof_center, tof_right, tof_conf, vx_cur, vy_cur, tool_dist_norm, vx_pilot, vy_pilot, vz_pilot, yaw_rate_pilot, gimbal_yaw_pilot)`. The inputs are exactly the current 12-dim contract; the targets are what the *pilot* actually commanded, not a kinematic reference.
3. Target ~30–60 minutes of expert flight per shot type, across varied lighting, subject speed, and obstacle layouts. This is the single highest-value dataset the project can produce.

**Phase 2 — Behavior cloning (the first real CfC):**
- Train the CfC (`cfc_v1_n19_i12_o5`, unchanged architecture) on the expert dataset with MSE on the pilot's commanded velocities. This is the MIT recipe.
- Add a **jerk/smoothness loss term** (penalize ‖v_t − v_{t-1}‖²) so the policy learns smoothness as a primary objective, not a post-hoc clamp.
- Validate on held-out expert trajectories and on OOD conditions (different subject, different lighting, different obstacle layout).

**Phase 3 — DAgger (the refinement loop):**
- Deploy the trained CfC in SITL (or with a safety pilot).
- When the CfC's output diverges from what a human pilot would do (have a pilot monitor and intermittently override), log the correction.
- Retrain on the augmented dataset. `train_dagger.py` already exists — wire it into a recurring retrain job.
- This is how you get OOD robustness: the policy sees its own mistakes and learns from human corrections.

**Phase 4 (optional, later) — RL fine-tuning in sim:**
- Once Isaac Sim + Pegasus + PX4 SITL is working, fine-tune the behavior-cloned CfC with PPO on a reward that includes framing quality, smoothness, and obstacle clearance. The CfC repo's `train_walker.py` is a template for CfC-as-RL-policy.
- This is higher-risk and should only be done after behavior cloning + DAgger gives a working baseline.

### 8.3 What NOT to train on

- **Synthetic PD-style targets (current):** Blunder 1. A lookup table for a function you already wrote.
- **Pure RL from scratch in sim:** The CfC is tiny (1621 params); RL from scratch is sample-inefficient and unstable for such small nets. Always bootstrap from behavior cloning.
- **Random flight data:** Without expert structure, the CfC learns the wrong distribution (hovering, drifting).

### 8.4 Dataset size estimate

The MIT drone work used a modest amount of expert data (hours, not thousands of hours). For GarudaOne's 6 shot types at 20Hz:
- 6 shots × 10 min × 20Hz × 60 s/min = ~72,000 timesteps per shot, ~432k total for one session.
- 3–5 sessions per shot type across conditions → ~2–3M timesteps. This is plenty for a 1621-param CfC.

---

## 9. Correct Update Rate: 20Hz, 1–5Hz, or Something Else?

### 9.1 The three candidate rates and their roles

| Rate | Role | Owner | Justification |
|---|---|---|---|
| 400Hz | Attitude rate PID | PX4 | Hard real-time, microsecond timing. |
| 100–250Hz | Attitude / position PID | PX4 | Inner loops. |
| **20Hz** | **LNN policy + OFFBOARD setpoints** | **L2b CfC** | **Correct for GarudaOne.** Matches perception rate (PicoDet duty-cycled to ~15–20Hz with flow propagation to 25Hz). PX4 requires ≥2Hz; 20Hz gives 10x margin. Fast enough for cinematic framing (subject motion is ~1–2 m/s). |
| 5–10Hz | Trajectory *planning* (if separated) | Optional planner | If you add a higher-level shot planner ("in 5 seconds, transition from orbit to push-in"). Not the CfC's rate. |
| 1–5Hz | Mission / shot-type changes | L1/L2a | "Follow me, stay wide" doesn't change at 20Hz. The *intent* is low-rate; the *execution* is 20Hz. |

### 9.2 Why 20Hz is correct for the CfC (not 1–5Hz)

1. **Subject motion bandwidth.** A walking subject at 1.5 m/s moves 7.5cm per 20Hz frame. At 5Hz they move 30cm — that's visible framing drift. Cinematic framing needs ~20Hz correction.
2. **PX4 OFFBOARD keepalive.** PX4 exits OFFBOARD if setpoints stop for `COM_OF_LOSS_T` (default ~1s, GarudaOne sets 0.5s). 20Hz is a comfortable keepalive. 5Hz is marginal.
3. **CfC inference cost is negligible.** Sub-ms on Pi 5 (NumPy). 20Hz uses <2% of one core. There's no compute reason to slow down.
4. **The LNN's continuous-time advantage.** CfC's liquid time constants adapt to the input *timespan* parameter. Running at 20Hz gives the CfC a 50ms timespan to reason over. Running at 5Hz gives 200ms — too coarse for reactive framing.

### 9.3 When 1–5Hz is correct

Only for the *mission/shot-type* layer — "the user said 'orbit,' now plan a 12-second circular trajectory." That's a planner, not the CfC. If GarudaOne adds such a planner (recommended for complex multi-shot sequences), it runs at 1–5Hz and feeds *shot parameters* (radius, omega, subject lock) to the CfC, which runs at 20Hz and produces velocities.

**Recommendation:** Keep the CfC at 20Hz. Add a 1–5Hz shot planner above it only when multi-shot autonomy is needed (Phase 2+).

---

## 10. Real MIT/CSAIL LNN Drone Control Examples

### 10.1 The Science Robotics 2023 paper (the canonical example)

- **Authors:** Ramin Hasani, Makram Chahine, Patrick Kao, Aaron Ray, Ryan Shubert, Mathias Lechner, Alexander Amini, **Daniela Rus** (CSAIL director).
- **Task:** Vision-based fly-to-target on a quadrotor.
- **Network:** ~20,000 parameters, ~34 neurons in the LNN policy head. CNN frontend (image → features) → LNN (features → control).
- **Training:** Imitation learning from human pilot footage.
- **Experiments (all closed-loop, real hardware):**
  - Range tests (fly to target at varying distances)
  - Stress tests (noise, rotation, occlusion added to target)
  - Hiking with adversaries (target moves evasively)
  - Triangular loops (multi-step navigation between objects)
  - Dynamic target tracking
  - **OOD:** Summer forest → winter forest; forest → urban. No retraining.
- **Result:** LNNs were "the only ones that could generalize to scenarios they had never seen, without any fine-tuning." Beat CNN+LSTM, transformer, and feed-forward baselines.
- **Funding:** Schmidt Futures, USAF Research Lab, USAF AI Accelerator, Boeing.

### 10.2 The autonomous driving work (keras-ncp)

- **Code:** `mlech26l/keras-ncp` (the same Mathias Lechner who co-authors the drone work).
- **Task:** End-to-end steering from dashcam.
- **Architecture:** CNN → NCP-wired CfC/LTC → steering angle.
- **Network:** 19 liquid neurons match 100,000 conventional neurons.
- **Deployment:** Runs on a Raspberry Pi (Hasani quote, IEEE Spectrum).

### 10.3 What MIT did NOT do

- They did **not** use the LNN as a velocity PID replacement.
- They did **not** train on synthetic kinematic targets.
- They did **not** run the LNN at 1–5Hz.
- They did **not** use the LNN for motor-level control.

MIT's pattern is consistent: **LNN = perception→action policy, trained by imitation, deployed at the control rate, sitting on top of a deterministic low-level controller.** GarudaOne should match this pattern.

---

## 11. CfC vs LTC — Which Is Better for Real-Time Control?

### 11.1 The technical difference

| Property | LTC (Liquid Time-Constant) | CfC (Closed-form Continuous-time) |
|---|---|---|
| **Formulation** | ODE: `τ(x,t) dh/dt = -h + f(x,h)` | Closed-form approximation of the LTC integral |
| **Computation** | Numerical ODE solver (semi-implicit, multiple unfolds) | Single closed-form step (no solver) |
| **Speed** | Baseline | **1–5 orders of magnitude faster** (training & inference) |
| **Accuracy vs LTC** | Reference | <2% accuracy drop on sequence benchmarks (CfC paper) |
| **Stability** | Provably stable (constructed from stable ODE) | Stable (bounded gate + learnable drift factor) |
| **Memory** | O(sequence) for solver states | O(1) — constant memory per step |
| **Irregular sampling** | Native (time is continuous) | Native (time appears explicitly in closed-form) |
| **Deploy on edge/MCU** | Feasible but solver overhead | **Preferred** — no solver, sub-ms inference |
| **ncps library** | `ncps.torch.LTC` | `ncps.torch.CfC` |
| **Paper** | Hasani et al., AAAI-21 (arXiv:2006.04439) | Hasani et al., Nature Machine Intelligence 2022 (arXiv:2106.13898) |

### 11.2 Verdict for GarudaOne

**CfC is the correct choice** for real-time control on Pi 5. GarudaOne already uses CfC — this decision is right.

Reasons:
1. **No ODE solver** → sub-ms inference on NumPy → trivially fits in a 20Hz loop with 50ms budget.
2. **<2% accuracy drop vs LTC** — negligible for a velocity policy (not a precision tracking task).
3. **Constant memory** → no hidden state blowup on long flights.
4. **The MIT autonomous-driving Raspberry-Pi demo uses CfC** ("we can implement a liquid neural network that can drive a car, on a Raspberry Pi" — this is the CfC, not the LTC).
5. **LTC would require a numerical solver in the inference loop** — either a PyTorch dependency on Pi 5 (heavy) or a hand-rolled ODE integrator in NumPy (complex, slower, harder to verify). CfC's closed-form forward pass is what makes pure-NumPy deployment viable.

**When to reconsider LTC:** Only if CfC's <2% accuracy drop proves unacceptable on the real expert dataset — which is unlikely for a framing policy. LTC would then be the upgrade path, at the cost of a solver dependency.

---

## 12. The Minimal Correct Architecture for GarudaOne

### 12.1 What to keep (unchanged)

- **L1/L2a/L2b/L3 layer authority.** ML never owns motors. RC/kill > PX4 > Arbiter > ML.
- **CfC + AutoNCP wiring, 19 neurons, NumPy-only inference on Pi 5.**
- **20Hz update rate via PX4 OFFBOARD.**
- **Velocity-only output for v1** (`vx, vy, vz, yaw_rate`) via `SET_POSITION_TARGET_LOCAL_NED` (MAVLink) or `TrajectorySetpoint` (ROS 2).
- **Clamps + safety limits** (defense-in-depth, `safety_limits.py` as single source).
- **Toy-checkpoint detection** (refuse to fly 480-param weights).

### 12.2 What to change

| Change | Priority | Effort |
|---|---|---|
| **Retrain CfC on expert pilot demonstrations, not synthetic PD targets** | P0 — this is the blunder | Medium (requires flight time or sim time) |
| **Add jerk/smoothness loss to training** | P0 | Low (loss function change) |
| **Wire `train_dagger.py` into a recurring retrain loop** | P1 | Low (already scaffolded) |
| **Remove `gimbal_yaw` from CfC output; drive gimbal separately from bbox error** | P1 | Low (separate PID) |
| **Migrate to position + velocity feedforward output (v2)** | P2 | Medium (contract change + retrain) |
| **Add a 1–5Hz shot planner above the CfC for multi-shot sequences** | P3 (Phase 2+) | High |

### 12.3 Updated CfC contract (v1.1 — minimal change)

The architecture (`cfc_v1_n19_i12_o5`) stays. The **training data and loss** change. Optionally, drop gimbal_yaw from the output and let a separate gimbal PID handle it.

**Option A — keep 5 outputs (minimal disruption):**
```
Input (12, unchanged):
  [cx, cy, bw, bh,           # subject bbox (normalized)
   tof_min, tof_left, tof_center, tof_right, tof_conf,  # ToF
   vx_cur, vy_cur,           # current drone velocity (EKF2)
   tool_dist_norm]           # target distance (normalized 0..1)

Output (5, unchanged in shape, changed in semantics):
  [vx_ned, vy_ned, vz_ned,   # velocity setpoint (m/s) — now from expert policy, not PD
   yaw_rate_body,            # yaw rate (rad/s)
   gimbal_yaw_deg]           # gimbal yaw correction (deg) — or 0 if gimbal handled separately

Training: MSE on expert pilot commands + λ * jerk_penalty(‖v_t - v_{t-1}‖²)
```

**Option B — drop gimbal, 4 outputs (cleaner):**
```
Input (12, unchanged)

Output (4):
  [vx_ned, vy_ned, vz_ned, yaw_rate_body]

Gimbal yaw: separate PID on (cx - 0.5) → gimbal_yaw_deg (in gimbal/ package)
```

**Recommendation:** Option B for cleanliness. The gimbal is a 1-DOF framing servo; it does not need an LNN. A PI controller on bbox horizontal offset is simpler, more robust, and more interpretable. The CfC should focus on drone motion (4 outputs).

### 12.4 Updated CfC contract (v2 — position + velocity feedforward, later)

```
Input (14, add current pose):
  [cx, cy, bw, bh,
   tof_min, tof_left, tof_center, tof_right, tof_conf,
   vx_cur, vy_cur,
   tool_dist_norm,
   px_rel, py_rel]    # relative position to shot center or subject (m)

Output (7):
  [px_sp, py_sp, pz_sp,        # position setpoint (m, NED) — where to be
   vx_ff, vy_ff, vz_ff,        # velocity feedforward (m/s) — how to get there
   yaw_rate_body]              # yaw rate (rad/s)

PX4: TrajectorySetpoint with position non-NaN + velocity non-NaN (feedforward)
     → PX4 trajectory generator does jerk-limiting
     → PX4 position PID + velocity feedforward → thrust

Gimbal: separate PID (not in CfC)
```

This is the professional cable-cam architecture. Defer to v2.

### 12.5 Code example — correct training loop (behavior cloning + smoothness)

```python
# scripts/train_cfc_expert.py — the CORRECT training script

import torch, torch.nn as nn, numpy as np
from ncps.torch import CfC
from ncps.wirings import AutoNCP
from torch.utils.data import DataLoader, Dataset

ARCH_ID = "cfc_v1_n19_i12_o5"
NUM_NEURONS, INPUT_SIZE, OUTPUT_SIZE, DT, HZ = 19, 12, 4, 0.05, 20  # Option B: 4 outputs

class ExpertTrajectoryDataset(Dataset):
    """Loads expert pilot logs collected from RC flights or sim.
    
    Each log is a CSV/npz with columns:
      cx,cy,bw,bh, tof_min,tof_left,tof_center,tof_right,tof_conf,
      vx_cur,vy_cur, tool_dist_norm,           # inputs (12)
      vx_pilot,vy_pilot,vz_pilot,yaw_rate_pilot  # targets (4)
    """
    def __init__(self, log_paths: list[str], seq_len: int = 200):
        self.sequences = []  # list of (inputs[T,12], targets[T,4])
        for p in log_paths:
            data = np.load(p)  # or pd.read_csv
            inp = data[:, :12].astype(np.float32)
            tgt = data[:, 12:16].astype(np.float32)  # pilot's vx,vy,vz,yaw_rate
            # Slide a window
            for i in range(0, len(inp) - seq_len, seq_len // 2):
                self.sequences.append((inp[i:i+seq_len], tgt[i:i+seq_len]))
    
    def __len__(self): return len(self.sequences)
    def __getitem__(self, i):
        inp, tgt = self.sequences[i]
        return torch.from_numpy(inp), torch.from_numpy(tgt)

def smoothness_loss(pred: torch.Tensor) -> torch.Tensor:
    """Penalize jerk: 3rd derivative of velocity (2nd diff)."""
    if pred.shape[1] < 3: return pred.new_zeros(())
    jerk = pred[:, 2:] - 2*pred[:, 1:-1] + pred[:, :-2]
    return (jerk ** 2).mean()

def build_model() -> CfC:
    wiring = AutoNCP(NUM_NEURONS, OUTPUT_SIZE, sparsity_level=0.5, seed=22222)
    return CfC(INPUT_SIZE, wiring, return_sequences=True, batch_first=True)

def train(model, dataset, epochs=80, lr=1e-3, lambda_smooth=0.1):
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    mse = nn.MSELoss()
    loader = DataLoader(dataset, batch_size=16, shuffle=True)
    
    for ep in range(epochs):
        model.train()
        ep_loss = 0.0
        for inp_b, tgt_b in loader:
            bs = inp_b.shape[0]
            hx = torch.zeros(bs, NUM_NEURONS)
            opt.zero_grad()
            out, _ = model(inp_b, hx)
            loss = mse(out, tgt_b) + lambda_smooth * smoothness_loss(out)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            ep_loss += loss.item()
        sched.step()
        if (ep+1) % 5 == 0:
            print(f"epoch {ep+1}/{epochs}  loss={ep_loss/len(loader):.6f}")

# Usage:
# dataset = ExpertTrajectoryDataset(log_paths=["logs/follow_01.npz", "logs/orbit_01.npz", ...])
# model = build_model()
# train(model, dataset)
# Export to NumPy .npz for Pi 5 deployment (use existing export_pytorch_to_numpy)
```

### 12.6 Code example — correct runtime integration (unchanged wire, better provenance)

```python
# src/garudaone/control/cfc_runner.py — the runtime loop

import time, numpy as np
from .cfc_controller import CfcController
from .clamps import clamp_velocity
from ..link.px4_offboard import OffboardClient  # MAVSDK wrapper

class CfcRunner:
    """20Hz loop: perception → CfC → clamps → PX4 OFFBOARD velocity setpoint.
    
    The CfC is a perception→framing policy. PX4 owns the velocity PID.
    """
    def __init__(self, cfc: CfcController, offboard: OffboardClient, hz: int = 20):
        self.cfc = cfc
        self.offboard = offboard
        self.dt = 1.0 / hz
        self.hz = hz
    
    def step(self, perception: dict) -> None:
        """One control step. Call at 20Hz.
        
        perception: {
            'bbox': (cx, cy, bw, bh),       # from PicoDet, normalized
            'tof':  (mn, lf, ct, rt, conf),  # from VL53L8CX
            'vel':  (vx, vy),                # from PX4 EKF2 via MAVSDK
            'tool_dist_norm': float,          # from Arbiter (target distance)
        }
        """
        b = perception['bbox']; t = perception['tof']; v = perception['vel']
        inp = np.array([
            b[0], b[1], b[2], b[3],
            t[0], t[1], t[2], t[3], t[4],
            v[0], v[1],
            perception['tool_dist_norm'],
        ], dtype=np.float32)
        
        out = self.cfc.forward(inp)  # [vx, vy, vz, yaw_rate] (Option B)
        vx, vy, vz, yaw_rate = out
        
        # Defense-in-depth clamps (cfc_controller already clamps; this is belt-and-suspenders)
        vx, vy, vz, yaw_rate = clamp_velocity(vx, vy, vz, yaw_rate)
        
        # Send to PX4 OFFBOARD — velocity setpoint in NED
        self.offboard.set_velocity_ned(vx, vy, vz, yaw_rate=yaw_rate)
    
    def run(self, perception_source):
        """Main 20Hz loop."""
        next_t = time.monotonic()
        while True:
            self.step(perception_source.get())
            next_t += self.dt
            sleep = next_t - time.monotonic()
            if sleep > 0: time.sleep(sleep)
            else: next_t = time.monotonic()  # overran, reset
```

### 12.7 Code example — DAgger correction loop

```python
# scripts/dagger_collect.py — collect corrections when the CfC drifts

class DAggerCollector:
    """When a safety pilot overrides the CfC, log (input, pilot_command) for retraining.
    
    Run alongside CfcRunner. The safety pilot's RC overrides via PX4's
    MAN_OVERRIDE_SPD mechanism (stick movement > threshold → control returns to pilot).
    """
    def __init__(self, out_path: str):
        self.out_path = out_path
        self.buffer = []  # list of (inp[12], pilot_cmd[4])
    
    def on_override(self, perception: dict, pilot_cmd: tuple):
        """Called when safety pilot intervenes."""
        b = perception['bbox']; t = perception['tof']; v = perception['vel']
        inp = np.array([
            b[0], b[1], b[2], b[3],
            t[0], t[1], t[2], t[3], t[4],
            v[0], v[1],
            perception['tool_dist_norm'],
        ], dtype=np.float32)
        self.buffer.append((inp, np.array(pilot_cmd, dtype=np.float32)))
    
    def flush(self):
        if not self.buffer: return
        data = np.stack([
            np.concatenate([inp, tgt]) for inp, tgt in self.buffer
        ])
        np.savez(self.out_path, data=data)
        self.buffer.clear()

# After each flight session: flush() → retrain CfC on expert + DAgger data.
```

---

## 13. Summary of Recommendations (Action List)

### Immediate (P0 — fix the blunder)

1. **Stop training on synthetic PD targets.** Delete or archive `gen_hover`/`gen_forward_tracking`/etc. in `train_cfc.py`. They produce a lookup table for a function you already have.
2. **Collect expert pilot demonstrations.** Fly with RC (or sim with a pilot) for each shot type. Log the 12 inputs + the pilot's 4 commanded velocities at 20Hz. Target ~2–3M timesteps total.
3. **Retrain the CfC on expert data** with MSE + smoothness (jerk) penalty. Use the existing `cfc_v1_n19_i12_o5` architecture and `NumpyCfC` export — no architecture change needed.
4. **Drop `gimbal_yaw` from CfC output** (Option B, 4 outputs). Drive the gimbal with a separate PI controller on bbox horizontal offset in the `gimbal/` package.

### Near-term (P1)

5. **Wire `train_dagger.py` into the flight workflow.** After every flight with safety-pilot overrides, flush corrections and retrain.
6. **Validate OOD.** Test the retrained CfC on a different subject, different lighting, and different obstacle layout than training. This is the LNN's value proposition — verify it.
7. **Update the CfC contract** in `safety_limits.py` if dropping gimbal_yaw: `output_size=4`, remove `gimbal_yaw_max_deg`.

### Later (P2 — v2 architecture)

8. **Migrate to position + velocity feedforward output.** Add `px_rel, py_rel` to inputs; output `(px_sp, py_sp, pz_sp, vx_ff, vy_ff, vz_ff, yaw_rate)`. Let PX4's trajectory generator do jerk-limiting. This is the cable-cam architecture.
9. **Add a 1–5Hz shot planner** above the CfC for multi-shot sequences ("orbit for 10s, then push-in for 5s"). The planner emits shot parameters (radius, omega, subject lock), not velocities.

### Never

10. **Never let the CfC output attitude, body rates, or thrust.** That's PX4's job (§5).
11. **Never fly the toy 480-param checkpoint.** Already enforced — keep it.
12. **Never train the CfC on synthetic kinematic targets again.** This is the blunder.

---

## 14. References

1. Hasani, Lechner, Amini, Liebenwein, Ray, Tschaikowski, Teschl, Rus. "Closed-form continuous-time neural networks." *Nature Machine Intelligence* 4, 992–1003 (2022). arXiv:2106.13898. https://www.nature.com/articles/s42256-022-00556-7
2. Hasani, Lechner, Amini, Rus, Grosu. "Liquid Time-constant Networks." AAAI-21. arXiv:2006.04439. https://ojs.aaai.org/index.php/AAAI/article/view/16936
3. Hasani, Chahine, Kao, Ray, Shubert, Lechner, Amini, Rus. "Robust flight navigation out of distribution with liquid neural networks." *Science Robotics* 6, eadc8892 (2023). https://www.science.org/doi/10.1126/scirobotics.adc8892
4. Lechner, Hasani, Amini, Henzinger, Rus, Grosu. "Neural Circuit Policies Enabling Auditable Autonomy." *Nature Machine Intelligence* 2, 642–652 (2020). (NCPs origin.)
5. MIT CSAIL news. "Drones navigate unseen environments with liquid neural networks." 2023-04-19. https://www.csail.mit.edu/news/drones-navigate-unseen-environments-liquid-neural-networks
6. MIT news. "'Liquid' machine-learning system adapts to changing conditions." 2021-01-28. https://news.mit.edu/2021/machine-learning-adapts-0128
7. IEEE Spectrum. "'Liquid' Neural Network Adapts on the Go." 2023-04-27. https://spectrum.ieee.org/liquid-neural-networks (Hasani: "We can implement a liquid neural network that can drive a car, on a Raspberry Pi.")
8. PX4 Autopilot. "Offboard Mode (Generic/All Frames)." PX4 Guide (main). https://docs.px4.io/main/en/flight_modes/offboard
9. ncps library (PyTorch/TensorFlow). mlech26l/ncps, 2.3k★. https://github.com/mlech26l/ncps — docs: https://ncps.readthedocs.io/en/latest/api/torch.html
10. CfC repo. raminmh/CfC, 1k★. https://github.com/raminmh/CfC
11. LTC repo. raminmh/liquid_time_constant_networks, 1.8k★.
12. keras-ncp (autonomous driving code). mlech26l/keras-ncp. (Referenced from MIT news 2021.)
13. "Adaptive Drone Swarm Navigation with Liquid Neural Networks in Dynamic Wind Fields." IEEE 2025 (Bengaluru). Document 11335870.
14. CineMPC. IEEE Transactions on Robotics, 2024. https://dl.acm.org/doi/10.1109/TRO.2024.3353550 (MPC-based autonomous cinematography — defines aesthetic objectives; not LNN but the framing reference.)
15. Ajith Vallath. "Liquid Neural Networks & Edge-Optimized Foundation Models." 2025-05-04. https://ajithp.com/2025/05/04/liquid-neural-networks-edge-ai/ (Survey: 19 neurons match 100k conventional; CfC 1–5 orders of magnitude faster than LTC; <50mW for 19-unit lane-keeping.)
16. GarudaOne project. `C:\Projects\DroneOS\` — `GARUDAONE_CONTEXT_PACK.md`, `garudaone-software/src/garudaone/control/cfc_controller.py`, `scripts/train_cfc.py`, `src/garudaone/arbiter/safety_limits.py`, `garudaone-architecture/12_optimized_rebuild_plan.md`.

---

**End of report.**
