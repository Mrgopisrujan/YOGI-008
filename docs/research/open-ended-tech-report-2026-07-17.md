# GarudaOne Open-Ended Research Report — July 17, 2026

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - Needle 2 (45M, `cactus-needle==2.0.0`) replaced Needle 26M as the active constrained router.
> - The active PX4 transport is pymavlink, not MAVSDK-Python.
> - The selected flight profile uses one forward VL53L5CX at 8x8/15Hz; three-sensor/VL53L8CX designs are not active.
> - Production VIO/SLAM adapters are absent or deferred.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!NOTE]
> This is a dated research snapshot. Model choices, estimates, and recommendations are not implementation claims. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


## Context
Decision: Drop LFM2.5-230M, use LFM2.5-VL-450M for both text tool-calling AND episodic vision.
Research sources: 2 subagents (broad tech stack + URL analysis), 6 X Searches, 4 web searches.

---

## 1. LFM2.5-VL-450M Fine-Tuning — YES, and Liquid gives you the exact toolchain

### The official path: leap-finetune
- **`github.com/Liquid4All/leap-finetune`** — Liquid's official training stack
- Supports VLM SFT, DPO, GRPO, LoRA, full fine-tuning, GGUF export for edge
- **Official VLM fine-tune example exists**: `docs.liquid.ai/examples/customize-models/satellite-vlm`
  - Fine-tunes LFM2.5-VL-450M on satellite imagery (VQA + visual grounding + captioning)
  - **This is our template.** Swap satellite images for drone camera frames, swap VQA for our 5-tool schema
- TRL and Unsloth also supported

### Process for our 5-tool drone schema
1. Train in cloud (Modal), deploy on edge (Pi 5). LoRA on CPU is NOT practical for training
2. 500-5,000 examples: (NL command, camera frame, tool-call JSON) triples
3. Use LoRA first pass. Train on LFM's native Pythonic tool-call format (NOT OpenAI-style JSON)
4. Export to GGUF via leap-finetune. Deploy Q8_0 on Pi 5
5. Budget: ~$5-10 Modal GPU per iteration. Colab free tier also works for 450M class

### Also: LFM2.5-VL-450M-Extract variant
- Specifically tuned for structured JSON extraction with ~99% JSON validity
- Even better for G4 gate than base 450M VL
- **Test both variants** — -Extract might hit 95% out of the box with GBNF

---

## 2. ML Community Optimizations — INT8 > INT4 at this scale

### Critical finding from Cactus Compute
At 350M-450M params, **INT4 causes measurable quality drops vs INT8**. Smaller models are more sensitive to quantization.

| Optimization | Finding | Impact |
|---|---|---|
| **INT8 vs INT4** | Q4 causes 2-4 point MMLU drops vs Q8 at 350M scale | **Use Q8_0, not Q4_0, for 450M VL** |
| **I8MM / SMMLA** | ARMv8.2-a has 2×8 by 8×2 INT8 matmul in one instruction. Pi 5 A76 supports this | Compile with `-march=armv8.2-a+dotprod+i8mm` |
| **Single-core decode** | Decode is memory-bandwidth-bound, not FLOPS-bound. Adding cores adds sync overhead | Run decode on 1-2 cores, leave others for PicoDet + MAVSDK |
| **mmap zero-copy** | Maps model file directly. ~300MB RAM for 450M | Use `--mlock` judiciously, NVMe SSD over microSD |
| **KV cache quant** | `--cache-type-k q4_0` has little quality impact, big memory win | Enable for 8GB Pi 5 |
| **Prefix caching** | `--prompt-cache` eliminates reprocessing ~500-token system prompt | Fixed tool schema = same prefix every call |
| **Speculative decoding** | Pair 350M as draft for 450M target. 20-50% speedup | Same model family = compatible tokenization |
| **Build from source** | 10-20% faster than Ollama on Pi, ~35% faster prompt processing | Always build llama.cpp from source on Pi 5 |
| **Active cooling** | Sustained inference thermal-throttles Pi 5 | Mandatory active cooler |

### Verdict
**Q8_0 + single-core decode + KV cache quant + prefix caching + build from source.** Test speculative decoding with 350M draft model.

---

## 3. Antidoom / FTPO — DIRECTLY RELEVANT, run as post-fine-tune cleanup

### What it is
- Open-sourced July 7, 2026. Fixes "doom loops" in reasoning models
- FTPO: trains only the single trailing token that starts a loop
- Results: LFM2.5-2.6B doom-loop rate 10.2% → 1.4%. Eval scores went UP
- github.com/Liquid4All/antidoom

### Why it matters for GarudaOne
LFM2.5-VL-450M does tool-calling in a loop (arbiter calls it repeatedly). A doom loop = stuck behavior, wasted compute, dangerous on a drone.

### Two-tier defense
**Tier 1 (do now, ~20 lines):** Inference-time loop detector in `cognition/lfm_brain.py`
- Detect span repeating ≥4 times, ≥60 chars
- Abort generation, return safe fallback ToolProposal (hover)
- Log to FDR

**Tier 2 (after fine-tuning):** Run Antidoom FTPO pipeline as cleanup pass
- Generate drone-specific loop examples + use LiquidAI/antidoom-mix-v1.0
- Train LoRA on Modal, stop at `chosen_win=0.35`
- **Key insight: run at temp=0.1 after Antidoom, not temp=0.7**

### Caveats
- Over-training creates NEW loop tokens. Early stopping mandatory
- Can break tool invocation patterns — test tool-calling eval after applying
- Multiple rounds may be needed

---

## 4. Edge VLM Alternatives — LFM2.5-VL-450M wins, nothing else close

| Model | Params | Tool Calling | Vision | Pi 5 fit | Verdict |
|---|---|---|---|---|---|
| **LFM2.5-VL-450M** | 450M | ✅ BFCLv4 21.08, native | ✅ RefCOCO-M 81.28 | ✅ 307MB Q4 | **BEST** |
| **LFM2.5-VL-450M-Extract** | 450M | ✅ ~99% JSON validity | ✅ structured extraction | ✅ same | **Best for G4 gate** |
| SmolVLM2-500M | 500M | ❌ MM-IFEval 11.27 (terrible) | ✅ | ✅ | Eliminated — can't follow instructions |
| Qwen2.5-VL-0.5B | 500M | ❌ text-only, VL starts at 3B | — | — | No 0.5B VL variant exists |
| MiniCPM-V 4.6 | 1.3B | ✅ via Qwen backbone | ✅ strong OCR | ⚠️ 3x larger | B2 bench candidate if need OCR |
| OmniVision-968M | 968M | via Qwen backbone | ✅ 9x token reduction | ⚠️ 2x params | Innovative but no tool-calling benchmarks |
| Moondream 3 | 2B active | ❌ not a tool-caller | ✅ SOTA | ❌ too slow | Too large for Pi 5 |

### Why LFM2.5-VL-450M wins
1. **Only sub-1B VLM with native function calling** (SmolVLM2 MM-IFEval 11.27 = useless for tool calls)
2. **Hybrid SSM architecture** = fast on CPU (avoids quadratic attention)
3. **Liquid's fine-tuning stack** (leap-finetune) is purpose-built for it
4. **GGUF + llama.cpp day-one support** with official Q4_0 release
5. **Antidoom compatibility** — same model family Liquid tested FTPO on

---

## 5. MAVLink/MAVSDK — Keep MAVSDK-Python, use pymavlink for hot path

| Option | Role | When to use |
|---|---|---|
| **MAVSDK-Python** | High-level: connect, arm, mode switch, mission | Keep for state management |
| **pymavlink** | Low-level: raw SET_POSITION_TARGET_LOCAL_NED at 20Hz | **Use for OFFBOARD setpoint hot path** |
| MAVSDK-C++ | Same API, no GIL | Migration path if Python timing is bottleneck |
| MAVSDK-Rust | Reactive, async | "Proof of concept" status — skip |

### Hybrid approach
MAVSDK-Python for connection/arming/mode. **pymavlink for the real-time 20Hz setpoint stream.** Common PX4 companion pattern. If jitter >5ms on MAVSDK-Python, switch the hot path.

---

## 6. Simulation — Genesis replaces Isaac Sim for data gen

| Simulator | GPU? | Drone Support | Speed | Verdict |
|---|---|---|---|---|
| **Genesis** | **No — CPU** | Add quadrotor dynamics | **80x faster** | **Best for data gen on CPU** |
| MuJoCo-Drones | Yes | Native quadrotor | Fast on GPU | Good for RL, needs GPU |
| Flightmare | Moderate | Native | Decoupled | Stale, Unity dependency |
| AirSim | Yes (Unreal) | Native | Heavy | Archived by MS |
| PX4 SITL + Gazebo | Moderate | Native PX4 | Real-time | Keep for control stack testing |

### New pipeline
1. **Genesis** (CPU, dev machine) → synthetic drone frames + cinematography scenarios for fine-tuning
2. **PX4 SITL + Gazebo** → full arbiter FSM + MAVSDK + OFFBOARD loop testing
3. **Real flight** → final step
4. **Skip Isaac Sim entirely** — requires cloud GPU, overkill

---

## 7. ToF Sensor — TMF8829 is a game-changer

| Sensor | Range | Zones | FOV | Verdict |
|---|---|---|---|---|
| VL53L8CX (current) | 4m | 8×8 (64) | 61° | Solid but range limiting |
| TMF8828 | 5m | 8×8 (64) | 63° | 25% more range, better sunlight |
| **TMF8829 (NEW 2025)** | **11m** | **Up to 48×32 (1536!)** | **80°** | **2.75x range, 24x resolution, wider FOV** |

### Why TMF8829 matters
- At 10 m/s drone speed: 4m gives 0.4s reaction time; **11m gives 1.1s** — difference between "can't stop" and "comfortable braking"
- 1536 zones vs 64 = near-depth-image instead of 8×8 grid. Enables obstacle shape/trajectory estimation
- SPAD + TDC + histogram = better in sunlight than VL53L8CX
- Available since Aug 2025 (Mouser)

### Recommended setup
- **TMF8829 forward-facing** (11m, 48×32) for obstacle avoidance
- **VL53L8CX downward-facing** (4m, 8×8) for landing altitude
- Trade-off: newer → fewer community drivers, may need custom I2C driver

---

## 8. User-Provided URL Analysis

| URL | Topic | Relevant? | Action |
|---|---|---|---|
| Ali Pahlevani SLAM/CV | SLAM for mobile robots | Low (SLAM explicitly rejected) | None |
| Antidoom/FTPO | Doom loop fix for LFM family | **HIGH** | **Add inference-time loop detector + post-fine-tune FTPO** |
| visionarynet AI/CV | Generalist vision foundation models | Low-medium (7B+ too large for Pi 5) | Monitor for future GPU tier |
| Liquid AI homepage | LFM product lineup | Already integrated | LEAP SDK bookmarked for fine-tuning |

---

## 9. Top 5 Actionable Changes (ranked by impact)

| # | Change | Effort | When |
|---|---|---|---|
| 1 | **Fine-tune LFM2.5-VL-450M** via leap-finetune on drone 5-tool schema | ~$5-10 Modal GPU | After G4 baseline |
| 2 | **Run Antidoom FTPO** as post-fine-tune cleanup, then temp=0.1 | ~1 GPU-hour | After fine-tuning |
| 3 | **Build llama.cpp from source** with `armv8.2-a+dotprod+i8mm`, use Q8_0 not Q4_0 | Config + build | S2 cognition |
| 4 | **TMF8829 ToF sensor** (11m, 48×32) forward-facing for obstacle avoidance | Hardware swap | Before G6 |
| 5 | **Genesis simulator** for CPU-only fine-tuning data gen | Setup + scripts | S4 control |

### Also do (quick wins)
- Inference-time doom loop detector (~20 lines in cognition layer) — S2
- Test LFM2.5-VL-450M-Extract variant for G4 gate — S2
- KV cache quantization + prefix caching in llama.cpp config — S2
- pymavlink for OFFBOARD hot path if MAVSDK jitter >5ms — S1/S5

### Keep as-is
- LFM2.5-VL-450M (best sub-1B VLM with function calling)
- MAVSDK-Python (with pymavlink hot-path upgrade if needed)
- Needle 26M router, PicoDet-S tracker, CfC LNN, PX4 OFFBOARD architecture
- Arbiter FSM (deterministic, owns all authority)
