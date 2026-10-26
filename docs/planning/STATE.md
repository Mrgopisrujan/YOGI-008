# GarudaOne state

> [!NOTE]
> [DOC_STATUS: CURRENT] Short restart status. Read [`docs/CURRENT_CAPABILITIES.md`](../CURRENT_CAPABILITIES.md) for behavior and [`DONE_PENDING.md`](DONE_PENDING.md) for acceptance gates.

Last synchronized: **2026-09-05**

## Release state

- Primary repository checkout: `C:\Projects\DroneOS`.
- Release branch: `master`. Reviewed feature work uses temporary worktrees; merged worktrees and branches are removed after closure.
- The current repository line includes Sameer research references, runtime/tracking, hardware policy, CAD, release documentation, localization hardening, and C10 RTSP perception changes. Individual merge records remain in Git history.
- Current Windows x86/Python 3.11 full suite: **800 passed, 3 skipped** with all three pinned submodules initialized.
- Localization façade/VIO focused suite: **53 passed** on Windows x86/Python 3.11.
- Documentation consistency: **111 Markdown files** and **11 documentation tests**, passed.
- FlyLens 85 CAD validation: **passed** for 14 STEP solids, a closed 13,212-triangle STL, a correctly scaled GLB, and a complete 1600×1200 preview. This is a conceptual blockout only.
- Live PX4 SIH candidate verification: 17/17 parameter read-backs plus independent non-arming Land and RTL transfers passed.
- Live operator-cycle SIH: 1.5m target, 1.35m maximum observed, target-tolerance hover, PX4 LAND transfer, landed confirmation, and external-command disarm passed with pre-wait target-ID and freshness gates in 380 ticks; FDR recorded one successful disarm confirmation.
- Prior neutral-hover SIH baseline: 17/17 parameter read-backs, 49 ticks, OFFBOARD confirmed, no software arm/takeoff.
- Hardware evidence submodule: `43a5a33d88baddca57245422b1cbe953010ffdc5`.
- Physical flight: **blocked**.

## Simulation test results

- mavlink-routerd built from source: `/tmp/mavlink-router/build/src/mavlink-routerd` (commit `2362c62`)
- Router config: UDP endpoint on `0.0.0.0:14550`, forwards to PX4 SITL on `udp:127.0.0.1:14280`
- Verified pymavlink end-to-end (WSL2 → mavlink-routerd → PX4 SITL):
 - HEARTBEAT received (type=0, PX4 heartbeat)
 - NAV_TAKEOFF sent → COMMAND_ACK received (cmd=22, result=0)
 - NAV_LAND sent → COMMAND_ACK received (cmd=21, result=0)
 - NAV_RTL sent → COMMAND_ACK received (cmd=20, result=0)
- Node.js bridge (`sitl_bridge.js`) built and tested on TCP 8766 → mavlink-routerd UDP 14550
- Windows→WSL2 UDP blocked at hypervisor layer; all tests run from WSL2
- PX4 broadcast param (`MAV_1_BROADCAST=1`) confirmed active
- Gazebo Harmonic installed and running with X3 quadcopter world
- Gazebo bridge (`scripts/gz_bridge.js`) connects TCP 8766 → Gazebo Harmonic twist topics
- Verified Gazebo flight: takeoff, hover, land commands confirmed via odometry
- LFM path: Needle/LFM text → JSON tool call → TCP 8766 → Gazebo topic → drone motion
- Perception pipeline (PicoDet + ByteTrack + ZipDepth) tested on 380-frame real drone video (clip.mp4, 1920×1080 @ 30fps, 12.67s):
 - Person detection: 85.3% frame rate, avg confidence 55.9%, p95 71.4%, latency 10.2ms mean
 - ByteTrack: 80.5% frame rate with active tracks, avg primary confidence 55.8%, 0 id-switches
 - ZipDepth: 99.99% valid pixels, mean depth 122.6m (simulated altitude), 1.0 FPS CPU inference
 - End-to-end pipeline: 96.2 FPS mean, 11.1ms mean latency, 53.9% LFM target lock rate
 - LFM natural language integration: Needle intent → tool call → target acquisition verified
 - Evidence: `results/perception/combined_report.json`, `results/perception/viz/` (3 plots)

## Product scope

GarudaOne now includes the **GarudaPin** wearable voice-control interface in its product definition. GarudaPin is not the drone's primary flight controller — it is a voice capture and emergency-control bridge between the user and the drone:

- **WaveShare ESP32-S3-Touch-AMOLED-2.16** is the active prototype board: dual PDM microphones with ES8311 codec, BLE 5, AXP2101 PMU, QMI8658 IMU, 2.16" AMOLED display.
- GarudaPin streams 16 kHz 16-bit PCM audio over BLE GATT to the user's smartphone. It does not run STT on-device.
- The smartphone companion app runs Indic Whisper (small quantized) for on-device speech-to-text with single-pass translation to English, then forwards structured JSON intent to the drone over 5.8 GHz Wi-Fi.
- **Spectrum split**: GarudaPin uses 2.4 GHz BLE exclusively for audio streaming; phone-to-drone command/telemetry and FPV video use 5.8 GHz Wi-Fi to avoid 2.4 GHz interference.
- **Emergency button (GPIO18)**: bypasses the phone and app entirely. Sends a direct BLE command to the drone Pi for RTL (short press), LAND (long press ≥3s), or HOVER (double press). This is a deterministic path that does not depend on STT, phone link, or app state.
- GarudaPin firmware (ESP-IDF) is architectural intent only — no code has been committed yet.

## Current product truth

- Needle 2 is the active router: 45M parameters, `cactus-needle==2.0.0`, revision `231364ff02542c4060afb5f4795801e0a09f5107`.
- Active flight transport is pymavlink, not MAVSDK.
- Active ToF is one forward VL53L5CX, not a three-sensor VL53L8CX array; the 5-series device is selected because 8-series hardware is unavailable to this build.
- `cad/` contains a reproducible FlyLens 85 envelope/placement blockout and validator. It is not an as-built model, manufacturing drawing, print-ready airframe, or physical evidence.
- The integrated service sends authenticated WebSocket commands through the live runtime arbiter, returns grants/rejections, and hosts a local browser UI while ticking at 20Hz.
- Neutral zero-velocity hover remains the default safe integrated behavior outside qualified track operation.
- Land and RTL request PX4 modes, require `COMMAND_ACK` plus matching heartbeat confirmation, and stop OFFBOARD streaming only after transfer succeeds. Exact operator takeoff implicitly arms with ACK/heartbeat proof, climbs at a bounded rate/altitude, and times out to LAND. Landing disarms only after PX4 confirms grounded. Physical behavior remains unqualified.
- Runtime flight startup consumes a path-based, SHA-256-bound hardware attestation receipt; callers cannot assert a raw `hardware_attested` boolean.
- The flight profile uses the selected C10 RTSP feed for PicoDet/ZipDepth/tracker/scene-graph input, one forward VL53L5CX, and the C10 UDP control backend. RTSP open/read calls are bounded and invalid or stale frames fail closed. Deployment preflight verifies the typed C10 profile plus OpenCV FFmpeg, `VideoCapture`, and timeout capabilities instead of requiring `picamera2`. The physical feed remains unqualified, and missing rear/top ToF directions remain explicitly blind.
- P0 `flight.yaml` disables voice and accepts authenticated text commands only. Dormant voice code was not changed by the tracking work.
- Track mode remains disabled in `flight.yaml`, but the production path now uses hash-checked PicoDet, two-pass person-only ByteTrack, box Kalman filtering, validated LK flow, affine camera-motion compensation, locked identities, complete worker packets, and same-tick stale/ambiguous/lost denial.
- A qualified CfC path builds all 12 inputs, binds the exact executable artifact and expert evidence, validates finite tensor shapes without poisoning state, rotates body velocity into local NED, applies jerk limiting/ToF/governor clamps, drives bounded C10 yaw speed, and records exact FDR identity/evidence/hash data.
- Hardened fail-loud Python VINS-Fusion and ORB-SLAM3 subprocess façades validate finite inputs, output schemas, child readiness/lifecycle, and sticky protocol errors with real child-process fixtures on Windows x86. The target-Pi/POSIX path remains unexercised. Native adapter source, binaries, calibrated configs, and active runtime integration remain unavailable; stock upstream executables do not implement the custom protocol, and GPL-3.0 distribution requires review. Any deployed VIO/SLAM path must use the available sensors; no dedicated navigation camera will be added. Physical closed-loop C10 attitude feedback also remains unavailable.

## Safety boundaries

- No standalone arm, disarm, kill, motor-test, or raw-actuator tool exists. Takeoff is an exact authenticated operator-only route; it is not available to Needle/LFM and performs arm implicitly.
- Real flight profiles forbid mock telemetry and mock ToF.
- Battery, estimator, CPU, ToF, gimbal, and attestation evidence fail closed.
- A state transition, unit test, SITL result, checksum, or model-card claim is not physical-flight evidence.

## Remaining work

Software before physical flight:

1. Exercise the exact C10 RTSP feed, PicoDet, ZipDepth, Needle, and LFM bundles on the target Pi 5.
2. Collect, hash, train, validate, independently approve, and qualify a real expert-pilot CfC dataset/checkpoint before enabling track.
3. Complete the native VIO/localization path required for autonomous motion, or keep it excluded from the production profile.
4. Run hardware-in-the-loop takeoff/implicit-arm/disarm plus Land/RTL fault-injection regressions against current `master` or an explicitly named HIL candidate derived from it; live PX4 SIH is complete.

### GarudaPin (wearable voice interface — prototype)

5. Implement ESP-IDF firmware on WaveShare ESP32-S3-Touch-AMOLED-2.16: AMOLED UI, ES8311 audio capture at 16 kHz, BLE GATT service for PCM streaming, GPIO18 emergency-button handler, QMI8658 gesture detect, AXP2101 battery gauge.
6. Implement BLE GATT client on Pi 5 (bleak/BlueZ): receive 16 kHz PCM, validate framing, forward PCM chunks to the phone over 5.8 GHz Wi-Fi.
7. Implement phone companion app: Indic Whisper small/quantized STT with `--task translate` for Indic-to-English, intent parser, structured JSON to drone. Bench latency and accuracy across target Indic languages on reference mid-range Android hardware.
8. Wire emergency-button BLE path into the arbiter as a first-class command channel (independent of WebSocket / phone path).
9. Validate GarudaPin battery endurance, BLE range (50m LOS), and acoustic SNR under prop-wash conditions at the bench.
10. Package GarudaPin as a removable P0-from-flight workstream — physical drone qualification is not gated on GarudaPin readiness.

Hardware work remains in [`DONE_PENDING.md`](DONE_PENDING.md): identity, regulators, firmware/recovery, UART and sensor soaks, RC failsafe, propulsion, gimbal limits, target-Pi thermal/model evidence, calibration, and staged flight.

## Documentation rule

Any source, config, model, hardware, safety, or user-facing behavior change must update the matching current docs in the same change. Run:

```bash
python scripts/check_docs_consistency.py
python scripts/check_docs_consistency.py --staged
```
