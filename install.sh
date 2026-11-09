#!/usr/bin/env bash
# Stark Rice Installation & Setup Script
set -e

echo "=========================================="
echo "  Stark Rice & Zenify Installer"
echo "=========================================="

CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Deploying stark-rice configuration..."
mkdir -p "$CONFIG_HOME/stark-rice"
cp -rn "$SCRIPT_DIR/stark-rice/"* "$CONFIG_HOME/stark-rice/"

if [ ! -f "$CONFIG_HOME/stark-rice/weather_config.json" ]; then
    echo "==> Initializing weather_config.json from template..."
    cp "$CONFIG_HOME/stark-rice/weather_config.json.example" "$CONFIG_HOME/stark-rice/weather_config.json"
fi

echo "==> Setting executable permissions..."
chmod +x "$CONFIG_HOME/stark-rice/"*.sh || true
chmod +x "$CONFIG_HOME/stark-rice/"*.py || true

echo "==> Installation complete!"
echo "To start Zenify:"
echo "    python3 $CONFIG_HOME/stark-rice/stark_spotify.py"
echo "To launch desktop widgets:"
echo "    $CONFIG_HOME/stark-rice/launch.sh"
