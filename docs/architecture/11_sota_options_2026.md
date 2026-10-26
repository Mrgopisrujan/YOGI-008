# GarudaOne: SOTA Options Scan & Architecture Improvements (2026-07-07)

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - Needle 2 (45M, `cactus-needle==2.0.0`) replaced Needle 26M as the active constrained router.
> - Local voice transport is integrated; the exact STT bundle still requires target-Pi qualification.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - The flight profile instantiates C10 and requires an inbound checksummed status reply; physical attitude feedback and motion limits remain unvalidated.
> - Production VIO/SLAM adapters are absent or deferred.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!IMPORTANT]
> This is an architecture/design record, not deployment evidence. Current verified implementation status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


Rule for this pass (per Arjun): **prototype is license-unconstrained** — anything goes on the bench; the license ledger (§4) tracks what must be resolved or swapped before production firmware. All constraints from docs 08/10 still bind: Pi 5 CPU-only, <8 W sustained, 25 fps 1080p feed, 20 Hz control, ~300 g dev platform.

Verdicts: **ADOPT** (do it now) · **BENCH-OFF** (measure, then decide) · **OPTIONAL** (experimental branch) · **PRODUCTION** (needs NPU) · **REJECT** (with reason).

---

## 1. Slot-by-slot scan (July 2026)

| Slot | Current plan | Best challenger found | Verdict |
|---|---|---|---|
| Object detection | PicoDet-S (2021, Apache-2.0), 53.7 FPS isolated | **YOLO26n** (Ultralytics, Jan 2026): NMS-free end-to-end, ~43% faster CPU inference than predecessors, ncnn-exportable, higher mAP (40.1 vs PicoDet's 27.0). License: AGPL-3.0/commercial ([docs](https://docs.ultralytics.com/guides/raspberry-pi), [overview](https://arxiv.org/html/2510.09653v1)) | **BENCH-OFF (B1)** at 320×320 INT8 ncnn on the Pi. NMS-free = deterministic latency, a real win for control loops. PicoDet stays the license-clean production fallback. |
| Tracking (was: "highest-conf person") | none explicit | **ByteTrack-style association** (Kalman + IoU, no extra NN) + **sparse LK optical-flow bbox propagation** between detector frames | **ADOPT.** Detector runs 10–15 FPS; flow propagation updates the box at 25 Hz for ~1 ms/frame. Halves vision CPU, doubles thermal headroom, keeps control fed at full rate. This is how everyone ships CPU tracking. |
| Scene understanding (new slot) | — | **LFM2.5-VL-450M** (Liquid, Apr 2026): 450M VLM, **bounding-box prediction + function calling**, multilingual; sub-250 ms on Orin-class, expect ~1–3 s/frame on Pi 5 CPU (EST) ([Liquid blog](https://www.liquid.ai/blog/lfm2-5-vl-450m), [HF](https://huggingface.co/LiquidAI/LFM2.5-VL-450M)) | **ADOPT as episodic "Director's Eye"** — on-demand single frames only ("what's around me?", shot framing checks, target disambiguation "the guy in red"). Never in the control loop. Same vendor/stack as the brain (llama.cpp). On Jetson-Orin-class edge modules it reaches ~4 FPS (vendor; NPU figure TBD). |
| Language brain | LFM2.5-230M | Gemma 3 270M (Google, Aug 2025): IFEval 51.2 vs LFM2-350M's 65.1; not agentic-tuned ([Google](https://developers.googleblog.com/en/introducing-gemma-3-270m/)) | **KEEP LFM2.5-230M.** Nothing at ≤500M beats the LFM2.5+Needle pair for tool calling as of July 2026. Add **GBNF grammar-constrained JSON output** in llama.cpp — guarantees syntactically valid tool calls, eliminates a whole failure class, negligible per-token overhead. **ADOPT.** |
| Tool router | Needle 26M | (nothing comparable found as of Jul 2026) | **KEEP.** Integrate the real runtime (currently keyword placeholder — 10 §8). |
| Command input | voice pipeline | — | **CHANGED 2026-07-08 (Arjun): prototype = TEXT natural-language commands** over Wi-Fi (doc 02). Frees ~1 core, ~8 g, kills the acoustic risk (08 N4 closed). Everything below this row is **DEFERRED to product phase** — selections locked so no re-research is needed later. |
| STT (deferred) | Moonshine Tiny (26 MB, 12.66% WER en) | **"Flavors of Moonshine"** (Sep 2025): tiny per-language ASR matching Whisper-Medium-class ([paper](https://arxiv.org/html/2509.02523v1)) | Locked for product phase: Moonshine + flavors (Indic path), Silero VAD (MIT) gate. Capture = BT buds → phone. |
| TTS (deferred) | Piper | **Kokoro-82M** (Apache-2.0): top open-quality class; ~10 s audio in ~3 s on Pi-class CPU ([bench](https://mikeesto.com/posts/kokoro-82m-pi/)) | Locked for product phase: Kokoro product voice + pre-rendered phrase cache; Piper fallback. |
| Wake word (deferred) | openWakeWord | microWakeWord (MCU-class) | Locked for product phase; MCU offload is production-PCB territory. |
| VIO (optional branch, license now unlocked) | none (EKF2 only) | **OpenVINS** (GPLv3, proven on Pi 5 via [RoboEye](https://github.com/mzahana/roboeye)); **LEVIO** (Feb 2026, pure-C embedded VIO, open-sourced — [arXiv 2602.03294](https://arxiv.org/abs/2602.03294)) | **OPTIONAL (B2):** only on a **fixed global-shutter nav cam** (Pi GS cam, ~4 g, ~₹3.5K), never the gimbal feed. Buys GPS-denied/indoor demos. LEVIO is the one to watch — built exactly for our compute class. Budget 1 core max; if it can't hold 15 Hz there, drop the branch. |
| Mono depth assist | — | Depth Anything V2-small quantized (~1–2 FPS on Pi 5 CPU, EST); **DA3** (ICLR 2026) is GPU/multi-view class ([DA3](https://arxiv.org/abs/2511.10647)) | **OPTIONAL (B3)** 1 Hz advisory layer fused with ToF (long-range "something big ahead" hints). **PRODUCTION** for real use (NPU). Not a control-loop sensor on CPU. |
| End-to-end VLA (replace detector+LNN) | — | SmolVLA/TinyVLA class | **REJECT for prototype** — 450M+ VLM at CPU token rates cannot close a 20 Hz control loop. Stays the Part-16 production research track. |
| Sim for CI | Isaac Sim (cloud GPU) | — | **ADOPT split:** headless Gazebo/JMAVSim PX4 SITL for the fast agent-harness CI loop (no GPU, seconds to boot); Isaac+Pegasus reserved for photoreal domain-randomized data generation. Cuts cloud spend and makes the Claude-Code loop fast. |

## 2. Architecture change (the "layers" question)

**Question asked:** more or fewer layers? **Answer: keep 3 layers, but add a 4th *authority* — a deterministic Flight Arbiter inside Layer 2.** Not more AI — more determinism.

```
L1  DIRECTOR (slow, advisory)      LFM2.5-230M + Needle + LFM2.5-VL eye     ~1 Hz, on-demand
      │ proposes {mode, params}
L2a ARBITER (deterministic, OWNS AUTHORITY)   ~500 lines, no ML
      mode state machine · speed governor · watchdogs (target-lost/battery/
      thermal/geofence) · hard clamps · failsafe triggers
      │ grants/denies; forwards limits
L2b REFLEX (fast, continuous)      tracker @25Hz + CfC LNN + smoother        20–25 Hz
      │ velocity setpoints (pre-clamped)
L3  PX4 (hard real-time safety floor)          400 Hz, unchanged
```

Why: today the LFM's tool call mutates flight mode directly — an LLM in the authority path. The arbiter makes every AI component (LFM, VLM, LNN) *advisory*; only auditable deterministic code changes modes or limits. This is the pattern under every shipped autonomy product, it's ~2 days of work, and it is what makes "150% reliability" a designable property instead of a hope. The go/no-go gates in doc 10 §7 become the arbiter's unit tests.

Rejected structural alternatives: collapsing to an end-to-end VLA (can't meet 20 Hz on CPU); adding a cloud layer (violates offline vision — Modal stays training-only); ROS 2 (unchanged: overkill for a single-purpose product).

## 3. Smaller adopted improvements (full list)

1. Detector duty-cycling: 10–15 FPS detect + 25 Hz flow propagation (§1) — biggest thermal win available.
2. GBNF-constrained LFM output — zero invalid tool calls.
3. llama.cpp prefix/KV caching — system prompt prefilled once, not per command.
4. Person-only detector fine-tune @ 192×320 (VisDrone + aerial-person data) — ~2× detector speed at equal person recall (bench B1 includes this).
5. Voice barge-in: wake word interrupts TTS playback *(product phase — moved with the voice descope)*.
6. Pre-rendered phrase cache for instant audio feedback *(product phase)*; prototype equivalent: instant "understood: `<tool call>`" echo in the app.
7. **Flight data recorder:** log every topic (frames ring-buffer, bbox, ToF, EKF2, setpoints, arbiter decisions) per flight — each flight becomes a regression dataset for the agentic dev harness, and DAgger-style pilot-takeover corrections become LNN training data automatically.
8. Gimbal joint-angle telemetry (if the reverse-engineered protocol exposes it) → proper bbox-to-body-frame projection.

## 4. Production license ledger (because prototype is unlocked)

| Component | Prototype | Production action |
|---|---|---|
| YOLO26 (AGPL-3.0) | ✅ free to bench | Buy Ultralytics license **or** ship PicoDet/license-clean retrain |
| OpenVINS (GPLv3) | ✅ free to bench | Swap to Basalt (BSD-3) / LEVIO (verify license) / license or drop |
| LEVIO | ✅ | Verify repo license before integration hardening |
| Kokoro-82M (Apache-2.0) | ✅ | Clean — ship |
| Silero VAD (MIT) | ✅ | Clean — ship |
| LFM2.5 family | ✅ | Confirm Liquid AI redistribution terms for embedded firmware |
| Moonshine (MIT-class) | ✅ | Confirm flavors' per-model licenses |

## 5. New bench-offs added to the gate list (extends doc 10 §7)

- **B1 Detector bench-off:** YOLO26n vs PicoDet-S vs person-only fine-tune — 320×320 INT8 ncnn, 2 pinned cores, 10-min soak: FPS, person-recall on our footage, latency p99, package temp.
- **B2 VIO branch:** OpenVINS/LEVIO on GS nav cam @ 1 core: drift <1% over 100 m indoor at 15 Hz, else drop.
- **B3 Depth assist:** DA-V2-small INT8 @ 1 Hz on 1 core: does fused ToF+mono flag 10 m obstacles earlier without false-brake events?
- **B4 VLM eye:** LFM2.5-VL-450M single-frame Q&A on Pi 5: latency + usefulness on 50 real shot-setup queries.
- **B5 TTS:** ~~Kokoro time-to-first-audio~~ — **deferred with voice descope (2026-07-08)**; run when voice returns.

## 5b. Feature coverage — master guide (18 parts) vs. what is actually planned now

Answering "did we plan all master-doc features?" — **No, deliberately.** The current build (docs 00–11) implements the master guide's **Phase 1 (Part 13, "Core Autonomy, months 1–4") only.** Coverage map:

| Guide part | Feature | Status in current plan |
|---|---|---|
| 1 | Weight budget / Orin architecture | Superseded by architecture docs (Pi 5 plan; guide's weights had errors — see errata banner) |
| 2 | Subject tracking (YOLO+BoT-SORT+re-ID) | ✅ **IN, simplified**: single-subject detector + ByteTrack-lite + flow propagation. OSNet re-ID = Phase 2 (re-acquisition) |
| 3 | SLAM / depth / EGO-Planner | 🟡 **PARTIAL**: EKF2 + ToF governor now; VIO (B2) & mono-depth (B3) optional branches; AirSLAM/EGO-Planner = production |
| 4 | Voice (Indic languages) | ⏸ **DEFERRED** (2026-07-08): text NL now; BT-buds voice + Moonshine flavors = product phase |
| 5 | Gesture recognition | ❌ Not in prototype (Phase 2) |
| 6 | Pre-flight scene intelligence (DVGFormer, 3DGS, CLIP-IQA) | ❌ Phase 2 — the LFM2.5-VL Director's Eye is the small seed of this |
| 7 | Shot memory / creator style | ❌ Phase 3 |
| 8 | GarudaPin (UWB beacon) | ❌ Separate hardware program, not started |
| 9 | Environmental intelligence (golden hour, weather) | ❌ Phase 2 (mostly app-side) |
| 10 | Crowd-sourced maps | ❌ Phase 3 |
| 11 | Shot classification (CameraBench) | ❌ Phase 2 (training-time tooling) |
| 12 | Model training requirements | 🟡 PARTIAL: LNN imitation-learning pipeline is in plan; other fine-tunes deferred |
| 13 | Roadmap | ✅ Phase 1 = the current build, exactly |
| 14–15 | Reference tables / risk matrix | Superseded by docs 08/10 |
| 16–18 | VLA / world-action models | ❌ Production R&D track (correctly kept out of the CPU prototype) |

This is the right shape: the prototype proves the **experience core** (talk to it in natural language → it flies and films like an operator). Every ❌ above layers onto that core without re-architecting — that's what the Arbiter/Director split buys.

## 6. Sources

[Ultralytics YOLO26 Pi guide](https://docs.ultralytics.com/guides/raspberry-pi) · [YOLO evolution paper](https://arxiv.org/html/2510.09653v1) · [Liquid LFM2.5-VL-450M](https://www.liquid.ai/blog/lfm2-5-vl-450m) · [MarkTechPost LFM2.5-VL](https://www.marktechpost.com/2026/04/11/liquid-ai-releases-lfm2-5-vl-450m-a-450m-parameter-vision-language-model-with-bounding-box-prediction-multilingual-support-and-sub-250ms-edge-inference/) · [Gemma 3 270M](https://developers.googleblog.com/en/introducing-gemma-3-270m/) · [Kokoro on Pi](https://mikeesto.com/posts/kokoro-82m-pi/) · [Flavors of Moonshine](https://arxiv.org/html/2509.02523v1) · [LEVIO](https://arxiv.org/abs/2602.03294) · [RoboEye (OpenVINS on Pi 5)](https://github.com/mzahana/roboeye) · [OpenVINS](https://docs.openvins.com/) · [Depth Anything 3](https://arxiv.org/abs/2511.10647) · [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2)
