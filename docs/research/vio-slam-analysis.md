# VIO & SLAM Analysis for GarudaOne

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - Production VIO/SLAM adapters are absent or deferred.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!NOTE]
> This is a dated research snapshot. Model choices, estimates, and recommendations are not implementation claims. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


**Author:** GarudaOne Research
**Date:** 2026-07-18
**Status:** Decision support — VIO/SLAM addition for Pi 5 + PX4 cinematography drone
**Target reader:** GarudaOne architect (deciding whether to add VIO/SLAM)

---

## TL;DR (Read This First)

GarudaOne currently has **no visual pose estimation**. PX4 EKF2 fuses IMU + GPS + baro only, which means:

- **Outdoors:** fine (GPS gives absolute position).
- **Indoors:** EKF2 dead-reckons from IMU alone and **drifts ~1 m/min**. Position hold, waypoints, and smooth arcs all degrade. Cinematography indoors is effectively impossible in any autonomous mode.

**VIO fixes the indoor drift problem.** It is cheap (~1 core, ~500 MB on Pi 5), well-trodden (VINS-Fusion), and integrates into PX4 via one MAVLink message. **VIO should be added.** It is the single highest-value perception addition for a drone that must work indoors.

**SLAM adds persistent spatial memory** — a map that remembers where obstacles, pillars, and furniture are even when the camera isn't looking at them. This is what lets an LFM reason *"fly around the table, not through it."* Full SLAM (ORB-SLAM3) is 1–2 cores / 1–2 GB and is a worthwhile **Phase 2** addition once VIO is stable.

**Semantic SLAM (SuperMap-style)** turns the map into a **queryable 4D scene graph** — objects with stable IDs, spatial relations, and temporal history — which is exactly what a cinematography LFM needs to plan shots around scene geometry. SuperMap itself requires an **NVIDIA GPU ≥16 GB VRAM** and **cannot run on Pi 5** as-is, but its *architecture* is the target. A Pi-5-feasible subset (VIO + lightweight scene graph from PicoDet detections) captures most of the value.

**Recommendation:** Add VIO (VINS-Fusion, mono+IMU) now → add ORB-SLAM3 or a custom lightweight scene graph in Phase 2 → keep SuperMap as the architectural north star for when a GPU companion (Jetson Orin Nano / Coral / Hailo) is added.

---

## 1. What is VIO? (Plain English)

**Visual-Inertial Odometry** answers one question, over and over, as fast as possible:

> *"Since the last frame, how far have I moved, and in which direction, in 3D?"*

It combines two sensors that are weak alone but strong together:

| Sensor | What it gives | What it lacks |
|---|---|---|
| **Camera** (mono or stereo) | Tracks feature points across frames — *"that corner moved 12 px right"* | No absolute scale (mono), noisy when motion is tiny, fails in textureless/blurred frames |
| **IMU** (accelerometer + gyro) | High-rate (100–1000 Hz) acceleration & angular velocity — gives scale & bridges camera blind spots | Integrates error → drifts in seconds; bias changes with temperature |

**How it works (the loop):**

1. **Predict** at IMU rate (200+ Hz): integrate accelerometer & gyro to propagate pose and velocity. This is fast but accumulates error.
2. **Update** at camera rate (20–60 Hz): detect/match feature points (e.g. KLT optical flow or ORB), build a sliding-window of recent frames, and run a **joint optimization** (VINS-Fusion, OKVIS) or **Kalman update** (OpenVINS/MSCKF) that reconciles the visual measurements with the inertial prediction. The visual step *corrects* the IMU drift and recovers metric scale.
3. **Output** a 6-DOF pose (position + orientation) + velocity, in a local frame anchored to where the system started.

**Sensors required:**
- 1× monocular camera (or 1× stereo pair for better robustness/scale) — global shutter preferred, ~30–60 fps.
- 1× IMU — ideally synchronized to the camera; the PX4 FC's IMU works but time-sync to the camera frame is the hard part.
- **No GPS, no LiDAR, no depth sensor required.**

**What VIO is NOT:** it does *not* build a persistent map, does *not* recognize loop closures reliably (some do, weakly), and does *not* know what objects are in the scene. It is pure ego-motion estimation. The "map" it maintains internally is a sliding window of ~10 recent keyframes discarded after a few seconds.

**Drift:** VIO still drifts, but ~**100× slower** than IMU-only — on the order of **~1 m per 100 m travelled** (≈1%) for a well-tuned system, vs ~1 m/min for bare IMU integration. For a drone that stays within a room, VIO drift is effectively negligible over a shoot.

---

## 2. What is SLAM? (Plain English)

**Simultaneous Localization And Mapping** does two things VIO does not:

1. **Builds a persistent map.** Every keyframe and every 3D landmark (feature point) is kept, not discarded. The map grows over the flight and survives the session.
2. **Performs loop closure.** When the drone re-enters a previously-seen area, SLAM recognizes it ("I've been here before") and **optimizes the entire trajectory** to be consistent with that observation. This is what kills long-term drift — VIO drift accumulates forever; SLAM drift gets corrected every time you revisit a place.

**The SLAM pipeline (beyond VIO):**

| Stage | VIO does this? | SLAM adds |
|---|---|---|
| Feature extraction & matching | ✅ | ✅ |
| IMU propagation | ✅ | ✅ |
| Local sliding-window optimization | ✅ | ✅ |
| **Local map (keyframes + landmarks, kept)** | ❌ (discarded) | ✅ |
| **Loop closure detection (DBoW2 place recognition)** | ❌ | ✅ |
| **Global pose-graph / bundle-adjustment optimization** | ❌ | ✅ |
| **Map save/reload across sessions** | ❌ | ✅ (ORB-SLAM3) |

**What "building a map" concretely means:** a sparse point cloud of 3D landmarks, each tied to the keyframes that observed it, plus a pose graph of all keyframes. This is a **geometric** map — it knows *where* points are but not *what* they are. It's a cloud of anonymous 3D dots.

**Semantic SLAM** (Hydra, Kimera, SuperMap) goes further: it clusters the point cloud into *objects*, attaches *labels* ("chair", "pillar", "person"), and builds a **scene graph** — nodes are objects/rooms, edges are spatial relations ("on", "behind", "near"). This is the layer an LLM/VLM can reason over.

**Sensors for SLAM:** same as VIO (camera + IMU). Stereo or RGB-D makes the map denser and more robust; mono+IMU works (ORB-SLAM3 supports it). Loop closure is the main added cost vs VIO.

---

## 3. VIO vs SLAM vs Neither (Current) — Comparison for GarudaOne

| Capability | **Neither** (current: EKF2 + IMU + GPS + baro) | **VIO** (VINS-Fusion) | **SLAM** (ORB-SLAM3 / semantic) |
|---|---|---|---|
| Outdoor position | ✅ GPS | ✅ GPS + VIO | ✅ GPS + VIO + loop closure |
| **Indoor position** | ❌ drifts ~1 m/min | ✅ ~1% of distance travelled | ✅ near-zero (loop closure) |
| Velocity estimate for CfC | IMU-integrated (noisy) | ✅ direct from VIO (smooth) | ✅ same as VIO |
| Yaw reference indoors | magnetometer (distorted by metal) | ✅ visual yaw (absolute in local frame) | ✅ visual yaw |
| Altitude indoors | baro (drifts with pressure) | ✅ visual scale | ✅ visual scale |
| **Persistent map** | ❌ | ❌ (sliding window only) | ✅ survives the session |
| **Remembers off-camera obstacles** | ❌ | ❌ | ✅ |
| Loop closure (drift reset) | ❌ | ❌ (or weak) | ✅ |
| Object-level scene understanding | ❌ | ❌ | ✅ (semantic SLAM only) |
| "Where is the pillar?" query | ❌ | ❌ | ✅ (semantic only) |
| LFM scene-graph reasoning | ❌ | ❌ | ✅ (semantic only) |
| CPU on Pi 5 | ~0 (EKF2 on FC) | ~1 core, ~500 MB | 1–2 cores, 1–2 GB |
| GPU required | none | none | none (geometry) / GPU (semantic) |
| Sensors to add | none | 1 camera + (synced IMU) | same as VIO |
| Integration effort | — | ~1–2 weeks | ~3–6 weeks |
| Cinematography impact | indoor shots impossible | **enables indoor shots** | **enables "fly around the table" shots** |

**Bottom line:** VIO is the difference between "can fly indoors autonomously" and "cannot." SLAM is the difference between "flies blind to scene structure" and "reasons about scene structure."

---

## 4. What VIO Gives Us That We Don't Have Now

### 4.1 Indoor position without GPS
This is the headline. Today, indoors, EKF2 has **no position measurement** — only IMU integration. The drone literally does not know where it is. Position-hold degenerates to attitude-only hold (rate mode-ish); waypoints are meaningless; CfC's smooth-arc commands have no position reference to track against. VIO gives a **bounded-drift 3D position** in a local frame, making all autonomous modes functional indoors.

### 4.2 No drift (vs PX4 EKF2 alone, ~1 m/min indoors)
The EKF2 indoor failure mode is well documented on the PX4 forums: without GPS or optical flow or vision, the EKF's position states are pure inertial dead-reckoning, and accelerometer bias + integration error produce ~1 m/min of horizontal drift (worse vertically without baro assist). A 60-second indoor hover can put the drone 1 m from where it thinks it is — enough to hit a wall.

VIO's drift budget is ~**1% of distance travelled**, and crucially it **does not grow with time** when stationary (visual features pin the pose). A 5-minute indoor hover stays within ~5 cm. This is the difference between "flies into walls" and "holds rock-steady."

### 4.3 Better velocity estimates for CfC input
CfC (the cinematography flight controller) commands smooth arcs by tracking position/velocity references. Today its velocity input is **EKF2's velocity, which indoors is IMU-integrated** — noisy, laggy, and biased. VIO produces a **direct, smooth, visually-grounded velocity** at camera rate (30–60 Hz), which CfC can use to:
- Track moving subjects with lower lag (subject velocity = VIO velocity − image-based subject velocity).
- Execute dolly/arc moves with accurate feedforward (CfC knows its own true ground velocity, not a noisy guess).
- Hand off cleanly between position hold and velocity mode (both now share the same high-quality state).

### 4.4 Bonus: visual yaw indoors
Magnetometers indoors are unreliable (rebar, motors, monitors cause multi-degree yaw errors). VIO yaw is **absolute in its local frame** — the drone knows which way it's pointing relative to where it started, with no magnetic interference. This matters for framing: "keep the camera pointed at the subject" requires accurate yaw.

---

## 5. What SLAM Gives Us Beyond VIO

VIO answers *"where am I?"* SLAM also answers *"what's around me, and where was I?"* For a cinematography drone, the SLAM-only value (beyond VIO) falls into four buckets:

### 5.1 Persistent map (remembers obstacles even when not visible)
VIO only sees what's in the current sliding window. If the drone pans away from a pillar, VIO forgets it. SLAM keeps the pillar in the map. Concretely:
- The drone flies down a hallway, looks back, and the hallway geometry is still in the map — useful for backing out or planning a return path.
- Collision avoidance can query "is there anything within 2 m in the direction I'm about to move?" against the **full map**, not just the current frame's depth.
- A ReFrame-style "orbit this point" command can reason about occluders that aren't currently visible.

### 5.2 "Where is the pillar?" — spatial memory
With SLAM, you can ask the map a geometric query: *"give me the 3D position of the vertical structure at bearing θ."* With VIO you cannot — there is no map to query. This enables:
- LFM prompt: *"keep the pillar on the left of the frame as you orbit the subject"* — needs to know where the pillar is even when it's behind the camera.
- Pre-flight scene survey: fly a quick lap, build the map, then plan shots that use the known geometry.
- Repeatable shots: "fly the same arc as last take" requires a persistent map to anchor against.

### 5.3 SuperMap-style: object-level semantic map for VLM reasoning
This is the step from *anonymous 3D points* to *named objects with history*. SuperMap (and Hydra, Kimera-Semantic) attach labels and stable IDs to map clusters:
- Object: `pillar_03` at (x,y,z), radius 0.4 m, last seen 12 s ago, status: unchanged.
- Object: `person_01` (the subject) at (x,y,z), trajectory: moving left at 0.8 m/s.
- Spatial relation: `pillar_03` is `behind` `person_01` from the camera's current view.

A VLM/LFM can reason over this directly: *"frame the shot so pillar_03 is in the background, person_01 in foreground, camera at 1/3 rule position."* This is qualitatively different from reasoning over raw pixels — it's **symbolic spatial reasoning**, which is where LLMs are strong.

### 5.4 Scene graph for LFM to reason about ("fly around the table, not through it")
The scene graph is the LFM-facing API. Instead of the LFM receiving an image and having to re-derive geometry every frame, it receives a compact graph:

```
room_0
├── table_0 (center=(2.1, 1.5, 0.0), dims=(1.8×0.9×0.75))
│   ├── on: laptop_0, mug_0
│   └── near: chair_0, chair_1
├── pillar_0 (center=(3.0, 0.0, 0.0→2.5), radius=0.3)
└── person_0 (the subject, moving)
```

The LFM can now plan: *"to get from current pose to a 3/4 front view of person_0, I must route around table_0 (extent 1.8×0.9) and clear pillar_0 (radius 0.3)."* This is the **"fly around the table, not through it"** capability. Without a scene graph, the LFM would have to infer all of this from the image every frame — expensive, slow, and unreliable.

For GarudaOne specifically, the scene graph is what turns the LFM from "follow the subject" into "**direct the shot** given the scene structure."

---

## 6. SuperMap Specifically

### 6.1 What it is
**SuperMap** (AirLab, CMU — Zhao, Chen, Zhu, Li, Yao, Zantout, Kim, Wang, Zhang, Scherer; **RSS 2026**) is a **training-free spatio-temporal SLAM** system that builds a *living spatial memory*: a **4D scene graph** where every object has a stable identity, a 3D extent, spatial relations to other objects, **and a temporal history** (when it appeared, disappeared, moved). Open source (code releasing after RSS; repo: `github.com/superxslam/SuperMap`).

### 6.2 How it works (architecture)
SuperMap fuses two asynchronous streams:

1. **High-frequency geometric SLAM** — built on **SuperOdometry** (the AirLab odometry stack). Runs at sensor rate, produces the drone pose and a dense geometric map. This is the "where am I and what's the geometry" backbone.
2. **Asynchronous open-vocabulary perception** — runs a detector/segmenter **when compute is available**, not every frame. Supports **GroundingDINO**, **YOLOE**, or pre-baked detections. Open-vocabulary means you query with free text (*"chair"*, *"red mug"*, *"the pillar on the left"*) rather than a fixed class list.
3. **3D-aware instance association** — fuses the 2D detections with the 3D geometric map via **SAM2** segmentation masks, lifting 2D boxes into 3D object volumes. Critically, it maintains **stable object IDs across occlusions and appearance changes** — the same chair is `chair_0` whether seen from the front, back, or after being temporarily occluded.
4. **4D scene graph serialization** — emits a per-frame JSON schema: `bbox3d, label, id, center, spatial_relations, status, latest_stamp`. Downstream consumers (VLM, LFM, planner) get one shared interface.

### 6.3 What it adds beyond standard SLAM
- **Temporal dimension:** objects have a history (`status: appeared|unchanged|moved|disappeared`, `latest_stamp`). The LFM can ask *"did the chair move since the last take?"* — useful for continuity.
- **Open vocabulary:** no retraining to detect "c-stand" or "jib" — just add to `config/prompts.yaml`.
- **Stable identities:** the same object keeps its ID across the whole deployment; the LFM doesn't re-reason about "a new chair" every time the camera pans back.
- **VLN-native:** designed for visual-language navigation — i.e., *"fly to the red chair and look back at the door"* is a first-class query.

### 6.4 Can it run on Pi 5?
**No, not as-is.** From the SuperMap README (verified 2026-07-18):

> **Requirements:** Ubuntu 22.04 / 24.04, **NVIDIA GPU with ≥ 16 GB VRAM**, Python ≥ 3.10. ROS2 Jazzy for live mode.

The blocker is the perception stream: **GroundingDINO + SAM2** are GPU-heavy models (SAM2 alone is several GB of weights and wants a modern NVIDIA GPU). The geometric SLAM backbone (SuperOdometry) is GPU-light and *could* run on Pi 5, but the semantic value of SuperMap is precisely the GPU-dependent part.

**Options to get SuperMap-class capability on Pi 5:**
1. **Add a GPU companion** (Jetson Orin Nano 8GB, Hailo-10, Coral). Run SuperMap on the accelerator, keep Pi 5 for Cactus/PicoDet/CfC. This is the clean path and the long-term plan.
2. **Run SuperMap's perception stream at low rate on a remote ground station** (laptop with GPU) over WiFi — the drone streams RGB, the ground station runs GroundingDINO+SAM2 and sends back object detections. Latency-bound but feasible for non-realtime shot planning.
3. **Reimplement the *architecture* on Pi 5 with lightweight substitutes:** VINS-Fusion (VIO) + PicoDet (we already have it) for detections + a custom 3D-association + scene-graph module. Loses open-vocabulary and SAM2-quality segmentation, but gains the **stable-ID, spatial-relation, temporal-history** structure that's the real value for an LFM. This is the **Pi-5-feasible subset** recommended below.

**Verdict:** SuperMap is the **architectural north star**, not the immediate deployment target. Reimplement the structure; plan to run the real thing when a GPU accelerator is added.

---

## 7. Pi 5 Resource Budget

### 7.1 Current load (Pi 5 8GB, 4× A76 @ 2.4 GHz)
| Component | CPU | RAM | Notes |
|---|---|---|---|
| Cactus LFM | ~1 core | ~300 MB | local LLM inference |
| PicoDet (ncnn) | ~0.5 core | ~50 MB | subject detection |
| CfC (NumPy) | negligible | <50 MB | cinematography controller |
| pymavlink + ROS2 bridge | ~0.1 core | ~50 MB | PX4 comms |
| OS + overhead | ~0.4 core | ~500 MB | Linux, drivers |
| **Total in use** | **~2.0 cores** | **~1.0 GB** | |
| **Free** | **~2.0 cores** | **~6.0 GB** | of 4 cores / 8 GB |

### 7.2 Adding VIO (VINS-Fusion)
| Component | CPU | RAM |
|---|---|---|
| VINS-Fusion (mono+IMU) | ~1 core | ~500 MB |
| Camera driver (v4l2/libcamera) | ~0.1 core | ~100 MB |
| **VIO subtotal** | **~1.1 cores** | **~600 MB** |

**After VIO:** ~0.9 cores free, ~5.4 GB free. ✅ **Comfortable.** Cactus keeps its core, PicoDet keeps its half-core, CfC stays snappy. Thermal headroom is the main concern — sustained 3 cores on Pi 5 needs active cooling (fan + heatsink), which a drone should have anyway.

### 7.3 Adding full SLAM (ORB-SLAM3) on top
| Component | CPU | RAM |
|---|---|---|
| ORB-SLAM3 (mono+IMU, with loop closure) | 1–2 cores | 1–2 GB |
| **After VIO + SLAM** | **~0–0.9 cores free** | **~3.4–4.4 GB free** |

⚠️ **Tight but feasible** if ORB-SLAM3 lands at the low end (1 core / 1 GB). At the high end (2 cores / 2 GB) the Pi 5 is maxed and Cactus inference latency will suffer — Cactus's 1-core budget gets squeezed. Mitigations:
- Run ORB-SLAM3's local BA thread at lower priority (`nice`/`chrt`).
- Cap the local-map size (fewer keyframes → less BA work).
- Throttle Cactus to 0.5 core when SLAM is mapping (CfC doesn't need full LLM rate during stable cruise).

**Verdict:** VIO + Cactus + PicoDet + CfC fits cleanly. **Adding ORB-SLAM3 on top is feasible but requires CPU arbitration.** A GPU accelerator (even a Hailo-8) would offload PicoDet and free a core for SLAM.

### 7.4 Thermal / power note
Pi 5 at sustained ~3 cores draws ~6–8 W and hits ~70 °C with a passive heatsink — needs active fan. On a drone this is normal (flight already needs cooling). Budget ~2 W extra for the VIO camera. Total companion-computer power ~10–12 W — well within a typical drone's 30–60 W companion budget.

---

## 8. PX4 Integration — Feeding VIO/SLAM to EKF2

### 8.1 The path (verified against ModalAI's VOXL/PX4 guide)
PX4's EKF2 accepts external vision/odometry via two MAVLink messages:

| MAVLink msg | ID | Use when |
|---|---|---|
| `VISION_POSITION_ESTIMATE` | #102 | Minimal — position + orientation only |
| `ODOMETRY` | #331 | **Preferred** — position + orientation + velocity + angular rate. ModalAI/VOXL uses this. |

**GarudaOne should use `ODOMETRY` (#331)** because CfC and EKF2 both benefit from the velocity field. This matches the context's reference to VISION_POSITION_ESTIMATE but upgrades to the richer message.

### 8.2 Frame conventions (the part that bites people)
PX4 expects VIO data as **body pose w.r.t. a local NED-ish frame** (X forward, Y right, Z down) originating where the drone booted. VIO outputs **IMU pose w.r.t. VIO frame** (often X right, Y down, Z forward, optical convention). You must apply two transforms:
1. **Camera/IMU → body frame** (static extrinsic: mount offset + rotation — `vio_wrt_body`).
2. **VIO frame → local NED** (gravity alignment: rotate so Z points down along gravity; yaw is whatever VIO started with).

Get these wrong and the drone flies sideways or into the floor. ModalAI's `voxl-vision-px4` has the reference implementation; the transforms live in their open-source repo. **Budget real time for frame calibration — it is the #1 integration gotcha.**

### 8.3 EKF2 parameters to set (PX4)
Key params (verify against current PX4 version — names evolve):
```
EKF2_EV_CTRL        = enable external vision for position + yaw (bitmask)
EKF2_HGT_REF        = set to vision (not baro) when indoors
EKF2_EV_DELAY       = tune to VIO pipeline latency (typically 50–150 ms)
EKF2_EV_POS_X/Y/Z   = VIO sensor offset from body CG (mount position)
EKF2_EV_ROT_*       = VIO frame rotation w.r.t. body
EKF2_OF_CTRL        = disable if using VIO (avoid double-counting)
```
`EKF2_EV_DELAY` is critical — if it's wrong, EKF2 fights the VIO and you get oscillation. Measure end-to-end latency (camera capture → VIO output → MAVLink arrival) and set the param to that.

### 8.4 ROS 2 alternative path
If using ROS 2 (which GarudaOne may for the Cactus/CfC bridge), the `OffboardControlMode` + `TrajectorySetpoint` path lets you send **setpoints** computed from VIO rather than feeding VIO to EKF2. But for *state estimation*, the MAVLink ODOMETRY path is simpler and lets PX4's EKF2 do the fusion (it handles sensor disagreement gracefully). **Recommendation: feed VIO to EKF2 via MAVLink ODOMETRY; use ROS 2 Offboard only for CfC's setpoint commands.**

### 8.5 AprilTag relocalization (cheap persistent anchor)
ModalAI's stack also supports AprilTag relocalization — place a tag at a known world location, and when the drone sees it, the VIO local frame snaps to a fixed world frame. This gives **repeatable absolute pose across reboots** without full SLAM. Cheap interim for "fly the same shot twice" before committing to SLAM.

---

## 9. Options Ranked by Complexity

### 9a. VINS-Fusion (VIO only, lightweight) — ⭐ **Phase 1 pick**
- **What:** Optimization-based VIO from HKUST. Mono+IMU, stereo+IMU, or stereo-only. ROS1原生, ROS2 ports exist (`yangfuyuan/vins_fusion_ros2`, `JanekDev/VINS-Fusion-ROS2-humble-arm` — explicit ARM/Humble support).
- **Cost:** ~1 core, ~500 MB on Pi 5. No GPU. Camera + synced IMU.
- **Accuracy:** ~1% drift on EuRoC. Handles aggressive motion. Loop closure is weak/optional (it's VIO, not SLAM).
- **Integration:** Mature. PX4 has documented VIO integration. ROS2 ARM ports exist. 1–2 weeks to a flying demo.
- **Risk:** Low. Hardest part is camera-IMU time sync and frame calibration.
- **Gets us:** Indoor position, no drift, good velocity, visual yaw. **Everything in §4.**

### 9b. ORB-SLAM3 (full SLAM, heavier) — **Phase 2 candidate**
- **What:** Feature-based monocular/stereo/RGB-D VI-SLAM with strong loop closure (DBoW2) + global bundle adjustment. The de-facto academic SLAM baseline.
- **Cost:** 1–2 cores, 1–2 GB on Pi 5. No GPU. Same sensors as VIO.
- **Accuracy:** Best-in-class on EuRoC; loop closure kills long-term drift. Map persists and can be saved/reloaded (Atlas feature).
- **Integration:** Heavier — ORB-SLAM3 has a finicky build (C++11, g2o, DBoW2, Eigen). ROS2 wrappers exist but quality varies. 3–6 weeks to robust.
- **Risk:** Medium. Build pain, parameter tuning, atlas/relocalization edge cases.
- **Gets us:** Everything in §4 **plus** §5.1 (persistent map), §5.2 (spatial memory), loop-closure drift reset. **Not** §5.3/§5.4 (no semantics — it's geometric SLAM).

### 9c. SuperMap (semantic SLAM + VLM, heaviest) — **Architectural north star**
- **What:** SuperOdometry (geometric) + GroundingDINO/SAM2 (open-vocab perception) + 3D instance association → 4D scene graph with temporal history. RSS 2026, open source.
- **Cost:** **NVIDIA GPU ≥16 GB VRAM.** Cannot run on Pi 5 (§6.4).
- **Accuracy:** Geometric via SuperOdometry (LiDAR-inertial grade when LiDAR present); semantic via foundation models.
- **Integration:** On a Jetson Orin / GPU box: ROS2 Jazzy package, colcon build, subscribes to RGB+PointCloud+Odometry. On Pi 5: not supported.
- **Risk:** High for Pi-5 deployment (requires hardware change); low on supported GPU hardware.
- **Gets us:** Everything in §5 — persistent semantic map, stable object IDs, open-vocab queries, 4D temporal history, VLN-native. **The full cinematography-LFM dream.**
- **Pi-5 strategy:** Reimplement the *architecture* (VIO + PicoDet detections → 3D association → scene graph + temporal status) without GroundingDINO/SAM2. Plan to run the real thing when a GPU companion is added.

### 9d. Alternatives — VINS-Fusion's competitors
| Option | Type | Pi 5 fit | Notes |
|---|---|---|---|
| **OpenVINS** | VIO (MSCKF filter) | ✅ ~1 core, ~400 MB | Filter-based → more predictable CPU than optimization-based VINS. Clean codebase, good docs. Strong alternative to VINS-Fusion if you prefer Kalman over optimization. Loop closure is *loosely* bolted on via VINS-Fusion. |
| **Kimera-VIO** | VIO + (optional) mesher/pose-graph | ✅ ~1–1.5 cores, ~600 MB | MIT-SPARK. Stereo+IMU focus. Has a sibling **Kimera-Semantic** (RGB-D scene graph) and **Kimera-Multi** (multi-robot). If you want a VIO that's on-ramp to a scene-graph ecosystem, Kimera is the path. Heavier than VINS-Fusion. |
| **Kimera (full)** | VIO + 3D mesh + 2D/3D scene graph | ⚠️ ~2 cores, ~1.5 GB, RGB-D preferred | The "scene graph without SAM2" option. Needs depth (RGB-D or stereo+depth-est). Closer to §5.3/§5.4 than ORB-SLAM3, lighter than SuperMap. Strong Phase-2.5 candidate. |
| **SVO Pro / SVO 2.0** | VIO (semi-direct) | ✅ ~0.5 core (lighter) | Semi-direct (features + direct pixels) → can be lighter than VINS. Less mature ecosystem, harder to get help. |
| **HybVIO** | VIO + SLAM | ✅ runs on phone-class ARM | Designed for mobile/embedded. Has a Raspberry Pi benchmark in the paper. Strong Pi-5 candidate if VINS-Fusion proves too heavy. |
| **OpenVSLA** | (newer; verify scope) | TBD | Treat as research — evaluate if it matures. |
| **MONO-HYDRA++** | Monocular scene graph (RGB+IMU) | ⚠️ laptop GPU in paper (15 fps on 3080) | Exactly the *semantic* capability on a *monocular* drone — but GPU-bound in the paper. A CPU-only subset (PicoDet instead of their learned semantics) is the Pi-5 path. Useful architectural reference for §5.3/§5.4. |

**Ranking for GarudaOne, Pi 5 only, no new hardware:**
1. **VINS-Fusion** (Phase 1) — proven, ARM ROS2 ports, lowest risk.
2. **OpenVINS** (Phase 1 alt) — if you prefer filter-based & cleaner code.
3. **ORB-SLAM3** (Phase 2) — when persistent map / loop closure is needed.
4. **Kimera-VIO → Kimera (scene graph)** (Phase 2.5) — on-ramp to semantic scene graph without SAM2.
5. **HybVIO** (fallback) — if VINS/OpenVINS both prove too heavy on Pi 5.
6. **SuperMap** — deploy when a GPU companion (Jetson Orin Nano / Hailo) is added.

---

## 10. Recommendation — What to Add, When, and How

### 10.1 The decision in one line
> **Add VIO now. Add geometric SLAM in Phase 2. Keep SuperMap as the architectural target and add it (or a GPU companion to run it) in Phase 3.**

### 10.2 Phased plan

**Phase 1 — VIO (weeks 1–3). Goal: fly indoors autonomously.**
- Pick **VINS-Fusion** (mono+IMU). Use `JanekDev/VINS-Fusion-ROS2-humble-arm` as the ARM ROS2 base.
- Hardware: 1× global-shutter mono camera (Pi Cam 3 or Arducam OV9281) + IMU. Time-sync is the hard part — use a camera with hardware trigger synced to a Pi GPIO, or accept ~10 ms soft sync and set `EKF2_EV_DELAY` accordingly.
- Integration: VINS-Fusion → `ODOMETRY` (#331) MAVLink → PX4 EKF2. Set `EKF2_EV_CTRL`, `EKF2_HGT_REF=vision`, tune `EKF2_EV_DELAY`.
- Frame calibration: budget 3–5 days. Verify with a known-move ground-truth test (tape measure).
- Acceptance: <20 cm drift over a 5-min indoor hover; CfC arc commands track within 10 cm indoors.
- Deliverable: indoor position hold + waypoints + CfC arcs all functional. **This alone unlocks indoor cinematography.**

**Phase 1.5 — AprilTag relocalization (week 4, optional).**
- Add 1 AprilTag at a known world location for shot-repeatable absolute pose across reboots. Cheap insurance before committing to full SLAM.

**Phase 2 — Geometric SLAM (weeks 5–10). Goal: persistent map + loop closure.**
- Add **ORB-SLAM3** (mono+IMU) *alongside* VINS-Fusion, OR replace VINS-Fusion with ORB-SLAM3's VIO mode + enable loop closure. (Running both is wasteful; ORB-SLAM3's VIO is fine.)
- CPU arbitration: `nice`/`chrt` the local-BA thread; cap keyframe count; throttle Cactus to 0.5 core during mapping.
- Acceptance: <5 cm drift over a 30-min indoor session with loop closure; map save/reload works; "fly the same arc twice" succeeds.
- Deliverable: persistent geometric map; CfC can query "is anything within R in direction d?"

**Phase 2.5 — Lightweight scene graph (weeks 11–16). Goal: LFM-facing spatial API.**
- Build a custom module (not SuperMap) that:
  - Takes PicoDet detections (we already have them) + VIO/SLAM pose.
  - Projects 2D boxes into 3D using VIO depth (or stereo if added) → 3D object volumes.
  - Maintains stable object IDs via IoU + 3D-center association across frames.
  - Emits the SuperMap JSON schema (`bbox3d, label, id, center, spatial_relations, status, latest_stamp`).
  - Exposes a query API to Cactus/LFM: `get_objects_in_view()`, `where_is("pillar")`, `relation(a, b)`.
- This is the **Pi-5-feasible subset of SuperMap** — same interface, lighter perception (PicoDet not GroundingDINO, no SAM2). Loses open-vocabulary but gains the scene-graph + temporal-history structure that's the real LFM value.
- Deliverable: LFM can reason *"fly around the table, not through it"* using the scene graph.

**Phase 3 — GPU companion + real SuperMap (months 6+). Goal: full semantic VLN.**
- Add a GPU accelerator: **Jetson Orin Nano 8GB** (~$250, 40 TOPS, runs SuperMap) or **Hailo-8** (~$70, 26 TOPS, runs SAM2/GroundingDINO) as a Pi 5 HAT.
- Migrate perception to the accelerator; keep Pi 5 for Cactus/CfC/SLAM.
- Run actual SuperMap (GroundingDINO + SAM2 + SuperOdometry) → open-vocabulary 4D scene graph.
- Deliverable: *"fly to the red chair and frame the door behind it"* as a natural-language shot command.

### 10.3 What NOT to do
- **Don't start with SuperMap on Pi 5.** It won't run (16 GB VRAM requirement). You'll burn weeks discovering this.
- **Don't add SLAM before VIO.** VIO is the 80% value; SLAM is the next 15%; semantic SLAM the last 5%. Going straight to SLAM doubles integration risk for marginal extra gain.
- **Don't skip frame calibration.** VIO-to-body and VIO-to-NED transforms are where 90% of "my VIO doesn't work" posts come from. Budget the time.
- **Don't run VIO and SLAM simultaneously long-term.** Pick one state estimator. If SLAM's VIO mode is good enough, drop standalone VIO.

### 10.4 Decision criteria for "do we even need SLAM/SuperMap?"
Given the user's framing — *"if we feel the need then it must be included"* — the honest test:

- **If GarudaOne only shoots outdoors with GPS:** VIO still helps (better velocity for CfC, visual yaw) but is optional. SLAM is overkill. **Stop at Phase 1.**
- **If GarudaOne shoots indoors with static scenes (one room, one subject):** VIO is required; SLAM is optional (VIO drift is low enough for a single room). **Phase 1, maybe Phase 2.**
- **If GarudaOne shoots indoors across multiple rooms / wants repeatable shots / wants the LFM to direct around scene structure:** VIO + SLAM + lightweight scene graph required. **Phases 1 → 2 → 2.5.**
- **If GarudaOne wants natural-language shot direction ("orbit the subject with the pillar in background"):** all of the above + Phase 3 GPU companion for real SuperMap. **Phases 1 → 2 → 2.5 → 3.**

The cinematography use case — *especially* the LFM-directs-the-shot vision — puts GarudaOne in the third or fourth bucket. **VIO is unconditionally worth it; SLAM is very likely worth it; SuperMap-class semantics is worth it as soon as a GPU companion is affordable.**

---

## References (verified 2026-07-18)

- **SuperMap** — Zhao et al., "SuperMap: A Spatio-Temporal SLAM System for Visual-Language Navigation," RSS 2026. Repo: https://github.com/superxslam/SuperMap · Project: https://superodometry.com/supermap · Requirements confirmed: Ubuntu 22.04/24.04, NVIDIA GPU ≥16 GB VRAM, Python ≥3.10, ROS2 Jazzy. Built on SAM2, GroundingDINO, YOLOE, ByteTrack.
- **VINS-Fusion** — HKUST-Aerial-Robotics, optimization-based multi-sensor state estimator. https://github.com/HKUST-Aerial-Robotics/VINS-Fusion · ROS2 ARM port: https://github.com/JanekDev/VINS-Fusion-ROS2-humble-arm · ROS2 port: https://github.com/yangfuyuan/vins_fusion_ros2
- **ORB-SLAM3** — feature-based VI-SLAM with loop closure (DBoW2) + Atlas. The academic SLAM baseline.
- **OpenVINS** — MSCKF-based VIO, RPNG. https://docs.openvins.com/ · IMX95/ARM benchmark port: https://github.com/kylefoxaustin/openvins-imx95
- **Kimera-VIO / Kimera** — MIT-SPARK, VIO + mesh + scene graph. https://github.com/MIT-SPARK/Kimera-VIO
- **HybVIO** — Särkkä et al., real-time VIO with a Raspberry Pi benchmark. arXiv:2106.11857.
- **MONO-HYDRA++** — real-time monocular 3D scene graph (RGB+IMU), drone-targeted. arXiv:2605.17661 · 15 fps on NVIDIA 3080.
- **PX4 VIO integration** — ModalAI "How to Autonomously Navigate with PX4" (MAVLink VISION_POSITION_ESTIMATE #102 vs ODOMETRY #331, frame conventions, AprilTag relocalization). https://www.modalai.com/blogs/blog/how-to-autonomously-navigate-with-px4 · MAVLink common message set: https://mavlink.io/en/messages/common.html
- **VI-SLAM comparison** — Lbulovic et al., "Visual-Inertial SLAM for Unstructured Outdoor Environments," arXiv:2408.01716 (benchmarks ORB-SLAM3, VINS-Fusion, OpenVINS, Kimera, SVO Pro, HFNet-SLAM, AirSLAM).
- **VIO-shootout** — CPU/memory comparison on EuRoC: https://github.com/0xWILL225/vio-shootout

---

*End of report.*
