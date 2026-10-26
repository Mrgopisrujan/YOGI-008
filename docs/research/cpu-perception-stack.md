# CPU-Only Edge Perception Stack for Drones — Research Report

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - The selected flight profile uses one forward VL53L5CX at 8x8/15Hz; three-sensor/VL53L8CX designs are not active.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!NOTE]
> This is a dated research snapshot. Model choices, estimates, and recommendations are not implementation claims. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


**Target:** GarudaOne autonomous cinematography drone
**Hardware:** Raspberry Pi 5 — 4× Cortex-A76 @ 2.4 GHz, 8 GB LPDDR4X, ARMv8.2-A with I8MM + dotprod + FP16, NO GPU
**Current stack:** PicoDet-S (ncnn, 4.7 MB, ~15 ms) + ByteTrack + VL53L8CX ToF
**Goal:** CPU-only perception stack for 360° obstacle avoidance, dense depth, tracking, scene understanding
**Date:** 2026-07-18

> Numbers below are synthesized from published papers, GitHub READMEs, community benchmarks
> (rpi-yolo-benchmark by kadirmertabatay, Qengineering repos, Ultralytics Pi guide, Roboflow
> trackers comparison, ZipDepth ECCV 2026 paper, ncnn DeepWiki, OpenCV DNN docs, Forasoft
> tracker writeup). Where a number is marked **~est** it is an extrapolation from a sibling
> platform (Pi 4, Jetson, iPhone) using core-count / clock / IPC scaling — treat as a planning
> estimate, not a measured value. Run your own benchmark on the actual Pi 5 before committing.

---

## TL;DR — Recommended Stack

| Role | Model | Engine | Size | Pi 5 FPS (est) | Notes |
|---|---|---|---|---|---|
| Detection (primary) | **PicoDet-S** (existing) or **Gold-YOLO-N** | ncnn INT8 | ~4–6 MB | **45–70 FPS** | Keep PicoDet; Gold-YOLO-N is the accuracy upgrade |
| Detection (alt) | YOLOv8n | ncnn INT8 | ~6 MB | 25–40 FPS | Best ecosystem, slightly slower than PicoDet |
| Detection (DETR-grade) | RT-DETR-R18 | ONNX Runtime / OpenVINO | ~77 MB FP / ~20 MB INT8 | **~2–5 FPS** | Too heavy for real-time; use offline only |
| Open-vocab detection | **YOLO-World v2-S** (reparameterized) | ncnn | ~30–50 MB | **~3–8 FPS** | Only viable CPU grounding option |
| Tracking | **ByteTrack** (existing) | C++ | <100 KB | **>500 FPS** on tracker alone | Keep. OC-SORT if nonlinear motion dominates |
| Monocular depth | **ZipDepth base** | ncnn (RepVGG encoder fuses to plain conv) | ~24 MB FP / ~6 MB INT8 | **~8–15 FPS @ 256×320** | Best CPU depth option in 2026; Depth-Anything-V2-Small is the fallback |
| Segmentation | **RepViT-SAM** (a.k.a. EdgeSAM class) | ncnn | ~40 MB | **~3–8 FPS encoder** | Point/box-prompt only; no full-image free segmentation at real-time |
| Scene graph | **DSFlash** (YOLOv8 backbone variant) | ncnn | backbone + small relation head | **~5–15 FPS** with YOLOv8n backbone | The only realistic CPU SGG path; use sparse relation head |

**Hard truths for Pi 5 CPU-only:**
1. **No real-time transformer detector.** RT-DETR, GroundingDINO, SAM2-full are all GPU/TensorRT stories. CPU variants exist but they are 1–5 FPS, not 30.
2. **The CPU is compute-bound, not memory-bound.** IJERT 2026 paper shows YOLOv8n on Pi 5 sustains ~2.6 FPS FP32 at 100% A76 utilization before throttle — the Roofline classifies it as arithmetic-bound. **FP16/INT8 is therefore mandatory**, not optional. Pi 5's I8MM + dotprod extensions give ncnn a real INT8 speedup (2–3× per ncnn docs).
3. **Reparameterization is the secret weapon.** PicoDet, Gold-YOLO-N, ZipDepth, YOLO-World-v2 all use RepVGG-style blocks that train multi-branch but fuse to a single conv at inference — this is why they win on CPU.
4. **Tracker choice barely matters for CPU cost.** ByteTrack, OC-SORT, NorFair are all <2 ms / frame on Pi 5. The ReID-feature trackers (BoT-SORT-ReID, Deep-OC-SORT) add a CNN feature pass per detection and become the dominant cost.
5. **Dense depth at 30 FPS on CPU is not realistic** with current models. Budget for 8–15 FPS depth and fuse with the ToF (VL53L8CX) + optical flow for the rest.

---

## 1. RT-DETR on ncnn/CPU

**What it is:** Baidu's CVPR 2024 "Real-Time Detection Transformer" — first end-to-end (NMS-free) detector to beat YOLO on accuracy at comparable GPU FPS. Hybrid encoder + transformer decoder.

**Variants (official lyuwenyu/RT-DETR):**

| Variant | Backbone | Params | FLOPs | COCO mAP | T4 GPU FPS |
|---|---|---|---|---|---|
| RT-DETR-R18 (smallest official) | ResNet-18vd | **20 M** | 60 G | 46.9 | 108 |
| RT-DETR-R34 | ResNet-34vd | 31 M | 92 G | 48.9 | 74 |
| RT-DETR-R50 | ResNet-50vd | 42 M | 136 G | 53.0 | 108 |
| RT-DETR-L | R50vd-m | 32 M | 108 G | 53.0 | 114 |
| RT-DETR-X | R200vd | 67 M | 234 G | 54.8 | 74 |

**Can it run on ncnn/CPU?** Technically yes — the official repo lists ONNX Runtime, TensorRT, and OpenVINO as supported backends, and the ONNX export converts cleanly. ncnn support is **community-only and flaky** because:
- The hybrid encoder uses deformable attention operators (`MultiScaleDeformableAttention`) that ncnn does not have a native fused kernel for — they fall back to a slow generic path.
- The transformer decoder has cumsum / topk / gather ops that need custom ncnn plugin layers.
- A Pinto model zoo / community fork exists but is not maintained upstream.

**Smallest variant:** RT-DETR-R18 (20 M params, 60 GFLOPs). There is no official "nano" RT-DETR. Third-party "Mobile RT-DETR" papers (2025–2026) report ~2000 ms inference on embedded ARM — i.e. **~0.5 FPS**, which is worse than vanilla R18 because they trade FLOPs for ops that CPUs hate.

**ARM CPU performance (Pi 5, 4× A76):**
- ONNX Runtime, RT-DETR-R18, FP32, 640×640: **~250–350 ms** per frame (DETR-AE-Mamba paper reports 292 ms for R18 on comparable ARM-class hardware via ONNX Runtime) → **~3–4 FPS**.
- INT8 quantized via OpenVINO NNCF: **~150–250 ms** → **~4–7 FPS**.
- ncnn (if it loads): expect **300–500 ms** due to unfused attention.

**Pi 5 feasibility:** ❌ **Not real-time.** Fine for offline / keyframe analysis (e.g. one grounding pass per second for scene labeling), but cannot be the primary 30 FPS detector. **Keep PicoDet for the loop, use RT-DETR-R18 only as an offline "high-accuracy" pass on keyframes.**

**Export:** ONNX ✅ (official), TensorRT ✅, OpenVINO ✅, ncnn ⚠️ (needs custom plugins).

---

## 2. OpenCV DNN Module on Pi 5

**What it is:** OpenCV's built-in inference module — zero-dependency, ships with the OpenCV apt package, supports ONNX / TF / Caffe / Darknet / Torch formats.

**Backends available on Pi 5 (aarch64, 64-bit Pi OS):**

| Backend | Works on Pi 5? | Notes |
|---|---|---|
| `DNN_BACKEND_OPENCV` (default CPU) | ✅ | Pure OpenCV CPU path with NEON. Layer fusion (conv+bn+relu) automatic. |
| `DNN_BACKEND_OPENVINO` | ✅ (via `openvino` pip + OpenCV built with `-DWITH_OPENVINO=ON`) | The prebuilt `opencv` apt package does **not** ship OpenVINO linkage. You either build OpenCV from source against OpenVINO, or skip the OpenCV wrapper and use the `openvino` Python/C++ API directly. |
| `DNN_BACKEND_ONNXRUNTIME` | ✅ (build OpenCV with `-DWITH_ONNX=ON` and link `onnxruntime`) | Same caveat — not in the apt package. Usually simpler to call ONNX Runtime directly. |
| `DNN_BACKEND_CUDA` | ❌ | No NVIDIA GPU on Pi 5. |
| `DNN_BACKEND_VKCOM` | ⚠️ | Vulkan backend compiles, but Pi 5's V3DV GPU is a tile-based rasterizer with no compute throughput story — slower than CPU for inference. Don't use. |
| `DNN_BACKEND_ARMNN` | ⚠️ | Requires ACL/compute library build; rarely worth it on Pi 5 vs ncnn. |

**Targets on Pi 5:** `DNN_TARGET_CPU` ✅, `DNN_TARGET_OPENCL` ❌ (no OpenCL driver stack by default; V3DV is Vulkan-only), `DNN_TARGET_VULKAN` ⚠️ (works but slow).

**Practical recommendation:** OpenCV DNN is great for **rapid prototyping and reading ONNX files with zero build pain**, but for production on Pi 5 use **ncnn** (detection/depth) or **OpenVINO runtime directly** (if you need INT8 calibration tooling). OpenCV DNN's INT8 story is weak; it runs quantized models but does not calibrate them.

**OpenVINO on Pi 5:** Officially supported since OpenVINO 2023.3 — `pip install openvino` works on aarch64. Intel's own benchmarks and the Yury Gorbachev post show YOLO inference on Pi 5 ARM improved ~6.5× year-over-year with OpenVINO. The Raspberry Pi Foundation's own tutorial ("Run Ultralytics YOLO on Raspberry Pi with OpenVINO") is the canonical install path. INT8 via NNCF works on ARM CPU.

**ONNX Runtime on Pi 5:** `pip install onnxruntime` works on aarch64. Default CPU EP uses MLAS with NEON. No CUDA/TensorRT/CoreML EPs on Pi 5. Generally **slower than ncnn for the same model** on Pi 5 (MLAS is good but ncnn's hand-tuned A76/i8mm kernels win), but **easier operator coverage** for transformer models (RT-DETR, SAM) that ncnn struggles with.

---

## 3. ByteTrack vs BoT-SORT vs OC-SORT vs NorFair — CPU

**Key fact (Forasoft, Roboflow tracker comparison):** on CPU, the *tracker itself* is cheap (Kalman + Hungarian <2 ms). The cost driver is **whether the tracker needs a ReID CNN feature per detection**.

| Tracker | ReID CNN? | CMC? | Pi 5 cost/frame (est) | MOT17 MOTA | MOT17 IDF1 | MOT17 HOTA | Strength |
|---|---|---|---|---|---|---|---|
| **ByteTrack** | ❌ | ❌ | **~1–2 ms** | 80.3 | 71.3 | 61.3 | Cheapest, robust to low-conf detections |
| **OC-SORT** | ❌ | ❌ | ~1–3 ms | 78.0 | 77.5 | 63.2 | Best for nonlinear motion (camera-moving) |
| **SORT** | ❌ | ❌ | <1 ms | 79.5 | 79.3 | 62.1 | Baseline, fragile to occlusion |
| **BoT-SORT** | ✅ (optional) | ✅ (ECC or sparse OF) | ~5–20 ms (with ReID) | 80.5 | 80.1 | 65.0 | Best accuracy when ReID CNN is affordable |
| **NorFair** | ✅ (pluggable) | ❌ | ~1–10 ms (depends on distance fn) | n/a (custom) | n/a | n/a | Most flexible; you supply the distance function |
| **Deep OC-SORT** | ✅ | ✅ | ~10–30 ms | 78.4 | 79.3 | 65.4 | OC-SORT + appearance, for crowded scenes |

**For GarudaOne (drone, camera moving, no ReID budget):**
- **Keep ByteTrack** — it is what you have, it is the cheapest, and for a drone with mostly linear inter-frame motion it is excellent.
- **Switch to OC-SORT** if you find ID switches during fast yaw/translation maneuvers — OC-SORT's observation-centric re-update handles nonlinear motion much better, at near-zero extra CPU.
- **Skip BoT-SORT/Deep-OC-SORT** unless you can afford a separate 4 MB ReID CNN pass per frame. That CNN pass is the bottleneck, not the tracker math.
- **NorFair** is attractive because you can plug a *geometric* distance (IoU + 3D centroid distance from the ToF) instead of a CNN feature — that gives you tracker + 3D association in one shot with no CNN cost. Worth prototyping.

**Pi 5 feasibility:** ✅ All four run real-time. ByteTrack at >500 FPS standalone is normal.

---

## 4. ZipDepth on ncnn CPU + Lightweight Depth Alternatives

### ZipDepth (ECCV 2026, fabiotosi92/ZipDepth)

- **Architecture:** RepVGG-style reparameterizable encoder (4 hierarchical stages) + SPPF + cross-scale neck + FPN decoder with convex (sub-pixel) upsampling. Distilled from Depth-Anything-V2-Large over 14.1 M multi-domain images.
- **Size:** **6.1 M params, 3.0 GFLOPs** at default resolution. The `zipdepth_base.pth` variant uses `nn.Unfold` for the convex upsampling; `zipdepth_lite.pth` swaps to a cheaper upsampler for export.
- **Reparameterization win:** All RepVGG blocks fuse to plain 3×3 convs at inference time → **clean ncnn/TensorRT/CoreML export** with no custom ops. This is the single biggest reason to pick ZipDepth over Depth-Anything on CPU.
- **Reported speed:** **34.4 FPS @ ~397 mJ/frame on a 15 W Jetson Orin NX GPU** (per the project page). The encoder has ~77 FPS throughput on Jetson GPU per the LinkedIn post.
- **Accuracy:** Best AbsRel on NYUv2 (8.4) and ScanNet (8.8) among lightweight models; approaches Depth-Anything-V2-Large quality.

**Pi 5 CPU estimate (no published Pi 5 number exists):**
- Jetson Orin NX GPU is ~100 GFLOP/s FP16. Pi 5's 4× A76 with I8MM is roughly 30–50 effective GFLOP/s for INT8 conv. ZipDepth is 3 GFLOPs/frame.
- Extrapolation: **~10–15 FPS FP16, ~15–25 FPS INT8** at 256×320 input on Pi 5 with ncnn.
- At 512×512 (full-res decode via the convex upsampler): expect **~3–6 FPS** — too slow for control loop, fine for sparse keyframe depth.

**Realistic Pi 5 plan:** Run ZipDepth at 256×320, INT8, ~10–15 FPS, and use it as a **dense depth prior** that you fuse with the VL53L8CX ToF (8×8, 60 FPS) + optical-flow scale drift. Not a 30 FPS dense depth replacement — that does not exist on CPU in 2026.

**Export:** PyTorch ✅, ONNX ✅ (clean — reparameterized), ncnn ✅ via pnnx, CoreML ✅, TensorRT ✅. **No custom ops. This is the cleanest depth export in 2026.**

### Alternatives

| Model | Params | Accuracy (NYUv2 AbsRel) | Pi 5 CPU FPS (est) | Notes |
|---|---|---|---|---|
| **ZipDepth base** | 6.1 M | **0.084** (best lightweight) | 10–15 INT8 | **Recommended.** Reparameterized, clean export. |
| **Depth-Anything-V2-Small** | 24.8 M | ~0.094 | 3–6 FP16, ~5–10 INT8 | Bigger, slightly worse on NYUv2, but stronger zero-shot on weird domains. ONNX export clean; ncnn export possible but the ViT-DPT head has reshape/interpolate ops that need care. |
| **Depth-Anything-V1-Small** | 24.8 M | ~0.099 | 3–6 | V2 supersedes it. |
| **FastDepth** (DW) | ~3.5 M | ~0.115 | ~20–30 INT8 | 178 FPS on TX2 GPU, 27 FPS on TX2 CPU. Fastest but worst accuracy. Trained on NYUv2 only → poor zero-shot outdoors. Only valid if you fine-tune on drone video. |
| **MiDaS v3.1 Small** | ~22 M | ~0.090 (relative) | 4–8 FP16 | Older; V2/ZipDepth supersede. |
| **DepthAnything-V2-Large** | 335 M | ~0.057 | **<1 FPS** | Not feasible on Pi 5. Use as the *teacher* for distillation, not inference. |
| **Lite-Mono** | ~3 M | ~0.107 | ~15–25 | Good self-supervised KITTI option if you have drone video to train on. |

**Pick:** **ZipDepth base, INT8, ncnn, 256×320.** If its zero-shot outdoor quality disappoints on drone footage, fine-tune it on a small drone-video dataset with Depth-Anything-V2-Large as the teacher (the ZipDepth authors already did this — replicate their distillation recipe).

---

## 5. MobileNet-SSD / YOLOv8n / Gold-YOLO / PicoDet — CPU Edge Comparison

All numbers are **ncnn, INT8 where available, 640×640 input, Pi 5 4× A76 @ 2.4 GHz, inference only (no preprocess/NMS)** unless noted. "Pi 4 @ 1950" column from Qengineering benchmarks; Pi 5 ≈ 2.0–2.5× Pi 4 for ncnn INT8.

| Model | Params | FLOPs | COCO mAP | ncnn INT8 size | Pi 4 @1950 FPS | **Pi 5 FPS (est)** | Export to ncnn |
|---|---|---|---|---|---|---|---|
| **PicoDet-S** (your current) | 1.0 M | 0.6 G | 30.6 (320 input) / ~33 (640) | 4.7 MB | ~30–45 | **45–70** | ✅ (Paddle2ONNX → ncnn) |
| **PicoDet-M** | 2.8 M | 1.5 G | 36.1 | ~10 MB | ~15–25 | ~25–40 | ✅ |
| **YOLOv8n** | 3.2 M | 8.7 G | 37.3 | ~6 MB (INT8) / 12 MB FP16 | ~10–15 | **25–40** | ✅ (Ultralytics export, mature) |
| **YOLOv8s** | 11.2 M | 28.6 G | 44.9 | ~22 MB INT8 | ~4–6 | ~10–15 | ✅ |
| **Gold-YOLO-N** | ~3.5 M | ~6 G | **39.9** | ~7 MB INT8 | ~12–18 | **~30–45** | ✅ (Huawei noah, ONNX → ncnn) |
| **Gold-YOLO-S** | ~8 M | ~21 G | 46.4 | ~16 MB | ~5–8 | ~12–20 | ✅ |
| **YOLOv10n** | 2.3 M | 6.7 G | 38.5 | ~5 MB | ~12–18 | ~30–45 | ✅ |
| **YOLO26n** | — | — | ~38–40 | ~5 MB | ~15–20 | **~35–50** | ✅ (Ultralytics, up to 43% faster CPU than v8 per Datature) |
| **MobileNetV2-SSDLite** | ~3.4 M | ~0.8 G | ~22 (COCO, 320 input) | ~5 MB | ~25–40 | ~50–80 | ✅ (ncnn has example) |
| **MobileNetV3-SSDLite-Large** | ~3.4 M | ~0.8 G | ~25 | ~5 MB | ~25–40 | ~50–80 | ✅ (ncnn example) |
| **NanoDet-Plus** | ~1.2 M | ~0.9 G | ~27 | ~4 MB | ~40–60 | ~70–100 | ✅ |

**Interpretation for GarudaOne:**

1. **Your PicoDet-S is already an excellent CPU detector.** 1 M params, 30.6 mAP, 45–70 FPS est on Pi 5 — this is a great primary detector. Do not switch without a measured reason.
2. **Gold-YOLO-N is the accuracy upgrade** if you need +9 mAP (39.9 vs 30.6) and can pay ~2× the latency. Its RepVGG-style GD mechanism fuses cleanly for ncnn. The Huawei PINTO model zoo has Gold-YOLO-Body-Head-Hand running at ~5 ms per inference on Pi 4 with 4 threads (TFLite INT8) — that extrapolates to **~2–3 ms (300+ FPS) on Pi 5** for the body/head/hand sub-task at 128×160 input. At 640×640 it is back to ~30–45 FPS.
3. **YOLOv8n is the ecosystem choice** — best tooling, every tracker/quantizer/exporter supports it first. Slightly slower than PicoDet-S on Pi 5 (~30 vs ~50 FPS) but +7 mAP.
4. **MobileNet-SSD family is the speed king but the accuracy is poor** (22–25 mAP vs 30–40 for the YOLOs). Only pick it if you have a fixed, small class set and need every last FPS — e.g. a dedicated "is-there-a-person-in-my-path" detector running in parallel with a richer model.
5. **YOLO26n** is the newest CPU-optimized YOLO (Feb 2026, Datature reports "up to 43% faster CPU inference than YOLOv8"). Worth benchmarking head-to-head with PicoDet-S on your Pi 5 — it may take the primary slot.

**Pi 5 feasibility:** ✅ for all of these at real-time rates. The question is *which accuracy/latency point*, not *whether*.

---

## 6. OpenVINO on ARM / Pi 5 vs ncnn

**Does OpenVINO work on Pi 5?** ✅ **Yes, officially.** Since OpenVINO 2023.3 the ARM/aarch64 CPU plugin is a first-class target. `pip install openvino` on 64-bit Pi OS gives you a working `Core()` that sees `device="CPU"`. The Raspberry Pi Foundation's official tutorial uses it for Ultralytics YOLO.

**Performance vs ncnn (Pi 5, YOLO family):**

| Workload | ncnn INT8 | OpenVINO FP32 | OpenVINO INT8 (NNCF) | ONNX Runtime |
|---|---|---|---|---|
| YOLOv8n @ 640 | ~30–40 FPS | ~5–8 FPS | ~15–25 FPS | ~10–15 FPS |
| YOLOv8s @ 640 | ~10–15 FPS | ~2–3 FPS | ~6–10 FPS | ~4–6 FPS |
| RT-DETR-R18 @ 640 | ⚠️ plugin issues | ~3–4 FPS | ~5–7 FPS | ~3–5 FPS |
| SAM2-Hiera-Tiny encoder | ⚠️ not supported | ~1–2 FPS | ~2–4 FPS | ~2–3 FPS |

**Why ncnn usually wins on Pi 5 CPU:**
- Hand-tuned NEON + I8MM + dotprod kernels for conv/deconv/depthwise. The `convolution_arm_i8mm.cpp` kernel uses the SMMLA instruction for 2:4 INT8 matmul — this is the single biggest Pi 5 win and OpenVINO does not exploit it as aggressively.
- Layer fusion (conv+bn+relu+padding) is more aggressive in ncnn for CNN detectors.
- No runtime overhead — ncnn is a static lib; OpenVINO has a heavier runtime and plugin loader.

**When OpenVINO wins:**
- **INT8 calibration tooling (NNCF).** ncnn has no calibrator; you bring quantized weights from elsewhere. NNCF gives you a one-shot PTQ + QAT pipeline with accuracy-aware quantization.
- **Transformer models** (RT-DETR, SAM, SegFormer). OpenVINO has fused kernels for multi-head attention, deformable attention, LayerNorm — ncnn does not.
- **Mixed-precision / per-layer quantization.** OpenVINO lets you keep sensitive layers in FP32 and quantize the rest; ncnn is all-or-nothing per layer.

**Pi 5 recommendation:** **ncnn for the detection + depth loop** (PicoDet/Gold-YOLO/ZipDepth — all pure CNN, all reparameterized). **OpenVINO + NNCF for the offline / keyframe transformer models** (RT-DETR-R18, SAM2-Tiny, YOLO-World) where you need INT8 calibration and fused attention. Run the OpenVINO models on a separate thread at 1–5 FPS for scene labeling, not in the control loop.

---

## 7. CPU-Only Optimization Tricks

### INT8 Quantization (the big one on Pi 5)

- **Why it matters on Pi 5 specifically:** The Cortex-A76 implements **ARMv8.2 I8MM** (the `SMMLA` instruction — 2× INT8xINT8→INT32 matmul per cycle) and **dotprod** (`SDOT`/`UDOT`). ncnn's `convolution_arm_i8mm.cpp` kernel uses these and the ncnn DeepWiki reports **2–3× inference speedup + 4× model size reduction** on supported platforms. Pi 5 is exactly that platform.
- **PTQ (post-training):** Easiest path — export ONNX → quantize with **PPQ**, **PP-Lite**, **ONNX Runtime static quantization**, or **OpenVINO NNCF** → convert to ncnn with `onnx2ncnn` + INT8 table. Expect ~1–3% mAP drop on YOLO/PicoDet.
- **QAT (quantization-aware training):** Best accuracy. Ultralytics supports QAT export. PicoDet has a QAT recipe in PaddleDetection. **Recommended workflow:** take PicoDet-S, fine-tune 10 epochs with QAT on your drone-specific class set, export INT8 ncnn → recovers most of the PTQ mAP loss.
- **Pitfall:** INT8 quantization on CPU *can* be slower than FP16 if the runtime does not have INT8 kernels (e.g. ONNX Runtime issue #6732 — INT8 SSD slower than FP32 because QLinearConv fell back to a reference kernel). **ncnn and OpenVINO have real INT8 kernels on A76; ONNX Runtime's coverage is hit-or-miss — verify before shipping.**

### Pruning

- **Structured (channel) pruning** is the only kind that helps CPU. Unstructured sparse pruning needs sparse kernels, which ncnn does not have — sparse weights run at dense speed.
- Workflow: train → rank channels by activation magnitude / Taylor importance / BN gamma → prune 30–50% → fine-tune → distill from unpruned teacher. Ultralytics has channel-prune; PaddleDetection has `slim` recipes for PicoDet.
- Realistic gain: 1.3–1.8× speedup at <2% mAP drop on YOLOv8n/PicoDet-S. **Distillation is what recovers the accuracy — see below.**

### Knowledge Distillation

- **The single best CPU accuracy booster.** Train a tiny student (PicoDet-S / YOLOv8n) to mimic a big teacher (RT-DETR-R50 / YOLOv8m / Depth-Anything-V2-Large).
- Ultralytics has a `yolov8_distillation` pattern (garlic-byte repo); PaddleDetection ships PicoDet distillation recipes; ZipDepth is itself a distillation product (DA-V2-Large → 6.1 M student).
- **Recipe for GarudaOne:** Use RT-DETR-R50 (offline, on a workstation) to soft-label your drone video, then distill into PicoDet-S with feature-map + logit loss. Expect to recover most of the mAP gap to the teacher at the student's original latency.
- CVPR 2022 "Detecting Vehicles on the Edge" showed YOLOv3→YOLOv2 distillation recovering ~5 mAP on a pruned edge student. Same pattern applies to YOLOv8m→YOLOv8n.

### Operator Fusion (engine-level, free)

- ncnn, OpenCV DNN, OpenVINO all do **conv+bn+relu** and **conv+add** fusion automatically.
- RepVGG / RepConv blocks (used in PicoDet, Gold-YOLO, ZipDepth, YOLO-World-v2) **fuse 3-branch (1×1 + 3×3 + identity) training blocks into a single 3×3 conv at deploy time** — this is why these models are disproportionately fast on CPU. Prefer architectures that use RepVGG-style blocks.
- OpenCV DNN (per the OpenCV forum + DeepWiki) fuses ReLU/Sigmoid/BatchNorm into the preceding conv/fc. No action needed.

### Other tricks

- **FP16 storage, FP32 accumulation:** ncnn's `use_fp16_packed` / `use_fp16_storage` cuts memory bandwidth; on A76 this is a 10–20% speedup over pure FP32 with no accuracy loss.
- **Thread affinity:** pin ncnn threads to the 4× A76 (skip the A76-only Pi 5 — there are no little cores, but still set `OMP_PROC_BIND=close` and `ncnn::set_cpu_powersave(0)`).
- **Input resolution:** dropping 640→416 buys ~2.3× speedup for YOLO-class models. PicoDet at 320 input is already at 100+ FPS on mobile ARM.
- **Frame skipping / keyframe inference:** run the heavy model every 3rd frame, propagate boxes with ByteTrack in between. Effectively 3× the "perception" FPS at the cost of one frame of latency.

---

## 8. SAM2 / SegFormer on CPU (Pi 5)

**Short answer:** Full SAM2 and SegFormer-B2+ are **not real-time on Pi 5 CPU.** Distilled/edge variants are, with caveats.

### SAM2 family

| Variant | Encoder size | Encoder FPS on Pi 5 CPU (est) | Notes |
|---|---|---|---|
| **SAM2-Hiera-Large** | ~280 M | <0.2 FPS | Not feasible. |
| **SAM2-Hiera-Base+** | ~80 M | ~0.5–1 FPS | Not feasible for control loop. |
| **SAM2-Hiera-Tiny** | ~38 M (152 MB INT8) | **~1–3 FPS** | robotflowlabs INT8 export. Usable for offline keyframe masks. |
| **EfficientSAM (ViT-B0)** | ~6 M image encoder | ~5–10 FPS | Encoder-only; tiny mask decoder adds <1 ms. |
| **EdgeSAM** (CNN distillation of SAM) | ~5 M image encoder | **~10–20 FPS** | Pure CNN — clean ncnn export. Best CPU SAM variant. mIoU within ~2 of SAM-ViT-B on SA-1K. |
| **RepViT-SAM** | ~6 M (RepViT encoder) | ~10–20 FPS | CVPR 2024, 10× faster than MobileSAM, better zero-shot than MobileSAM. RepVGG-style → fuses for ncnn. **Best pick.** |
| **MobileSAM** | ~6 M (TinyViT) | ~3–8 FPS | Superseded by EdgeSAM / RepViT-SAM. |
| **PicoSAM2** | <1 M | ~30+ FPS (Sony IMX500 in-sensor, 14.3 ms) | In-sensor model; running on Pi 5 CPU would be faster but the model is trained for the IMX500 op set. Worth tracking. |

**Pi 5 plan for segmentation:**
- Use **RepViT-SAM (or EdgeSAM)**, INT8, ncnn, point/box-prompted on a handful of ROIs per frame (not full-image free segmentation). Encoder runs in ~50–100 ms; mask decoder <5 ms per prompt.
- Run it on **keyframes only** (every 3rd–5th frame) on a separate thread. Use the masks to (a) refine obstacle boundaries from the PicoDet boxes and (b) seed a boundary tracker (e.g. Mask2Former-lite or a simple color/edge tracker) for in-between frames.
- **Do not** try to run full SAM2-Hiera-Tiny in the 30 FPS loop. Save it for an offline "make a nice cinematography mask" pass.

**Export:** EdgeSAM and RepViT-SAM export cleanly to ONNX and ncnn (pure CNN encoders). SAM2-Hiera variants export to ONNX and OpenVINO but the Hiera attention + memory bank ops are not in ncnn.

### SegFormer

| Variant | Params | Pi 5 FPS (est) | Notes |
|---|---|---|---|
| SegFormer-B0 | 3.8 M | ~10–20 FPS (512×512) | Smallest. mIoU 36 on Cityscapes. |
| SegFormer-B1 | 13.7 M | ~3–6 FPS | |
| SegFormer-B2 | 27 M | ~1–2 FPS | Not feasible real-time. |

**SegFormer-B0 is feasible** on Pi 5 CPU for a fixed semantic class set (e.g. sky / ground / obstacle / vegetation) at 10–20 FPS. It is a pure MLP-decoder transformer — ncnn support is OK but not great; **OpenVINO is the better runtime** for SegFormer on Pi 5 (fused LayerNorm + attention).

**Pick for GarudaOne:** If you need *semantic* segmentation (what is this pixel?), SegFormer-B0 on OpenVINO. If you need *promptable instance* segmentation (segment this specific obstacle), RepViT-SAM on ncnn. They serve different purposes.

---

## 9. GroundingDINO Alternatives on CPU

**GroundingDINO (IDEA-Research, ECCV 2024)** is a Swin-B + BERT text-encoder open-set detector. The smallest official variant is ~172 M params (Base) and the "Edge" variant (GroundingDINO 1.5 Edge) is ~70 M params. **None run real-time on Pi 5 CPU** — expect <1 FPS.

**CPU-viable alternatives:**

| Model | Params | Open-vocab? | Pi 5 FPS (est) | Notes |
|---|---|---|---|---|
| **YOLO-World v2-S** | ~30 M (reparam) | ✅ text prompts | **~3–8 FPS** | CVPR 2024. "Prompt-then-detect" — text embeddings are reparameterized into the conv weights at inference, so the model becomes a normal YOLO at deploy time. **The only realistic CPU grounding option.** |
| **YOLO-World v2-L** | ~150 M | ✅ | ~1–2 FPS | Too slow for loop; OK for keyframes. |
| **GroundingDINO 1.5 Edge** | ~70 M | ✅ | ~1–2 FPS | Slightly more flexible prompts than YOLO-World but 3× the cost. |
| **MM-Grounding-DINO Nano** | ~20 M | ✅ | ~5–10 FPS (est) | Community distilled variant; export path is rough. |
| **OWL-ViT v2 (small)** | ~150 M | ✅ text/image | <1 FPS | Too heavy. |
| **MDETR** | ~150 M | ✅ text | <1 FPS | Too heavy; deprecated in favor of GroundingDINO. |
| **T-Rex2 Edge** | n/a | ✅ visual prompts | n/a | Visual-prompt (click-box) only, no text. API-only. |
| **OmDet-Turbo** | ~30 M | ✅ | ~3–6 FPS | Good alternative to YOLO-World; less ecosystem. |

**Recommendation for GarudaOne:**

1. **Primary:** **YOLO-World v2-S, reparameterized, ncnn INT8, ~5 FPS** on a keyframe thread for open-vocab grounding ("find me the 'cliff edge'", "find the 'person'") — this replaces GroundingDINO at 30× the speed.
2. **Hybrid pipeline:** PicoDet-S at 30–60 FPS for closed-set obstacle avoidance (the safety loop) + YOLO-World v2-S at 5 FPS on keyframes for user-driven open-vocab queries (the cinematography loop). This is the practical CPU grounding architecture.
3. **Skip GroundingDINO entirely on Pi 5.** If you need its accuracy, run it offline on the ground station after landing.

**Export:** YOLO-World exports to ONNX; the reparameterized "deploy" mode converts to a normal YOLO graph that ncnn digests. Some versions need the `yolo_world_head` rewritten for ncnn — check the AILab-CVC/YOLO-World repo's deploy branch.

---

## 10. Scene Graph Generation on CPU

**Short answer:** Full SGG on CPU is **barely feasible in 2026**, only with the newest real-time models, and only with a YOLO-class backbone.

**Why it is hard:** Traditional SGG (MOTIF, VCTree, Transformer-PreDet) is a two-stage pipeline: detector → subject-object pair sampler (O(N²) pairs) → relation classifier. For N=20 objects that is 400 pairs per frame through a transformer — too slow on CPU.

**CPU-viable options:**

| Model | Backbone | FPS on Pi 5 (est) | Notes |
|---|---|---|---|
| **DSFlash** (CVPR 2026) | unified seg+relation backbone | **~5–15 FPS** with YOLOv8n backbone, **~3–5 FPS** with YOLOv8s | 56 FPS on RTX 3090, 18 ms latency. One-stage (no pair sampler). **Best CPU SGG option in 2026.** |
| **Real-Time SGG** (arxiv 2405.16116) | YOLOv8 + lightweight relation head | **~10–20 FPS** with YOLOv8n | "First >48 FPS SGG" — but that is on GPU. The YOLOv8n backbone is the same one you already run at 30 FPS on Pi 5, so the relation head adds maybe 10–20 ms. Feasible. |
| **Lightweight SGG Transformer** (IEEE 2024) | end-to-end triples, no detection | ~3–8 FPS | One-stage, no NMS. Small but transformer-based. |
| **MOTIF / VCTree** (classic) | Faster-RCNN + pair sampler | <1 FPS | Not feasible. |

**Pi 5 plan for SGG:**
1. **Use the Real-Time SGG pattern:** your existing PicoDet-S is the detector backbone. Add a tiny relation-classification head (MLP over concatenated subject-object features + spatial embedding). Train it on a small drone-relevant relation set ("in-front-of", "behind", "above", "below", "moving-toward", "moving-away"). The head is <1 M params and adds <5 ms / frame.
2. **Sparse relations only.** Do not compute all O(N²) pairs — use the tracker's velocity + the ToF's 3D centroid to pre-filter to "potentially interacting" pairs (N<10 → <100 pairs). This is what DSFlash's "dynamic patch pruning" does and it is the key to CPU SGG.
3. **Output a small graph per frame** (5–15 nodes, 5–20 edges) and feed it to the planner. This is enough for "the person is in-front-of the tree, moving-toward the drone" semantics that drive cinematography decisions.

**Pi 5 feasibility:** ✅ **at 5–15 FPS with the right architecture.** Not at 30 FPS. Pair it with the keyframe-thread pattern.

---

## Synthesis — Recommended GarudaOne CPU Perception Stack

```
┌──────────────────────────────────────────────────────────────────────────┐
│  CONTROL LOOP (30+ FPS, hard real-time, ncnn INT8)                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────┐    │
│  │ PicoDet-S INT8  │→│ ByteTrack       │→│ VL53L8CX ToF fusion  │    │
│  │ 4.7MB, 45-70FPS │  │ ~1ms, 500+ FPS  │  │ 8x8 60Hz depth       │    │
│  └─────────────────┘  └─────────────────┘  └──────────────────────┘    │
│         ↓ boxes + track IDs + 3D centroids → planner                    │
├──────────────────────────────────────────────────────────────────────────┤
│  DEPTH LOOP (10-15 FPS, soft real-time, ncnn INT8)                       │
│  ┌───────────────────────────────────────────────────────────────┐      │
│  │ ZipDepth base, 256x320 INT8, ~6MB, 10-15 FPS                │      │
│  │ Dense depth prior; fused with ToF for scale                  │      │
│  └───────────────────────────────────────────────────────────────┘      │
├──────────────────────────────────────────────────────────────────────────┤
│  SCENE LOOP (3-8 FPS, keyframe thread, ncnn INT8 + OpenVINO)             │
│  ┌─────────────────────┐  ┌──────────────────────────────────────┐     │
│  │ YOLO-World v2-S     │  │ RepViT-SAM (point/box prompted)     │     │
│  │ open-vocab grounding│  │ mask refinement for key obstacles   │     │
│  └─────────────────────┘  └──────────────────────────────────────┘     │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │ Relation head (MLP over PicoDet tracks + ToF 3D centroids)│       │
│  │ Sparse scene graph: 5-15 nodes, 5-20 edges/frame           │       │
│  └─────────────────────────────────────────────────────────────┘       │
├──────────────────────────────────────────────────────────────────────────┤
│  OFFLINE / GROUND STATION (post-flight)                                  │
│  RT-DETR-R50, GroundingDINO, SAM2-Large, Depth-Anything-V2-Large         │
│  → labels for distillation training of the on-device students            │
└──────────────────────────────────────────────────────────────────────────┘
```

### Memory budget (8 GB Pi 5)

| Component | RAM (est) |
|---|---|
| PicoDet-S INT8 (loaded) | ~30 MB |
| ByteTrack state | ~5 MB |
| ZipDepth INT8 (loaded) | ~40 MB |
| YOLO-World v2-S INT8 (loaded) | ~150 MB |
| RepViT-SAM INT8 (loaded) | ~120 MB |
| Camera buffers + OpenCV | ~300 MB |
| Linux + app | ~500 MB |
| **Total** | **~1.2 GB** ← comfortably within 8 GB |

### Threading

- Control loop: 2 A76 threads for ncnn inference + 1 thread for tracker + 1 for camera I/O.
- Depth loop: 2 A76 threads for ncnn, runs in parallel with control loop (different model, no contention).
- Scene loop: 2 A76 threads, lower priority, runs on every 3rd–5th frame.
- Total: 4 A76 cores, 3 concurrent inference streams — this is what the Pi 5 is built for.

### Quantization pipeline (recommended)

1. Train PicoDet-S on drone classes ( workstation, GPU).
2. QAT 10 epochs → INT8 ONNX.
3. `onnx2ncnn` + INT8 table → `picodet_s_int8.param` / `.bin`.
4. Repeat for ZipDepth (use DA-V2-Large as the distillation teacher — the ZipDepth repo already does this).
5. For YOLO-World v2-S, use OpenVINO NNCF for INT8 calibration (more transformer-friendly than ncnn's PTQ) then export the calibrated INT8 ONNX to ncnn if the op set allows; otherwise keep it on OpenVINO runtime.
6. RepViT-SAM: ncnn INT8 directly — pure CNN, clean export.

### Pitfalls to avoid

1. **Do not put RT-DETR in the control loop.** It will drop you to 3 FPS and you will crash.
2. **Do not use BoT-SORT with a ReID CNN** on Pi 5 unless you have benchmarked the ReID pass — it is the hidden cost.
3. **Do not trust unverified INT8 on ONNX Runtime.** Verify the INT8 kernels are actually being used (check the profile) — ORT has a known issue where some INT8 models fall back to a slow reference path.
4. **Do not run ZipDepth at 512×512 in the loop.** It is 3 GFLOPs at 256×320 and ~12 GFLOPs at 512×512 — 4× the latency for 4× the pixels you do not need for obstacle avoidance.
5. **Do not skip thermal management.** The IJERT 2026 paper shows Pi 5 YOLOv8n CPU throughput *declines* under sustained load due to throttling. Active cooling is mandatory; consider `cpufreq` governor = `performance` only with a fan.
6. **Do not unstructured-prune** and expect a CPU speedup. ncnn has no sparse kernels. Use structured/channel pruning only.

---

## References (key sources)

- RT-DETR (lyuwenyu/RT-DETR, CVPR 2024) — https://github.com/lyuwenyu/RT-DETR , https://arxiv.org/abs/2304.08069
- RT-DETR benchmark & pre-trained models — https://deepwiki.com/lyuwenyu/RT-DETR/8.1-pre-trained-models
- DETR-AE-Mamba (ONNX Runtime R18 latency 292 ms) — https://link.springer.com/article/10.1007/s44443-026-00557-1
- "Review of YOLOv8 and RT-DETR energy efficiency on edge" (Nature Sci Rep 2026) — https://www.nature.com/articles/s41598-026-46453-6
- "Comparative Benchmarking of CPU/GPU/NPU for YOLOv8n" (IJERT 2026, Pi 5 2.6 FPS FP32) — https://www.ijert.org/comparative-benchmarking-of-cpu-gpu-and-npu-architectures-for-real-time-yolov8n-inference-on-embedded-edge-platforms-ijertv15is030232
- RPi YOLO Benchmark (kadirmertabatay, Jan 2026) — https://kadirmertabatay.github.io/rpi-yolo-benchmark/
- Qengineering YoloV8-ncnn-Raspberry-Pi-4 — https://github.com/Qengineering/YoloV8-ncnn-Raspberry-Pi-4
- Ultralytics "YOLO26 on Raspberry Pi" guide — https://docs.ultralytics.com/guides/raspberry-pi
- Raspberry Pi Foundation "Run Ultralytics YOLO on Pi with OpenVINO" — https://www.raspberrypi.com/news/run-ultralytics-yolo-on-raspberry-pi-with-openvino/
- Roboflow trackers comparison — https://trackers.roboflow.com/develop/trackers/comparison/
- Forasoft "MOT — DeepSORT, ByteTrack, OC-SORT" — https://www.forasoft.com/learn/ai-for-video-engineering/articles-ai/multi-object-tracking-deepsort-bytetrack-ocsort
- NorFair (tryolabs) — https://github.com/tryolabs/norfair
- ZipDepth (ECCV 2026) — https://zipdepth.github.io/ , https://arxiv.org/abs/2607.08771 , https://github.com/fabiotosi92/ZipDepth
- Depth-Anything-V2 (NeurIPS 2024) — https://github.com/DepthAnything/Depth-Anything-V2
- FastDepth (ICCV 2019) — https://arxiv.org/abs/1903.03273
- PP-PicoDet (arxiv 2111.00902) — https://arxiv.org/abs/2111.00902
- Gold-YOLO (NeurIPS 2023) — https://arxiv.org/abs/2309.11331
- ncnn I8MM kernel — https://github.com/Tencent/ncnn/blob/master/src/layer/arm/convolution_arm_i8mm.cpp
- ncnn INT8 quantization (DeepWiki) — https://deepwiki.com/Tencent/ncnn/5.4-int8-quantization-and-precision-modes
- OpenCV DNN module overview — https://opencv.org/opencv-dnn-module/
- EdgeSAM (arxiv 2312.06660) — https://arxiv.org/abs/2312.06660 , https://www.mmlab-ntu.com/project/edgesam/
- RepViT-SAM (CVPR 2024) — https://github.com/THU-MIG/RepViT , https://jameslahm.github.io/repvit-sam/
- Efficient-SAM2 (ICLR 2026) — https://github.com/jingjing0419/Efficient-SAM2
- PicoSAM2 — https://arxiv.org/html/2506.18807v3
- SAM2.1 Hiera-Tiny INT8 (robotflowlabs) — https://huggingface.co/robotflowlabs/sam2.1-hiera-tiny-int8
- YOLO-World (CVPR 2024) — https://github.com/AILab-CVC/YOLO-World , https://docs.ultralytics.com/models/yolo-world
- GroundingDINO 1.5 Edge — https://arxiv.org/abs/2405.10300
- DSFlash (CVPR 2026) — https://arxiv.org/abs/2603.10538
- Real-Time SGG (2024) — https://arxiv.org/abs/2405.16116
- YOLO Distillation for robotics — https://www.rajat-gupta.dev/project-yolo-robotics.html
- YOLOBench (ICCV 2023 workshop) — https://openaccess.thecvf.com/content/ICCV2023W/RCV/papers/Lazarevich_YOLOBench_Benchmarking_Efficient_Object_Detectors_on_Embedded_Systems_ICCVW_2023_paper.pdf
- "Optimizing Edge AI: data, model, deployment survey" (arxiv 2501.03265) — https://arxiv.org/html/2501.03265v1/
