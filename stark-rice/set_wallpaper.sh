#!/usr/bin/env bash
# Stark Rice Wallpaper Setter

DEFAULT_WALLPAPER="/home/elitex/.config/stark-rice/wallpaper.png"
IMG="${1:-$DEFAULT_WALLPAPER}"

if [ ! -f "$IMG" ]; then
    echo "Error: File '$IMG' not found."
    exit 1
fi

# If a new image was passed, update the default wallpaper symlink/file
if [ "$IMG" != "$DEFAULT_WALLPAPER" ]; then
    cp "$IMG" "$DEFAULT_WALLPAPER"
fi

# Restart swaybg cleanly
pkill -x swaybg 2>/dev/null || true
sleep 0.2
nohup /home/elitex/.local/bin/swaybg -i "$DEFAULT_WALLPAPER" -m fill >/dev/null 2>&1 &
disown 2>/dev/null || true

echo "Wallpaper updated to: $IMG"
