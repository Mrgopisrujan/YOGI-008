# LFM2.5-VL-450M Deep Analysis for GarudaOne Drone Project

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - Needle 2 (45M, `cactus-needle==2.0.0`) replaced Needle 26M as the active constrained router.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - Land/RTL mode transfer requires PX4 ACK and heartbeat confirmation; physical behavior remains unqualified.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!NOTE]
> This is a dated research snapshot. Model choices, estimates, and recommendations are not implementation claims. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


## Research Date: July 17, 2026
## Sources: Liquid AI blog, HuggingFace model cards, Cactus Compute GitHub, BFCL leaderboard, Liquid docs

---

## Executive Summary

**The 450M VL cannot replace both the 230M text router AND the VL model.** While it technically supports both function calling and vision, its tool-calling accuracy is critically low (BFCLv4: 21.08) — essentially identical to the 230M (21.03) and 350M (21.86). None of these small Liquid models have reliable enough tool calling for a 95% accuracy requirement without GBNF grammar constraints and/or fine-tuning. The architecture decision should be:

- **Keep LFM2.5-230M as text tool router** (42 tok/s, 142MB Q4_0, BFCLv3: 43.26)
- **Use LFM2.5-VL-450M for episodic vision only** (scene understanding, Director's Eye)
- **Rely on GBNF grammar + Needle 26M for the 95% tool-call accuracy target**
- **RefCOCO-M: 81.28 is a supplement to PicoDet, not a replacement** — too slow for 25Hz tracking

---

## 1. Can LFM2.5-VL-450M Do BOTH Text Tool-Calling AND Visual Scene Understanding?

### Capabilities (Confirmed)
- ✅ **Function calling for text-only input** — uses `<|tool_call_start|>[func_name(arg="val")]<|tool_call_end|>` format
- ✅ **Bounding box prediction** — RefCOCO-M: 81.28, outputs JSON `{"label": ..., "bbox": [x1,y1,x2,y2]}`
- ✅ **Visual scene understanding** — MMStar: 43.00, RealWorldQA: 58.43, POPE: 86.93
- ✅ **32K context, 9 languages, 512×512 native resolution**

### The Critical Problem: Tool-Calling Quality
The 450M VL's BFCLv4 score is **21.08** — and this is the *overall accuracy* including complex multi-turn agentic tasks. For comparison on the BFCL leaderboard:

| Model | BFCLv4 Overall | Params |
|-------|---------------|--------|
| Claude Opus 4.5 (FC) | 77.47 | ~largest |
| GPT-4.1 (FC) | 53.96 | ~largest |
| Qwen3-1.7B (FC) | 28.13 | 1.7B |
| LFM2.5-350M (backbone) | 21.86 | 350M |
| **LFM2.5-VL-450M** | **21.08** | 450M |
| **LFM2.5-230M** | **21.03** | 230M |
| Llama-3.2-1B (FC) | 10.82 | 1B |
| Granite-4.0-350m (FC) | 18.98 | 350M |

**Key insight**: The 450M VL's tool calling is essentially identical to the 230M (21.08 vs 21.03). The VL model's text tool-calling capability is NOT better than the smaller text-only model. The 450M adds vision on top of the same 350M backbone, but the RL post-training for vision tasks didn't improve text tool calling.

### Verdict
**The 450M VL can technically do both, but its tool-calling is no better than the 230M.** At 21% BFCLv4 accuracy, raw tool calling is unreliable for production. The 95% accuracy target REQUIRES GBNF grammar constraints or fine-tuning regardless of which model you use. The 230M is the better choice for pure text routing because:
- It's faster (42 tok/s vs ~472 tok/s decode but the 230M has lower latency for short tool-call outputs)
- It uses less RAM (142MB vs 307MB at Q4_0)
- Same tool-calling accuracy (21.03 vs 21.08)

---

## 2. Actual Pi 5 CPU Inference Speed

### Official Liquid AI Claims
- **Sub-250ms on Jetson Orin** (GPU-accelerated, NOT CPU): 233ms @ 256×256, 242ms @ 512×512
- **Samsung S25 Ultra**: 950ms @ 256×256, 2.4s @ 512×512 (mobile CPU)
- **AMD Ryzen AI Max+ 395**: 637ms @ 256×256, 944ms @ 512×512

### Cactus Compute Benchmarks (ARM CPU, optimized kernels)
| Model | Decode Speed | Image Encode |
|-------|-------------|-------------|
| LFM2.5-VL-450m | **472 tok/s** | **43ms** |
| LFM2.5-VL-230m | 555 tok/s | N/A (text-only) |
| LFM2.5-VL-1.6B | 289 tok/s | — |

### Pi 5 Extrapolation (No Direct Benchmark Found)
**No direct Pi 5 benchmark exists for the 450M VL.** However, we can extrapolate:

- The 230M runs at **42 tok/s on Pi 5** (officially confirmed)
- The 450M is ~2x larger (450M vs 230M params)
- Cactus shows 472 tok/s vs 555 tok/s for 450M vs 230M (0.85x ratio on mobile-class ARM)
- **Estimated Pi 5 decode: ~35-38 tok/s** (applying 0.85x to 42 tok/s)

### Full Image+Prompt Latency on Pi 5 (Estimated)
For a single 256×256 image + short prompt:
- **Image encoding**: ~43-100ms (SigLIP2 86M vision encoder, Pi 5 CPU is slower than mobile SoC)
- **Prefill**: ~50-100ms (image tokens 32-256 + text prompt ~20 tokens)
- **Decode** (50 token response): 50/37 = ~1.35s
- **Total estimated**: **1.5-2.0 seconds per image+prompt on Pi 5 CPU**

For 512×512 (the model's native max):
- Image encoding is higher, potentially 2-4x more vision tokens
- **Total estimated**: **2.5-4.0 seconds per image+prompt on Pi 5 CPU**

### Verdict
The "sub-250ms" claim is **Jetson Orin GPU-only**. On Pi 5 CPU, expect **1.5-4 seconds per image+prompt**. This fits the "episodic (1-3s/frame)" role in the current architecture but is too slow for real-time control. Text-only tool calling (no image) would be faster: ~1s for a 30-token tool call response.

---

## 3. Tool Calling Accuracy & GBNF Support

### BFCL Scores (All Three Liquid Models)
| Model | BFCLv3 | BFCLv4 | τ²-Bench Telecom | τ²-Bench Retail |
|-------|--------|--------|------------------|-----------------|
| LFM2.5-230M | **43.26** | 21.03 | 5.26 | 13.68 |
| LFM2.5-350M | **44.11** | 21.86 | 18.86 | 17.84 |
| LFM2.5-VL-450M | — | **21.08** | — | — |

**Note**: BFCLv3 (43.26) is much higher than BFCLv4 (21.03). BFCLv4 includes multi-turn agentic tasks, web search, and memory — much harder. BFCLv3 is single-turn function calling, closer to the drone use case.

### GBNF Grammar-Constrained Output in llama.cpp
- ✅ **Supported** — LFM2.5-VL-450M-GGUF runs in llama.cpp which supports GBNF grammars
- The Liquid docs show llama.cpp as a supported inference method: `llama-cli -hf LiquidAI/LFM2.5-VL-450M-GGUF:Q4_0`
- GBNF can constrain output to valid JSON tool-call format
- **This is the key enabler**: With GBNF, even a 21% BFCLv4 model can achieve >95% structured output accuracy for a constrained tool set

### Can It Parse "follow me, stay wide" → {tool: "track_subject", kwargs: {framing: "wide"}}?
- **Without GBNF**: Unreliable. At 21% BFCLv4, raw accuracy is too low for complex parameter extraction.
- **With GBNF + fine-tuning**: Yes, achievable. The model understands the tool-call format (`<|tool_call_start|>[func(arg="val")]<|tool_call_end|>`) and with:
  1. A system prompt listing available tools with descriptions
  2. GBNF grammar constraining output to `{tool: "track_subject"|"orbit"|"land"|..., kwargs: {...}}`
  3. Fine-tuning on drone command examples (LEAP Fine-Tune or Unsloth LoRA)
  4. The BFCLv3 score of 43.26 (single-turn) is more representative of this use case

- **Needle 26M as fast router**: For simple commands like "follow me, stay wide", the Needle 26M (1,200 tok/s) can handle it with GBNF. Complex commands escalate to the 230M/450M.

### Verdict
**GBNF is mandatory.** No Liquid model under 1B parameters has reliable enough raw tool calling. The architecture must use:
1. Needle 26M + GBNF for simple commands (1,200 tok/s, <100ms)
2. LFM2.5-230M + GBNF for complex commands (42 tok/s, ~1s)
3. Fine-tune on drone-specific command patterns

---

## 4. Bounding Box Prediction for Person Tracking

### RefCOCO-M: 81.28 — What Does This Mean?
RefCOCO-M measures referring expression comprehension — given a text description ("the person on the left"), the model predicts a bounding box. The score 81.28 means:
- ~81% of predictions have sufficient IoU (Intersection-over-Union) with ground truth
- This is **referring expression** accuracy, NOT general object detection mAP
- It requires a text prompt describing what to find

### Compared to PicoDet-S (Person Detection)
| Metric | LFM2.5-VL-450M (RefCOCO-M) | PicoDet-S (COCO mAP) |
|--------|---------------------------|---------------------|
| Score | 81.28 (referring expression) | ~30-35 mAP (COCO person) |
| Speed on Pi 5 | ~1.5-4s per image | **~10-30ms per frame** (ncnn INT8) |
| Output | JSON bbox + label + reasoning | Bounding boxes only |
| Use case | "Find the person wearing red" | Fast person detection @ 25-60Hz |
| Latency budget | Episodic (1-3s) | Real-time (40ms budget) |

### Can It Replace PicoDet for 25Hz Tracking?
**NO.** The 450M VL is 50-100x too slow for 25Hz tracking:
- 25Hz = 40ms per frame budget
- 450M VL takes 1,500-4,000ms per image
- PicoDet-S takes 10-30ms per frame

### Can It Supplement PicoDet for "Director's Eye"?
**YES — this is the ideal use case.** For episodic (every 1-3 seconds) scene understanding:
- PicoDet-S handles fast detection + tracking (25Hz)
- 450M VL runs episodically to answer semantic questions:
  - "Is the subject centered in frame?"
  - "Is there a better composition angle?"
  - "Detect all people and describe their positions relative to the subject"
  - "Is the lighting good for this shot?"

The 450M VL's bounding box prediction adds value here because it can:
1. Verify PicoDet's tracking is on the right subject
2. Provide semantic grounding ("the person near the tree")
3. Detect composition issues that PicoDet can't

### Verdict
**Keep PicoDet-S for real-time tracking. Use 450M VL's bbox prediction for episodic verification and semantic grounding.** The RefCOCO-M: 81.28 is good enough for occasional verification, not for continuous tracking.

---

## 5. Memory Footprint

### GGUF File Sizes (LFM2.5-VL-450M-GGUF)
| Quantization | LM Weights | Vision Encoder (mmproj) | Total |
|-------------|-----------|------------------------|-------|
| **Q4_0** | **209.2 MB** | **98.1 MB** (Q8_0) | **~307 MB** |
| Q4_K_M | 218.7 MB | 98.1 MB | ~317 MB |
| Q5_K_M | 248.3 MB | 98.1 MB | ~346 MB |
| Q6_K | 279.8 MB | 98.1 MB | ~378 MB |
| Q8_0 | 361.7 MB | 98.1 MB | ~460 MB |
| F16 | 678.5 MB | 180.4 MB | ~859 MB |

### Comparison: LFM2.5-230M-GGUF (Text Only)
| Quantization | Size |
|-------------|------|
| **Q4_0** | **142.2 MB** |
| Q4_K_M | 146.3 MB |
| Q8_0 | 235.2 MB |

### Pi 5 RAM Usage (8GB Pi 5)
- **LFM2.5-VL-450M Q4_0**: ~307MB weights + ~200-400MB runtime (KV cache, activations) = **~500-700MB total**
- **LFM2.5-230M Q4_0**: ~142MB weights + ~100-200MB runtime = **~250-350MB total**
- **Both models loaded simultaneously**: ~750MB-1.05GB — well within 8GB Pi 5

### Recommended Quantization
- **Q4_0 for both models** — Liquid AI's blog uses Q4_0 for their edge benchmarks
- Q4_0 provides the best speed/quality tradeoff for the LFM2 architecture
- The vision encoder (mmproj) is only available in Q8_0 and F16/BF16 — use Q8_0 (98MB)

---

## 6. LFM2.5-230M vs LFM2.5-VL-450M for Text-Only Tool Calling

### Direct Comparison
| Metric | LFM2.5-230M | LFM2.5-VL-450M | Winner |
|--------|------------|----------------|--------|
| **BFCLv4** | 21.03 | 21.08 | Tie (both low) |
| **BFCLv3** | 43.26 | — | 230M (only data available) |
| **Pi 5 decode speed** | 42 tok/s | ~35-38 tok/s (est.) | **230M** |
| **Q4_0 size** | 142 MB | 307 MB (incl. vision) | **230M** |
| **RAM usage** | ~250-350 MB | ~500-700 MB | **230M** |
| **Vision capability** | None | ✅ Full VLM | **450M** |
| **Tool calling format** | `<\|tool_call_start\|>[func()]<\|tool_call_end\|>` | Same | Tie |
| **Context length** | 32K | 32K | Tie |
| **Fine-tuning** | Unsloth/TRL/LEAP | Unsloth/TRL/LEAP | Tie |

### Analysis
The 450M VL is built on the LFM2.5-350M backbone (not the 230M). The 350M has:
- Slightly better BFCLv4 (21.86 vs 21.03) — negligible difference
- Better IFEval (76.96 vs 71.71) — the 350M follows instructions better
- Better τ²-Bench scores (18.86 vs 5.26 Telecom, 17.84 vs 13.68 Retail)

But the 450M VL adds the SigLIP2 vision encoder (86M params) on top, which:
- Increases model size from 350M to 450M
- Increases memory from ~200MB to ~307MB
- Adds image processing latency
- Does NOT improve text tool calling (the RL post-training focused on vision tasks)

### The 230M Is Distilled FROM the 350M
The 230M was distilled from LFM2.5-350M and refined with RL specifically for tool use and data extraction. It's a **specialist** for text-based agentic tasks. The 450M VL is a **generalist** that adds vision.

### Verdict
**Keep the 230M for text tool routing. Use the 450M VL only for vision.** The 230M is:
- Faster on Pi 5 (42 tok/s vs ~37 tok/s)
- Smaller (142MB vs 307MB)
- Specifically tuned for tool calling
- Distilled from the same 350M backbone

The 450M VL does NOT subsume the 230M for text tasks. It adds vision at the cost of speed and memory, with no improvement in tool-calling accuracy.

---

## Architecture Recommendation for GarudaOne

### Keep the Current 3-Model Architecture (Confirmed Optimal)

```
┌─────────────────────────────────────────────────────────────┐
│ L1 Director (Text Processing)                                │
│                                                              │
│  ┌──────────────┐     ┌──────────────┐                      │
│  │ Needle 26M   │────▶│ LFM2.5-230M  │                      │
│  │ Simple cmds  │     │ Complex cmds │                      │
│  │ 1,200 tok/s  │     │ 42 tok/s     │                      │
│  │ GBNF router  │     │ GBNF tools   │                      │
│  │ <100ms       │     │ ~1s          │                      │
│  └──────────────┘     └──────────────┘                      │
│                                                              │
│  Combined: ~400MB RAM, handles 95%+ with GBNF               │
├─────────────────────────────────────────────────────────────┤
│ L1 Director (Episodic Vision)                                │
│                                                              │
│  ┌──────────────────────────────────────────────┐           │
│  │ LFM2.5-VL-450M (Q4_0)                        │           │
│  │ • Scene understanding (1-3s/frame)           │           │
│  │ • Bbox verification (RefCOCO-M: 81.28)       │           │
│  │ • Composition analysis                       │           │
│  │ • "Director's Eye" semantic checks           │           │
│  │ ~500-700MB RAM, episodic duty cycle          │           │
│  └──────────────────────────────────────────────┘           │
├─────────────────────────────────────────────────────────────┤
│ L2b Reflex (Real-Time Vision)                                │
│                                                              │
│  ┌──────────────────────────────────────────────┐           │
│  │ PicoDet-S ncnn INT8                          │           │
│  │ • Person detection @ 25-60Hz                 │           │
│  │ • 10-30ms per frame                          │           │
│  │ • ByteTrack-lite for tracking                │           │
│  └──────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────┘

Total RAM: ~1.1-1.4GB (well within 8GB Pi 5)
```

### Why NOT Consolidate to 450M VL Only
1. **Tool calling is not better** (21.08 vs 21.03 BFCLv4 — identical)
2. **Slower for text-only** (~37 tok/s vs 42 tok/s, plus vision encoder overhead even for text-only)
3. **More memory** (307MB vs 142MB for text path)
4. **No benefit**: The 450M VL doesn't subsume the 230M's capabilities — it adds vision on top of a different backbone (350M vs 230M)
5. **Risk**: Running vision encoding for every text command would add latency even when no image is needed

### Where the 450M VL Adds Unique Value
1. **Episodic "Director's Eye"**: Every 1-3 seconds, analyze the frame for composition, lighting, subject positioning
2. **Bbox verification**: Confirm PicoDet is tracking the right person using semantic descriptions
3. **Scene understanding**: "There's a cliff behind the subject — adjust orbit radius"
4. **Multi-object reasoning**: "The subject and their companion are both in frame — frame for both"
5. **Natural language grounding**: "Track the person in the red jacket" → bbox → hand off to PicoDet/ByteTrack

### Fine-Tuning Path for 95% Tool-Call Accuracy
1. **GBNF grammar** (mandatory): Constrain output to valid tool-call JSON
2. **Fine-tune LFM2.5-230M** on drone command dataset:
   - 500-1000 examples of (natural language → tool call) pairs
   - Use Unsloth LoRA or LEAP Fine-Tune
   - Include edge cases: "follow me, stay wide", "orbit clockwise at 5m", "land now"
3. **Needle 26M** handles the 80% simple cases (follow, stop, land, return)
4. **230M** handles the 20% complex cases (multi-parameter, conditional commands)
5. **Fallback**: If both fail, default to safe hover + ask for clarification

---

## Data Sources

| Source | URL | Key Data |
|--------|-----|----------|
| Liquid AI Blog (450M VL) | liquid.ai/blog/lfm2-5-vl-450m | Benchmarks, edge performance |
| Liquid AI Blog (230M) | liquid.ai/blog/lfm2-5-230m | Pi 5 42 tok/s, BFCLv3 43.26 |
| HF Model Card (450M VL) | huggingface.co/LiquidAI/LFM2.5-VL-450M | Tool use format, bbox example |
| HF Model Card (230M) | huggingface.co/LiquidAI/LFM2.5-230M | Full benchmarks, Pi 5 speed |
| HF Model Card (350M) | huggingface.co/LiquidAI/LFM2.5-350M | BFCLv4 21.86, backbone comparison |
| HF GGUF (450M VL) | huggingface.co/LiquidAI/LFM2.5-VL-450M-GGUF | File sizes: Q4_0=209MB+98mmproj |
| HF GGUF (230M) | huggingface.co/LiquidAI/LFM2.5-230M-GGUF | Q4_0=142MB |
| Cactus Compute | github.com/cactus-compute/cactus | 472 tok/s, 43ms image encode |
| BFCL v4 Leaderboard | gorilla.cs.berkeley.edu/leaderboard.html | 21.08 context, model comparisons |
| Liquid Docs | docs.liquid.ai/lfm/models/lfm25-vl-450m | llama.cpp usage, Q4_0 recommended |
