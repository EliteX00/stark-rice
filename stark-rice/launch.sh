#!/usr/bin/env bash
# Stark Rice Unified Background Service Launcher

DIR="/home/elitex/.config/stark-rice"

# Clean up any old instances
killall -9 waybar.real waybar 2>/dev/null || true
pkill -9 -f "stark_widgets.py" 2>/dev/null || true
pkill -9 -f "cava_widget.conf" 2>/dev/null || true
pkill -9 -f "zenify_discord_rpc.py" 2>/dev/null || true
sleep 0.5

# 1. Wallpaper
if ! pgrep -f "swaybg" > /dev/null; then
    setsid /home/elitex/.local/bin/swaybg -i "$DIR/wallpaper.png" -m fill > /dev/null 2>&1 &
fi

# 2. Waybar
setsid /home/elitex/.local/bin/waybar > /dev/null 2>&1 &

# 3. Stark Desktop Widgets (Clock, Sysmon, Zenify Music Card, Quote)
setsid python3 "$DIR/stark_widgets.py" > /dev/null 2>&1 &

# 4. Blue light filter daemon
setsid python3 "$DIR/stark_sunset.py" --daemon > /dev/null 2>&1 &

# 5. Zenify Discord Rich Presence daemon
setsid python3 "$DIR/zenify_discord_rpc.py" > /dev/null 2>&1 &

# 6. J.A.R.V.I.S. System Voice Greeting (if enabled in jarvis_config.json)
if [ -f "$DIR/jarvis_config.json" ]; then
    BOOT_GREETING=$(jq -r '.boot_greeting // true' "$DIR/jarvis_config.json" 2>/dev/null)
    if [ "$BOOT_GREETING" = "true" ]; then
        nohup python3 "$DIR/jarvis_chat.py" --boot > /dev/null 2>&1 &
    fi
fi

sleep 0.5
echo "All Stark Rice and Zenify services restarted."
