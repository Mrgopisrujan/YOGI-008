# DroneOS Simulation/Visualization Research Report

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - The integration branch bridges authenticated WebSocket/UI requests to the live runtime arbiter; physical-flight qualification remains blocked.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!NOTE]
> This is a dated research snapshot. Model choices, estimates, and recommendations are not implementation claims. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).

## Date: July 17, 2026

## Your Setup
- **Host:** Windows 10, Intel Ultra 7 255H, 32GB RAM, **Intel Arc 140T GPU (16GB)**
- **WSL2:** Ubuntu 26.04 "resolute" (PX4 SITL built and running headless)
- **Python stack:** pymavlink, arbiter FSM, cognition — all Python
- **Unreal Engine:** Installed on Windows (Epic Games Launcher, no drone env)
- **Blender 5.2:** Installed at `C:\Program Files\Blender Foundation\Blender 5.2\`
- **Docker:** Available on Windows
- **JMAVSim:** Built in WSL but fails (WSLg DRI3 software rendering issue)

## Options Analyzed

### 1. Gazebo Harmonic (gz-sim8) in Docker — ✅ BEST OPTION
**Verdict: This is the one.**

- **Pre-built Docker image exists:** `px4io/px4-sitl-gazebo` on Docker Hub
- Runs PX4 SITL + Gazebo Harmonic in one container
- Exposes MAVLink on port 14540 (same as our headless PX4)
- Headless mode (`HEADLESS=1`) works without GPU
- Can forward X11 to Windows for GUI mode (needs GPU passthrough — won't work in WSL2)
- **Headless + QGroundControl combo:** Run Gazebo headless in Docker, use QGroundControl on Windows for visual
- **Setup time:** 10 minutes (docker pull + run)
- **Visual quality:** Full 3D with terrain, buildings, iris quadcopter model (when GUI works)
- **MAVLink:** Native PX4 integration, port 14540 exposed
- **Maintained:** Actively maintained by PX4 team

**Command:**
```bash
docker run --rm -it --net=host -e HEADLESS=1 px4io/px4-sitl-gazebo
```

**Limitation:** Headless mode = no 3D GUI. For visual, need QGroundControl or gz client forwarding.

### 2. QGroundControl on Windows — ✅ IMMEDIATE VISUAL
**Verdict: Do this RIGHT NOW. It's free, instant, and shows the drone flying.**

- Native Windows app, no WSL/Linux needed
- Connects to PX4 SITL via MAVLink UDP (port 14540)
- Shows: **real-time 2D/3D map**, drone position, heading, flight path, battery, mode
- Built-in MAVLink inspector, flight plan editor, parameter tuning
- **Download:** qgroundcontrol.com → Windows installer
- **Setup time:** 2 minutes (download + install + connect)
- **Visual quality:** Map-based 2D/3D with terrain (not photorealistic, but professional GCS view)
- **Maintained:** Official MAVLink project, actively maintained
- **Works with:** Our existing headless PX4 SITL in WSL (no changes needed)

**This is what every real drone pilot uses to see their drone. It's not a toy visualizer — it's the industry standard GCS.**

### 3. Colosseum (AirSim fork) + Unreal Engine — ⚠️ POSSIBLE BUT HEAVY
- AirSim was abandoned by Microsoft in 2024
- Colosseum is the community fork (CodexLabsLLC), actively maintained
- Runs on **Windows natively** with Unreal Engine (you have both!)
- Photorealistic 3D environments
- Connects to PX4 via SITL ( HITL)
- **Problem:** Requires Ubuntu 20.04 for PX4 SITL integration (not WSL)
- **Workaround:** Can use AirSim's built-in simple_flight (no PX4) for visual testing
- **Setup time:** 2-4 hours (build Unreal plugin, configure PX4 SITL bridge)
- **Visual quality:** Photorealistic (Unreal Engine quality)
- **GPU:** Arc 140T 16GB — sufficient for Unreal

**This is the long-term path for photorealistic cinematics, but heavy to set up now.**

### 4. NVIDIA Isaac Sim + Pegasus — ❌ TOO HEAVY FOR NOW
- Isaac Sim 5.x runs on Windows
- Pegasus is NVIDIA's PX4 integration for Isaac Sim
- **Problem:** Requires RTX GPU (NVIDIA only). Your Arc 140T is Intel — **will not work**
- Would need cloud GPU (AWS/GCP/Modal) to run
- Photorealistic + physics + synthetic data generation
- **Verdict:** Skip. Hardware incompatible. Revisit if you get an NVIDIA GPU machine.

### 5. jMAVSim with Software Rendering — ❌ BROKEN
- Already tried, WSLg DRI3 fails
- Can't force software rendering through WSLg's Weston compositor
- Would need Xvfb + X11 forwarding but that gives ~1 FPS
- **Verdict:** Dead end on WSL2.

### 6. Blender bpy (Python Module) — ✅ UNIQUE OPTION
- Blender 5.2 already installed on your machine
- `bpy` PyPI package = Blender as Python module (headless)
- Could render drone flight path in 3D with Cycles (photorealistic)
- **Approach:** Read PX4 telemetry via pymavlink → animate drone in Blender → render frames
- **Visual quality:** Photorealistic (Cycles renderer, you already use this for CAD)
- **Real-time:** No — it's offline rendering (minutes per frame)
- **Best for:** FDR replay visualization, marketing renders, investor demos
- **Setup time:** 1-2 hours (Python script to drive bpy from FDR data)
- **Maintained:** Blender is one of the most actively maintained open source projects

**This is the "wow factor" option for investor demos — photorealistic drone flight replay in Blender.**

### 7. three.js + WebSocket (Web-based 3D) — ✅ REAL-TIME IN BROWSER
- Python WebSocket server streams PX4 telemetry to browser
- three.js renders 3D drone in browser tab (uses your Arc 140T via WebGL)
- **Real-time:** Yes, 30+ FPS
- **Visual quality:** Good 3D (custom drone model, terrain, skybox) — not photorealistic but interactive
- **No install:** Just open a browser URL
- **Setup time:** 2-3 hours (Python WebSocket + three.js scene)
- **Maintained:** three.js is the most popular WebGL library
- **Unique advantage:** Works on any device (phone, tablet, laptop) — could show investors on their phone

**This is the real-time interactive option that works everywhere.**

### 8. Gazebo Classic (gazebo11) — ❌ NOT AVAILABLE
- No packages for Ubuntu 26.04 "resolute"
- OSRF repo doesn't support this Ubuntu version
- Would need to downgrade WSL to Ubuntu 22.04/24.04
- **Verdict:** Not worth the OS downgrade.

### 9. Pure Python 3D (Panda3D, Ursina, PyOpenGL) — ⚠️ MEDIOCRE
- Panda3D: game engine in Python, could render 3D drone
- Ursina: simpler wrapper around Panda3D
- **Problem:** Low visual quality, lots of manual 3D model work
- Real-time but ugly compared to Gazebo/Unreal
- **Verdict:** Not worth the effort vs. three.js or QGroundControl.

## Recommendations

### Do RIGHT NOW (10 min total):
1. **QGroundControl** — download, install, connect to PX4 SITL. Instant visual of drone flying on a real map. This is what real drone pilots use.
2. **Gazebo Docker (headless)** — `docker run px4io/px4-sitl-gazebo` with HEADLESS=1. Replaces our hand-built PX4 SITL with the official PX4+Gazebo image. More features, better physics.

### Do NEXT (2-3 hours):
3. **three.js + WebSocket visualizer** — Python server streams telemetry to a browser 3D scene. Real-time, interactive, works on any device. This is your "show investors" real-time visual.

### Do LATER (when you need photorealistic):
4. **Blender bpy FDR replay** — Photorealistic Cycles render of flight path from FDR data. For investor demo videos and marketing.
5. **Colosseum + Unreal** — Full photorealistic SITL with PX4. When you have a dedicated dev day for Unreal setup.

### Skip:
- Isaac Sim (wrong GPU brand)
- Gazebo Classic (wrong Ubuntu version)
- JMAVSim (broken on WSLg)
- Panda3D/Ursina (not worth the effort)

## Summary Table

| Option | Works now? | Visual quality | Real-time? | Setup time | Recommendation |
|---|---|---|---|---|---|
| QGroundControl | ✅ Yes | Map 2D/3D | ✅ Yes | 2 min | **DO NOW** |
| Gazebo Docker (headless) | ✅ Yes | Physics only (no GUI) | ✅ Yes | 10 min | **DO NOW** |
| three.js + WebSocket | ✅ Yes | Good 3D | ✅ Yes | 2-3 hr | **DO NEXT** |
| Blender bpy replay | ✅ Yes | Photorealistic | ❌ Offline | 1-2 hr | **For demos** |
| Colosseum + Unreal | ⚠️ Possible | Photorealistic | ✅ Yes | 4+ hr | **Later** |
| Isaac Sim | ❌ No GPU | Photorealistic | ✅ Yes | N/A | **Skip** |
| Gazebo Classic | ❌ No packages | Good 3D | ✅ Yes | N/A | **Skip** |
| JMAVSim | ❌ Broken | Basic 3D | ✅ Yes | N/A | **Skip** |
| Panda3D/Ursina | ✅ Yes | Low | ✅ Yes | 2+ hr | **Skip** |
