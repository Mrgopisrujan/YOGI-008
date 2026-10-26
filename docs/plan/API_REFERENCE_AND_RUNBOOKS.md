# GarudaOne API Reference & Operational Runbooks
## Complete Developer & AI Agent Execution Guide

---

## 1. Quickstart Runbooks

### Runbook A: Launching the Simulator
To run the photorealistic `Neighborhood` environment:

```powershell
# 1. Ensure no existing instances are running
taskkill /F /IM AirSimNH-Win64-Shipping.exe /T 2>$null

# 2. Launch simulator as background process with working directory set
$simPath = "C:\Projects\drone-sim\sim_worlds\Neighborhood\AirSimNH\Binaries\Win64"
Start-Process -FilePath "$simPath\AirSimNH-Win64-Shipping.exe" `
              -ArgumentList "-LOG -stdout" `
              -WorkingDirectory $simPath

# 3. Wait for initialization and test TCP connectivity
Start-Sleep -Seconds 6
Test-NetConnection -ComputerName 127.0.0.1 -Port 8989
```

---

### Runbook B: Running the Autonomous Mission Recorders

#### 1. Outdoor Dynamic Street Mission
```powershell
python record_video1_dynamic_street.py
```
- **Generated Outputs:**
  - `garudaone_outdoor_dynamic_mission.mp4`
  - `garudaone_outdoor_preview.gif`

#### 2. Indoor Enclosed Facility Mission
```powershell
python record_video2_indoor_mission.py
```
- **Generated Outputs:**
  - `garudaone_indoor_mission.mp4`
  - `garudaone_indoor_preview.gif`

---

### Runbook C: Clean Teardown
```powershell
taskkill /F /IM AirSimNH-Win64-Shipping.exe /T
taskkill /F /IM Blocks-Win64-Shipping.exe /T
taskkill /F /IM LandscapeMountains-Win64-Shipping.exe /T
taskkill /F /IM DynamicCity-Win64-Shipping.exe /T
```

---

## 2. Python Client API Essentials

### Basic Connection Pattern
```python
import projectairsim
import os
import asyncio

async def fly_mission():
    client = projectairsim.ProjectAirSimClient()
    try:
        client.connect()
        sim_dir = os.path.abspath("sim_config")
        world = projectairsim.World(client, "scene_basic_drone.jsonc", delay_after_load_sec=1, sim_config_path=sim_dir)
        drone = projectairsim.Drone(client, world, "Drone1")

        # Arm & Takeoff
        drone.enable_api_control()
        drone.arm()
        t = await drone.takeoff_async()
        await t

        # Climb 2 meters (negative Z in NED)
        t_climb = await drone.move_by_velocity_async(v_north=0.0, v_east=0.0, v_down=-2.0, duration=1.5)
        await t_climb

        # Hover
        await drone.hover_async()

        # Telemetry query
        kin = drone.get_ground_truth_kinematics()
        pos = kin['pose']['position']
        print(f"Drone at X={pos['x']:.2f}, Y={pos['y']:.2f}, Z={pos['z']:.2f}")

        # Land
        t_land = await drone.land_async()
        await t_land
        drone.disarm()
        drone.disable_api_control()

    finally:
        client.disconnect()

if __name__ == "__main__":
    asyncio.run(fly_mission())
```

---

### Subscribing to Live Onboard Camera Frames
```python
import numpy as np

frames = []

def on_camera_frame(topic, msg):
    width = msg['width']
    height = msg['height']
    raw_bytes = msg['data']
    # Reshape byte array into standard OpenCV BGR image
    bgr_img = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((height, width, 3))
    frames.append(bgr_img)

# "Chase" sensor is mapped to the Front Nose Camera in robot_quadrotor_fastphysics.jsonc
client.subscribe(drone.sensors["Chase"]["scene_camera"], on_camera_frame)
```

---

### Spawning Dynamic 3D Actors in Unreal
```python
from projectairsim.types import Pose, Vector3, Quaternion

# Define spawn pose in global NED
actor_pose = Pose({
    "translation": Vector3({"x": 5.2, "y": 14.0, "z": -1.2}),  # Z must be <= -1.0 to clear ground collision
    "rotation": Quaternion({"w": 0.0, "x": 0.0, "y": 0.0, "z": 1.0}),
    "frame_id": "DEFAULT_ID"
})

# Spawn Actor: (name, asset_registry_name, pose, scale [x,y,z], enable_physics)
actor_name = world.spawn_object("MySportsCar", "SKM_SportsCar", actor_pose, [1.0, 1.0, 1.0], False)
```

### Animating Actors in Real Time
```python
new_pose = Pose({
    "translation": Vector3({"x": 5.2, "y": 14.0 + current_distance, "z": -1.2}),
    "rotation": Quaternion({"w": 0.0, "x": 0.0, "y": 0.0, "z": 1.0}),
    "frame_id": "DEFAULT_ID"
})
world.set_object_pose(actor_name, new_pose, teleport=True)
```

---

### Visual Servoing Math Snippet
```python
def compute_servoing_command(bbox, frame_width=1280, frame_height=720):
    x1, y1, x2, y2 = bbox
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    
    # Normalized error (-1.0 to +1.0)
    err_x = (cx - (frame_width / 2.0)) / (frame_width / 2.0)
    err_y = (cy - (frame_height / 2.0)) / (frame_height / 2.0)
    
    # Control gains
    K_yaw = 0.8   # rad/s per normalized error
    K_z   = 0.5   # m/s per normalized error
    
    yaw_rate = K_yaw * err_x
    v_down   = -K_z * err_y
    
    return yaw_rate, v_down
```

---

## 3. Common Troubleshooting Guide

| Symptom / Error | Root Cause | Solution |
| :--- | :--- | :--- |
| `RuntimeError: Timeout waiting to get topic info from sim server.` | An earlier Python script crashed or was cancelled without calling `client.disconnect()`, leaving NNG `Pair0` socket locked. | Check for established sockets: `netstat -ano \| findstr 8989 \| findstr ESTABLISHED`. Kill the process ID found holding the socket. |
| `RuntimeError: SetObjectPose failed. Unable to move object, check if object state is movable!` | The actor's translation $Z$ coordinate is penetrating the ground terrain collision mesh. | Set $Z = -1.0\,\text{m}$ to $-1.2\,\text{m}$ instead of $-0.5\,\text{m}$ or $0.0\,\text{m}$. |
| `AirSimNH-Win64-Shipping.exe` exits immediately on launch. | Working directory was not set to the binary directory, causing it to fail to find `Content/Paks`. | Pass `-WorkingDirectory "C:\Projects\drone-sim\sim_worlds\Neighborhood\AirSimNH\Binaries\Win64"`. |
| YOLO detects drone propellers as "boat" or "elephant". | Camera origin is placed at frame center or behind the propellers ($X \le 0.25\,\text{m}$). | Set camera origin in `robot_quadrotor_fastphysics.jsonc` to `xyz: "0.48 0.0 -0.08"`. |
| `RuntimeError: There were no objects with name X found in the Registry`. | Typo in Unreal asset name or static mesh name. | Refer to the discovered asset list in `docs/SYSTEM_ARCHITECTURE_AND_HANDOFF.md` (e.g. use `Outer_Wall_01`, not `Inner_Wall_01`). |
