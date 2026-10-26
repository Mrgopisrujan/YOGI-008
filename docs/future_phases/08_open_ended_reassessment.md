# Open-Ended Reassessment (Goals-First, Stack-Agnostic)

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
**Rev note (2026-07-14):** This doc deliberately *de-centered* foundation models vs market table stakes. **GarudaOne product decision (see `09_investor_prototype_definition.md` + `03`):** Phase-1 **investor prototype still requires core offline AI (Needle+LFM+GBNF) + seamless sky experience** — not presets-only. Use this file for tech re-ranking (CfC optional polish, UWB raise, trajectory optimizer), **not** as permission to ship a mute follow drone as P1.

**Method:** Start from product goals only. Survey competitors, arXiv cinematography lines, DIY/community, edge/embodied leads, HF/X/Reddit/web **without** treating prior GarudaOne choices (LFM, CfC, PicoDet, “3-layer liquid”, no-UWB, etc.) as axioms. Then ask: **what still holds, and what should change?**

---

## 1. Goals (what we optimize for)

| Goal | Operational meaning |
| --- | --- |
| **G1 Cinematic output** | Subject framed, smooth motion, gimbal-stable footage people will post |
| **G2 Zero-skill flight** | Creator is not a pilot; RC safety pilot only for R&D |
| **G3 Trust / failsafe** | Won’t fly into people/glass; AI death → safe PX4 behavior |
| **G4 Small & efficient** | Path to **&lt;249 g**, long enough flight for real shoots |
| **G5 Aha interaction** | Natural intent (“follow wide”, “orbit”) beats mode menus |
| **G6 Ship in India** | Legal channel, supportable, competitive vs IZI / grey Neo |
| **G7 Production economics** | BOM, yield, license-clean firmware |

If a technology doesn’t move ≥2 of these, it is R&D, not critical path.

---

## 2. What actually ships in the market (reality check)

| Product class | How they deliver G1–G2 | Language model? | Obstacle | Mass / time |
| --- | --- | --- | --- | --- |
| **DJI Neo / Neo 2** | Preset cinematic modes + ActiveTrack-class follow; voice via **phone/buds** | Thin / cloud-or-phone assisted, not a full onboard agent | Forward LiDAR + mono sensing (Neo 2) | ~151 g, ~19 min class |
| **HoverAir X1 / Pro** | Throw-and-go + **fixed shot templates** (hover, follow, orbit, bird’s eye) | No open-vocab brain | Limited / simpler | Sub-200 g class |
| **Skydio** (heavier) | **Vision-first** omnidirectional obstacle + track | Not the product story | Multi-camera autonomy | Not nano |
| **IZI Mini X Nano (India)** | Manual + basic assist; **legal 4K** | No | Basic | 249 g, long flight |
| **DIY PX4/ArduPilot + companion** | Community: detect→track→setpoint; few ship NL agents | Rare | ToF/LiDAR/stereo experiments | Varies |

**Market lesson (unbiased):**  
Winners sell **reliable follow + presets + camera + battery**. Open-vocabulary onboard LLM is **not** what made Neo/HoverAir win. It can still be a **differentiator** in India (legal + offline conversational), but it is **not** the load-bearing structure of cinematic autonomy.

---

## 3. What cinematography research actually optimizes

Open literature on **aerial cinematography** (not general embodied AI) centers on:

| Line | Core idea | Implication |
| --- | --- | --- |
| **CMU AirLab / artistic principles** | Smooth, safe, **occlusion-free** trajectories; aesthetic rules | Framing + collision + smoothness as **optimization**, not “neural stick feel” alone |
| **Gimbal–body decoupling** (classic papers) | Optimize **drone path** and **camera aim** as coupled but separate systems | Gimbal counter-rotation is real product tech; needs **joint angles + framing cost**, not only velocity CfC |
| **Optimal / aesthetic trajectory planning** | Cost on view angle, subject size in frame, jerk, obstacles | **Trajectory planner with camera objectives** is first-class for G1 |
| **DiffusionCinema (2026)** | Text + image → **UAV trajectory** via diffusion | Alt path: language → **trajectory distribution**, not necessarily LFM tool-calls |
| **ACDC / agentic aerial cinematography (2025)** | Dialogue → cinematic trajectories (indoor demos) | Supports NL, but as **shot planner**, not continuous controller |
| **Multi-ROI aesthetic planning (2026)** | Multiple points of interest, viewpoint selection | Phase 3 “scene intelligence” without full VLA |

**Research lesson:** For G1, the highest-leverage software is often:

```text
subject state + framing goals + obstacle constraints
        → trajectory + gimbal setpoints
        → FC
```

not:

```text
foundation model → actions end-to-end
```

Embodied AI (VLA, LingBot, MolmoAct, Robostral) is a **parallel research river**. It is valuable, but **cinematography-native papers** pull harder toward **planners + gimbal geometry + tracking quality**.

---

## 4. Independent lead map (by goal contribution)

### 4.1 Subject lock (G1, G2)

| Approach | Strengths | Weaknesses | Open verdict |
| --- | --- | --- | --- |
| Vision detect + MOT (YOLO/PicoDet + Byte/BoT-SORT) | No wearable; works outdoor | Occlusion, lighting, twins | **Necessary baseline** |
| Optical flow / CMC between detects | Cheap 25 Hz feel | Drifts without detect | Keep |
| **UWB / RF wearable (tag on person)** | cm-class, occlusion-robust | Extra hardware, pairing, BOM | **Under-weighted in prior stack** — serious G2 reliability path |
| Phone-as-beacon (BLE/UWB phone) | No custom tag | Phone in pocket geometry | Product option |
| Pure VLA tracking papers | Research hype | Latency, unproven nano | Not MVP |

**Change signal:** Prior docs treated GarudaPin/UWB as late optional. Market + positioning tech say: **vision-only follow will always fail in some creator scenarios** (tree, crowd, sun). A **wearable ranging backup** may be more “aha reliability” than a better VLM.

### 4.2 Obstacle safety (G3, G4)

| Approach | Verdict |
| --- | --- |
| Multi-zone ToF / dToF | Best g/W for near field; glass-capable sensors matter |
| Stereo / depth cam | Better range; mass/power |
| Mono foundation depth (DA-V2, etc.) | Advisory; not sole brake |
| LingBot-Depth class completion | Strong for glass **if** NPU; not P0 blocker |
| Omni multi-cam (Skydio style) | Best avoidance; kills nano mass |
| Speed governor tied to range | Non-negotiable software |

**Change signal:** Prior emphasis on LingBot as production unlock is fine; **P0 safety still ToF + speed cap + PX4**. Don’t wait on foundation depth to fly safe demos.

### 4.3 Cinematic motion (G1)

| Approach | Verdict |
| --- | --- |
| Shot **templates** (orbit, follow, rise, reveal) | What HoverAir ships; fastest path to delight |
| Classical **trajectory optimization** (jerk, view angle, occlusion) | Strong academic + real outdoor trials |
| Imitation learning (any policy: CfC, ACT, diffusion policy) | Good for “feel”; needs real demos + clamps |
| Full VLA continuous control | Wrong latency/safety for nano product |
| Gimbal independent control with framing cost | **Must-have** for counter-rotate magic |

**Change signal:** Prior stack elevated **CfC LNN** as the cinematic differentiator because of MIT liquid-drone lineage. Unbiased view: **templates + optimized trajectories + gimbal framing** ship more often than continuous-time nets. CfC remains a **valid advisory policy**, not the only or primary path to cinematic quality. **Do not block ship on LNN training quality.**

### 4.4 Natural language / aha (G5)

| Approach | Verdict |
| --- | --- |
| Mode buttons / app chips only | Ships (HoverAir); weaker aha |
| Finite intent parser (grammar / rules / small classifier) | Extremely reliable; covers 80% phrases |
| Tiny tool LM (Needle 26M; or 200–350M class) | Good for open phrasing → structured tools |
| Edge VLM episodic | Scene Q&A, disambiguation |
| Diffusion text→trajectory | Research alternative to tool→mode |
| Cloud LLM | Latency, offline claim dies |

**Change signal:** Prior narrative: LFM2.5 is the brain. Unbiased: **structured intents + templates** deliver most UX; LFM is an **upgrade layer**. You can sequence:

1. Ship app chips + finite phrases  
2. Add Needle/LFM for freer language  
3. Add VL for visual disambiguation  

…without failing G5 if chips are excellent.

LFM2.5-VL-450M remains a **strong episodic option**, not a reason to re-center the architecture on multimodal foundation models.

### 4.5 State estimation (G3, G4)

| Approach | Verdict |
| --- | --- |
| PX4 EKF2 outdoor | Default correct |
| Companion SLAM | Heavy; rarely needed for outdoor follow |
| VIO fixed cam | Indoor / GPS-denied product slice |
| Gimbal-mounted VO | Still architecturally wrong for body pose |

**Change signal:** Prior anti-SLAM-for-P1 stance **still holds** under open review. Your earlier YOLO→SLAM→WorldState chain overfits general robotics textbooks, not outdoor creator drones.

### 4.6 Flight stack & companion (G3, G6, G7)

| Approach | Verdict |
| --- | --- |
| PX4 OFFBOARD + companion | Proven; BSD |
| ArduPilot guided/python | Also proven; GPL considerations for proprietary |
| Fully custom FC | Unnecessary R&D risk |
| ROS 2 Nav full stack | Great lab; product tax for single-purpose drone |
| Modular processes + arbiter | Still best reliability pattern industry-wide |

**Change signal:** PX4 + deterministic supervisor **still correct**. Not Liquid-specific.

---

## 5. Embodied-AI wave — re-scored without brand bias

| Wave item | Helps which goals? | Honest priority |
| --- | --- | --- |
| Liquid LFM / Needle | G5 offline NL | High **if** offline agent is the India wedge; else medium |
| LFM2.5-VL-450M | G5 scene/re-acquire | Medium, episodic |
| Robbyant Depth/Vision | G3 glass, G1 scene | Medium-high on NPU |
| Robostral Navigate | Language navigation | Medium as **pattern**; 8B onboard low for nano |
| MolmoAct / OpenVLA / π / GR00T | General manipulation brains | **Low** for cinematic nano MVP |
| Aerial VLA papers (AutoFly etc.) | Future nav | Research |
| LeRobot / OXE data culture | Training discipline | Medium for any IL policy |
| AI HAT / Hailo | Unlock vision FPS | Medium (dev ladder) |
| World models / Cosmos | Synthetic data | Medium offline |
| MIT CfC drone OOD | Adaptive visual nav | Medium advisory policy |

**Meta-lesson:** The 2025–26 embodied boom is **real but manipulation- and humanoid-heavy**. For a **creator nano drone**, most of that boom is **transferable patterns**, not drop-in product modules.

---

## 6. What changes vs our previous conclusions?

### 6.1 Still solid (re-validated open-ended)

| Prior conclusion | Status |
| --- | --- |
| Deterministic arbiter + PX4 safety floor | **Confirmed** — production autonomy pattern |
| Do not put LLM/VLA on motor loop | **Confirmed** |
| Detector + tracker continuous; language episodic | **Confirmed** |
| ToF + speed governor for near obstacles | **Confirmed** |
| No VO on gimbal feed | **Confirmed** |
| Text NL prototype → buds voice product | **Confirmed** by DJI product design |
| Modular edge (detect / track / control) beats mono VLA on small compute | **Confirmed** by edge modular literature + market |
| Weight/endurance honesty (300 g prototype ≠ nano claim) | **Confirmed** |

### 6.2 Softened or re-ranked (important)

| Prior emphasis | Open-ended update |
| --- | --- |
| **CfC LNN as cinematic core** | Downgrade to **one of several** motion policies. Elevate **shot templates + trajectory optimization + gimbal framing costs**. Ship cinematic without waiting on perfect LNN. |
| **LFM as center of product identity** | Reposition as **differentiation layer**, not existence condition. Ship track+presets first if schedule forces; add NL when reliable. |
| **LingBot / foundation depth as key unlock** | Keep for production glass; **don’t gate outdoor demos** on it. |
| **UWB / GarudaPin late** | **Raise priority** for reliability of “follow me” (especially weddings/trees/crowds). Vision+UWB fusion may beat “better YOLO”. |
| **Full VLA / aerial VLN interest** | Stay research track; **do not pull P1 engineering**. |
| **World state bus** | Still good engineering; keep **thin** (tracks, ToF, EKF, mode) — not SLAM map. |
| **BoT-SORT** | Still optional upgrade; single-subject follow often doesn’t need full BoT. |
| **YOLO26 vs PicoDet** | Still a **bench + license** issue; neither defines product success. |

### 6.3 Newly elevated leads (under-weighted before)

1. **Cinematography trajectory optimization** (view angle, subject scale, occlusion, gimbal limits) — G1 core.  
2. **Preset shot library quality** as UX equal to NL.  
3. **UWB / phone beacon fusion** for track reliability.  
4. **Diffusion / generative trajectory from text** as alternate NL→motion path (research-competitive with tool-calling LFM).  
5. **Independent gimbal planner** (not only velocity policy side-effect).  
6. **Creator success metrics** (usable clip rate, re-acquire rate, crash rate) over model benchmark scores.

### 6.4 Explicit de-bias list (things we may have overfit)

| Possible bias from prior chat | Corrective |
| --- | --- |
| “Liquid stack because edge benchmarks” | True for NL; false that it solves tracking/obstacles |
| “Everything is embodied AI 2026” | Creator drones solved largely with classical autonomy + templates |
| “More foundation models = more aha” | Aha = **reliable follow + framing**; language is sugar if follow fails |
| “Master guide VLA future = now” | Future R&D track; not MVP |
| “SLAM because robots” | Outdoor follow doesn’t need it |
| “CfC because liquid story” | Story-aligned, not uniquely required |

---

## 7. Goal-convergent architecture (stack-agnostic)

```text
                    CREATOR INTENT
           (app chips | finite phrases | free NL | voice)
                              │
                    INTENT → SHOT REQUEST
                   (mode, framing, duration)
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
   SUBJECT STATE        WORLD / SAFETY         SHOT EXECUTOR
   vision track         ToF, EKF2, batt        templates and/or
   (+ optional UWB)     temp, geofence         trajectory optimizer
         │                    │                (+ optional IL policy)
         └────────► SUPERVISOR / ARBITER ◄─────┘
                              │
                    velocity + gimbal cmds
                              │
                           FC (PX4)
```

**Minimum lovable product (MLP)** that hits G1–G3 without any foundation model:

- Detect + track subject  
- Follow / orbit / hover / land presets  
- ToF speed cap + PX4 failsafes  
- Gimbal subject hold  
- App UX chips  

**Differentiation stack** (India / aha):

- Offline NL → same shot requests  
- Optional VL disambiguation  
- Optional UWB re-acquire  
- Better cinematic optimizer than presets  
- Legal retail + support  

---

## 8. Does anything “invalidate” docs 01–07 / 12?

| Area | Invalidate? | Action |
| --- | --- | --- |
| Rebuild safety-first software (doc 12) | **No** | Proceed |
| Flight Arbiter | **No** | Proceed |
| LFM as only brain | **Partially** | Treat as **optional Phase-1b**, not Phase-1a hard dependency |
| CfC as must-train for track mode | **Partially** | Allow **template follow** without LNN; LNN improves feel later |
| Reject VLA on motors | **No** | Confirmed |
| UWB late | **Yes, soften** | Promote wearable ranging in Phase 2 plan (or parallel HW track) |
| Cinematic = LNN | **Yes, reframe** | Cinematic = planner + gimbal + track quality |
| Embodied catalog (07) | **No** | Keep as inventory; use goal grades above when picking |

---

## 9. Recommended priority order (open-ended, goal-sorted)

| Rank | Work | Goals |
| --- | --- | --- |
| 1 | Safe OFFBOARD + failsafes + arbiter | G3 |
| 2 | Solid single-subject track + gimbal hold | G1, G2 |
| 3 | Shot presets that look good (orbit/follow/wide) | G1, G5 |
| 4 | ToF envelope + speed governor | G3 |
| 5 | App UX (chips first) | G5, G2 |
| 6 | Trajectory/framing optimizer (classical) | G1 |
| 7 | Finite phrase → shot request | G5 |
| 8 | Needle/LFM free NL | G5 wedge |
| 9 | UWB/phone beacon fusion | G2 reliability |
| 10 | VL-450M episodic eye | G5 polish |
| 11 | IL policy (CfC or other) for smoother feel | G1 polish |
| 12 | NPU depth (LingBot class) | G3 indoor/glass |
| 13 | Production PCB nano | G4, G7 |
| ∞ | Full aerial VLA / world-model closed loop | Research only |

This order **diverges** from “LFM + CfC first” if those block 2–4.

---

## 10. Bottom line

**What doesn’t change:** Failsafe modular autonomy; vision tracking; ToF; PX4; no end-to-end VLA on motors; honest mass/endurance; India GTM.

**What does change:**  
The product’s center of gravity is **cinematic subject tracking + shot execution + safety**, not a foundation-model stack. Liquid/Robbyant/Molmo/Robostral remain **useful plugins** for language, depth, and research—not the definition of the vehicle.

**Success metric to adopt:**  
*“% of battery-limited outdoor sessions that produce a postable follow clip with zero RC intervention (safety pilot hands-off except kill).”*  
Optimize that number. Model names are secondary.

---

## 11. Sources (open pass)

- Market: DJI Neo/Neo2, HoverAir, Skydio product patterns; India IZI positioning  
- Cine research: CMU drone filming; gimbal-decoupled trajectory planning; DiffusionCinema (arXiv 2601.17412); ACDC agentic cinematography (arXiv 2509.16176); aesthetic multi-ROI UAV planning  
- Sensing: UWB RTLS for drones; ToF multi-zone class; mono depth foundations  
- Autonomy practice: PX4 OFFBOARD community; edge modular VLA reports; Skydio vision-first philosophy  
- Embodied wave: as cataloged in `07_*` but re-scored here by goals  
- Prior internal: `garudaone-architecture/*`, `future-phases/01–07`
