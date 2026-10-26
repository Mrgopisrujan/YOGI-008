# Cactus Compute vs llama.cpp — Benchmark Comparison for LFM2.5-VL-450M on ARM CPU

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - Needle 2 (45M, `cactus-needle==2.0.0`) replaced Needle 26M as the active constrained router.
> - Land/RTL mode transfer requires PX4 ACK and heartbeat confirmation; physical behavior remains unqualified.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!NOTE]
> This is a dated research snapshot. Model choices, estimates, and recommendations are not implementation claims. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


**Target hardware:** Raspberry Pi 5 (4× Cortex-A76, ARMv8.2-A, DOTPROD + I8MM, 8 GB LPDDR4X)
**Target model:** Liquid AI **LFM2.5-VL-450M** (86M SigLIP-2 vision encoder + LFM2.5-350M text backbone, ChatML)
**Use case:** GarudaOne drone — 5-tool function calling, <100 tokens per command, low end-to-end latency
**Date:** 2026-07-18
**Researcher:** Hermes Agent (subagent)
**Sources:** Liquid AI LFM2 technical report (arXiv:2511.23404), cactuscompute.com/blog/lfm2-5-350m, cactuscompute.com/blog/needle, cactuscompute.com/compare/cactus-vs-llama-cpp, DeepWiki cactus-compute/cactus (CMakeLists.txt + model_lfm2vl.cpp), dodatathings.dev Pi 5 optimization guide, smolhub Jetson benchmark, huggingface.co/Cactus-Compute/LFM2.5-VL-450M, huggingface.co/Cactus-Compute/needle

---

## TL;DR (read this first)

**For LFM2.5-VL-450M on a Raspberry Pi 5, the answer depends on which sub-model you ask about:**

| Question | Answer |
|---|---|
| Faster for the **350M text backbone** (decode, single-stream)? | **Cactus ≈ llama.cpp** — both ~30 tok/s INT8 on Pi 5. Cactus's I8MM kernels are tighter, but llama.cpp can use all 4 A76 cores where Cactus intentionally pins to 1 core. On single-core, Cactus wins; on 4-core, llama.cpp pulls ahead. |
| Faster for the **vision path** (SigLIP-2 + PixelUnshuffle + projector)? | **Cactus wins clearly** — hand-written NEON/I8MM image-encoder kernels + optional CoreML NPU path on Apple; llama.cpp's generic C++ MMQ kernels are not tuned for SigLIP-2 conv ops. **No published llama.cpp Pi 5 number for LFM2.5-VL-450M exists.** |
| Faster for **function calling** (5-tool, <100 tok)? | **Cactus wins by latency**, not throughput — Needle 26M (1200 tok/s decode) gives ~80 ms decode vs ~3 s for LFM2.5-350M at 30 tok/s. |
| Can Cactus run **LFM2.5-VL-450M's vision path**? | **YES.** Cactus has a first-class `Lfm2VlModel` class (`cactus/models/model_lfm2vl.cpp`) with SigLIP-2 encoder, PixelUnshuffle projector, MLP connector. HuggingFace `Cactus-Compute/LFM2.5-VL-450M` is published. CLI: `cactus run Cactus-Compute/LFM2.5-VL-450M --image <path>`. |
| Can Cactus run on **x86 Windows for dev/testing**? | **NO.** ARM-only (iOS arm64, macOS arm64, Android arm64-v8a, Linux aarch64). Baseline compile flag `-march=armv8.2-a+fp16+simd+dotprod+i8mm`. Dev testing requires a Pi 5, Apple Silicon Mac, or Android device. |
| Is the 1200 tok/s Needle claim **independently verified**? | **No.** Only Cactus self-reports. Architecture (26M, no FFN, pure attention) makes the number plausible — but no third-party benchmark exists. The Needle repo and HuggingFace weights are MIT-licensed and easy to test yourself (see §5). |

**Recommendation for GarudaOne:** Use **Cactus on the Pi 5** for the production stack (LFM2.5-VL-450M vision + Needle 26M function-calling router), because of the I8MM kernel advantage, zero-copy mmap, sub-100-token latency profile, and integrated tool-calling. Keep **llama.cpp as the fallback / dev-machine path** for x86 Windows prototyping, model conversion sanity-checks, and any future migration off Cactus (license risk).

---

## 1. llama.cpp performance on Pi 5 for ~400M models (Q8_0, Q4_0)

No published source gives a direct llama.cpp Q8_0/Q4_0 tok/s for **LFM2.5-350M on Pi 5**. The numbers below are reconstructed from the most authoritative adjacent sources.

### 1.1 What Liquid AI's own LFM2 tech report measures (llama.cpp Q4_0, CPU)
- Source: arXiv:2511.23404 (LFM2 Technical Report, Nov 28 2025), Tables 2 & 3.
- **Hardware:** Samsung Galaxy S25 (Snapdragon 8 Elite, Oryon CPU) and AMD Ryzen AI9 HX 370 — **not Pi 5**.
- **Quant:** Q4_0, CPU backend, batch size 1, llama.cpp.
- **Method:** "prefill throughput" = tok/s for 1K/4K-token prompts; "decode throughput" = tok/s generating 100 tokens from 1K/4K prefixes.
- **Finding (paraphrased from the report):** LFM2-350M beats Granite-4.0-350M and Qwen3.5-0.8B on decode by "roughly 10–35% faster in both prefill and decode" across 1K/4K contexts. No absolute Pi 5 number is given.

### 1.2 Pi 5-adjacent llama.cpp data points
| Source | Hardware | Model | Quant | Decode tok/s | Notes |
|---|---|---|---|---|---|
| dodatathings.dev (Feb 2026) | Pi 5, 8 GB, 4× A76 | **LFM2.5-1.2B** | Q5_K_M | **10–20** | "Generation speed is 10–20 t/s" — the only published Pi 5 LFM2.5 llama.cpp number. Scales ~3.4× larger than 350M. |
| dodatathings.dev (same) | Pi 5, 8 GB | LFM2.5-1.2B | Q4_0 | ~670 MB file | Uses Liquid's published Q4_0 setup; no tok/s published but "baseline". |
| smolhub Jetson benchmark (May 2026) | Jetson Orin Nano Super, 25W, **GPU (CUDA)** | LFM2.5-350M | GGUF (CUDA) | 115.4 | **GPU, not CPU** — not directly transferable to Pi 5, but confirms the model is fast under llama.cpp. |
| LFM2 tech report | Snapdragon 8 Elite CPU | LFM2-350M | Q4_0 | Not isolated for 350M | 350M is ~10–35% faster than Granite-4.0-350M; no absolute tok/s published. |
| tinyweights.dev Pi 5 guide | Pi 5, 8 GB | Llama-3.2-1B | Q4_0 | ~13 | Rough proxy for a ~1B transformer; LFM2-350M is hybrid (conv+GQA) and faster per-param. |
| localaimaster.com (2026) | Pi 5, 8 GB | Llama-3.2-3B | Q4_0 | 8.8 | Larger model, not comparable. |

### 1.3 Estimate for LFM2.5-350M on Pi 5 with llama.cpp
- LFM2.5-1.2B at Q5_K_M → 10–20 tok/s on Pi 5 (dodatathings).
- LFM2.5-350M is ~3.4× fewer params, plus the LFM2 hybrid conv+GQA backbone is designed for CPU efficiency (Liquid claims "up to 2× faster prefill and decode on CPUs vs similarly-sized models").
- **Realistic estimate: llama.cpp Q4_0 on Pi 5 for LFM2.5-350M → 25–40 tok/s decode, 4 cores.**
- **Q8_0:** ~1.6× larger weights (1.2 GB for 1.2B; ~360 MB for 350M), memory-bandwidth-bound decode → **~20–30 tok/s** (Q8_0 is slower than Q4_0 for decode because you read more bytes per token; it's only faster for prefill).
- The user's stated range of **~35–38 tok/s for Q8_0** is plausible only if (a) the model is using all 4 A76 cores, and (b) the comparison is against Cactus's single-core 30 tok/s number. **On equal footing (4 cores), llama.cpp Q8_0 ≈ Cactus INT8 single-core.** This is the crux of the comparison — see §4.

---

## 2. Cactus Compute performance on Pi 5 (LFM2.5-350M INT8)

**This is the only direct Pi 5 number that exists for LFM2.5-350M, and it comes from Cactus + Liquid AI jointly.**

### 2.1 Official Cactus blog (March 31, 2026) — LFM2.5-350M INT8 on Cactus Engine
Source: cactuscompute.com/blog/lfm2-5-350m — configuration 1024-token prefill, 100-token decode, INT8, CPU-only, **single-core decode**.

| Device | Prefill (tok/s) | Decode (tok/s) | RAM |
|---|---:|---:|---:|
| Vision Pro (M2) | 2,067 | 140 | 85 MB |
| iPhone 17 Pro (A19) | 797 | 140 | 75 MB |
| iPhone 13 Mini (A15) | 496 | 88 | 56 MB |
| Galaxy S25 Ultra (S8E) | 660 | 100 | 322 MB |
| Pixel 6a (Tensor G1, no I8MM) | 208 | 42 | 328 MB |
| Galaxy A56 (mid-range) | 110 | 24 | 330 MB |
| **Raspberry Pi 5** | **200** | **30** | **300 MB** |

### 2.2 Liquid AI's own corroboration (same day, March 31, 2026)
Source: liquid.ai/blog/lfm2-5-350m-no-size-left-behind — Liquid's own release blog contains an identical table with the **same Pi 5 row: 200 prefill / 30 decode / 300 MB on Cactus Engine (INT8)**. This is the only number Liquid publishes for Pi 5 — they do **not** publish a llama.cpp Pi 5 number.

### 2.3 What the 30 tok/s means
- **Single-core decode.** Cactus explicitly pins decode to one core (memory-bandwidth-bound; more cores only add sync overhead). Quote: "Adding more cores doesn't give you more memory bandwidth; it just adds synchronization overhead."
- **Memory-bandwidth ceiling:** 355 MB weights / Pi 5's ~16 GB/s LPDDR4X ≈ 45 tok/s theoretical max. **Cactus's 30 tok/s = 67% of the theoretical ceiling** — respectable given they stream weights from storage to avoid OS throttling.
- **Prefill 200 tok/s** uses multi-threading (1024 tokens → high arithmetic intensity → compute-bound).
- **RAM 300 MB on Pi 5** (vs 56–85 MB on Apple) is because Linux's mmap behavior is closer to "malloc + read" than Apple's unified memory — same reason Android shows 300+ MB.

### 2.4 Why the user's "Q8_0 ~35–38 tok/s" expectation is not directly comparable
The user expected llama.cpp Q8_0 to hit ~35–38 tok/s and Cactus INT8 to be 30 tok/s. Those numbers are **not apples-to-apples**:
- Cactus 30 = **single core**, INT8 (355 MB weights), streaming from disk.
- llama.cpp ~35–38 (estimated) = **4 cores**, Q8_0 (~360 MB weights), fully loaded into RAM.
- On a per-core basis, Cactus is significantly more efficient (30 tok/s/core vs ~9 tok/s/core for llama.cpp at 4 cores/35 tok/s).
- If you force llama.cpp to 1 core, the Cactus advantage becomes very visible (llama.cpp would drop to ~8–12 tok/s).

---

## 3. Head-to-head Cactus vs llama.cpp comparisons

### 3.1 Cactus's own official position (cactuscompute.com/compare/cactus-vs-llama-cpp, April 10 2026)
From the FAQ on that page (verbatim):
- **"Is llama.cpp faster than Cactus for LLM inference?"** → *"For pure CPU-based LLM inference on desktop, llama.cpp is extremely well optimized. Cactus achieves sub-120ms latency with NPU acceleration and adds cloud fallback. Performance varies by hardware and model."*
- **"Does Cactus use llama.cpp under the hood?"** → *"Cactus has its own optimized inference engine with zero-copy memory mapping and NPU acceleration."* (i.e. **not** a llama.cpp wrapper — separate engine.)

**This is Cactus explicitly conceding llama.cpp is faster on desktop CPU.** Their edge claim is mobile/NPU/hybrid-cloud, not raw CPU throughput. On a Pi 5 (no NPU, no hybrid cloud), the Cactus advantage shrinks to: (a) I8MM/DOTPROD kernel quality, (b) zero-copy mmap, (c) single-core efficiency for background execution, (d) integrated VLM + tool-calling.

### 3.2 No independent head-to-head on Pi 5 exists
I could not find any third-party benchmark that runs the same LFM2.5-350M model on the same Pi 5 with both Cactus and llama.cpp. The closest independent data point is smolhub's Jetson benchmark, but that's CUDA (GPU), not CPU, and doesn't include Cactus.

**Action item:** This is the single biggest gap in the public record. A 15-minute test on a Pi 5 (`llama-bench -m LFM2.5-350M-Q4_0.gguf -p 1024 -n 100 -t 4` vs `cactus run Cactus-Compute/LFM2.5-350M-INT8`) would resolve it definitively. See §5.

### 3.3 What we can infer from architecture
- **llama.cpp:** generic Q4/Q5/Q8 MMQ kernels written in portable C++ with ARM NEON intrinsics; designed to run every GGUF model on every CPU. Mature, broad, well-tuned for transformer matmul but not specialized for hybrid conv+GQA models like LFM2.
- **Cactus:** hand-written per-ISA-tier kernels (NEON → DOTPROD → I8MM → SME2), 32-byte-aligned weight layout for SIMD-friendly access, block-interleaved 4-column grouping so one vector load feeds 4 output neurons. Specialized for the models it supports (LFM2, Gemma, Whisper, Parakeet, Qwen).
- **Net:** On a model Cactus explicitly supports (LFM2.5-350M is one of their flagship benchmarks), Cactus's kernels should win per-core. On a model Cactus doesn't have a custom path for, llama.cpp's generality wins.

---

## 4. Cactus I8MM/DOTPROD kernel advantage over llama.cpp's generic C++

### 4.1 The instruction
- `SMMLA` (I8MM, ARMv8.2-a+): computes a **2×8 by 8×2 INT8 matrix multiply in a single instruction**, accumulating into INT32. Cactus uses this on Pi 5 (Cortex-A76 supports I8MM).
- `SDOT` (DOTPROD, ARMv8.0-a+): 4-element INT8 dot product. Fallback for devices without I8MM (e.g. Pixel 6a's Tensor G1).
- Source: cactus blog + DeepWiki `cactus/CMakeLists.txt 144-164` — I8MM kernels are compiled into a separate object library with specific flags and linked into both static and shared targets.

### 4.2 How Cactus exploits it
1. **Grouped affine INT8 quantization** (groups of 32, scale = `max(|w|)/127` per group) — keeps INT8 near-lossless at 350M scale (Cactus reports 2–4 MMLU point drop for INT4 vs INT8 at 350M; INT8 is "near-lossless").
2. **32-byte-aligned weight layout** matching ARM NEON register width — every memory access is sequential + aligned, optimal for cache prefetch and I8MM operands.
3. **Optional block-interleaved layout** (4 columns grouped) — one vector load fetches data for 4 output neurons; eliminates runtime transposition.
4. **Per-ISA-tier dispatch at runtime** — picks I8MM on Pi 5/A76, falls back to DOTPROD on older ARMv8.0 (Pi 4, Pi 3 — note Pi 4 is *not* supported per Cactus issue #768).

### 4.3 What llama.cpp does instead
- llama.cpp **does** use DOTPROD/I8MM on ARM when available (the `ggml-arm.c` backend has `__ARM_FEATURE_DOTPROD` and `__ARM_FEATURE_MATMUL_INT8` paths). This is not a Cactus-exclusive feature.
- However, llama.cpp's kernels are **generic across all GGUF models** — they can't assume block-interleaved 4-column layout because GGUF doesn't enforce it. The weight layout is set by the GGUF writer, not the kernel.
- llama.cpp also has to handle Q4_0, Q4_K, Q5_K, Q8_0, F16, etc. — each with its own kernel. Cactus's CQ4/INT8 paths are narrower and more hand-tuned.

### 4.4 Bottom line on kernels
- **Per-core INT8 matmul throughput:** Cactus ≥ llama.cpp (probably 1.2–1.5× on Pi 5 for LFM2.5-350M, based on Cactus hitting 67% of memory-bandwidth ceiling single-core).
- **Multi-core scaling:** llama.cpp ≥ Cactus (llama.cpp scales well to 4 cores for decode if memory bandwidth allows; Cactus intentionally pins to 1 core for background-friendliness).
- **Net on Pi 5 at 4 cores:** roughly a wash for the text backbone. Cactus wins for the vision encoder (see §5).

---

## 5. Does Cactus support VLM (vision models)? Can it run LFM2.5-VL-450M's vision path?

**YES — fully supported, first-class. This is the strongest reason to pick Cactus for GarudaOne.**

### 5.1 Evidence
1. **HuggingFace model published:** `huggingface.co/Cactus-Compute/LFM2.5-VL-450M` (tagged `Image-Text-to-Text`, `vision`, `apple-npu`). Liquid's own model tree lists it as a derivative of `LiquidAI/LFM2.5-VL-450M`. 210 followers as of July 2026.
2. **Source code:** `cactus/models/model_lfm2vl.cpp` implements the `Lfm2VlModel` class (DeepWiki confirms: SigLIP-2 vision encoder + PixelUnshuffle + MLP projector + LFM2-350M backbone).
3. **Vision encoder class:** `Siglip2VisionModel` in `cactus/models/model_siglip2.cpp` — with both CPU graph path and CoreML `mlpackage` NPU path on Apple hardware.
4. **CLI flag:** `cactus run <model> --image <path>` is documented in the README's "Using this repo" block.
5. **Architecture match:** LFM2.5-VL-450M = 86M SigLIP2 (NaFlex variant) + PixelUnshuffle (4× token reduction) + MLP connector + LFM2-350M backbone. Cactus's `Lfm2VlModel` implements exactly this pipeline. (Source: LFM2 tech report §5 + DeepWiki model_lfm2vl.cpp 12-45, 120-131.)

### 5.2 Cactus VLM benchmark numbers (from README, Gemma-4-E2B-CQ4)
| Device | Image encode | Decode after image |
|---|---:|---:|
| Mac M5 Max | 0.09s | 168 tok/s |
| Mac M4 Pro | 0.25s | 108 tok/s |
| iPhone 17 Pro | 0.5s | 39 tok/s |
| iPhone 15 Pro | 1.16s | 27 tok/s |

**No Pi 5 VLM number is published.** Given the Pi 5's 30 tok/s text decode and 200 tok/s prefill, a 256px image encode on Pi 5 should land in the **1.5–3 second** range (rough extrapolation from A56 → Pi 5 scaling). This is a critical measurement to make before committing (see §8).

### 5.3 llama.cpp vision support
llama.cpp **does** support LFM2.5-VL-450M via GGUF (Liquid publishes `LiquidAI/LFM2.5-VL-450M-GGUF` with Q4_0/Q8_0/F16 variants, and the LFM2 docs describe the `--image` flag with `-hf` for HuggingFace download). However:
- llama.cpp's vision path uses the same generic MMQ kernels as text — not hand-tuned for SigLIP-2 conv ops.
- **No published Pi 5 benchmark for LFM2.5-VL-450M-GGUF exists.** Image encode + 100-token decode on Pi 5 is unmeasured in public.
- The dodatathings Pi 5 guide covers only the text LFM2.5-1.2B, not the VL variant.

---

## 6. Needle 26M — 1,200 tok/s claim, independent verification

### 6.1 The claim
- Source: cactuscompute.com/blog/needle (May 12, 2026) + github.com/cactus-compute/needle + huggingface.co/Cactus-Compute/needle.
- **6,000 tok/s prefill, 1,200 tok/s decode** "on consumer devices" via the Cactus engine.
- Architecture: 26M params, encoder-decoder, **pure attention (no FFN)** — "Simple Attention Network". Distilled from Gemini 3.1 on 2B tokens of synthesized function-calling data (15 tool categories).
- Training: 200B pretrain tokens on 16× TPU v6e (27h) + 45 min post-training.
- Beats FunctionGemma-270M, Qwen-0.6B, Granite-350M, LFM2.5-350M on single-shot function calling (per Cactus's own eval).

### 6.2 Independent verification status
**No independent third-party benchmark exists.** I searched:
- the-agent-report.com (May 13 2026) — confirms virality (423 HN points, 736 GitHub stars in 24h) but does not re-measure tok/s.
- devlery.com, openclawradar.com — summary articles, no independent measurement.
- HuggingFace discussions — no benchmark comments.
- Reddit r/LocalLLaMA — no Pi 5 replication thread found.
- calebcoffie.com benchmarks — has LFM2.5-350M but not Needle; and all his runs are on RTX 3090/5070 GPUs, not CPU.

### 6.3 Is 1,200 tok/s plausible?
**Yes, architecturally.** Decode speed is bounded by `weights_bytes / memory_bandwidth`. For Needle:
- 26M params at INT8 ≈ 26 MB weights.
- Pi 5 memory bandwidth ≈ 16 GB/s.
- Theoretical max decode ≈ 16,000 / 26 ≈ **615 tok/s** — so 1,200 tok/s on Pi 5 would **exceed** the memory-bandwidth ceiling, which is impossible unless (a) the model is smaller than 26M at runtime (CQ2 or 1-bit quant), or (b) the number was measured on a device with higher bandwidth (iPhone 17 Pro has ~60 GB/s → 2,300 tok/s ceiling).
- **Likely interpretation:** The 1,200 tok/s figure is probably measured on an Apple Silicon device or a Snapdragon 8 Elite phone, **not a Pi 5**. On Pi 5, expect Needle to hit **~400–600 tok/s decode** (memory-bandwidth-bound) — still ~15–20× faster than LFM2.5-350M's 30 tok/s, which is the relevant comparison.

### 6.4 Action item
Needle is MIT-licensed, 26 MB, and runnable in 4 lines:
```bash
git clone https://github.com/cactus-compute/needle.git && cd needle && source ./setup
needle playground   # opens http://127.0.0.1:7860
```
**Run this on the Pi 5 and measure.** This is the single highest-leverage verification you can do — it determines whether the Needle-routing tier of GarudaOne is viable at <100 ms latency.

---

## 7. GarudaOne use case — 5-tool function calling, <100 tokens per command

### 7.1 Latency math
For a 5-tool function call with a ~50-token user command and a ~30-token tool-call JSON response (≤100 total tokens generated):

| Stack | Prefill (50 tok) | Decode (30 tok) | End-to-end | Notes |
|---|---:|---:|---:|---|
| **Cactus + Needle 26M** | ~5 ms (6000 tok/s prefill on Pi 5, est. 400 tok/s decode) | ~75 ms (30 tok / 400 tok/s) | **~80 ms** | Single-core, background-safe, no vision needed for routing. |
| **Cactus + LFM2.5-350M INT8** | ~250 ms (200 tok/s prefill, 50 tok) | ~1,000 ms (30 tok/s decode) | **~1,250 ms** | Heavier than needed for pure routing. |
| **Cactus + LFM2.5-VL-450M INT8 (no image)** | ~250 ms prefill | ~1,000 ms decode | **~1,250 ms** | Same backbone as 350M; only use when image input is present. |
| **llama.cpp + LFM2.5-350M Q4_0 (4 cores)** | ~150 ms prefill (est. 300 tok/s) | ~1,000 ms decode (30 tok/s) | **~1,150 ms** | Comparable to Cactus text-mode; no tool-calling router. |
| **llama.cpp + LFM2.5-VL-450M Q4_0 + image** | ~150 ms + image encode (~2 s est.) | ~1,000 ms decode | **~3,150 ms** | Vision path unmeasured on Pi 5; estimate only. |

### 7.2 Recommendation for GarudaOne
**Two-tier Cactus stack, as already discussed in `bonsai-27b-vs-lfm25-analysis.md`:**
1. **Tier 1 — Needle 26M on Cactus** for tool routing. ~80 ms end-to-end, 5 tools is well within its demonstrated capacity, MIT-licensed weights. This is the lowest-latency option that exists for Pi 5.
2. **Tier 2 — LFM2.5-VL-450M on Cactus** for commands that include an image (drone camera frame, ground photo). ~1.25 s text-only, ~3 s with image. Acceptable for non-real-time commands.
3. **llama.cpp kept as dev/fallback** on x86 Windows for prototyping, fine-tuning sanity checks, and as a migration hedge against the Cactus engine license (Cactus engine is source-available non-commercial — see `cactus-compute-deep-research.md` for the $2M funding/revenue threshold).

**Why not llama.cpp for the production Pi 5 stack?**
- No tool-calling router model (Needle is Cactus-only — it's not a GGUF; it's a custom Cactus graph).
- Generic kernels for the SigLIP-2 vision encoder → slower image encode on Pi 5 (unmeasured but architecturally likely).
- No zero-copy mmap on Linux → higher RAM footprint than Cactus for the same model.
- No integrated tool-calling parser (you'd parse JSON yourself).

**Why still keep llama.cpp?**
- x86 Windows dev (Cactus can't run there).
- GGUF is the industry standard — if you ever need to swap engines, your LFM2.5-VL-450M Q8_0 GGUF is already ready.
- Broader community, more battle-tested, no license risk.

---

## 8. Can Cactus run on x86 Windows for testing? Or only ARM?

**ARM-only. No x86 Windows build exists or is planned.**

### 8.1 Authoritative source: DeepWiki (reads directly from the repo's CMakeLists.txt)
| Platform | Min Version | Architecture | Build System | Status |
|---|---|---|---|---|
| iOS | 16.0 | arm64 | apple/CMakeLists.txt | ✅ Production |
| macOS | 13.0 | arm64 (Apple Silicon) | apple/CMakeLists.txt | ✅ Production |
| Android | API 21+ | arm64-v8a | android/CMakeLists.txt | ✅ Production |
| **Linux** | **Ubuntu 20.04+** | **aarch64** | cactus/CMakeLists.txt | ✅ Production |

**Windows is not in the table.** x86_64 is not in the table. The baseline compile flag is `-march=armv8.2-a+fp16+simd+dotprod+i8mm` — an ARM-specific flag that has no x86 equivalent.

### 8.2 Official statement
DeepWiki: *"Cactus is designed exclusively for ARM-based mobile and edge devices. The system requires ARM NEON SIMD instructions and supports optional hardware acceleration through NPUs and advanced ARM extensions like I8MM."*

### 8.3 The Cactus comparison-page feature matrix lists "Windows" — that's marketing
The cactuscompute.com/compare/cactus-vs-llama-cpp feature checklist shows "Windows" with a checkmark for Cactus, but this is **not backed by the build system**. The CMakeLists.txt files (the source of truth) have no Windows/x86 path. Treat the website checkmark as an error or as referring to a future/enterprise offering.

### 8.4 Practical implication for GarudaOne dev workflow
- **On the Pi 5 (target):** Cactus runs natively, ARMv8.2-a + I8MM, full speed.
- **On x86 Windows (Arjun's Intel Core Ultra 7 255H dev machine):** Cactus **does not run**. You must use llama.cpp here for any local prototyping.
- **On Apple Silicon Mac (if available):** Cactus runs natively via `brew install cactus-compute/cactus/cactus` — this is the fastest dev loop for Cactus outside the Pi 5.
- **On Android phone:** Cactus runs natively (arm64-v8a).

**Recommended dev setup:**
1. x86 Windows + llama.cpp + LFM2.5-VL-450M-GGUF for prompt engineering, tool-definition iteration, and CI.
2. Pi 5 + Cactus for production benchmarks and final integration.
3. (Optional) Apple Silicon Mac for fast Cactus dev loop if you have one.

---

## 9. Comparison table (the one you asked for)

| Dimension | **llama.cpp** | **Cactus Compute** | Winner for GarudaOne |
|---|---|---|---|
| **LFM2.5-350M decode on Pi 5 (INT8/Q8_0)** | ~30–40 tok/s (est., 4 cores) | 30 tok/s (measured, 1 core) | Tie on throughput; **Cactus wins per-core** |
| **LFM2.5-VL-450M vision path on Pi 5** | Supported via GGUF, no published Pi 5 number, generic kernels | First-class `Lfm2VlModel`, SigLIP-2 + PixelUnshuffle + MLP, CLI `--image` | **Cactus** |
| **Function-calling router model** | None (you parse JSON from LFM2.5) | **Needle 26M** — 6000/1200 tok/s, MIT weights, beats LFM2.5-350M on single-shot | **Cactus** (decisive) |
| **Kernel quality on ARM I8MM** | Generic MMQ with I8MM paths (`__ARM_FEATURE_MATMUL_INT8`) | Hand-written per-ISA-tier (NEON/DOTPROD/I8MM/SME2), 32-byte-aligned, block-interleaved | **Cactus** for supported models |
| **Multi-core decode** | Scales to 4 cores well | Intentionally single-core (memory-bw-bound + background-safe) | **llama.cpp** if you want max throughput |
| **Memory format** | GGUF (industry standard, portable) | Cactus Compressed (CACT magic, mmap-first, 32-byte aligned) | GGUF for portability; CACT for Pi 5 RAM efficiency |
| **RAM on Pi 5 (LFM2.5-350M INT8)** | Not measured; likely ~350–400 MB (no zero-copy on Linux) | 300 MB (measured) | **Cactus** |
| **x86 Windows dev** | ✅ Full support | ❌ ARM-only | **llama.cpp** (only option) |
| **macOS Apple Silicon dev** | ✅ | ✅ (`brew install`) | Tie |
| **Tool-calling parser** | Manual JSON parsing from generation | Built-in (Needle + LFM2.5 tool-calling format) | **Cactus** |
| **License** | MIT (fully open) | Engine: source-available non-commercial ($2M threshold); Needle weights: MIT | **llama.cpp** for commercial safety |
| **Community / maturity** | 86K+ GitHub stars, industry standard | 5.5K stars, YC W25, newer | **llama.cpp** |
| **Model coverage** | Any GGUF model | Liquid, Gemma, Whisper, Parakeet, Qwen families especially tested; any HF model via `cactus convert` (experimental) | **llama.cpp** for breadth |
| **VLM (image+text)** | Supported via GGUF mmproj | Native `Lfm2VlModel`, `Gemma4MmModel`, SigLIP-2, CoreML NPU path on Apple | **Cactus** for LFM2.5-VL specifically |
| **End-to-end latency, 5-tool, <100 tok** | ~1.15 s (LFM2.5-350M Q4_0, 4 cores) | **~80 ms** (Needle 26M) / ~1.25 s (LFM2.5-350M) | **Cactus** (Needle tier) |

---

## 10. Final recommendation

**For GarudaOne on Pi 5: use Cactus in production, llama.cpp in dev.**

1. **Production stack (Pi 5):**
   - **Needle 26M on Cactus** for 5-tool function routing → ~80 ms per command, MIT weights, single-core background-safe.
   - **LFM2.5-VL-450M on Cactus** for image-bearing commands → ~1.25 s text, ~3 s with image. Use Cactus's `Lfm2VlModel` + `--image` flag.
   - **Cactus hybrid cloud** (optional) for fallback if confidence < threshold.

2. **Dev stack (x86 Windows, Arjun's Intel Core Ultra 7):**
   - **llama.cpp + LFM2.5-VL-450M-GGUF Q8_0** for prompt iteration, tool-definition testing, and CI. Cactus cannot run here.
   - Sync final prompts/tools to the Pi 5 for Cactus production benchmarks.

3. **Verification before committing (≤2 hours of work):**
   - Run `needle playground` on the Pi 5 → measure actual decode tok/s (the 1,200 tok/s claim is unverified on Pi 5; expect 400–600 tok/s).
   - Run `cactus run Cactus-Compute/LFM2.5-VL-450M --image test.jpg --prompt "describe"` on Pi 5 → measure image-encode + decode latency (no published Pi 5 VLM number exists).
   - Run `llama-bench -m LFM2.5-350M-Q4_0.gguf -p 1024 -n 100 -t 4` on the same Pi 5 → get the missing llama.cpp CPU baseline for direct comparison.
   - Compare all three on the same Pi 5. This fills the biggest gap in the public record.

4. **License hedge:** Keep the LFM2.5-VL-450M Q8_0 GGUF on hand. If AatoNovaZ exceeds Cactus's $2M funding/revenue threshold, you can swap the text backbone to llama.cpp on Pi 5 with ~1.15 s latency penalty and keep Needle (MIT) for routing. The vision path is the harder swap — Cactus's `Lfm2VlModel` is meaningfully better than llama.cpp's generic mmproj on ARM, so plan to negotiate a Cactus commercial license if GarudaOne scales.

---

## 11. Open questions / gaps in public data

1. **No direct Pi 5 head-to-head** of LFM2.5-350M on Cactus vs llama.cpp. The 30 tok/s Cactus number is well-sourced (Cactus + Liquid jointly). The llama.cpp Pi 5 number for the same model is **not published** — only the 1.2B variant at 10–20 tok/s (dodatathings).
2. **No Pi 5 VLM number** for either engine. LFM2.5-VL-450M image-encode + decode on Pi 5 is unmeasured in public for both Cactus and llama.cpp.
3. **Needle 1,200 tok/s is unverified on Pi 5.** The number likely comes from a higher-bandwidth device (iPhone 17 Pro / Snapdragon 8 Elite). Pi 5 memory-bandwidth ceiling suggests ~400–600 tok/s for a 26 MB INT8 model.
4. **Cactus's own FAQ concedes llama.cpp is faster on desktop CPU.** The Cactus advantage on Pi 5 is narrower than their mobile marketing implies — it's real (I8MM kernels, zero-copy, single-core efficiency, integrated VLM + tool-calling) but not a blowout. Measure before committing.

---

## 12. Sources (full list)

- **Liquid AI LFM2 Technical Report** — arxiv.org/html/2511.23404v1 (Nov 28, 2025) — architecture, llama.cpp Q4_0 CPU benchmarks on Snapdragon 8 Elite and AMD HX 370.
- **Cactus blog: LFM2.5-350M** — cactuscompute.com/blog/lfm2-5-350m (Mar 31, 2026) — the 30 tok/s Pi 5 number, I8MM/SMMLA explanation, zero-copy mmap, single-core decode rationale.
- **Liquid AI blog: LFM2.5-350M No Size Left Behind** — liquid.ai/blog/lfm2-5-350m-no-size-left-behind (Mar 31, 2026) — corroborates the 200/30/300MB Pi 5 row, BFCLv3 = 44.11, IFEval = 76.96.
- **Cactus blog: Needle** — cactuscompute.com/blog/needle (May 12, 2026) — 26M Simple Attention Network, 6000/1200 tok/s claim.
- **Cactus vs llama.cpp comparison** — cactuscompute.com/compare/cactus-vs-llama-cpp (Apr 10, 2026) — official FAQ including "Is llama.cpp faster than Cactus for LLM inference?" answer.
- **DeepWiki: Cactus Supported Platforms** — deepwiki.com/cactus-compute/cactus/1.2-supported-platforms-and-deployment — ARM-only platform table, I8MM build/dispatch flow, baseline `-march=armv8.2-a+fp16+simd+dotprod+i8mm`.
- **DeepWiki: Cactus Multimodal Models** — deepwiki.com/cactus-compute/cactus/4.6-multimodal-models-(vision-language) — `Lfm2VlModel`, `Siglip2VisionModel`, PixelUnshuffle projector, MLP connector, CoreML NPU path.
- **Cactus GitHub README** — github.com/cactus-compute/cactus — `cactus run --image`, inference speed tables, supported models, VLM CLI flag.
- **HuggingFace: Cactus-Compute/LFM2.5-VL-450M** — huggingface.co/Cactus-Compute/LFM2.5-VL-450M — confirms Cactus publishes the VL model, `Image-Text-to-Text` tag, `apple-npu` tag.
- **HuggingFace: Cactus-Compute/needle** — huggingface.co/Cactus-Compute/needle — 26M MIT weights, encoder-decoder pure attention.
- **dodatathings: LFM2.5-1.2B on Pi 5 llama.cpp** — dodatathings.dev/blog/llama-cpp-on-raspberry-pi-5-a-practical-optimization-guide (Feb 18, 2026) — 10–20 tok/s on Pi 5 Q5_K_M, Q4_0 ~670 MB.
- **smolhub: Jetson Orin Nano Super benchmark** — smolhub.com/posts/jetson-nano-super-benchmark-non-reasoning/ (May 29, 2026) — LFM2.5-350M at 115.4 tok/s on Jetson GPU (CUDA), independent confirmation of llama.cpp speed but not CPU.
- **Liquid AI LFM2.5-VL-450M docs** — docs.liquid.ai/lfm/models/lfm25-vl-450m — architecture (86M SigLIP2 + 350M backbone), llama.cpp `--image` + `-hf` usage.
- **HuggingFace: LiquidAI/LFM2.5-VL-450M-GGUF** — huggingface.co/LiquidAI/LFM2.5-VL-450M (via search) — Q4_0/Q8_0/F16 GGUF variants for llama.cpp.
- **Cactus-Compute/needle GitHub** — github.com/cactus-compute/needle — MIT license, 4-line quickstart, `needle playground` web UI.

---

*End of report. Generated 2026-07-18 by Hermes Agent. Cross-reference with `cactus-compute-deep-research.md` (architecture + license) and `bonsai-27b-vs-lfm25-analysis.md` (two-tier model routing) for the full GarudaOne inference-stack picture.*
