# Investor / First Prototype Definition

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
>
> - Local voice transport is integrated; the exact STT bundle still requires target-Pi qualification.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - Land/RTL mode transfer requires PX4 ACK and heartbeat confirmation; physical behavior remains unqualified.
> - The flight profile instantiates C10 and requires an inbound checksummed status reply; physical attitude feedback and motion limits remain unvalidated.
> - Production VIO/SLAM adapters are absent or deferred.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.

> [!NOTE]
> This file is a roadmap or future-phase proposal. It does not describe the current deployed system. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).

**Date:** 2026-07-14  
**Status:** Locked product-engineering contract for Phase 1  

---

## Are you right that P1 needs core AI + seamless experience?

**Yes.** For *this* company:

| If P1 is only… | Investor reads… |
| --- | --- |
| Follow drone + presets | “HoverAir/Neo clone, India angle maybe” |
| Chatbot on a grounded Pi | “AI theater” |
| **NL → filmed sky shot + failsafe + frame lock** | “Category: offline aerial director” |

You need **table stakes and aha in the same prototype.** Not sequential years.

---

## Category claim (honest)

- **Enter:** self-flying creator camera drones (real market).  
- **Create / own:** **offline conversational cinematic agent**, especially **India-legal** retail.  

Do not claim “no one has follow-me.” Claim **sky agent that takes director language and films, offline, legally supportable.**

---

## Must-show demo script (target ~4–6 min flight)

1. **Arm / takeoff** (RC-primary; safety pilot).  
2. Type or send: *“Follow me, stay wide.”*  
3. App shows **Understood: track + framing wide** immediately.  
4. Subject walks; drone follows; face/frame stable.  
5. Optional: *“Orbit left slowly.”* → smooth orbit.  
6. Pass near a soft obstacle / cone: **arc or stop** without losing subject (ToF).  
7. **Kill AI link / power companion:** PX4 lands or RTL safely.  
8. Cut reel: best 20–40 s as **hero clip** for deck.

---

## In / out of first prototype

### IN (required)

- Offline **Needle + LFM2.5-230M + GBNF** tools  
- **Flight Arbiter** + clamps + mode FSM  
- Detect + track + **25 Hz** path feel  
- Gimbal subject hold (+ counter-rotate if HW allows)  
- Shot tools: follow_wide, orbit, hover, land, rtl  
- ToF + speed governor  
- PX4 failsafe proof  
- Seamless UX: one intent path (chips and free text hit same tools)  
- Honest mass/endurance messaging  

### OUT (not required for first raise reel)

- Production nano mass claim  
- Full voice STT onboard (moved to GarudaPin)  
- LingBot-Depth production path  
- Always-on VL-450M  
- UWB pin (nice if early)  
- Aerial VLA / full SLAM  
- Multi-language product polish  

---

## GarudaPin wearable voice interface (planned prototype)

GarudaPin is an in-scope prototype workstream that is not gated on physical drone qualification.

**Selected hardware:** WaveShare ESP32-S3-Touch-AMOLED-2.16 dev board (dual PDM mics, ES8311 codec, BLE 5, AXP2101 PMU with LiPo header, QMI8658 6-axis IMU, 2.16" AMOLED touch display for diagnostics).

**Architecture:**

- GarudaPin captures 16 kHz 16-bit PCM audio from the dual PDM mics via the ES8311 codec and streams it over BLE 5 GATT to the user's smartphone.
- The smartphone companion app runs Indic Whisper (small quantized) with `--task translate` for single-pass Indic-to-English speech-to-text, then parses intent and forwards structured JSON to the drone.
- The drone receives JSON commands over 5.8 GHz Wi-Fi from the phone; the arbiter validates them the same way it validates WebSocket commands.
- **Spectrum split:** 2.4 GHz is reserved exclusively for GarudaPin BLE audio streaming. Phone-to-drone commands, telemetry, and FPV video all use 5.8 GHz Wi-Fi.
- **Emergency button (GPIO18):** bypasses the phone entirely. Short press = RTL, long press (≥3s) = LAND, double press = HOVER. This path is a deterministic BLE GATT command that reaches the Pi 5 arbiter in <10 ms, independent of STT, phone link, or app state.

GarudaPin firmware (ESP-IDF) and the phone companion app are not yet implemented. This is architectural intent only.

**Current non-claims:** GarudaPin does not currently claim firmware implementation, BLE GATT service, on-device Whisper inference, emergency-button arbiter integration, battery endurance, BLE range, or acoustic SNR qualification.

**Investor framing:** GarudaPin is the voice layer that makes GarudaOne feel like a personal agent, not a remote-controlled toy. The phone's existing CPU runs the STT — no extra compute on the pin, no weight penalty from an NPU, no thermal issue against skin.  

---

## Success metrics (not model leaderboards)

| Metric | Target for P1 exit |
| --- | --- |
| NL tool accuracy (held-out phrases) | ≥95% |
| Outdoor “postable follow” sessions (safety pilot hands-off except kill) | ≥7/10 scripted trials |
| Failsafe AI-kill | 10/10 |
| Time phrase → first motion (complex) | ≤1 s typical |
| Investor gut check | “I’d want one” / “I see the category” |

---

## Engineering order (do not reorder casually)

See `03_phase_roadmap_to_production.md` Phase 1 build sequence:  
foundations → hover/failsafe → track/gimbal → **good presets** → **NL core AI** → obstacle hero → smoother/CfC → reel.

Presets and NL share tools so the experience is **one brain**, not two products.

---

## Deck one-liner

> GarudaOne is the offline aerial director: say the shot, it films it, keeps you framed, respects the sky — legal where DJI isn’t, intelligent where local 4K remotes aren’t.
