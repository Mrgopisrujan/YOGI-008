# Web Validation Report v3 — 2026-07-15

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - Needle 2 (45M, `cactus-needle==2.0.0`) replaced Needle 26M as the active constrained router.
> - The selected flight profile uses one forward VL53L5CX at 8x8/15Hz; three-sensor/VL53L8CX designs are not active.
> - Local voice transport is integrated; the exact STT bundle still requires target-Pi qualification.
> - The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; track remains disabled and autonomous cinematic flight is unavailable.
> - The flight profile instantiates C10 and requires an inbound checksummed status reply; physical attitude feedback and motion limits remain unvalidated.
> - Production VIO/SLAM adapters are absent or deferred.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!IMPORTANT]
> This is an architecture/design record, not deployment evidence. Current verified implementation status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


**Method:** 436 externally-verifiable claims were machine-extracted from the full corpus (architecture 00–12, future-phases 01–09, master guide, garudaone-software, context pack BOOK III, lingbot repos) by a 14-agent extraction pass, deduplicated, and bucketed into 13 topics. The ~35 unique **load-bearing** facts (everything the build plan or investor story rests on) were then re-verified against the **live web on 2026-07-15** — primary sources only: HuggingFace model cards, GitHub trees, vendor blogs/datasheets, arXiv, plus community channels (X, Reddit, HN) where relevant. The long-tail sweep (~180 medium/low-priority claims, mostly master-guide catalog rows) is queued for a resumable multi-agent pass (see §6).

**Verdict summary: the build plan survives. Zero load-bearing claims refuted.** Two license/detail errors found and fixed; several local repo-hygiene issues flagged.

> **Repo note (2026-07-15 cleanup):** `garudaone-software/`, `TempPX4/`, `lingbot-vision/`, `lingbot-depth/`, `lingbot-map/`, and `models/lnn_weights.pt` referenced below have since been removed from this repo (vendored clones + a scrapped v1 codebase's post-mortem docs) — kept only as historical decision record.

---

## 1. Confirmed — core stack (all against primary sources, 2026-07-15)

| Claim (docs) | Verdict | Source |
|---|---|---|
| LFM2.5-230M exists; official GGUF; 42 tok/s Pi 5; 213 tok/s S25U; 32K ctx; distilled from LFM2.5-350M; June 2026 | ✅ Confirmed, incl. exact tok/s | [HF LiquidAI/LFM2.5-230M-GGUF](https://huggingface.co/LiquidAI/LFM2.5-230M-GGUF), [Liquid blog](https://www.liquid.ai/blog/lfm2-5-230m) |
| LFM2.5-VL-450M exists; SigLIP2 NaFlex ~86M encoder + LFM2.5-350M backbone; 32,768 ctx; bbox prediction + function calling; ≤512×512 native; GGUF/ONNX; released April 2026 | ✅ Confirmed (release date via [MarkTechPost 2026-04-11](https://www.marktechpost.com/2026/04/11/liquid-ai-releases-lfm2-5-vl-450m-a-450m-parameter-vision-language-model-with-bounding-box-prediction-multilingual-support-and-sub-250ms-edge-inference/); model card cites arXiv 2511.23404) | [HF LiquidAI/LFM2.5-VL-450M](https://huggingface.co/LiquidAI/LFM2.5-VL-450M) |
| Needle 26M — Cactus Compute, MIT, 1,200 tok/s decode / 6,000 prefill, distilled from Gemini (3.1 Flash Lite), released 2026-05-12 | ✅ Confirmed | [HF Cactus-Compute/needle](https://huggingface.co/Cactus-Compute/needle), [GitHub](https://github.com/cactus-compute/needle) |
| PX4 v1.16 stable; **`boards/micoair/h743-aio` is a real upstream target** (plus h743, h743-v2, h743-lite) | ✅ Confirmed | [PX4 releases](https://github.com/PX4/PX4-Autopilot/releases), [boards/micoair tree](https://github.com/PX4/PX4-Autopilot/tree/main/boards/micoair) |
| PicoDet-S 53.7 FPS @ 320×320, RPi 5 @ 2.9 GHz, mAP 27.0 | ✅ Confirmed from the cited benchmark repo | [Qengineering PP-PicoDet-ncnn](https://github.com/Qengineering/PP-PicoDet-ncnn-Raspberry-Pi-4) |
| YOLO26: released 2026-01-14, NMS-free end-to-end, AGPL-3.0 (+commercial) | ✅ Confirmed. Official paper is [arXiv 2606.03748](https://arxiv.org/abs/2606.03748); doc 11's cited 2510.09653 is a legit third-party YOLO26 survey (Sapkota & Karkee) | [Ultralytics docs](https://docs.ultralytics.com/models/yolo26) |
| VL53L8CX: 8×8 @ 15 Hz, 4×4 @ 60 Hz, 400 cm, I2C/SPI | ✅ Confirmed | [ST datasheet](https://www.st.com/resource/en/datasheet/vl53l8cx.pdf) |
| LEVIO embedded VIO, pure C, open source | ✅ Confirmed — [arXiv 2602.03294](https://arxiv.org/abs/2602.03294), MIT, [ETH-PBL/levio](https://github.com/ETH-PBL/levio), IEEE Sensors Journal 2026 |
| Pegasus v5.1.0 ↔ Isaac Sim 5.1.0 strict pairing (2025-10-26, BSD-3, PX4 SITL backend) | ✅ Confirmed | [Pegasus docs](https://pegasussimulator.github.io/PegasusSimulator/) |
| PX4 OFFBOARD >2 Hz setpoint requirement; COM_OF_LOSS_T / COM_OBL_RC_ACT failsafe params | ✅ Consistent with PX4 docs (stable, pre-2026 facts) |

## 2. Confirmed — landscape & market

| Claim | Verdict | Source |
|---|---|---|
| Robbyant = Ant Group embodied-AI arm; LingBot-VLA 2.0 (6B, Apache-2.0, 2026-07-08), LingBot-World 2.0 (2026-07-09, 1-hour 720p60 world gen), LingBot-Map (streaming 3D recon, Apr 2026), LingBot-VA 2.0; six-model "embodied-native full stack" | ✅ Confirmed | [BusinessWire](https://www.businesswire.com/news/home/20260708757367/en/), [MarkTechPost](https://www.marktechpost.com/2026/07/08/lingbot-vla-2-0/) |
| Robostral Navigate (Mistral, 2026-07-08): 8B, single RGB, pointing-based waypoints, sim-only training, ~22× token-efficient, CISPO online RL, 76.6% R2R-CE val-unseen, cross-embodiment incl. flying | ✅ Confirmed (incl. [Mistral's X announcement](https://x.com/MistralAI/status/2074856309438980145)) | [mistral.ai/news/robostral-navigate](https://mistral.ai/news/robostral-navigate/) |
| AI2 MolmoAct 2 (May 2026, 37× faster than MolmoAct, [arXiv 2605.02881](https://arxiv.org/abs/2605.02881)), Molmo 2-ER (63.8 avg over 13 embodied benchmarks), MolmoSpaces (230k+ scenes / 130k+ assets / 42M grasps) | ✅ Confirmed | [allenai.org/blog/molmoact2](https://allenai.org/blog/molmoact2), [GitHub](https://github.com/allenai/molmoact2) |
| DJI Neo 2: 151 g, Oct 2025 (Asia) / Nov 2025 global (not US), fwd LiDAR + omni monocular + downward IR, voice+gesture control, 19 min, 12MP 1/2", 4K/60 (+4K/100 slo-mo); India grey-market ~₹24–25K | ✅ Confirmed | [DPReview](https://www.dpreview.com/news/4344636762/dji-neo-2-drone-announcement/), [heliguy](https://www.heliguy.com/blogs/posts/dji-neo-2-review-top-10-features/) |
| IZI Mini X Nano: ₹29,999, 249 g, 4K/30 20MP Sony CMOS, 3-axis gimbal, 31 min, 4 km link, manual piloting only | ✅ Confirmed | [izicart.com](https://www.izicart.com/products/izi-mini-x-nano-camera-drone) |
| India nano class (≤250 g): no UIN/registration, no type certificate, no RPC, minimal ops restrictions; Drone Rules 2021 + amendments; DGFT drone import ban since Feb 2022 (components exempt) | ✅ Confirmed — cross-checked 2026-07-15 against multiple independent legal/industry sources (drone-laws.com, QuadX, Patras Law Chambers, FPV-India, UAV Coach), all agreeing on the nano exemptions. The "camera-equipped drones need a UIN regardless of weight" line traces to a **single 2026 blog** with no corroboration and no rule citation — treated as **not credible**. Residual: have counsel eyeball the gazette text once before external marketing claims (ops task Q1, doc 12); Digital Sky FAQ is a JS app and couldn't be fetched directly | [drone-laws.com](https://drone-laws.com/drone-laws-in-india/), [QuadX 2026 guide](https://www.quadxdrones.com/blogs/blogs/drone-laws-india-2026-complete-guide) |
| LFM Open License v1.0: Apache-2.0-based, royalty-free **but free commercial use only < US$10M annual revenue**; paid Liquid agreement above; not OSI | ✅ Confirmed (this **contradicted** two doc lines — fixed, see §4) | [liquid.ai/lfm-license](https://www.liquid.ai/lfm-license), [Liquid docs](https://docs.liquid.ai/lfm/help/model-license) |
| lingbot-vision / lingbot-depth local clones are genuine Robbyant releases (Apache-2.0; arXiv 2607.05247 / 2601.17895; LingBot-Depth accepted ECCV 2026) | ✅ Family + licenses confirmed via Robbyant ecosystem coverage; individual arXiv IDs queued for the long-tail pass |

## 3. Consistent with pre-2026 knowledge (not re-fetched today)

Kokoro-82M (Apache), Moonshine/"Flavors of Moonshine" (Useful Sensors), Silero VAD (MIT), ncps/CfC (Apache-2.0; Science Robotics 2023 LNN drone flight paper), Depth-Anything-V2-Small (24.8M), DW3000/nRF5340 specs, SISFS ₹20L/₹50L structure, DVGFormer + DroneMotion-99K (yunzhong-hou), Gemma 3 270M IFEval 51.2 (Google blog, Aug 2025). All match established facts as of training data; none is load-bearing enough to block P1.

## 4. Corrections applied 2026-07-15

| # | File | Was | Now |
|---|---|---|---|
| F1 | `10_stress_test_and_code_audit.md` §9 (+ pack I-L) | "LFM2.5 + Needle + PicoDet + CfC … correctly licensed (Apache/MIT)" | LFM2.5 is **LFM Open License v1.0** (free commercial < US$10M revenue; paid above) — not Apache/MIT |
| F2 | `01_architecture_overview.md` licensing (+ pack I-C) | "confirm redistribution terms" (open question); "All AI models: Open-source (Apache-2.0/MIT)" | License named + terms resolved; "all Apache/MIT" corrected — LFM2.5 excluded, not OSI |
| F3 | `garuda_master_guide.md` Part 3 (+ pack BOOK II + errata #6) | "LingBot-Depth 2.0 (ViT-Small), ~22M params, HF `lingbot-vision-vit-small`" | Published Depth 2.0 checkpoints are **ViT-L/14 class**; `vit-small` is a backbone only — no small depth model exists |
| F4 | `future-phases/08` §NL-options table | "Tiny tool LM (Needle / 200–350M)" | "Needle **26M**; or 200–350M class" |
| F5 | `GARUDAONE_CONTEXT_PACK.md` header | Version 2026-07-14 | Version 2026-07-15 + validation stamp + TempPX4 warning |

## 5. Local repo-hygiene findings (not doc claims)

1. **`TempPX4/` is checked out at v1.14.0 (Oct 2023).** The plan requires **PX4 ≥ v1.16**, and v1.14 has **no `boards/micoair/`** at all — nothing built from this tree will target the chosen FC. Re-clone/fetch `v1.16.x` (or track `release/1.16`) before any SITL or firmware work.
2. **`lingbot-map/` is empty** and root `lingbot_map_readme.md` was a 0-byte file (now filled with a pointer). LingBot-Map weights/code were announced Apr 2026 — re-check the Robbyant GitHub for the drop.
3. **`PID-data/` filenames are corrupted** ("WhatsApp Image 20266-28…", "…at.38.39…") — harmless but rename before scripting against them.
4. `models/lnn_weights.pt` (11 KB) is the known toy checkpoint — matches the pack's "Toy lnn_weights refuse track" rule. Keep refusing to load it for tracking.
5. `lingbot-depth/example.py` references `robbyant/lingbot-depth-postrain-dc-vitl14-v0.5`, which is absent from its own Model Zoo table — upstream repo bug; verify the exact HF ID before running the example (do not edit the third-party clone).

## 6. Coverage & what remains

- 436 claims extracted → 13 topics: sensors-hw 70, embodied-landscape 49, liquid-lfm 43, india-legal-market 41, px4-fc 40, vision 39, slam-depth 32, vla-wam 30, speech 23, licenses 22, misc 23, lnn-cfc 15, needle 9.
- **Validated today:** every high-priority fact underpinning P1 architecture, licensing, and the investor/market story (§1–§2), each against primary sources.
- **Queued (multi-agent long-tail pass, resumable):** master-guide catalog rows (Parts 14/17 model tables, arXiv IDs like 2605.00870, 2604.19151, 2602.15922, 2604.07427), hardware price spot-checks, and the India camera-UIN primary-source check. The extraction results are journaled; the research fleet hit the session usage cap and can be resumed as-is.
- Community channels: X (Mistral announcement), Reddit/HN surfaced via searches on LFM2.5, YOLO26, and India drone rules; no contradicting community signal found for any confirmed claim.

## 7. Long-tail pass — part 1 (2026-07-15, resumed multi-agent fleet)

75 additional verdicts landed before the session cap: **53 confirmed · 21 partially-correct · 1 refuted**. Topics completed: india-legal-market, liquid-lfm, needle-router (+ partial others). All 21 nuance corrections were reviewed against their cited sources and **applied to the docs + context pack**:

- **HoverAir X1 = 125 g, not 159 g** (only actual refutation; master guide Part 1 reference line — X1 Pro ≈ 191.5 g / ProMax ≈ 192.5 g) — [HoverAir official](https://us.hoverair.com/products/hoverair-x1-self-flying-camera-combo)
- **Official GGUFs live in `LiquidAI/LFM2.5-230M-GGUF`** (companion repo), not the safetensors repo — download-script/G4 hash-pin references updated in docs 02/10/12
- **LFM2.5-VL "~4 FPS" figure is Jetson Orin-class (GPU module), not "production NPU"** — relabeled in docs 02/11; published: 233–242 ms/img Orin, 0.95–2.4 s S25 Ultra; Pi 5 figure remains an internal EST
- **"Voice Control 2.0" is not DJI branding** (plain "voice control"; Apple Watch support arrived via Dec 2025 firmware) — docs 00/07/08
- **DJI grey-market band widened**: entry Mini-class ~₹45–60K, premium ₹90K–₹1.35L (was flat "₹90K–1.2L+"); Neo 2 Indian grey listings ~₹60K vs ~₹25K overseas equivalent — actually *strengthens* the pricing moat — docs 00/07
- **GBNF "zero runtime cost" → negligible per-token overhead**; **Needle "nothing smaller/faster exists" → "nothing comparable found"** (unsupported superlative); Needle tok/s figures are vendor consumer-device numbers, Pi 5 unbenchmarked — docs 11 / fp-05
- **Deleted-code post-mortem math error flagged**: "LFM parse 50–200 ms on Pi 5" is impossible at 42 tok/s decode (real: ≈0.7–2 s per 20–60-token tool call) — garudaone-software/04. **Design implication (already in doc 12): Needle owns the fast path; LFM replies are a "thinking…" moment, not instant.**
- New primary-source confirmations: CISF 22-drone seizure ([Deccan Chronicle](https://www.deccanchronicle.com/southern-states/telangana/cisf-seizes-22-high-end-drones-worth-rs267-lakh-at-rgia-1914982)), DGFT Notification 54 gazette PDF, SISFS ₹20L/₹50L ([seedfund.startupindia.gov.in](https://seedfund.startupindia.gov.in/)), `usermma/LFM2.5-230M-ECE` fine-tune existence (validating doc 08's provenance warning), LFM2.5 family incl. 1.2B + 8B-A1B MoE.
- Minor unresolved nuances (captured, not edited): nano is **≤250 g** inclusive (doc 10 says "under"); IZI has 10+ GPS-assist modes (not "only manual"); original Neo lacks omnidirectional sensing (Neo 2 only); LFM2-VL-3B "robotics demos" softened to unverified in fp-01.

### Part 2 (final pass, same day)

Licenses topic completed (+20 verdicts → **95 total: 67 confirmed / 27 partially-correct / 1 refuted**). New fixes applied:

- **ARM-VO is MIT-licensed, not GPLv3** ([zanazakaryaie/ARM-VO](https://github.com/zanazakaryaie/ARM-VO)) — its removal stands, but on technical grounds (ground-vehicle scale-recovery assumption + gimbal-frame flaw), not license. Corrected in docs 00/01/02/04/08/README + pack.
- **ncnn is BSD 3-Clause, not Apache** (conclusion unchanged: license-clean) — fp-02 ledger row fixed.
- **Needle "single-digit-ms" routing unsupported** — published support is ~50 ms-class per tool call (vendor tok/s figures are consumer-device numbers). Docs 02/08/10/12 + pack relabeled.
- **Doc 12 Q5 narrowed**: Liquid terms are no longer "unresolved" — LFM Open License v1.0 is published (redistribution OK with attribution; <$10M revenue free commercial); what remains is firmware-image redistribution confirmation and >$10M pricing.
- SVO Pro GPLv3, ORB-SLAM3 GPLv3, PicoDet Apache-2.0, ncps Apache-2.0 all re-confirmed.

**Deliberately not swept agent-style** (per owner's call — token economy): the residual long tail is ~340 claim-restatements across sensors-hw/speech/vla-wam/misc, overwhelmingly (a) restatements of the ~35 primary-source-verified pillar facts above, (b) master-guide catalog entries already fenced by its errata banner and "superseded by architecture docs" status, or (c) pre-2025 stable facts (DW3000/nRF5340/IMX678 datasheets, Ego4D, RT-2/OpenVLA/π0 lineage). Spot-check coverage of that tail found one error (HoverAir 159 g) in ~40 checks — error rate low and confined to the deprecated guide.

## 8. Net assessment

The 2026-07-13/14 rebuild plan (doc 12) and P1 contract (future-phases 09) remain **fully actionable**: every component it depends on exists, is currently obtainable, performs as quoted (with the docs' own operating-condition caveats), and is license-viable for a startup below US$10M revenue — with the single strategic note that **shipping LFM2.5 in production firmware needs a Liquid AI conversation** (redistribution + growth beyond the revenue cap) tracked as a pre-production gate, and the DGCA camera-UIN question needs a primary-source answer before any "no registration needed" marketing claim.
