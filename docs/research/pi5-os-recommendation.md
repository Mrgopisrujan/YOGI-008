# GarudaOne Pi 5 8GB — OS Recommendation Report

> [!IMPORTANT]
> [DOC_STATUS: HISTORICAL] This dated document preserves research, design, or planning context. It does not describe the current product. Read [GarudaOne current capabilities](../CURRENT_CAPABILITIES.md) first.
>
> Current outcome (2026-08-13):
> - Needle 2 (45M, `cactus-needle==2.0.0`) replaced Needle 26M as the active constrained router.
> - The active PX4 transport is pymavlink, not MAVSDK-Python.
> - The selected flight profile uses one forward VL53L5CX at 8x8/15Hz; three-sensor/VL53L8CX designs are not active.
> - The integration branch bridges authenticated WebSocket/UI requests to the live runtime arbiter; physical-flight qualification remains blocked.
> - The flight profile instantiates C10 and requires an inbound checksummed status reply; physical attitude feedback and motion limits remain unvalidated.
> - The LFM/Cactus path exists, but its target-Pi bundle, throughput, memory, and thermal behavior remain unqualified.
> - Performance figures here are dated estimates or upstream claims unless tied to inspected current evidence; target-Pi performance is unmeasured.


> [!NOTE]
> This is a dated research snapshot. Model choices, estimates, and recommendations are not implementation claims. Current verified status: [`../docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).


**Date:** 2026-07-17
**Author:** Hermes Agent (research subagent)
**Target hardware:** Raspberry Pi 5 8GB (Broadcom BCM2712, quad-core Arm Cortex-A76 @ 2.4 GHz, LPDDR4X-4267)
**Target stack:** GarudaOne DroneOS — llama.cpp (LFM2.5-VL-450M Q8_0, ~379 MB + KV cache), ncnn (PicoDet-S 4.7 MB), pymavlink (20 Hz OFFBOARD), OpenCV, PyTorch CPU (CfC LNN, 1621 params), Python 3.11+
**Constraint:** Maximum RAM headroom for ML models. 8 GB total — every MB saved on the OS is a MB available for model weights, KV cache, and perception buffers.
**Current target (doc 12):** Ubuntu 24.04 LTS ARM — **this report recommends changing it.**

---

## TL;DR — The Winner

**DietPi (Trixie-based, 64-bit/ARM64) for the Pi 5 companion computer.**

| Metric | DietPi (Trixie 64-bit) | Raspberry Pi OS Lite (Trixie 64-bit) | Ubuntu Server 24.04 (Noble) |
|---|---|---|---|
| **Idle RAM (free -tm)** | **152 MiB** | 240 MiB | ~250–350 MiB* |
| **Boot time** | **2.768 s** | 15.836 s | ~30–45 s (snapd + cloud-init) |
| **Running processes** | **9** | 24 | 30–40+ |
| **Disk usage** | **894 MiB** | 2639 MiB | ~2500+ MiB |
| **Pre-installed packages** | **251** | 658 | ~500+ |
| **Python version** | 3.13 (Trixie) / 3.11 (Bookworm) | 3.13 (Trixie) / 3.11 (Bookworm) | 3.12 |
| **snapd bloat** | None | None | ~37+ MiB at idle + CPU hammering |
| **ARM64 (aarch64)** | Yes | Yes | Yes |
| **piwheels dependency** | None (pure aarch64 wheels from PyPI) | None | None |
| **PREEMPT_RT path** | Same kernel tree as RPi OS (rpi-rt-kernel applies) | Native rpi-rt-kernel support | Mainline RT (6.12+), but harder on Ubuntu Pi |
| **pymavlink / PX4** | pip wheel works | pip wheel works | pip wheel works |

\* Ubuntu Server 24.04 on Pi 5 does not publish an official "free -tm" idle number in DietPi's comparison table (Ubuntu is not in that table). Community reports and the snapd issue (36.93 MiB for snapd alone at idle, plus cloud-init, systemd-networkd-wait-online, pollinate, apport, etc.) place it in the 250–350 MiB range. Forum reports of "Ubuntu 24.04 running slow on Pi 5" and "4 GB of RAM and 8 GB of swap is completely insufficient" corroborate the bloat.

**Why DietPi wins for GarudaOne specifically:**
- **88 MiB more RAM free vs RPi OS Lite, ~100–200 MiB more vs Ubuntu Server.** On an 8 GB Pi with LFM2.5-VL-450M Q8_0 (379 MB) + KV cache (~200 MB Q4) + PicoDet ncnn (50 MB working set) + OpenCV (100 MB) + Python runtime (50 MB), every extra 100 MB of OS-free RAM is either a larger KV cache (more context) or more headroom for the CfC LNN training/eval and the 25 Hz perception pipeline.
- **2.768 s boot vs 15.8 s (RPi OS) vs 30–45 s (Ubuntu).** Faster boot = faster time-to-OFFBOARD = less time the drone sits on the ground with the FC armed but no companion brain.
- **9 processes vs 24 vs 30–40.** Fewer processes = less scheduler jitter on the 20 Hz OFFBOARD setpoint stream. This directly addresses pitfall #11 in the GarudaOne skill (pymavlink hot-path jitter).
- **Logs and temp files on tmpfs (RAM disk).** No SD card I/O contention during FDR recording or model loading. Ubuntu and RPi OS Lite write logs to rootfs (SD card), which competes with the FDR recorder and ncnn model loads for I/O.
- **No snapd.** Ubuntu's snapd is a known CPU/RAM hog on ARM (see Ask Ubuntu #1553378: "snapd hammering CPU, server is out of RAM"). On a drone, a background daemon eating CPU during the 20 Hz control loop is unacceptable.

---

## Detailed OS Analysis

### 1. DietPi (Trixie 64-bit) — RECOMMENDED

**What it is:** A highly optimized Debian-based distribution focused on minimal CPU and RAM usage. Not a fork — it's Debian userland with DietPi's own minimal base image, dietpi-software catalog, and automated first-boot configuration.

**Measured stats on Pi 5 (Trixie 64-bit, tested 2026-04-02, source: dietpi.com/stats.html):**
| Stat | Value |
|---|---|
| RAM usage (idle) | **152 MiB** |
| Running processes | **9** |
| Disk usage | 894 MiB |
| Pre-installed packages | 251 |
| Boot duration | **2.768 s** |
| Temp files | RAM disk (tmpfs) |
| Log files | RAM disk (tmpfs) |
| SSH pre-installed | Yes |
| Download size | 183 MiB |
| Image size | 1095 MiB |

**Python version:**
- DietPi Bookworm images: Python 3.11 (same as RPi OS Bookworm — both are Debian 12)
- DietPi Trixie images: Python 3.13 (Debian 13, released August 2025; DietPi v9.15 added a Bookworm→Trixie upgrade script on July 28, 2025)
- Both 3.11 and 3.13 satisfy GarudaOne's Python 3.11+ requirement. **Recommend Trixie for Python 3.13** (faster, better error messages, more wheels available) unless a specific package lacks cp313 wheels.

**ML library support (all via PyPI aarch64 wheels, NOT piwheels):**
| Package | aarch64 wheel on PyPI | Python versions | Notes |
|---|---|---|---|
| `llama-cpp-python` | Source build (no prebuilt aarch64 wheel on PyPI for Linux) | cp38–cp314 | **Build from source on Pi 5** with `CMAKE_ARGS="-DCMAKE_C_FLAGS=-march=armv8.2-a+dotprod+i8mm"`. This is REQUIRED anyway — prebuilt wheels won't have Pi 5 A76 SMMLA optimizations. ~10-15 min compile. |
| `ncnn` | **Yes** — `manylinux_2_24_aarch64` + `manylinux_2_28_aarch64` | cp310–cp314 | 4.3 MB wheel. Works on any glibc 2.24+ ARM64. DietPi Trixie has glibc 2.41. |
| `torch` (CPU) | **Yes** — `manylinux_2_28_aarch64` | cp39–cp314 | See SIGILL note below. Pi 5 Cortex-A76 supports the LSE atomics that older Pi 4 Cortex-A72 lacks. |
| `opencv-python` | **Yes** — `manylinux_aarch64` + source | cp38–cp313 | Use `opencv-python-headless` for no GUI deps. |
| `pymavlink` | **Yes** — pure Python + C extension, builds on any platform | cp38–cp314 | Works out of the box. |
| `ncps` (CfC LNN) | Pure Python + torch dependency | Any | Works once torch is installed. |
| `websockets` | Pure Python | Any | Works. |
| `numpy` | **Yes** — `manylinux_aarch64` | cp38–cp314 | Works. |

**PyTorch SIGILL note:** The widely reported SIGILL crash (`ldaddal` instruction, LSE atomics) affects **Pi 4 and older** (Cortex-A72, no LSE). **Pi 5's Cortex-A76 supports LSE atomics** — the prebuilt `torch` aarch64 wheel works on Pi 5. If you still hit SIGILL, build torch from source with `-DCMAKE_C_FLAGS=-march=armv8.2-a`. The GarudaOne CfC LNN is tiny (1621 params) — torch CPU inference is sub-ms and the SIGILL issue is unlikely to manifest.

**Real-time / PREEMPT_RT:**
- DietPi uses the same Raspberry Pi Linux kernel tree as RPi OS (it's a Debian userland on the RPi foundation kernel). The `remusmp/rpi-rt-kernel` project and `emlid/linux-rt-rpi` provide PREEMPT_RT-patched kernels that work on any Debian-based Pi distro, including DietPi.
- **Linux kernel 6.12+ has RT merged into mainline for ARM64** (no patch needed). DietPi Trixie ships kernel 6.12+ — RT can be enabled via `CONFIG_PREEMPT_RT=y` in a custom kernel build or via the rpi-rt-kernel repo.
- For GarudaOne, **PREEMPT_RT is nice-to-have, not required.** The 20 Hz OFFBOARD loop has a 50 ms period — even a non-RT kernel with `chrt -f 80` (SCHED_FIFO) and CPU pinning via `taskset` achieves <1 ms jitter. The hard real-time safety floor is PX4 on NuttX (L3), not the companion Pi. See architecture: "L3 PX4 (hard real-time safety floor, 400 Hz)" — the Pi is advisory only.

**Advantages for GarudaOne specifically:**
1. **152 MiB idle RAM** — 88 MiB less than RPi OS Lite, ~100–200 MiB less than Ubuntu. That's ~50–100 extra tokens of LFM KV cache, or more buffer for the 25 Hz perception pipeline.
2. **2.768 s boot** — get to OFFBOARD-ready fast. Critical for a drone that needs the companion brain alive before arming.
3. **9 processes** — minimal scheduler interference with the 20 Hz pymavlink setpoint stream. No snapd, no cloud-init, no pollinate, no apport, no unattended-upgrades daemon.
4. **Logs on tmpfs** — FDR recording to SD card has zero log-write I/O contention. Model loads from SD card are not competing with syslog/journal writes.
5. **DietPi-Software** — one-command install of common tools (Python, Node.js, Git, build tools) without apt dependency hell.
6. **dietpi-config** — easy overclocking (2.0–2.2 GHz per GarudaOne pitfall #9), GPU memory split, I2C/SPI/UART enablement via menu.
7. **First-boot automation** — `dietpi.txt` and `dietpi-software` config files on the boot partition let you pre-configure the entire system before first boot. No manual SSH setup.

**Disadvantages:**
1. **Smaller community than RPi OS** — but DietPi is Debian under the hood. Any Debian/RPi OS tutorial works with minor path adjustments.
2. **DietPi's own software catalog** can be opinionated — but you don't have to use it. `apt` and `pip` work normally.
3. **First boot takes longer** (does updates + configuration) — but subsequent boots are the 2.768 s measured above.
4. **Not an "official" Raspberry Pi product** — but it uses the official RPi kernel and firmware. The userland is DietPi's. No hardware support risk.

---

### 2. Raspberry Pi OS Lite 64-bit (Trixie/Bookworm) — STRONG SECOND CHOICE

**What it is:** The official Raspberry Pi Foundation OS, Lite version (no desktop). Debian-based. The most widely used Pi OS.

**Measured stats on Pi 5 (Trixie 64-bit, tested 2026-04-02, source: dietpi.com/stats.html):**
| Stat | Value |
|---|---|
| RAM usage (idle) | **240 MiB** |
| Running processes | 24 |
| Disk usage | 2639 MiB |
| Pre-installed packages | 658 |
| Boot duration | 15.836 s |
| Temp files | RAM disk (tmpfs) |
| Log files | **rootfs (SD card)** ← I/O contention risk |
| SSH pre-installed | edit required (must enable via raspi-config or boot/ssh) |
| Download size | 487 MiB |
| Image size | 2848 MiB |

**Python version:**
- Bookworm (Debian 12): Python **3.11** (pre-installed, system-managed via PEP 668 — must use venv or `--break-system-packages`)
- Trixie (Debian 13): Python **3.13** (available via apt)

**ML library support:** Identical to DietPi. Same kernel, same glibc, same aarch64 PyPI wheels. The only difference is DietPi uses fewer packages and tmpfs for logs.

**Key issue — PEP 668 (externally-managed Python):** Bookworm and Trixie enforce PEP 668. `pip install` outside a venv is blocked:
```
error: externally-managed-environment
× This environment is externally managed
```
**Fix:** Always use a venv (`python3 -m venv ~/garudaone-venv && source ~/garudaone-venv/bin/activate`) or `pipx`. This is the correct practice anyway for a production drone. DietPi has the same PEP 668 enforcement (it's Debian, not DietPi-specific).

**Real-time / PREEMPT_RT:** Best-in-class. The `rpi-rt-kernel` project and Emlid's `linux-rt-rpi` are tested primarily against RPi OS. The official RPi kernel tree is the reference implementation. If you want PREEMPT_RT with zero friction, RPi OS is the path of least resistance.

**Why it's second, not first:**
- 88 MiB more idle RAM than DietPi (240 vs 152). On 8 GB, that's 1.1% — small but non-zero when you're fighting for every MB of KV cache.
- 15.8 s boot vs 2.768 s. 13 extra seconds on the ground with FC armed.
- 24 processes vs 9. More scheduler noise.
- Logs on rootfs (SD card), not tmpfs. FDR + model load I/O contention.
- 658 packages vs 251. More attack surface, more things that can break, more apt upgrade time.

**When to choose RPi OS Lite over DietPi:** If you need maximum ecosystem compatibility (every tutorial, every library, every hardware add-on is tested on RPi OS first), or if you want the absolute easiest PREEMPT_RT path (rpi-rt-kernel is tested on RPi OS).

---

### 3. Ubuntu Server 24.04 LTS (Noble) — NOT RECOMMENDED (current target — change it)

**What it is:** Canonical's server-oriented Ubuntu for Raspberry Pi. Debian-based but with Ubuntu's own package selection, snapd, cloud-init, and Canonical-specific tooling.

**Measured stats:** Ubuntu Server is NOT included in DietPi's comparison table (DietPi only compares against Debian/Armbian/RPi OS). Based on community reports and component analysis:

| Stat | Estimated Value | Source |
|---|---|---|
| RAM usage (idle) | **~250–350 MiB** | snapd (~37 MiB), cloud-init, systemd-networkd-wait-online, pollinate, apport, unattended-upgrades, systemd-resolved, etc. |
| Boot time | **~30–45 s** | cloud-init + snapd seeding + network wait. Forum: "each command takes forever" |
| Running processes | 30–40+ | systemd services + snapd + cloud-init |
| Disk usage | ~2500+ MiB | Larger than RPi OS Lite due to snap seed data |
| Python version | **3.12** | Noble ships Python 3.12 |

**Why it's bloated (the specific culprits):**

1. **snapd** — The biggest offender. Uses ~37 MiB RAM at idle (measured, Level1Techs forum). Known to "hammer CPU" on ARM (Ask Ubuntu #1553378: "4 gig of RAM and 8 gig of swap is completely insufficient"). On a drone, a background daemon spiking CPU during your 20 Hz control loop is a direct threat to flight safety. **snapd can be removed** (`sudo apt purge snapd`) but then you lose `rpi-imager` (snap-only on Ubuntu) and some Canonical tooling.

2. **cloud-init** — Designed for cloud VMs, not drones. Delays boot by 10–30 seconds waiting for network metadata service. Can be disabled but is installed by default.

3. **systemd-networkd-wait-online** — Blocks boot for up to 2 minutes waiting for network. On a drone that may not have network at boot (it's in the air), this is actively harmful. Must be disabled.

4. **pollinate** — Canonical's entropy-gathering service that phones home to entropy.ubuntu.com. Unnecessary on a Pi with hardware RNG.

5. **apport** — Crash report tool. Catches SIGSEGV/SIGILL and writes reports to disk. On a drone, if torch SIGILLs, you want the core dump, not apport intercepting it.

6. **unattended-upgrades** — Automatically installs security updates. On a drone in flight, an apt lock + dpkg running in the background can stall your control loop. Must be disabled.

7. **Ubuntu Pro / Livepatch** — Canonical's commercial offering. Snaps kernel patches. Irrelevant for a drone and adds a daemon.

8. **systemd-resolved** — DNS stub resolver. Uses ~20 MiB. Unnecessary for a drone talking to a FC over UART.

**Total bloat estimate:** snapd (37) + cloud-init (30) + networkd-wait-online (10) + pollinate (5) + apport (10) + unattended-upgrades (15) + resolved (20) + misc Ubuntu services (30) ≈ **~157 MiB of daemons that do nothing useful on a drone.** Removing all of them gets you close to RPi OS Lite's 240 MiB — but you've spent an hour purging Ubuntu's "value-add" when DietPi starts at 152 MiB with none of it.

**Forum evidence:**
- "Ubuntu 24.04 running slow on Pi 5" (raspberrypi.com forum): "4K video is dropping frames, each command takes forever, opening apps is with delay up to a 30 s"
- Ask Ubuntu #1553378: "snapd hammering CPU, server is out of RAM" — "4 gig of RAM and 8 gig of swap is completely insufficient for a 'test' server"
- Level1Techs: "snapd does seem to be using at least 36.93 MB of RAM at idle"

**ML library support:** Same as DietPi/RPi OS — all packages have aarch64 wheels. Python 3.12 (Noble) is fine. No advantage over DietPi here.

**Real-time / PREEMPT_RT:** Possible but harder. Ubuntu's kernel is mainline-based. Linux 6.12+ has RT in mainline for ARM64, but Ubuntu's Pi kernel lags behind RPi's kernel tree. The rpi-rt-kernel project targets RPi OS, not Ubuntu. You'd need to build a custom kernel, which is more work on Ubuntu than on RPi OS/DietPi.

**Verdict:** Ubuntu Server 24.04 is the worst choice for GarudaOne. It's designed for cloud servers, not embedded real-time systems. Every advantage it offers (snap ecosystem, cloud-init, Ubuntu Pro) is irrelevant or harmful on a drone. The user is correct that it's bloated. **Switch to DietPi.**

---

### 4. Other Minimal OS Candidates

#### 4a. Alpine Linux — REJECTED

**What it is:** Security-oriented, ultra-lightweight Linux based on musl libc and BusyBox. Idle RAM ~20–30 MiB. The lightest option.

**Why rejected:**
- **musl libc breaks many Python wheels.** PyPI wheels tagged `manylinux` require glibc. `musllinux` wheels exist for some packages but NOT all. Specifically:
  - `llama-cpp-python`: No musllinux wheel. Must build from source — and it links against glibc-specific features.
  - `torch`: No musllinux aarch64 wheel on PyPI. Must build from source (hours on Pi 5).
  - `ncnn`: Has `musllinux_1_2_aarch64` wheel ✓ — but the overall stack breaks.
  - `opencv-python`: No musllinux wheel. Build from source (30+ min).
- **No PEP 668 venv story tested.** Alpine's Python packaging is different.
- **OpenRC instead of systemd.** Not a problem per se, but all GarudaOne service files (if any) would need rewriting.
- **The RAM savings (20–30 MiB vs DietPi's 152) are not worth the pip compatibility nightmare.** The GarudaOne stack has 6+ compiled Python packages. Building each from source on Alpine is days of work.

#### 4b. Armbian Minimal — VIABLE BUT NO ADVANTAGE OVER DIETPI

**Measured stats on Pi 5 (Trixie 64-bit, tested 2026-04-02, source: dietpi.com/stats.html):**
| Stat | Armbian Minimal | DietPi |
|---|---|---|
| RAM usage | 186 MiB | 152 MiB |
| Running processes | 21 | 9 |
| Disk usage | 1148 MiB | 894 MiB |
| Boot duration | 5.224 s | 2.768 s |

**Verdict:** Armbian is good but DietPi beats it on every metric. Armbian's value is broad SBC support (not just Pi), but GarudaOne only targets Pi 5. No reason to choose Armbian over DietPi for this project.

#### 4c. Kali Linux ARM — REJECTED

Security-focused, heavyweight. ~400+ MiB idle RAM. Tons of pre-installed tools irrelevant to a drone. Not minimal. Rejected.

#### 4d. Debian Netinst (vanilla Debian) — VIABLE BUT MORE WORK

Debian network installer gives you the most control but requires manual configuration of everything DietPi automates (tmpfs for logs, minimal package set, Pi-specific firmware). End result is similar to DietPi but with more manual work. No advantage.

#### 4e. NixOS — INTERESTING BUT TOO COMPLEX

Reproducible builds, declarative config — great for a production drone fleet. But the learning curve is steep, aarch64 binary cache coverage for ML packages is incomplete (llama-cpp-python, ncnn may need building), and the Nix store uses more disk. Not worth it for a prototype.

---

## Package Compatibility Matrix (all on aarch64 + Python 3.11+)

| Package | PyPI aarch64 wheel | Build-from-source needed? | Works on DietPi? | Works on RPi OS? | Works on Ubuntu? |
|---|---|---|---|---|---|
| `llama-cpp-python` | ❌ (source only on Linux ARM) | ✅ **Yes — required** | ✅ | ✅ | ✅ |
| `ncnn` | ✅ `manylinux_2_24_aarch64` | ❌ | ✅ | ✅ | ✅ |
| `torch` (CPU) | ✅ `manylinux_2_28_aarch64` | ❌ (Pi 5 A76 has LSE) | ✅ | ✅ | ✅ |
| `opencv-python-headless` | ✅ `manylinux_aarch64` | ❌ | ✅ | ✅ | ✅ |
| `pymavlink` | ✅ (pure Python + C ext) | ❌ | ✅ | ✅ | ✅ |
| `ncps` (CfC LNN) | ✅ (pure Python, needs torch) | ❌ | ✅ | ✅ | ✅ |
| `numpy` | ✅ `manylinux_aarch64` | ❌ | ✅ | ✅ | ✅ |
| `websockets` | ✅ (pure Python) | ❌ | ✅ | ✅ | ✅ |
| `pytest` | ✅ (pure Python) | ❌ | ✅ | ✅ | ✅ |

**Key insight:** `piwheels.org` does NOT support aarch64 (it only builds armv6l/armv7l 32-bit wheels — confirmed on the piwheels ncnn page: "Notice: piwheels does not currently support aarch64"). But this **does not matter** because:
1. Pi 5 runs a 64-bit OS (aarch64), and PyPI now has native aarch64 `manylinux` wheels for all GarudaOne packages.
2. `llama-cpp-python` must be built from source on ANY OS (no prebuilt aarch64 Linux wheel on PyPI) — this is not an OS-specific issue.
3. The `manylinux_2_24_aarch64` and `manylinux_2_28_aarch64` wheel tags work on any glibc 2.24+ or 2.28+ ARM64 Linux. DietPi Trixie (glibc 2.41), RPi OS Trixie, and Ubuntu 24.04 (glibc 2.39) all satisfy this.

**Conclusion: package compatibility is identical across all three OSes.** The OS choice is about RAM, boot time, and bloat — not package availability.

---

## PX4 / MAVLink Support

All three OSes support PX4 companion computer workflows identically:
- **pymavlink:** pip install, works on any Linux + Python 3.11+. Pure Python with a C extension that compiles via setuptools.
- **MAVSDK-Python:** pip install, works on any Linux + Python 3.11+.
- **UART connection:** `/dev/ttyAMA0` on Pi 5 (serial0). Must enable in `config.txt` / `raspi-config` / `dietpi-config`. All three OSes expose the same serial device.
- **PX4 SITL:** Not run on the Pi — it runs on the dev machine (WSL Ubuntu in GarudaOne's case). The Pi only runs the companion stack.

**No OS-specific PX4 advantage.** DietPi, RPi OS, and Ubuntu all work equally well with PX4/pymavlink.

---

## Real-Time Scheduling Support

| Feature | DietPi | RPi OS Lite | Ubuntu Server |
|---|---|---|---|
| Standard kernel PREEMPT (voluntary) | ✅ | ✅ | ✅ |
| PREEMPT_RT kernel (hard RT) | ✅ via rpi-rt-kernel | ✅ via rpi-rt-kernel (reference) | ✅ via mainline 6.12+ (harder) |
| `chrt` (SCHED_FIFO/RR) | ✅ | ✅ | ✅ |
| `taskset` (CPU pinning) | ✅ | ✅ | ✅ |
| `isolcpus` boot param | ✅ | ✅ | ✅ |
| Kernel 6.12+ (RT in mainline for ARM64) | ✅ (Trixie) | ✅ (Trixie) | ✅ (needs HWE kernel) |

**For GarudaOne, PREEMPT_RT is optional.** The architecture puts hard real-time on PX4/NuttX (L3, 400 Hz). The Pi companion is advisory (L1/L2, 20 Hz). Standard `chrt -f 80` + `taskset` on a non-RT kernel achieves <1 ms jitter at 20 Hz. PREEMPT_RT is a nice-to-have for the 25 Hz perception pipeline but not required for the 20 Hz OFFBOARD loop.

**If you do want PREEMPT_RT:** DietPi and RPi OS both use the RPi foundation kernel tree, so `rpi-rt-kernel` (github.com/remusmp/rpi-rt-kernel) works on both. Ubuntu uses a different kernel base and the RT path is harder.

---

## RAM Budget on 8 GB Pi 5 (DietPi vs Ubuntu)

### With DietPi (152 MiB OS):
```
Total RAM:              8192 MB
OS idle:                 152 MB
Linux filesystem cache:  ~500 MB (reclaimable)
─── Available for app:  ~7500 MB ───
LFM2.5-VL-450M Q8_0:      379 MB (model weights)
KV cache (Q4, 4K ctx):   ~200 MB
mmproj (vision):          ~80 MB
PicoDet ncnn working set:  ~50 MB
OpenCV (headless):        ~100 MB
Python runtime + venv:     ~50 MB
pymavlink + DroneLink:     ~20 MB
CfC LNN (torch, 1621p):    ~30 MB (torch overhead ~200 MB if loaded)
FDR recorder buffers:      ~50 MB
Tracker + ToF:             ~30 MB
WebSocket server:          ~10 MB
─── Subtotal app:       ~1399 MB ───
FREE HEADROOM:          ~6100 MB  ← plenty for larger models, more context, training
```

### With Ubuntu Server (~300 MiB OS + bloat):
```
Total RAM:              8192 MB
OS idle:                 300 MB
snapd + cloud-init:       ~50 MB (if not purged)
Linux filesystem cache:  ~500 MB (reclaimable)
─── Available for app:  ~7340 MB ───
(same app stack)         ~1399 MB
FREE HEADROOM:          ~5940 MB  ← ~160 MB less than DietPi
```

**The 160 MB difference matters.** It's:
- ~800 extra tokens of LFM KV cache (at ~200 bytes/token Q4), OR
- The entire PicoDet ncnn working set (50 MB) × 3, OR
- Enough to run a second small model (Needle 26M = 14 MB + overhead)

On a drone fighting for every MB of model headroom, DietPi's 152 MiB base is a meaningful advantage.

---

## Recommendation: DietPi Trixie 64-bit

### Installation Steps for GarudaOne Pi 5

#### Step 1: Flash DietPi to SD card
```bash
# On dev machine (Windows):
# Option A: Use Raspberry Pi Imager
#   → Choose OS → DietPi → DietPi for Raspberry Pi 5 (ARMv8/64-bit)
#   → Flash to 32GB+ microSD (A2 V30 recommended)

# Option B: Direct download + balenaEtcher
#   Download: https://dietpi.com/downloads/images/DietPi_RPi-ARMv8-(64bit).7z
#   Extract .img, flash with balenaEtcher or Rufus
```

#### Step 2: Pre-configure (before first boot)
Mount the boot partition on the dev machine and edit these files:

**`dietpi.txt`** (DietPi config — on boot partition):
```ini
# --- Network ---
AUTO_SETUP_NET_ETHERNET_ENABLED=1
# (or set WiFi if no Ethernet):
# AUTO_SETUP_NET_WIFI_ENABLED=1
# AUTO_SETUP_NET_WIFI_COUNTRY_CODE=IN
# aWIFI_SSID[0]="YourNetwork"
# aWIFI_KEY[0]="YourPassword"

# --- Hostname ---
AUTO_SETUP_NET_HOSTNAME=garudaone

# --- Software (skip auto-install, we'll do it manually) ---
AUTO_SETUP_INSTALL_SOFTWARE_ID=0

# --- Overclock (per GarudaOne pitfall #9: 2.0-2.2 GHz) ---
# CONFIG_CPU_GOVERNOR=ondemand  # set in dietpi-config after boot

# --- Disable unnecessary services ---
AUTO_SETUP_SERIAL_CONSOLE_ENABLED=1   # keep for FC UART debugging

# --- Timezone ---
AUTO_SETUP_TIMEZONE=Asia/Kolkata

# --- APT mirror (fast India mirror) ---
# AUTO_SETUP_APT_RASPBIAN_MIRROR=http://mirror.raspi.ind.in/raspbian/

# --- Disable automatic updates (don't want apt running during flight) ---
AUTO_SETUP_AUTO_UPDATE=0
```

**`config.txt`** (Pi hardware config — on boot partition, edit existing):
```ini
# Enable UART for PX4 FC connection (ttyAMA0)
enable_uart=1

# Pi 5 overclock (per GarudaOne pitfall #9)
# (set via dietpi-config > Performance > CPU after first boot)

# GPU memory split (headless, minimize GPU RAM)
gpu_mem=16

# I2C for VL53L8CX ToF sensor
dtparam=i2c_arm=on

# SPI (if using TMF8829 ToF on production PCB)
# dtparam=spi=on

# Camera (Skydroid C10 Pro is USB, but keep CSI enabled)
# camera_auto_detect=1

# Disable audio (save RAM, avoid codec loading)
dtparam=audio=off

# Boot to console, no desktop
# (DietPi Lite is already headless)
```

Create empty file `boot/ssh` equivalent — DietPi has SSH enabled by default, so skip this.

#### Step 3: First boot
```bash
# Insert SD, power on Pi 5
# Wait for first-boot configuration (~2-5 min, one-time)
# SSH in:
ssh root@garudaone.local
# Default password: dietpi (change immediately!)

# Change password
passwd

# Update (one-time, not during flight):
dietpi-update
apt update && apt upgrade -y
```

#### Step 4: Install build tools and Python
```bash
# Via dietpi-software (interactive) or apt:
dietpi-software install 9  # Python 3 (installs pip, venv)

# Or via apt:
apt install -y python3 python3-pip python3-venv python3-dev \
    build-essential cmake git wget curl \
    libcurl4-openssl-dev libssl-dev \
    libopencv-dev  # system OpenCV (optional, we'll use pip opencv-python-headless)

# Verify Python version (Trixie = 3.13, Bookworm = 3.11)
python3 --version  # should be 3.13.x (Trixie) or 3.11.x (Bookworm)
```

#### Step 5: Create GarudaOne venv
```bash
# PEP 668: must use venv (same on DietPi as RPi OS Bookworm/Trixie)
python3 -m venv ~/garudaone-venv
source ~/garudaone-venv/bin/activate
pip install --upgrade pip wheel setuptools
```

#### Step 6: Install ML stack (in venv)
```bash
# 1. numpy (foundation)
pip install numpy

# 2. llama-cpp-python — BUILD FROM SOURCE for Pi 5 A76 optimizations
# This takes ~10-15 minutes on Pi 5
CMAKE_ARGS="-DCMAKE_C_FLAGS=-march=armv8.2-a+dotprod+i8mm \
            -DCMAKE_CXX_FLAGS=-march=armv8.2-a+dotprod+i8mm" \
pip install llama-cpp-python --no-binary llama-cpp-python --force-reinstall

# 3. ncnn (prebuilt aarch64 wheel)
pip install ncnn  # manylinux_2_24_aarch64, 4.3 MB

# 4. PyTorch CPU (prebuilt aarch64 wheel, works on Pi 5 Cortex-A76)
pip install torch --index-url https://download.pytorch.org/whl/cpu
# If SIGILL: build from source with -march=armv8.2-a (unlikely on Pi 5)

# 5. OpenCV (headless — no GUI deps)
pip install opencv-python-headless

# 6. pymavlink (PX4 MAVLink)
pip install pymavlink

# 7. ncps (CfC LNN)
pip install ncps

# 8. WebSockets (text server)
pip install websockets

# 9. Test/dev
pip install pytest pytest-asyncio pyyaml
```

#### Step 7: Clone GarudaOne repo
```bash
cd ~
git clone https://github.com/SREESAIARJUN/GarudaOne.git
cd GarudaOne/garudaone-software
pip install -e ".[dev]"

# Verify tests pass
python -m pytest tests/ -v
```

#### Step 8: CPU pinning for flight (per GarudaOne pitfall #9)
```bash
# Pin ncnn to 2 cores max (never let it autospawn 4)
# This is done in Python: ncnn.VulkanDevice() or thread count in Net
# At OS level, use taskset for the main runtime:

# Isolate core 3 for the 20 Hz control loop (optional, advanced):
# Add to /boot/cmdline.txt:
#   isolcpus=3 nohz_full=3 rcu_nocbs=3

# Run GarudaOne runtime with CPU affinity:
taskset -c 0-2 python -m garudaone.main  # main app on cores 0-2
# OR pin control loop to core 3 with real-time priority:
chrt -f 80 taskset -c 3 python -m garudaone.main
```

#### Step 9: Disable flight-irrelevant services
```bash
# DietPi already minimal, but ensure these are off:
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer
systemctl disable --now bluetooth  # if not using BT
systemctl disable --now wpa_supplicant  # if using Ethernet only

# Disable swap (we have 8GB, swap adds latency):
dphys-swapfile uninstall  # or: swapoff -a && rm /var/swap
```

#### Step 10: PX4 UART connection
```bash
# Enable serial port (if not done in config.txt):
# dietpi-config > Advanced > Serial console
# OR edit /boot/config.txt: enable_uart=1

# Verify:
ls -la /dev/ttyAMA0  # should exist
stty -F /dev/ttyAMA0 921600  # match PX4 SER_TEL1_BAUD

# Test pymavlink connection:
python3 -c "
from pymavlink import mavutil
conn = mavutil.mavlink_connection('serial:///dev/ttyAMA0:921600')
conn.wait_heartbeat()
print('PX4 connected!')
"
```

---

## Action Items

1. **Update doc 12 (rebuild plan) companion OS line** from "Ubuntu 24.04 LTS ARM" to "DietPi Trixie 64-bit ARM"
2. **Update GarudaOne skill tech stack table** companion OS row
3. **Add DietPi to the GarudaOne skill** as a reference doc with installation steps
4. **Test on actual Pi 5 hardware** (S6 milestone: Pi bring-up) — measure actual idle RAM with `free -tm` and boot time with `systemd-analyze`
5. **If PREEMPT_RT is needed**: use `rpi-rt-kernel` (github.com/remusmp/rpi-rt-kernel) — works on DietPi since it uses the same RPi kernel tree

---

## Sources

- DietPi official stats (Pi 5, Trixie 64-bit, tested 2026-04-02): https://dietpi.com/stats.html
- DietPi vs RPi OS Lite comparison: https://pcbsync.com/dietpi-vs-raspberry-pi-os-lite/
- Minimal OS showdown (DietPi 30-50 MB, RPi OS Lite 60-80 MB on Pi Zero): https://www.tech-reader.blog/2025/05/insight-great-minimal-os-showdowndietpi.html
- Ubuntu snapd RAM at idle (36.93 MB): https://forum.level1techs.com/t/ubuntu-server-25-10-safest-way-to-disable-remove-snapd-in-2026/247127
- Ubuntu snapd CPU hammering + OOM: https://askubuntu.com/questions/1553378/snapd-hammering-cpu-server-is-out-of-ram
- Ubuntu 24.04 slow on Pi 5: https://forums.raspberrypi.com/viewtopic.php?t=375010
- piwheels does NOT support aarch64 (notice on ncnn page): https://www.piwheels.org/project/ncnn/
- ncnn PyPI aarch64 wheels (manylinux_2_24/2_28_aarch64, cp310-cp314): https://pypi.org/project/ncnn/#files
- PyTorch SIGILL on Pi 4 (Cortex-A72, no LSE) — does NOT affect Pi 5 (Cortex-A76, has LSE): https://github.com/pytorch/pytorch/issues/132032
- llama-cpp-python build from source on Pi 5 with ARM optimizations: https://www.sitepoint.com/llms-raspberry-pi-edge/
- rpi-rt-kernel (PREEMPT_RT for Pi, works on DietPi): https://github.com/remusmp/rpi-rt-kernel
- Linux 6.12+ RT merged into mainline for ARM64: https://github.com/by/RT-Kernel
- DietPi v9.15 (Trixie upgrade, July 2025): https://dietpi.com/blog/?p=3128
- RPi OS Bookworm Python 3.11 + PEP 668: https://www.tomshardware.com/how-to/install-python-modules-raspberry-pi
- pymavlink piwheels page (works on Pi): https://www.piwheels.org/project/pymavlink/

---

## Appendix: Quick Comparison Card

```
┌─────────────────────────────────────────────────────────────────────┐
│                    GarudaOne Pi 5 OS Comparison                     │
├──────────────────┬──────────┬──────────┬──────────┬────────────────┤
│ Metric           │ DietPi   │ RPi OS   │ Ubuntu   │ Alpine         │
│                  │ Trixie64 │ Lite64   │ Server24 │ (rejected)     │
├──────────────────┼──────────┼──────────┼──────────┼────────────────┤
│ Idle RAM         │ 152 MB ★ │ 240 MB   │ ~300 MB  │ ~30 MB         │
│ Boot time        │ 2.8 s  ★ │ 15.8 s   │ ~30-45 s │ ~5 s           │
│ Processes        │ 9      ★ │ 24       │ 30-40+   │ ~10            │
│ Disk usage       │ 894 MB ★ │ 2639 MB  │ ~2500 MB │ ~130 MB        │
│ Python           │ 3.13   ★ │ 3.13     │ 3.12     │ 3.13 (musl)    │
│ snapd bloat      │ None   ★ │ None     │ ~37 MB   │ None           │
│ Logs on tmpfs    │ Yes    ★ │ No (SD)  │ No (SD)  │ Yes            │
│ pip aarch64      │ Full   ★ │ Full     │ Full     │ BROKEN (musl)  │
│ PREEMPT_RT       │ Easy   ✓ │ Easiest ✓│ Harder   │ Unknown        │
│ PX4/pymavlink    │ Works  ✓ │ Works  ✓ │ Works  ✓ │ Unknown        │
│ Community size   │ Medium   │ Largest ★│ Large    │ Small          │
├──────────────────┼──────────┼──────────┼──────────┼────────────────┤
│ VERDICT          │ WINNER ★ │ 2nd      │ 3rd (✗)  │ REJECTED       │
└──────────────────┴──────────┴──────────┴──────────┴────────────────┘
```

**DietPi Trixie 64-bit. Flash it, configure it, fly.**
