# Tracking and native-backend research — 2026-08-14

> [!NOTE]
> [DOC_STATUS: HISTORICAL] Dated research snapshot. This file does not describe enabled flight behavior. Current behavior is in [`../docs/CURRENT_CAPABILITIES.md`](../CURRENT_CAPABILITIES.md).

## Current outcome (2026-08-14)

The flight candidate uses PicoDet, two-pass ByteTrack, a box Kalman filter, validated LK flow, and affine camera-motion compensation. McByte, REMIND, VOCA, MVTrack, and the surveyed LocalAI backends are not enabled flight dependencies.

## Decision

GarudaOne keeps the Pi 5 flight tracker small and deterministic:

- PicoDet INT8 through ncnn;
- person-only, two-pass ByteTrack association;
- an 8-state constant-velocity box Kalman filter;
- forward/backward Lucas–Kanade optical flow;
- affine camera-motion compensation with RANSAC;
- explicit provisional, confident, ambiguous, lost, and removed identity states;
- control authority only for a locked, confident target with current detector or validated flow evidence.

McByte and REMIND are not onboard dependencies. VOCA and MVTrack are research leads, not flight components. The reviewed LocalAI C++ projects are evaluated one by one; their existence is not evidence that they meet GarudaOne latency, memory, license, or safety requirements.

## McByte

McByte adds segmentation-mask overlap to BoT-SORT-style association. The Roboflow implementation uses SAM to initialize masks and Cutie to propagate them through time. This can preserve identity through overlap and short occlusion, but the full stack adds large vision models and stateful segmentation memory.

Evidence reviewed:

- Roboflow Trackers release `2.6.0`, commit `0e839f348d8bf4ed09eea9f3bef58fd5f95dca3f`;
- Apache-2.0 Roboflow tracking code;
- SAM ViT-B and Cutie model/runtime requirements;
- the paper *No Train Yet Gain: Towards Generic Multi-Object Tracking in Sports and Beyond*;
- the WaspMOT benchmark, which evaluates McByte with other tracking-by-detection methods.

The reviewed full configuration used approximately 515 MB of checkpoint bytes before runtime memory. The paper reported only low single-digit frame rates on an NVIDIA A100 for the complete mask path. No Raspberry Pi 5 CPU, ARM64, PicoDet, or aerial benchmark was found. Cutie's dynamic memory also prevents a simple one-file ONNX or ncnn conversion.

**GarudaOne decision:** do not run full McByte onboard. If hardware permits, compare it offline on recorded flights. Reuse only the general idea of adding a validated non-box cue after the current box/flow tracker has real flight data.

Sources:

- <https://github.com/roboflow/trackers>
- <https://github.com/roboflow/trackers/releases/tag/2.6.0>
- <https://trackers.roboflow.com/latest/trackers/mcbyte/>
- <https://arxiv.org/abs/2506.01373>
- <https://arxiv.org/abs/2607.08729>
- <https://github.com/hkchengrex/Cutie>
- <https://github.com/facebookresearch/segment-anything>

## REMIND

REMIND targets long-term indoor re-identification after an object leaves and later re-enters view. It combines accumulated appearance memory, nearby-object context, and joint multi-object assignment. Its reported `90.35` IDF1 is from the authors' custom indoor re-entry benchmark. It is not a general drone benchmark or independent replication result.

The implementation uses DINOv3 appearance features. Even the ViT-S/16 variant is a foundation-model feature extractor, and the reviewed code depends on Python, PyTorch, Transformers, OpenCV, and a detector stack. No Pi 5 CPU real-time benchmark or target-native ncnn path was found. Appearance memory also has privacy and retention implications that the current box-only tracker avoids.

**GarudaOne decision:** do not run REMIND in the 20 Hz flight loop. Consider an offline or low-rate desktop study only if real data shows that long exits and re-entry are a product requirement. Any future use needs a bounded gallery, expiry policy, explicit license review, and a measured Pi/native implementation.

Sources:

- <https://arxiv.org/abs/2607.09267>
- <https://cvar-vision-dl.github.io/remind-reid-tracker/>
- <https://github.com/cvar-vision-dl/remind-reid-tracker>
- <https://github.com/facebookresearch/dinov3>
- <https://huggingface.co/facebook/dinov3-vits16-pretrain-lvd1689m>

## LocalAI native C++ backends

The reviewed “17 backends” are real LocalAI-team native projects listed under “Backends built by us.” They are not 17 repositories owned only by one maintainer. The LocalAI table also lists the in-tree `local-store`, which explains count differences.

Relevant findings:

| Project | What was verified | GarudaOne decision |
|---|---|---|
| `depth-anything.cpp` | C++17/GGML; small quantized artifacts; x86 CPU benchmarks; no Pi result | Keep as an offline comparison. Do not replace calibrated ZipDepth/ncnn without Pi parity and metric validation. |
| `rf-detr.cpp` | Native detector with x86 CPU parity/benchmark evidence | Useful desktop baseline. Too unproven for the current Pi detector budget. |
| `parakeet.cpp` | Native ASR project | Out of this tracking scope; speech remains outside P0. |
| `locate-anything.cpp` | Large visual grounding model with model-specific license | Too large and not needed for locked-person flight tracking. |
| `voice-detect.cpp` | Speaker identity/attributes, not simple VAD | Irrelevant to P0 and has privacy costs. |
| `LocalVQE` | Native audio enhancement with compact options | Audio research only; not part of tracking. |
| `privacy-filter.cpp` | Large text privacy model | Not an onboard vision requirement. |
| `face-detect.cpp` | Native face analysis | Do not add biometric identity to flight tracking. |
| `vllm.cpp`, TTS, 3D, and image-generation projects | Real repositories with mixed maturity, hardware support, and model licenses | Not flight-loop dependencies. |

A repository's code license does not automatically cover its weights, tokenizer, training data, or commercial use. Most published benchmarks were on high-end x86 or GPU systems. No blanket “C++ therefore Pi-ready” conclusion is valid.

Sources:

- <https://github.com/mudler/LocalAI/blob/9fd7ea7e93a81cdfcdbe807730c3b1a3b5bbbe22/README.md#backends-built-by-us>
- <https://github.com/localai-org/depth-anything.cpp>
- <https://github.com/localai-org/rf-detr.cpp>
- <https://github.com/mudler/parakeet.cpp>
- <https://github.com/mudler/locate-anything.cpp>
- <https://github.com/localai-org/voice-detect.cpp>
- <https://github.com/localai-org/LocalVQE>
- <https://github.com/localai-org/privacy-filter.cpp>
- <https://github.com/mudler/face-detect.cpp>
- <https://github.com/mudler/vllm.cpp>

## VOCA

VOCA (*Visual Odometry with Codec Awareness*) is a causal stereo visual-odometry method. It uses codec information to improve feature tracking and reports strong causal VO accuracy and efficiency. It is a localization method, not a subject tracker.

**GarudaOne decision:** set aside as a future localization experiment. Adoption would require synchronized stereo video, access to the encoded bitstream and codec metadata, a target-native implementation, calibration, and comparison against the selected MTF-01/PX4 estimator path. None of these are present in the current camera contract.

Source: <https://arxiv.org/abs/2607.00189>

## MVTrack

MVTrack (*Ultrafast Appearance-Free Moving Object Tracking from Compressed Bitstreams*) operates from compressed-video motion information and avoids image appearance features. This is promising for low-cost motion proposals, but it does not by itself establish persistent person identity, detector class, or safe subject re-identification.

**GarudaOne decision:** set aside. A future offline probe may use it as a motion-cue generator. It cannot replace PicoDet class evidence, locked identity, or the deterministic control gate without a measured integration and failure analysis.

Source: <https://arxiv.org/abs/2608.10790>

## Revisit gate

Reconsider one of these methods only after all of the following exist:

1. real target-Pi recordings with identity-switch and occlusion labels;
2. an offline comparison against the current tracker using HOTA, IDF1, ID switches, loss/reacquisition time, p50/p95 latency, peak RSS, and temperature;
3. an ARM64/native artifact with pinned source and separate code/weight licenses;
4. a measured CPU budget that preserves the 20 Hz deterministic control loop;
5. fail-closed evidence showing that ambiguous, stale, or prediction-only identity never authorizes motion.
