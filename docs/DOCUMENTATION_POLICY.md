# GarudaOne documentation policy

> [!NOTE]
> [DOC_STATUS: CURRENT] This policy defines documentation authority, status markers, and the checks that keep docs synchronized with code.

## Authority order

When documents disagree, use this order:

1. Current code, schemas, configs, tests, and inspected live evidence.
2. [`CURRENT_CAPABILITIES.md`](CURRENT_CAPABILITIES.md) for product behavior and interaction.
3. [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) for implementation evidence.
4. [`../DONE_PENDING.md`](planning/DONE_PENDING.md) for exact acceptance gates and restart continuity.
5. [`../hardware/HARDWARE_INTEGRATION_STATUS.md`](../hardware/HARDWARE_INTEGRATION_STATUS.md) for the selected hardware contract and physical closure.
6. Current subsystem guides.
7. Dated architecture, research, roadmap, and context documents.

A historical document can explain why a choice was considered. It cannot override current code or current-status documents.

## Required status markers

Every tracked first-party Markdown file is classified in `documentation_inventory.json` and must contain one marker near the top:

| Marker | Meaning |
|---|---|
| `[DOC_STATUS: CURRENT]` | Maintained product or subsystem truth. |
| `[DOC_STATUS: HISTORICAL]` | Dated research, design, or plan. Superseded claims may remain for provenance. |
| `[DOC_STATUS: REFERENCE]` | Narrow hardware/configuration reference with explicit evidence boundaries. |
| `[DOC_STATUS: PROCEDURAL]` | Repository workflow or agent procedure, not a product claim. |
| `[DOC_STATUS: GENERATED]` | Run log or budget record, not a source of product truth. |

Historical files must link to `CURRENT_CAPABILITIES.md` in their opening notice. Old model names, transport choices, sensors, estimates, and planned capabilities are retained only inside that boundary.

## Evidence wording

Use these labels consistently:

- **Exercised:** the production path or external process ran and output was inspected.
- **Structurally validated:** schemas, tests, or loopback contracts passed without the target device.
- **Implemented, not integrated:** code exists but the active runtime does not use it end to end.
- **Hardware blocked:** closure requires the assembled aircraft or target Pi.
- **Disabled:** the product deliberately refuses the capability.
- **Historical:** dated research or design, not current product behavior.

Do not turn model-card claims into measured results. Do not describe SIH/SITL as physical flight. Do not call an internal FSM transition a completed physical action unless the runtime sends and verifies that action.

## Documentation update matrix

A change is incomplete until the matching docs are updated.

| Change | Required documentation |
|---|---|
| User-visible capability or limitation | `CURRENT_CAPABILITIES.md`, `IMPLEMENTATION_STATUS.md`, root `README.md` if surface-level |
| Command/tool schema or interaction path | `CURRENT_CAPABILITIES.md`, `garudaone-software/README.md` |
| Model, runtime, revision, license, artifact hash | `CURRENT_CAPABILITIES.md`, `DONE_PENDING.md`, `context/SESSION_CONTEXT.md`, installer guide |
| Hardware selection, pinout, or evidence threshold | Hardware status, capabilities, ledger, BOM/reference |
| Safety boundary, watchdog, arbiter, or flight action | Capabilities, implementation status, safety docs, ledger |
| Test count or release evidence | `IMPLEMENTATION_STATUS.md`, `STATE.md`, `DONE_PENDING.md`; do not copy counts into historical docs |
| Completed roadmap item | Current status plus the roadmap's opening overlay or delivered-outcome section |
| New Markdown file | `documentation_inventory.json` and `DOCUMENTATION_INDEX.md` |
| New physical evidence | Hardware status and hashed attestation; never only a prose claim |

## Automated checks

Run from the repository root:

```bash
python scripts/check_docs_consistency.py
python scripts/check_docs_consistency.py --staged
```

The checker verifies:

- every tracked or newly added Markdown file is inventoried;
- every file has the declared status marker;
- historical product docs link to current capabilities;
- active docs contain the current Needle 2/runtime and selected VL53L5CX facts where required;
- current docs do not present Needle 26M, MAVSDK, three active VL53L8CX sensors, voice, or physical readiness as current behavior;
- canonical test counts and immutable pins are synchronized;
- relative Markdown links resolve;
- source/config/model/hardware changes staged without required documentation updates fail.

## Local hook

Install the repository hook once:

```bash
bash scripts/install_git_hooks.sh
```

This sets `core.hooksPath=.githooks`. The pre-commit hook runs the staged documentation check. It does not modify files.

## CI hook

`.github/workflows/docs-consistency.yml` runs the same checker on pushes and pull requests. CI also checks the changed file range so capability-bearing code cannot land without a current-document update.

## Agent rule

`AGENTS.md` requires agents to classify documentation impact before completion. Agents must update the required docs in the same change, run the checker, and report the evidence class. A green test suite does not excuse stale docs.

## Historical preservation

Do not rewrite dated research to pretend it predicted the current system. Add or maintain the historical marker, preserve sources and decision context, and add a delivered-outcome section when the research recommendation was accepted, rejected, or superseded.

## Review receipt

The inventory records the files reviewed through the 2026-08-15 release-state and CAD reconciliation. A file can be unchanged in later work only when its classification and claims remain valid. The checker prevents silent additions outside the inventory.
