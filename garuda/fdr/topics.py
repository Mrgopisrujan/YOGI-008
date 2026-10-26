"""FDR topics — names for recorded data channels."""

from __future__ import annotations

# All topics that the FDR records (jsonl format, KD25)
TOPICS = [
    "bbox",           # perception: bbox detection
    "tof",            # perception: ToF grid
    "ekf2",           # PX4: EKF2 state estimate
    "setpoints",      # control: velocity setpoints sent to PX4
    "gimbal_cmd",     # gimbal: command sent
    "gimbal_state",   # gimbal: joint angles feedback
    "arbiter_grant",  # arbiter: mode grant decisions
    "cpu_temp",       # telemetry: CPU temperature
    "battery",        # telemetry: battery voltage
    "preflight",      # preflight snapshot
]
