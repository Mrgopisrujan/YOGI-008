# GarudaOne: Hardware Research Brief — Forward Edge-Case Sensor (Flash LiDAR / ToF)

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - The selected flight profile uses one forward VL53L5CX at 8x8/15Hz; three-sensor/VL53L8CX designs are not active.


> [!IMPORTANT]
> This is the historical sensor-comparison brief, not deployment evidence. The current selected prototype contract is one forward **VL53L5CX**, Linux address `0x29`, 8×8 at 15Hz. See [`../DONE_PENDING.md`](../planning/DONE_PENDING.md).


## 1. The Exact Problem We Are Solving
Our camera-based perception (detector + planned production depth stack — see doc 04 rev.) goes "blind" in three specific scenarios:
*   **Transparent surfaces:** Glass doors and windows (the camera looks *through* them).
*   **Reflective surfaces:** Mirrors and highly polished floors (the camera tracks the reflection, hallucinating depth that doesn't exist).
*   **Featureless surfaces:** Pure white walls with no texture (the camera cannot track any contrast points).

If the drone relies purely on the camera, it will fly at full speed into a glass door. We need a secondary, active sensor that shoots a physical signal (infrared laser) to bounce off these surfaces, proving they exist. 

**The Software Magic (production phase):** We do not need a high-resolution map from this sensor. On the production SoC (NPU-class), the sparse zone "pings" plus the RGB feed are fed into LingBot-Depth 2.0 (Robbyant/Orbbec, arXiv 2601.17895), which completes them into a dense depth surface including glass/mirrors. **On the Pi 5 prototype the raw ToF grid is used directly with a speed governor — depth completion is NOT free on a CPU (see 08 C7).** Prototype camera feed is 1080p25, not 4K.

## 2. Hardware Specifications Needed
The HW team needs to source a **Multi-Zone Time-of-Flight (ToF) Sensor** (often called Flash LiDAR) that meets our strict sub-250g drone constraints. 

Please optimize for the following requirements:

*   **Type:** Multi-zone ToF (we need a grid of points, e.g., an 8x8 or 4x4 grid, NOT a single-point laser).
*   **Weight Limit (Critical):** Under 2 to 3 grams (module + PCB). 
*   **Effective Range:** 4 to 8 meters. This is only for indoor/close-quarters glass detection at low speeds (1-3 m/s).
*   **Field of View (FOV):** ~45° to 65°. It needs to cover the central flight path of the drone, roughly matching the camera's center field.
*   **Refresh Rate (amended — see datasheets):** No available multizone dToF does 8×8 at 30–60 Hz. Real limits: **8×8 @ ~15 Hz; 4×4 @ up to 60 Hz** (VL53L8CX). At our ≤3 m/s governed indoor speed, 15 Hz = one measurement per ≤20 cm of travel, which is sufficient. Requirement: ≥15 Hz in 8×8 mode, with 4×4 @ 60 Hz available as a fast fallback mode.
*   **Interface:** I2C or SPI (Must be easily readable by the Raspberry Pi 5 / Production SoC without complex driver overhead).
*   **Power Draw:** Low power (< 200mW).

## 3. Recommended Baselines for Comparison
Please evaluate the following standard components and determine if there is a better, lighter, or more reliable alternative for 5-meter glass detection:
1.  **ams OSRAM TMF8828:** 8×8 grid, 5 m range, I2C, ~15 Hz max in 8×8 mode ([datasheet](https://download.mikroe.com/documents/datasheets/TMF8828_datasheet.pdf)). Longest range of the class.
2.  **STMicroelectronics VL53L8CX:** 8×8 grid, 4 m range (400 cm), 8×8 @ 15 Hz / 4×4 @ 60 Hz, I2C **and SPI** (SPI relieves I2C bus contention with the optical-flow sensor), better ambient-light immunity than its predecessor ([datasheet](https://www.st.com/resource/en/datasheet/vl53l8cx.pdf)). **Current recommendation** unless the extra 1 m of TMF8828 range proves decisive in glass-detection bench tests.

**Goal:** Find the module that gives us the most reliable transparent-surface detection at 5 meters for the absolute lowest weight penalty.
