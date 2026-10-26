# Phase Roadmap — Prototype to Production

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
>
> - The active PX4 transport is pymavlink, not MAVSDK-Python.
> - Local voice transport is integrated; the exact STT bundle still requires target-Pi qualification.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - Land/RTL mode transfer requires PX4 ACK and heartbeat confirmation; physical behavior remains unqualified.
> - The flight profile instantiates C10 and requires an inbound checksummed status reply; physical attitude feedback and motion limits remain unvalidated.
> - Production VIO/SLAM adapters are absent or deferred.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.

> [!NOTE]
> This file is a roadmap or future-phase proposal. It does not describe the current deployed system. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).

**Date:** 2026-07-14 (rev: investor prototype = **core AI + seamless experience**)  
**North star:** Offline conversational **aerial director** — failsafe, small, India-legal — that creates a category (not me-too HoverAir/Neo).

**SSOT for Phase-0/1 software rebuild:** `garudaone-architecture/12_optimized_rebuild_plan.md`  
**Strategy / positioning:** `future-phases/08_*`, `09_investor_prototype_definition.md`

---

## Doctrine (locked)

1. **First prototype is not “classical only.”** It must show **core AI + seamless sky experience** for investors and early believers.  
2. **Table stakes + aha together.** Track/fly/safe without AI story = commodity. AI story without postable clip = science project.  
3. **Category creation:** enter the self-flying camera market; **own** the offline NL cinematic-agent wedge (esp. India-legal).  
4. **Failsafe never optional.** Arbiter + PX4 floor on day 0.  
5. **Production path from day 0:** licenses, FDR, model hashes, mass honesty (~300 g R&D ≠ nano claim).

---

## Timeline overview (indicative)

```text
Phase 0    Now–M1     Foundations (software skeleton, gates, official models)
Phase 1    M1–M5      ★ INVESTOR / CORE PROTOTYPE — AI + seamless experience
Phase 2    M5–M9      Intelligence depth (VL eye, NPU depth, UWB, voice path)
Phase 3    M9–M14     Creator intelligence (style, maps, Indic, polish)
Phase 4    M8–M20     Production hardware (parallel; nano PCB)
Phase 5    M18–M24    Manufacture, certify, ship
```

Months = effort bands, not calendar promises. **Failsafe gates do not slip.**

---

## Phase 0 — Foundations

**Goal:** Rebuild that can never fly on random weights or unclamped AI.

| Workstream | Deliverables | Exit |
| --- | --- | --- |
| Software | Doc 12: PR-0 → A3, L1; FSM; refuse toy LNN | G8 green |
| Models | Official LFM2.5-230M GGUF; ban ECE; license ledger | Hash pinned |
| PX4 | ≥1.16 + `micoair_h743-aio` (re-clone if needed) | SITL + board path |
| Contracts | WorldState v1, CfC meta schema, FDR jsonl | Frozen I/O |
| Intent schema | Tool set: hover, track, follow_wide, orbit, land, rtl, set_framing | GBNF draft |

**Not Phase 0:** outdoor investor reel (that is Phase 1 exit).

---

## Phase 1 — ★ Investor / Core Prototype  

### Core AI + seamless experience (non-negotiable)

**One-line success (investor demo):**

> Non-pilot **tells** the drone a shot in natural language (text); it **understands**, **films a postable follow/orbit**, **flows past a simple obstacle without losing the subject**, and **fails safe** if the AI computer dies — offline, on the R&D airframe.

### 1A — Vehicle table stakes (must land)

| Capability | Spec | Gate |
| --- | --- | --- |
| Fly OFFBOARD | MAVSDK 20 Hz velocity | Stable hover / path |
| Failsafe | Kill Pi / stop setpoints | G5 10/10 RTL/Land |
| Subject track | Detector + ByteTrack-lite + flow → 25 Hz | Hold ID outdoors |
| Gimbal hold | Subject in frame during maneuver | Visual lock |
| Obstacle envelope | ToF + speed governor | Controlled stop/arc @ ≤2–3 m/s |
| Shot presets | follow_wide, orbit_left/right, hover, land | Chip-equivalent tools |

### 1B — Core AI (must land — this is the aha)

| Capability | Spec | Gate |
| --- | --- | --- |
| **Offline NL brain** | Needle (fast) + **LFM2.5-230M** + **GBNF tools** | ≥95% tool accuracy on 100-phrase set (G4) |
| **Instant “understood”** | App/CLI echo of tool call before motion | Felt &lt;100 ms UX |
| **Intent → shot** | Free phrases map to same tools as presets | Same executor path |
| **Flight Arbiter** | All AI proposals validated; clamps; mode FSM | G8 fault injection |
| **Cinematic motion policy** | Jerk-limited smoother + **either** (a) strong preset trajectories **or** (b) CfC with real weights — **prefer both**: presets always; CfC when allowlisted | Postable clip quality |
| **Seamless flow demo** | One scripted obstacle + subject lock + gimbal counter-rotate if HW allows | **Hero investor shot** |

### 1C — Explicitly *not* required for first investor prototype

| Defer | Why |
| --- | --- |
| Full LingBot-Depth on-path | NPU/HAT; Phase 2 |
| LFM2.5-VL-450M always-on | Episodic Phase 2 polish (optional spike OK) |
| BT voice / STT | Text NL is enough for aha; voice product phase |
| UWB GarudaPin | Strong Phase 2 reliability; not gate for first reel |
| Full SLAM / aerial VLA | Not MVP |
| Nano &lt;249 g claim | R&D ~300 g; say so |
| Perfect multi-person BoT-SORT | Single subject OK |

### Hardware (Phase 1)

- FlyLens-class + MicoAir H743 + Pi 5 (AI HAT **optional** if G3 fails)  
- Skydroid (or equivalent) gimbal if counter-rotate is part of hero demo  
- Forward multi-zone ToF  
- **Register / operate as micro R&D** — do not market as nano

### Phase 1 exit checklist (all required)

- [ ] Outdoor video: NL command → postable follow (≥20–30 s usable)  
- [ ] Outdoor video: orbit or arc with subject framed  
- [ ] Obstacle flow or hard stop without face loss (at least once, controlled)  
- [ ] Failsafe: AI kill mid-hover → safe PX4 action (recorded)  
- [ ] Side-by-side: same phrase → same tool → motion (reliability)  
- [ ] One-pager: category = offline aerial director; mass/endurance honest  

**Exit ≠ production.** Exit = **fundable, believable prototype.**

---

## Phase 2 — Intelligence & reliability depth

**Goal:** Make the aha **robust** and expand the sky agent.

| Track | What | Exit signal |
| --- | --- | --- |
| 2A VL eye | LFM2.5-VL-450M episodic (“who’s in red?”, framing tip) | Useful on 50 queries |
| 2B Depth | LingBot-Depth or DA-small on HAT/NPU + ToF | Better glass/tight space |
| 2C UWB / phone beacon | Re-acquire when vision dies | Wedding/tree demo |
| 2D Pointing | Tap/say “go there” | Corridor/doorway |
| 2E Voice path | BT buds → phone → same tools | Field demo |
| 2F Trajectory optimizer | Framing costs + jerk + obstacles (classical) | Looks more “crew” than presets alone |
| 2G CfC/DAgger mature | Real pilot demos → allowlisted flight weights | Track mode default |
| 2H HIL harness | 100+ scenarios nightly | Regression wall |

---

## Phase 3 — Creator intelligence (moat expansion)

| Feature | Note |
| --- | --- |
| Shot style memory | Per-creator defaults |
| Scene suggestions | Pre-flight VL / light |
| Indic languages | Moonshine flavors etc. |
| GarudaPin productize | If 2C validated |
| Maps / locations | LingBot-Map selective |
| Gesture | Never safety-critical |

All remain **ToolProposal → Arbiter** only.

---

## Phase 4 — Production hardware

- Custom PCB / SoM; drop Pi mass  
- Target **&lt;249 g**, 15+ min, 4K path (IMX678-class)  
- Same software contracts; NPU for detect/depth/VL  
- DFM, EMI, thermal, BOM to scale cost  

---

## Phase 5 — Ship

- Compliance (class claims only if measured)  
- Safety case, factory flash/cal, signed OTA models  
- India GTM: legal + offline director vs grey Neo / dumb legal 4K  

---

## Parallel tracks

```text
        ┌─ Phase 0–1 software + flight demos ──► investor reel
Program ┼─ Data/FDR/DAgger factory (from first flights)
        └─ Phase 4 HW exploration (from mid Phase 1, serious in Phase 2)
```

---

## Priority order inside Phase 1 (build sequence)

```text
0. Foundations (arbiter, link, refuse toy, official LFM)
1. Hover + failsafe (G5)
2. Track + gimbal hold
3. Preset follow/orbit that look good          ← seamless without free NL yet
4. Needle + LFM + GBNF → same tools           ← CORE AI ON
5. ToF governor + one obstacle-flow hero shot
6. Smoother / optional CfC allowlist
7. Investor reel + one-pager
```

**Note:** Step 3 can start in parallel with 4, but **exit requires 4** — presets alone are not the Phase 1 investor bar for *this* company.

---

## Relationship to open-ended reassessment (doc 08)

Doc 08 correctly said: market winners ship track+presets; NL is differentiation.  
**For GarudaOne Phase 1:** differentiation is **mandatory**, not optional — because the raise and the category story depend on **core AI + seamless sky**, not “another follow drone.”

Presets without NL = incomplete Phase 1.  
NL without track/failsafe = incomplete Phase 1.  
**Both required.**

---

## Gates map (quick)

| Gate | Phase |
| --- | --- |
| G8 Arbiter, G4-T0 tools | 0→1 |
| G5 failsafe, track, NL tools, hero reel | **1 exit** |
| G3 concurrency soak, G6 glass | 1 late / 2 |
| VL, UWB, voice, depth NPU | 2 |
| Nano G1 weight, endurance product | 4–5 |
