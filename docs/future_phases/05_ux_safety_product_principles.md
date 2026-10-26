# UX, Safety & Product Principles (Production-First)

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
>
> - Local voice transport is integrated; the exact STT bundle still requires target-Pi qualification.
> - Land/RTL mode transfer requires PX4 ACK and heartbeat confirmation; physical behavior remains unqualified.
> - The flight profile instantiates C10 and requires an inbound checksummed status reply; physical attitude feedback and motion limits remain unvalidated.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.

> [!NOTE]
> This file is a roadmap or future-phase proposal. It does not describe the current deployed system. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).

**Date:** 2026-07-13  
**Audience:** Product + software + flight ops.

This document freezes the **experience bar** and **safety non-negotiables** so landscape FOMO (new VLAs every week) cannot wreck the product.

---

## 1. The aha moments we are buying

Ranked by product value:

1. **Zero pilot skill** — natural language (later voice) produces a usable cinematic clip.  
2. **Subject-locked framing** during obstacle flow (gimbal counter-rotation).  
3. **Trust** — user feels the drone is careful (stops, arcs, lands when sick).  
4. **Instant understanding** — “Understood: orbit left, stay wide” before motion.  
5. **Indoor confidence** — glass/doorways don’t mean crash.  
6. **Personal style** — “it films like *my* operator” (Phase 3).  
7. **Legal peace of mind** in India (warranty, import legality).

If a new model does not improve 1–4, it is R&D, not a roadmap commit.

---

## 2. Interaction principles

### 2.1 Commands

- **Prototype:** text NL over authenticated Wi-Fi.  
- **Product:** BT buds → phone STT → same tool schema (capture is the phone’s problem).  
- **Always:** structured tools under the hood (`track`, `orbit`, `hover`, `land`, `set_framing`, `rtl`).  
- **Never:** free-form “do whatever” without Arbiter validation.

### 2.2 Feedback loop (UX latency)

| Step | Target |
| --- | --- |
| Echo “understood” | &lt;100 ms after parse start (or immediately on Needle hit) |
| First motion (complex) | &lt;1.0 s typical |
| Continuous track update | 25 Hz feel (smooth) |
| Failsafe voice/app alert | &lt;500 ms after detect |

### 2.3 Framing language

Ship a **small controlled vocabulary** that maps cleanly to tools:

- Distance: close / medium / wide / hero  
- Angle: eye / high / low / side / orbit  
- Motion: follow / lead / static / reveal / arc left|right  

LFM may accept freer language; tools stay discrete for reliability (GBNF).

### 2.4 Pointing (Phase 2+)

From Robostral-class UX: user taps a point in the live view or says “go to that doorway.”  
Policy proposes image-space goal → geometry → Arbiter-limited velocity.  
**Always** subject to ToF/depth envelope.

---

## 3. Safety principles (non-negotiable)

### 3.1 Authority hierarchy

```text
Human RC / kill  >  PX4 failsafes  >  Flight Arbiter  >  any ML proposal
```

ML may **suggest**. Only Arbiter **grants**. Only PX4 **actuates motors** in RT.

### 3.2 Fail closed

| Failure | Behavior |
| --- | --- |
| AI process crash | OFFBOARD timeout → Land/RTL |
| Insane velocity | Clamp + log + hold |
| Target lost | Hover → search → RTL (timers fixed) |
| Thermal | Drop FPS → defer LFM → land |
| Battery | Land at defined V/cell under load |
| Gimbal loss | Freeze gimbal; disable counter-rot manoeuvres |
| Wi-Fi loss | Hold mode; no panic |
| Depth/ToF blind | Lower v_max |

### 3.3 Arming

- **RC-primary arm/takeoff** for all field ops until product certification says otherwise.  
- No Wi-Fi arm.  
- Stream setpoints **before** OFFBOARD engage.  
- Preflight checklist FDR-logged.

### 3.4 Speed as a safety property

`v_max = f(sensor confidence, mode, geofence, battery)`  
Not overridable by LFM/LNN/VLA.

### 3.5 Transparency

- Every mode change logs reason code (FDR).  
- App shows mode: HOVER / TRACK / SEARCH / LANDING.  
- After incidents, support can reconstruct from FDR (privacy policy required).

---

## 4. Reliability engineering as product quality

Borrow from industrial robotics (Figure-class ops lesson: demos ≠ 10-hour shifts):

| Practice | Product meaning |
| --- | --- |
| Scenario harness | “Does it still work after 100 weird cases?” |
| Soak tests (G3) | “Does it cook itself in 10 min?” |
| Fault injection (G8) | “Does bad AI get ignored?” |
| Canary OTA | “Does a model update brick the fleet?” |
| Signed models | “Can someone flash malware GGUF?” |

**Reliability is the UX.** A magical orbit that crashes once destroys trust forever.

---

## 5. Competitive UX positioning (India)

| Competitor | They win on | We win on |
| --- | --- | --- |
| DJI Neo 2 (grey) | Polish, 4K, voice, sensing | **Legal channel**, support, offline agent flexibility |
| IZI Mini X class | Price, legal 4K | **Autonomy + NL experience** |
| HoverAir-class | Simple auto modes | **Open-vocabulary cinematic intent** |

Marketing must never claim “only voice drone” (false since Neo). Claim: **offline conversational cinematographer that is legal to own and service in India.**

---

## 6. Privacy & data

- Flight logs may contain faces / locations — **local-first**, opt-in cloud.  
- Training uploads: explicit consent, strip audio if any.  
- No continuous cloud video for product claims of offline.  
- Enterprise/wedding modes: wipe SD + FDR on request.

---

## 7. Progressive disclosure of AI

Users should not configure “which VLA.” Modes:

| User mode | What runs |
| --- | --- |
| **Simple** | Track + follow templates |
| **Director** | Full NL + framing tools |
| **Pro** | Pointing, style profiles, manual RC blend |
| **Dev** | Feature flags, model benches (hidden) |

Feature flags for LingBot-Depth, Navigate-distill, VLM eye stay off until gates green.

---

## 8. Definition of delight (acceptance tests for UX)

Ship a feature only if **≥8/10** creators in a hallway test say:

- “I would post this clip,” and  
- “I felt safe,” and  
- “I didn’t need a pilot license to try.”

If only engineers are impressed, it is not product-ready.

---

## 9. Anti-patterns

1. Shipping a heavier HAT forever because demos look better on LinkedIn.  
2. Letting LFM invent new flight modes at runtime.  
3. Voice that only works on a quiet desk.  
4. “Sub-250 g” marketing on a 300 g prototype.  
5. Chasing every Robbyant/AI2/Mistral release into the critical path.  
6. Disabling failsafes “just for the shoot.”

---

## 10. One-page product contract

> GarudaOne is a **failsafe-first**, **offline-capable** cinematic drone that turns **natural language into framed motion**.  
> Intelligence is **layered and replaceable**; safety is **not**.  
> We will use any edge AI (Liquid, Robbyant, HAT, future distillations of Navigate/VLA) that **improves creator outcomes inside the mass and power envelope**.  
> We will not ship brains that own the motors.

This contract binds Phase 1 rebuild and all future-phases work.
