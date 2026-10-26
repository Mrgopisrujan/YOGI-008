# Embodied AI Landscape 2026 — Deep Dive

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
>
> - Local voice transport is integrated; the exact STT bundle still requires target-Pi qualification.
> - Production VIO/SLAM adapters are absent or deferred.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.

> [!NOTE]
> This file is a roadmap or future-phase proposal. It does not describe the current deployed system. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).

**Date:** 2026-07-13  
**Scope:** Companies and open stacks relevant to GarudaOne (aerial cinematography autonomy).  
**Sources:** Vendor blogs, arXiv, Hugging Face, GitHub, X, press (Reuters/BusinessWire), in-repo `lingbot-*`.

> Hardware is **not** treated as a hard ceiling in this document. Dev platforms may use AI HAT / NPU. Production still optimizes for **mass, watts, cost, failsafe**.

---

## 1. Executive map

```text
LANGUAGE / AGENT (edge)          SPATIAL PERCEPTION              ACTION / POLICY
─────────────────────            ──────────────────              ────────────────
Liquid AI LFM2.5 family          Robbyant LingBot-Depth/Vision   AI2 MolmoAct 2 (ARM)
Needle-class routers             LingBot-Map                     Physical Intelligence π0.x
Mistral (text + Robostral)       Depth Anything class            Robbyant LingBot-VLA 2.0
                                 Orbbec + ToF hardware           Mistral Robostral Navigate
                                                                 NVIDIA GR00T / Cosmos
                                                                 Skild / Figure (closed)

SIM / DATA / FRAMEWORKS
───────────────────────
AI2 MolmoSpaces + MolmoBot
NVIDIA Isaac / Cosmos
Robotec RAI (agentic + HIL)
LeRobot (HF) + open datasets
Pegasus / PX4 SITL (our path)
```

**Industry consensus (2026):**  
Foundation models for robots are real; **demo ≠ product**. Production winners use **modular stacks** (perception + policy + hard safety), not pure end-to-end VLA on the motor path. Edge-capable modular VLAs (Pi 5 + Hailo class) already work for ground robots; aerial + sub-250 g remains harder (power + mass + failsafe regulation).

---

## 2. Player dossiers

### 2.1 Allen Institute for AI (AI2 / Ai2)

| Item | Detail |
| --- | --- |
| **Products** | **MolmoAct / MolmoAct 2** (Action Reasoning Models), **Molmo 2-ER**, **MolmoSpaces**, **MolmoBot**, open datasets (bimanual YAM 720h+) |
| **Thesis** | Reason in **3D before acting** (ARM); fully open weights + data + code; simulation-first zero-shot transfer |
| **Performance notes** | MolmoAct 2 up to **~37× faster** than MolmoAct (~180 ms base action call on H100-class eval setup vs multi-second predecessor); adaptive depth (“Think”); strong zero-shot Franka results; LeRobot integration |
| **Licensing** | Research-friendly open artifacts (verify redistribution for commercial firmware) |
| **Aerial relevance** | Low for direct flight control (manipulation-centric). **High** for: embodied reasoning backbone ideas, open data discipline, adaptive 3D reasoning, sim ecosystems |
| **Steal for GarudaOne** | (1) Explicit **3D/spatial reasoning pass** before risky maneuver (Director’s Eye + arbiter). (2) **Open training recipe culture** for LNN/VLA finetunes. (3) Adaptive compute: run depth/VLM only when useful. (4) MolmoSpaces-style domain randomization mindset for Isaac |

**Links:** [allenai.org/embodied-ai](https://allenai.org/embodied-ai), [MolmoAct 2 blog](https://allenai.org/blog/molmoact2), [github.com/allenai/molmoact2](https://github.com/allenai/molmoact2)

---

### 2.2 Robbyant (Ant Group) — LingBot family

| Item | Detail |
| --- | --- |
| **Products** | **LingBot-Depth 2.0**, **LingBot-Vision** (21M→1.1B), **LingBot-Map**, **LingBot-VLA / VLA 2.0**, **LingBot-World 2.0**, **LingBot-VA 2.0**, **LingBot-Video** |
| **Thesis** | Full stack for embodied AI: perception foundation → VLA brain → world model; heavy real-world hours; open-source push |
| **Scale claims (2026)** | VLA 1.0 ~20k hours / 9 platforms; VLA 2.0 ~**60k hours**, multi-embodiment, whole-body action dims, MoE action (~1.6B / 0.6B active), &lt;130 ms latency class on RTX 4090 post-train path; Depth 2.0 glass/mirror; Vision trained on filtered large web image sets |
| **Licensing** | Many Apache-2.0 / open weights — **verify each artifact before production** |
| **Aerial relevance** | **Highest in the open landscape for our sensors.** Depth completion for glass is exactly cinematic indoor failure mode. Vision small variants (21M–hundreds of M) fit edge NPUs. VLA is manipulation/mobile-manipulation first — not drop-in for OFFBOARD velocity |
| **Reference clones** | Not vendored in-repo (removed 2026-07-15 cleanup); re-clone from Robbyant GitHub if needed for a bench-off |
| **Steal for GarudaOne** | (1) **Production NPU path: LingBot-Depth** fused with ToF. (2) Small **LingBot-Vision** backbone for person/scene features. (3) **Map** for pre-flight / creator location memory (Phase 3). (4) Study VLA 2.0 **cross-embodiment action representation** for multi-airframe later. (5) World models for **sim data gen** (not online control) |

**Links:** [github.com/Robbyant](https://github.com/Robbyant), Orbbec partnership announcements, arXiv LingBot-Depth 2601.17895

---

### 2.3 Liquid AI

| Item | Detail |
| --- | --- |
| **Products** | **LFM2 / LFM2.5** text (230M → 1.2B → MoE), **LFM2.5-VL-450M**, LFM2-VL-3B robotics demos (demo use unverified), Audio models, enterprise fine-tunes |
| **Thesis** | **Edge-native** foundation models: tool use, structured output, privacy, hybrid conv+attention for CPU/NPU speed |
| **Edge numbers** | LFM2.5-230M: **42 tok/s Pi 5**, 213 tok/s Galaxy S25 Ultra (vendor). VL for episodic scene/tool use. Robotics: LFM2-VL-3B with **AMD + Robotec RAI** for warehouse-style agentic inspection (HIL sim first) |
| **Licensing** | LFM open license — **confirm redistribution for embedded commercial product** early |
| **Aerial relevance** | **Direct fit** for GarudaOne “Director” brain (already in architecture docs). Not a flight controller |
| **Steal for GarudaOne** | (1) Stay on **official LFM** + GBNF tool calls. (2) Scale brain: 230M prototype → **350M/1.2B** when NPU allows, same API. (3) **VL-450M** as Director’s Eye. (4) Copy **HIL + agent framework** pattern (RAI-like) for scenario testing without flying |

**Links:** [liquid.ai](https://www.liquid.ai/), [LFM2.5-230M](https://www.liquid.ai/blog/lfm2-5-230m), [Agentic robotics edge](https://www.liquid.ai/blog/agentic-robotics-at-the-edge-liquid-ai-amd-and-robotec-ai-demonstrate-lfm2-vl-3b-in-embedded-autonomy)

---

### 2.4 Mistral AI — Robostral Navigate

| Item | Detail |
| --- | --- |
| **Product** | **Robostral Navigate** (July 2026): **8B** VLA-style navigation model |
| **Thesis** | Navigation is the foundation of general robotics; single RGB + language is enough with the right training |
| **Tech highlights** | **Pointing-based** next-waypoint in image (robust to intrinsics/scale); fallback to body-frame displacements; trained **entirely in sim** (~400k trajectories / 6k scenes); prefix-cache tree training (**~22×** fewer tokens); online RL (CISPO) +3.2% SR; **76.6%** R2R-CE unseen; claimed wheeled/legged/**flying** generalization |
| **Licensing** | Commercial / contact sales (not Apache open weights as of announcement) — treat as **reference architecture + future partner**, not free ship |
| **Aerial relevance** | **High conceptually**: language → navigate complex spaces with one camera is the creator “go through the doorway and orbit me” dream. **8B is heavy** for nano; distill or use as cloud/offline planner first |
| **Steal for GarudaOne** | (1) **Pointing / gaze targets** in image for cinematic goals (“go there”) instead of only metric NED. (2) **Sim-first navigation curriculum** at scale. (3) **Prefix-cache episode training** for our LNN/VLA finetunes. (4) RL fine-tune after BC (not pure imitation). (5) Keep multi-sensor (ToF) as **failsafe envelope**, not as the only path to intelligence |

**Links:** [mistral.ai/news/robostral-navigate](https://mistral.ai/news/robostral-navigate/), Reuters coverage July 2026

---

### 2.5 Robotec.ai — RAI framework

| Item | Detail |
| --- | --- |
| **Product** | **RAI** — multi-agent framework for embodied AI on ROS 2; voice, tools, scenarios, HIL |
| **Thesis** | Agentic layer above robot stacks; validate in simulation before field |
| **Aerial relevance** | ROS 2 is **overkill for our single-purpose product**, but the **pattern** (agent tools + HIL + scenario suites) is gold |
| **Steal for GarudaOne** | (1) Scenario catalog: “target lost”, “thermal”, “glass wall”, “Wi-Fi drop”. (2) Multi-agent roles: Director / Tracker / Safety. (3) HIL with PX4 SITL (we already prefer this over full ROS) |

**Links:** [github.com/RobotecAI/rai](https://github.com/RobotecAI/rai), arXiv 2505.07532

---

### 2.6 Physical Intelligence (π)

| Item | Detail |
| --- | --- |
| **Products** | **π0 / π0.5 / π0.7** steerable generalist policies, memory (MEM), online RL tokens |
| **Thesis** | Universal physical intelligence layer across robots/homes |
| **Licensing** | Mostly closed / limited access |
| **Steal for GarudaOne** | Ideas only: **steerable** policies (style: cinematic vs aggressive), **multi-scale memory** for long shots, extract RL from frozen VLA. Do **not** wait on their weights for product |

---

### 2.7 Skild AI, Figure AI, NVIDIA GR00T / Cosmos

| Player | What they do | GarudaOne takeaway |
| --- | --- | --- |
| **Skild** | Omni-bodied robot brain, multi-form factor | Cross-embodiment training data strategy |
| **Figure** | Humanoid + Helix VLA; factory deployments | Demo-to-production gap is real; reliability & tooling matter more than paper SOTA |
| **NVIDIA** | GR00T humanoid models, **Cosmos** world models, Isaac Lab/Sim | Use Cosmos/Isaac for **data generation** and photoreal synthetic cinematography; not runtime on nano |

---

### 2.8 Edge modular VLA practice (community / deepsense-class)

Practical 2025–2026 deployments show:

- **Modular** (YOLO/detect + small LLM + VSLAM) beats monolithic VLA on Pi-class.  
- **Pi 5 + Hailo-8L** is a known sweet spot for vision+language+spatial on ~100 g companion boards.  
- Latency isolation: perception 20–30 Hz, language 1 Hz, control 20–100 Hz.

This **validates GarudaOne’s 3-layer + Arbiter** design rather than contradicting it.

---

## 3. Cross-cutting technical patterns (what “everyone” converges on)

| Pattern | Who | Production implication |
| --- | --- | --- |
| **Reason then act** (3D / spatial tokens) | AI2 MolmoAct | Cinematic risk checks before aggressive orbits |
| **Foundation perception models** | Robbyant Vision/Depth/Map | Own depth/vision as NPU modules, not ad-hoc nets only |
| **Edge language agents** | Liquid | Keep offline NL; GBNF/tools |
| **Pointing / image-space goals** | Robostral | Shot composition UX: tap or say “there” |
| **Sim-scale data + RL after BC** | Robostral, AI2, π | LNN + later aerial VLA training loop |
| **World models offline** | Robbyant World, Cosmos | Synthetic flights, not closed-loop 400 Hz |
| **Agent frameworks + HIL** | Robotec RAI, Liquid | Scenario harness before field |
| **Safety floor outside ML** | Everyone serious (implicit in industrial) | PX4 failsafes + Flight Arbiter non-negotiable |
| **Open weights where possible** | AI2, Robbyant | Faster iteration; still need license ledger |
| **Closed SOTA brains** | π, Skild, Figure, parts of Mistral | Partner or ignore; don’t block roadmap |

---

## 4. Gap analysis: landscape vs GarudaOne today

| Capability | Landscape SOTA (2026) | GarudaOne now (docs 12) | Gap |
| --- | --- | --- | --- |
| On-device NL agent | LFM2.5 / Needle | Planned, software rebuild | Implement |
| Failsafe authority | Industrial + PX4 community | Arbiter designed | Ship A1–A3 |
| Depth / glass | LingBot-Depth 2.0 | ToF only prototype | Phase 2 NPU |
| Single-cam language nav | Robostral Navigate 8B | Speed governor + track | Distill / episodic planner |
| Action foundation | MolmoAct2 / VLA 2.0 / π | CfC LNN imitation | Aerial finetune track |
| World model data | Cosmos / LingBot-World | Isaac+Pegasus plan | Operationalize |
| Creator cinematography | Niche (DJI closed) | Core product bet | **Our moat if we ship UX** |

**Strategic read:** The open embodied wave is **manipulation- and ground-nav-heavy**. Almost no open stack owns **legal Indian market + offline conversational cinematic drone**. That is GarudaOne’s wedge — **not** racing π0 on LIBERO.

---

## 5. What not to cargo-cult

1. **8B navigation models on-device for nano** without NPU — power and thermal kill flight time.  
2. **End-to-end VLA setpoints at 20 Hz** on early hardware — fails G3/G8 style reliability.  
3. **World model as realtime controller** — use for data/sim.  
4. **Dropping ToF because Robostral is single-cam SOTA** — aerial glass + sun + motion need multi-modal envelope for production safety.  
5. **Closed-brain dependency** for ship date — only open/licensed path is production-first.

---

## 6. Watchlist (re-scan quarterly)

| Item | Why |
| --- | --- |
| Robostral open weights / smaller distill | Language navigation on NPU |
| LingBot-VLA 2.0 aerial or multirotor adapters | Cross-embodiment for drones |
| LFM2.5-VL quantized NPU packs | Director’s Eye at &lt;1 s |
| AI2 aerial / drone datasets if any | Reasoning transfers |
| Hailo / Qualcomm / Ambarella drone reference designs | Production BOM |
| India DGCA / Digital Sky rule changes | Compliance |

---

## 7. References (primary)

- Liquid AI LFM2.5-230M blog; Agentic robotics (AMD/Robotec)  
- AI2 MolmoAct 2 blog + GitHub molmoact2  
- Mistral Robostral Navigate announcement  
- Robbyant GitHub + LingBot press (VLA 2.0, Depth 2.0, Vision, World 2.0)  
- Robotec RAI GitHub / arXiv 2505.07532  
- Physical Intelligence site (π0.x)  
- deepsense-style edge modular VLA reports (Pi + Hailo)  
- `garudaone-architecture/11`, `12` (lingbot-depth/lingbot-vision reference clones removed 2026-07-15; re-clone from Robbyant GitHub if needed)
