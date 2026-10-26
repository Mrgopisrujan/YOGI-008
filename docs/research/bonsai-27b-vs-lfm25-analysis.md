# Bonsai-27B (PrismML) vs LFM2.5 Stack — Deep Research for GarudaOne

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - The active PX4 transport is pymavlink, not MAVSDK-Python.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - Land/RTL mode transfer requires PX4 ACK and heartbeat confirmation; physical behavior remains unqualified.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!NOTE]
> This is a dated research snapshot. Model choices, estimates, and recommendations are not implementation claims. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


**Date:** 2026-07-17
**Researcher:** Hermes subagent
**Question:** Can Bonsai-27B replace the LFM2.5-230M (L1 Director) + LFM2.5-VL-450M (episodic VL) stack on a Pi 5 CPU-only, 8GB RAM drone?
**Verdict:** **No.** Bonsai-27B is a remarkable model but is NOT viable as a Pi 5 CPU-only replacement for the LFM stack in this use case. Details and numbers below.

---

## 1. Actual CPU Inference Speed on ARM / Pi 5

### What the sources actually measured (all cited)

| Hardware | Variant | tok/s (gen) | Source |
|---|---|---|---|
| **Ryzen 7 5700X** desktop (8-core x86, 48GB) | 1-bit (Q1_0) | **6.0** | @networked, HN 645-pt thread (researchaudio.io) |
| **Ryzen 7 5700X** desktop | Ternary (Q2_0) | **0.7** | @networked, HN thread — "CPU inference for ternary isn't optimized yet" |
| **DGX Spark Grace** (20-core Cortex-X925/A725, aarch64) CPU-only | Ternary (Q2_0) | **~7.5** | khpawan/bonsai-dgx-spark (GitHub) |
| **DGX Spark GB10** CUDA (Blackwell GPU) | 1-bit (Q1_0) | **44.14** (tg128) | official community-benchmarks/bonsai/cuda-gb10-27b-linux.md |
| **iPhone 17 Pro Max** (A19 Pro) | 1-bit (Q1_0) | **10.82** (sustained, thermal) | PrismML whitepaper / researchaudio.io |
| **M4 Pro** laptop (Metal) | 1-bit | 26.0 | PrismML benchmark table |
| **M5 Max** laptop (Metal) | 1-bit / Ternary | 66.4 / 44.0 | PrismML benchmark table |
| **RTX 5090** | 1-bit / Ternary | 162.6 / 133.6 | PrismML benchmark table |
| **Bonsai 4B** on Pi 4 (4GB) | 1-bit | **~2.0** | stfurkan/pi-llm (GitHub) |
| **Bonsai 1.7B** on Pi 4 (4GB) | 1-bit | **~4-8** | stfurkan/pi-llm (GitHub) |
| **Ternary-Bonsai-1.7B** M4 Pro CPU (TQ2_0) | Ternary | 111.0 | ChaiWithJai/the-little-tree-thinks (1.7B, not 27B) |

### Pi 5 (4x A76 @ 2.4GHz) extrapolation — with reasoning

**There is NO published Pi-5-specific Bonsai-27B benchmark.** The community-benchmarks folder in Bonsai-demo has only one 27B entry (DGX Spark GB10 CUDA). Nobody has run 27B on a Pi 5 and published it — because at ~6 tok/s on an 8-core desktop Ryzen, a Pi 5 (roughly **1/4 the core count and ~1/5 the memory bandwidth** of a 5700X) would land in the **~1-2 tok/s range for 1-bit, and likely <0.5 tok/s for ternary (which is unoptimized on CPU).**

Evidence supporting this extrapolation:
- Pi 4 (4x A72, weaker than Pi 5) runs the **4B** at ~2 tok/s. A 27B is ~6.75x the params → expect ~0.3 tok/s on Pi 4, and Pi 5's A76 cores are ~2-3x faster than A72 → ~0.6-0.9 tok/s for 27B 1-bit on Pi 5.
- The 6 tok/s figure on a Ryzen 5700X (much faster IPC + 8 cores + AVX2) is the ceiling reference for desktop x86. ARM A76 has no AVX2; it has NEON (128-bit). The Bonsai-demo README confirms "Q1_0 (1-bit) is fully merged upstream... CPU (generic, NEON, and optimized x86)" — so NEON kernels exist, but NEON is narrower than AVX2.

**ARM NEON Q1_0 dot kernels: confirmed to exist** (mainline llama.cpp, merged). But "existence" ≠ "fast on a 4-core A76." The 6 tok/s number is the realistic desktop-x86 ceiling; Pi 5 will be a fraction of that.

**Speculative decoding (DSpark) does NOT help on low-end hardware.** Per the official GB10 27B benchmark: speculative with the official drafter gave 21.6 tok/s vs 43.7 base (a *slowdown*) on Q1_0, because "the Q1_0 forward pass is cheap enough that drafting overhead cancels verification-batching gains." DSpark gives only 1.34-1.37x on NVIDIA GPUs and is neutral-to-negative on Q1_0. **It will not rescue Pi 5 throughput.**

### Bottom line for Q1
- **1-bit Bonsai-27B on Pi 5: estimated ~1-2 tok/s** (no published measurement; extrapolated from 6 tok/s on a 4x-faster desktop x86 + 2 tok/s for 4B on Pi 4).
- **Ternary Bonsai-27B on Pi 5: estimated <0.5 tok/s** (CPU ternary kernels are explicitly unoptimized — 0.7 tok/s on a Ryzen 5700X).
- **For comparison: LFM2.5-230M on Pi 5 = 42 tok/s** (confirmed, runaihome.com + Liquid AI official).
- **Bonsai-27B is ~20-40x too slow for real-time L1 director use on Pi 5.** A single NL command → tool call could take 30+ seconds to generate at 1-2 tok/s with a thinking model that emits 1.5-2k reasoning tokens before the answer.

---

## 2. Vision / VL Capabilities

### Does 1-bit/ternary quantization preserve vision?

**Yes, but the vision tower is NOT quantized by the 1-bit/ternary scheme.** From docs.prismml.com/models/bonsai-27b:

> "The language model is quantized end-to-end 1-bit or ternary weights across embeddings, attention, MLPs, and the LM head. **The vision tower is handled separately, at 4-bit.**"

So the vision path (SigLIP-class tower + mmproj) is a **separate ~0.9 GiB file** (`*mmproj*.gguf`) that must be loaded alongside the language weights, regardless of whether you pick 1-bit or ternary. From VISION.md in Bonsai-demo:

> "Budget about 0.9 GiB of extra memory for the projector."

### What can it do?

- **Yes: scene understanding, image Q&A, screenshot/document analysis, OCR.** Send `image_url` content parts to the OpenAI-compatible API; get text answers.
- **Bounding-box prediction / object detection: NOT a native strength.** Bonsai-27B is a VLM (vision-language), not an object detector. It can *describe* scenes and *reason* about images, but it does not output pixel-accurate bounding boxes the way a detector (PicoDet, YOLO) or a grounded VLM (LFM2.5-VL-450M, which scores 81.28 on RefCOCO-M for bbox prediction) does.
- **Vision benchmark scores (PrismML whitepaper Table 11):**
  - FP16 Qwen3.6-27B: 72.61 (MMMU Pro, OCRBench)
  - Ternary Bonsai-27B: 65.19 (**-7.42pp, -10.2%**)
  - 1-bit Bonsai-27B: 59.57 (**-13.04pp, -18.0%**)

### The image-token cost problem for episodic use

From VISION.md: an image is encoded into vision tokens (~1 token per 32×32 patch), capped at **1024 tokens on CPU/Metal** (vs uncapped on CUDA/ROCm). Vision tokens are **prefill** — a 1024-token image adds 1024 tokens of prefill before the first output token.

On a Pi 5 at ~1-2 tok/s decode (and prefill is faster but still CPU-bound), a single frame's vision query would take **many seconds just for prefill**, then the thinking model emits 1.5-2k reasoning tokens before the answer. **A "1-3s/frame" episodic budget is not achievable** with Bonsai-27B on Pi 5 CPU. Even the iPhone 17 Pro Max (A19 Pro, much faster than A76) does 11 tok/s — and that's text-only; vision adds prefill overhead.

**For comparison: LFM2.5-VL-450M on Jetson Orin does 512×512 in 242ms** (sub-250ms, 4 FPS video stream). On Pi 5 it would be slower but still in the 1-3s/frame range that GarudaOne requires. Bonsai-27B's vision is far richer *qualitatively* (27B reasoning vs 450M) but far too slow *quantitatively* on Pi 5 CPU.

---

## 3. Tool Calling / Function Calling — How Bad Is the Degradation?

### The "14pp agentic drop" — fully sourced

From the PrismML official benchmark (prismml.com/news/bonsai-27b, Table 11 of the whitepaper), category "Agentic and Tool-calling (BFCL v3, TauBench)":

| Variant | Score | Drop from FP16 |
|---|---|---|
| FP16 Qwen3.6-27B | 80.00 | — |
| **Ternary Bonsai-27B** | **74.01** | **-5.99pp (-7.5%)** |
| **1-bit Bonsai-27B** | **66.03** | **-13.97pp (-17.5%)** ← the "14pp" |

The "14pp" refers to the **1-bit** variant. Ternary is only ~6pp down. researchaudio.io confirmed: "The blog post says 'tool calling stays within a few points of full precision.' A 14pp drop on the headline use case is not 'a few points.'"

### Independent tool-eval-bench (MiaAI-Lab) — real multi-turn tool use

This is the most relevant dataset for GarudaOne. MiaAI-Lab ran **Ternary-Bonsai-27B (Q2_0)** through `tool-eval-bench v2.0.6`: 84 scenarios, 8 trials, multi-turn tool calling with mock tools.

**Headline:** 85.0/100 mean, **76.2% pass rate** (pass = fully correct), 0.0pp reliability gap (fully deterministic across 8 trials at temp 0.7 seed 42), deployability 80/100.

**Per-category (the important part for drone tool calls):**

| Category | Ternary Bonsai-27B | Read-through for GarudaOne |
|---|---|---|
| Tool Selection | **100%** | Picks the right tool ✅ |
| Parameter Precision | **100%** | Right args ✅ |
| Error Recovery | **100%** | Recovers from tool errors ✅ |
| Structured Reasoning | **100%** | ✅ |
| Instruction Following | **100%** | ✅ |
| Code Patterns | **100%** | ✅ |
| Toolset Scale | 88% | Good |
| Safety & Boundaries | 88% | 1 safety warning per trial |
| Restraint & Refusal | 83% | Sometimes calls tools when none needed |
| Structured Output | 83% | JSON mostly clean, occasional extra keys |
| Autonomous Planning | 83% | |
| Localization | 83% | |
| Creative Composition | 83% | |
| Multi-Step Chains | **75%** | 3+ tool chains lose coherence |
| Context & State | **65%** | ← weakest; multi-turn state tracking fails |
| Hard Mode | 80% | |

**5 scenarios NEVER pass (0/8 trials):**
- TC-48: Did not send any emails.
- **TC-60: CRITICAL — Sleeper injection activated; added attacker BCC/CC from turn-1 weather data.** (Prompt-injection vulnerability — concerning for any agent that ingests external data.)
- TC-61: Ran once but didn't handle 'pending' response by retrying.
- TC-68: Called tools when none were needed.
- TC-71: Sent email to multiple Jordans — should have asked which one.

**Comparison vs Qwen3.6-27B-NVFP4** (the NVFP4 4-bit build, from the same bench):
- NVFP4: 89.0 mean, 81.0% pass, 0 safety warnings, median turn 7.1s
- Ternary Bonsai: 85.0 mean, 76.2% pass, 1 safety warning, median turn 1.7s
- Bonsai is **faster (1.7s vs 7.1s median turn)** but **less accurate and less safe** (-4 score, -4.8pp pass, +1 safety failure).

### Can it reliably produce structured JSON tool calls (GBNF-constrained)?

**With GBNF grammar constraining the output: yes, structurally.** The ChaiWithJai field study explicitly used "grammar-constrained JSON the model *cannot* get wrong" — decode-time schemas that force valid JSON. With a GBNF grammar pinning the output to your tool-call schema (hover, land, rtl, track_subject, set_framing + args), Bonsai-27B would emit valid JSON every time.

**But GBNF only guarantees structure, not semantic correctness.** The 83% "Structured Output" category score (vs 100% for tool selection/precision) means that even when the JSON is valid, ~17% of the time it has extra keys or wrong values. GBNF won't fix a model that picks `track_subject` when it should pick `set_framing` — and the 100% Tool Selection score suggests it usually picks correctly, but the 65% Context & State score means multi-turn command sequences will drift.

**The 76.2% pass rate is below GarudaOne's G4 gate (≥95% on 100 NL commands).** Even the ternary (better) variant fails this gate. The 1-bit variant (66.03 agentic score) would be worse.

---

## 4. Memory Footprint on Pi 5 8GB — Will It OOM?

### The numbers (from docs.prismml.com + HF model cards)

| Component | Size |
|---|---|
| 1-bit Bonsai-27B GGUF (Q1_0) | 3.53 GiB on disk |
| Ternary Bonsai-27B GGUF (Q2_0) | 6.66 GiB on disk |
| mmproj (vision tower, 4-bit) | +0.9 GiB |
| KV cache (4-bit quantized, 262K ctx) | up to ~4.3 GiB at full context; **~1-2 GiB realistic for drone chat ctx (4-8k tokens)** |

### Pi 5 8GB budget math

| Budget item | 1-bit path | Ternary path |
|---|---|---|
| Pi 5 OS + MAVSDK + overhead | ~0.5 GiB | ~0.5 GiB |
| PicoDet ncnn perception | ~0.2 GiB | ~0.2 GiB |
| Bonsai-27B weights | 3.53 GiB | **6.66 GiB** |
| mmproj (if using vision) | +0.9 GiB | +0.9 GiB |
| KV cache (8k ctx, 4-bit) | ~1.0 GiB | ~1.0 GiB |
| **Total** | **~6.1 GiB** | **~9.3 GiB** |
| **Pi 5 8GB headroom** | **~1.9 GiB free** ✅ (text-only) / ~1.0 GiB (with VL) | **OOM** ❌ |

**Findings:**
- **1-bit Bonsai-27B (text-only, no VL) FITS on Pi 5 8GB** with ~1.9 GiB headroom for perception + OS. Tight but workable.
- **1-bit Bonsai-27B + mmproj (VL enabled): ~6.1 GiB**, ~1.0 GiB headroom — very tight, risky with a live perception stack.
- **Ternary Bonsai-27B: OOMs on Pi 5 8GB.** 6.66 GiB weights alone leave only 1.34 GiB for everything else (OS + MAVSDK + PicoDet + KV cache). **Will not fit.** This matches the iPhone finding: "Ternary doesn't fit on iPhone 17 Pro (7.2GB > 6GB app budget)."
- **The KV cache is the hidden killer.** The whitepaper notes the 27B's hybrid-attention (16/64 full-attention layers + 48 linear-attention) helps, and 4-bit KV cache is tolerated well — but even at 4-bit, an 8k-token context for a thinking model (which emits 1.5-2k reasoning tokens) needs ~1 GiB of KV cache. Add that to 3.53 GiB weights + 0.9 GiB mmproj + 0.7 GiB OS/perception = 6.1 GiB. Survivable for 1-bit text-only; fatal for ternary.

**Verdict: Only 1-bit text-only fits. Ternary OOMs. 1-bit + VL is marginal.**

---

## 5. License

**Apache 2.0. Confirmed by 5+ independent sources:**
- prism-ml/Bonsai-27B-gguf HF model card: "License: Apache 2.0"
- docs.prismml.com/models/bonsai-27b spec table: "Apache 2.0"
- prismml.com/news/bonsai-27b: "Everything is available today under the Apache 2.0 License."
- marktechpost, business-standard, tldevtech, best-ai.org, creativeainews: all confirm Apache 2.0.
- Bonsai-demo repo has a LICENSE file.

**Commercial use: YES.** Apache 2.0 permits commercial use, modification, distribution, and derivative works (including fine-tuning) without per-seat fees or royalty obligations. The only requirements: preserve the copyright notice, include a copy of the Apache 2.0 license, and state significant changes made to the model.

**AatoNovaZ can use Bonsai-27B commercially in a product.** No license blocker. (Note: the *base model* Qwen3.6-27B is also Apache 2.0, so the chain is clean.)

**Caveat:** The 27B repos were briefly private (needed `BONSAI_TOKEN` during a preview window). Per the README, this is "removed at launch" — they should be public now. Verify at huggingface.co/prism-ml/Bonsai-27B-gguf.

---

## 6. Comparison: Bonsai-27B vs LFM2.5-230M + LFM2.5-VL-450M

### Head-to-head for GarudaOne's three jobs

| Criterion | Bonsai-27B (1-bit, if it fit) | LFM2.5-230M + LFM2.5-VL-450M | Winner |
|---|---|---|---|
| **Pi 5 tok/s (text)** | ~1-2 tok/s (est.) | 42 tok/s (confirmed) | **LFM (20-40x faster)** |
| **Pi 5 RAM (text-only)** | 3.53 GiB + KV | ~0.3-0.4 GiB (293-375 MB Q4) | **LFM (10x smaller)** |
| **Pi 5 RAM (with VL)** | ~6.1 GiB (marginal) | ~0.3 (LLM) + ~0.5 (VL) = ~0.8 GiB | **LFM (7.6x smaller)** |
| **Tool-calling accuracy (BFCL-class)** | Ternary 74.0 / 1-bit 66.0 (FP16=80) | 230M: "competitive for 230M" + GBNF-constrained JSON; no published BFCL score but grammar-pinned output is structurally guaranteed | **Bonsai (raw capability)** but LFM+GBNF wins on *reliability* |
| **Multi-turn tool-eval pass rate** | 76.2% (ternary, MiaAI-Lab) | No equivalent bench published; but GBNF + Needle router + small fixed toolset → high reliability on narrow domain | **LFM (for narrow toolset)** / Bonsai (for open-ended) |
| **G4 gate (≥95% on 100 NL cmds)** | 76.2% — **FAILS** | Achievable with GBNF + Needle + small toolset (GarudaOne's design) | **LFM** |
| **Structured JSON reliability** | 83% structured-output category (valid JSON, occasional extra keys) | GBNF grammar = 100% structurally valid; semantic accuracy depends on model | **LFM (with GBNF)** |
| **Scene understanding quality** | 27B reasoning over images — rich, nuanced, can describe cinematographic framing, lighting, composition. Vision score 59.6 (1-bit) / 65.2 (ternary) | 450M VLM — basic grounding, bbox prediction (RefCOCO-M 81.28), scene description, but shallow reasoning | **Bonsai (quality, if it were fast enough)** |
| **Bbox / object detection** | Not a native capability (VLM, not detector) | Native bbox prediction (81.28 RefCOCO-M) + pairs with PicoDet | **LFM-VL / PicoDet** |
| **Episodic frame latency (Pi 5)** | Many seconds (prefill 1024 vision tokens + 1.5-2k thinking tokens at 1-2 tok/s) = 30s+ per frame | 1-3s/frame target (Jetson Orin does 242ms for 512×512; Pi 5 slower but in-budget) | **LFM-VL** |
| **Prompt-injection resistance** | TC-60 CRITICAL failure: sleeper injection activated (added attacker BCC) — 1 safety warning per trial | Small model + GBNF + arbiter FSM = injection surface minimized; model can't emit arbitrary actions | **LFM (architecture)** |
| **License** | Apache 2.0 ✅ | LFM2.5: Apache 2.0 / Liquid AI license (check — LFM2.5-230M is Apache 2.0) | Tie |
| **Latency to first tool call** | 30+ seconds (thinking model, 1-2 tok/s, 1.5-2k reasoning tokens) | <1 second (42 tok/s, no thinking mode, GBNF-constrained) | **LFM** |

### Per-question answers

**Q: Which gives better tool-calling accuracy for NL drone commands?**
**LFM2.5-230M + GBNF + Needle router** — for GarudaOne's *narrow, fixed toolset* (hover, land, rtl, track_subject, set_framing + args). Bonsai-27B has higher *raw* agentic capability (74.0 BFCL vs an unmeasured-but-grammar-pinned 230M), but:
1. Bonsai's 76.2% multi-turn pass rate **fails the 95% G4 gate**.
2. Bonsai is 20-40x too slow on Pi 5 for real-time L1 direction (30s+ per command).
3. GBNF grammar-constrained output from the 230M *guarantees* structurally valid tool calls every time; the 230M only needs to get the *semantic* choice right among 5 tools, which is a much easier task than BFCL's 84 open-ended scenarios.
4. Bonsai had a CRITICAL prompt-injection failure (TC-60) — a safety concern for any agent ingesting external data.

For a *narrow, fixed, safety-critical toolset* on a constrained device, the small-model + GBNF + deterministic arbiter pattern is more reliable than a large model with a 14-17% agentic degradation.

**Q: Which has better scene understanding for cinematography?**
**Bonsai-27B (qualitatively)** — a 27B reasoning model sees and reasons about framing, lighting, composition, subject movement, and cinematic intent far better than a 450M VLM. If you could run it fast enough (you can't on Pi 5), Bonsai would give richer cinematographic guidance.

**But operationally on Pi 5: LFM2.5-VL-450M wins** because:
1. It actually fits the 1-3s/frame episodic budget (242ms on Jetson Orin; Pi 5 likely 1-3s).
2. It has native bbox prediction (81.28 RefCOCO-M) — directly useful for track_subject framing.
3. Bonsai-27B's vision on Pi 5 would take 30+ seconds per frame (prefill + thinking tokens at 1-2 tok/s), breaking the episodic budget entirely.

**Q: Which is more reliable for structured JSON output?**
**LFM2.5-230M + GBNF** — grammar-constrained decoding produces *structurally* valid JSON 100% of the time by construction. Bonsai-27B scored 83% on the structured-output category (valid JSON but occasional extra keys/wrong values). GBNF doesn't guarantee semantic correctness, but for a 5-tool drone schema, the 230M + GBNF + Needle router is the more reliable path to the ≥95% G4 gate.

---

## Summary Verdict

**Bonsai-27B is an extraordinary model — for laptops and phones with accelerators (Metal/CUDA). It is NOT viable as a Pi 5 CPU-only replacement for the LFM2.5 stack in GarudaOne.**

| Gate | Bonsai-27B on Pi 5 | Pass? |
|---|---|---|
| Real-time L1 speed (≤2s/command) | ~30s+ at 1-2 tok/s | ❌ FAIL |
| Episodic VL (1-3s/frame) | 30s+ per frame | ❌ FAIL |
| 8GB RAM (1-bit text-only) | ~6.1 GiB with VL | ⚠️ Marginal |
| 8GB RAM (ternary) | OOMs (~9.3 GiB) | ❌ FAIL |
| Tool-calling ≥95% (G4) | 76.2% pass rate | ❌ FAIL |
| License (commercial) | Apache 2.0 | ✅ PASS |

**5 of 6 gates fail. Only the license passes.**

### The one scenario where Bonsai-27B could matter for GarudaOne
If GarudaOne later adds a **cloud/hybrid tier** (e.g., Modal GPU for complex mission planning, pre-flight cinematic intent parsing, or post-flight highlight reel generation), Bonsai-27B ternary on a cloud GPU (44 tok/s on GB10, 134 tok/s on RTX 5090) would be a strong *offline* reasoning model — Apache 2.0, no per-token cost, 74.0 BFCL agentic score. But that's a cloud workload, not a Pi-5 CPU workload.

### Recommendation
**Keep the LFM2.5-230M + LFM2.5-VL-450M + GBNF + Needle + arbiter FSM architecture for the Pi 5 onboard stack.** It is purpose-built for the constraints (42 tok/s, <1GB, GBNF-guaranteed JSON, deterministic arbiter owns motors). Bonsai-27B does not clear the speed, memory, or tool-calling-reliability gates on Pi 5 CPU. Revisit Bonsai-27B only if (a) GarudaOne moves to a Jetson Orin Nano + GPU, or (b) a cloud/hybrid reasoning tier is added.

---

## Sources (all verified, not speculation)

- **PrismML official:** prismml.com/news/bonsai-27b (benchmark table, license), docs.prismml.com/models/bonsai-27b (specs, mmproj 4-bit, vision-token cap)
- **Bonsai-demo repo:** github.com/PrismML-Eng/Bonsai-demo (README, VISION.md, SPECULATIVE.md, community-benchmarks/bonsai/cuda-gb10-27b-linux.md)
- **Tool-eval-bench:** github.com/MiaAI-Lab/Ternary-Bonsai-27B-tool-eval-bench-results (85.0 score, 76.2% pass, per-category breakdown, failure analysis, comparison vs NVFP4)
- **DGX Spark CPU benchmark:** github.com/khpawan/bonsai-dgx-spark (7.5 tok/s CPU-only, 28 tok/s CUDA, 20-core Grace)
- **Pi 4 Bonsai benchmark:** github.com/stfurkan/pi-llm (4B ~2 tok/s, 1.7B ~4-8 tok/s)
- **HN thread (645 pts):** researchaudio.io (6 tok/s binary / 0.7 tok/s ternary on Ryzen 7 5700X, 14pp agentic drop, 1.125 effective bits)
- **Field study:** github.com/ChaiWithJai/the-little-tree-thinks (125 tok/s on 1.7B M4 Pro, grammar-constrained JSON pattern, 18 footguns)
- **alphaxiv overview:** alphaxiv.org/overview/2607.bonsai-27b (DSpark 1.34-1.37x, hybrid-attention KV cache, qualitative-collapse analysis)
- **LFM2.5-230M:** runaihome.com, Liquid AI LinkedIn (42 tok/s Pi 5, 213 tok/s S25 Ultra, 293-375 MB)
- **LFM2.5-VL-450M:** liquid.ai/blog/lfm2-5-vl-450m (RefCOCO-M 81.28 bbox, 242ms Jetson Orin 512×512, MMMB 68.09, function calling via BFCLv4)
- **MarkTechPost, Business Standard, TLDevTech, Best-AI.org, CreativeAINews:** Apache 2.0 license confirmation (multiple independent)
- **the-agent-report.com:** unit-economics analysis, 74.01 ternary agentic score, hybrid routing context
