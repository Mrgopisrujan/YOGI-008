# Production Transfer Playbook — What We Keep, Adapt, Reject

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
>
> - Needle 2 (45M, `cactus-needle==2.0.0`) replaced Needle 26M as the active constrained router.
> - Local voice transport is integrated; the exact STT bundle still requires target-Pi qualification.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - Land/RTL mode transfer requires PX4 ACK and heartbeat confirmation; physical behavior remains unqualified.
> - The flight profile instantiates C10 and requires an inbound checksummed status reply; physical attitude feedback and motion limits remain unvalidated.
> - Production VIO/SLAM adapters are absent or deferred.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.

> [!NOTE]
> This file is a roadmap or future-phase proposal. It does not describe the current deployed system. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).

**Date:** 2026-07-13  
**Mindset:** Production-first day 0. Everything we adopt must have a path to: **shipped license**, **failsafe**, **&lt;249 g**, **&lt;~3–5 W AI budget (prod)**, **aha UX**.

Companion to [01_embodied_ai_landscape_2026.md](01_embodied_ai_landscape_2026.md). Implementation of Phase 1 remains [garudaone-architecture/12_optimized_rebuild_plan.md](../garudaone-architecture/12_optimized_rebuild_plan.md).

---

## 1. Decision rubric (use on every new model)

Score each candidate 0–2 on:

| Axis | 0 | 1 | 2 |
| --- | --- | --- | --- |
| **Safety isolability** | Owns motors | Advisory only with hard clamps | Pure perception / offline |
| **Latency class** | &gt;2 s in control path | Episodic 0.2–2 s | &lt;50 ms continuous |
| **Power @ target SoC** | &gt;8 W continuous | 2–8 W | &lt;2 W or NPU INT8 |
| **License** | Unknown/AGPL risk | Negotiable commercial | Apache/MIT/BSD + clear redistribution |
| **UX leverage** | Invisible to user | Marginal | Creates “magic” moment |
| **Sim/data path** | None | Manual only | Scalable synth or open data |

**Ship rule:** Sum ≥ 8 and **Safety isolability ≥ 1** for anything on the flight computer. Anything with Safety 0 is **rejected** for production firmware.

---

## 2. Adopt now (Phase 1 / already planned) — production-aligned

| Component | Source | Why production-safe |
| --- | --- | --- |
| **Flight Arbiter + PX4 floor** | Industrial pattern + our doc 11/12 | Deterministic authority; license-clean code we own |
| **LFM2.5-230M + GBNF tools** | Liquid AI | Edge agent; offline; expand model size later without UX change |
| **Needle 26M** | Cactus (MIT) | Hot-path land/stop; tiny |
| **PicoDet-S (Apache) + duty-cycle + ByteTrack-lite + LK** | Community + our 11 | License-clean detector path; YOLO26 only if licensed |
| **CfC LNN advisory + clamps** | ncps Apache + our clamps | Microsecond policy; never unclamped |
| **EKF2 + multi-zone ToF** | PX4 + ST/ams | Failsafe sensing envelope |
| **FDR + DAgger loop** | Autonomy industry | Production reliability + continuous improvement |
| **Text NL prototype → BT-buds voice product** | DJI-class product lesson | Don’t fight prop noise |

These are **keep forever** architectural choices even when models upgrade.

---

## 3. Adopt next (Phase 2–3) — high ROI from landscape

### 3.1 Robbyant stack (already in repo)

| Module | Use in GarudaOne | Production notes |
| --- | --- | --- |
| **LingBot-Depth 2.0** | Dense depth / glass-aware layer fused with ToF | NPU INT8/FP16 only; never sole brake authority |
| **LingBot-Vision (small variants)** | Features for tracking / scene; optional person embedding | Prefer 21M–~100M class on NPU; Apache check |
| **LingBot-Map** | Pre-flight / location memory / creator “same courtyard” | Not real-time control loop |
| **LingBot-VLA 2.0** | Research branch for “style” actions; **not** motor owner | Aerial finetune experiment; action → arbiter proposals |
| **LingBot-World / Video** | Offline synthetic cinematography data | Cloud GPU training only |

### 3.2 AI2 patterns (not necessarily their full model on-drone)

| Pattern | Transfer |
| --- | --- |
| **Action Reasoning (3D-then-act)** | Before aggressive orbit/arc: short spatial check (VLM + ToF/depth). User-visible: “checking path…” |
| **Adaptive depth compute** | Run LingBot-Depth or DA-V2 only when ToF confidence low or user requests “tight space” mode |
| **Open recipe discipline** | Publish internal training cards; version checkpoints (`arch_id` like `cfc_v1_…`) |
| **LeRobot-style integration** | Standard dataset schema for teleop + DAgger so future VLA plug-ins are cheap |

### 3.3 Robostral Navigate patterns

| Pattern | Transfer |
| --- | --- |
| **Image-space pointing goals** | Companion app: “go here” / “frame this corner”; policy outputs pixel goal → body velocity via geometry |
| **Sim-only navigation curriculum at scale** | Isaac/Pegasus: 10k+ language-conditioned indoor routes before outdoor |
| **Prefix-cache episode training** | Cut LNN/VLA train cost 10–20× |
| **BC then online RL** | After imitation, CISPO-like / PPO residual on safety-filtered rewards (collision, jerk, subject framing) |
| **Generalization across robot sizes** | Train with action in normalized body frame + pointing |

**Do not ship full 8B on nano without NPU + thermal proof.** Path: **distill to 0.5–2B** or run Navigate-class model as **episodic high-level planner** (1–2 Hz proposals) under Arbiter.

### 3.4 Liquid / Robotec agent pattern

| Pattern | Transfer |
| --- | --- |
| **HIL scenario matrix** | Warehouse-style: hundreds of scripted failures before field |
| **Agent tools = our tool schema** | `hover`, `track`, `orbit`, `land`, `set_framing` — GBNF locked |
| **Scale LFM with same API** | 230M → 1.2B when NPU free; app UX unchanged |

### 3.5 Edge modular VLA (Pi + AI HAT)

| Pattern | Transfer |
| --- | --- |
| **NPU for vision, CPU for agent, MCU for control** | Maps to our L1/L2/L3 |
| **Hailo / AI HAT on dev platforms** | Unlock LingBot + YOLO26 latency for demos without redesigning software contracts |

---

## 4. Reject or defer (with reasons)

| Idea | Verdict | Why |
| --- | --- | --- |
| End-to-end VLA velocity at 20 Hz as sole controller | **Reject production** | Failsafe, certifiability, debug; use advisory only |
| Cloud LLM for in-flight commands | **Reject** | Latency, privacy, India connectivity, offline claim |
| Pure single-cam no ToF product | **Reject P0** | Glass, sun, cinematography indoors; ToF is cheap grams |
| ROS 2 full stack product | **Reject** | Complexity tax for single-purpose drone |
| Onboard open mic always-on | **Reject** | Prop noise; BT buds product path |
| Depends on closed π/Skild weights for ship | **Reject** | Supply risk |
| World model closed-loop control | **Reject** | Too heavy; offline data only |
| AGPL detector without commercial license | **Reject production firmware** | PicoDet or buy Ultralytics |

---

## 5. Production license ledger (living)

| Component | Prototype | Production action owner |
| --- | --- | --- |
| LFM2.5 family | ✅ evaluate | Confirm Liquid redistribution for firmware images |
| Needle | ✅ MIT | Ship |
| PicoDet / ncnn | ✅ Apache-2.0 / BSD-3 | Ship |
| YOLO26 | Bench only | Commercial license **or** drop |
| LingBot-* | ✅ research | Per-repo Apache/redistribution check |
| OpenVINS | Bench | Prefer Basalt/LEVIO license-clean |
| MolmoAct2 | Research | License + size; likely cloud/train only |
| Robostral | Contact | Partner/distill; not default |
| PX4 | ✅ BSD | Ship |
| Kokoro / Silero / Moonshine | Product voice | Confirm each |

**Rule:** No merge to `production` branch without ledger row green.

---

## 6. Target production software architecture (end state)

```text
┌──────────────────────────────────────────────────────────────┐
│ APP (phone): NL / voice (BT buds) / framing UI / pairing     │
└────────────────────────────┬─────────────────────────────────┘
                             │ encrypted link (non-flight-critical)
┌────────────────────────────▼─────────────────────────────────┐
│ L1 DIRECTOR (NPU/CPU episodic)                                │
│  LFM2.5-* + GBNF tools · Needle · LFM-VL · optional Navigate  │
│  LingBot-Vision features · shot style memory (Phase 3)        │
└────────────────────────────┬─────────────────────────────────┘
                             │ ToolProposal only
┌────────────────────────────▼─────────────────────────────────┐
│ L2a FLIGHT ARBITER (deterministic, ours, MCU-adjacent)        │
│  FSM · SafetyLimits · watchdogs · speed governor · logs       │
└──────────────┬─────────────────────────────┬──────────────────┘
               │ granted mode/limits         │ gimbal grants
┌──────────────▼──────────────┐   ┌──────────▼──────────────────┐
│ L2b REFLEX (NPU continuous) │   │ Gimbal controller           │
│ Detect@10–15 · Track@25–30  │   │ counter-rotation            │
│ LingBot-Depth @1–5 Hz fuse  │   └─────────────────────────────┘
│ CfC / distilled policy      │
│ jerk-limited setpoints      │
└──────────────┬──────────────┘
               │ velocity / yaw_rate @ 20–50 Hz
┌──────────────▼──────────────────────────────────────────────┐
│ L3 PX4 / FC (hard RT) — always owns failsafes                │
└─────────────────────────────────────────────────────────────┘
```

**Invariant from day 0:** L1 never talks to motors. L3 never runs Python ML.

---

## 7. “Aha UX” features mapped to landscape tech

| User moment | Tech stack | Phase |
| --- | --- | --- |
| “Follow me, stay wide” | Needle/LFM → track + framing params | 1 |
| “Understood: orbit left” instant echo | App + GBNF echo before motion | 1 |
| Seamless arc around tree, subject locked | CfC + gimbal counter-rotate + ToF | 1–2 |
| “What’s around me?” / framing tips | LFM-VL Director’s Eye | 2 |
| Glass hallway without crash | LingBot-Depth + ToF + governor | 2 |
| “Go to that doorway” (point or say) | Pointing goal (Robostral pattern) | 2–3 |
| Remembers creator style | Shot memory / style embedding | 3 |
| Indoor GPS-denied | VIO branch + optical flow | 2 |
| Indic voice | Moonshine flavors + Kokoro | Product |
| Sub-250 g 15 min 4K | Custom SoC + micro-gimbal | Production HW |

---

## 8. Day-0 engineering rules (production-first)

1. **Version every model artifact** with hash + `arch_id` + license SPDX.  
2. **Feature flags** for every experimental brain (Navigate, VLA, Depth). Default off in flight.yaml.  
3. **Property tests** for Arbiter grow with every new ToolProposal.  
4. **FDR is product infrastructure**, not debug nice-to-have — enables DAgger, support, legal.  
5. **Sim CI must fail** if anyone routes LNN past clamps.  
6. **Weight/power budgets** are first-class CI metrics once hardware exists (not only code tests).  
7. **India compliance** (class, UIN, RF, privacy) tracked like a feature.

---

## 9. Quick “steal list” for the next 90 days

1. Implement Phase 1 rebuild per doc 12 (Arbiter first).  
2. Stand up **official LFM GGUF** + GBNF tool suite.  
3. Prototype **pointing goal** API in app (even if backend is simple geometric go-to).  
4. Benchmark **LingBot-Vision small** + **Depth** on Pi+AI HAT (latency/power).  
5. Build **scenario harness** (RAI-inspired, no ROS required).  
6. Start **aerial DAgger dataset schema** compatible with future VLA finetune.  
7. Open license talks with Liquid (and Ultralytics only if B1 chooses YOLO26).
