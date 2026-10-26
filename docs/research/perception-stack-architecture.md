# Perception Stack — GarudaOne DroneOS

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - The selected flight profile uses one forward VL53L5CX at 8x8/15Hz; three-sensor/VL53L8CX designs are not active.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - Production VIO/SLAM adapters are absent or deferred.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!NOTE]
> This is a dated research snapshot. Model choices, estimates, and recommendations are not implementation claims. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


**Date:** 2026-07-18
**Hardware:** Raspberry Pi 5 (4× Cortex-A76, 8GB RAM, ARMv8.2-A, I8MM, NO GPU)
**Goal:** Full 360° obstacle awareness + dense depth + object tracking + scene understanding — all on CPU

---

## TL;DR

The Pi 5 has **4 A76 cores and 8GB RAM with no GPU**. The perception stack must fit in ~3 cores and ~4GB RAM (the rest goes to Cactus LFM + CfC + pymavlink + arbiter). Here's what we can run:

| Component | Model/Engine | Size | FPS (Pi 5) | Cores | RAM |
|---|---|---|---|---|---|
| Person detection | PicoDet-S ncnn | 4.7MB | 25+ | 0.5 | 50MB |
| Dense depth | ZipDepth NPU ncnn | ~25MB | 10-15 | 0.5 | 200MB |
| Object tracking | ByteTrack (NumPy) | ~0 | 30+ | 0.1 | 50MB |
| VIO (position) | VINS-Fusion (OpenVINS alt) | ~5MB | 30 | 1.0 | 500MB |
| 360° ToF safety | 3× VL53L8CX (front+back+top) | hardware | 15 | 0.1 | 10MB |
| Scene graph | Custom (PicoDet + depth + VIO) | ~0 | 5-10 | 0.1 | 100MB |
| **Total perception** | | ~35MB | | **~2.3 cores** | **~910MB** |

Remaining for Cactus LFM (1 core, 300MB) + CfC (negligible) + pymavlink (0.1 core) + arbiter = fits in 4 cores, 8GB.

---

## 1. 360° Obstacle Sensing

### The problem

Current: 1× VL53L8CX ToF facing forward (65° FOV, 4m range, 8×8 zones).
Blind spots: **above** (ceiling, fan), **behind** (walls when flying backward), **below** (tables, chairs).

### Solution: 3× VL53L8CX sensors

| Sensor | Direction | Purpose | I2C Address |
|---|---|---|---|
| VL53L8CX #1 | Forward | Subject distance + front obstacles (existing) | 0x52 (default) |
| VL53L8CX #2 | Up | Ceiling/fan detection | 0x53 |
| VL53L8CX #3 | Back | Rear obstacle detection | 0x54 |

**Cost:** ~$30 (3 sensors), ~15g total, ~60mA power
**I2C bandwidth:** 3 × 64 zones × 2 bytes = 384 bytes per read cycle, 15 Hz each
**Code:** `tof.py` already supports multi-zone — extend to multi-sensor

### ToF + Arbiter safety clamps (deterministic, no ML)

```
tof_front < 1.0m → v_max = 0.60 m/s
tof_front < 0.5m → v_max = 0.30 m/s
tof_front < 0.3m → v_max = 0.0 (full stop)

tof_top < 0.5m → vz_max = 0.0 (stop ascending)
tof_back < 0.5m → v_max_backward = 0.0 (stop backward)
```

These are Python `if` statements — no inference, no failure mode, always work.

### Why not single 360° LiDAR?

- Benewake TF03: $150, 360° but single-line (no vertical), 180g
- Livox Mid-360: $300+, too heavy for small drone, 261g
- 3× VL53L8CX: $30, 15g, covers the 3 critical directions, proven code

---

## 2. Dense Depth — ZipDepth on CPU

### What ZipDepth gives us

Current ToF: 8×8 = 64 depth zones in a 65° forward cone. Sparse — a ceiling fan blade falls between zones.

ZipDepth: **full dense depth map from a single camera**. Every pixel gets a depth value. The entire scene in front of the camera is depth-mapped.

### ZipDepth specs

| Spec | Value |
|---|---|
| Parameters | ~6.1M (NPU/mobile variant) |
| Input | Single RGB camera (monocular, 384×384) |
| Output | Dense depth map (per-pixel depth) |
| Zero-shot | Works on any scene without fine-tuning |
| Export | PyTorch → ONNX → ncnn (Pi 5 compatible) |
| Architecture | RepVGG (reparameterized: 3×3+1×1 fused → single 3×3 at inference) |
| ECCV 2026 | State-of-the-art among lightweight methods on 5 benchmarks |

### On Pi 5 (ncnn, INT8 quantized)

- **Estimated FPS:** 10-15 FPS at 384×384 (2 threads)
- **RAM:** ~200MB
- **Model size:** ~25MB (INT8 ncnn)
- **Shares camera feed with PicoDet** (no extra camera)

### What ZipDepth enables

| Capability | ToF only | ToF + ZipDepth |
|---|---|---|
| Forward obstacle distance | 8×8 zones (4m) | Full pixel depth (camera FOV, ~10m) |
| Subject distance for CfC | ToF center (one number) | Dense depth at bbox (accurate) |
| 3D object positions | ❌ | ✅ (bbox + depth → 3D world position) |
| Dense 3D map for SLAM | ❌ | ✅ (depth + VIO pose → 3D point cloud) |
| Ceiling fan (in camera view) | ❌ | ✅ (depth map shows it) |

### Alternatives if ZipDepth is too slow

| Model | Size | FPS (Pi 5 est.) | Notes |
|---|---|---|---|
| ZipDepth NPU | ~25MB | 10-15 | Best accuracy, RepVGG optimized |
| FastDepth (MobileNet) | ~5MB | 20-30 | Faster, less accurate, proven on mobile |
| MiDaS small | ~20MB | 8-12 | Relative depth (not metric) |
| DepthAnything small | ~25MB | 8-12 | Good but heavier |
| Monodepth2 | ~15MB | 15-20 | Older but very efficient |

**Recommendation:** Start with ZipDepth NPU variant. If <8 FPS on Pi 5, fall back to FastDepth.

---

## 3. Object Detection — PicoDet vs Alternatives on CPU

### Current: PicoDet-S ncnn

| Spec | Value |
|---|---|
| Model | PicoDet-S-320 (COCO) |
| Size | 4.7MB (.bin) + 27KB (.param) |
| Input | 320×320 |
| FPS on Pi 5 | 25+ FPS (15ms inference) |
| Classes | 80 (COCO: person, chair, car, etc.) |
| Engine | ncnn (ARM NEon optimized) |
| Accuracy | mAP 30.6 on COCO (good for edge) |

### Alternatives compared

| Model | Size | FPS (Pi 5 est.) | mAP (COCO) | ncnn export | Notes |
|---|---|---|---|---|---|
| **PicoDet-S** (current) | 4.7MB | 25+ | 30.6 | ✅ native | Already running, proven |
| YOLOv8n | 6MB | 15-20 | 37.3 | ✅ (export) | Better accuracy, slower |
| YOLOv10n | 6MB | 15-20 | 38.5 | ✅ | NMS-free (faster post) |
| Gold-YOLO-n | 6MB | 12-18 | 39.6 | ✅ | Better accuracy, heavier |
| RT-DETR-R18 | 20MB | 5-10 | 46.0 | ⚠️ (ViT ops) | Best accuracy but slow on CPU |
| MobileNet-SSD | 5MB | 20-25 | 22.2 | ✅ | Fast but low accuracy |
| RT-DETRv2-S | 20MB | 5-10 | 43.5 | ⚠️ | DETR family needs attention ops |

**Verdict: Keep PicoDet-S.** It's the best speed/accuracy/size tradeoff for CPU edge. RT-DETR is more accurate but 3-5× slower — the attention ops don't map well to ARM NEON without a GPU. PicoDet was designed specifically for edge CPU.

### When to upgrade detection

If we need better accuracy (e.g., detecting small objects like ceiling fans), consider:
1. **PicoDet-M** (slightly bigger, mAP 34.5, ~12ms on Pi 5) — same engine, just bigger
2. **YOLOv8n** (mAP 37.3, ~20ms, 6MB) — if we accept 20 FPS instead of 25
3. **Fine-tune PicoDet** on indoor drone scenes — custom classes (fan, lamp, shelf)

---

## 4. Object Tracking — ByteTrack vs Alternatives on CPU

### Current: ByteTrackLite (NumPy)

| Spec | Value |
|---|---|
| Model | ByteTrack (association-based, no ReID) |
| Engine | Pure NumPy + OpenCV |
| CPU | negligible (0.1 core) |
| FPS | 30+ (limited by detector, not tracker) |
| Tracking | IoU + optical flow propagation |

### Alternatives

| Tracker | Type | CPU cost | ReID? | Notes |
|---|---|---|---|---|
| **ByteTrack** (current) | IoU + flow | ~0.1 core | No | Fast, proven, no extra model |
| BoT-SORT | IoU + ReID | ~0.5 core | Yes (extra NN) | Better occlusion handling, heavier |
| OC-SORT | Observation-centric | ~0.1 core | No | Better than ByteTrack on nonlinear motion |
| NorFair | Generic | ~0.1 core | Optional | Flexible, lightweight |
| DeepSORT | IoU + ReID | ~0.5 core | Yes | Classic, needs ReID model |

**Verdict: Keep ByteTrack.** It's the lightest and our use case (single subject tracking at 25 FPS) doesn't need ReID. If subject occlusion becomes a problem (person walks behind pillar), upgrade to OC-SORT — same CPU cost, better occlusion handling.

---

## 5. VIO (Visual-Inertial Odometry)

### VINS-Fusion on Pi 5

| Spec | Value |
|---|---|
| Engine | VINS-Fusion (optimization-based VIO) |
| Sensors | Camera + IMU (synced) |
| FPS | 30 Hz |
| CPU | ~1 core |
| RAM | ~500MB |
| Drift | ~1% of distance travelled |
| Output | 6-DOF pose + velocity → PX4 EKF2 via MAVLink ODOMETRY |

### Integration with PX4

```
VINS-Fusion → ODOMETRY (#331) MAVLink → PX4 EKF2

PX4 params:
  EKF2_EV_CTRL    = enable external vision (position + yaw)
  EKF2_HGT_REF    = vision (indoor) / baro (outdoor)
  EKF2_EV_DELAY   = tune to VIO pipeline latency (~100ms)
  EKF2_EV_POS_X/Y/Z = VIO sensor offset from body CG
```

### Why VIO is the highest-value addition

Without VIO: indoor drift ~1m/min. Drone can hover but can't navigate.
With VIO: drift ~10cm over entire flight. Drone can fly arcs, return to start, hold position.

---

## 6. Scene Graph — Pi-5 SuperMap Substitute

### What SuperMap does (needs GPU)

SuperMap (CMU, RSS 2026):
1. GroundingDINO + SAM2 → open-vocabulary segmentation (GPU)
2. SuperOdometry → geometric SLAM
3. 3D association → persistent object IDs
4. Scene graph: objects + spatial relations + temporal history

### What we can do on Pi 5 (no GPU)

```
PicoDet (person + object detection, 25 FPS, CPU)
  + ZipDepth (dense depth, 15 FPS, CPU)
  + VINS-Fusion (VIO pose, 30 FPS, CPU)
  + ByteTrack (stable object IDs, 30 FPS, CPU)
  → Scene Graph Builder (pure Python)
```

### Scene graph construction (CPU-only)

```python
# For each PicoDet detection:
#   bbox → 2D pixel coordinates
#   ZipDepth at bbox → metric depth to object
#   VIO pose → drone's 3D position
#   Object 3D position = drone_pose + depth * ray_direction

# SceneGraph:
#   objects: [{id, label, position_3d, last_seen, confidence}]
#   relations: [{a, b, relation (left/right/behind/above)}]
#   temporal: [{id, action (appeared/disappeared/moved)}]

# Query API for LFM:
#   where_is("pillar") → "3m to the left of the subject"
#   objects_in_view() → [{label, distance, direction}]
#   is_path_clear(direction) → True/False
```

### What we lose vs SuperMap

| Capability | SuperMap (GPU) | Pi-5 substitute (CPU) |
|---|---|---|
| Open-vocabulary ("detect red chair") | ✅ GroundingDINO | ❌ Fixed COCO classes only |
| Instance segmentation | ✅ SAM2 | ❌ Bbox only (PicoDet) |
| Dense 3D reconstruction | ✅ SuperOdometry | ✅ VIO + ZipDepth (sparser) |
| Object stable IDs | ✅ | ✅ ByteTrack |
| Temporal history | ✅ | ✅ Custom tracker |
| Scene graph | ✅ | ✅ Custom builder |
| Visual-language queries | ✅ native | ✅ via LFM (JSON scene description) |

We lose open-vocabulary and instance segmentation. But we keep the scene graph, temporal history, and spatial reasoning — which is what the LFM actually needs.

---

## 7. Full Pi-5 Perception Architecture

```
                    ┌──────────────────────────────────────┐
                    │         Raspberry Pi 5 (8GB)         │
                    │                                      │
  Camera ──────────┼──→ PicoDet ncnn (0.5 core, 25 FPS) ──┼──→ detections
  (Pi Cam 3)       │                                      │
                    │──→ ZipDepth ncnn (0.5 core, 15 FPS) ─┼──→ dense depth
                    │                                      │
                    │──→ VINS-Fusion (1 core, 30 FPS) ────┼──→ VIO pose
                    │                                      │
  3× VL53L8CX      │                                      │
  (front/back/top) ┼──→ ToF reader (0.1 core, 15 Hz) ────┼──→ 64×3 zones
                    │                                      │
                    │    ┌─────────────────────────────┐  │
                    │    │   Scene Graph Builder        │  │
                    │    │   (0.1 core, pure Python)    │  │
                    │    │                             │  │
                    │    │  detections + depth + pose  │  │
                    │    │  → 3D object positions      │  │
                    │    │  → stable IDs (ByteTrack)   │  │
                    │    │  → spatial relations        │  │
                    │    │  → temporal history         │  │
                    │    └──────────┬──────────────────┘  │
                    │               │                      │
                    │    ┌──────────▼──────────────────┐  │
                    │    │   Cactus LFM2.5-VL-450M     │  │  ← scene graph as JSON context
                    │    │   (1 core, 300MB)           │  │
                    │    └──────────┬──────────────────┘  │
                    │               │ tool call           │
                    │    ┌──────────▼──────────────────┐  │
                    │    │   Arbiter FSM (safety)      │  │  ← ToF clamps
                    │    │   (0.1 core)                │  │
                    │    └──────────┬──────────────────┘  │
                    │               │ velocity             │
                    │    ┌──────────▼──────────────────┐  │
                    │    │   CfC LNN (NumPy, ~0ms)    │  │  ← perception + VIO state
                    │    └──────────┬──────────────────┘  │
                    │               │ OFFBOARD setpoints   │
                    │    ┌──────────▼──────────────────┐  │
                    │    │   pymavlink (0.1 core)      │  │
                    │    └──────────┬──────────────────┘  │
                    └───────────────┼──────────────────────┘
                                    │ UART
                            ┌───────▼───────┐
                            │   PX4 (STM32)  │
                            │   400 Hz PID    │
                            └─────────────────┘
```

### CPU budget (4 cores total)

| Component | Cores | RAM |
|---|---|---|
| PicoDet ncnn | 0.5 | 50MB |
| ZipDepth ncnn | 0.5 | 200MB |
| VINS-Fusion | 1.0 | 500MB |
| ToF (3× sensors) | 0.1 | 10MB |
| Scene graph builder | 0.1 | 100MB |
| Cactus LFM | 1.0 | 300MB |
| CfC LNN (NumPy) | ~0 | 1MB |
| pymavlink + arbiter | 0.1 | 50MB |
| **Total** | **~3.3** | **~1.2GB** |
| **Free** | **~0.7** | **~6.8GB** |

Fits comfortably. 0.7 cores free for overhead, OS, logging. 6.8GB RAM free for models, buffers, FDR.

---

## 8. CPU-Only Optimization Techniques

### Why CPU can surprise us

| Technique | What it does | Impact |
|---|---|---|
| **INT8 quantization (QAT)** | Train with fake quant, deploy with INT8 ops | 2-4× faster, 4× smaller, <1% accuracy loss |
| **ncnn ARM NEON + I8MM** | Hand-tuned SIMD kernels for ARM | 2-3× faster than generic C++ |
| **RepVGG reparameterization** | Multi-branch training → single conv inference | 3× faster, zero accuracy loss |
| **Knowledge distillation** | Small model learns from large teacher | Small model gets large model accuracy |
| **Operator fusion** | Combine multiple ops into one kernel | 1.5-2× faster |
| **Channel pruning** | Remove unimportant channels | 2× smaller, 1.5× faster |
| **ONNX Runtime ARM** | Optimized graph execution on ARM | Comparable to ncnn, better for some ops |
| **XNNPACK / QNNPACK** | Google's ARM-optimized neural net kernels | 2× faster than PyTorch on ARM |
| **TensorRT for ARM** | NVIDIA's optimizer (if we add Hailo/Jetson later) | 5-10× faster with accelerator |

### What this means

A model that runs at 5 FPS on generic PyTorch can hit 15-20 FPS on ncnn with INT8 quantization + NEON kernels. PicoDet is already proof — 4.7MB model running at 25 FPS on Pi 5. The same optimization path applies to ZipDepth and any other model we add.

**The key insight: the bottleneck isn't the model size, it's the inference engine.** ncnn with ARM NEON + I8MM is purpose-built for this. Cactus's I8MM kernels are the same idea for LLMs. PyTorch is the worst case — never use it for inference on Pi 5.

---

## 9. Hardware Shopping List

| Item | Price | Purpose |
|---|---|---|
| VL53L8CX ×2 (back + top) | ~$20 | 360° obstacle sensing |
| Pi Cam 3 (global shutter) | ~$25 | VIO + PicoDet + ZipDepth (shared) |
| IMU (MPU6050 or BMI270) | ~$5 | VIO (synced to camera) |
| **Total** | **~$50** | Full perception stack |

Already have: VL53L8CX (front), Pi 5, PX4 flight controller.

---

## 10. Implementation Phases

| Phase | What | Weeks | Deliverable |
|---|---|---|---|
| **P1** | Add 2× VL53L8CX (back + top) + ToF code | 1 | 360° hard safety |
| **P2** | VINS-Fusion VIO → PX4 EKF2 | 2-3 | Indoor position, no drift |
| **P3** | ZipDepth ncnn export + integration | 2 | Dense depth map |
| **P4** | Scene graph builder (PicoDet + depth + VIO) | 2 | LFM spatial reasoning |
| **P5** | PicoDet fine-tune on indoor scenes (fan, lamp) | 3 | Better indoor detection |
| **P6** | (Future) GPU companion + full SuperMap | 6+ | Open-vocab semantic SLAM |

---

## References

1. ZipDepth — Tosi et al., ECCV 2026. https://zipdepth.github.io/ · https://github.com/geoeo/zipdepth
2. SuperMap — Zhao et al., RSS 2026. https://superodometry.com/supermap · Requires NVIDIA GPU ≥16GB
3. VINS-Fusion — HKUST. https://github.com/HKUST-Aerial-Robotics/VINS-Fusion · ARM ROS2 port exists
4. PicoDet — PaddlePaddle, ncnn export. 4.7MB, 15ms on Pi 5.
5. ByteTrack — Zhang et al., ECCV 2022. Association-based tracking.
6. VL53L8CX — STMicroelectronics, 8×8 ToF, 4m range, 65° FOV, I2C.
7. PX4 VIO integration — https://docs.px4.io/main/en/computer_vision/visual_inertial_odometry
8. ncnn — Tencent, ARM NEON optimized inference engine. https://github.com/Tencent/ncnn
9. OpenVINS — RPNG, MSCKF-based VIO. https://docs.openvins.com/
10. ORB-SLAM3 — feature-based VI-SLAM with loop closure. https://github.com/UZ-SLAMLab/ORB_SLAM3
