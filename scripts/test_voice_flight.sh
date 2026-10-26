#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

SIM_BIN="/home/balaraj/autonovaz/ProjectAirSim-Linux/CityEnviron/Binaries/Linux/CityEnviron-Linux-Shipping"
RECORD="${1:-voice_verified}"
DURATION="${2:-25}"

export DISPLAY=:0
XAUTH=$(ls -t /run/user/$(id -u)/.mutter-Xwaylandauth.* 2>/dev/null | head -1 || echo "$HOME/.Xauthority")
export XAUTHORITY="$XAUTH"
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json
export __NV_PRIME_RENDER_OFFLOAD=1
export __GLX_VENDOR_LIBRARY_NAME=nvidia

echo "1. Cleaning existing processes..."
pkill -9 -f "CityEnviron-Linux-Shipping" 2>/dev/null || true
pkill -9 -f "scripts/pas_follow.py" 2>/dev/null || true
pkill -9 -f "scripts/pas_voice_pilot.py" 2>/dev/null || true
tmux kill-session -t sim 2>/dev/null || true
while ss -tulpn 2>/dev/null | grep -q ":8989"; do
    sleep 1
done
sleep 2

echo "2. Starting CityEnviron..."
tmux new-session -d -s sim "DISPLAY=:0 XAUTHORITY=$XAUTH VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia $SIM_BIN -windowed -ResX=640 -ResY=360 -nosound -log"

cleanup() {
    echo "[cleanup] Shutting down simulator..."
    pkill -9 -f "CityEnviron-Linux-Shipping" 2>/dev/null || true
    tmux kill-session -t sim 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "3. Waiting for port 8989..."
PORT_OPEN=0
for i in $(seq 1 45); do
    if ss -tulpn 2>/dev/null | grep -q ":8989"; then
        echo "Port 8989 ready after ${i}s. Waiting 28s for world load..."
        sleep 28
        PORT_OPEN=1
        break
    fi
    sleep 1
done

if [ "$PORT_OPEN" -eq 0 ]; then
    echo "❌ Simulator failed to open port 8989 within 45s."
    exit 1
fi

rm -rf "logs/rec/$RECORD"
mkdir -p "logs/rec/$RECORD"

echo "4. Running pas_voice_pilot with automated takeoff + follow..."
./venv/bin/python scripts/pas_voice_pilot.py --commands "take off" "follow that man" --follow-duration "$DURATION" --record "$RECORD"
EXIT_CODE=$?

if [ -d "logs/rec/$RECORD/follow" ] && ls logs/rec/"$RECORD"/follow/f_*.jpg 1>/dev/null 2>&1; then
    echo "🎬 Compiling demonstration video..."
    ./venv/bin/python scripts/make_demo_video.py --session "$RECORD/follow" --fps 10 || true
elif [ -d "logs/rec/$RECORD" ] && ls logs/rec/"$RECORD"/f_*.jpg 1>/dev/null 2>&1; then
    echo "🎬 Compiling demonstration video..."
    ./venv/bin/python scripts/make_demo_video.py --session "$RECORD" --fps 10 || true
fi

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Voice pilot run completed successfully!"
else
    echo "❌ Voice pilot exited with code $EXIT_CODE"
fi

exit $EXIT_CODE
