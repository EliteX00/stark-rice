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

if [ ! -f "$CONFIG_HOME/stark-rice/jarvis_config.json" ]; then
    echo "==> Initializing jarvis_config.json from template..."
    cp "$CONFIG_HOME/stark-rice/jarvis_config.json.example" "$CONFIG_HOME/stark-rice/jarvis_config.json"
fi

echo "==> Installing global jarvis CLI command..."
mkdir -p "$HOME/.local/bin"
cat << 'EOF' > "$HOME/.local/bin/jarvis"
#!/usr/bin/env bash
DIR="${XDG_CONFIG_HOME:-$HOME/.config}/stark-rice"
if [ "$1" = "--toggle" ] || [ "$1" = "-t" ] || [ "$1" = "--hud" ]; then
    exec "$DIR/jarvis_launcher.sh"
fi
exec python3 "$DIR/jarvis_chat.py" "$@"
EOF
chmod +x "$HOME/.local/bin/jarvis"

echo "==> Setting executable permissions..."
chmod +x "$CONFIG_HOME/stark-rice/"*.sh || true
chmod +x "$CONFIG_HOME/stark-rice/"*.py || true

echo "==> Installation complete!"
echo "To start Zenify:"
echo "    python3 $CONFIG_HOME/stark-rice/stark_spotify.py"
echo "To launch desktop widgets:"
echo "    $CONFIG_HOME/stark-rice/launch.sh"
