# GarudaOne implementation status

> [!NOTE]
> [DOC_STATUS: CURRENT] Authoritative implementation/evidence matrix. Product behavior and interaction are explained in [`CURRENT_CAPABILITIES.md`](CURRENT_CAPABILITIES.md).

Verified/synchronized: **2026-08-15**

## Release verdict

The evidence-available software slice is implemented and test-green on Windows x86. GarudaOne is not ready for physical flight. Physical identity, electrical, sensor, propulsion, RC, target-Pi model, and staged-flight evidence are absent.

Track mode is disabled. No model schema exposes takeoff and no standalone arm/disarm command exists. The exact authenticated operator route can request takeoff; arm/disarm remain implicit confirmed actions.

## Verification snapshot

| Check | Result | What it proves |
|---|---:|---|
| Python suite | **800 passed, 3 skipped** | Current release-tree software contracts on Windows x86/Python 3.11 with pinned submodules initialized |
| Prior cross-cutting corrective suite | **31 passed** | Non-finite input, estimator-rate, strict JSON, and ToF evidence boundaries |
| Localization façade/VIO focused suite | **53 passed** | Strict JSON/stdio protocol, lifecycle, sticky-error, and fail-closed numeric/path boundaries on Windows x86/Python 3.11 |
| Needle 2 native probe | Passed | Pinned official Windows engine loads and returns constrained calls |
| PX4 parameter contract | **17/17 passed** | Set/read-back against live PX4 SIH |
| PX4 OFFBOARD/Land/RTL | Passed in SIH | ACK/heartbeat-confirmed OFFBOARD plus independent Land/RTL transfers; no arming/takeoff |
| PX4 operator cycle | Passed in SIH | Pre-wait target-peer confirmed arm, 1.5m target-tolerance takeoff, LAND transfer, grounded state, and one FDR-confirmed disarm in 380 ticks |
| Hardware evidence | Pinned | Offline evidence repository at an exact SHA; not physical compatibility |
| Deployment preflight | C10 runtime gate passes on host; overall blocked | Typed C10 source plus OpenCV FFmpeg/`VideoCapture`/bounded-timeout capabilities replace the stale `picamera2` check. Missing target bundles, expert checkpoint, runtime receipt, target-Pi execution, and physical reports remain visible |
| Physical flight | Not run | No physical readiness claim |

## Capability matrix

| Subsystem | Evidence class | Current result |
|---|---|---|
| Needle 2 routing | Exercised | `cactus-needle==2.0.0`, 45M, pinned revision/hash, constrained tools |
| Deterministic direct commands | Exercised | Exact hover/stop/land/RTL phrases bypass model uncertainty |
| Local LFM tool calling | Implemented, target blocked | Native Cactus path exists; Pi bundle/thermal smoke missing |
| LFM vision analysis | Implemented, not integrated | Image analysis API exists; active runtime does not call it |
| Authenticated text parsing | Structurally validated | Token, schema, rate limit, banned tools, stable peer identity |
| WebSocket-to-flight bridge | Exercised on loopback | Authenticated request reaches live runtime arbiter and returns grant/rejection |
| Flight arbiter/FSM | Exercised | Grants/rejections, watchdog transitions, clamps, governors, FDR |
| PX4 link | Exercised in SIH | pymavlink, telemetry, neutral setpoints, ACK/heartbeat OFFBOARD |
| Hover | Exercised in SIH | 20Hz zero-velocity stream |
| Operator takeoff | Exercised in SIH | Exact non-model route, implicit ACK/heartbeat-confirmed arm, bounded climb/timeout, grounded implicit disarm; physical behavior not qualified |
| PX4 Land/RTL execution | Structurally validated | Mode request requires ACK and matching heartbeat; physical behavior not qualified |
| C10 RTSP/PicoDet/ZipDepth | Integrated, target blocked | Flight profile selects a typed credential-free RTSP source; bounded OpenCV/FFmpeg open/read, reconnect, positive-size frame, stopped-worker, and heartbeat contracts are structurally exercised. Physical C10/Pi execution is absent |
| ByteTrack/LK/CMC/scene graph | Integrated, target blocked | Evidence-gated identity, full-rate flow, target lock, complete worker packets, stale denial, and FDR context reach runtime; flight track remains disabled |
| CfC control | Qualified-only path integrated, disabled | External checkpoint/dataset/report qualification required; no expert artifact exists |
| VL53L5CX | Implemented, hardware blocked | ST-ULD 8x8/15Hz path and qualification tools exist; this is the available project ToF hardware and no VL53L8CX unit is available to the build |
| SkyDroid C10 | Integrated, hardware blocked | Flight startup requires checksummed inbound control status and a valid bounded RTSP frame before perception readiness; no physical video, limits, or attitude feedback are qualified |
| Voice | Disabled in flight P0 | `flight.yaml` accepts authenticated text only; dormant local voice code is outside this tracking release |
| VIO/SLAM | Python façades hardened and structurally validated; deployment missing/deferred | Windows x86 child-process fixtures prove finite input/output validation, strict typed protocols, sticky errors, stale-pose suppression, and bounded Windows cleanup. POSIX cleanup is structurally present but not target-Pi exercised. Native adapter source/binaries/calibrated configs/runtime wiring are absent; stock upstream executables do not implement the protocol, GPL-3.0 distribution needs review, and deployed use must keep the selected sensor set with no added navigation camera |
| Operator UI | Exercised on loopback | Local takeoff/hover/stop/land/RTL buttons and text; the flight page omits microphone controls and PCM capture code |
| FlyLens 85 CAD reference | Structurally validated reference | Reproducible 14-solid STEP, closed STL, meter-scaled GLB, preview, and adversarial validator; not as-built, manufacturing, print, structural, or flight evidence |

## Current integrated runtime

`GarudaOneRuntime` now wires:

```text
local UI/text -> authenticated WebSocket -> Needle/LFM -> FlightArbiter
C10 RTSP/PicoDet/ZipDepth/ByteTrack/LK/CMC + forward VL53L5CX + C10 control + PX4 telemetry
  -> neutral/search or externally qualified CfC -> frame transform -> jerk limiter/clamps
  -> pymavlink/PX4 -> FDR
```

The normal service owns the WebSocket/UI lifecycle and the 20Hz tick loop. The flight profile enables perception, C10, and exact operator takeoff; disables voice; and fails closed if required native/device evidence is absent. Takeoff performs implicit confirmed arm, bounded climb, timeout-to-LAND, and grounded implicit disarm. Track remains disabled because no expert checkpoint qualification exists. Takeoff/Land/RTL physical behavior remains unqualified.

## AI contract

Needle 2 can emit only `hover`, `stop`, `land`, `rtl`, or `delegate_to_lfm`. The richer LFM schema adds `track_subject` and `set_framing`, but the arbiter rejects tracking while the flight profile disables it. Takeoff is parsed only by the exact authenticated operator route before either model.

Model-generated takeoff and standalone arm/disarm remain banned, as do kill, motor/actuator controls, arbitrary mode changes, and mission upload.

Needle confidence must be finite and at least 0.7. Empty, malformed, unsupported, or multiple calls delegate. LFM failures and repetition loops fall back to hover with an explicit error.

## Safety implementation

- Battery, CPU, estimator, ToF, and gimbal fields no longer start healthy by assumption.
- Production startup requires real battery and estimator telemetry before OFFBOARD.
- Neutral setpoints stream for at least 500ms before OFFBOARD is requested.
- OFFBOARD requires both accepted `COMMAND_ACK` and heartbeat confirmation.
- Expected PX4 IDs are snapshotted before `wait_heartbeat()` can mutate pymavlink state. The initial heartbeat binds or proves positive system/component IDs; missing source accessors, zero IDs, and later mismatched ACKs, heartbeats, or telemetry are rejected.
- Takeoff arm and post-land disarm always issue an idempotent request and require matching `COMMAND_ACK` plus heartbeat state from the connected PX4 system/component; cached `armed=False` cannot close landing, in-air disarm is rejected, and FDR confirmation is the successful request result rather than a telemetry-derived guess.
- Takeoff altitude/rate are bounded; position must be fresh within 0.5s; transient evidence loss holds neutral for at most 1s, then persistent position/EKF loss triggers PX4 LAND.
- Arm requires landed, battery, EKF, and heartbeat samples no older than 2s; disarm requires landed evidence no older than 2s.
- Percentage-only battery evidence is accepted only by the explicitly constructed SITL link. Voltage and percentage use separate freshness clocks; the physical flight link requires fresh measured pack voltage.
- No-mock perception profiles reject synthetic, null, and file camera backends before runtime construction.
- `GLOBAL_POSITION_INT.hdg` centidegrees are converted to radians before body-to-NED control math.
- Watchdogs can force hold, hover, land, or RTL states based on configured limits.
- Velocity and yaw commands are bounded by deterministic clamps.
- Track authority requires a locked `CONFIDENT` identity with current detector or validated flow evidence; stale, provisional, ambiguous, lost, and prediction-only results are neutral.
- TRACK never bypasses measured/blind ToF limits. Thermal warning changes live detector duty.
- Target/mode changes reset recurrent and smoother state. Search emits bounded yaw; watchdog Land/RTL uses receiver ACK and heartbeat confirmation.
- Physical deployment requires a path-contained, SHA-256-verified eight-report attestation.
- Evidence parsing rejects duplicate keys, `NaN`, infinities, booleans-as-numbers, impossible ranges, and empty `passed: true` reports.
- Offline firmware bytes cannot certify DFU recovery, completed flashing, reboot, or physical board identity.

## Selected hardware/software contract

- Raspberry Pi 5 8GB with independent regulated 5V/5A rail
- MicoAir743-AIO-35A candidate, target `micoair_h743-aio_default`
- one 3S 450mAh LiHV pack; series use forbidden
- one forward VL53L5CX at `0x29`, 8x8/15Hz, selected from available project hardware
- MTF-01 flow/range and MG-A01 GNSS/compass
- Nexus1 receiver and RadioMaster Pocket ELRS target
- SkyDroid C10 Pro
- Needle 2 revision `231364ff02542c4060afb5f4795801e0a09f5107`
- hardware evidence revision `43a5a33d88baddca57245422b1cbe953010ffdc5`

The contract is selected design intent. It does not prove the physical labels, revisions, wiring, or behavior.

## PX4 parameter corrections

Required read-back includes:

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

The AIO board's 4S/4.2V defaults are not accepted for the selected 3S LiHV pack. Range aid is conditional; it is not forced as the global altitude reference.

## Hardware and target-Pi blockers

- exact labels and revisions;
- Pi and gimbal regulator selection, rail ripple, brownout, current, and thermal measurements;
- physical firmware recovery, flash, reboot, and marker evidence;
- Pi-to-PX4 UART reliability;
- MTF-01/MG-A01 wiring, rates, calibration, and EKF quality;
- VL53L5CX electrical, mounting, orientation, and environmental validation;
- RC loss, manual override, and kill-switch validation;
- motor order, thrust, current, vibration, mass, CG, and endurance;
- C10 RTSP, status, movement, reset, and measured limits;
- target-Pi Needle/LFM throughput and thermal soak;
- camera calibration and metric depth scale;
- tethered and staged flight evidence.

## Software work remaining

1. Exercise all enabled flight-profile components on the exact Pi and as-built vehicle.
2. Collect, validate, independently approve, and qualify expert CfC data/weights before enabling track.
3. Complete VIO/localization with selected existing sensors, or exclude it before autonomous motion; do not add a dedicated navigation camera.
4. Complete physical Land/RTL, RC, propulsion, sensor, calibration, HIL, tethered, and staged-flight evidence.

## Physical deployment gate

`garudaone-software/configs/hardware_attestation.template.yaml` lists eight reports. Preflight validates local containment, SHA-256, strict JSON, `passed: true`, and gate-specific measurements. Unit tests, model cards, checksums, and manually typed booleans cannot replace physical evidence.

## Documentation authority

- Capabilities and interaction: [`CURRENT_CAPABILITIES.md`](CURRENT_CAPABILITIES.md)
- Restart and acceptance ledger: [`../DONE_PENDING.md`](planning/DONE_PENDING.md)
- Hardware closure: [`../hardware/HARDWARE_INTEGRATION_STATUS.md`](../hardware/HARDWARE_INTEGRATION_STATUS.md)
- Documentation rules: [`DOCUMENTATION_POLICY.md`](DOCUMENTATION_POLICY.md)
