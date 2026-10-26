# GarudaOne future phases and research

> [!NOTE]
> [DOC_STATUS: CURRENT] Current roadmap index. The numbered reports are dated proposals, not deployed capabilities.

Current behavior and remaining software are in [`../docs/CURRENT_CAPABILITIES.md`](../CURRENT_CAPABILITIES.md). Exact physical acceptance gates are in [`../DONE_PENDING.md`](../planning/DONE_PENDING.md).

## Baseline before using these plans

- Needle 2 is the active 45M constrained router; Needle 26M is historical.
- The integrated runtime supports neutral hover and PX4-confirmed Land/RTL transfer; physical behavior remains unqualified.
- Physical Land/RTL actions, WebSocket-to-runtime execution, tracking, obstacle avoidance, gimbal integration, voice, and the operator app remain incomplete.
- The selected sensor is one forward VL53L5CX, not a three-sensor VL53L8CX array.
- Track is disabled until expert CfC data and staged validation exist.
- Physical flight remains blocked by eight hashed reports.

The reports below were written in July 2026 and contain alternatives or ambitions that were later rejected, deferred, or only partially implemented. Their opening historical notices control whenever text conflicts with the current baseline.

## Dated documents

| # | Document | Use today |
| --- | --- | --- |
| 01 | [Embodied AI landscape](01_embodied_ai_landscape_2026.md) | Candidate/research background |
| 02 | [Production transfer playbook](02_production_transfer_playbook.md) | Adoption and license considerations |
| 03 | [Roadmap to production](03_phase_roadmap_to_production.md) | Historical phase plan; re-baseline before execution |
| 04 | [Compute and form-factor ladder](04_compute_and_form_factor_ladder.md) | Future hardware options |
| 05 | [UX and safety principles](05_ux_safety_product_principles.md) | Product principles, not current UI evidence |
| 06 | [Pipeline and LFM-VL analysis](06_pipeline_and_lfm_vl_deep_dive.md) | Research background |
| 07 | [Advancements and leads](07_full_advancements_and_leads_catalog.md) | Candidate catalog |
| 08 | [Open-ended reassessment](08_open_ended_reassessment.md) | Dated reprioritization |
| 09 | [Investor prototype definition](09_investor_prototype_definition.md) | Historical prototype target, not current demo proof |

## Current next software slices

1. Bridge authenticated WebSocket requests to the runtime arbiter.
2. Implement verified PX4 Land and RTL execution.
3. Consume a verified attestation receipt at runtime.
4. Integrate selected perception and C10 modules.
5. Train and allowlist expert CfC weights.
6. Add the text operator UI, then voice.

Physical work remains gated by the hardware ledger.
