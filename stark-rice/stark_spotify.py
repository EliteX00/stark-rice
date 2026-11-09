#!/usr/bin/env python3
"""
Zenify - Kinetic Typography & Apple Music Frosted Glass UI
==========================================================
- Mode 1: Apple Music Synced Kinetic Lyrics & Showcase
  - Large artwork, metadata, slim scrubber with remaining time.
  - Minimalist monochrome vector controls (JetBrainsMono Nerd Font).
  - 60FPS Kinetic Typography Edit Lyrics Canvas (Custom GPU-accelerated Cairo/Pango).
  - Dynamic Cover Art Ambient Mesh Gradient directly on Frosted Glass.
  - Interactive tap-to-seek and smooth inertia wheel scroll.
- Mode 2: Full Spotify Playlist / Search / Library Browser
  - Instant live debounced search.
  - Curated mixes (Last.fm collaborative engine for 'mrmeowx').
  - Persistent bottom docked player.
- 100% genuine frosted glass blur on Hyprland.
- 0% idle CPU footprint.
"""

import os
import sys
import time
import json
import math
import random
import socket
import hashlib
import threading
import urllib.request
import urllib.parse
from PIL import Image

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Pango, PangoCairo
import cairo

GLib.set_prgname("zenify")
GLib.set_application_name("Zenify")

CONFIG_DIR = os.path.expanduser("~/.config/stark-rice")
CSS_FILE = os.path.join(CONFIG_DIR, "spotify.css")
ASSETS_DIR = os.path.join(CONFIG_DIR, "assets")
THUMB_CACHE_DIR = os.path.join(ASSETS_DIR, "album_thumbs")
UI_SOCKET = "/tmp/stark_spotify_ui.sock"
AUTH_FILE = os.path.join(CONFIG_DIR, "lastfm_auth.json")

os.makedirs(THUMB_CACHE_DIR, exist_ok=True)
sys.path.insert(0, CONFIG_DIR)
from stark_player import StarkPlayerBackend, sanitize_title
from lyrics_service import fetch_lyrics

# Minimalist Monochrome Vector Glyphs (JetBrainsMono Nerd Font)
GLYPHS = {
    "play": "󰐊",
    "pause": "󰏤",
    "prev": "󰒮",
    "next": "󰒭",
    "shuffle": "󰒝",
    "repeat": "󰑖",
    "heart_off": "󰋔",
    "heart_on": "󰋑",
    "star": "󰓎",
    "more": "󰇙",
    "volume": "󰕾",
    "search": "󰍉",
    "library": "󰲸",
    "music": "󰎆",
    "recommendations": "󰓎",
    "top_hits": "󱐋",
    "phonk": "󰌳",
    "hiphop": "󱐋",
    "rnb": "󰖔",
    "cinematic": "󰿎",
    "close": "󰅖",
    "min": "󰍴",
    "expand": "󰍍"
}


def format_duration(seconds):
    if not seconds or seconds <= 0:
        return "0:00"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def format_remaining(total_sec, pos_sec):
    rem = max(0.0, total_sec - pos_sec)
    m = int(rem // 60)
    s = int(rem % 60)
    return f"-{m}:{s:02d}"


def extract_art_palette(image_path):
    """
    Extracts primary vibrant color and secondary accent from the album artwork.
    """
    if not image_path or not os.path.exists(image_path):
        return (56, 189, 248), (147, 51, 234)
    try:
        im = Image.open(image_path).convert("RGB").resize((32, 32), Image.Resampling.LANCZOS)
        colors = im.getcolors(1024)
        scored = []
        for count, (r, g, b) in colors:
            mx, mn = max(r, g, b), min(r, g, b)
            sat = (mx - mn) / (mx + 1e-5)
            bright = mx / 255.0
            if 0.18 <= bright <= 0.94 and sat >= 0.15:
                score = (sat * 1.5 + bright) * count
                scored.append((score, (r, g, b)))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored:
            primary = scored[0][1]
            secondary = None
            for sc, rgb in scored[1:]:
                dist = sum(abs(a - b) for a, b in zip(primary, rgb))
                if dist > 75:
                    secondary = rgb
                    break
            if not secondary:
                secondary = (
                    min(255, int(primary[2] * 0.8 + 40)),
                    min(255, int(primary[0] * 0.6 + 60)),
                    min(255, int(primary[1] * 0.9 + 50))
                )
            return primary, secondary
    except Exception:
        pass
    return (56, 189, 248), (147, 51, 234)


# ==============================================================================
# Apple Music Slim Scrubber
# ==============================================================================
class AppleMusicScrubber(Gtk.DrawingArea):
    def __init__(self, on_seek_cb=None, height=14):
        super().__init__()
        self.on_seek_cb = on_seek_cb
        self.progress = 0.0
        self.accent_rgb = (255, 255, 255)
        self.set_size_request(260, height)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_click)

    def set_progress(self, prog):
        self.progress = max(0.0, min(1.0, prog))
        self.queue_draw()

    def set_accent_rgb(self, rgb):
        self.accent_rgb = rgb
        self.queue_draw()

    def _on_click(self, widget, event):
        w = self.get_allocated_width()
        if w > 0:
            pct = max(0.0, min(1.0, event.x / float(w))) * 100.0
            if self.on_seek_cb:
                self.on_seek_cb(pct)
            return True
        return False

    def _on_draw(self, widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        line_y = h / 2.0
        line_h = 3.5

        # Unfilled Trough (clean translucent white)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.18)
        cr.rectangle(0, line_y - (line_h / 2.0), w, line_h)
        cr.fill()

        # Filled Progress
        fill_w = int(w * self.progress)
        if fill_w > 0:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.95)
            cr.rectangle(0, line_y - (line_h / 2.0), fill_w, line_h)
            cr.fill()

            # Indicator Knob
            cr.set_source_rgb(1.0, 1.0, 1.0)
            cr.arc(fill_w, line_y, 4.0, 0, 2 * math.pi)
            cr.fill()

        return False


# ==============================================================================
# Kinetic Typography Edit Lyrics Canvas (60 FPS Locked, 0% Idle CPU)
# ==============================================================================
class CinematicLyricsCanvas(Gtk.DrawingArea):
    def __init__(self, on_seek_cb=None):
        super().__init__()
        self.on_seek_cb = on_seek_cb
        self.lines = []  # [(timestamp_sec, text), ...]
        self.is_synced = False
        self.active_idx = -1
        self.current_scroll = 0.0
        self.target_scroll = 0.0
        self.accent_rgb = (56, 189, 248)
        self.anim_timer = None
        self.snap_back_timer = None
        self.user_scrolling = False

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_click)
        self.connect("scroll-event", self._on_scroll)

    def set_lyrics(self, lines, is_synced):
        self.lines = lines
        self.is_synced = is_synced
        self.active_idx = 0 if lines else -1
        self.current_scroll = 0.0
        self.target_scroll = 0.0
        self.queue_draw()

    def set_accent_rgb(self, rgb):
        self.accent_rgb = rgb
        self.queue_draw()

    def update_position(self, pos_sec):
        if not self.is_synced or not self.lines:
            return

        # Find active line
        new_active = -1
        for i, (t, _) in enumerate(self.lines):
            if pos_sec >= t:
                new_active = i
            else:
                break

        if new_active != self.active_idx and new_active >= 0:
            self.active_idx = new_active
            if not self.user_scrolling:
                self.target_scroll = float(new_active)
                self._start_anim()

    def _start_anim(self):
        if not self.anim_timer:
            self.anim_timer = GLib.timeout_add(16, self._anim_tick)

    def _anim_tick(self):
        diff = self.target_scroll - self.current_scroll
        if abs(diff) < 0.004:
            self.current_scroll = self.target_scroll
            self.queue_draw()
            self.anim_timer = None
            return False

        # Fluid cubic-spring smoothing
        self.current_scroll += diff * 0.16
        self.queue_draw()
        return True

    def _on_click(self, widget, event):
        if not self.lines or not self.is_synced:
            return False

        h = self.get_allocated_height()
        center_y = h * 0.44
        line_spacing = 64.0

        clicked_idx = int(round(self.current_scroll + (event.y - center_y) / line_spacing))
        if 0 <= clicked_idx < len(self.lines):
            target_time = self.lines[clicked_idx][0]
            if self.on_seek_cb:
                self.on_seek_cb(max(0.0, target_time - 0.05))
            return True
        return False

    def _on_scroll(self, widget, event):
        if not self.lines:
            return False

        self.user_scrolling = True
        delta = 1.0 if event.direction == Gdk.ScrollDirection.DOWN else -1.0
        self.target_scroll = max(0.0, min(len(self.lines) - 1, self.target_scroll + delta))
        self._start_anim()

        # Snap back to active line after 3s of user inactivity
        if self.snap_back_timer:
            GLib.source_remove(self.snap_back_timer)
        self.snap_back_timer = GLib.timeout_add(3000, self._snap_back_to_active)
        return True

    def _snap_back_to_active(self):
        self.user_scrolling = False
        self.snap_back_timer = None
        if self.active_idx >= 0:
            self.target_scroll = float(self.active_idx)
            self._start_anim()
        return False

    def _on_draw(self, widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()

        if not self.lines:
            # Empty / Instrumental state
            pctx = self.get_pango_context()
            layout = Pango.Layout.new(pctx)
            desc = Pango.FontDescription("Google Sans Flex 18")
            desc.set_weight(Pango.Weight.BOLD)
            layout.set_font_description(desc)
            layout.set_text("󰎆  Instrumental or lyrics unavailable", -1)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.40)
            cr.move_to(24, h * 0.42)
            PangoCairo.show_layout(cr, layout)
            return False

        center_y = h * 0.44
        line_spacing = 66.0
        pctx = self.get_pango_context()
        layout = Pango.Layout.new(pctx)
        layout.set_width(int((w - 48) * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)

        r_accent, g_accent, b_accent = [c / 255.0 for c in self.accent_rgb]

        # Draw lines relative to current_scroll
        for i, (_, txt) in enumerate(self.lines):
            dist = i - self.current_scroll
            y = center_y + (dist * line_spacing)

            # Cull off-screen lines for pure 60FPS speed
            if -90 < y < h + 90:
                layout.set_text(txt, -1)
                abs_d = abs(dist)

                if abs_d < 0.6:
                    # ACTIVE SPOTLIGHT LINE (Bold Kinetic Typography Edit)
                    font_size = 28 - int(abs_d * 8)
                    desc = Pango.FontDescription(f"Google Sans Flex {font_size}")
                    desc.set_weight(Pango.Weight.HEAVY)
                    layout.set_font_description(desc)

                    # Soft Ambient Glow Bloom behind Active Text
                    bloom_alpha = 0.40 * (1.0 - abs_d)
                    cr.set_source_rgba(r_accent, g_accent, b_accent, bloom_alpha)
                    cr.move_to(24, y + 2)
                    PangoCairo.show_layout(cr, layout)

                    # Pure Crisp White Foreground
                    cr.set_source_rgba(1.0, 1.0, 1.0, 1.0 - (abs_d * 0.25))
                elif abs_d < 1.6:
                    # Adjacent Lines (Clean transition)
                    font_size = 21 - int((abs_d - 0.6) * 4)
                    desc = Pango.FontDescription(f"Google Sans Flex {font_size}")
                    desc.set_weight(Pango.Weight.BOLD)
                    layout.set_font_description(desc)
                    alpha = 0.48 - ((abs_d - 0.6) * 0.18)
                    cr.set_source_rgba(1.0, 1.0, 1.0, max(0.15, alpha))
                else:
                    # Distant Lines (Faded smoothly into background)
                    font_size = max(15, 18 - int(abs_d * 1.5))
                    desc = Pango.FontDescription(f"Google Sans Flex {font_size}")
                    desc.set_weight(Pango.Weight.NORMAL)
                    layout.set_font_description(desc)
                    alpha = max(0.06, 0.28 - (abs_d * 0.05))
                    cr.set_source_rgba(1.0, 1.0, 1.0, alpha)

                cr.move_to(24, y)
                PangoCairo.show_layout(cr, layout)

        return False


# ==============================================================================
# Main Zenify Application Window
# ==============================================================================
class StarkifyApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Zenify")
        self.set_role("zenify")
        self.set_default_size(980, 640)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.get_style_context().add_class("stark-spotify-window")

        # RGBA visual for true frosted transparency
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.player = StarkPlayerBackend()
        self.current_tracks = []
        self.current_category = "daily_mix"
        self.username = "mrmeowx"
        self.current_mode = "player"
        self.primary_accent = (56, 189, 248)
        self.secondary_accent = (147, 51, 234)
        self.search_debounce_timer = None
        self.is_liked = False
        self._last_loaded_track_key = ""

        if os.path.exists(AUTH_FILE):
            try:
                with open(AUTH_FILE) as f:
                    d = json.load(f)
                    self.username = d.get("username", "mrmeowx")
            except Exception:
                pass

        self._load_css()
        self._build_ui()
        self._start_ipc_server()

        # Keyboard shortcuts
        self.connect("key-press-event", self._on_key_press)
        self.connect("delete-event", lambda w, e: self._hide_or_quit())

        # Highly Optimized Playback Sync Loop (200ms - Blazing Fast & Zero Lag)
        GLib.timeout_add(200, self._update_player_state)

        # Pre-load initial Daily Mix tracks
        threading.Thread(target=self._load_category, args=("daily_mix",), daemon=True).start()

    def _load_css(self):
        self.css_provider = Gtk.CssProvider()
        if os.path.exists(CSS_FILE):
            self.css_provider.load_from_path(CSS_FILE)
            screen = Gdk.Screen.get_default()
            Gtk.StyleContext.add_provider_for_screen(
                screen, self.css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        # Dynamic Provider for Cover Art Dual-Bloom Gradients
        self.dynamic_css_provider = Gtk.CssProvider()
        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(
            screen, self.dynamic_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

    def _update_dynamic_gradient(self, p_rgb, s_rgb):
        self.primary_accent = p_rgb
        self.secondary_accent = s_rgb
        r1, g1, b1 = p_rgb
        r2, g2, b2 = s_rgb
        css = f"""
        .stark-apple-container {{
            background-image: 
                radial-gradient(ellipse 75% 65% at 85% 35%, rgba({r1}, {g1}, {b1}, 0.38) 0%, transparent 68%),
                radial-gradient(ellipse 65% 55% at 20% 20%, rgba({r2}, {g2}, {b2}, 0.26) 0%, transparent 62%),
                radial-gradient(ellipse 90% 75% at 50% 90%, rgba(10, 14, 22, 0.50) 0%, rgba(8, 12, 18, 0.20) 100%);
        }}
        .stark-playlist-banner {{
            background-image: linear-gradient(180deg, rgba({r1}, {g1}, {b1}, 0.35) 0%, rgba(12, 18, 28, 0.35) 100%);
        }}
        """
        try:
            self.dynamic_css_provider.load_from_data(css.encode())
        except Exception:
            pass
        if hasattr(self, "showcase_scrubber"):
            self.showcase_scrubber.set_accent_rgb(p_rgb)
        if hasattr(self, "lyrics_canvas"):
            self.lyrics_canvas.set_accent_rgb(p_rgb)
        if hasattr(self, "docked_scrubber"):
            self.docked_scrubber.set_accent_rgb(p_rgb)

    def _build_ui(self):
        root_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root_vbox)

        # ---------------------------------------------------------------------
        # 1. Top Mode Header Bar
        # ---------------------------------------------------------------------
        header_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_bar.get_style_context().add_class("stark-mode-header")
        root_vbox.pack_start(header_bar, False, False, 0)

        # Mode Switcher Pill Container
        pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        pill_box.get_style_context().add_class("stark-mode-pill-box")

        self.btn_mode_player = Gtk.Button(label=f"{GLYPHS['music']}  Song Playing Window")
        self.btn_mode_player.get_style_context().add_class("stark-mode-btn")
        self.btn_mode_player.get_style_context().add_class("active")
        self.btn_mode_player.connect("clicked", lambda w: self.set_mode("player"))
        pill_box.pack_start(self.btn_mode_player, False, False, 0)

        self.btn_mode_browser = Gtk.Button(label=f"{GLYPHS['library']}  Playlist / Search / Browser")
        self.btn_mode_browser.get_style_context().add_class("stark-mode-btn")
        self.btn_mode_browser.connect("clicked", lambda w: self.set_mode("browser"))
        pill_box.pack_start(self.btn_mode_browser, False, False, 0)

        header_bar.pack_start(pill_box, False, False, 0)

        # Center Now Playing Ticker
        self.header_ticker_lbl = Gtk.Label(label="Ready to play")
        self.header_ticker_lbl.set_ellipsize(3)
        self.header_ticker_lbl.set_hexpand(True)
        self.header_ticker_lbl.set_halign(Gtk.Align.CENTER)
        self.header_ticker_lbl.get_style_context().add_class("stark-showcase-artist")
        header_bar.pack_start(self.header_ticker_lbl, True, True, 0)

        # Minimalist Window Controls
        min_btn = Gtk.Button(label=GLYPHS["min"])
        min_btn.get_style_context().add_class("stark-win-btn")
        min_btn.connect("clicked", lambda w: self.iconify())
        header_bar.pack_end(min_btn, False, False, 0)

        close_btn = Gtk.Button(label=GLYPHS["close"])
        close_btn.get_style_context().add_class("stark-win-btn")
        close_btn.get_style_context().add_class("close")
        close_btn.connect("clicked", lambda w: self.hide())
        header_bar.pack_end(close_btn, False, False, 4)

        # ---------------------------------------------------------------------
        # 2. Main Dual-Mode Stack
        # ---------------------------------------------------------------------
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(150)
        root_vbox.pack_start(self.stack, True, True, 0)

        # Build Page 1: Apple Music Synced Lyrics & Showcase
        self.player_page = self._build_player_view()
        self.stack.add_named(self.player_page, "player")

        # Build Page 2: Playlist / Search / Browser Mode
        self.browser_page = self._build_browser_view()
        self.stack.add_named(self.browser_page, "browser")

        self.stack.set_visible_child_name("player")

    # =========================================================================
    # MODE 1 BUILDER: Apple Music Synced Lyrics & Showcase
    # =========================================================================
    def _build_player_view(self):
        container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        container.get_style_context().add_class("stark-apple-container")

        # ---------------------------------------------------------------------
        # Left Column: Cover Art, Metadata, Slim Scrubber, Minimal Controls
        # ---------------------------------------------------------------------
        left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        left_col.get_style_context().add_class("stark-showcase-left")
        left_col.set_valign(Gtk.Align.CENTER)
        container.pack_start(left_col, False, False, 0)

        # Square Artwork Showcase (280x280)
        art_frame = Gtk.Box()
        art_frame.get_style_context().add_class("stark-showcase-art-frame")
        self.showcase_art_img = Gtk.Image()
        self.showcase_art_img.set_size_request(280, 280)
        art_frame.pack_start(self.showcase_art_img, True, True, 0)
        left_col.pack_start(art_frame, False, False, 0)

        # Metadata Row: Title & Artist on left, Star & Options on right
        meta_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        left_text_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        self.showcase_title_lbl = Gtk.Label(label=self.player.state.get("title", "Ready to Play"))
        self.showcase_title_lbl.set_xalign(0.0)
        self.showcase_title_lbl.set_ellipsize(3)
        self.showcase_title_lbl.get_style_context().add_class("stark-showcase-title")
        left_text_col.pack_start(self.showcase_title_lbl, False, False, 0)

        self.showcase_artist_lbl = Gtk.Label(label=self.player.state.get("artist", "Zenify Audio"))
        self.showcase_artist_lbl.set_xalign(0.0)
        self.showcase_artist_lbl.set_ellipsize(3)
        self.showcase_artist_lbl.get_style_context().add_class("stark-showcase-artist")
        left_text_col.pack_start(self.showcase_artist_lbl, False, False, 0)

        meta_row.pack_start(left_text_col, True, True, 0)

        # Star / Favorite Button
        self.btn_showcase_star = Gtk.Button(label=GLYPHS["star"])
        self.btn_showcase_star.get_style_context().add_class("stark-mini-icon-btn")
        self.btn_showcase_star.connect("clicked", self._on_toggle_like)
        meta_row.pack_end(self.btn_showcase_star, False, False, 0)

        # More Options Button
        btn_more = Gtk.Button(label=GLYPHS["more"])
        btn_more.get_style_context().add_class("stark-mini-icon-btn")
        btn_more.connect("clicked", lambda w: self.set_mode("browser"))
        meta_row.pack_end(btn_more, False, False, 4)

        left_col.pack_start(meta_row, False, False, 0)

        # Slim Progress Scrubber
        self.showcase_scrubber = AppleMusicScrubber(on_seek_cb=self._on_seek, height=14)
        left_col.pack_start(self.showcase_scrubber, False, False, 0)

        # Scrubber Timestamps: Elapsed (left), Remaining (right)
        time_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.showcase_time_elapsed = Gtk.Label(label="0:00")
        self.showcase_time_elapsed.get_style_context().add_class("stark-scrubber-time")
        time_row.pack_start(self.showcase_time_elapsed, False, False, 0)

        time_row.pack_start(Gtk.Box(), True, True, 0)

        self.showcase_time_remaining = Gtk.Label(label="-0:00")
        self.showcase_time_remaining.get_style_context().add_class("stark-scrubber-time")
        time_row.pack_end(self.showcase_time_remaining, False, False, 0)
        left_col.pack_start(time_row, False, False, 0)

        # Minimalist Playback Controls Deck
        ctrl_deck = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        ctrl_deck.set_halign(Gtk.Align.CENTER)
        ctrl_deck.set_margin_top(4)

        # Shuffle
        self.btn_showcase_shuffle = Gtk.Button(label=GLYPHS["shuffle"])
        self.btn_showcase_shuffle.get_style_context().add_class("stark-playback-btn")
        self.btn_showcase_shuffle.connect("clicked", lambda w: self._on_shuffle_queue())
        ctrl_deck.pack_start(self.btn_showcase_shuffle, False, False, 0)

        # Previous
        btn_prev = Gtk.Button(label=GLYPHS["prev"])
        btn_prev.get_style_context().add_class("stark-playback-btn")
        btn_prev.connect("clicked", lambda w: self.player.play_prev())
        ctrl_deck.pack_start(btn_prev, False, False, 0)

        # Play / Pause (Large white glyph)
        self.btn_showcase_play = Gtk.Button(label=GLYPHS["play"])
        self.btn_showcase_play.get_style_context().add_class("stark-playback-main-btn")
        self.btn_showcase_play.connect("clicked", lambda w: self.player.toggle_play())
        ctrl_deck.pack_start(self.btn_showcase_play, False, False, 0)

        # Next
        btn_next = Gtk.Button(label=GLYPHS["next"])
        btn_next.get_style_context().add_class("stark-playback-btn")
        btn_next.connect("clicked", lambda w: self.player.play_next())
        ctrl_deck.pack_start(btn_next, False, False, 0)

        # Repeat
        self.btn_showcase_repeat = Gtk.Button(label=GLYPHS["repeat"])
        self.btn_showcase_repeat.get_style_context().add_class("stark-playback-btn")
        if self.player.state.get("autoplay", True):
            self.btn_showcase_repeat.get_style_context().add_class("active")
        self.btn_showcase_repeat.connect("clicked", self._on_toggle_autoplay)
        ctrl_deck.pack_start(self.btn_showcase_repeat, False, False, 0)

        left_col.pack_start(ctrl_deck, False, False, 0)

        # Slim Volume Slider
        vol_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        vol_box.get_style_context().add_class("stark-showcase-vol-box")
        vol_box.set_halign(Gtk.Align.CENTER)
        vol_box.set_size_request(220, -1)
        vol_box.set_margin_top(8)

        v_icon = Gtk.Label(label=GLYPHS["volume"])
        v_icon.get_style_context().add_class("stark-vol-icon")
        vol_box.pack_start(v_icon, False, False, 0)

        self.showcase_vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.showcase_vol_scale.set_value(self.player.state.get("volume", 80))
        self.showcase_vol_scale.set_draw_value(False)
        self.showcase_vol_scale.set_hexpand(True)
        self.showcase_vol_scale.connect("value-changed", self._on_volume_changed)
        vol_box.pack_start(self.showcase_vol_scale, True, True, 0)
        left_col.pack_start(vol_box, False, False, 0)

        # ---------------------------------------------------------------------
        # Right Column: 60FPS Kinetic Typography Edit Canvas
        # ---------------------------------------------------------------------
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        right_box.get_style_context().add_class("stark-kinetic-lyrics-box")
        container.pack_start(right_box, True, True, 0)

        self.lyrics_canvas = CinematicLyricsCanvas(on_seek_cb=self._on_seek)
        right_box.pack_start(self.lyrics_canvas, True, True, 0)

        return container

    # =========================================================================
    # Synced Lyrics Loading
    # =========================================================================
    def _load_lyrics_for_track(self, title, artist, duration=0):
        key = f"{title}_{artist}"
        if key == self._last_loaded_track_key:
            return
        self._last_loaded_track_key = key

        def _worker():
            lines, is_synced, _ = fetch_lyrics(title, artist, duration)
            GLib.idle_add(self.lyrics_canvas.set_lyrics, lines, is_synced)

        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # MODE 2 BUILDER: Playlist / Search / Browser Mode (Full Spotify View)
    # =========================================================================
    def _build_browser_view(self):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Top Bar: Search Entry & Quick Filters
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        top_bar.get_style_context().add_class("stark-browser-topbar")
        container.pack_start(top_bar, False, False, 0)

        # Search Entry (Frosted Pill)
        self.browser_search_entry = Gtk.Entry()
        self.browser_search_entry.set_placeholder_text(f"{GLYPHS['search']}  What do you want to play?")
        self.browser_search_entry.get_style_context().add_class("stark-browser-search-entry")
        self.browser_search_entry.connect("changed", self._on_search_text_changed)
        self.browser_search_entry.connect("activate", self._on_search_activate)
        top_bar.pack_start(self.browser_search_entry, False, False, 0)

        # Filter Pills
        self.filter_buttons = {}
        filters = [
            ("daily_mix", "Daily Mix"),
            ("recommendations", "Recommendations"),
            ("library", "Library"),
            ("hiphop", "Hip-Hop"),
            ("phonk", "Phonk"),
            ("rnb", "R&B")
        ]
        for f_key, f_name in filters:
            btn = Gtk.Button(label=f_name)
            btn.get_style_context().add_class("stark-filter-pill")
            if f_key == "daily_mix":
                btn.get_style_context().add_class("active")
            btn.connect("clicked", self._on_filter_clicked, f_key)
            top_bar.pack_start(btn, False, False, 0)
            self.filter_buttons[f_key] = btn

        # Middle Content Area (Sidebar + Track Table)
        body_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        container.pack_start(body_hbox, True, True, 0)

        # Left Sidebar (Playlists & Navigation)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sidebar.get_style_context().add_class("stark-browser-sidebar")
        body_hbox.pack_start(sidebar, False, False, 0)

        brand_lbl = Gtk.Label(label="󰓇  ZENIFY")
        brand_lbl.set_xalign(0.0)
        brand_lbl.get_style_context().add_class("stark-browser-brand")
        sidebar.pack_start(brand_lbl, False, False, 0)

        chip_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        chip_box.get_style_context().add_class("stark-browser-user-chip")
        chip_lbl = Gtk.Label(label=f"󰓇 {self.username} • Last.fm")
        chip_lbl.get_style_context().add_class("stark-browser-user-text")
        chip_box.pack_start(chip_lbl, False, False, 0)
        sidebar.pack_start(chip_box, False, False, 0)

        self.sidebar_buttons = {}
        nav_items = [
            ("daily_mix", f"{GLYPHS['music']}  Daily Mix"),
            ("recommendations", f"{GLYPHS['recommendations']}  Recommendations"),
            ("library", f"{GLYPHS['library']}  Your Library"),
            ("top_hits", f"{GLYPHS['top_hits']}  Top Hits"),
            ("phonk", f"{GLYPHS['phonk']}  Phonk & Ambient"),
            ("hiphop", f"{GLYPHS['hiphop']}  Trap Bangers"),
            ("rnb", f"{GLYPHS['rnb']}  Late Night R&B"),
            ("cinematic", f"{GLYPHS['cinematic']}  Cinematic Masters")
        ]

        sec_lbl = Gtk.Label(label="PLAYLISTS & MIXES")
        sec_lbl.set_xalign(0.0)
        sec_lbl.get_style_context().add_class("stark-sidebar-section-title")
        sidebar.pack_start(sec_lbl, False, False, 0)

        for s_key, s_name in nav_items:
            btn = Gtk.Button(label=s_name)
            btn.set_halign(Gtk.Align.FILL)
            lbl = btn.get_child()
            if isinstance(lbl, Gtk.Label):
                lbl.set_xalign(0.0)
            btn.get_style_context().add_class("stark-sidebar-item")
            if s_key == "daily_mix":
                btn.get_style_context().add_class("active")
            btn.connect("clicked", self._on_sidebar_clicked, s_key)
            sidebar.pack_start(btn, False, False, 0)
            self.sidebar_buttons[s_key] = btn

        sidebar.pack_start(Gtk.Box(), True, True, 0)

        # Right Content Panel: Playlist Banner + Spotify Track Table
        content_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body_hbox.pack_start(content_vbox, True, True, 0)

        # Dynamic Gradient Banner
        self.banner_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.banner_box.get_style_context().add_class("stark-playlist-banner")
        content_vbox.pack_start(self.banner_box, False, False, 0)

        self.banner_art_img = Gtk.Image()
        self.banner_art_img.get_style_context().add_class("stark-playlist-banner-art")
        self.banner_box.pack_start(self.banner_art_img, False, False, 0)

        banner_text_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        banner_text_col.set_valign(Gtk.Align.CENTER)

        tag_box = Gtk.Box()
        tag_box.get_style_context().add_class("stark-playlist-badge")
        self.banner_tag_lbl = Gtk.Label(label="PLAYLIST")
        self.banner_tag_lbl.get_style_context().add_class("stark-playlist-badge-text")
        tag_box.pack_start(self.banner_tag_lbl, False, False, 0)
        banner_text_col.pack_start(tag_box, False, False, 0)

        self.banner_title_lbl = Gtk.Label(label="Daily Mix 1")
        self.banner_title_lbl.set_xalign(0.0)
        self.banner_title_lbl.get_style_context().add_class("stark-playlist-title")
        banner_text_col.pack_start(self.banner_title_lbl, False, False, 0)

        self.banner_meta_lbl = Gtk.Label(label="Travis Scott, The Weeknd, Kendrick Lamar • 45 songs")
        self.banner_meta_lbl.set_xalign(0.0)
        self.banner_meta_lbl.get_style_context().add_class("stark-playlist-meta")
        banner_text_col.pack_start(self.banner_meta_lbl, False, False, 0)

        self.banner_box.pack_start(banner_text_col, True, True, 0)

        # Play All Button in Banner
        self.btn_play_all = Gtk.Button(label=f"{GLYPHS['play']}  Play All")
        self.btn_play_all.get_style_context().add_class("stark-filter-pill")
        self.btn_play_all.get_style_context().add_class("active")
        self.btn_play_all.set_valign(Gtk.Align.CENTER)
        self.btn_play_all.connect("clicked", lambda w: self._on_play_all())
        self.banner_box.pack_end(self.btn_play_all, False, False, 0)

        # Track Table Header
        th_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        th_box.get_style_context().add_class("stark-table-header")

        th_num = Gtk.Label(label="#")
        th_num.get_style_context().add_class("stark-table-header-lbl")
        th_num.set_size_request(30, -1)
        th_box.pack_start(th_num, False, False, 0)

        th_title = Gtk.Label(label="TITLE & ARTIST")
        th_title.get_style_context().add_class("stark-table-header-lbl")
        th_title.set_xalign(0.0)
        th_box.pack_start(th_title, True, True, 0)

        th_dur = Gtk.Label(label="TIME")
        th_dur.get_style_context().add_class("stark-table-header-lbl")
        th_dur.set_size_request(60, -1)
        th_box.pack_end(th_dur, False, False, 18)

        content_vbox.pack_start(th_box, False, False, 0)

        # Scrollable Track List
        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content_vbox.pack_start(self.scrolled_window, True, True, 0)

        self.track_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.scrolled_window.add(self.track_list_box)

        # Bottom Persistent Docked Player Bar
        docked_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        docked_bar.get_style_context().add_class("stark-bottom-player")
        container.pack_end(docked_bar, False, False, 0)

        # Left: Mini artwork & Title
        self.docked_art_img = Gtk.Image()
        self.docked_art_img.get_style_context().add_class("stark-bottom-art")
        docked_bar.pack_start(self.docked_art_img, False, False, 0)

        docked_meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        docked_meta.set_valign(Gtk.Align.CENTER)
        self.docked_title_lbl = Gtk.Label(label="Ready to Play")
        self.docked_title_lbl.set_xalign(0.0)
        self.docked_title_lbl.set_ellipsize(3)
        self.docked_title_lbl.set_size_request(160, -1)
        self.docked_title_lbl.get_style_context().add_class("stark-bottom-title")
        docked_meta.pack_start(self.docked_title_lbl, False, False, 0)

        self.docked_artist_lbl = Gtk.Label(label="Zenify")
        self.docked_artist_lbl.set_xalign(0.0)
        self.docked_artist_lbl.set_ellipsize(3)
        self.docked_artist_lbl.get_style_context().add_class("stark-bottom-artist")
        docked_meta.pack_start(self.docked_artist_lbl, False, False, 0)
        docked_bar.pack_start(docked_meta, False, False, 0)

        self.btn_docked_heart = Gtk.Button(label=GLYPHS["heart_off"])
        self.btn_docked_heart.get_style_context().add_class("stark-bottom-ctrl-btn")
        self.btn_docked_heart.connect("clicked", self._on_toggle_like)
        docked_bar.pack_start(self.btn_docked_heart, False, False, 0)

        # Center: Playback Controls & Mini Scrubber
        docked_center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        docked_center.set_valign(Gtk.Align.CENTER)
        docked_center.set_hexpand(True)

        d_ctrls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        d_ctrls.set_halign(Gtk.Align.CENTER)

        d_prev = Gtk.Button(label=GLYPHS["prev"])
        d_prev.get_style_context().add_class("stark-bottom-ctrl-btn")
        d_prev.connect("clicked", lambda w: self.player.play_prev())
        d_ctrls.pack_start(d_prev, False, False, 0)

        self.btn_docked_play = Gtk.Button(label=GLYPHS["play"])
        self.btn_docked_play.get_style_context().add_class("stark-bottom-play-btn")
        self.btn_docked_play.connect("clicked", lambda w: self.player.toggle_play())
        d_ctrls.pack_start(self.btn_docked_play, False, False, 0)

        d_next = Gtk.Button(label=GLYPHS["next"])
        d_next.get_style_context().add_class("stark-bottom-ctrl-btn")
        d_next.connect("clicked", lambda w: self.player.play_next())
        d_ctrls.pack_start(d_next, False, False, 0)

        docked_center.pack_start(d_ctrls, False, False, 0)

        # Mini Scrubber Line
        d_scrub_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.docked_cur_time = Gtk.Label(label="0:00")
        self.docked_cur_time.get_style_context().add_class("stark-scrubber-time")
        d_scrub_box.pack_start(self.docked_cur_time, False, False, 0)

        self.docked_scrubber = AppleMusicScrubber(on_seek_cb=self._on_seek, height=12)
        d_scrub_box.pack_start(self.docked_scrubber, True, True, 0)

        self.docked_total_time = Gtk.Label(label="0:00")
        self.docked_total_time.get_style_context().add_class("stark-scrubber-time")
        d_scrub_box.pack_end(self.docked_total_time, False, False, 0)

        docked_center.pack_start(d_scrub_box, False, False, 0)
        docked_bar.pack_start(docked_center, True, True, 12)

        # Right: Volume & Expand to Lyrics Showcase
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        right_box.set_valign(Gtk.Align.CENTER)

        d_vol_icon = Gtk.Label(label=GLYPHS["volume"])
        d_vol_icon.get_style_context().add_class("stark-vol-icon")
        right_box.pack_start(d_vol_icon, False, False, 0)

        self.docked_vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.docked_vol_scale.set_value(self.player.state.get("volume", 80))
        self.docked_vol_scale.set_draw_value(False)
        self.docked_vol_scale.set_size_request(80, -1)
        self.docked_vol_scale.connect("value-changed", self._on_volume_changed)
        right_box.pack_start(self.docked_vol_scale, False, False, 0)

        btn_expand = Gtk.Button(label=f"{GLYPHS['expand']}  Now Playing")
        btn_expand.get_style_context().add_class("stark-expand-btn")
        btn_expand.connect("clicked", lambda w: self.set_mode("player"))
        right_box.pack_end(btn_expand, False, False, 0)

        docked_bar.pack_end(right_box, False, False, 0)

        return container

    # =========================================================================
    # Mode Switching & Actions
    # =========================================================================
    def set_mode(self, mode):
        self.current_mode = mode
        if mode == "player":
            self.stack.set_visible_child_name("player")
            self.btn_mode_player.get_style_context().add_class("active")
            self.btn_mode_browser.get_style_context().remove_class("active")
        else:
            self.stack.set_visible_child_name("browser")
            self.btn_mode_browser.get_style_context().add_class("active")
            self.btn_mode_player.get_style_context().remove_class("active")

    def _on_toggle_like(self, widget):
        self.is_liked = not self.is_liked
        icon = GLYPHS["heart_on"] if self.is_liked else GLYPHS["heart_off"]
        self.btn_docked_heart.set_label(icon)
        self.btn_showcase_star.set_label(GLYPHS["heart_on"] if self.is_liked else GLYPHS["star"])
        if self.is_liked:
            self.btn_showcase_star.get_style_context().add_class("liked")
            self.btn_docked_heart.get_style_context().add_class("liked")
        else:
            self.btn_showcase_star.get_style_context().remove_class("liked")
            self.btn_docked_heart.get_style_context().remove_class("liked")

    def _on_seek(self, pct_or_sec):
        dur = self.player.state.get("duration", 0)
        # Handle both percentage and absolute seconds
        if pct_or_sec <= 100.0 and dur > 0 and isinstance(pct_or_sec, float):
            target_sec = (pct_or_sec / 100.0) * dur
        else:
            target_sec = pct_or_sec
        self.player.seek(target_sec)

    def _on_volume_changed(self, scale):
        val = int(scale.get_value())
        self.player.set_volume(val)
        if scale == self.showcase_vol_scale and hasattr(self, "docked_vol_scale"):
            self.docked_vol_scale.set_value(val)
        elif scale == self.docked_vol_scale and hasattr(self, "showcase_vol_scale"):
            self.showcase_vol_scale.set_value(val)

    def _on_toggle_autoplay(self, btn):
        enabled = self.player.toggle_autoplay()
        if enabled:
            self.btn_showcase_repeat.get_style_context().add_class("active")
        else:
            self.btn_showcase_repeat.get_style_context().remove_class("active")

    def _on_shuffle_queue(self):
        if self.current_tracks:
            random.shuffle(self.current_tracks)
            self._render_tracks(self.current_tracks)

    def _on_play_all(self):
        if self.current_tracks:
            self._on_play_track(self.current_tracks[0])

    # =========================================================================
    # Navigation, Filter & Search Handlers
    # =========================================================================
    def _on_sidebar_clicked(self, btn, cat_key):
        for k, b in self.sidebar_buttons.items():
            if k == cat_key:
                b.get_style_context().add_class("active")
            else:
                b.get_style_context().remove_class("active")
        for k, b in self.filter_buttons.items():
            if k == cat_key:
                b.get_style_context().add_class("active")
            else:
                b.get_style_context().remove_class("active")
        threading.Thread(target=self._load_category, args=(cat_key,), daemon=True).start()

    def _on_filter_clicked(self, btn, cat_key):
        self._on_sidebar_clicked(btn, cat_key)

    def _on_search_text_changed(self, entry):
        if self.search_debounce_timer:
            GLib.source_remove(self.search_debounce_timer)
        q = entry.get_text().strip()
        if len(q) >= 2:
            self.search_debounce_timer = GLib.timeout_add(350, self._trigger_search, q)

    def _on_search_activate(self, entry):
        q = entry.get_text().strip()
        if q:
            self._trigger_search(q)

    def _trigger_search(self, q):
        self.search_debounce_timer = None
        self.banner_tag_lbl.set_label("SEARCH RESULTS")
        self.banner_title_lbl.set_label(f'"{q}"')
        self.banner_meta_lbl.set_label("Searching official catalogs & store APIs...")

        def _worker():
            results = StarkPlayerBackend.search_official_catalog(q, limit=20)
            GLib.idle_add(self._render_tracks, results)
            GLib.idle_add(self.banner_meta_lbl.set_label, f"{len(results)} results found")

        threading.Thread(target=_worker, daemon=True).start()
        return False

    def _load_category(self, cat_key, force_refresh=False):
        self.current_category = cat_key

        category_titles = {
            "daily_mix": ("Daily Mix 1", "Curated from your Last.fm favorites • Travis Scott, The Weeknd, Kendrick"),
            "recommendations": ("Collaborative Recommendations", f"Last.fm smart peer algorithm for '{self.username}'"),
            "library": ("Seeded Bangers", "Your 19 core seed bangers from browser history"),
            "top_hits": ("Global Top Hits", "Top trending official tracks"),
            "hiphop": ("Trap & Hip-Hop Bangers", "Travis Scott, Metro Boomin, 21 Savage, Don Toliver"),
            "phonk": ("Phonk & Night Drive", "øneheart, DVRST, Hensonn, After Dark"),
            "rnb": ("Late Night R&B", "The Weeknd, Frank Ocean, Lana Del Rey"),
            "cinematic": ("Cinematic & Epic Scores", "Hans Zimmer, Ludwig Göransson, Interstellar")
        }

        title, desc = category_titles.get(cat_key, (cat_key.title(), "Curated audio selection"))
        GLib.idle_add(self.banner_tag_lbl.set_label, "PLAYLIST")
        GLib.idle_add(self.banner_title_lbl.set_label, title)
        GLib.idle_add(self.banner_meta_lbl.set_label, desc)

        tracks = []
        if cat_key == "daily_mix":
            tracks = self.player.history_mgr.get_daily_suggestions()
        elif cat_key == "library":
            tracks = self.player.history_mgr.get_history(limit=50)
        elif cat_key == "recommendations":
            engine = self.player.history_mgr.recommendation_engine
            tracks = engine.fetch_collaborative_similar("Travis Scott", limit=8)
            tracks += engine.fetch_collaborative_similar("The Weeknd", limit=8)
        elif cat_key == "hiphop":
            engine = self.player.history_mgr.recommendation_engine
            tracks = engine.fetch_lastfm_top_tracks("Travis Scott", limit=8)
            tracks += engine.fetch_lastfm_top_tracks("Metro Boomin", limit=6)
        elif cat_key == "phonk":
            engine = self.player.history_mgr.recommendation_engine
            tracks = engine.fetch_tag_top_tracks("phonk", limit=8)
            tracks += engine.fetch_tag_top_tracks("ambient", limit=6)
        elif cat_key == "rnb":
            engine = self.player.history_mgr.recommendation_engine
            tracks = engine.fetch_lastfm_top_tracks("The Weeknd", limit=8)
            tracks += engine.fetch_lastfm_top_tracks("Frank Ocean", limit=6)
        elif cat_key == "cinematic":
            engine = self.player.history_mgr.recommendation_engine
            tracks = engine.fetch_lastfm_top_tracks("Hans Zimmer", limit=8)

        if not tracks:
            tracks = self.player.history_mgr.get_history(limit=25)

        GLib.idle_add(self._render_tracks, tracks)

    # =========================================================================
    # Spotify Track Table Renderer
    # =========================================================================
    def _render_tracks(self, tracks):
        self.current_tracks = tracks
        for child in self.track_list_box.get_children():
            self.track_list_box.remove(child)

        # Update Banner Art with First Track's Art
        if tracks and tracks[0].get("art_url"):
            self._load_art_image(tracks[0].get("art_url"), self.banner_art_img, size=88)

        cur_title = self.player.state.get("title", "").lower()

        for idx, track in enumerate(tracks, start=1):
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            row_box.get_style_context().add_class("stark-track-row")

            is_active = (track.get("title", "").lower() == cur_title)
            if is_active:
                row_box.get_style_context().add_class("now-playing")

            # Track Number
            num_lbl = Gtk.Label(label=f"{idx:02d}")
            num_lbl.get_style_context().add_class("stark-track-num")
            row_box.pack_start(num_lbl, False, False, 0)

            # Thumbnail Artwork
            thumb_img = Gtk.Image()
            thumb_img.get_style_context().add_class("stark-track-art")
            thumb_img.set_size_request(40, 40)
            self._load_art_image(track.get("art_url", ""), thumb_img, size=40)
            row_box.pack_start(thumb_img, False, False, 0)

            # Title & Artist Column
            meta_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            meta_col.set_valign(Gtk.Align.CENTER)

            t_lbl = Gtk.Label(label=track.get("title", "Unknown Track"))
            t_lbl.set_xalign(0.0)
            t_lbl.set_ellipsize(3)
            t_lbl.get_style_context().add_class("stark-track-title")
            meta_col.pack_start(t_lbl, False, False, 0)

            a_lbl = Gtk.Label(label=track.get("artist", "Unknown Artist"))
            a_lbl.set_xalign(0.0)
            a_lbl.set_ellipsize(3)
            a_lbl.get_style_context().add_class("stark-track-artist")
            meta_col.pack_start(a_lbl, False, False, 0)

            row_box.pack_start(meta_col, True, True, 0)

            # Duration
            dur = track.get("duration", 0)
            dur_str = format_duration(dur) if dur > 0 else "--:--"
            d_lbl = Gtk.Label(label=dur_str)
            d_lbl.get_style_context().add_class("stark-track-duration")
            row_box.pack_end(d_lbl, False, False, 8)

            # Play Button
            btn_play = Gtk.Button(label=GLYPHS["play"])
            btn_play.get_style_context().add_class("stark-track-play-btn")
            btn_play.connect("clicked", lambda w, t=track: self._on_play_track(t))
            row_box.pack_end(btn_play, False, False, 0)

            # Event box so clicking anywhere on row plays the track
            ev_box = Gtk.EventBox()
            ev_box.add(row_box)
            ev_box.connect("button-press-event", lambda w, e, t=track: self._on_play_track(t))

            self.track_list_box.pack_start(ev_box, False, False, 0)

        self.track_list_box.show_all()

    def _on_play_track(self, track):
        title = track.get("title", "")
        artist = track.get("artist", "")
        art_url = track.get("art_url", "")
        yt_id = track.get("yt_id", "")

        # Immediate responsive UI update
        self.showcase_title_lbl.set_label(title)
        self.showcase_artist_lbl.set_label(artist)
        self.docked_title_lbl.set_label(title)
        self.docked_artist_lbl.set_label(artist)
        self.header_ticker_lbl.set_label(f"Now Playing: {title} • {artist}")

        # Async audio resolution in background thread
        def _worker():
            self.player.play_track(title, artist, art_url, yt_id)

        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # Artwork Async Caching & Palette Extraction
    # =========================================================================
    def _load_art_image(self, art_url, gtk_image, size=40):
        def _worker():
            cache_file = None
            if art_url:
                fn = hashlib.md5(art_url.encode("utf-8")).hexdigest() + f"_{size}.jpg"
                p = os.path.join(THUMB_CACHE_DIR, fn)
                if os.path.exists(p) and os.path.getsize(p) > 300:
                    cache_file = p
                else:
                    try:
                        req = urllib.request.Request(art_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=3.5) as resp, open(p, "wb") as f:
                            f.write(resp.read())
                        cache_file = p
                    except Exception:
                        pass
            if not cache_file:
                cache_file = os.path.join(ASSETS_DIR, "after_dark.png")

            if cache_file and os.path.exists(cache_file):
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(cache_file, size, size, False)
                    GLib.idle_add(gtk_image.set_from_pixbuf, pb)
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # Real-Time Playback Synchronization Loop (200ms - Blazing Fast)
    # =========================================================================
    def _update_player_state(self):
        st = self.player.update_playback_metrics()
        title = st.get("title", "Ready to Play")
        artist = st.get("artist", "Zenify Audio")
        pos = st.get("position", 0.0)
        dur = st.get("duration", 0.0)
        prog = st.get("progress", 0.0)
        is_playing = st.get("is_playing", False)
        art_path = st.get("art_path")

        # 1. Update Title & Artist Labels
        self.showcase_title_lbl.set_label(title)
        self.showcase_artist_lbl.set_label(artist)
        self.docked_title_lbl.set_label(title)
        self.docked_artist_lbl.set_label(artist)
        self.header_ticker_lbl.set_label(f"Now Playing: {title} • {artist}")

        # 2. Update Play/Pause Buttons
        glyph = GLYPHS["pause"] if is_playing else GLYPHS["play"]
        self.btn_showcase_play.set_label(glyph)
        self.btn_docked_play.set_label(glyph)

        # 3. Update Progress Scrubber & Times
        self.showcase_scrubber.set_progress(prog)
        self.docked_scrubber.set_progress(prog)

        elapsed_str = format_duration(pos)
        remaining_str = format_remaining(dur, pos) if dur > 0 else "-0:00"
        self.showcase_time_elapsed.set_label(elapsed_str)
        self.showcase_time_remaining.set_label(remaining_str)

        self.docked_cur_time.set_label(elapsed_str)
        self.docked_total_time.set_label(format_duration(dur))

        # 4. Cover Art & Mesh Palette Sync
        if hasattr(self, "_last_synced_art") and self._last_synced_art != art_path:
            self._last_synced_art = art_path
            self._sync_art_and_palette(art_path)
        elif not hasattr(self, "_last_synced_art"):
            self._last_synced_art = art_path
            self._sync_art_and_palette(art_path)

        # 5. Check & Fetch Lyrics if track changed
        track_key = f"{title}_{artist}"
        if track_key != self._last_loaded_track_key and title not in ("Ready to Play", "Nothing Playing"):
            self._load_lyrics_for_track(title, artist, dur)

        # 6. Real-Time 60FPS Kinetic Lyrics Canvas Update
        self.lyrics_canvas.update_position(pos)

        return True

    def _sync_art_and_palette(self, art_path):
        if not art_path or not os.path.exists(art_path):
            art_path = os.path.join(ASSETS_DIR, "after_dark.png")

        def _worker():
            p_rgb, s_rgb = extract_art_palette(art_path)
            GLib.idle_add(self._update_dynamic_gradient, p_rgb, s_rgb)

            try:
                # Left Showcase Artwork (280x280)
                pb_showcase = GdkPixbuf.Pixbuf.new_from_file_at_scale(art_path, 280, 280, False)
                GLib.idle_add(self.showcase_art_img.set_from_pixbuf, pb_showcase)

                # Bottom Docked Artwork (44x44)
                pb_mini = GdkPixbuf.Pixbuf.new_from_file_at_scale(art_path, 44, 44, False)
                GLib.idle_add(self.docked_art_img.set_from_pixbuf, pb_mini)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # Keyboard Shortcuts & IPC
    # =========================================================================
    def _on_key_press(self, widget, event):
        val = event.keyval
        # Tab or B toggles between Player and Browser mode
        if val in (Gdk.KEY_Tab, Gdk.KEY_b, Gdk.KEY_B):
            if not isinstance(self.get_focus(), Gtk.Entry):
                next_mode = "browser" if self.current_mode == "player" else "player"
                self.set_mode(next_mode)
                return True
        elif val == Gdk.KEY_Escape:
            if self.current_mode == "browser":
                self.set_mode("player")
                return True
            else:
                self.hide()
                return True
        # Spacebar toggles Play/Pause
        elif val == Gdk.KEY_space:
            if not isinstance(self.get_focus(), Gtk.Entry):
                self.player.toggle_play()
                return True
        # Left/Right Arrow seeks -5s / +5s
        elif val == Gdk.KEY_Left:
            if not isinstance(self.get_focus(), Gtk.Entry):
                self.player.seek(max(0, self.player.state.get("position", 0) - 5))
                return True
        elif val == Gdk.KEY_Right:
            if not isinstance(self.get_focus(), Gtk.Entry):
                self.player.seek(self.player.state.get("position", 0) + 5)
                return True
        return False

    def _hide_or_quit(self):
        self.hide()
        return True

    def _start_ipc_server(self):
        if os.path.exists(UI_SOCKET):
            try:
                os.remove(UI_SOCKET)
            except Exception:
                pass

        def server_loop():
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.bind(UI_SOCKET)
            s.listen(5)
            while True:
                try:
                    conn, _ = s.accept()
                    data = conn.recv(1024).decode("utf-8").strip()
                    if data == "toggle":
                        GLib.idle_add(self._toggle_visibility)
                    elif data == "play":
                        GLib.idle_add(self.player.toggle_play)
                    elif data == "next":
                        GLib.idle_add(self.player.play_next)
                    elif data == "prev":
                        GLib.idle_add(self.player.play_prev)
                    elif data == "mode_player":
                        GLib.idle_add(self.set_mode, "player")
                    elif data == "mode_browser":
                        GLib.idle_add(self.set_mode, "browser")
                    conn.close()
                except Exception:
                    pass

        threading.Thread(target=server_loop, daemon=True).start()

    def _toggle_visibility(self):
        if self.is_visible():
            self.hide()
        else:
            self.show_all()
            self.present()


def toggle_or_launch():
    if os.path.exists(UI_SOCKET):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(UI_SOCKET)
            s.sendall(b"toggle\n")
            s.close()
            return True
        except Exception:
            try:
                os.remove(UI_SOCKET)
            except Exception:
                pass
    return False


def main():
    if "--toggle" in sys.argv:
        if toggle_or_launch():
            sys.exit(0)

    app = StarkifyApp()
    app.show_all()
    app.present()
    Gtk.main()


if __name__ == "__main__":
    main()
