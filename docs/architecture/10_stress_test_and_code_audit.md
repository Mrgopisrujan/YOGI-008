# GarudaOne: Engineering Stress Test — Budgets, Failure Modes, Code Audit (2026-07-07)

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - Needle 2 (45M, `cactus-needle==2.0.0`) replaced Needle 26M as the active constrained router.
> - The active PX4 transport is pymavlink, not MAVSDK-Python.
> - Local voice transport is integrated; the exact STT bundle still requires target-Pi qualification.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - Land/RTL mode transfer requires PX4 ACK and heartbeat confirmation; physical behavior remains unqualified.
> - The integration branch bridges authenticated WebSocket/UI requests to the live runtime arbiter; physical-flight qualification remains blocked.
> - The flight profile instantiates C10 and requires an inbound checksummed status reply; physical attitude feedback and motion limits remain unvalidated.
> - Production VIO/SLAM adapters are absent or deferred.


> [!IMPORTANT]
> This is an architecture/design record, not deployment evidence. Current verified implementation status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


This document exists to make the plan survive contact with physics. Every budget below must be re-measured on the actual airframe; EST values are engineering estimates to be replaced by bench data.

> **Repo note (2026-07-15 cleanup):** `garudaone-software/`, `TempPX4/`, `lingbot-vision/`, `lingbot-depth/`, `lingbot-map/`, and `models/lnn_weights.pt` referenced below have been removed from this repo (vendored clones + a scrapped v1 codebase's post-mortem docs) — kept only as historical decision record. Re-clone from upstream if you need to run a bench-off.

---

## 1. Weight budget (prototype, as currently specified)

| Component | Weight | Source |
|---|---|---|
| Flywoo FlyLens 85 frame kit | 27 g | vendor (25.5–27 g) |
| 4× QPT 1404 motors | ~38 g | EST (~9.5 g/motor, 1404 class) |
| Props + mounting hardware | ~6 g | EST |
| MicoAir H743 AIO 35A | ~10 g | vendor |
| Skydroid C10 Pro gimbal camera | 61 g | vendor |
| Raspberry Pi 5 (8GB) | ~45 g | vendor |
| RPi Active Cooler | ~26 g | EST 20–33 g |
| Foxeer M10Q GPS | ~9 g | vendor |
| MicoAir optical flow/ranging | ~2 g | vendor |
| ELRS receiver | ~1 g | vendor |
| 5 V/5 A BEC for Pi (was missing from BOM) | ~10 g | EST |
| ~~Mic + speaker + amp~~ | ~~8 g~~ → 0 g | **Descoped 2026-07-08** (text NL commands; voice = product phase) |
| LAVA 3S 450 mAh | ~42 g | EST 40–45 g |
| Wiring, mounts, standoffs | ~15 g | EST |
| **Total** | **~292 g** | **+43 g over the 249 g nano limit** |

**Decision required (owner: Arjun):**
- **Option A — Dev platform (recommended):** accept ~300 g, register once as a micro-class R&D platform on Digital Sky (UIN; no RPC needed for non-commercial R&D use), fly at a designated test site. Keeps every capability on one airframe. Nano compliance becomes a production gate, which the custom PCB + micro-gimbal design meets by removing the Pi 5 (45 g), cooler (26 g), BEC (10 g) and replacing the 61 g gimbal — that alone recovers ~100+ g.
- **Option B — Nano P0:** drop the gimbal camera for a fixed Pi Camera Module 3 (~4 g) + EIS. Loses the "gimbal counter-rotation" demo but gets under 249 g immediately.

## 2. Power & endurance budget

| Item | Value |
|---|---|
| Hover power @ ~300 g | ~34 W (EST, ~115 W/kg for 2" props) |
| Pi 5 under AI load | 8–12 W measured class; budget 10 W |
| Total draw | ~44 W |
| 3S 450 mAh energy | 5.0 Wh |
| **Endurance** | **~6.7 min theoretical → ~5 min usable (80% DoD, reserves)** |

Consequences: demo flights must be scripted around 4-minute windows; carry ≥4 charged packs per session. Production target (2S ~1100 mAh ≈ 8.1 Wh, ~3 W SoC, ~170 g AUW) supports 15–18 min EST — competitive with Neo 2 (19 min) only if weight discipline holds.

## 3. CPU & thermal budget (Pi 5, 4× Cortex-A76 @ 2.4 GHz stock)

| Workload | Cores | Duty | Notes |
|---|---|---|---|
| PicoDet-S ncnn 320×320 | 2 pinned | continuous | ~20–30 FPS at 2 threads (53.7 FPS needs all 4 cores + 2.9 GHz OC — not available in flight) |
| Control loop + MAVSDK + smoother + CfC LNN | 1 pinned | 20 Hz | CfC forward pass at 19–50 neurons is microseconds–milliseconds; negligible |
| Text command listener (WebSocket) | shared | idle | negligible; non-flight-critical |
| LFM2.5-230M (llama.cpp) | 1–2 | burst | 42 tok/s peak in isolation; expect ~25–35 tok/s concurrent (EST). Tool-call outputs are <30 tokens → <1 s per command |
| LFM2.5-VL-450M (Director's Eye) | 2 | on-demand | ~1–3 s/frame (EST); arbiter blocks maneuvers during a query only if user requested a framing check |
| Needle 26M router | shared | burst | ~50 ms-class |
| ~~Wake word / STT / TTS~~ | — | — | **Descoped from prototype 2026-07-08** → ~1 core of headroom recovered |

Rules: pin processes with `taskset`/cgroups; never let ncnn autospawn 4 threads; cap governor at 2.0–2.2 GHz to keep sustained package power <8 W. **Go/no-go gate G3 (below) measures all of this together.**

Thermal: an enclosed airframe at 40 °C ambient will throttle a 10–12 W Pi 5 even with the active cooler. Duct prop wash across the cooler; log `vcgencmd measure_temp` in every flight log.

## 4. Latency chain (text command → motion) — rev. 2026-07-08

| Stage | Budget |
|---|---|
| App/CLI → Wi-Fi → Pi | ~10–30 ms |
| Needle route (simple) | <10 ms |
| LFM parse (complex, GBNF) | 500–900 ms (~25 output tokens @ ~30 tok/s) |
| Arbiter validate + grant | <5 ms |
| Tool dispatch → first setpoint | ≤50 ms (one control tick) |
| **Total (complex command)** | **≈0.6–1.0 s from send to motion** — app shows "understood: <tool call>" echo immediately |

*(Voice chain deferred to product phase; when it returns via BT buds it adds STT ~100–300 ms on top.)*

Perception→control latency: frame capture (40 ms @ 25 fps) + detect (~35 ms) + LNN+smooth (<5 ms) + MAVLink (<5 ms) ≈ **~85 ms** — fine for 3–5 m/s flight; PX4's inner loops handle stabilization regardless.

## 5. Obstacle-sensing reality check (replaces the old SVO2 story)

Kinematics: stopping/arc-initiation distance at speed v with detect range R and system latency ~0.2 s must satisfy R > v·0.2 + v²/(2a), a ≈ 3 m/s².

| Speed | Required detect range | Prototype sensor that provides it |
|---|---|---|
| 1–3 m/s (indoor) | ≥2.1 m | ToF 8×8 @ 5 m ✅ (15 Hz) |
| 5 m/s | ≥5.2 m | ToF marginal; PicoDet-recognized obstacles (people/vehicles) via bbox scale ✅ open air only |
| 8–10 m/s | ≥12–18 m | **Nothing on the prototype.** Cap autonomous speed at 5 m/s; higher speeds only in open sky (subject-follow at altitude). Production: stereo/depth-completion (LingBot-Depth 2.0 on NPU) unlocks this. |

Speed governor is a hard rule in software: `v_max = f(active sensing range)`, never overridable by the LNN or the LFM.

## 6. Failure-mode analysis (top 10)

| # | Failure | Detection | Response |
|---|---|---|---|
| 1 | Pi 5 crash / power brownout | PX4 OFFBOARD setpoint timeout (`COM_OF_LOSS_T`) | PX4 failsafe → RTL/Land (configure `COM_OBL_RC_ACT`) |
| 2 | LNN weights missing/corrupt | Startup check (now enforced in code) | Refuse to enter track mode; hover only |
| 3 | LNN outputs insane velocity | Hard clamp (now enforced in code) + PX4 velocity limits | Clamped; log event |
| 4 | Target lost (occlusion/exit frame) | No bbox for >2 s | Hover; push app notification; after 10 s → slow yaw search; after 30 s → RTL |
| 5 | ToF blinded by sunlight (dToF in direct sun degrades) | Zone confidence flags | Governor drops v_max to detector-only envelope |
| 6 | Gimbal link (reverse-engineered) drops | Heartbeat on gimbal responses | Continue flight; freeze gimbal; disable flow-around maneuvers that rely on counter-rotation |
| 7 | GPS degraded (urban canyon) | EKF2 variance flags via MAVSDK telemetry | Switch to optical-flow position hold; reduce v_max to 2 m/s |
| 8 | Thermal throttle mid-flight | soc temp >80 °C | Drop detector to 10 FPS, defer LFM/VLM calls, push app warning, land if >85 °C |
| 9 | Battery sag under Pi + motor load | PX4 battery estimator | Land at 3.5 V/cell under load; never below 3.4 V |
| 10 | Command link (Wi-Fi) drops mid-flight | Link heartbeat | Nothing changes: arbiter holds last granted mode; all failsafes are PX4/arbiter-side. (Voice/mic risk removed from prototype scope 2026-07-08.) |

## 7. Go/no-go gates (each is a bench test with a number)

- **G1 Weight:** AUW on a scale ≤ the declared class limit for the chosen registration path.
- **G2 Endurance:** ≥4.5 min hover with full AI stack running, 80% DoD.
- **G3 Concurrency:** tracker pipeline ≥25 Hz output (detector duty-cycled) sustained 10 min while LFM parses a text command every 30 s + one VLM query, control loop at 20 Hz jitter <10 ms, package temp <80 °C at 35 °C ambient.
- **G4 Model provenance & parsing:** deployed GGUF hash matches official `LiquidAI/LFM2.5-230M-GGUF` release; tool-call accuracy ≥95% on a 100-text-command test set (Needle + LFM combined, GBNF on).
- **G5 Failsafe:** kill the Pi mid-hover → PX4 executes RTL/Land within `COM_OF_LOSS_T + 1 s`, 10/10 trials.
- **G6 Obstacle envelope:** 10/10 stops/arcs before a 5 m glass pane at 2 m/s using ToF only (no vision).
- **G7 Sim-to-real:** identical MAVSDK script produces qualitatively matching trajectories in Pegasus SITL and on the airframe (change connection string only).
- **G8 Arbiter:** every AI-proposed mode change passes through the Flight Arbiter (doc 11 §2); fault-injection tests (bad tool call, insane LNN output, stale sensor) 10/10 handled deterministically.
- **Bench-offs B1–B5** (detector, VIO branch, depth assist, VLM eye, TTS latency) are defined in doc 11 §5 and run on the same rig as G3.

## 8. Code audit (garudaone-software) — state vs. plan

| File | Finding | Severity | Status |
|---|---|---|---|
| `models/LFM2.5-230M-ECE.IQ4_XS.gguf` | Third-party fine-tune, not official Liquid model (see 08 N3) | 🔴 | `download_models.py` now pulls official repo; delete the ECE file |
| `control/lnn_flow.py` | Default weights path `../models/lnn_weights.pt` doesn't exist (`models/` has `lnn_weights_cloud.pt`); on failure it logged an error and **kept flying with random weights**; outputs unclamped | 🔴 | **Fixed:** `weights_loaded` flag + hard output clamp |
| `main.py` | No clamp on LNN output; track mode allowed without trained weights; LNN constructed with no explicit weights path | 🔴 | **Fixed:** clamps + track-mode guard |
| `main.py` | Detector is YOLOv8n (`yolov8n.pt`) — dev placeholder for x86; PicoDet-S/ncnn is the Pi target (as detector.py docstring says) | 🟡 | Acceptable for dev; port to ncnn before on-target work |
| `control/smoother.py` | EMA, not B-spline; docs claimed "guarantees continuous curvature." Yaw wrap-around not handled | 🟡 | Docs corrected; implement `scipy.splprep` or clamped jerk-limited filter before flight tests |
| `cognition/brain.py` | Uses hand-built ChatML prompt; should apply the model's own chat template (llama.cpp `--jinja`/`create_chat_completion`) to avoid template drift; `n_ctx=2048` (docs said 32K — fine, but make docs match) | 🟡 | Documented; low-risk |
| `cognition/voice.py` | Mock loop only (no PyAudio/openWakeWord yet) — fires "follow me" every 10 s; must never run against a real armed drone | 🟠 | Documented; gate behind `--sim` flag before real integration |
| `main.py` | Voice callback thread mutates asyncio-loop state directly; use `loop.call_soon_threadsafe` for mode changes; queue drain race in producer is benign but ugly | 🟢 | Documented |
| `main.py` | No app-level watchdogs (target-lost, geofence, battery) — relies wholly on PX4 | 🟠 | Add per §6 table |
| `requirements.txt` | Missing torch/ncps/ultralytics/llama-cpp-python/scipy | 🟢 | **Fixed** |
| `tests/` | Edge-case tests pass (pytest lastfailed empty). No tests for failsafe paths | 🟡 | Add tests for §6 items 2–4 |
| `modal_*.py` | Cloud LFM server also pulls the ECE fine-tune URL | 🔴 | Update to official model (same fix as download script) |

## 9. What was right (credit where due)

The 3-layer separation (LFM director / fast perception-control / PX4 hard-real-time safety floor) is sound and matches how serious autonomy stacks are built. PX4-as-safety-net over OFFBOARD is exactly correct for a startup: the certified-grade failsafe logic is free. Component choices LFM2.5 + Needle + PicoDet + CfC are all real, current (June 2026), license-viable (Needle MIT; ncps/PicoDet Apache-2.0/BSD; LFM2.5 under Liquid's LFM Open License v1.0 — free commercial use below US$10M annual revenue, paid agreement above; see doc 13), and the quoted headline numbers were accurate — they were just quoted without their operating conditions. The gimbal counter-rotation insight for cinematic obstacle flow is a genuine differentiator and survives this audit intact.
