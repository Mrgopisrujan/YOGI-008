# Full Advancements & Meaningful Leads Catalog  

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
>
> - Needle 2 (45M, `cactus-needle==2.0.0`) replaced Needle 26M as the active constrained router.
> - The active PX4 transport is pymavlink, not MAVSDK-Python.
> - The selected flight profile uses one forward VL53L5CX at 8x8/15Hz; three-sensor/VL53L8CX designs are not active.
> - Local voice transport is integrated; the exact STT bundle still requires target-Pi qualification.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - The flight profile instantiates C10 and requires an inbound checksummed status reply; physical attitude feedback and motion limits remain unvalidated.
> - Production VIO/SLAM adapters are absent or deferred.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.

> [!NOTE]
> This file is a roadmap or future-phase proposal. It does not describe the current deployed system. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).

## Embodied AI · Edge Agents · Aerial Autonomy · Perception · Control  

**Through ~2026-07-13** — not only SOTA winners; every durable lead that still shapes a production cinematography drone.

**Purpose:** One living map so GarudaOne can pull from *the whole stack of history*, not the latest blog post.  
**Companion docs:** `01` landscape · `02` transfer · `03` phases · `04` compute · `06` pipeline+VL.

**Lead grades (for GarudaOne):**

| Grade | Meaning |
| --- | --- |
| **P0-SHIP** | Use in Phase-1 product path now |
| **P2-ADOPT** | Plan Phase 2–3 integration |
| **R&D** | Track, prototype offline; don’t block ship |
| **PATTERN** | Steal architecture idea only |
| **AVOID** | Wrong size/license/safety for production path |

---

## 0. How to read this catalog

Advancements are grouped by **capability**, then roughly **time**.  
“Meaningful lead” = still useful for design, data, training, or safety — even if no longer #1 on a leaderboard.

---

## 1. Timeline spine (physical AI 2020 → mid-2026)

| Era | What changed | Still matters because |
| --- | --- | --- |
| **2020–22** | LTC / CfC liquid nets; RT-1; ACT; Diffusion Policy; MiDaS era depth | Continuous-time control; imitation baselines; classic depth |
| **2023** | **RT-2** coins VLA; OXE dataset; DROID starts; liquid nets **Science Robotics** drone OOD flight; DJI Neo-class self-fly consumer | Language→action paradigm; open multi-robot data; LNN aerial proof |
| **2024** | **OpenVLA**, **Octo**, **π0**, GR00T, LeRobot growth; Depth Anything → **V2**; YOLO11/v8 edge; PicoDet still king on ARM ncnn | Open generalists; monocular depth foundations; edge detect |
| **2025** | **SmolVLA**, π0.5, Gemini Robotics, GR00T N1.x, MolmoAct (AI2), LingBot-Depth/VLA v1, LFM2 edge, constrained decoding mainstream, Aerial VLN boom, modular Pi+Hailo VLAs | Edge VLAs; open ARMs; glass-aware depth; tiny agents |
| **2026 H1** | **MolmoAct 2**, **LingBot 2.0 suite**, **LFM2.5** text+VL-450M, **Robostral Navigate**, LeRobot+**GR00T 1.7**, Cosmos 3 path, YOLO26, LEVIO, AutoFly/UAV-Track VLA papers | Production-open robotics platforms; single-cam language nav; edge structured VL |

---

## 2. Language & edge agents

### 2.1 Foundation & small LMs (all meaningful)

| Lead | When | What | Grade |
| --- | --- | --- | --- |
| llama.cpp / GGUF ecosystem | 2023– | Universal edge runtime | **P0-SHIP** |
| Phi-2 / Phi-3 / Phi-3.5 mini | 2023–25 | Small SLM culture | PATTERN (LFM usually wins tool+speed) |
| Gemma 2 / Gemma 3 270M | 2024–25 | Google small open models | R&D alt brain |
| Qwen2 / Qwen2.5 / Qwen3 small | 2024–26 | Strong multilingual + tools | R&D alt; Indic path |
| MobileLLM / TinyLlama class | 2023–24 | Phone-class LM experiments | PATTERN |
| **LFM2 / LFM2.5 family** (350M–1.2B, MoE, 230M) | 2025–26 | Edge tool-use specialist | **P0-SHIP** |
| **Needle 26M** (Cactus) | 2026 | Ultra-fast tool router | **P0-SHIP** |
| FunctionGemma / tool-specialists | 2025–26 | Tiny tool models | R&D vs Needle |
| Constrained decoding: **GBNF**, Outlines, XGrammar, guided JSON | 2023–26 | Schema-valid tool calls | **P0-SHIP** |
| Chat templates / Jinja standardization | 2024– | Stop prompt drift | **P0-SHIP** |
| Antidoom / FTPO (loop reduction) | 2026 | Small reasoning reliability | P2 if larger reasoners |
| Prefix / KV cache reuse | always | System-prompt once | **P0-SHIP** |

### 2.2 Vision-language (edge → large)

| Lead | When | What | Grade |
| --- | --- | --- | --- |
| CLIP / SigLIP / SigLIP2 | 2021–25 | Vision encoders for VL & robots | PATTERN / backbone |
| LLaVA lineage | 2023– | Open VL recipe | PATTERN |
| PaliGemma / Florence-2 | 2024– | Small VL + grounding | R&D |
| SmolVLM / SmolVLM2 | 2024–25 | Sub-1B VL | R&D vs LFM-VL |
| InternVL / Qwen2-VL / Qwen2.5-VL | 2024–26 | Strong open VL | Cloud/train or large NPU only |
| **LFM2-VL / LFM2.5-VL-450M / 1.6B** | 2025–26 | Edge VL + bbox + tools | **P2-ADOPT** (Director’s Eye) |
| **LFM2.5-VL-Extract** | 2026 | Structured JSON from images | P2 preflight / shot cards |
| Molmo / Molmo2 / Molmo2-ER (AI2) | 2024–26 | Open multimodal + embodied reasoning | R&D reasoning recipes |
| Gemini / GPT-4V class | closed | Cloud ceiling | AVOID flight path |

---

## 3. VLA, policies & “robot brains”

### 3.1 Canonical VLA / policy line

| Lead | When | What | Grade |
| --- | --- | --- | --- |
| **RT-1** | 2022 | Transformer policy scale | PATTERN |
| **RT-2** | 2023 | Actions as tokens; coining VLA | PATTERN |
| **ACT** (Action Chunking) | 2023 | Chunked imitation | PATTERN for smooth control |
| **Diffusion Policy** | 2023– | Generative continuous actions | R&D for style motion |
| **Open X-Embodiment (OXE)** | 2023 | 1M+ traj, 22 embodiments | PATTERN for data standards |
| **DROID** | 2024 | In-the-wild Franka scale | Data lead (manip) |
| Bridge / BC-Z / Fractal / RoboMIND | 2022–25 | Domain datasets | Data lead |
| **Octo** (27–93M) | 2024 | Compact diffusion generalist | R&D small policy |
| **OpenVLA** 7B | 2024 | Open OXE VLA | R&D / train only |
| OpenVLA-OFT / fine-tune recipes | 2025– | Efficient adaptation | PATTERN |
| **π0 / π0.5 / π0.7** (Physical Intelligence) | 2024–26 | Closed generalist + memory/RL tokens | PATTERN (steerability, memory) |
| **NVIDIA GR00T N1 → 1.7** | 2024–26 | Humanoid VLA; open-er path; LeRobot | R&D (humanoid-centric) |
| **SmolVLA** (~450M) | 2025 | Lightweight VLA / LeRobot | R&D aerial finetune later |
| **MolmoAct / MolmoAct 2** (ARM) | 2025–26 | 3D reason-then-act; open data/code | **P2-ADOPT** (reasoning pattern + open recipes) |
| **LingBot-VLA / VLA 2.0** | 2026 | 20k→60k h multi-embodiment; MoE action | R&D cross-embodiment |
| Figure Helix | 2025– | Dual-system factory humanoid | PATTERN (ops reliability) |
| Skild Brain | 2025–26 | Omni-bodied closed | Watch only |
| EO-1 / EmbodiedOneVision | 2025 | Unified VTA interleaved | R&D |
| Edge VLA / TinyVLA / modular VLA papers | 2024–25 | Prove modular edge > mono VLA on Pi | **PATTERN → validates our stack** |

### 3.2 Aerial-specific VLA / VLN (2025–26 surge)

| Lead | What | Grade |
| --- | --- | --- |
| AerialVLN / CityNav / OpenFly benchmarks | Language→UAV metrics | R&D eval |
| **AutoFly** UAV VLA | End-to-end outdoor; often offboard GPU | R&D |
| UAV-Track VLA | Tracking via VLA | R&D |
| ScoutVLA / AIR-VLA / LiteVLA dual-rate | Efficiency for aerial | **PATTERN** (dual-rate inference) |
| Aerial VLN surveys 2026 | Roadmap + sim platforms (AirSim, Isaac) | R&D |
| **Robostral Navigate** (Mistral, 8B) | Single-RGB language nav; pointing; sim train; flying claim | **P2-ADOPT pattern** (pointing, sim scale, BC→RL); distill for onboard |

**Truth:** Aerial VLA is **hot research**; almost none are **nano production-proven** closed-loop. Leads = curriculum + eval + dual-rate design, not drop-in brains.

---

## 4. World models & simulation

| Lead | When | What | Grade |
| --- | --- | --- | --- |
| PlaNet / Dreamer / DreamerV3 | 2019–24 | Latent RSSM control | R&D |
| DayDreamer / real-robot world models | 2023– | Sample efficiency | R&D |
| **NVIDIA Isaac Sim / Lab** | ongoing | Photoreal + RL | **P0-SHIP** (data + SITL path) |
| **Pegasus + PX4 SITL** | ongoing | Drone-specific | **P0-SHIP** |
| AirSim / Gazebo / JMAVSim | classic | Fast CI SITL | **P0-SHIP** |
| **Cosmos** (→ Cosmos 3) | 2025–26 | Physical AI world foundation | **P2** synthetic data |
| **LingBot-World 2.0 / VA / Video** | 2026 | Embodied video/world | **P2** offline data |
| Genie Envisioner / AgiBot world | 2025 | Manip world+act | R&D |
| V-JEPA / latent planners | 2025–26 | Latent imagination | R&D |
| Position papers: “more than VLA+WM” | 2026 | Data engines, rewards, retargeting | PATTERN (data flywheel) |
| Domain randomization literature | classic | Wind, light, textures | **P0-SHIP** |

---

## 5. Perception — detection, tracking, re-ID

### 5.1 Detection

| Lead | When | What | Grade |
| --- | --- | --- | --- |
| YOLO lineage v5→v8→v11→**v26** | 2020–26 | Industry default detect | **P0** candidate (license!) |
| **PicoDet / PP-PicoDet** | 2021– | ARM/ncnn speed king class | **P0-SHIP** |
| NanoDet / YOLO-Fastest | 2021– | Ultra-light | R&D |
| RT-DETR / RF-DETR | 2023–26 | End-to-end DETR class | R&D accuracy |
| Grounding DINO / YOLO-World / open-vocab detect | 2023–25 | Open vocabulary | P2 with VL |
| Person-only / VisDrone aerial fine-tunes | ongoing | Domain transfer | **P2-ADOPT** |

### 5.2 Multi-object tracking

| Lead | When | What | Grade |
| --- | --- | --- | --- |
| SORT / DeepSORT | 2016–17 | Classic association | PATTERN |
| **ByteTrack** | 2021 | Simple high-recall assoc | **P0-SHIP** lite |
| **BoT-SORT** | 2022– | CMC + appearance; 2026 crowded default | **P2-ADOPT** |
| OC-SORT / StrongSORT | 2022– | Occlusion variants | R&D |
| Sparse LK / optical-flow bbox prop | classic | Between detect frames | **P0-SHIP** |
| OSNet / ReID embeddings | 2019– | Re-acquire identity | P2–3 |
| YOLO+BoT-SORT multi-UAV (2025) | 2025 | Aerial tracking baseline | PATTERN |

### 5.3 Depth, geometry, glass

| Lead | When | What | Grade |
| --- | --- | --- | --- |
| MiDaS | 2020– | Relative depth classic | PATTERN |
| ZoeDepth | 2023 | Metric monocular | R&D |
| **Depth Anything → V2** (+ small 25M) | 2024 | Foundation MDE | **P2** advisory depth |
| Metric3D / v2, UniDepth, Depth Pro | 2024–25 | Metric / sharp depth | R&D |
| **Depth Anything 3** (community 2026) | 2026 | Next DA generation | Watch |
| Marigold / diffusion depth | 2024 | High detail, slow | AVOID realtime |
| **LingBot-Depth / 2.0** (masked depth modeling) | 2026 | Sparse→dense; **glass/mirrors** | **P2-ADOPT** NPU |
| Multi-zone **ToF** (VL53L8CX, TMF8828) | hardware | True near-field metric | **P0-SHIP** |
| Stereo / active stereo (OAK etc.) | hardware | Heavy for nano | Production optional |
| Promptable / fused depth (PromptDA class) | 2025– | LiDAR/ToF+mono fusion | **P2 PATTERN** |

### 5.4 SLAM / VIO / state estimation

| Lead | When | What | Grade |
| --- | --- | --- | --- |
| **PX4 EKF2** | ongoing | Production drone state | **P0-SHIP** |
| ORB-SLAM3 | 2021 | Full SLAM | AVOID companion P0 (heavy) |
| VINS-Mono / OpenVINS | 2018– | VIO standard | P2 fixed-cam branch |
| **Basalt** (BSD) | — | License-clean VIO | P2 production VIO |
| **LEVIO** embedded C VIO | 2026 | Ultra-low power VIO | **P2** watch |
| SVO / SVO Pro | classic | Fast VO; **GPL/commercial** | AVOID (audit) |
| cuVSLAM / vendor VIO | — | Fast on Jetson | R&D if NPU path |
| Optical flow + ranging sensors | hardware | Indoor hold | **P0-SHIP** |

**Lead:** Treat **state estimation as FC-owned** unless GPS-denied demos force a fixed-cam VIO branch.

### 5.5 Spatial foundation (Robbyant & peers)

| Lead | What | Grade |
| --- | --- | --- |
| **LingBot-Vision** (21M–1.1B) | Robot vision backbone | **P2** |
| **LingBot-Map** | Streaming 3D reconstruction | **P3** creator maps |
| DINOv2 / DINO-video robotics priors | Self-sup features | PATTERN |
| 3DGS / Gaussian splat mapping | Novel view / scene | P3 offline (not control) |

---

## 6. Control, liquid nets & safety architecture

| Lead | When | What | Grade |
| --- | --- | --- | --- |
| **LTC** liquid time-constant nets | 2020–21 | Continuous-time adaptive RNN | PATTERN |
| **CfC** closed-form continuous-time | 2022 | Fast liquid nets (`ncps`) | **P0-SHIP** advisory controller |
| MIT liquid **drone OOD navigation** | 2023 *Science Robotics* | Vision fly-to-target OOD | **PATTERN** (why CfC on drones) |
| Liquid AI LFMs | 2024–26 | From LNN research → edge FMs | **P0** language plane |
| MPC / iLQR / differential flatness | classic | Trajectory optimization | P2 advanced planner |
| EGO-Planner / Fast-Planner | UAV planning | Local map planning | Production NPU later |
| Jerk/snap limited trajectories | classic | Cinematic smoothness | **P0-SHIP** |
| **PX4 OFFBOARD + failsafe SM** | ongoing | COM_OF_LOSS_T etc. | **P0-SHIP** |
| Deterministic **arbiter / supervisor** pattern | industrial autonomy | ML never owns motors | **P0-SHIP** |
| Runtime assurance / simplex architecture | aviation/robotics | Simple controller backup | **PATTERN** |
| Constrained RL / safety filters | research | CBF etc. | R&D |

---

## 7. Voice & multimodal I/O

| Lead | What | Grade |
| --- | --- | --- |
| Whisper / faster-whisper / Whisper.cpp | STT classic | Product alt |
| **Moonshine** + flavors (per-language) | Tiny ASR | **P2 product** |
| Silero VAD | VAD MIT | **P2 product** |
| openWakeWord / microWakeWord | Wake word | Product optional |
| Piper TTS | Classic TTS | Fallback |
| **Kokoro-82M** | High quality small TTS | **P2 product** |
| On-device vs BT-buds voice | Product lesson (DJI) | **P0 PATTERN** — buds not prop-mic |
| LFM2-Audio class | Speech edge | Watch |

---

## 8. Data, training & tooling platforms

| Lead | What | Grade |
| --- | --- | --- |
| **LeRobot** (HF) | Datasets, policies, VLA recipes; GR00T 1.7 integration 2026 | **P2-ADOPT** data schema |
| HF robotics dataset explosion (2024–25) | Scale culture | PATTERN |
| Open X-Embodiment format | Cross-embodiment | PATTERN for our FDR→train |
| Teleop / DAgger loops | Human correction | **P0-SHIP** for LNN |
| Isaac Teleop | Standardized teleop | R&D |
| Unsloth / TRL / LoRA for VL | Cheap finetune | **P2** VL domain adapt |
| Modal / cloud GPU bursts | Train without local cluster | **P0** infra |
| Flight data recorders | Aviation + autonomy | **P0-SHIP** |
| Scenario / HIL harnesses (RAI class) | Agent test matrices | **P2-ADOPT** |

---

## 9. Hardware & edge silicon leads

| Lead | What | Grade |
| --- | --- | --- |
| RPi 4/5 + ncnn culture | Cheap companion | **P0** prototype |
| **Hailo-8 / 8L + AI HAT** | High TOPS/W vision | **P2** demo NPU |
| Coral / EdgeTPU | Legacy edge | Limited |
| Jetson Orin Nano / NX | Strong but grams/watts | EVT option / ground test |
| **RK3588 / RK3588S** | Cost NPU Linux | **P2 EVT** candidate |
| **Ambarella CV5x** | Drone-native ISP | **P2 EVT** candidate |
| Qualcomm Flight / RB | Integrated AI+RF | Watch India supply |
| STM32H7 / H743 AIO FC | PX4 class | **P0-SHIP** |
| Multi-zone ToF 8×8 | Gram-cheap depth | **P0-SHIP** |
| Micro gimbals / EIS trade | Mass vs magic | Product decision |
| Sub-250 g consumer (Neo, HoverAir, IZI) | Product envelope proof | **PATTERN** (mass is possible) |

---

## 10. Consumer / market / product leads (UX constraints)

| Lead | What | Grade |
| --- | --- | --- |
| DJI ActiveTrack / MasterShots | Tracking UX bar | PATTERN UX |
| DJI Neo / Neo 2 voice + sensing | Voice via phone/buds; omni sensing | **PATTERN** (don’t invent onboard mic) |
| HoverAir self-flying | Zero-skill launch | UX bar |
| India DJI ban + IZI legal 4K | Go-to-market reality | **P0 product constraint** |
| Grey-market pressure | Speed to ship | Business lead |

---

## 11. Safety, reliability, software architecture leads

| Lead | What | Grade |
| --- | --- | --- |
| Layered autonomy (deliberative / reactive / reflexive) | Classic AI robotics | **P0** maps to L1/L2/L3 |
| ROS 2 + Nav2 | Industry middleware | AVOID full stack product tax |
| MAVLink / MAVSDK | Drone standard | **P0-SHIP** |
| Watchdogs, heartbeats, setpoint streams | PX4 OFFBOARD law | **P0-SHIP** |
| Structured logging / MCAP / jsonl FDR | Debug + ML data | **P0-SHIP** |
| Property-based / fault-injection tests | Critical software | **P0-SHIP** G8 |
| Signed model artifacts + license ledger | Production firmware | **P0-SHIP** |
| Feature flags / progressive rollout | Fleet ops | **P0-SHIP** |

---

## 12. GarudaOne “pull list” — consolidate

### Must internalize (already or Phase 1)

1. PX4 EKF2 + OFFBOARD failsafes  
2. Flight Arbiter (supervisor)  
3. PicoDet/ByteTrack-lite/LK + ToF governor  
4. LFM2.5-230M + Needle + GBNF  
5. CfC imitation + clamps + jerk smooth  
6. FDR + DAgger  
7. Sim split: headless SITL + Isaac data  
8. Text NL first; BT voice later  

### Strong Phase 2 pulls

1. LFM2.5-VL-450M Director’s Eye + grounding  
2. LingBot-Depth 2.0 on NPU + ToF fusion  
3. BoT-SORT when multi-person  
4. Pointing goals (Robostral pattern)  
5. AI HAT / Hailo for benches  
6. LeRobot-compatible dataset schema  
7. HIL scenario matrix (RAI-like, no ROS required)  
8. Dual-rate inference pattern (LiteVLA literature)  

### Phase 3+ / production pulls

1. LingBot-Vision/Map; shot style memory  
2. Distilled language-nav planner  
3. Custom SoC (RK/Ambarella class)  
4. Cosmos / LingBot-World synthetic cinematography  
5. Optional VIO (LEVIO/Basalt) GPS-denied  
6. License-clean production detector (or paid YOLO)  

### Explicit non-pulls (for product critical path)

- End-to-end large VLA on motor loop  
- Full SLAM on companion for P1  
- Cloud inference for flight commands  
- GPL VO on gimbal  
- Onboard always-on mic  
- Closed π/Skild dependency for ship date  

---

## 13. Watchlist cadence (ongoing leads)

| Cadence | Check |
| --- | --- |
| **Weekly** | Liquid / Robbyant / AI2 / Mistral robotics releases; HF trending robotics |
| **Monthly** | arXiv aerial VLN/VLA; Ultralytics YOLO; Depth Anything lineage |
| **Quarterly** | EVT SoC bake-off; license ledger; India regs; competitor Neo/IZI/HoverAir |
| **Per phase gate** | Re-score this catalog grades against power/mass measurements |

---

## 14. Sources (representative, not exhaustive)

**Models / orgs:** Liquid AI blogs & HF; AI2 MolmoAct; Robbyant GitHub; Mistral Robostral; Physical Intelligence; NVIDIA Isaac/GR00T/Cosmos; Hugging Face LeRobot.  
**Papers:** RT-2; OpenVLA; OXE; Diff. Policy; LTC/CfC; Science Robotics liquid drones 2023; Depth Anything V2; BoT-SORT; AutoFly; Aerial VLN surveys 2026; LEVIO.  
**Systems:** PX4 docs; Qengineering PicoDet; Ultralytics trackers.  
**In-repo:** `garudaone-architecture/*`, `lingbot-*`, `future-phases/01–06`.

---

## 15. One-sentence doctrine

> **Ship a failsafe modular stack that can absorb any future lead (VL, depth, VLA distill, NPU) as a plug-in — never as a replacement for the flight controller or the arbiter.**

This catalog is the inventory of plugs. Update it; don’t redesign the socket every week.
