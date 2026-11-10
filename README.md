# Stark Rice

A frosted-glass Hyprland desktop setup with **Zenify**, a dual-mode music player featuring synchronized, animated lyrics. Stark Rice combines Hyprland configuration and desktop widgets with a GTK music interface for browsing and playing music.

> **Platform:** Linux with Hyprland and a Wayland session. This project is tailored to its author's setup; review the paths and commands before using it on your machine.

## Features

- Frosted-glass Zenify player with a now-playing view and playlist/search browser.
- Synchronized lyrics with animated kinetic typography, seeking, and adjustable lyric timing.
- Playback controls, listening history, recommendations, and optional autoplay.
- Desktop widgets and supporting services, including wallpaper, Waybar, weather, audio visualization, and Discord Rich Presence components.
- Hyprland configuration with custom keybindings and startup integration.

## Repository layout

```text
.
├── hypr/                 # Hyprland Lua configuration and custom overrides
├── stark-rice/           # Zenify player, widgets, services, styles, and assets
└── install.sh            # Copies the Stark Rice application files into your config directory
```

The installer deploys the contents of `stark-rice/` to `~/.config/stark-rice` (or `$XDG_CONFIG_HOME/stark-rice`). It does **not** install system dependencies or deploy the `hypr/` configuration. Review and integrate those files with your existing Hyprland setup manually.

## Requirements

Install the components your chosen features need using your distribution's package manager. The project uses:

- Hyprland and a Wayland desktop session.
- Python 3 and GTK 3 introspection (PyGObject), Cairo/Pango, and Pillow.
- `mpv` and `yt-dlp` for audio playback and media lookup.
- `waybar`, `swaybg`, and `cava` for the related desktop services/widgets.
- Python packages imported by the player and services, including `requests` and `ytmusicapi`.
- Nerd Font glyph support for the UI icons; JetBrainsMono Nerd Font is referenced by the player.

Some integrations are optional and may need credentials/configuration, such as Spotify, Last.fm, YouTube Music, weather, and Discord Rich Presence. Check the relevant service scripts for exact setup details. The weather service includes `weather_config.json.example` as a starting template.

## Installation

1. Clone the repository and inspect the scripts and configuration before running them:

   ```bash
   git clone https://github.com/EliteX00/stark-rice.git
   cd stark-rice
   ```

2. Install the system and Python dependencies listed above.

3. Run the installer:

   ```bash
   ./install.sh
   ```

   The script copies application files without overwriting existing files and initializes `weather_config.json` from the example if needed.

4. **Review `~/.config/stark-rice/launch.sh` before launching it.** The current script includes `/home/elitex/...` paths; change these to match your installation (or otherwise adapt the script) before use.

5. Configure and merge the files under `hypr/` into your Hyprland setup as appropriate. Back up your current configuration first; do not replace a working setup blindly.

6. Start Zenify:

   ```bash
   python3 ~/.config/stark-rice/stark_spotify.py
   ```

   To launch the desktop widgets and related services after adapting `launch.sh`:

   ```bash
   ~/.config/stark-rice/launch.sh
   ```

## Zenify controls

- **Space:** play/pause.
- **Left / Right arrows:** seek backward/forward by five seconds.
- **Tab** or **B:** switch between player and browser views.
- **Escape:** return from browser to player, or hide the player.
- **`[` / `]`:** adjust lyric timing by 0.5 seconds.
- **`{` / `}`:** adjust lyric timing by 0.1 seconds.
- **`0`:** reset lyric timing.

The custom Hyprland keybindings also include **Super+P** to toggle Zenify and **Ctrl+Super+B** to restart the Stark UI services, once the configuration has been integrated and paths verified.

## Configuration and data

Application configuration and runtime data are stored under `~/.config/stark-rice` (or the configured XDG config directory where supported). This includes playback state, listening history, cached artwork, and optional authentication/configuration files. Keep credentials private and do not commit personal tokens or generated auth files.

For weather setup, copy/edit `weather_config.json.example` as `weather_config.json` and fill in the provider and location/API details required by the weather service.

## Troubleshooting

- If the UI does not start, verify GTK 3, PyGObject, Cairo/Pango, and Python dependencies are installed.
- If playback does not start, check that `mpv` and `yt-dlp` are installed and usable from your shell.
- If widgets or wallpaper fail to launch, check the executable paths in `launch.sh`; they are currently hardcoded to `/home/elitex/...` in parts of the script.
- If Hyprland keybindings do not work, verify that the custom Lua files are loaded by your existing configuration and that the referenced commands resolve on your system.

## License

No license file is currently included. Unless the repository adds a license, all rights remain with the author and reuse or redistribution is not granted by default.
