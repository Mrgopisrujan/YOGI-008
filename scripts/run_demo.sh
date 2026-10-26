#!/usr/bin/env bash
# run_demo.sh — Autonomous Flight, Tracking, and Demo Video Generation
# Usage: bash scripts/run_demo.sh [duration_sec] [session_name]
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

SIM_BIN="/home/balaraj/autonovaz/ProjectAirSim-Linux/CityEnviron/Binaries/Linux/CityEnviron-Linux-Shipping"
DURATION="${1:-45}"
RECORD="${2:-demo_final}"

export DISPLAY=:0
XAUTH=$(ls -t /run/user/$(id -u)/.mutter-Xwaylandauth.* 2>/dev/null | head -1 || echo "$HOME/.Xauthority")
export XAUTHORITY="$XAUTH"
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json
export __NV_PRIME_RENDER_OFFLOAD=1
export __GLX_VENDOR_LIBRARY_NAME=nvidia

echo "=========================================================="
echo "  🚁 GarudaOne DroneOS — Autonomous Simulation & Video"
echo "=========================================================="
echo "  Session  : $RECORD"
echo "  Duration : ${DURATION}s"
echo "  XAUTH    : $XAUTHORITY"
echo "=========================================================="

echo "[1/4] Cleaning up any old simulator or flight processes..."
pkill -9 -f "CityEnviron-Linux-Shipping" 2>/dev/null || true
pkill -9 -f "pas_follow|pas_voice|pas_interactive|test_walker|test_sim" 2>/dev/null || true
tmux kill-session -t sim 2>/dev/null || true
sleep 3

echo "[2/4] Starting CityEnviron simulator..."
tmux new-session -d -s sim "DISPLAY=:0 XAUTHORITY=$XAUTH VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia $SIM_BIN -windowed -ResX=640 -ResY=360 -nosound -log"

cleanup() {
    echo "[cleanup] Shutting down simulator..."
    pkill -9 -f "CityEnviron-Linux-Shipping" 2>/dev/null || true
    tmux kill-session -t sim 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[3/4] Waiting for simulation ports (8989/8990) to open..."
PORT_OPEN=0
for i in $(seq 1 30); do
    if ss -tulpn 2>/dev/null | grep -q ':8989'; then
        echo "      Port 8989 open after ${i}s. Waiting 25s for world init..."
        sleep 25
        PORT_OPEN=1
        break
    fi
    sleep 1
done

if [ "$PORT_OPEN" -eq 0 ]; then
    echo "❌ Simulator failed to open port 8989 within 30s."
    exit 1
fi

rm -rf "logs/rec/$RECORD"
mkdir -p "logs/rec/$RECORD"

echo "[4/4] Executing autonomous follow flight: pas_follow.py..."
./venv/bin/python scripts/pas_follow.py --duration "$DURATION" --record "$RECORD"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "=========================================================="
    echo "  🎬 Assembling output MP4 demo video from frames..."
    echo "=========================================================="
    ./venv/bin/python scripts/make_demo_video.py --session "$RECORD" --fps 10
    echo ""
    echo "✅ Demo run completed successfully!"
    echo "   Telemetry: logs/rec/$RECORD/follow_telemetry.csv"
    echo "   Video    : logs/rec/$RECORD/demo.mp4"
    echo "=========================================================="
else
    echo "❌ Flight script exited with error code $EXIT_CODE"
fi

exit $EXIT_CODE
