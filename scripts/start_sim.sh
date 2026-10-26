#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

SIM_BIN="/home/balaraj/autonovaz/ProjectAirSim-Linux/CityEnviron/Binaries/Linux/CityEnviron-Linux-Shipping"

export DISPLAY=:0
XAUTH=$(ls -t /run/user/$(id -u)/.mutter-Xwaylandauth.* 2>/dev/null | head -1 || echo "$HOME/.Xauthority")
export XAUTHORITY="$XAUTH"
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json
export __NV_PRIME_RENDER_OFFLOAD=1
export __GLX_VENDOR_LIBRARY_NAME=nvidia

echo "1. Cleaning..."
pkill -9 -f "CityEnviron-Linux-Shipping" 2>/dev/null || true
pkill -9 -f "pas_follow|pas_voice" 2>/dev/null || true
tmux kill-session -t sim 2>/dev/null || true
while ss -tulpn 2>/dev/null | grep -q ":8989"; do
    sleep 1
done
sleep 2

echo "2. Starting CityEnviron..."
tmux new-session -d -s sim "DISPLAY=:0 XAUTHORITY=$XAUTH VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia $SIM_BIN -windowed -ResX=640 -ResY=360 -nosound -log"

echo "3. Waiting for port 8989..."
for i in $(seq 1 40); do
    if ss -tulpn 2>/dev/null | grep -q ":8989"; then
        echo "Port 8989 open after ${i}s. Waiting 28s for world load..."
        sleep 28
        echo "READY"
        exit 0
    fi
    sleep 1
done

echo "Failed to open port 8989"
exit 1
