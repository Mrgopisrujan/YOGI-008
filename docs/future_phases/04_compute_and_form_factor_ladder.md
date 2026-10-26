# Compute & Form-Factor Ladder

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated compute/form-factor proposal does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
>
> - Raspberry Pi 5 8GB remains the selected companion target; performance and thermal behavior are not yet qualified on the target aircraft.
> - Later HAT, SoM, and custom-PCB options remain roadmap candidates, not selected hardware.

**Date:** 2026-07-13  
**Rule:** Dev may be “whatever it takes” (AI HAT, extra grams). **Production** optimizes **grams + watts + rupees + thermal + failsafe isolation**.

---

## 1. Design principle

```text
Heavy brains are allowed on the workbench.
Only lean brains fly in the product.
Same software contracts from day 0 → no rewrite when SoC changes.
```

Isolate:

| Plane | Role | Technology |
| --- | --- | --- |
| **A** | Hard real-time flight | H7/H743-class MCU, PX4/NuttX |
| **B** | Continuous perception/control assist | NPU INT8 (+ light CPU) |
| **C** | Episodic language / VLM / planning | CPU or NPU burst, power-gated |

Never merge A with C on one unsafe process.

---

## 2. Ladder stages

### Stage D0 — Lab / Windows

| Item | Spec |
| --- | --- |
| Host | x86 laptop |
| Use | Unit tests, GBNF, arbiter, mock perception |
| Flight | SITL only |

### Stage D1 — Current prototype (architecture docs)

| Item | Spec |
| --- | --- |
| Companion | **RPi 5 8GB** + active cooler |
| FC | MicoAir H743 AIO |
| AI budget | CPU-only ~8–12 W under load |
| Mass impact | ~45 g Pi + ~26 g cooler + BEC |
| AUW | ~292–300 g |
| Models | PicoDet ncnn, LFM 230M, CfC, ToF |
| Optional | — |

**Role:** Prove experience core. **Not** sales nano.

### Stage D2 — AI HAT / accelerated prototype (“whatever it takes”)

| Item | Spec |
| --- | --- |
| Companion | Pi 5 **or CM5** + **Hailo-8 / Hailo-8L AI HAT** (or Coral — weaker) |
| Extra mass | ~20–40 g class (HAT + carrier; measure) |
| Extra power | ~1.5–3 W NPU typical under vision load |
| Unlocks | YOLO26/PicoDet high FPS; LingBot-Vision; experimental Depth; faster VLM pre/post |
| Still keep | Arbiter on CPU; PX4 on FC |

**When:** Phase 1 late / Phase 2 demos — when CPU thermal or FPS fails G3.

**Community evidence:** Modular VLA stacks on Pi 5 + Hailo-8L are proven for ground robots; we reuse the **partitioning**, not their ROS stacks.

### Stage D3 — Production-intent SoM (EVT)

Pick **one** primary after bake-off (power × mass × ISP × NPU SDK maturity):

| Option | Why consider | Risks |
| --- | --- | --- |
| **Rockchip RK3588S SoM** | Strong NPU ecosystem, Linux, cost | Power if not tuned; ISP integration |
| **Ambarella CV52S** | Drone-native, low W, camera pipeline | Closed toolchain, partner access |
| **Qualcomm RB / Flight-class** | ISP + AI + RF integration | Cost, availability, India supply |
| **Custom SIP** (MCU + NPU die) | Ultimate grams | CapEx, schedule |

**Target budgets (production intent):**

| Metric | Target |
| --- | --- |
| AI plane mass | **≤15–25 g** (SoM + tiny PMIC, no Pi cooler) |
| AI continuous power | **≤2–4 W** average; peaks managed |
| Peak TOPS usable | Enough for detect@15 + depth@2 + LFM burst |
| RAM | 4–8 GB |
| Storage | eMMC 32–64 GB |

### Stage D4 — Custom PCB nano (production)

| Item | Spec |
| --- | --- |
| Board | Single PCB: FC MCU + AI SoC + PMICs + RF + camera interfaces |
| Frame | Injection molded |
| Camera | Micro gimbal **or** fixed + EIS (product decision) |
| AUW | **≤249 g** with margin |
| Endurance | **≥15 min** measured (not EST-only) |
| Cost | BOM path to ₹8–10k @ 10k units (doc 00/03) |

**Software:** NPU runtimes (ncnn / ONNX / vendor) behind same Python/C++ interfaces as D1–D2.

---

## 3. Model placement by stage

| Model | D1 Pi CPU | D2 + HAT | D3/D4 NPU prod |
| --- | --- | --- | --- |
| PicoDet / person detector | ✅ duty-cycle | ✅ higher FPS | ✅ always |
| ByteTrack + LK | ✅ | ✅ | ✅ |
| LFM2.5-230M | ✅ burst | ✅ | ✅ or 350M/1.2B |
| Needle | ✅ | ✅ | ✅ |
| LFM-VL 450M | episodic only | better latency | ✅ episodic |
| LingBot-Depth | ❌ / rare | trial | ✅ 1–5 Hz |
| LingBot-Vision small | trial | ✅ | ✅ |
| Robostral-class 8B | ❌ | ❌ / offboard | distill or 1 Hz planner only |
| MolmoAct / π / full VLA | train only | train only | advisory research |
| CfC LNN | ✅ | ✅ | ✅ (or distilled policy) |
| World models | cloud | cloud | cloud |

---

## 4. Power & thermal discipline (all stages)

1. **Measure** package power with full stack — never ship EST-only claims.  
2. **Cap** CPU/NPU clocks for sustained flight (doc 10 style).  
3. **Priority under thermal pressure:**  
   - Keep: control loop, clamps, ToF governor, detect reduced FPS  
   - Defer: VLM, Depth, LFM  
   - Land if &gt; critical temp  
4. **Duct prop wash** across AI heatsink on every airframe.  
5. Log `temp`, `throttle`, `FPS`, `tok/s` every flight (FDR).

---

## 5. Weight recovery math (why D4 exists)

Approx removals from D1 → D4:

| Remove / replace | Grams (order of) |
| --- | --- |
| Pi 5 | −45 |
| Active cooler | −20–30 |
| Fat BEC | −10 |
| Skydroid 61 g → micro cam | −40–50 |
| Add: SoM + PMIC + tiny heatsink | +15–25 |
| **Net** | **~100 g recovered** → nano class becomes real |

AI HAT **increases** mass — use it to **learn**, not to **ship**.

---

## 6. Bake-off plan (Phase 2)

| ID | Comparison | Metrics |
| --- | --- | --- |
| **C1** | Pi5 CPU vs Pi5+Hailo detect | FPS, p99 latency, W, °C |
| **C2** | LingBot-Depth on HAT vs DA-V2-small | glass scenes, FPS, W |
| **C3** | LFM 230M vs 350M concurrent with detect | tok/s, W, tool accuracy |
| **C4** | SoM candidates (RK vs Ambarella quote) | TOPS/W, ISP, availability India, SDK pain |

Exit: written pick for EVT SoC with BOM estimate.

---

## 7. Failsafe hardware rules

1. **Independent** FC power path from AI plane brownouts (as much as PCB allows).  
2. **COM_OF_LOSS_T** always armed for OFFBOARD.  
3. Hardware kill / RC override never software-blocked.  
4. If AI HAT/NPU dies → degrade to hover/RTL via Arbiter, not free fall of logic.  
5. No single Python process is allowed to be “the only thing keeping the sky up.”

---

## 8. Recommendation summary

| Horizon | Compute |
| --- | --- |
| **Now** | Pi 5 CPU; finish software truth |
| **+NPU demos** | Pi 5 / CM5 + **Hailo AI HAT** when G3 fails or Depth needed |
| **EVT** | One SoM with real NPU; drop Pi |
| **MP** | Custom PCB nano; AI ≤ few watts continuous |

**Endgame is not the biggest HAT.** Endgame is **invisible intelligence in a 249 g aircraft that doesn’t kill people when the model is wrong.**
