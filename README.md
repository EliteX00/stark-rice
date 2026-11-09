# 🌌 Stark Rice & Zenify Music Player

> **Ultra-aesthetic Frosted Glass Hyprland Rice with Zenify: Apple Music & Spotify Hybrid Player featuring Synced Kinetic Typography Lyrics.**

---

## 🎧 Zenify: The Dual-Mode Music Experience

Zenify is a high-performance music player engineered with GTK3, Cairo, and MPV IPC, blending the minimalist luxury of **Apple Music** with the discovery power of **Spotify**.

### 🌟 Mode 1: Song Playing Window (Apple Music Showcase)
- **Kinetic Typography Edit Lyrics Canvas**: 60 FPS millisecond-accurate lyrics with word-by-word kinetic pops, tempo-reactive speed dynamics, chromatic impact aberration, and artwork ambient glow.
- **Dynamic Dual-Bloom Mesh Gradient**: Automatically samples the current song's album art and generates a lush, glowing radial gradient directly onto the frosted glass window.
- **Monochrome Minimalist Vector Controls**: Clean vector glyphs from `JetBrainsMono Nerd Font` (zero emojis).
- **Interactive Scrubber**: Sleek progress bar with elapsed and `-remaining` time, instant click-to-seek, and wheel scrubbing.

### 📚 Mode 2: Spotify Playlist & Search Browser
- **Live Debounced Search**: Instant YouTube & Spotify catalog query with 350ms debouncing.
- **Smart Recommendations Engine**: Collaborative filtering and curated daily mixes powered by Last.fm and YouTube Music streams.
- **Persistent Bottom Player Dock**: Mini artwork, title/artist ticker, playback controls, and volume slider accessible while browsing.

---

## 🖥️ Desktop Widgets & Features

- **Frosted Glass Desktop Cards**: Cairo-rendered translucent system monitor, AccuWeather card, and CAVA audio visualizer.
- **Circadian Theme Daemon (`stark_sunset.py`)**: Automatically shifts color warmth and wallpaper ambiance with sunrise and sunset.
- **Discord Rich Presence (`zenify_discord_rpc.py`)**: Real-time Discord presence showing current track, artist, album art, and timestamps.
- **Lightweight & Battery Efficient**: Under 2% CPU footprint on dual-core Intel Pentium CPUs.

---

## ⌨️ Shortcuts & Navigation

| Key | Action |
|---|---|
| `Tab` / `B` | Toggle between Mode 1 (Showcase) and Mode 2 (Browser) |
| `Space` | Play / Pause |
| `N` / `P` | Next / Previous track |
| `S` | Shuffle Queue |
| `L` | Toggle Favorite / Like |
| `M` / `F` | Toggle Window Mode |

---

## 🚀 Installation & Quick Start

### Prerequisites
- **OS**: Linux (Hyprland / Wayland or X11)
- **Packages**: `mpv`, `yt-dlp`, `cava`, `python3-gobject`, `gtk3`, `pango`, `cairo`
- **Fonts**: `Google Sans Flex` (or Inter / Adwaita Sans), `JetBrainsMono Nerd Font`

### Setup
```bash
git clone https://github.com/EliteX00/stark-rice.git
cd stark-rice
chmod +x install.sh
./install.sh
```

### Starting Zenify
```bash
python3 ~/.config/stark-rice/stark_spotify.py
```

### Launching Desktop Widgets
```bash
~/.config/stark-rice/launch.sh
```

---

## 🔐 Privacy & Configuration

- **Zero Hardcoded Secrets**: All authentication keys and personal tokens are read from environment variables or local `.json` files.
- **Custom Weather Location**: Copy `weather_config.json.example` to `weather_config.json` and enter your local AccuWeather location key.

---

## 📜 License
MIT License. Crafted with precision for peak aesthetic minimalism.
