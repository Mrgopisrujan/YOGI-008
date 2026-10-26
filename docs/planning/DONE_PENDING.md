# GarudaOne completion and continuity ledger

> [!NOTE]
> [DOC_STATUS: CURRENT] Maintained product documentation. Validate capability claims against `docs/CURRENT_CAPABILITIES.md` and `docs/IMPLEMENTATION_STATUS.md`.


Last synchronized: **2026-08-15**

This is the canonical restart/resume ledger for the current hardware-evidence and runtime-hardening release. Read [`docs/CURRENT_CAPABILITIES.md`](../CURRENT_CAPABILITIES.md) for user-visible behavior and [`docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md) for evidence classes. Nothing here authorizes physical flight.

## Workspace and release state

- Primary repository checkout: `C:\Projects\DroneOS`
- Release branch: `master`; it tracks `origin/master`. Obsolete runtime/tracking/hardware-asset worktrees and local branches were removed after merge; temporary task worktrees may exist while a change is under review.
- Remote: `https://github.com/SREESAIARJUN/GarudaOne`
- Runtime/tracking release chain: [#2](https://github.com/SREESAIARJUN/GarudaOne/pull/2) merged the tracking tree into `feat/real-runtime-integration`; [#3](https://github.com/SREESAIARJUN/GarudaOne/pull/3) then merged the combined runtime/tracking tree into `master`
- Hardware-policy release PR: [#4](https://github.com/SREESAIARJUN/GarudaOne/pull/4), merged at `0b37a93820bd62f764906d7b77bd23d6068404e0`
- Reproducible CAD-blockout PR: [#5](https://github.com/SREESAIARJUN/GarudaOne/pull/5), merged at `924c59df33c75d94f595aaf104cc2978b225c7a6`
- Final reviewed software tree: `8b1c4c6225ad4b0b5c2fbe465ec0f1aa5640fe2cfd4c15aa5550aec18288a6d1`; independent safety review: **VERDICT: PASS**
- Reviewed hardware-policy tree: `3eda2f9ca4c0895cb3755dcd2a179c93c563169958eda75d7944982179ac660e`; independent review: **VERDICT: PASS**
- Reviewed CAD tree: `2f62202ddfc8aab035b5dcd32fc799dc0810a455b73602865f0c5c029446c536`; independent review: **VERDICT: PASS**
- Current Windows x86/Python 3.11 suite: **800 passed, 3 skipped** on the release tree with all three pinned submodules initialized
- Localization façade/VIO focused suite: **53 passed** on Windows x86/Python 3.11
- Documentation consistency: **111 Markdown files**, with **11 documentation tests** passing
- FlyLens 85 CAD validator: **passed** for 14 STEP solids, a closed 13,212-triangle STL, a correctly scaled GLB, and a complete 1600×1200 PNG; this remains a conceptual blockout, not manufacturing evidence
- Physical-flight status: **BLOCKED**
- Track mode: **disabled**
- Operator takeoff: **implemented and live-SIH verified, not physically qualified**; arm/disarm are implicit only and require PX4 confirmation
- Final PX4 SIH regression: **passed**, 17/17 parameter read-backs, 49 runtime ticks, receiver-confirmed OFFBOARD, no software arming/takeoff
- Operator-cycle PX4 SIH: **passed**, 1.5m target, 1.35m maximum observed, target-tolerance hover, LAND transfer, landed confirmation, and explicit disarm confirmation with pre-wait target-ID and freshness gates in 380 ticks; FDR recorded one successful confirmation

## Current integration boundary

- Authenticated WebSocket commands now reach the live arbiter and return the resulting grant. The same service owns a local browser operator UI and 20Hz runtime loop.
- `land` and `rtl` request PX4 AUTO modes and require command ACK plus independent heartbeat confirmation before OFFBOARD streaming stops. Exact operator takeoff implicitly arms with ACK/heartbeat confirmation, climbs within the configured envelope, times out to LAND, and disarms only after grounded confirmation. Physical behavior remains unqualified.
- Runtime startup directly verifies the hardware-attestation path and its hashed reports; there is no raw hardware-ready boolean.
- The flight profile selects the credential-free C10 RTSP feed for PicoDet/ZipDepth/tracker/scene-graph input, one forward VL53L5CX, and C10 UDP control. Open/read calls use bounded OpenCV/FFmpeg timeouts; malformed sources, userinfo/query credentials, missing timeout support, zero-sized or failed reads, stopped workers, and stale frames fail closed. Deployment preflight requires this typed source plus an FFmpeg-enabled, bounded-timeout, callable OpenCV `VideoCapture` runtime; it no longer requires `picamera2`. The physical feed remains unqualified. Rear/top ToF remain blind because the selected design has no such sensors.
- C10 startup requires a checksummed source-matched inbound status reply. No attitude/encoder feedback is claimed.
- P0 flight enables authenticated text only; `flight.yaml` disables voice and dormant speech code is outside this tracking release.
- The authoritative worker now publishes hash-checked PicoDet, ByteTrack/Kalman, validated LK/CMC, identity/evidence, ZipDepth, and capture-time metadata. Main adds real forward ToF without rebuilding IDs.
- Qualified CfC inference is wired through locked subject arguments, exact executable/expert hashes, finite tensor/state checks, body-to-local-NED conversion, jerk limiting, ToF/governor clamps, bounded C10 yaw speed, PX4 setpoints, and FDR. `flight.yaml` still disables track because no real expert candidate/qualification exists.
- Fail-loud Python VINS-Fusion/ORB-SLAM3 subprocess façades now validate finite sensor input, frame paths/metadata, typed pose/map/loop output, message types, child readiness, lifecycle cleanup, and sticky reader errors with real child-process fixtures on Windows x86. The POSIX process-group path is structurally present but not target-Pi exercised. Native adapter source, binaries, calibrated configs, and active runtime integration are absent. Both upstream engines are GPL-3.0, so any adapter distribution requires an explicit licensing review. Autonomous obstacle-avoidance flight, target-Pi qualification, and physical flight remain unavailable.

## Implemented and verified now

### 1. Complete offline hardware evidence

- Added `SREESAIARJUN/hardware-datasheets-docs` as a git submodule at:
  - `hardware/upstream/hardware-datasheets-docs`
  - commit `43a5a33d88baddca57245422b1cbe953010ffdc5`
- Deployment preflight requires `README.md`, `INDEX.md`, `manifest.yaml`, and `hardware.yaml`, then verifies the exact git revision.
- The evidence repository's offline-link validator is exercised by tests.
- Legacy duplicate PDFs, firmware, and unsigned executables are ignored locally and are not intended for public GarudaOne history. Their redistribution status remains `NOASSERTION`; the pinned evidence repository is the canonical local source.

### 2. Machine-readable selected hardware contract

`garudaone-software/configs/hardware_flylens85.yaml` selects:

- Flight controller: MicoAir743-AIO-35A, original target candidate
- PX4 target: `micoair_h743-aio_default`
- Required firmware marker: `MICOAIR_H743_AIO`
- AIO firmware candidate SHA-256: `85d5b667354e0868b7d0f92d4f4d0c34959dd10753ea10f34c245d120614aa25`
- Companion: Raspberry Pi 5 8GB, dedicated regulated 5V/5A supply required
- Battery: one BETAFPV LAVA 3S 450mAh LiHV; 13.05V maximum; series use forbidden
- ToF: one available forward VL53L5CX, Linux 7-bit address `0x29`, 8×8 at 15Hz, 4m declared maximum; no VL53L8CX unit is available to this build
- GNSS/compass: MicoAir MG-A01
- Optical-flow/range: MicoAir MTF-01
- Receiver: Zerodrag Nexus1 2.4GHz ELRS
- Transmitter target: RadioMaster Pocket ELRS 2.4GHz
- Gimbal/camera: SkyDroid C10 Pro

The contract is design intent. It does not prove the physical labels or wiring.

### 3. Tamper-evident physical attestation

- Added `configs/hardware_attestation.template.yaml`.
- A physical deployment must reference eight local JSON reports:
  - `firmware`
  - `power`
  - `mavlink`
  - `tof`
  - `propulsion`
  - `rc_failsafe`
  - `gimbal`
  - `pi_runtime`
- Preflight resolves every path beneath the attestation directory, rejects traversal, recomputes SHA-256, parses JSON, requires `passed: true`, and enforces gate-specific measured fields.
- A bare `{"passed": true}` report is rejected.
- Reports use strict JSON parsing: duplicate keys and non-standard `NaN`/infinity constants are rejected. Numeric validation also rejects non-finite values, negative ripple/error fractions, and inverted rail minima/maxima.

Project acceptance thresholds encoded today include:

- Pi rail: 4.75–5.25V, no more than 100mV peak-to-peak ripple, at least 600s
- MAVLink observation: at least 600s with battery, estimator, optical flow, range, GNSS, and RC streams
- VL53L5CX: at least 9000 valid frames, at least 10Hz, at most 1% read errors
- Propulsion: verified motor order/direction, named propeller, vibration review, thrust-to-weight ratio at least 2.0
- Pi runtime: Needle 2 decode at least 200 tokens/s, real local LFM smoke, at least 600s, CPU below 80°C

### 4. Needle 2 upgrade

Official source identity:

- Model: `Cactus-Compute/needle2`
- Hugging Face revision: `231364ff02542c4060afb5f4795801e0a09f5107`
- Runtime: `cactus-needle==2.0.0`
- License: Apache-2.0
- Architecture: 45M-parameter Simple Attention Network, CQ2/effective 2.2-bit
- Official artifact statement: 14MB binary, approximately 28MB session RAM, approximately 500 decode tokens/s on Pi 5
- Pinned manylinux ARM64 wheel SHA-256: `6660386292916935188edfe8eef94fbf24712085d7c84f80b0698f79509edde3`

Real Windows native probe performed from the official pinned wheel:

- initialization: 204.02ms
- `hover in place`: 44.23ms, confidence 0.9142
- `land now`: 31.8ms, confidence 0.9671
- cinematography request delegated to LFM
- unsupported weather request returned an empty constrained call
- observed Windows native peak RAM: approximately 49MB

Runtime changes:

- Uses `needle.Needle(...).complete()` instead of the old generic Cactus bundle API.
- Tool grammar contains only `hover`, `stop`, `land`, `rtl`, and `delegate_to_lfm`.
- Empty, malformed, unsupported, multiple, or confidence-below-0.7 calls delegate to the local LFM.
- Direct emergency commands remain deterministic.
- Pi installer downloads the exact native ARM64 wheel, verifies SHA-256, force-installs it over the universal shim, and performs real constrained inference.
- Deployment preflight performs real Needle 2 inference, not an import-only check.

### 5. VL53L5CX production path

- Added `vl53l5cx_driver.py` backed by Pimoroni's ctypes wrapper over ST's ULD.
- Pinned wrapper commit `b1f093a8fa538988315e606d9e9ea6d04392cee3` and ULD submodule commit `59dae4097c86e15366899c2669095d31e983d634`.
- Uses 8×8/15Hz and 7-bit address `0x29`.
- Accepts status 5 at full confidence and statuses 6/9 at reduced confidence per UM2884.
- Corrects both-axis optical orientation.
- Invalid zones cannot authorize clearance.
- Pi installer enables 400kHz I²C and installs/smokes the exact wrapper.
- Legacy VL53L8CX support remains available in software but is not selected and has no available project hardware.

### 6. Real telemetry and fail-closed defaults

- `DroneLink` now parses battery, global position, attitude, velocity, heartbeat, and estimator status.
- Physical startup waits for valid battery and estimator telemetry before OFFBOARD.
- Arbiter telemetry defaults no longer fabricate a healthy battery, CPU temperature, EKF state, ToF clearance, or gimbal heartbeat.
- ToF measured minimum range and confidence now reach the governor.
- ToF read failure becomes blind telemetry rather than a clear-distance value.
- SITL substitutions are explicit through `telemetry_mock_allowed`; the flight profile forbids them.

### 7. PX4/MicoAir parameter correction

The MicoAir AIO board defaults declare 4S/4.2V cells. GarudaOne selects one 3S LiHV pack, so required set-and-read-back parameters now include:

```text
BAT1_N_CELLS=3
BAT1_V_CHARGED=4.35
BAT1_V_EMPTY=3.5
BAT1_CAPACITY=450
EKF2_OF_CTRL=1
EKF2_RNG_CTRL=1
SENS_FLOW_ROT=0
MAV_PROTO_VER=1
```

`EKF2_RNG_CTRL=1` is PX4 v1.17 conditional range aid. GarudaOne does not force range as the global height reference. MTF-01 serial-port selection remains an as-built wiring decision.

### 8. SkyDroid C10 Pro truthfulness

- Opening a UDP socket or succeeding at `sendto()` no longer certifies a connected gimbal.
- Added a benign SD/status probe: transmit `#TPUD2rSDC003E`, require an independently received source-address-matched reply with a valid checksum.
- The physically tested community reference is pinned separately as `skydroid-c10-gimbal-control`; it has no declared license.
- Available evidence confirms RTSP and some UDP commands but reports no exposed motor encoder/IMU telemetry.
- Therefore this implementation proves device liveness only. Closed-loop gimbal attitude and physical motion limits remain hardware gates.

### 9. Read-only hardware qualification harness

`scripts/hardware_qualification.py` provides:

- `mavlink-soak`: observes PX4/MTF-01/MG-A01/RC messages; no actuator commands
- `tof-soak`: reads real VL53L5CX frames without fallback
- `power`: assesses externally captured Pi rail samples and oscilloscope ripple
- `firmware`: validates bytes, exact SHA-256, and required board marker as **artifact-only** evidence; it explicitly records physical recovery/flash fields as false and cannot satisfy the deployment firmware gate

The harness intentionally has no software arm, takeoff, motor-test, or actuator surface.

## Pending: cannot be truthfully completed without physical evidence

### Identity

- Photograph and confirm exact MicoAir AIO PCB/revision.
- Confirm exact FlyLens frame revision and motor-hole/duct geometry.
- Confirm RadioMaster Pocket is the internal ELRS 2.4GHz variant.
- Record serial numbers/labels for every installed part.

### Power and firmware

- Select the exact 5V/5A Pi regulator and gimbal regulator.
- Measure startup/load voltage, current, ripple, brownout behavior, temperature, grounding, and full 13.05V battery conditions.
- Prove DFU recovery, then flash only the target-matched AIO candidate.
- Capture the firmware qualification report and post-flash board/sensor inventory.

### Sensors and communications

- Run the 10-minute Pi↔PX4 UART/MAVLink soak.
- Configure MTF-01 to `Mavlink_PX4`, validate flow/range rates, lighting/texture/dropout behavior, and EKF innovations.
- Validate MG-A01 10Hz GNSS, 3D fix, compass orientation, calibration, and magnetic interference.
- Run the 10-minute VL53L5CX soak and environmental target tests.
- Calibrate camera intrinsics/extrinsics and ZipDepth scale/shift before metric use.

### RC, propulsion, and gimbal

- Validate RC-loss Land behavior, physical kill switch, and manual takeover with companion disconnected and deliberately failed.
- Verify motor mapping/direction with props removed using the FC/GCS safety procedure.
- Thrust-stand the exact QPT/Gemfan/3S combination; measure current, sag, temperature, vibration, thrust margin, AUW, CG, and endurance.
- Validate C10 Pro regulated power, RTSP, status response, bounded movement, reset/power-cycle behavior, and physical motion limits.
- No network protocol currently exposes gimbal attitude feedback; external feedback is required for true closed-loop pointing.

### Models/localization

- Run the pinned Needle 2 and Cactus LFM smoke/thermal soak on the target Pi 5.
- Keep P0 flight text-only. Voice qualification is outside this tracking release.
- GarudaPin prototype is in scope but not gated on physical drone qualification. See STATE.md for the 10-item GarudaPin backlog.
- Collect expert-pilot demonstrations and train/validate a non-synthetic CfC checkpoint; track remains disabled until allowlisted.
- Decide the GPL-3.0 distribution boundary, then build and qualify compatible native VINS-Fusion adapter source/binary/config behind the hardened JSON/stdio façade using the selected existing cameras and sensors, or keep it excluded from the deployment profile; stock upstream executables do not implement this protocol, and no dedicated navigation camera will be added.
- Keep ORB-SLAM3 deployment deferred until its GPL-3.0 licensing boundary, compatible native adapter source/binary/config, and Pi CPU budget are proven behind the hardened façade using only the selected existing sensor set; stock upstream executables do not implement this protocol.
- Exercise the runtime-consumed attestation receipt against the final private as-built evidence directory.

### Flight

- Complete all eight hashed attestation reports.
- Rerun deployment preflight with the as-built attestation.
- Perform propeller-free, tethered, safety-pilot, and staged outdoor gates in that order.

## Reproduce software and evidence checks

```bash
cd C:/Projects/DroneOS/garudaone-software
PYTHONPATH=src python -m pytest -q --tb=short
python scripts/deployment_preflight.py --json

cd C:/Projects/DroneOS
python hardware/upstream/hardware-datasheets-docs/scripts/verify_offline_docs.py
git submodule status
```

Physical qualification examples:

```bash
cd garudaone-software
python scripts/hardware_qualification.py --output reports/mavlink.json \
  mavlink-soak --connection serial:///dev/ttyAMA0:921600 --duration 600
python scripts/hardware_qualification.py --output reports/tof.json tof-soak --frames 9000
python scripts/hardware_qualification.py --output reports/power.json \
  power --samples pi_rail_samples.txt --ripple-mv-pp 60 --duration 600
python scripts/hardware_qualification.py --output reports/firmware.json \
  firmware --path MicoAir743-AIO.bin \
  --sha256 85d5b667354e0868b7d0f92d4f4d0c34959dd10753ea10f34c245d120614aa25 \
  --marker MICOAIR_H743_AIO
python scripts/deployment_preflight.py --require-hardware \
  --hardware-attestation /path/to/hardware_attestation.yaml
```

## Resume procedure after restart/session loss

1. Open this file first.
2. Start from the clean `C:\Projects\DroneOS` checkout. Create a dedicated worktree before making changes.
3. Run `git status --short`, `git branch --show-current`, and `git submodule status`.
4. Read `docs/IMPLEMENTATION_STATUS.md`, `STATE.md`, and `context/SESSION_CONTEXT.md`.
5. Do not declare physical completion from unit/SITL tests.
6. Keep standalone arm/disarm and model-generated takeoff unavailable. Do not run physical takeoff or flash firmware without exact physical identity and recovery evidence.
7. Continue from the first unchecked item in **Release closure** or **Pending**.

## Historical hardware-evidence release closure (superseded snapshot)

The following three closure sections preserve earlier release receipts. Their old test counts and commits are historical; the current release state is recorded at the top of this file.

- [x] Hardware/model/runtime implementation complete for the evidence-available slice
- [x] Focused hardware/model suites green
- [x] Historical full x86 suite green: 619 passed, 3 skipped
- [x] Final hardware evidence validator and submodule checks
- [x] Fail-closed deployment preflight captured (correctly blocked)
- [x] Live PX4 SITL and parameter read-back: 17/17, 49 ticks, PASS
- [x] Changed-file Ruff, syntax, diff, doc-link, security, and tool-surface gates
- [x] Independent safety reviewer verdict consumed: PASS for tree `d4c48ac261eabb0b7945508f45657a1e7e458e57`
- [x] Historical final full suite after that source write: 619 passed, 3 skipped
- [x] Reviewed implementation commit created: `42f08c1e934e99fdf5a68e799e88b48ce0c8c910`
- [x] Reviewed implementation pushed to `origin/master`
- [x] Remote reviewed-implementation SHA equals local SHA

## Historical corrective review closure (superseded snapshot)

- [x] Require at least 1 Hz `ESTIMATOR_STATUS` or `EKF_STATUS_REPORT` in physical MAVLink evidence
- [x] Require the qualification harness itself to observe estimator status at ≥1Hz and exact boolean ToF heartbeat evidence
- [x] Reject non-finite Needle 2 smoke confidence
- [x] Reject non-finite MAVLink/power/ToF qualification inputs and prohibit non-standard JSON output
- [x] Correct Skydroid UDP documentation and print the required hardware-attestation path in Pi guidance
- [x] Focused corrective suite green: 31 passed
- [x] Historical full corrective suite green: 619 passed, 3 skipped
- [x] Independent corrective safety review consumed: PASS for tree `929a3092bfd7898c15aa065876178cdad6f02132`
- [x] Corrective commit pushed to `origin/master`: `f250fca0f9cb4a818b6b4ade66c992571f858df8`
- [x] Final corrective SHA verified through local Git, `origin/master`, and GitHub API

## Historical documentation reconciliation closure (superseded snapshot)

- [x] Inventory every tracked first-party Markdown file
- [x] Add explicit current, historical, reference, procedural, or generated status markers
- [x] Add the canonical current-capabilities dossier
- [x] Reconcile root, runtime, hardware, architecture, roadmap, guide, and session entry points
- [x] Mark Needle 26M as historical; mark MAVSDK as historical; mark the three-VL53L8CX design, voice, and autonomous-flight-era material as historical where retained
- [x] Add a complete documentation index and machine-readable inventory
- [x] Add repository, staged-change, link, pin, count, and freshness validation
- [x] Add local pre-commit and GitHub Actions documentation hooks
- [x] Run final documentation checker, stale-claim scans, writing scan, shell/Python validation, and independent Codex review
- [x] Commit after human approval: `c1c9d4c7601e317b8b04c6e73922cb6f88813374`
- [x] Push the reviewed implementation and verify local Git, `origin/master`, and GitHub API equality

## Current master release closure

- [x] Runtime/tracking releases merged through PRs #2 and #3
- [x] Sameer research-reference integration merged through PR #1
- [x] Hardware/sensor/localization truth merged through PR #4
- [x] Reproducible FlyLens 85 conceptual CAD blockout merged through PR #5
- [x] Current release-state documentation merged through PR #6
- [x] Localization subprocess façade hardening merged through PR #7
- [x] Bounded C10 RTSP perception source implemented and host-verified
- [x] Deployment preflight verifies the selected C10/OpenCV runtime contract instead of `picamera2`
- [x] Exact-tree independent reviews passed for software, hardware policy, and CAD
- [x] Current Windows suite green: 800 passed, 3 skipped
- [x] Localization façade/VIO focused suite green: 53 passed
- [x] Documentation consistency green across 111 Markdown files; 11 documentation tests passed
- [x] Current `master` and `origin/master` synchronized; merged release branches and worktrees removed
- [ ] Physical identity, power, sensor, RC, propulsion, gimbal, target-Pi, attestation, and staged-flight evidence remain required
