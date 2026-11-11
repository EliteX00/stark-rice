#!/usr/bin/env bash
# J.A.R.V.I.S. Floating HUD Toggle Launcher

DIR="/home/elitex/.config/stark-rice"

# 1. Check if a jarvis-hud window is already open in Hyprland
WIN_PID=$(hyprctl clients -j | jq -r '.[] | select(.class == "jarvis-hud") | .pid' 2>/dev/null | head -n 1)

if [ -n "$WIN_PID" ] && [ "$WIN_PID" != "null" ]; then
    kill -TERM "$WIN_PID" 2>/dev/null || kill -9 "$WIN_PID" 2>/dev/null
    exit 0
fi

# 2. Also check if background instance is running via pgrep
EXISTING_PID=$(pgrep -f "kitty.*jarvis-hud" | head -n 1)
if [ -n "$EXISTING_PID" ]; then
    kill -TERM "$EXISTING_PID" 2>/dev/null || kill -9 "$EXISTING_PID" 2>/dev/null
    exit 0
fi

# 3. Launch floating J.A.R.V.I.S. HUD
exec kitty --class jarvis-hud \
           --title "J.A.R.V.I.S. Core Console" \
           -o background=#070b14 \
           -o background_opacity=0.92 \
           -o window_padding_width=18 \
           -o font_size=11.5 \
           -o cursor_shape=beam \
           python3 "$DIR/jarvis_chat.py"
