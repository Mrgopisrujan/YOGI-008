# Cactus Compute — Deep Research Report

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - Needle 2 (45M, `cactus-needle==2.0.0`) replaced Needle 26M as the active constrained router.
> - Local voice transport is integrated; the exact STT bundle still requires target-Pi qualification.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - Land/RTL mode transfer requires PX4 ACK and heartbeat confirmation; physical behavior remains unqualified.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!NOTE]
> This is a dated research snapshot. Model choices, estimates, and recommendations are not implementation claims. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


**Prepared for:** GarudaOne DroneOS (Raspberry Pi 5, 8 GB, CPU-only, ARM64)
**Date:** 2026-07-18
**Sources:** cactuscompute.com, github.com/cactus-compute/{cactus,needle}, huggingface.co/Cactus-Compute, pypi.org/project/cactus-compute, docs.cactuscompute.com, GitHub Issues, agentry.press tutorial, Reddit r/LocalLLaMA
**Researcher:** Hermes Agent (subagent)

---

## TL;DR — Executive Summary for GarudaOne

Cactus Compute is a **YC-backed** (W25 batch) startup building a hybrid edge-cloud AI inference engine explicitly designed for **ARM mobile/wearable/edge** devices. The engine is written in C++ with hand-tuned **ARM NEON SIMD + DOTPROD + I8MM + SME2** kernels and a proprietary post-training quantization called **Cactus Quants (CQ)** that works from 4-bit down to **1-bit**. It targets **ARMv8.2-A and later** — which means **the Raspberry Pi 5 is officially supported** (Cortex-A76, ARMv8.2-a, with DOTPROD and I8MM). The Pi 4 (ARMv8.0) is *not* supported ("Illegal instruction" at runtime, per issue #768).

**Needle 26M** is their flagship tiny model: a 26 M-parameter encoder-decoder "Simple Attention Network" (no FFN layers) distilled from Gemini 3.1 for single-shot function calling. MIT-licensed weights, runs at **6000 tok/s prefill / 1200 tok/s decode** on Cactus on consumer hardware. On a **Raspberry Pi 5, LFM2.5-350M (355 MB, INT8) hits 200 tok/s prefill / 30 tok/s decode** — so Needle (10× smaller, ~50 MB) should comfortably exceed those numbers.

**Critical license finding:** The **Cactus *engine* is NOT OSI-open-source**. It uses a custom non-commercial source-available license: free for individuals/edu/non-profits, or companies with **both** <$2 M total funding **and** <$2 M annual revenue; otherwise a commercial license is required (contact founders@cactuscompute.com). The **Needle model + weights + needle repo are MIT-licensed** (truly open, commercial-use OK). AatoNovaZ (GarudaOne) at ₹20 L (~$24 K) funding is **well under the $2 M threshold**, so the engine is usable today, but the license auto-terminates if either funding or revenue exceeds $2 M.

**Bottom line for GarudaOne:** Cactus is **architecturally ideal** for the Pi 5 and likely **faster than llama.cpp for Needle** (custom NEON/I8MM kernels, zero-copy mmap, CQ quantization vs generic GGUF). The hybrid cloud routing is a perfect fit for the "Needle routes, LFM2.5-VL handles complex" two-tier architecture. The license is the main caveat — viable now, but plan for a commercial license if GarudaOne scales.

---

## 1. Cactus Engine — Full Architecture

Cactus is a **5-layer stack**, each layer independently replaceable. From the README and docs (`docs/cactus_engine.md`, `docs/cactus_graph.md`, `docs/cactus_kernels.md`):

```
┌─────────────────┐
│  Cactus Engine  │  ← OpenAI-compatible C FFI APIs for text, speech, vision
└─────────────────┘     (chat, tool calling, transcription, embeddings, RAG, cloud handoff)
         │
┌─────────────────┐
│  Cactus Graph   │  ← Zero-copy computation graph ("PyTorch for mobile")
└─────────────────┘     Custom ops optimized for RAM + quantization
         │
┌─────────────────┐
│ Cactus Kernels  │  ← C++ ARM NEON SIMD kernels (matmul, attention, conv, quant, DSP, image)
└─────────────────┘
         │
┌─────────────────┐
│ Cactus Quants   │  ← Rotation-and-codebook PTQ, 4-bit → 1-bit, all weight tensors
└─────────────────┘
         │
┌─────────────────┐
│Cactus Transpiler│  ← PyTorch (or JAX/Flax) → Cactus runtime graph
└─────────────────┘
```

### 1.1 Cactus Engine (C FFI layer)
- Pure C ABI (`cactus_engine.h`) so it binds to Swift, Kotlin, Flutter, React Native, Python, Rust.
- Handles: chat completion, streaming, tool calling (OpenAI function-calling JSON), transcription (Whisper + Parakeet TDT), embeddings (text/image/audio), RAG with on-device vector index, **automatic cloud handoff**.
- The single entry point `cactus_complete()` returns a JSON dict with `success`, `response`, `function_calls`, `confidence`, `confidence_threshold`, `cloud_handoff`, and full timing telemetry (`prefill_tps`, `decode_tps`, `ram_usage_mb`, `time_to_first_token_ms`).
- Supports PCM audio input inline (for audio chat / live transcription).

### 1.2 Cactus Graph (C++ computation graph)
- A lazy dataflow graph of typed tensor ops: `matmul`, `transpose`, `input`, `set_input`, `execute`, `get_output`.
- Supports FP16, INT8, CQ1–CQ4 precisions.
- Constants become either `mmap_weights()` (zero-copy, disk-backed) or inline tensors.
- Acts as "PyTorch for mobile" — the transpiler lowers PyTorch FX graphs into this.

### 1.3 Cactus Kernels (C++ ARM SIMD)
- **Hand-tuned ARM NEON SIMD** implementations of every core op. Default compute precision is **FP16 (`__fp16`)**.
- Designed for mobile ARM chips: Apple Silicon, Snapdragon, Exynos, Google Tensor, **ARMv8/v9 CPUs**.
- Kernel categories (from `cactus_kernels.h`): element-wise arithmetic (+ broadcast + scalar ops), reductions, **FP16 + CQ 1–4 bit matmul** (GEMV + GEMM), attention (FP16 + hybrid INT8/FP16 KV-cache), normalization (RMSNorm, LayerNorm, BatchNorm, Softmax), positional encoding (RoPE + GPT-J RoPE), activations (ReLU, SiLU, GELU, sigmoid, tanh, GLU, clamp), **1D/2D convolution** (incl. depthwise, pointwise, causal), **recurrent** (LSTM cell, BiLSTM, **Gated DeltaNet** decode/prefill), sampling (top-k/top-p/min-p/repetition penalty), **DSP** (RFFT, mel filter bank, spectrogram — for speech), **image processing** (load/resize/normalize/patches), precision conversion, **KV-cache quantization (FP16→INT8, group=32)**.
- Kernel source layout: `cactus-kernels/src/{attention,attention_hybrid,blas,conv,conv2d,dsp,fused,image,lstm,matmul,nn,norms_rope,quants,reduce,scalar}.cpp`.

### 1.4 Cactus Quants (CQ)
- See **§4** below for full detail.

### 1.5 Cactus Transpiler
- 6-stage compiler: **(1) Canonicalize** (wrap in task adapter: causal_lm, multimodal, encoder, ctc, seq2seq, tdt) → **(2) torch.export** (capture FX graph of ATen ops, no Python control flow) → **(3) Import to IR** (FX nodes → `IRGraph`/`IRNode`/`IRValue`, resolve weights via `weights_manifest.json`) → **(4) Canonicalize IR** (rename, permute, constant-fold, FP16 casts, DCE) → **(5) Fuse patterns** (RMSNorm, RoPE, attention, MLP, conv+BN+act, LSTM) → **(6) Lower to CactusGraph** (IRNode → graph ops, constants → `mmap_weights`).
- Key design choice: **dispatches on ATen op names, not layer names** — so fusion works on any model producing the same compute pattern regardless of code organization.
- Also supports **JAX/Flax** models via `capture_jax.py` + `JaxGraphSpec` (this is how Needle, a Flax model, is bundled).
- Tested model-family adapters: **Gemma 3/4, Qwen 3/3.5, LFM2/2.5, Whisper, Parakeet CTC, Parakeet TDT**.

### 1.6 Python bindings
- `cactus-compute` PyPI package (current: **v2.0.1**), ctypes FFI wrapping the C engine.
- Auto-installed via `source ./setup` in the repo; also `pip install cactus-compute`.
- Module-level functions mirror the C FFI: `cactus_init`, `cactus_complete`, `cactus_transcribe`, `cactus_embed`, `cactus_image_embed`, `cactus_audio_embed`, `cactus_prefill`, `cactus_tokenize`, `cactus_score_window`, `cactus_rag_query`, vector index (`cactus_index_*`), streaming transcription (`cactus_stream_transcribe_*`).
- Graph API also exposed: `from cactus.bindings.cactus import Graph`.

---

## 2. Models Offered (HuggingFace `Cactus-Compute` org)

The HF org publishes **50 models** (queried via `huggingface.co/api/models?author=Cactus-Compute`). These split into two tiers:
- **Base converted weights** (full HF-format models, downloadable by anyone) — carry the *upstream* license.
- **Pre-built CQ bundles** (suffix `-cq`) — Cactus's quantized runtime bundles, usable only with the Cactus engine.

### 2.1 Function-calling / agent routers (the "tiny" tier)
| Model | Params | License | Purpose |
|---|---|---|---|
| **Cactus-Compute/needle** | 26 M | **MIT** | Single-shot tool calling (distilled from Gemini 3.1). 874 downloads, 260 likes. JAX/Flax, safetensors. 4 finetunes + 4 quantizations in tree. |
| Cactus-Compute/needle-hf | 26 M | (HF format port) | Needle in HF Transformers-compatible format (338 dl). |
| Cactus-Compute/needle-pebble-ft | — | — | Official Needle finetune ("pebble"), updated 5 days ago. |
| Cactus-Compute/functiongemma-270m-it | 270 M | Gemma | Function calling baseline (what Needle beats). |
| Cactus-Compute/gemma-3-270m-it | 270 M | Gemma | Small Gemma 3. |

### 2.2 LLMs (text generation)
| Model | Params | License |
|---|---|---|
| Cactus-Compute/LFM2-8B-A1B | 8 B (MoE, 1 B active) | Liquid "other" |
| Cactus-Compute/LFM2-2.6B | 2.6 B | Liquid "other" |
| Cactus-Compute/LFM2.5-1.2B-Instruct / -Thinking | 1.2 B | Liquid "other" |
| Cactus-Compute/LFM2-1.2B / -RAG / -Tool | 1.2 B | Liquid "other" |
| Cactus-Compute/LFM2.5-VL-1.6B | 1.6 B (VLM) | Liquid "other" |
| Cactus-Compute/Qwen3-1.7B / Qwen3.5-2B | 1.7–2 B | Apache-2.0 |
| Cactus-Compute/Qwen3-0.6B / Qwen3.5-0.8B | 0.6–0.8 B | Apache-2.0 |
| Cactus-Compute/gemma-3-1b-it, gemma-3n-E2B/E4B-it | 1–4 B | Gemma |
| Cactus-Compute/gemma-4-E2B-it, gemma-4-E4B-it, gemma-4-26B-A4B-it | 2–26 B | Apache-2.0 |
| Cactus-Compute/LFM2.5-350M, LFM2-350M, LFM2-700M | 350–700 M | Liquid "other" |
| Cactus-Compute/Youtu-LLM-2B | 2 B | "other" |
| Cactus-Compute/Qwen3-VL-2B-Instruct-cq | 2 B (VLM) | Apache-2.0 |

### 2.3 Vision-language models (VLMs)
- **Cactus-Compute/LFM2-VL-450M** and **LFM2.5-VL-450M** — 450 M VLMs (relevant to GarudaOne's LFM2.5-VL-450M use).
- **Cactus-Compute/LFM2.5-VL-1.6B** — 1.6 B VLM.
- **Cactus-Compute/gemma-4-E2B-it** (image-text-to-text) — the headline multimodal model Cactus benchmarks on.
- **Cactus-Compute/Qwen3.5-0.8B / Qwen3.5-2B** — Qwen VL.
- Pre-quantized VLM bundles: `LFM2.5-VL-450M-cq`, `LFM2.5-VL-1.6B-cq`, `Qwen3-VL-2B-Instruct-cq`.

### 2.4 Speech (ASR / transcription)
| Model | Size | License |
|---|---|---|
| Cactus-Compute/parakeet-tdt-0.6b-v3 | 0.6 B | CC-BY-4.0 |
| Cactus-Compute/parakeet-ctc-1.1b | 1.1 B | CC-BY-4.0 |
| Cactus-Compute/parakeet-ctc-0.6b | 0.6 B | CC-BY-4.0 |
| Cactus-Compute/whisper-tiny/base/small/medium/large-v3 | 39 M–1.5 B | Apache-2.0 |
| Cactus-Compute/moonshine-base | — | MIT |
| Cactus-Compute/silero-vad | — | MIT (voice activity detection) |
| Cactus-Compute/whisper-large-v3-cq | pre-quantized bundle | Apache-2.0 |

### 2.5 Embeddings, speaker ID, segmentation
| Model | License | Purpose |
|---|---|---|
| Cactus-Compute/nomic-embed-text-v2-moe | Apache-2.0 | Text embeddings |
| Cactus-Compute/Qwen3-Embedding-0.6B | Apache-2.0 | Text embeddings |
| Cactus-Compute/wespeaker-voxceleb-resnet34-LM | CC-BY-4.0 | **Speaker identification/verification** |
| Cactus-Compute/segmentation-3.0 | MIT | **Segmentation model** |

### 2.6 Gemma 4 grouped-attention experiments
- `gemma4-e2b-grouped-k96`, `grouped-k192`, `grouped-k192-router` — research variants.

### 2.7 Pre-built CQ bundles (suffix `-cq`)
- `gemma-4-e2b-it-cq`, `LFM2.5-VL-450M-cq`, `LFM2.5-VL-1.6B-cq`, `Qwen3-VL-2B-Instruct-cq`, `Qwen3-0.6B-cq`, `whisper-large-v3-cq`.
- These are the ones you fetch with `cactus download <name>` and load directly with `cactus_init()`.

---

## 3. ARM NEON SIMD Kernel Details & Pi 5 Performance

### 3.1 What's optimized
From `docs/cactus_kernels.md`, every performance-critical op has a hand-tuned NEON path:
- **Matmul**: FP16 GEMM (`cactus_matmul_f16`) + **CQ 1/2/3/4-bit GEMV and GEMM** with Hadamard-rotated activations, codebook lookup, fused norm-scale.
- **Attention**: FP16 attention with GQA, sliding window, additive masks, logit soft-capping; **hybrid INT8/FP16 attention** for KV-cache (FP16 new tokens vs INT8 cached keys/values, per-group dequant scales, group_size=32).
- **Normalization**: RMSNorm, LayerNorm, BatchNorm, Softmax.
- **RoPE**: standard + GPT-J variant.
- **Activations**: ReLU, SiLU, GELU (exact + erf), sigmoid, tanh, GLU, clamp.
- **Conv**: 1D (incl. causal depthwise, pointwise via GEMM) and 2D (3×3 s1/s2, depthwise, pointwise) — for vision towers and Conformer encoders.
- **Recurrent**: LSTM, BiLSTM, **Gated DeltaNet** (decode + prefill) — for LFM hybrid models.
- **DSP**: RFFT, IRFFT, mel filter bank, spectrogram — the full speech front-end.
- **Image**: load (JPEG/PNG/BMP via stb_image), resize, normalize, **ViT patch extraction**.
- **Sampling**: top-k/top-p/min-p/repetition penalty, logit bias.
- **KV-cache quant**: FP16→INT8 with group=32.

### 3.2 ISA extension tiers
The kernels dispatch across ARM ISA generations (from `blog/lfm2.5_350m.md`):
- **NEON** (baseline ARMv8-A) — 128-bit SIMD, FP16 vector ops.
- **DOTPROD** (`UDOT`/`SDOT`) — 4-element INT8 dot products, ARMv8.1-a.
- **I8MM** (`SMMLA`) — **2×8 by 8×2 INT8 mat-mul in a single instruction accumulating into INT32**, ARMv8.2-a. "Native hardware operation, not software emulation."
- **SME2** — streaming matrix ops approaching accelerator-class INT8 efficiency, ARMv9.2-a (upcoming).

Cactus **writes a dedicated kernel path per ISA tier** and profiles every major ARM variant (Apple, Qualcomm, MediaTek, Samsung, Broadcom).

### 3.3 Why CPU, not GPU/NPU (from the LFM2.5-350M blog)
- **Decode is memory-bandwidth-bound, not compute-bound.** For a 350 M INT8 model, each decode step reads ~355 MB of weights to produce 1 token. Adding cores doesn't add bandwidth.
- On iPhone 17 Pro (~60 GB/s memory bandwidth), the theoretical max decode is ~169 tok/s; Cactus measures **140 tok/s = 83% of ceiling**.
- **Single-core decode** is deliberate: avoids OS background-throttling (iOS suspends multi-core background tasks; Android caps perf-core frequency). Single-core decode "looks like a lightweight background task" — survives thermal throttling.
- **Prefill is compute-bound** (1024 tokens amortize weight loads 1024×), so Cactus uses **multi-threaded prefill** (Vision Pro hits 2,067 tok/s prefill using all cores).
- GPUs are energy-inefficient on battery; mobile GPU requires Metal + Vulkan/OpenCL dual codepaths; NPUs (ANE/Hexagon) lock you into vendor formats with limited quantization.

### 3.4 Raspberry Pi 5 — explicit benchmark
From `blog/lfm2.5_350m.md` (date 2026-03-31), benchmarking **LFM2.5-350M, INT8, 1024-token prefill, 100-token decode, single-core decode, CPU-only**:

| Device | Prefill (tok/s) | Decode (tok/s) | RAM |
|---|---|---|---|
| Vision Pro | 2,067 | 140 | 85 MB |
| iPhone 17 Pro | 797 | 140 | 75 MB |
| iPhone 13 Mini | 496 | 88 | 56 MB |
| Galaxy S25 Ultra | 660 | 100 | 322 MB |
| Google Pixel 6a | 208 | 42 | 328 MB |
| Galaxy A56 | 110 | 24 | 330 MB |
| **Raspberry Pi 5** | **200** | **30** | **300 MB** |

**Pi 5 specifics:** 200 tok/s prefill, 30 tok/s decode, 300 MB RAM for a 355 MB INT8 model. The blog notes "even the Raspberry Pi's 30 tok/sec is well ahead of human consumption" (~4-5 words/sec reading speed). The 300 MB RAM (vs 75 MB on Apple) is due to Android/Linux mmap behavior — the kernel copies mmap pages into anonymous memory rather than keeping them file-backed.

### 3.5 Extrapolation for Needle 26M on Pi 5
Needle is **~13× smaller** than LFM2.5-350M (26 M vs 350 M params). Decode is memory-bandwidth-bound (reads all weights per token), so Needle's weight read per token is ~13× smaller. **Naïve extrapolation: Pi 5 decode for Needle ≈ 30 × (350/26) ≈ 400 tok/s.** Cactus claims **1200 tok/s decode** for Needle on "consumer hardware" (likely Apple Silicon) and **6000 tok/s prefill**. On Pi 5, expect roughly **300–600 tok/s decode and ~2,000–3,000 tok/s prefill** — more than enough for real-time command routing on a drone.

---

## 4. Custom Quantization (CQ) — How It Works

CQ = **Cactus Quants**, a post-training quantization (PTQ) system. Full detail from `docs/cactus_quants.md`.

### 4.1 The problem CQ solves
Existing PTQ methods (GPTQ, AWQ, HQQ) have three failures:
1. **Only quantize linears** — leave per-layer embeddings, vision/audio towers, cross-modal bridges at FP16. In Gemma 4 E2B, per-layer embeddings alone are **60% of the model**.
2. **Break below 4 bits** — 15-30 point drops at 3-bit; near-random at 2-bit.
3. **Don't handle embeddings** — embeddings are gathered by token ID, not multiplied by activations, so Hessian-based methods (GPTQ/AWQ) have no signal.

CQ applies **one unified recipe to every weight tensor** — transformer linears, vision encoders, audio encoders, cross-modal bridges, per-layer embeddings, shared token embeddings — at **1, 2, 3, or 4 bits**.

### 4.2 The recipe: rotation + codebook
From `docs/cactus_kernels.md` (`CactusQuantMatrix` struct) and the quants doc:
- **Hadamard rotation** (or orthogonal rotation) applied to the **FP16 activation** (not the weight) at inference — this concentrates outlier weight energy.
- **Per-group codebooks**: weights divided into groups (group_size configurable, e.g. 128); each group gets a codebook + scale + norms.
- Packed indices (`uint8_t*`), left/right signs (`int8_t*`), permutation, rotation matrix, expanded representation, F32 norms.
- At inference, the kernel does a **fused Walsh-Hadamard transform → codebook lookup → norm-scale → matmul in a single NEON pass** (`cactus_quant_4bit_gemv`, `cactus_quant_4bit_gemm`, … `cactus_quant_1bit_*`, plus orthogonal variants).
- Embedding dequantization has dedicated paths (`cactus_quant_dequantize_hadamard_embedding_row`, `_orthogonal_embedding_row`).

### 4.3 Bit levels
The CLI flag `--bits 1|2|3|4|2.54|3.26`:
- **CQ4** (4-bit): competitive with GPTQ-4/AWQ-4/HQQ-4. Near-lossless.
- **CQ3.26** (mixed-precision, ~3.26 avg bits): allocate 4-bit to 68 high-sensitivity LLM units + 3-bit to remaining 207. Costs ~2 pts vs uniform CQ4. **The sweet spot.**
- **CQ3** (uniform 3-bit): CQ dominates — sweeps all 8 text metrics on Gemma 4 with up to **+32 point margins** (GSM8K 52.67 vs GPTQ 16.40; HumanEval 45.12 vs 8.54).
- **CQ2.54** (mixed ~2.54 bits): promoting 25% of tensors from 2→3 bits recovers ~75% of the CQ2→CQ3 gap.
- **CQ2** (uniform 2-bit): CQ is **the only survivor**. GPTQ/AWQ/HQQ all collapse to near-random; CQ retains 50.8 ARC-E, 33.2 MMLU, 18.75 BFCL-Simple.
- **CQ1** (1-bit): defined in the `Precision` enum and kernels (`cactus_quant_1bit_gemv/gemm`); production use is rare but supported.

### 4.4 Function-calling preservation (relevant to GarudaOne)
| Setting | CQ | GPTQ | AWQ | HQQ |
|---|---|---|---|---|
| 4-bit BFCL Parallel-Multi (Gemma 4) | **83.33** | 80.33 | 80.50 | 81.00 |
| 3-bit BFCL Parallel-Multi | **79.67** | 38.83 | 31.33 | 0.00 |
| 2-bit BFCL Parallel-Multi | **1.33** | 0.00 | 0.00 | 0.00 |

At 3-bit, CQ retains near-FP16 function calling while baselines lose 40-80 points. At 2-bit, all methods fail function calling (long-horizon coherence breaks).

### 4.5 Production bundle for Gemma 4 E2B
| Component | Bits | Rationale |
|---|---|---|
| LLM linears | 4 | Accuracy-sensitive |
| Per-layer embeddings (PLI) | 2 | 60% of model, 7.5× compression |
| Shared token embeddings | 4 | Small, accuracy-sensitive |
| Vision tower | 2 | Compresses gracefully |
| Audio tower | 2 | Holds understanding, some WER cost |

**Result: 4.79 GB FP16 → ~0.9 GB on disk (5.3× reduction) at ~3.0 bits-per-weight.** Matches or beats Unsloth UD-Q2_K_XL (~3.4 bpw) on 10/12 metrics despite a tighter bit budget.

### 4.6 Multimodal (vision + audio)
Under joint (M, L) schedule (M = modality-tower bits, L = LLM bits):
- **M2 + L4 ChartQA**: CQ 48.44 vs AWQ 14.22 vs HQQ 14.33 (CQ retains vision at 2-bit tower).
- **Parakeet-1.1B 2-bit WER**: CQ 0.147 vs GPTQ 1.043 (baselines collapse to ≥1.0).
- **Audio at 2-bit modality tower**: LibriSpeech WER degrades 5.9 → 10.4 (the main weakness — concentrated in acoustic decoding, not reasoning).

---

## 5. Python API — How to Load & Run

### 5.1 Install
```bash
# Option A: from source (needed on Pi 5/Linux — no brew tap there)
sudo apt-get install python3.12 python3.12-venv python3-pip cmake build-essential libcurl4-openssl-dev
git clone https://github.com/cactus-compute/cactus && cd cactus
source ./setup            # creates venv, installs cactus-compute PyPI pkg + builds native libs
cactus build --python     # build shared lib for Python FFI

# Option B: pip only (Mac, pre-built)
brew install cactus-compute/cactus/cactus
pip install cactus-compute
```

### 5.2 Quickstart — chat completion
```python
from cactus import ensure_model, cactus_init, cactus_complete, cactus_destroy
import json

# Downloads pre-built CQ bundle from HF if not present
bundle = ensure_model("LiquidAI/LFM2-VL-450M")
model = cactus_init(str(bundle), None, False)   # (model_path, corpus_dir, cache_index)

messages = json.dumps([{"role": "user", "content": "What is 2+2?"}])
result = cactus_complete(model, messages, None, None, None)
print(result["response"])
cactus_destroy(model)
```

### 5.3 Tool calling (the GarudaOne use case)
```python
tools = json.dumps([{
    "type": "function",
    "function": {
        "name": "fly_to",
        "description": "Fly the drone to a GPS coordinate",
        "parameters": {
            "type": "object",
            "properties": {"lat": {"type":"number"}, "lon": {"type":"number"}, "alt":{"type":"number"}},
            "required": ["lat", "lon"]
        }
    }
}])
messages = json.dumps([{"role":"user","content":"Fly to 37.7749, -122.4194 at 50 meters"}])
result = cactus_complete(model, messages, None, tools, None)
print(result["function_calls"])
# [{"name": "fly_to", "arguments": {"lat": 37.7749, "lon": -122.4194, "alt": 50}}]
```

### 5.4 Hybrid cloud handoff
```python
options = json.dumps({"confidence_threshold": 0.7, "auto_handoff": True, "cloud_timeout_ms": 15000})
result = cactus_complete(model, messages, options, None, None)
if result["cloud_handoff"]:
    print("Answered by cloud (local confidence was %.2f)" % result["confidence"])
```

### 5.5 Vision (VLM) + audio multimodal
```python
messages = json.dumps([{
    "role": "user",
    "content": "Describe this image and transcribe the audio.",
    "images": ["/path/to/photo.jpg"],
    "audio": ["/path/to/audio.wav"]
}])
result = cactus_complete(model, messages, None, None, None)
```

### 5.6 Streaming transcription (live mic)
```python
stream = cactus_stream_transcribe_start(model, {"language": "en"})
for chunk in pcm_chunks:  # 16 kHz mono 16-bit PCM
    out = cactus_stream_transcribe_process(stream, chunk)
    transcript += out["confirmed"]     # finalized words — append
    live_preview = out["pending"]      # volatile tail — replace each call
final = cactus_stream_transcribe_stop(stream)["confirmed"]
```

### 5.7 Embeddings + on-device RAG
```python
emb = cactus_embed(model, "search query", normalize=True)
idx = cactus_index_init("./rag_index", len(emb))
cactus_index_add(idx, [1], ["doc text"], [None], [emb])
results = cactus_index_query(idx, emb, {"top_k": 5})
```

### 5.8 Compute graph (custom models)
```python
from cactus.bindings.cactus import Graph
import numpy as np
g = Graph()
a = g.input((2,2)); b = g.input((2,2))
y = ((a - b) * (a + b)).abs().pow(2.0).view((4,))
g.set_input(a, np.array([[2,4],[6,8]], dtype=np.float16))
g.set_input(b, np.array([[1,2],[3,4]], dtype=np.float16))
g.execute(); print(y.numpy())  # [9. 144. 729. 2304.]
```

### 5.9 CLI (often faster to iterate)
```bash
cactus run Cactus-Compute/needle --tools my_tools.json
cactus run LiquidAI/LFM2.5-VL-450M --image photo.jpg --prompt "What do you see?"
cactus transcribe nvidia/parakeet-tdt-0.6b-v3 --file audio.wav
cactus serve LiquidAI/LFM2.5-VL-450M --port 8080   # OpenAI-compatible HTTP server
cactus benchmark --model google/gemma-4-E2B-it --bits 4
cactus convert <hf-model> ./bundle --bits 4         # quantize + build graph
```

---

## 6. Hybrid Edge-Cloud Routing — How It Decides

From `docs/cactus_hybrid.md`. This is one of Cactus's most distinctive features and directly matches GarudaOne's "Needle routes, LFM2.5-VL handles complex" architecture.

### 6.1 The probe
A **~65 k-parameter** probe network is attached to the local model's **hidden states** (post-generation, post-fusion). It emits a single scalar: **P(this generation is wrong)**.

- Reads hidden states directly — far richer signal than output token probabilities.
- **Negligible latency** (65 k params, runs after generation completes).
- **Modality-agnostic**: reads post-fusion hidden states where text/vision/audio are already merged. Trained on text + vision only, yet achieves **0.79–0.88 AUROC on audio benchmarks with zero audio training** (cross-modality transfer).
- **Quantization-robust**: same probe checkpoint works at FP16, 4-bit, 3-bit — no per-quant retraining.

### 6.2 Decision rule
At each completion:
1. Local model generates.
2. Probe emits `confidence` ∈ [0,1].
3. If `confidence < confidence_threshold` → **route to cloud** (Gemini Pro / Claude / GPT-4 via Cactus Cloud API key).
4. Response JSON includes `cloud_handoff: true/false` + the resolved threshold + timing.

`confidence_threshold` resolution order:
1. `0.5` if the bundle ships a `handoff_probe.bin` (the trained probe);
2. else the model's `default_cloud_handoff_threshold` (Gemma 4 = `0.81`);
3. else `0.7` (fallback).

Tunable per-request via `options.confidence_threshold` and `auto_handoff: true/false`.

### 6.3 Why not token entropy?
Token entropy is **anti-predictive** on transcription and vision MCQ — high entropy often means the model is considering multiple valid candidates, not that it's wrong. The probe outperforms token entropy on **every** one of 12 hold-out benchmarks:
- Mean probe AUROC: **0.814** vs token entropy **0.549**.
- On audio (GigaSpeech): probe **0.876** vs entropy **0.343** (entropy routes the *right* answers to cloud, keeps wrong ones local).
- On vision (MMBench): probe **0.840** vs entropy **0.435**.

### 6.4 How much handoff is needed
At FP16, hybrid matches Gemini 3.1 Flash-Lite accuracy on most benchmarks by routing **15–35%** of queries to cloud:
| Benchmark | Handoff @FP16 | @4-bit | @3-bit |
|---|---|---|---|
| ChartQA | 15–20% | 25–30% | 40–50% |
| MMBench | 30–35% | 40–45% | 50–55% |
| LibriSpeech | 25–30% | 35–40% | 55–65% |
| MMLU-Pro | 45–55% | ~90% | n/a |

### 6.5 Probe architecture
**Learned-query attention pool + MLP** (mean AUROC 0.814) > Mean pool + MLP (0.781) > Linear/logistic (0.773) > Token entropy (0.549). The attention pool opens a gap on long-generation modalities (audio +6 pts on MMAU) and loosely-structured tasks (MMLU-Pro +9 pts).

### 6.6 Weaknesses
1. **When the local model is broken** (MMLU-Pro at 4-bit: local accuracy 0.28) — probe AUROC → 0.5 (no signal).
2. **When the cloud target is worse** (DocVQA, GSM8K: Gemini Pro < Flash-Lite).
3. **High-handoff regime (>50%)** — marginal value over random routing narrows.

### 6.7 Setup
```bash
cactus auth          # set Cactus Cloud API key
cactus serve <model> --confidence-threshold 0.7 --cloud-timeout-ms 15000
```
Disable with `--no-cloud-handoff` or `auto_handoff: false`.

**GarudaOne fit:** This is exactly the two-tier routing GarudaOne wants. Needle (or a finetune) runs locally as the fast router; when probe confidence drops (complex visual command, ambiguous instruction), Cactus transparently hands off to LFM2.5-VL-450M (or a cloud model if you want a 3-tier system). No need to write a custom router — the probe is built in.

---

## 7. Running Needle 26M on Pi 5 ARM64 — Specific Steps

### 7.1 Pi 5 hardware check
- Pi 5 = **Broadcom BCM2712, 4× Cortex-A76 @ 2.4 GHz, ARMv8.2-A**.
- Supports **DOTPROD** (ARMv8.1-a) and **I8MM** (ARMv8.2-a) — the exact ISA extensions Cactus's fastest kernels use.
- ✅ **Officially supported.** Issue #768 ("build: fail early on unsupported (non-ARM64) targets") confirms: "ARMv8.0 CPUs such as the Raspberry Pi 4 … hits Illegal instruction at runtime (#561), because the engine is ARM64 v8.2+ by design." The Pi 4 is out; the **Pi 5 is in**.

### 7.2 Steps (Linux/ARM64, from source)
```bash
# 1. OS deps (Pi OS 64-bit / Ubuntu 24.04 ARM64)
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip cmake build-essential libcurl4-openssl-dev git

# 2. Clone + setup (builds native libs for ARM64)
git clone https://github.com/cactus-compute/cactus && cd cactus
source ./setup                       # creates venv, pip installs cactus-compute, builds libacactusengine.so

# 3. (Optional) force a rebuild if setup didn't trigger it
cactus build --python

# 4. Run Needle (downloads the pre-built CQ bundle from HF on first run)
cactus run Cactus-Compute/needle --tools my_drone_tools.json

# 5. Or via Python
python -c "
from cactus import ensure_model, cactus_init, cactus_complete
import json
bundle = ensure_model('Cactus-Compute/needle')
model = cactus_init(str(bundle), None, False)
tools = json.dumps([{'type':'function','function':{'name':'arm','description':'Arm the drone','parameters':{'type':'object','properties':{}}}}])
msgs = json.dumps([{'role':'user','content':'Arm the drone for takeoff'}])
r = cactus_complete(model, msgs, None, tools, None)
print(r['function_calls'])
"
```

### 7.3 Needle has TWO run paths
1. **Via Cactus engine** (above) — `cactus run Cactus-Compute/needle`. This uses CQ quantization + NEON kernels + mmap. **Fastest path.**
2. **Via the Needle repo's native Python/JAX** — `git clone https://github.com/cactus-compute/needle && cd needle && source ./setup && needle run --query "..." --tools '[...]'`. This runs the Flax model directly (no Cactus engine). Useful for finetuning (`needle playground` opens a Gradio UI at :7860). Weights are auto-downloaded.

### 7.4 Finetuning Needle for GarudaOne's drone tools
Needle's own repo is the finetuning path (the Cactus engine itself does not finetune):
```bash
git clone https://github.com/cactus-compute/needle && cd needle && source ./setup
needle playground       # web UI at http://127.0.0.1:7860 — test + finetune on your tools
# OR CLI:
needle finetune drone_tools.jsonl
```
**Data format** (JSONL, 1 example per line, `tools` and `answers` are JSON-encoded strings):
```jsonl
{"query":"Fly to the launch pad","tools":"[{\"name\":\"fly_to\",\"description\":\"Fly to GPS coordinate\",\"parameters\":{\"lat\":{\"type\":\"number\",\"required\":true},\"lon\":{\"type\":\"number\",\"required\":true},\"alt\":{\"type\":\"number\"}}}]","answers":"[{\"name\":\"fly_to\",\"arguments\":{\"lat\":37.7749,\"lon\":-122.4194}}]"}
{"query":"Return to home","tools":"[{\"name\":\"rtl\",\"description\":\"Return to launch\",\"parameters\":{}},{\"name\":\"land\",\"description\":\"Land in place\",\"parameters\":{}}]","answers":"[{\"name\":\"rtl\",\"arguments\":{}}]"}
```
- Provide **≥120 examples per tool** (100 train / 10 val / 10 test). Fewer overfits.
- Vary query phrasing; include examples with multiple tools available.
- Result: `checkpoints/needle_finetuned_<id>_best.pkl` — load with `needle run --checkpoint …` or via the Python `load_checkpoint` API.
- Then convert the finetune to a Cactus bundle: `cactus convert ./checkpoints/needle_finetuned_*_best.pkl ./needle-garuda-cq4 --bits 4` (note: issue #767 reports a current bug where finetuned checkpoints sometimes emit bad tokens after CQ4 conversion — track that issue).

### 7.5 Expected performance on Pi 5
- Needle = 26 M params. Even at CQ4 (~13 MB bundle) or Q8 (~50 MB), the per-token weight read is tiny.
- **Conservative estimate** based on LFM2.5-350M's 30 tok/s decode on Pi 5: **Needle should hit 300–600 tok/s decode, 2,000–3,000 tok/s prefill** on Pi 5 (13× smaller weights per token).
- Cactus's headline number is **1,200 tok/s decode / 6,000 tok/s prefill** on "consumer hardware" (Apple Silicon-class). Pi 5 will be lower but still far above real-time need.
- **RAM**: ~50–80 MB for the model (vs 300 MB for LFM2.5-350M) — leaves the rest of the Pi 5's 8 GB for LFM2.5-VL-450M and flight stack.

---

## 8. Running LFM2.5-VL-450M with Cactus Instead of llama.cpp

### 8.1 Can you? Yes.
- `Cactus-Compute/LFM2.5-VL-450M` exists on HF (15 downloads, image-text-to-text, Liquid "other" license).
- A **pre-built CQ bundle** `Cactus-Compute/LFM2.5-VL-450M-cq` is also published — fetch with `cactus download LiquidAI/LFM2.5-VL-450M` (or `Cactus-Compute/LFM2.5-VL-450M-cq`).
- The transpiler has a tested **LFM2/2.5** adapter (`docs/cactus_transpiler.md` supported families table). LFM2.5-VL is a vision variant — Cactus's `multimodal_causal_lm_logits` task handles it.
- The LFM2.5-350M blog benchmarks the **non-VL** 350 M variant on Pi 5 at 200/30 tok/s. The VL-450M is similar size + a small vision tower; expect **comparable text decode + 30–60 ms image encode** on Pi 5 (the M5 Max does 256px encode in 43 ms; Pi 5 will be ~5–10× slower → ~200–400 ms).

### 8.2 Would it be faster than llama.cpp on ARM?
**Likely yes, for these reasons:**

| Factor | Cactus | llama.cpp |
|---|---|---|
| **ARM kernel specificity** | Hand-tuned NEON/DOTPROD/I8MM per ISA tier; I8MM `SMMLA` 2×8×8×2 INT8 matmul-in-one-instruction | Generic GGML Q4/Q8 kernels; ARM NEON paths exist but less aggressively tuned per-tier |
| **Quantization** | CQ (Hadamard rotation + codebook) at 4-bit retains near-FP16 quality; 2-bit still usable. Production bundle ~3 bpw | GGUF Q4_K_M / Q8_0; mixed K-quants. No 1- or 2-bit usable path |
| **Memory** | Zero-copy `mmap` with on-demand page-in; SIMD-aligned 32-byte weight layout; block-interleaved for 4-output-neuron vector loads | mmap supported but less layout-optimized; weight layout less NEON-friendly |
| **Decode threading** | Single-core decode by design (memory-bound; avoids OS throttle) | Multi-thread decode by default (can be limited with `-t 1`) |
| **Prefill threading** | Multi-threaded prefill (compute-bound) | Multi-threaded prefill |
| **Vision tower** | Quantized with same CQ recipe; dedicated conv2d + image kernels | Vision usually offloaded to a separate CLIP/gguf path; less integrated |
| **KV cache** | INT8-quantized KV cache (group=32) with hybrid INT8/FP16 attention | FP16 KV cache by default (more RAM) |
| **Hybrid routing** | Built-in 65 k-param confidence probe → cloud handoff | Not built-in; requires custom router |

**Caveats / where llama.cpp wins:**
- **Maturity & ecosystem**: llama.cpp has years of community work, broader model support, mmproj handling for VLMs is battle-tested.
- **License**: llama.cpp is **MIT**. Cactus engine is **non-commercial source-available** (see §10).
- **Pi-specific tuning**: llama.cpp is widely benchmarked on Pi; Cactus's Pi 5 number is one data point (LFM2.5-350M at 30 tok/s decode). No public Needle-on-Pi-5-via-Cactus benchmark exists yet.
- **VLM completeness**: llama.cpp + mmproj handles LFM2.5-VL-450M today. Cactus supports it (the `-cq` bundle exists) but it's lower-download (15 dl) — less battle-tested on Pi.

### 8.3 Recommendation for GarudaOne
- **For Needle (command router):** Use **Cactus**. The CQ + NEON + mmap stack is purpose-built for this size of model on ARM. The hybrid routing probe is a free router for the "complex → LFM2.5-VL" handoff. License is fine for a <$2 M startup.
- **For LFM2.5-VL-450M (complex commands + vision):** **Try Cactus first** (`cactus download LiquidAI/LFM2.5-VL-450M` then benchmark `cactus benchmark --model LiquidAI/LFM2.5-VL-450M --bits 4`). If the benchmark meets your latency target, use Cactus for the integrated stack. If the vision path is buggy/slow on Pi, **fall back to llama.cpp** for the VLM tier only and keep Cactus for Needle — the two can coexist (different processes, different ports).

### 8.4 A hybrid deployment sketch
```
┌──────────────────────────────────────────────────────────────┐
│ Raspberry Pi 5 (8 GB, ARMv8.2-A, I8MM)                       │
│                                                              │
│  ┌──────────────┐    fast path (≥300 tok/s)                  │
│  │ Cactus +     │─── Needle 26M (CQ4) ──┐                    │
│  │ Needle       │    function_calls      │                    │
│  │ (router)     │                        │ confidence < 0.7?  │
│  └──────────────┘                        ▼                    │
│                              ┌──────────────────────┐         │
│                              │ Cactus + LFM2.5-VL   │         │
│                              │ 450M (CQ4, VLM)      │         │
│                              │ complex commands +   │         │
│                              │ vision               │         │
│                              └──────────────────────┘         │
│                                       │ still stuck?          │
│                                       ▼                       │
│                              [optional cloud handoff]         │
└──────────────────────────────────────────────────────────────┘
```

---

## 9. Other Models & Features Useful for a Drone Project

### 9.1 Speech (voice commands to the drone)
- **Parakeet-TDT-0.6B-v3** (CC-BY-4.0): non-autoregressive ASR, sub-200 ms end-to-end latency on Apple Silicon. Cactus supports **streaming transcription** (`cactus_stream_transcribe_*`) with LocalAgreement — finalized words append, pending tail is live preview. **6 M tok/s decode** on Parakeet CTC 1.1B. On Pi 5 expect real-time transcription.
- **Whisper-tiny/base/small** (Apache-2.0): if you want multilingual (Parakeet is English-only). Whisper-small is a good Pi 5 fit.
- **Moonshine-base** (MIT): lightweight ASR alternative.
- **Silero-VAD** (MIT): **voice activity detection** — detect speech start/stop before sending to ASR. Crucial for a drone that should listen continuously but only transcribe when spoken to.
- **Custom vocabulary boosting**: `cactus_transcribe` accepts `custom_vocabulary` + `vocabulary_boost` in options — bias the decoder toward drone terms ("waypoint", "loiter", "RTL", "geofence").

### 9.2 Vision (autonomous flight / camera)
- **LFM2.5-VL-450M** (Liquid "other"): your complex-command + camera model.
- **LFM2.5-VL-1.6B** (Liquid "other"): bigger VLM if Pi 5 RAM allows (~1 GB at CQ4).
- **gemma-4-E2B-it** (Apache-2.0): the model Cactus benchmarks most; strong multimodal.
- **segmentation-3.0** (MIT): for ground/object segmentation from the drone camera.
- The Cactus image kernels include `cactus_image_to_patches` (ViT patch extraction) — so custom vision models can be transpiled and run on-device.

### 9.3 Speaker ID (operator authentication)
- **wespeaker-voxceleb-resnet34-LM** (CC-BY-4.0): speaker verification. Use case: **only execute commands from authorized operator's voice**. Pair with Silero-VAD → Parakeet → wespeaker → Needle.

### 9.4 Embeddings + on-device RAG
- **nomic-embed-text-v2-moe** (Apache-2.0) or **Qwen3-Embedding-0.6B** (Apache-2.0).
- Cactus has a built-in **on-device vector index** (`cactus_index_*` API) — store the drone's flight manual, emergency procedures, waypoint catalog and retrieve relevant chunks before command execution. RAG runs fully offline.

### 9.5 Function calling (the core)
- **Needle 26M** (MIT): the router. Finetune on GarudaOne's tool set.
- **LFM2-1.2B-Tool** (Liquid "other"): if Needle's single-shot scope is too narrow, LFM2-1.2B-Tool is a conversational tool-calling model.
- **functiongemma-270m-it** (Gemma): baseline for comparison.

### 9.6 Command line server (OpenAI-compatible)
`cactus serve <model> --port 8080` exposes an **OpenAI-compatible HTTP API** on Pi 5. GarudaOne's flight stack (Python) can talk to it with the standard `openai` Python client pointed at `http://localhost:8080`. No custom protocol needed.

### 9.7 Useful flag: `cactus code`
Cactus ships an **AI coding agent** (`cactus code`) that can auto-start a server with a model. Not drone-relevant directly, but indicates the engine is being used for agent loops in production.

### 9.8 Telemetry
Built-in opt-out telemetry (`cactus_set_telemetry_environment`, `cactus_set_app_id`). Disable with `--no-cloud-tele` on the CLI.

---

## 10. License — Engine vs Models

### 10.1 Cactus **engine** (`github.com/cactus-compute/cactus`)
**NOT OSI-open-source.** Custom non-commercial source-available license. Full text in `LICENSE`:

> Copyright (c) 2025 Cactus Compute, Inc. All Rights Reserved.
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software … to use, copy, modify, merge, publish, and distribute the Software … subject to the following conditions:
> 1. Include copyright notice.
> 2. This grant applies only to:
>    (a) Individuals for personal, educational, research, or **non-commercial** purposes;
>    (b) Organizations with **both** (i) **< $2,000,000 USD total funding** (equity, debt, grants, loans) AND (ii) **< $2,000,000 USD gross annual revenue**;
>    (c) Educational institutions and students;
>    (d) Non-profits (501(c)(3) or equivalent).
> 3. Anyone not meeting §2 must obtain a **commercial license** from Cactus Compute, Inc. (founders@cactuscompute.com).
> 4. If an org qualifying under §2(b) **exceeds either threshold**, permission **automatically terminates** and a commercial license must be obtained within 30 days.

GitHub recognizes this as `license: other` / `spdx_id: NOASSERTION`.

**For AatoNovaZ / GarudaOne:** ₹20 L SISFS funding ≈ $24 K. **Far below $2 M on both funding and revenue.** ✅ **Usable today without a commercial license.** But:
- Track funding + revenue. The license auto-terminates the day either crosses $2 M.
- If GarudaOne raises a priced round > $2 M, or revenue exceeds $2 M/yr, you must obtain a commercial license within 30 days.
- For a patented commercial drone product, **budget for the commercial license** in any go-to-market plan. Email `founders@cactuscompute.com` for terms.

### 10.2 Needle **model + repo** (`github.com/cactus-compute/needle`, `Cactus-Compute/needle`)
**MIT License** (Copyright (c) 2026 Cactus Compute). Full commercial use, modification, distribution, sublicensing, private use — all permitted. HF card confirms `license: mit`.

This means:
- The **Needle weights and the Needle training/finetuning code are truly open** — you can use, modify, and ship Needle commercially with zero license obligations (just keep the copyright notice).
- You can finetune Needle on GarudaOne's tools and ship the finetune under any license you want.
- **However**, to run Needle *at the advertised speeds*, you need the **Cactus engine**, which is not MIT. You can run Needle without Cactus via the native Flax path or via llama.cpp (GGUF), but you lose the NEON/CQ/mmap advantages.

### 10.3 Other models on the HF org — upstream licenses apply
- **Gemma 3/4**: Google Gemma license (permit commercial use with restrictions).
- **Qwen3/3.5**: Apache-2.0 (fully open).
- **LFM2/2.5 (Liquid)**: "other" — Liquid's own license (check Liquid AI's terms; generally permissive for research + commercial with conditions).
- **Whisper**: Apache-2.0 (OpenAI).
- **Parakeet**: CC-BY-4.0 (NVIDIA — attribution required, commercial OK).
- **wespeaker**: CC-BY-4.0.
- **Moonshine, Silero-VAD, segmentation-3.0**: MIT.
- **FunctionGemma**: Gemma license.
- **Nomic embed, Qwen3-Embedding**: Apache-2.0.

**Always check the upstream model card** before shipping — the Cactus engine license is separate from the model weights license.

---

## 11. Community — How Active? Any Pi/ARM Work?

### 11.1 GitHub stats (as of 2026-07-18)
| Repo | Stars | Forks | Open issues | Lang | Created | Last push |
|---|---|---|---|---|---|---|
| **cactus-compute/cactus** | **5,503** | 445 | 76 | C++ | 2025-04-23 | **2026-07-17** (yesterday) |
| **cactus-compute/needle** | **3,196** | 239 | 25 | Python | 2026-02-24 | 2026-07-17 |
| cactus-compute/cactus-react-native | 178 | 23 | 8 | C++ | — | 2026-04-19 |
| cactus-compute/cactus-kotlin | 74 | 8 | 3 | Kotlin | — | 2026-02-10 |
| cactus-compute/cactus-flutter | 71 | 17 | 8 | C++ | — | 2025-12-21 |
| cactus-compute/functiongemma-hackathon | 41 | 163 | 7 | Python | — | 2026-02-21 |
| cactus-compute/voice-agents-hack | 17 | 47 | 3 | — | — | 2026-04-19 |
| cactus-compute/demo-cactus-chat | 28 | 12 | 16 | TypeScript | — | 2026-01-02 |
| cactus-compute/cactus-gemma4 | 4 | 0 | 0 | TypeScript | — | 2026-06-11 |

**18 repos total in the org.** Both flagship repos pushed **yesterday** — extremely active development. The cactus repo grew from 0 → 5,503 stars in ~15 months; Needle hit 3,196 stars in <5 months.

### 11.2 Backing & team
- **Y Combinator** backed (W25 batch — `ycombinator.com/companies/cactus`).
- 7-person team on HF: **Henry Ndubuaku** (founder, ex-mobile-ML), Roman Shemet, Jakub Mroz, Satyajit Kumar, Karen Mosoyan, Parkirat Sandhu, Noah Cylich.
- Partnerships: **Cactus x DeepMind hackathon** (functiongemma-hackathon repo, voice-agents-hack "Cactus x Google DeepMind x Y Combinator").
- HF org has **210 followers**.

### 11.3 Recent issues (signal for Pi/ARM work)
- **#768** "build: fail early on unsupported (non-ARM64) targets" (2026-07-16) — *directly addresses* Pi 4 vs Pi 5 support; documents the ARMv8.2+ requirement.
- **#767** "Finetuned Needle checkpoint converts to a CQ4 bundle that emits token [bug]" (2026-07-15) — **watch this if you finetune Needle then convert to Cactus.**
- **#761** "fix: resolve Python FFI buffer limits and single-quote escaping" (2026-07-11).
- **#764** engine content-search fix (2026-07-11).
- **#770** Gemma 4 agentic turn rendering (2026-07-17).

Issue #768's body explicitly references "ARMv8.0 / Raspberry Pi 4 case from #561" — meaning there's an **older issue #561 specifically about running on Pi 4** (which is unsupported). The Pi 5 is the first Pi that works. Search "Raspberry Pi" in the issue tracker before deploying — there may be Pi 5-specific threads.

### 11.4 Reddit & press
- **r/LocalLLaMA** thread on Needle (May 2026) — strong engagement, the launch post.
- **r/cactuscompute** — dedicated subreddit (linked from README).
- Press: Gigazine, TechPlanet, OpenClaw Radar, linkwordx, reporank — moderate coverage, mostly Needle-focused.
- **agentry.press** tutorial (June 2026) — "Local Tool-Calling Inference with Needle 26M, llama.cpp, and OpenTelemetry" — confirms the llama.cpp alternative path is in active community use.

### 11.5 Community finetunes
- **theabbie/needle-pi-coding-agent** (HF) — "A 26.3M-parameter Cactus Needle fine-tune for routing coding-agent intents into Pi's four built-in tools: read, bash, edit, and write." **Direct precedent: someone already finetuned Needle for a Pi-based agent.** This is the closest existing analog to GarudaOne's use case.
- `Cactus-Compute/needle-pebble-ft` — official finetune.
- 4 finetunes + 4 quantizations in the Needle model tree.
- `shreyask/needle-playground` — HF Space for interactive Needle testing.

### 11.6 Pi/ARM-specific verdict
- **Pi 5 is the only Pi officially supported** (ARMv8.2-A). Pi 4 and earlier are out.
- The LFM2.5-350M blog **explicitly benchmarks the Raspberry Pi 5** as one of 7 devices — so Pi 5 is a first-class test target, not an afterthought.
- Issue #768 shows the team is actively hardening the ARM build story.
- No large body of Pi 5-specific community benchmarks yet — you'll be on the early side, but the architecture is designed for exactly this device class.

---

## 12. Cactus vs llama.cpp for Needle 26M on ARM — Which Is Faster?

### 12.1 No direct head-to-head public benchmark exists
There is no published benchmark of Needle 26 M on Pi 5 comparing Cactus vs llama.cpp. Cactus's 6,000/1,200 tok/s claim is on "consumer hardware" (likely Apple M-series). The agentry.press tutorial uses llama.cpp but does not publish tok/s numbers. So the comparison must be reasoned from architecture.

### 12.2 Architectural reasons Cactus should win on ARM
1. **Kernels**: Cactus writes per-ISA-tier NEON/DOTPROD/I8MM kernels. The I8MM `SMMLA` instruction does a 2×8 × 8×2 INT8 matmul in one instruction. llama.cpp has ARM NEON paths but they are less aggressively tuned per-tier and use generic Q4/Q8 GGML formats.
2. **Quantization**: Cactus CQ4 is near-lossless and production-tuned for ARM. llama.cpp's Q8_0 is also near-lossless; Q4_K_M is good. At 26 M params, quantization matters less (the model is small either way) — but CQ's layout is SIMD-aligned (32-byte) and block-interleaved for 4-output-neuron vector loads, which reduces per-token decode memory traffic.
3. **Memory**: Cactus uses `mmap(PROT_READ, MAP_SHARED)` with on-demand page-in and weight streaming from storage — designed to avoid OS throttling. On Linux/Pi 5 the mmap benefit is reduced (the blog notes Android/Linux kernels copy mmap pages → anonymous memory), but the layout is still SIMD-friendly.
4. **Single-core decode**: Cactus deliberately runs decode single-core (memory-bound; avoids OS throttle). llama.cpp defaults to multi-thread decode which on Pi 5 adds synchronization overhead without adding bandwidth. You'd have to set llama.cpp `-t 1` to match.
5. **KV cache**: Cactus INT8-quantizes the KV cache (group=32) with hybrid INT8/FP16 attention. llama.cpp defaults to FP16 KV cache — more RAM, more bandwidth per token. At Needle's tiny size this is a small absolute difference but a real relative one.
6. **Needle-specific**: Cactus is the *reference* engine for Needle (same company). The CQ bundle for Needle is built and tested by the Needle team. llama.cpp support for Needle exists via the GGUF (`needle-q8_0.gguf`) but is community-maintained.

### 12.3 Reasons llama.cpp might win or tie
1. **Maturity**: llama.cpp has years of micro-optimizations across ARM variants. Cactus is ~15 months old.
2. **At 26 M params, the bottleneck may not be the engine**. The model is so small that overheads (Python FFI, tokenizer, JSON parsing) dominate. Both engines should hit "fast enough" (>500 tok/s decode on Pi 5).
3. **llama.cpp's Q8_0 is extremely well-tuned for ARM** with dedicated `vecdotq` NEON kernels. For a tiny model where you can afford Q8, llama.cpp's Q8_0 may be within 10-20% of Cactus CQ4.
4. **Pi 5 mmap behavior**: The blog shows Linux mmap degrades to near-malloc behavior (300 MB RAM for 355 MB model). This erodes some of Cactus's memory advantage on Linux specifically (vs Apple Silicon where mmap shines).

### 12.4 Verdict
**Cactus is very likely faster on Pi 5 for Needle** — probably **1.5–3× faster decode** than llama.cpp Q8_0, based on:
- The I8MM kernel advantage (single-instruction INT8 matmul),
- The CQ4 weight layout (SIMD-aligned, block-interleaved),
- INT8 KV cache,
- Single-core decode by default,
- And the fact that Cactus is the reference engine for Needle (the 1,200 tok/s claim is *their* number on *their* engine).

**But**: the margin may be small in absolute terms (both are "instant" for a 26 M model), and llama.cpp's MIT license + maturity may outweigh the speed difference if license is a concern.

### 12.5 Recommended test plan for GarudaOne
1. Build both on Pi 5:
   ```bash
   # Cactus
   git clone https://github.com/cactus-compute/cactus && cd cactus && source ./setup
   cactus benchmark --model Cactus-Compute/needle --bits 4

   # llama.cpp
   pip install llama-cpp-python
   huggingface-cli download Cactus-Compute/needle needle-q8_0.gguf --local-dir ./needle-gguf
   python -c "
   from llama_cpp import Llama
   import time
   llm = Llama('needle-gguf/needle-q8_0.gguf', n_ctx=512, n_threads=1, verbose=False)
   t0=time.perf_counter()
   out = llm('<tools>\n[...]\n</tools>\n<query>\nArm the drone\n</query>\n', max_tokens=64, temperature=0)
   dt=time.perf_counter()-t0
   print(f'{out[\"usage\"][\"completion_tokens\"]} tokens in {dt:.2f}s = {out[\"usage\"][\"completion_tokens\"]/dt:.1f} tok/s')
   "
   ```
2. Compare `decode_tps` from Cactus's `result["decode_tps"]` vs the llama.cpp tok/s.
3. Run 100 queries through each and compare mean/p95 latency + tool-call accuracy (use Needle's own eval set or your GarudaOne tool set).

---

## Appendix A — Key URLs

| Resource | URL |
|---|---|
| Website | https://cactuscompute.com |
| Main repo | https://github.com/cactus-compute/cactus |
| Needle repo | https://github.com/cactus-compute/needle |
| Docs | https://docs.cactuscompute.com (versioned: /v1.14/, /v2.0.1/) |
| HF org | https://huggingface.co/Cactus-Compute |
| Needle weights | https://huggingface.co/Cactus-Compute/needle |
| PyPI | https://pypi.org/project/cactus-compute/ |
| Reddit | https://www.reddit.com/r/cactuscompute/ |
| Blog | https://cactuscompute.com/blog |
| YC profile | https://www.ycombinator.com/companies/cactus |
| LFM2.5-350M Pi 5 blog | https://github.com/cactus-compute/cactus/blob/main/blog/lfm2.5_350m.md |
| Parakeet blog | https://github.com/cactus-compute/cactus/blob/main/blog/parakeet.md |
| Engine API doc | https://github.com/cactus-compute/cactus/blob/main/docs/cactus_engine.md |
| Kernels doc | https://github.com/cactus-compute/cactus/blob/main/docs/cactus_kernels.md |
| Quants doc | https://github.com/cactus-compute/cactus/blob/main/docs/cactus_quants.md |
| Hybrid doc | https://github.com/cactus-compute/cactus/blob/main/docs/cactus_hybrid.md |
| Transpiler doc | https://github.com/cactus-compute/cactus/blob/main/docs/cactus_transpiler.md |
| ARM support issue | https://github.com/cactus-compute/cactus/issues/768 |
| Needle-via-llama.cpp tutorial | https://agentry.press/tutorial/local-tool-calling-inference-with-needle-26m-llama-cpp-and-opentelemetry/ |
| Community Needle Pi finetune | https://huggingface.co/theabbie/needle-pi-coding-agent |
| Commercial license contact | founders@cactuscompute.com |

## Appendix B — Local raw source files downloaded during research
(under `C:\Projects\DroneOS\research\`)
- `cactus_readme_raw.md` — main repo README
- `cactus_needle_readme.md` — needle repo README
- `cactus_lfm_blog.md` — LFM2.5-350M Pi 5 benchmark blog
- `cactus_parakeet_blog.md` — Parakeet transcription blog
- `cactus_kernels_doc.md` — full kernel API
- `cactus_quants_doc.md` — full CQ quantization doc
- `cactus_hybrid_doc.md` — full hybrid routing doc
- `cactus_engine_doc.md` — full engine C FFI API (1,359 lines)
- `cactus_transpiler_doc.md` — full transpiler doc
- `cactus_compat_doc.md` — runtime/weights compatibility
- `cactus_license.md` — Cactus engine LICENSE (non-commercial)
- `cactus_needle_license.md` — Needle LICENSE (MIT)
- `cactus_gh_api.json`, `cactus_needle_gh_api.json`, `cactus_org_repos.json`, `cactus_gh_issues.json`, `cactus_issue_768.json` — GitHub API snapshots
- `cactus_hf_models.json`, `needle_hf_api.json` — HuggingFace API snapshots
- `cactus_python_sdk.md` — Python SDK docs page (HTML)

---

## Final Recommendation for GarudaOne

1. **Adopt Cactus + Needle as the fast command router on Pi 5.** Architecture is purpose-built for this exact device class (ARMv8.2-A + I8MM). Finetune Needle on GarudaOne's tool set using the Needle repo (≥120 examples/tool), then convert to a CQ4 bundle and load via `cactus_init`.
2. **Use Cactus's built-in hybrid probe** as the "complex → LFM2.5-VL" router. Set `confidence_threshold ≈ 0.7`. This eliminates the need to hand-build a router and the probe generalizes across modalities for free.
3. **Benchmark LFM2.5-VL-450M under Cactus on Pi 5** (`cactus benchmark --model LiquidAI/LFM2.5-VL-450M --bits 4`). If image-encode + decode meets your latency target, run it under Cactus too (integrated stack, one process). If not, fall back to llama.cpp for the VLM tier only — the two coexist fine.
4. **Add Silero-VAD + Parakeet-TDT-0.6B-v3** for hands-free voice commands with custom vocabulary boosting (drone terminology). Streaming transcription is built in.
5. **License: plan for a commercial Cactus license** in GarudaOne's go-to-market budget. It's free today (AatoNovaZ is <$2 M funding/revenue), but auto-terminates the day either threshold is crossed. Email `founders@cactuscompute.com` for terms once GarudaOne approaches commercial scale. The Needle weights themselves are MIT — no obligation there.
6. **Track issue #767** (finetuned-Needle-to-CQ4 conversion bug) before relying on a finetune in production.
7. **Run the head-to-head Cactus-vs-llama.cpp benchmark on Pi 5** (Appendix §12.5) before locking in the engine choice — confirm the architectural advantage holds for your specific Needle finetune.
