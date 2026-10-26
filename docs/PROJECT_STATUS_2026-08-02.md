# GarudaOne project status report — 2026-08-02

> [!NOTE]
> [DOC_STATUS: HISTORICAL] Dated integration record. Read [`CURRENT_CAPABILITIES.md`](CURRENT_CAPABILITIES.md) for current behavior and evidence.
>
> Current outcome (2026-08-15): This report records the `sameer` branch integration against `fc0d1d9` on 2026-08-02. Its counts, hardware assumptions, and runtime claims are historical and do not supersede current release documentation.

## Executive result

The repository's current mainline was merged into the local `sameer` branch without conflicts. The GitHub repository does not have a `main` branch: its default branch and `origin/HEAD` are `master`, so `origin/master` was used as the requested mainline.

The merged project passes all 571 collected tests (568 passed, 3 skipped), runs real ZipDepth ncnn inference, configures 9/9 PX4 parameters against the official SITL image, and completes the non-arming live SITL harness. It is not ready for Pi 5 deployment or physical flight because the required Cactus runtime, complete LFM bundle, expert-trained CfC checkpoint, native localization adapters, and hardware validation remain unavailable.

This integration is local only. No remote branch was pushed.

## Branch integration

| Item | Result |
|---|---|
| Remote repository | `https://github.com/SREESAIARJUN/GarudaOne.git` |
| Remote default branch | `master` (there is no `main` ref) |
| Common ancestor | `2269c30` |
| Previous local/remote `sameer` tip | `2662f24` |
| Fetched mainline tip | `fc0d1d9` |
| Integration merge | `1b5cb04` |
| Merge conflicts | None |
| Original primary-worktree change | Untracked `assets.zip` retained untouched |

Before the merge, the branches differed as follows:

- `sameer`: 3 unique commits, 132 added paths, 18,016 inserted lines.
- `origin/master`: 2 unique commits, 84 changed paths, 3,205 insertions and 3,245 deletions.
- The merged branch contains both histories and is four commits ahead of `origin/master` before this report/fix commit.

### Preserved `sameer` work

The three original `sameer` commits remain in history:

1. `ef4a1d1` — 38 research/asset Markdown files.
2. `8915921` — 53 `hermes-team-share` files containing inventories and private skills.
3. `2662f24` — 40 added root skill files moved from `.kiro/skills` into `skills/`.

The post-merge trees under `assets/`, `hermes-team-share/`, and `skills/` are byte-for-byte unchanged from the pre-merge `sameer` branch. The merged tree contains 38 asset files, 53 Hermes-share files, and 44 root skill files in total (40 branch additions plus 4 pre-existing files).

## What is new from mainline

The fetched mainline adds two commits from 2026-07-23:

- `afd9a1b` — `feat: harden GarudaOne runtime and align verified docs`
- `fc0d1d9` — `fix: close independent review blockers`

Major changes brought into `sameer`:

- Runtime/PX4 hardening: real heartbeat requirements, continuous setpoint streaming, OFFBOARD confirmation through both `COMMAND_ACK` and heartbeat state, current PX4 parameter names/values, and fail-closed preflight evidence.
- Safety truth: FDR writability is checked before OFFBOARD; command authentication fails closed; shutdown records the observed armed state and OFFBOARD-exit request without claiming a disarm; model tools do not expose arm/takeoff/disarm/kill.
- Command-path fixes: the runtime forwards command tokens, emergency commands use deterministic parsing, and WebSocket rate limiting uses the server-observed peer rather than caller-provided identity.
- Perception/localization truth: ZipDepth is explicitly relative rather than metric, the VL53L8CX path uses ST's ULD wrapper, MAVLink ODOMETRY fields/frames were corrected, and missing VINS/ORB native adapters are called out as blockers.
- Model policy: no llama.cpp production fallback, Cactus is required on the target, the current LFM directory is recognized as incomplete, and the synthetic CfC checkpoint cannot authorize tracking.
- Deployment tooling: a fail-closed deployment preflight script, VL53L8CX ULD installer, Pi guide updates, current PX4 configuration, and two declared Git submodules.
- Documentation: `docs/IMPLEMENTATION_STATUS.md` is now the authoritative deployment/status document and replaces earlier overclaims.
- Test coverage: new runtime-truth, PX4 parameter, VIO odometry, and voice-interface tests.

New mainline paths include `.gitmodules`, `docs/IMPLEMENTATION_STATUS.md`, `scripts/deployment_preflight.py`, `scripts/install_vl53l8cx_uld.sh`, and four new unit-test modules.

## Project details

GarudaOne is an offline conversational aerial-director drone runtime. It targets a Raspberry Pi 5 companion computer connected to a PX4 flight controller.

Authority is intentionally layered:

1. RC/hardware kill switch has highest authority.
2. PX4 owns hard real-time estimation, PID loops, and flight-controller failsafes.
3. The deterministic GarudaOne arbiter owns flight modes, governors, watchdogs, and setpoint clamps.
4. Language, perception, and CfC components remain advisory.

The software is Python 3.11+ and currently reports package version `0.1.0`. The merged repository contains approximately 950 tracked paths and 675 MB of tracked blobs. The software subtree contains 53 Python source files (about 10,910 lines), 27 test modules, 18 Python scripts, and 629 tracked model/artifact files.

Implemented x86/SITL paths include the arbiter, FDR, pymavlink transport, text command server, PicoDet ncnn, ByteTrack-lite, ZipDepth ncnn, NumPy CfC inference, Skydroid packet generation, and MAVLink ODOMETRY serialization.

## Verification performed

Environment: Windows x86-64, Python 3.11.15, pytest 8.4.2.

| Check | Result |
|---|---|
| Git fetch/integrity | Passed; `origin/master` fetched to `fc0d1d9`; object connectivity valid |
| Merge | Passed without conflicts |
| Preserve `sameer` trees | Passed; no differences in `assets`, `hermes-team-share`, or `skills` |
| Full Python suite | **568 passed, 3 skipped** in 106.62 seconds |
| Worker multiprocessing class | 4/4 passed after timing-bound correction |
| ZipDepth ncnn | Passed; two frames, relative-depth semantics preserved, mean 88.57 ms |
| PX4 parameter setup | Passed; 9/9 set and read back |
| Live PX4 SITL harness | Passed; 29 ticks, 1 command, 1.5 s uptime, FDR written |
| Deployment preflight | Failed as designed on unresolved production gates |
| Ruff | 297 existing findings; 235 are reported auto-fixable |
| Strict mypy | 140 existing errors across 34 of 53 source files |

### Test timing correction

`TestPerceptionWorkerMultiprocessing.test_worker_heartbeat` used a two-second deadline even though neighboring real-inference worker tests allow ten seconds. On this Windows host, process spawn, PicoDet/ZipDepth loading, and first inference completed just after two seconds; the child published a result after the parent deadline. The test now uses the established ten-second bound and a diagnostic assertion message. The complete suite then passed.

### Live run evidence

The official image `px4io/px4-sitl:v1.18.0-beta1` was used at digest:

`sha256:bab4270c4849b7027df4bd760c79d743d738c81d7830dde14c4cc5714f781216`

The harness never armed or took off. It verified heartbeat, OFFBOARD acknowledgement/state, neutral setpoint streaming, a text `land` command, link health, and FDR output. The generated FDR is under the ignored `garudaone-software/flight_logs/` directory. The temporary container was stopped and removed; the image remains cached. Docker Desktop was stopped afterward.

### Deployment preflight result

Passed checks:

- Python 3.11
- pymavlink and ncnn imports
- Needle Cactus v2 bundle structure
- PicoDet and ZipDepth model parameters

Blocking checks:

- Cactus Python/native runtime is absent.
- The LFM Cactus directory lacks a runnable component manifest.
- The bundled CfC checkpoint is synthetic, not an expert-trained flight candidate.
- VINS-Fusion and ORB-SLAM3 native JSON/stdio adapters remain absent (optional in the script, but required before those deployment profiles are claimed).

## Current risks and gaps

### Release blockers

1. Build and smoke-test Cactus v2 on Pi 5 ARM64.
2. Replace the incomplete LFM directory with a complete runnable Cactus v2 bundle.
3. Install a local Cactus speech bundle if voice control is required.
4. Train the CfC policy on expert-pilot demonstrations and validate it with a safety pilot.
5. Build or remove the missing VINS/ORB native adapter expectations.
6. Validate VL53L8CX, camera/IMU, PX4 UART, gimbal, RC/kill behavior, thermals, and latency on physical hardware.
7. Calibrate camera intrinsics/extrinsics and ZipDepth scale/shift before any metric safety use.

### Engineering quality debt

- Ruff is configured but not clean: 297 findings remain across source, tests, and scripts.
- Strict mypy is configured but not clean: 140 errors remain, including missing target-only stubs, Windows/POSIX API mismatches, incomplete annotations, and several real interface inconsistencies.
- No CI workflow is committed under `.github/workflows`, so the stated CI preflight evidence cannot be reproduced automatically from this repository alone.
- Dependency files use version ranges rather than exact pins and there is no lockfile, despite a comment claiming CI reproducibility. The successful environment resolved newer packages such as Torch 2.13.0, NumPy 2.4.6, and ncnn 1.0.20260526.
- No top-level license file is present, although `pyproject.toml` declares the package proprietary.
- The two Git submodules are declared but were not initialized for this validation; the tested runtime paths use the bundled model/runtime files.

## Recommended next actions

1. Review this local integration and push `sameer` only after approval.
2. Add a reproducible dependency lock and a Windows/Linux CI matrix that runs pytest, Ruff, mypy, deployment preflight, and artifact checks.
3. Triage Ruff/mypy findings separately from flight-feature work.
4. Initialize and pin the declared submodules in the deployment workflow.
5. Keep track mode and physical flight disabled until every production preflight and hardware gate is satisfied.
