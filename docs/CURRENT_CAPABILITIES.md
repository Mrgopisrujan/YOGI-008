# GarudaOne current capabilities

> [!NOTE]
> [DOC_STATUS: CURRENT] This is the canonical product-capability summary. It describes the code and evidence available on 2026-08-15. It does not authorize physical flight.

## Product definition

GarudaOne is an offline aerial-director runtime for a Raspberry Pi 5 companion computer and a PX4 flight controller. Language and perception models may propose high-level actions. A deterministic arbiter, PX4, and the human pilot retain control authority.

The current release is a safety-constrained software and SITL prototype. It is not a finished autonomous camera drone.

GarudaOne includes the **GarudaPin** wearable voice-control interface as a planned prototype. GarudaPin is an ESP32-S3-based device that streams voice over BLE to a smartphone; the phone runs on-device speech-to-text and translates to English. An emergency button on GarudaPin sends deterministic RTL/LAND/HOVER commands directly to the drone, bypassing the phone entirely.

## Evidence vocabulary

| Label | Meaning |
|---|---|
| Exercised | The production path or external process ran and its output was inspected. |
| Structurally validated | Code, schemas, tests, or loopback contracts passed without the target physical device. |
| Implemented, not integrated | A module exists but the active runtime does not call it end to end. |
| Hardware blocked | Completion needs the assembled aircraft or target Raspberry Pi. |
| Disabled | The code deliberately refuses the capability. |
| Historical | A dated design or research option, not current product behavior. |

## Release snapshot

- Full Windows x86/Python 3.11 release-tree suite: **800 passed, 3 skipped** with all three pinned submodules initialized.
- Prior cross-cutting corrective safety suite: **31 passed**.
- Current localization façade/VIO focused suite: **53 passed**.
- PX4 SIH: 17/17 parameter read-backs plus independent receiver-confirmed Land and RTL transfers, with no software arming or takeoff.
- Operator-cycle PX4 SIH: 1.5m target, 1.35m maximum observed, target-tolerance hover, pre-wait target-system/component proof, PX4 LAND transfer, grounded evidence, and confirmed disarm passed in 380 ticks; FDR recorded exactly one successful disarm confirmation.
- Physical flight: **blocked**.
- Track mode: **disabled**.
- Operator takeoff: **implemented and live-SIH verified, not physically qualified**. Arm/disarm are implicit only; there are no standalone arm/disarm tools.
- Deployment preflight: the selected C10 RTSP profile and installed OpenCV FFmpeg/`VideoCapture`/timeout capabilities pass on Windows x86. The complete gate remains intentionally blocked until target models, a verified runtime attestation receipt, expert CfC weights, target-Pi camera/runtime checks, and physical reports are available.
- FlyLens 85 CAD reference: structurally validated 14-solid conceptual blockout with a closed STL, correctly scaled GLB, preview, and fail-loud validator. It is not as-built, manufacturing, print, or flight evidence.

## GarudaPin prototype (planned, not implemented)

| Attribute | Current state |
|---|---|
| Hardware | WaveShare ESP32-S3-Touch-AMOLED-2.16 selected. Firmware not committed. |
| Audio capture | ES8311 codec + dual PDM mics on dev board; 16 kHz PCM streaming path is architectural intent |
| BLE GATT service | Not implemented |
| GPIO18 emergency button | Architectural intent only; no code yet |
| QMI8658 IMU gesture detect | Architectural intent only |
| BLE GATT client on Pi 5 | Not implemented |
| Phone companion app (Whisper + intent) | Not implemented |
| Spectrum split (2.4 GHz BLE pin, 5.8 GHz Wi-Fi phone→drone) | Architectural intent only |
| Emergency-button arbiter integration | Architectural intent only |
| Battery endurance / BLE range / acoustic SNR | Not tested |

GarudaPin is a P0-removable prototype workstream. Physical drone qualification is not gated on GarudaPin readiness.

## Current authority chain

```text
Human pilot, RC override, physical kill path
  > PX4 estimator, controller, and hardware failsafes
  > deterministic GarudaOne FSM, watchdogs, governors, and clamps
  > Needle/LFM/perception/CfC proposals
```

AI output is a request. It never becomes a motor command without deterministic validation.

## AI and cognition

### Needle 2 router: exercised

The active fast router is official Cactus Needle 2:

| Item | Current value |
|---|---|
| Model | `Cactus-Compute/needle2` |
| Architecture | 45M-parameter Simple Attention Network |
| Runtime | `cactus-needle==2.0.0` |
| Revision | `231364ff02542c4060afb5f4795801e0a09f5107` |
| License | Apache-2.0 |
| ARM64 wheel SHA-256 | `6660386292916935188edfe8eef94fbf24712085d7c84f80b0698f79509edde3` |

The pinned Windows engine was exercised with constrained commands. Observed host timings were about 204ms initialization, 44ms for hover, and 32ms for land. These are Windows observations, not Raspberry Pi 5 benchmarks.

Needle can emit only:

- `hover`
- `stop`
- `land`
- `rtl`
- `delegate_to_lfm`

Exact emergency phrases such as `hover`, `land now`, and `return home` have a deterministic parser before model inference. Empty, malformed, unsupported, multiple, low-confidence, `NaN`, or infinite model results delegate safely.

### Local LFM: implemented, target blocked

The richer path targets LFM2.5-VL-450M through the native Cactus engine. It can parse framing or tracking requests and can analyze an image for composition. The target Pi bundle and thermal/runtime behavior have not passed deployment preflight. When unavailable, it returns a safe hover proposal with an explicit error instead of fabricating output.

### Model and standalone-command boundary

No model schema exposes takeoff, and no public command surface exposes standalone:

- arm or disarm
- kill
- motor tests or raw actuator control
- arbitrary mode switching
- mission upload

The exact authenticated operator parser can emit `takeoff` without invoking Needle/LFM. All model-produced takeoff calls remain banned. The schema, parser, text server, and arbiter enforce this separation.

## User interaction

### Full command-to-arbiter path

The complete integrated software path is the Python API:

```python
runtime.process_command("hover in place", client_id="operator", token="...")
```

It runs:

```text
text
  -> deterministic direct-command parser
  -> Needle 2
  -> optional local LFM
  -> validated ToolProposal
  -> deterministic FlightArbiter
  -> ModeGrant or rejection
  -> flight-data recorder
```

### WebSocket and local operator UI: integrated

A token-aware WebSocket server exists at:

```text
ws://<pi-ip>:8765/v1/command
```

It authenticates, validates schema `v1`, rate-limits by server-derived client address, runs Needle/LFM routing, sends the proposal through the live deterministic arbiter, and returns the resulting grant or rejection. `run_runtime_service()` owns this server and the 20Hz tick loop in one asyncio event loop.

A local browser control surface is served on port 8080 by default. P0 flight enables takeoff, hover, stop, land, RTL, and free text. Takeoff is parsed before model inference, implicitly arms only after PX4 ACK plus armed-heartbeat confirmation, and uses the configured bounded climb. Land disarms only after grounded confirmation. The flight page omits microphone controls and PCM capture code. There are no standalone arm/disarm, kill, raw-actuator, or motor-test controls.

### Command input: text-only in the flight profile

The P0 flight profile sets `enable_voice: false` and accepts authenticated text commands only. Dormant browser/STT support remains in the repository but is outside this tracking change and is not enabled for flight.

## Integrated flight runtime

### PX4 transport: exercised in SIH

`DroneLink` uses `pymavlink`. It:

- waits for a real PX4 heartbeat;
- parses battery, position, velocity, attitude, armed state, and estimator status;
- streams local-NED velocity and yaw-rate setpoints;
- primes neutral setpoints for at least 500ms;
- requires an accepted `COMMAND_ACK` for OFFBOARD;
- requires a confirming PX4 heartbeat;
- transfers Land/RTL authority before stopping OFFBOARD setpoints;
- after PX4 reports landed, always issues an idempotent disarm request and requires its ACK plus a fresh disarmed heartbeat, even when cached state already says unarmed; FDR reports confirmation only from that successful call result.

MAVSDK references in dated documents are historical. The active transport is pymavlink.

### What commands do today

| Request | Current integrated effect |
|---|---|
| `hover` | Accepted in OFFBOARD hover and sends zero velocity. |
| `takeoff` | Exact authenticated operator-only route. Requires grounded, position (fresh within 0.5s), EKF, battery, stream, and preflight evidence; implicitly arms with ACK/heartbeat proof; climbs at 0.5m/s to 0.5–3.0m; holds neutral for at most 1s during transient evidence loss; holds on completion; and transfers to PX4 LAND after a 20s bounded timeout or persistent in-climb position/EKF evidence loss. Not physically qualified. |
| `stop` | Cancels tracking or hold where the FSM permits it. From ordinary hover it may be rejected as an illegal transition. |
| `land` | Requests PX4 AUTO.LAND, requires accepted ACK and a matching heartbeat, stops OFFBOARD setpoints only after transfer confirmation, and implicitly disarms only after grounded confirmation. Physical descent/disarm remain unqualified. |
| `rtl` | Requests PX4 AUTO.RTL with the same ACK/heartbeat confirmation. Physical return behavior remains unqualified. |
| `track_subject` | Flight profile rejects it because track is disabled and expert weights/hardware evidence are missing. In a qualified profile it locks a confirmed `subject_id`, applies distance/framing/yaw limits, and resets control state on identity change or loss. |
| `set_framing` | Updates the canonical tracking request for `wide`, `medium`, or `close`; unsupported values and unknown arguments are rejected. |

Land and RTL mode transfers require PX4 ACK and heartbeat confirmation; physical Land/RTL behavior remains unqualified.

The 20Hz runtime supplies zero velocity outside qualified track operation. A track-enabled configuration must first load an externally qualified expert CfC checkpoint. The current flight profile keeps track disabled.

## Safety system

The deterministic arbiter owns modes including takeoff and evaluates watchdogs every tick. It monitors:

- battery validity and per-cell voltage;
- CPU temperature validity and thresholds;
- EKF validity/degradation;
- ToF distance and confidence;
- geofence distance and altitude;
- setpoint age;
- target loss when tracking is enabled;
- gimbal heartbeat when tracking depends on it.

Missing battery or estimator evidence fails closed. Arm rejects landed, battery, EKF, or heartbeat samples older than 2s; disarm rejects landed evidence older than 2s. Expected PX4 IDs are captured before `wait_heartbeat()` can mutate pymavlink state; the initial heartbeat must prove those IDs or bind positive IDs when none were configured. All later ACKs, heartbeats, and telemetry must match both IDs. Missing source accessors or zero target IDs are rejected. Voltage and percentage battery evidence use separate monotonic clocks, so fresh simulator percentage cannot refresh stale physical voltage. The explicit SITL link may use PX4's simulated battery percentage because that backend emits no voltage; the flight/serial link disables this fallback and requires measured pack voltage. MAVLink centidegree headings are normalized to radians before body-to-NED control. Cached `armed=False` never closes landing: fresh landed evidence plus an idempotent disarm ACK and heartbeat are required. Real flight profiles forbid mock telemetry and mock ToF. Any no-mock profile with perception enabled also rejects synthetic, null, and file camera backends. Possible transitions include takeoff, hover, hold, land, RTL, search, and disarmed, but a state transition is not proof that its physical action profile is physically qualified.

## Perception

### Implemented modules

- PicoDet ncnn detector
- bounded OpenCV/FFmpeg capture for the configured C10 RTSP feed
- two-pass person-only ByteTrack with an 8-state box Kalman filter
- forward/backward Lucas–Kanade flow and affine RANSAC camera-motion compensation
- ZipDepth ncnn relative-depth estimator
- scene-graph builder
- single forward VL53L5CX ST-ULD adapter
- authoritative worker packets carrying same-frame identity/evidence/depth metadata

The flight profile selects the credential-free C10 RTSP URL and instantiates these modules in `GarudaOneRuntime`; it does not require a separate Pi navigation camera. A GIL-isolated worker owns bounded camera capture, detector cadence, depth, Kalman/LK state, identity lifecycle, and target lock. OpenCV/FFmpeg open/read calls have explicit timeouts. Unsupported timeout APIs, malformed URLs, userinfo/query credentials, zero-sized or failed reads, stopped workers, invalid frames, and stale heartbeats fail closed. A lock request succeeds only after the child tracker acknowledges the exact current identity; queue acceptance alone is not a grant. The 20Hz runtime consumes latest-only complete packets, adds measured forward ToF, applies a 250ms capture-time freshness gate, and records identity/evidence/model data in FDR. The installed Windows OpenCV timeout API was exercised against a closed localhost endpoint; the physical C10 stream and target-Pi path remain unexercised.

### Current boundaries

- The selected flight profile has **one forward VL53L5CX**, 8x8 at 15Hz, address `0x29`. It is the available project hardware; no VL53L8CX unit is available to this build.
- Older three-sensor VL53L8CX/ToF360 designs are historical or compatibility code.
- ZipDepth is relative until camera/ToF calibration establishes metric scale.
- Only `CONFIDENT` tracks with current `DETECTION` or validated `FLOW` evidence can control. Provisional, ambiguous, lost, stale, failed, or prediction-only results clear target validity and produce neutral motion in the same tick.
- Hardened fail-loud Python subprocess façades for VINS-Fusion and ORB-SLAM3 are structurally validated with real child-process fixtures on Windows x86. They reject empty/non-finite input, missing frame files, malformed or unknown messages, invalid poses/maps/loop events, stale buffered VINS poses, startup timeout leaks, early child exit, and reader-thread failures. The POSIX process-group path is code-reviewed but not target-Pi exercised. Native adapter source, binaries, calibrated configs, and active runtime wiring are not supplied. Stock upstream executables do not implement the custom JSON/stdio protocol, and both upstream engines are GPL-3.0, so adapter distribution needs an explicit licensing review. Any deployed localization path must use the selected existing cameras and sensors; the hardware plan does not add a dedicated navigation camera.
- There is no current autonomous obstacle-avoidance flight loop.

## Learned tracking controller

The CfC controller, real expert logger, expert retraining path, DAgger candidate/NumPy export, runtime input path, jerk limiter, clamps, and external qualification consumer are wired. Synthetic training can emit only `synthetic_candidate`; DAgger emits `candidate`, never `flight`. Production loading requires the exact executable artifact plus contained, hashed checkpoint, dataset, and validation-report evidence and explicit human approval metadata. Input/output/state tensors must have exact finite shapes before recurrent state can change. Measured local-NED velocity is rotated into body-forward/right before inference; body-forward/right output is rotated with current PX4 yaw back into local NED. Missing physical attitude denies inference and motion. Track mode remains disabled until real expert data and qualification exist.

## Gimbal and camera

The SkyDroid C10 Pro backend constructs checksummed UDP commands for pitch/yaw speed, centering, follow/lock modes, recording, photo capture, zoom, and calibration. Startup and periodic runtime polling require source-matched checksummed replies. Qualified CfC gimbal output is mapped to bounded C10 yaw speed; target loss or mode exit sends stop.

Current limits:

- the physical C10 has not been qualified;
- successful UDP send is not device evidence;
- the known network protocol does not provide gimbal attitude feedback;
- motion limits are unmeasured;
- the flight profile instantiates C10 and requires a source-matched checksummed inbound status reply at startup;
- recording, zoom, and photo are not model-facing natural-language tools.

The flight profile configures `rtsp://192.168.144.108:554/stream=0`. This is structurally validated source selection, not proof that the physical stream, latency, image quality, or reconnect behavior passes on the aircraft.

## Hardware contract

The selected design is:

- Raspberry Pi 5 8GB with a separate regulated 5V/5A supply;
- MicoAir743-AIO-35A candidate, PX4 target `micoair_h743-aio_default`;
- one 3S 450mAh LiHV pack, with series use forbidden;
- one forward SmartElex VL53L5CX, selected from the available hardware instead of an unavailable VL53L8CX;
- MicoAir MTF-01 flow/range;
- MicoAir MG-A01 GNSS/compass;
- Nexus1 ELRS receiver and RadioMaster Pocket ELRS target;
- SkyDroid C10 Pro.

This is a selected contract, not an as-built bill of materials. Exact labels, revisions, wiring, regulators, and physical behavior remain unverified.

The reproducible model under [`../cad/`](../cad/) is an envelope/placement reference for this selected contract. It does not close any physical identity, fit, clearance, structural, propulsion, or airworthiness gate.

## Physical deployment gate

Deployment requires eight local, hashed JSON reports:

1. firmware and physical post-flash identity;
2. Pi power rail and ripple;
3. MAVLink, estimator, flow, range, GNSS, and RC soak;
4. VL53L5CX soak;
5. propulsion mapping, thrust, vibration, and thermal evidence;
6. RC loss, kill switch, and manual override;
7. gimbal video, status, controls, and limits;
8. target-Pi model throughput, LFM smoke, temperature, and duration.

The validator rejects path traversal, duplicate JSON keys, non-standard numeric constants, non-finite values, missing measurements, and reports that only state `passed: true`.

## Demonstrable now

The repository can demonstrate:

- real Needle 2 constrained inference on the Windows host;
- deterministic command parsing, authenticated loopback WebSocket/UI operation, offline-PCM voice contracts, and arbiter grants/rejections;
- banned-tool rejection;
- fail-closed deployment and hardware-evidence validation;
- PX4 configuration/read-back and non-arming OFFBOARD SIH;
- neutral 20Hz hover setpoints, ACK/heartbeat-confirmed PX4 Land/RTL transfer contracts, and FDR logging;
- integrated perception/C10 lifecycle and qualified-only CfC setpoint flow against test doubles;
- read-only hardware qualification tooling;
- reproducible conceptual FlyLens 85 STEP/STL/GLB/preview generation and structural artifact validation.

## Explicit non-claims

GarudaOne does not currently claim:

- physical flight readiness;
- autonomous takeoff or physically qualified Land/RTL behavior;
- subject-following or cinematic autonomous flight;
- 360-degree obstacle sensing;
- metric monocular depth;
- production VIO/SLAM;
- physically qualified AI-controlled gimbal cinematography;
- target-Pi-qualified voice control;
- target-Pi model performance or thermal stability;
- expert-trained CfC control;
- a polished production mobile/desktop operator application;
- GarudaPin firmware implementation or target qualification;
- GarudaPin BLE streaming, phone-side Whisper, or emergency-button integration.

## Next software work before hardware flight

1. Exercise the complete service with the exact C10 RTSP feed, model bundles, VL53L5CX, C10 control link, and PX4 wiring.
2. Collect and qualify an expert CfC dataset/checkpoint before enabling track.
3. Complete production VIO/localization with the selected existing sensors, or explicitly exclude it before autonomous motion; do not add a dedicated navigation camera.
4. Run HIL, fault injection, physical Land/RTL, RC, propulsion, calibration, tethered, and staged-flight gates.
5. Implement GarudaPin ESP-IDF firmware (BLE GATT, audio, emergency button), BLE GATT client on Pi 5, phone companion app (Whisper + intent), and arbiter integration. These are P0-removable and not gated on physical drone qualification.

## Document authority

Use this file for capabilities and interaction. Use:

- [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) for implementation evidence;
- [`../DONE_PENDING.md`](planning/DONE_PENDING.md) for restart and acceptance criteria;
- [`../hardware/HARDWARE_INTEGRATION_STATUS.md`](../hardware/HARDWARE_INTEGRATION_STATUS.md) for hardware gates;
- [`DOCUMENTATION_POLICY.md`](DOCUMENTATION_POLICY.md) for documentation classifications and update rules.
