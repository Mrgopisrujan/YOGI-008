# Pipeline Reality Check + LFM2.5-VL-450M Deep Dive

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
>
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - Land/RTL mode transfer requires PX4 ACK and heartbeat confirmation; physical behavior remains unqualified.
> - The flight profile instantiates C10 and requires an inbound checksummed status reply; physical attitude feedback and motion limits remain unvalidated.
> - Production VIO/SLAM adapters are absent or deferred.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.

> [!NOTE]
> This file is a roadmap or future-phase proposal. It does not describe the current deployed system. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).

**Date:** 2026-07-13 (second-pass research)  
**Sources:** Liquid HF + blog, arXiv (Aerial VLN / AutoFly / UAV-Track VLA / BoT-SORT), Hugging Face, Ultralytics docs, X, Reddit, GitHub, GarudaOne docs 01–12.

---

## 1. What we re-scanned (this pass)

| Channel | What was pulled |
| --- | --- |
| **Hugging Face** | `LiquidAI/LFM2.5-VL-450M` (+ GGUF/ONNX/MLX/Extract variants); ~63k monthly downloads; GGUF for llama.cpp |
| **Liquid blog** | LFM2.5-VL-450M Apr 2026: bbox, multilingual, function calling, edge latency |
| **arXiv** | AutoFly UAV VLA (2602.09657), Aerial VLN surveys (2604.*), UAV-Track VLA (2604.02241), BoT-SORT multi-UAV (2503.17237), world-model surveys (2605–2606) |
| **GitHub** | Ultralytics trackers, YOLOv12-BoT-SORT-ReID, Robbyant/lingbot-*, AI2 molmoact2 |
| **X** | Liquid VL-450M / Extract demos; structured JSON VL; edge narrative |
| **Reddit / community** | ML news on VL-450M; edge modular stacks; BoT-SORT as 2026 default for crowded MOT |

This complements [01_embodied_ai_landscape_2026.md](01_embodied_ai_landscape_2026.md); it focuses on **your assumed pipeline** vs **GarudaOne SSOT** vs **what LFM-VL actually changes**.

---

## 2. LFM2.5-VL-450M — does it change the architecture?

### 2.1 Facts (primary sources)

| Spec | Value |
| --- | --- |
| Full name | **LFM2.5-VL-450M** (not “LFM-2.5-450M-VL” — same model, Liquid’s ordering is `LFM2.5-VL-450M`) |
| Backbone | LFM2.5-350M + **SigLIP2 NaFlex ~86M** vision encoder |
| Params | ~450M total |
| Context | 32K |
| Native image | up to **512×512**; tiling for larger |
| New vs LFM2-VL-450M | **BBox prediction** (RefCOCO-M **81.28**), better IF (MM-IFEval **45**), multilingual vision, **function calling (text-only)** |
| Edge latency (vendor) | Jetson Orin, Q4_0, **512×512 &lt; ~250 ms** (~4 FPS full VLM); phones often **&lt;1 s** smaller res |
| Deploy formats | Transformers, vLLM, SGLang, **llama.cpp GGUF**, ONNX, MLX |
| HF notes | Strong for captioning/detection/grounding; **not** knowledge-heavy or fine OCR |
| Related | **LFM2.5-VL-450M-Extract** — structured JSON fields from images (~99% JSON validity claims in community posts) |

### 2.2 What it is good for on GarudaOne

| Use | Fit | Rate |
| --- | --- | --- |
| **Director’s Eye** (“what’s around me?”, framing tips, “guy in red”) | **Excellent** — designed for this | Episodic, on demand |
| **Open-vocab grounding** (bbox of “red shirt”) | **Good** — RefCOCO-class grounding | Episodic / re-acquire |
| **Disambiguation** when BoT-SORT ID confuses two people | **Good** | Burst |
| **Structured scene JSON** (Extract variant) for mission planner | **Good** | 0.5–2 Hz max if ever continuous |
| **Primary person tracker at 25 Hz** | **Bad** | Too slow / heavy vs PicoDet+tracker |
| **Obstacle metric depth / glass** | **Bad** | Use ToF + LingBot-Depth |
| **Tool routing for “land/stop”** | **Suboptimal** | Keep **Needle + LFM text 230M** (or VL tools only when image needed) |
| **Closed-loop velocity at 20 Hz** | **Reject** | Cannot own PX4 setpoints |

### 2.3 What it does *not* replace

- YOLO/PicoDet continuous detection  
- BoT-SORT / ByteTrack association  
- PX4 EKF2 (or any real SLAM/VIO for body pose)  
- ToF safety envelope  
- Flight Arbiter  
- CfC / trajectory smoother continuous control  

### 2.4 Architecture impact (honest)

**It upgrades Layer 1 (Director), not the whole stack.**

Before (docs 11/12): LFM **text** 230M for tools + optional VL eye EST 1–3 s on Pi CPU.  
After this pass:

| Platform | Expected VL-450M role |
| --- | --- |
| **Pi 5 CPU alone** | Still **episodic** (EST ~1–3 s/frame class under concurrency — must bench B4). Use sparingly. |
| **Pi 5 + AI HAT / Jetson-class / NPU SoM** | Becomes **practical** for 1–4 Hz scene queries and occasional grounding — still not the tracker. |
| **Production NPU** | Default “Director’s Eye” + optional open-vocab re-ID assist |

**Optional product idea (Phase 2):**  
Single **LFM2.5-VL-450M** for image-conditioned tools *when the command needs vision*; keep **Needle + LFM2.5-230M text** for pure language hot path (land/hover/follow).  
**Do not** collapse everything into one 450M VL for all commands — wastes power and latency on “stop”.

**Extract variant:** use for offline/on-ground “shot checklist from a still” or pre-flight shelf/scene JSON — not flight-critical.

---

## 3. Your assumed path vs original GarudaOne path

### 3.1 Your assumption

```text
Camera → YOLO → BoTSORT → SLAM → Sensor Fusion → World State
  → Mission Planner → LFM (only when needed) → Trajectory Planner → PX4
```

### 3.2 What architecture docs actually say (original SSOT)

```text
Camera → Detector (PicoDet/YOLO) → Track (ByteTrack-lite + flow)
       ↘ ToF grid
PX4 EKF2 (GPS+IMU+flow+baro) ──► pose/vel telemetry
       ↘
Subject bbox + depth + EKF → CfC LNN + smoother → velocity setpoints
Text/NL → Needle/LFM → ToolProposal → Flight Arbiter → mode/limits
                              ↓
                         PX4 OFFBOARD (safety floor)
```

**No full SLAM map**, no heavy “mission planner” ROS node, no world-model sim in the loop.  
**SVO/VO on gimbal was removed** (license + wrong frame).  
**LFM is not mid-pipeline between world state and trajectory** as a continuous stage — it is **event-driven tool generation**.

### 3.3 Side-by-side verdict

| Block in your chain | Verdict | Production-first recommendation |
| --- | --- | --- |
| **Camera** | Keep | Gimbal for film + optional fixed GS for nav |
| **YOLO** | Keep class, not brand | **PicoDet-S** production default; YOLO26n only if licensed + B1 wins |
| **BoT-SORT** | **Upgrade path yes** | Phase 1: ByteTrack-lite + LK (cheapest). Phase 2: **BoT-SORT** when occlusion/multi-person (CMC + appearance). Ultralytics: BoT-SORT better IDs, slower; ByteTrack for open scenes |
| **SLAM** | **Over-specified for Phase 1** | Use **PX4 EKF2** as pose source. Optional **VIO** (LEVIO/Basalt) on fixed cam for GPS-denied — not ORB-SLAM3 on companion as P0 |
| **Sensor Fusion** | Keep idea, rename | **World-state estimator**: EKF2 pose + ToF grid + tracklets + battery/thermal — not a second SLAM |
| **World State** | **Keep as explicit structure** | Lightweight struct/topic (see §4) — this is the good part of your idea |
| **Mission Planner** | Keep thin | Finite modes + shot templates (follow/orbit/hover), not full topological mission stack |
| **LFM only when needed** | **Correct** | Needle first; LFM text; **VL-450M only if image required** |
| **Trajectory Planner** | Split | Continuous: **CfC + jerk limit + clamps**. Episodic: simple geometric/pointing goals. Not EGO-Planner full until production NPU |
| **PX4** | Keep | Always terminal authority |

**Bottom line:** Your chain is a classic **robotics textbook / ROS autonomy** shape. It is **directionally right** for a rich product, but **too heavy and mis-ordered** if implemented naively for a cinematic nano/micro drone. GarudaOne’s original path is the **minimal production skeleton**. Your chain is the **Phase 2–4 expansion** of that skeleton — with SLAM demoted and LFM moved off the continuous path.

---

## 4. Recommended production pipeline (merged)

Three rates. **World State** is the bus. **LFM does not tick every frame.**

```text
                    ┌─────────────────────────────────────┐
  SENSORS           │         WORLD STATE (10–50 Hz)      │
  Camera 1080p25 ──►│  tracks[]  tof[]  pose  v_est       │
  ToF 8×8 @15 ─────►│  battery  temp  mode  target_id     │
  PX4 EKF2 ────────►│  gimbal_angles  link_ok  flags      │
  RC / app ────────►│                                     │
                    └──────────────┬──────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
  FAST REFLEX 20–25 Hz      ARBITER ~50–200 Hz         SLOW BRAIN event-driven
  detect 10–15 Hz           mode FSM                   Needle (ms)
  ByteTrack/BoT-SORT        speed governor             LFM2.5-230M text tools
  LK flow 25 Hz             watchdogs                  LFM2.5-VL-450M image tools
  CfC + smoother            clamps                     (Director’s Eye / grounding)
  → VelocityCmd             grants only                → ToolProposal only
         │                         │                         │
         └────────────► ARBITER ◄──┴─────────────────────────┘
                              │
                              ▼
                     PX4 OFFBOARD 20–50 Hz
                     (failsafes always live)
```

### 4.1 World State schema (minimal, versioned)

```yaml
# world_state v1 — FDR + planners consume this only
timestamp_us: int
pose: {x,y,z, yaw, frame: "NED"}      # from PX4 EKF2
vel: {vx,vy,vz, yaw_rate}
tracks:
  - id: int
    class: person
    bbox_norm: [x1,y1,x2,y2]           # image
    conf: float
    age_s: float
tof: {zones: [[d,...]], conf: [[c,...]], range_m: float}
gimbal: {yaw_deg, pitch_deg, ok: bool}
health: {batt_v, temp_c, link_ok, npu_ok}
mode: hover|track|search|land|rtl|...
target_id: int | null
limits: {v_max, yaw_rate_max}          # last arbiter grant
```

**Mission Planner** reads `world_state` + active `mission` (e.g. `follow_wide`) and emits **desired behavior**, not raw motor PWM.  
**LFM** only writes **ToolProposals** that change `mission` / params when the user speaks or when a rare auto-replan is enabled (default off).

### 4.2 Where YOLO + BoT-SORT fit

| Phase | Detector | Tracker |
| --- | --- | --- |
| **P1 ship** | PicoDet-S INT8 | ByteTrack-lite + sparse LK (25 Hz) |
| **P2** | B1 winner; person-only fine-tune | **BoT-SORT** if occlusions / multi-person (weddings) |
| **P3** | + open-vocab assist via **VL-450M** re-acquire | OSNet-class re-ID optional |

Industry (2025–26): **YOLO + BoT-SORT** is the default for **crowded MOT**; **ByteTrack** wins on pure throughput. Cinematography “follow me” is usually **single primary target** → ByteTrack-lite is enough until re-ID matters.

### 4.3 Where SLAM fits (and where it doesn’t)

| Need | Solution |
| --- | --- |
| Outdoor pose | **PX4 EKF2** (GPS + IMU + optical flow) |
| Indoor hold | Optical flow + baro + **optional VIO** fixed cam |
| Dense map for cinematography | Phase 3 **LingBot-Map** / offline map — not 20 Hz control |
| Obstacle “map” | **ToF + depth completion** local occupancy, not full SLAM |

Full SLAM in the hot path is a common overbuild that burns CPU/NPU without helping “follow me stay wide”.

---

## 5. Aerial VLA research (arXiv 2026) — relevance

| Paper class | Claim | GarudaOne take |
| --- | --- | --- |
| **AutoFly** end-to-end UAV VLA | Outdoor nav VLA; often **server-side** inference | Confirms VLA for drones is research-hot; **not** nano-onboard closed loop yet |
| **Aerial VLN surveys** | Language → 3D flight is open problem | Use as Phase 2–3 **planner** research, not Phase 1 |
| **UAV-Track VLA** | Tracking via VLA | Interesting; still secondary to classical tracker for latency |
| **Robostral Navigate** | Single-RGB language nav, pointing | **UX pattern** for “go there”; distill later |

None of these justify replacing PX4 + Arbiter with a single neural net for a consumer product in 2026.

---

## 6. Decision table: adopt changes now?

| Decision | Action |
| --- | --- |
| Rename mental model to **World State bus** | **Yes** — document in software rebuild |
| Implement full SLAM P1 | **No** |
| BoT-SORT P1 | **Optional**; ByteTrack-lite default |
| LFM2.5-VL-450M as Director’s Eye | **Yes** — feature-flagged; bench B4 |
| Replace PicoDet with VL-450M detect | **No** |
| Merge VL-450M into all tool calls | **No** — image only when needed |
| LFM only when needed | **Yes** — already correct |
| Trajectory = CfC continuous + episodic pointing | **Yes** |
| YOLO name in docs | Prefer **detector** abstraction; YOLO26 behind B1 |

---

## 7. Corrected “one-liner” pipelines

**Phase 1 (build this):**

```text
Camera → Detector → Tracker(+flow) → WorldState
ToF + EKF2 → WorldState
User text → Needle/LFM230 → Arbiter
WorldState → CfC+smooth → Arbiter → PX4
```

**Phase 2+ (your intuition, cleaned):**

```text
Camera → Detector → BoT-SORT → WorldState
ToF + (VIO?) + EKF2 → SensorFusion → WorldState
WorldState → Mission(mode templates)
User / rare event → LFM230 | VL450M → ToolProposal → Arbiter
WorldState + mission → Trajectory(CfC / pointing / later planner) → Arbiter → PX4
```

**Never:**

```text
... → LFM every tick → trajectory → motors
```

---

## 8. Immediate engineering notes

1. Add `WorldState` dataclass + FDR logging in rebuild (doc 12).  
2. Gate `LFM2.5-VL-450M` behind `features.vl_eye: false` until B4 on target HW.  
3. Prefer **GGUF** path consistent with text LFM (llama.cpp) for one runtime family.  
4. Bench VL-450M **with** detector running (G3-style concurrency), not isolated HF demos.  
5. If VL-450M grounding is good enough for re-acquire, still keep classical tracker for the 25 Hz path.

---

## 9. Sources (selected)

- <https://www.liquid.ai/blog/lfm2-5-vl-450m>  
- <https://huggingface.co/LiquidAI/LFM2.5-VL-450M>  
- <https://huggingface.co/LiquidAI/LFM2.5-VL-450M-GGUF>  
- Ultralytics ByteTrack vs BoT-SORT production notes  
- arXiv:2503.17237 (YOLOv12 + BoT-SORT multi-UAV)  
- arXiv:2602.09657 AutoFly; 2604.* Aerial VLN; 2604.02241 UAV-Track VLA  
- GarudaOne `garudaone-architecture/01,02,04,08,10,11,12`
