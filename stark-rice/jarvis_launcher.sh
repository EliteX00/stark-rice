#!/usr/bin/env bash
# J.A.R.V.I.S. Floating HUD Toggle Launcher
# Toggles the Tony Stark Neural HUD Panel

DIR="/home/elitex/.config/stark-rice"

# 1. Check if jarvis_hud.py is already running
PIDS=$(pgrep -f "jarvis_hud.py")
if [ -n "$PIDS" ]; then
    for pid in $PIDS; do
        if [ "$pid" != "$$" ]; then
            kill -TERM "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null
        fi
    done
    exit 0
fi

# 2. Also check if a jarvis-hud window is in Hyprland
WIN_PID=$(hyprctl clients -j | jq -r '.[] | select(.class == "jarvis-hud" or .initialClass == "jarvis-hud") | .pid' 2>/dev/null | head -n 1)
if [ -n "$WIN_PID" ] && [ "$WIN_PID" != "null" ]; then
    kill -TERM "$WIN_PID" 2>/dev/null || kill -9 "$WIN_PID" 2>/dev/null
    exit 0
fi

# 3. Launch the high-tech floating J.A.R.V.I.S. HUD
exec python3 "$DIR/jarvis_hud.py"
