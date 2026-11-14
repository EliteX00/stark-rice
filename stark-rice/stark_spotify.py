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
import re
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
        self._is_dragging = False
        self.accent_rgb = (255, 255, 255)
        self.set_size_request(260, height)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_button_press)
        self.connect("button-release-event", self._on_button_release)
        self.connect("motion-notify-event", self._on_motion)

    def set_progress(self, prog):
        if self._is_dragging:
            return
        new_prog = max(0.0, min(1.0, prog))
        w = self.get_allocated_width()
        threshold = 0.5 / max(1, w) if w > 0 else 0.002
        if abs(self.progress - new_prog) < threshold:
            return
        self.progress = new_prog
        self.queue_draw()

    def set_accent_rgb(self, rgb):
        self.accent_rgb = rgb
        self.queue_draw()

    def _calc_pct(self, event_x):
        w = self.get_allocated_width()
        if w > 0:
            return max(0.0, min(1.0, event_x / float(w))) * 100.0
        return 0.0

    def _on_button_press(self, widget, event):
        if event.button == 1:
            self._is_dragging = True
            pct = self._calc_pct(event.x)
            self.progress = pct / 100.0
            self.queue_draw()
            if self.on_seek_cb:
                self.on_seek_cb(pct)
            return True
        return False

    def _on_motion(self, widget, event):
        if self._is_dragging:
            pct = self._calc_pct(event.x)
            self.progress = pct / 100.0
            self.queue_draw()
            return True
        return False

    def _on_button_release(self, widget, event):
        if event.button == 1 and self._is_dragging:
            self._is_dragging = False
            pct = self._calc_pct(event.x)
            self.progress = pct / 100.0
            self.queue_draw()
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
# ==============================================================================
# Dual-Mode Kinetic Typography & Apple Luminescence Canvas (60 FPS Locked)
# Ground-Truth Per-Word Sync with Minimalist Monochrome Glyphs & Static Rows
# ==============================================================================
MINIMAL_GLYPHS = {
    'car': '󰄋', 'cars': '󰄋', 'drive': '󰄋', 'driving': '󰄋', 'ride': '󰄋', 'whip': '󰄋', 'skrrt': '󰄋', 'drift': '󰄋',
    'phone': '󰏲', 'call': '󰏲', 'calling': '󰏲', 'ring': '󰏲',
    'time': '󰅐', 'minute': '󰅐', 'minutes': '󰅐', 'wait': '󰅐', 'waiting': '󰅐', 'hour': '󰅐',
    'heart': '󰋑', 'hearts': '󰋑', 'love': '󰋑', 'need': '󰋑', 'kiss': '󰋑',
    'fire': '󰈸', 'hot': '󰈸', 'burn': '󰈸', 'burning': '󰈸', 'flame': '󰈸',
    'star': '󰓎', 'stars': '󰓎', 'shine': '󰓎', 'sparkle': '󰓎',
    'music': '󰎆', 'song': '󰎆', 'sing': '󰎆', 'note': '󰎆',
    'rain': '󰖗', 'raining': '󰖗', 'storm': '󰖗', 'thunder': '󰖗',
    'sun': '󰖙', 'sunny': '󰖙', 'summer': '󰖙',
    'moon': '󰖔', 'night': '󰖔', 'midnight': '󰖔',
    'wind': '󰖝', 'blew': '󰖝', 'smoke': '󰖝', 'cloud': '󰖝',
    'money': '󰈚', 'cash': '󰈚', 'bands': '󰈚', 'rich': '󰈚', 'bag': '󰈚',
    'crown': '󰄯', 'king': '󰄯', 'queen': '󰄯',
    'eye': '󰈈', 'eyes': '󰈈', 'see': '󰈈', 'look': '󰈈',
    'smile': '󰍢', 'happy': '󰍢', 'laugh': '󰍢',
    'talk': '󰭹', 'say': '󰭹', 'telling': '󰭹', 'chat': '󰭹',
    'pill': '󰈺', 'pills': '󰈺',
    'walk': '󰈲', 'walking': '󰈲', 'run': '󰈲', 'running': '󰈲', 'dance': '󰈲',
    'plane': '󰀝', 'fly': '󰀝', 'flight': '󰀝',
    'chance': '󰄮', 'chances': '󰄮', 'deal': '󰄮', 'dice': '󰄮'
}

# ==============================================================================
# Dynamic Kinetic Typography Animation Presets
# ==============================================================================
ANIMATION_STYLES = {
    "constellation": {
        "id": "constellation",
        "name": "Constellation",
        "icon": "✦",
        "desc": "Celestial star map with connecting lines & diamond stars"
    },
    "apple_sing": {
        "id": "apple_sing",
        "name": "Apple Sing",
        "icon": "󰎆",
        "desc": "Fluid progressive syllable clipping wipe & 1.06x spring lift"
    },
    "impact_bounce": {
        "id": "impact_bounce",
        "name": "Impact Bounce",
        "icon": "󰑣",
        "desc": "Beat-synced 1.25x elastic pop & cover art ghost shards"
    },
    "rolling_flip": {
        "id": "rolling_flip",
        "name": "Rolling Flip",
        "icon": "󰐊",
        "desc": "Split-flap 3D perspective roll with cover art shadow"
    },
    "minimal_wave": {
        "id": "minimal_wave",
        "name": "Minimal Wave",
        "icon": "󰛐",
        "desc": "Silk sinusoidal vertical wave float & luminescence"
    },
    "glitch_flicker": {
        "id": "glitch_flicker",
        "name": "Cyber Glitch",
        "icon": "󰒓",
        "desc": "Streetwear chromatic prism split & strobe impact"
    }
}

STYLE_ALIASES = {
    "spring": "impact_bounce",
    "float": "minimal_wave",
    "cyber": "glitch_flicker",
    "retro": "rolling_flip",
    "luminescence": "apple_sing",
}


class CinematicLyricsCanvas(Gtk.DrawingArea):
    def __init__(self, on_seek_cb=None):
        super().__init__()
        self.on_seek_cb = on_seek_cb
        self.raw_lines = []
        self.kinetic_lines = []
        self.is_synced = False
        self.anim_style = "apple_sing"

        self.active_line_idx = -1
        self.smooth_line_idx = 0.0
        self.active_word_key = ''
        self._constellation_cache = {}
        self.last_c_w = 0
        self.last_c_h = 0

        # Audio Latency Offset Compensation (aligns visual strikes with acoustic waves)
        self.latency_offset = 0.0
        self.hud_toast_text = ""
        self.hud_toast_timer = 0.0

        # Persistent Pango Layouts & Pre-compiled Font Descriptions (Zero alloc in _on_draw!)
        self.pctx = None
        self.layout_word = None
        self.layout_ctx = None
        self.layout_toast = None
        self.cached_layouts = {}
        self.last_cache_w = 0

        self.font_act_constellation = Pango.FontDescription('Google Sans Flex Bold 30')
        self.font_past_constellation = Pango.FontDescription('Google Sans Flex Medium 15')
        self.font_context = Pango.FontDescription('Google Sans Flex Bold 16')
        self.font_toast = Pango.FontDescription('Google Sans Flex Bold 13')
        self.font_intro = Pango.FontDescription('Google Sans Flex Bold 15')
        self.font_intro_first = Pango.FontDescription('Google Sans Flex Bold 17')
        self.font_empty = Pango.FontDescription('Google Sans Flex Bold 18')

        # Audio-reactive Cava Engine for vocal / bass energy modulation
        try:
            from stark_widgets import CavaVisualizerEngine
            self.cava = CavaVisualizerEngine(num_bars=10)
        except Exception:
            self.cava = None

        # Continuous Sub-Millisecond Time Interpolation
        self.anchor_pos = 0.0
        self.anchor_wall_time = time.perf_counter()
        self.is_playing = False

        self.primary_accent = (56, 189, 248)
        self.secondary_accent = (200, 160, 180)
        self.anim_timer = None
        self.user_scrolling = False
        self.snap_back_timer = None

        # Floating Ambient Particles
        self.particles = []
        for _ in range(16):
            self.particles.append({
                'x': random.uniform(0.0, 1.0),
                'y': random.uniform(0.0, 1.0),
                'r': random.uniform(1.2, 3.0),
                'vy': random.uniform(0.0003, 0.0007),
                'vx': random.uniform(-0.00015, 0.00015),
                'alpha': random.uniform(0.08, 0.20)
            })

        self.shockwaves = []

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect('draw', self._on_draw)
        self.connect('button-press-event', self._on_click)
        self.connect('scroll-event', self._on_scroll)

        self._start_anim()

    def nudge_offset(self, delta):
        self.latency_offset += delta
        self.hud_toast_text = f"󰅐 Lyrics Offset: {self.latency_offset:+.2f}s"
        self.hud_toast_timer = time.time() + 1.8
        self.queue_draw()

    def reset_offset(self):
        self.latency_offset = -0.10
        self.hud_toast_text = f"󰅐 Lyrics Offset Reset: {self.latency_offset:+.2f}s"
        self.hud_toast_timer = time.time() + 1.8
        self.queue_draw()

    def set_palette(self, p_rgb, s_rgb):
        self.primary_accent = p_rgb
        self.secondary_accent = s_rgb
        self.queue_draw()

    def set_accent_rgb(self, rgb):
        self.primary_accent = rgb
        self.queue_draw()

    def set_anim_style(self, style_key):
        style_key = STYLE_ALIASES.get(style_key, style_key)
        if style_key in ANIMATION_STYLES:
            self.anim_style = style_key
            st = ANIMATION_STYLES[style_key]
            self.hud_toast_text = f"{st['icon']}  {st['name']}"
            self.hud_toast_timer = time.time() + 1.8
            self.queue_draw()

    def cycle_anim_style(self):
        keys = list(ANIMATION_STYLES.keys())
        cur = STYLE_ALIASES.get(self.anim_style, self.anim_style)
        idx = (keys.index(cur) + 1) % len(keys) if cur in keys else 0
        self.set_anim_style(keys[idx])
        return keys[idx]

    def set_lyrics(self, k_lines, is_synced, raw_text='', words=None):
        self.is_synced = is_synced
        self.raw_lines = [(l['start'], l['text']) for l in k_lines] if is_synced else []
        self.kinetic_lines = k_lines if is_synced else []

        # Attach minimalist monochrome glyphs to words
        for line in self.kinetic_lines:
            for w in line.get('words', []):
                clean = w.get('clean')
                if not clean:
                    clean = re.sub(r'[^a-zA-Z0-9]', '', w.get('text', '')).lower()
                    w['clean'] = clean
                w['glyph'] = MINIMAL_GLYPHS.get(clean.lower(), '')

        self.cached_layouts.clear()
        if hasattr(self, '_constellation_cache'):
            self._constellation_cache.clear()
        self.last_cache_w = 0
        self.active_line_idx = -1
        self.smooth_line_idx = 0.0
        self.active_word_key = ''
        self.queue_draw()

    def _draw_diamond_star(self, cr, cx, cy, r_outer, r_inner=None):
        if r_inner is None:
            r_inner = r_outer * 0.28
        cr.new_sub_path()
        for pt in range(8):
            angle = -math.pi / 2 + pt * (math.pi / 4)
            r = r_outer if pt % 2 == 0 else r_inner
            px = cx + r * math.cos(angle)
            py = cy + r * math.sin(angle)
            if pt == 0:
                cr.move_to(px, py)
            else:
                cr.line_to(px, py)
        cr.close_path()

    def _get_constellation_layout(self, line_idx, canvas_w, canvas_h):
        if not hasattr(self, '_constellation_cache'):
            self._constellation_cache = {}

        if abs(canvas_w - getattr(self, 'last_c_w', 0)) > 15 or abs(canvas_h - getattr(self, 'last_c_h', 0)) > 15:
            self._constellation_cache.clear()
            self.last_c_w = canvas_w
            self.last_c_h = canvas_h

        cache_key = f"{line_idx}_{int(canvas_w)}_{int(canvas_h)}"
        if cache_key in self._constellation_cache:
            return self._constellation_cache[cache_key]

        if not self.kinetic_lines or line_idx < 0 or line_idx >= len(self.kinetic_lines):
            return None

        line = self.kinetic_lines[line_idx]
        words = line.get('words', [])
        n = len(words)
        if n == 0:
            return None

        self._ensure_layouts()
        seed = (hash(line.get('text', '')) ^ (line_idx * 7919)) & 0xFFFFFFFF
        rng = random.Random(seed)

        min_x = canvas_w * 0.14
        max_x = canvas_w * 0.86
        min_y = canvas_h * 0.20
        max_y = canvas_h * 0.80
        usable_w = max_x - min_x
        usable_h = max_y - min_y
        y_mid = min_y + usable_h * 0.5

        if n == 1:
            txt = words[0]['text']
            la = Pango.Layout.new(self.pctx)
            la.set_font_description(self.font_act_constellation)
            la.set_text(txt, -1)
            twa, tha = la.get_pixel_size()

            lp = Pango.Layout.new(self.pctx)
            lp.set_font_description(self.font_past_constellation)
            lp.set_text(txt, -1)
            twp, thp = lp.get_pixel_size()

            nodes = [{
                'idx': 0, 'x': canvas_w * 0.5, 'y': canvas_h * 0.5, 'pos_above': True,
                'layout_act': la, 'twa': twa, 'tha': tha,
                'layout_past': lp, 'twp': twp, 'thp': thp
            }]
            res = {'nodes': nodes, 'words': words}
            self._constellation_cache[cache_key] = res
            return res

        # Organic Poisson-spaced random scatter for authentic constellations with overlapping lines
        min_dist = max(75.0, min(170.0, math.sqrt((usable_w * usable_h) / max(1, n * 1.35))))

        pts = []
        for i in range(n):
            best_pt = None
            best_dist = -1.0
            for attempt in range(100):
                rx = rng.uniform(min_x, max_x)
                ry = rng.uniform(min_y, max_y)
                too_close = False
                cur_min = 99999.0
                for px, py in pts:
                    d = math.hypot(rx - px, ry - py)
                    if d < min_dist:
                        too_close = True
                        break
                    if d < cur_min:
                        cur_min = d
                if not too_close:
                    best_pt = (rx, ry)
                    break
                elif cur_min > best_dist:
                    best_dist = cur_min
                    best_pt = (rx, ry)
            pts.append(best_pt)

        nodes = []
        for i, (x, y) in enumerate(pts):
            pos_above = (y >= y_mid)
            txt = words[i]['text']

            la = Pango.Layout.new(self.pctx)
            la.set_font_description(self.font_act_constellation)
            la.set_text(txt, -1)
            twa, tha = la.get_pixel_size()

            lp = Pango.Layout.new(self.pctx)
            lp.set_font_description(self.font_past_constellation)
            lp.set_text(txt, -1)
            twp, thp = lp.get_pixel_size()

            nodes.append({
                'idx': i,
                'x': x,
                'y': y,
                'pos_above': pos_above,
                'layout_act': la,
                'twa': twa,
                'tha': tha,
                'layout_past': lp,
                'twp': twp,
                'thp': thp
            })

        res = {'nodes': nodes, 'words': words}
        self._constellation_cache[cache_key] = res
        return res

    def update_position(self, pos_sec, is_playing=True):
        self.anchor_pos = max(0.0, float(pos_sec))
        self.anchor_wall_time = time.perf_counter()
        self.is_playing = is_playing
        self._start_anim()

    def pause_cava(self):
        if hasattr(self, 'cava') and self.cava and self.cava.proc:
            try:
                import signal
                os.kill(self.cava.proc.pid, signal.SIGSTOP)
            except Exception:
                pass

    def resume_cava(self):
        if hasattr(self, 'cava') and self.cava and self.cava.proc:
            try:
                import signal
                os.kill(self.cava.proc.pid, signal.SIGCONT)
            except Exception:
                pass

    def cleanup(self):
        if hasattr(self, 'cava') and self.cava:
            try:
                self.cava.stop()
            except Exception:
                pass

    def _start_anim(self):
        if not self.anim_timer:
            self.anim_timer = GLib.timeout_add(16, self._on_frame_tick)

    def _get_smooth_time(self):
        if self.is_playing:
            dt = time.perf_counter() - self.anchor_wall_time
            return self.anchor_pos + dt
        return self.anchor_pos

    def _ensure_layouts(self):
        if self.pctx is None:
            self.pctx = self.get_pango_context()
            self.layout_word = Pango.Layout.new(self.pctx)
            self.layout_ctx = Pango.Layout.new(self.pctx)
            self.layout_toast = Pango.Layout.new(self.pctx)
            self.layout_toast.set_font_description(self.font_toast)
            self.layout_toast.set_alignment(Pango.Alignment.CENTER)

    def _get_line_layout(self, line_idx, canvas_w):
        if line_idx < 0 or line_idx >= len(self.kinetic_lines):
            return None

        if abs(canvas_w - self.last_cache_w) > 10:
            self.cached_layouts.clear()
            self.last_cache_w = canvas_w

        if line_idx in self.cached_layouts:
            return self.cached_layouts[line_idx]

        self._ensure_layouts()
        line = self.kinetic_lines[line_idx]
        is_rap = (line.get('wps', 2.0) >= 2.4)

        if canvas_w < 480:
            base_font_size = 20
        elif canvas_w < 620:
            base_font_size = 22
        else:
            base_font_size = 24

        font_desc_str = f'Google Sans Flex, JetBrainsMono Nerd Font {base_font_size}'
        desc = Pango.FontDescription(font_desc_str)
        desc.set_weight(Pango.Weight.HEAVY if is_rap else Pango.Weight.BOLD)
        self.layout_word.set_font_description(desc)

        self.layout_word.set_text(' ', -1)
        space_w, _ = self.layout_word.get_pixel_size()
        word_spacing = max(space_w + 6, int(space_w * 1.7))

        measured_words = []
        for w_idx, w_obj in enumerate(line['words']):
            glyph = w_obj.get('glyph', '')
            disp_text = f"{w_obj['text']} {glyph}" if glyph else w_obj['text']
            wl = Pango.Layout.new(self.pctx)
            wl.set_font_description(desc)
            wl.set_text(disp_text, -1)
            pw, ph = wl.get_pixel_size()
            measured_words.append({
                'idx': w_idx,
                'obj': w_obj,
                'text': disp_text,
                'clean': w_obj['clean'],
                'start': w_obj['start'],
                'end': w_obj['end'],
                'duration': w_obj['duration'],
                'layout': wl,
                'pw': pw,
                'ph': ph
            })

        # STATIC row division - NEVER re-wraps words when active!
        max_row_w = max(220.0, canvas_w - 90.0)
        rows = []
        cur_row_words = []
        cur_row_w = 0.0

        for mw in measured_words:
            pw = mw['pw']
            if cur_row_words and (cur_row_w + word_spacing + pw > max_row_w):
                rows.append({'words': cur_row_words, 'w': cur_row_w})
                cur_row_words = [mw]
                cur_row_w = pw
            else:
                if cur_row_words:
                    cur_row_w += word_spacing + pw
                else:
                    cur_row_w = pw
                cur_row_words.append(mw)
        if cur_row_words:
            rows.append({'words': cur_row_words, 'w': cur_row_w})

        row_h = float(base_font_size * 1.6)
        total_h = len(rows) * row_h

        # Position words within rows statically
        for r_idx, r in enumerate(rows):
            r_start_x = max(24.0, (canvas_w - r['w']) / 2.0)
            x_cursor = r_start_x
            y_pos = r_idx * row_h
            for mw in r['words']:
                mw['x'] = x_cursor
                mw['y'] = y_pos
                mw['cx'] = x_cursor + (mw['pw'] / 2.0)
                mw['cy'] = y_pos + (mw['ph'] / 2.0)
                x_cursor += mw['pw'] + word_spacing

        # Pre-build context layout for previous/next line rendering (zero-alloc in _on_draw)
        ctx_l = Pango.Layout.new(self.pctx)
        ctx_l.set_font_description(self.font_context)
        ctx_l.set_alignment(Pango.Alignment.CENTER)
        ctx_l.set_width(int((max(200.0, canvas_w - 48.0)) * Pango.SCALE))
        ctx_l.set_text(line.get('text', ''), -1)
        _, ctx_h = ctx_l.get_pixel_size()

        layout_data = {
            'is_rap': is_rap,
            'font_size': base_font_size,
            'desc': desc,
            'rows': rows,
            'total_h': total_h,
            'row_h': row_h,
            'context_layout': ctx_l,
            'context_h': ctx_h
        }
        self.cached_layouts[line_idx] = layout_data
        return layout_data

    def _on_frame_tick(self):
        if not self.is_visible():
            return True

        if not self.is_playing and not self.user_scrolling and not self.shockwaves:
            return True

        cur_t = self._get_smooth_time() + self.latency_offset

        if self.is_synced and self.kinetic_lines and not self.user_scrolling:
            new_line = -1
            for i, l in enumerate(self.kinetic_lines):
                if cur_t >= l['start']:
                    new_line = i
                else:
                    break
            if new_line != -1 and new_line != self.active_line_idx:
                self.active_line_idx = new_line
                self.active_word_key = ''
            elif new_line == -1 and cur_t < self.kinetic_lines[0]['start']:
                self.active_line_idx = -1
                self.active_word_key = ''

            # Trigger shockwave when active word strikes in fast rap tracks
            if self.active_line_idx != -1 and self.active_line_idx < len(self.kinetic_lines):
                cur_l = self.kinetic_lines[self.active_line_idx]
                if cur_l.get('wps', 2.0) >= 2.4:
                    for w_obj in cur_l.get('words', []):
                        if w_obj['start'] <= cur_t <= w_obj['end']:
                            w_key = f"{self.active_line_idx}_{w_obj['text']}_{w_obj['start']}"
                            if w_key != self.active_word_key:
                                self.active_word_key = w_key
                                w_canvas = self.get_allocated_width()
                                h_canvas = self.get_allocated_height()
                                self._trigger_shockwave(w_canvas / 2.0, h_canvas * 0.48, max_r=55)
                            break

            target_idx = max(0, self.active_line_idx) if self.active_line_idx != -1 else 0.0
            diff = float(target_idx) - self.smooth_line_idx
            self.smooth_line_idx += diff * 0.18

        # Floating ambient dust
        for p in self.particles:
            p['y'] -= p['vy']
            p['x'] += p['vx']
            if p['y'] < -0.05:
                p['y'] = 1.05
                p['x'] = random.uniform(0.0, 1.0)
            if p['x'] < 0.0 or p['x'] > 1.0:
                p['vx'] = -p['vx']

        # Shockwaves
        kept_waves = []
        for sw in self.shockwaves:
            sw['r'] += 3.2
            sw['alpha'] -= 0.045
            if sw['alpha'] > 0:
                kept_waves.append(sw)
        self.shockwaves = kept_waves

        self.queue_draw()
        return True

    def _trigger_shockwave(self, x, y, max_r=55):
        if len(self.shockwaves) < 3:
            self.shockwaves.append({
                'x': x,
                'y': y,
                'r': 8.0,
                'max_r': max_r,
                'alpha': 0.42
            })

    def _draw_pill(self, cr, x, y, w, h, r):
        r = min(r, w / 2.0, h / 2.0)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def _on_click(self, widget, event):
        if not self.kinetic_lines or not self.is_synced:
            return False

        w = self.get_allocated_width()
        h = self.get_allocated_height()

        # Constellation Mode: click directly on a star node to seek to that word!
        current_style = STYLE_ALIASES.get(self.anim_style, self.anim_style)
        if current_style == "constellation":
            active_idx = max(0, min(len(self.kinetic_lines) - 1, self.active_line_idx))
            c_layout = self._get_constellation_layout(active_idx, w, h)
            if c_layout and c_layout.get('nodes'):
                for nd in c_layout['nodes']:
                    dx = event.x - nd['x']
                    dy = event.y - nd['y']
                    if math.sqrt(dx * dx + dy * dy) <= 38.0:
                        w_obj = c_layout['words'][nd['idx']]
                        if self.on_seek_cb:
                            self.on_seek_cb(max(0.0, w_obj['start'] - 0.05))
                        return True

        center_y = h * 0.48

        if event.y < center_y - 45:
            target_idx = max(0, self.active_line_idx - 1)
        elif event.y > center_y + 45:
            target_idx = min(len(self.kinetic_lines) - 1, self.active_line_idx + 1)
        else:
            target_idx = self.active_line_idx

        if 0 <= target_idx < len(self.kinetic_lines):
            target_time = self.kinetic_lines[target_idx]['start']
            if self.on_seek_cb:
                self.on_seek_cb(max(0.0, target_time - 0.05))
            return True
        return False

    def _on_scroll(self, widget, event):
        if not self.kinetic_lines:
            return False
        self.user_scrolling = True
        delta = 1.0 if event.direction == Gdk.ScrollDirection.DOWN else -1.0
        self.active_line_idx = max(0, min(len(self.kinetic_lines) - 1, int(self.smooth_line_idx + delta)))
        self.smooth_line_idx = float(self.active_line_idx)
        self.queue_draw()

        if self.snap_back_timer:
            GLib.source_remove(self.snap_back_timer)
        self.snap_back_timer = GLib.timeout_add(2500, self._snap_back_to_active)
        return True

    def _snap_back_to_active(self):
        self.user_scrolling = False
        self.snap_back_timer = None
        return False

    def _draw_hud_toast(self, cr, w, r_acc, g_acc, b_acc):
        if time.time() < self.hud_toast_timer and self.hud_toast_text:
            fade = min(1.0, max(0.0, (self.hud_toast_timer - time.time()) / 0.4))
            self._ensure_layouts()
            self.layout_toast.set_text(self.hud_toast_text, -1)
            hw, hh = self.layout_toast.get_pixel_size()
            toast_pad_x = 16.0
            toast_pad_y = 6.0
            toast_w = hw + (toast_pad_x * 2.0)
            toast_h = hh + (toast_pad_y * 2.0)
            toast_x = (w - toast_w) / 2.0
            toast_y = 18.0

            cr.set_source_rgba(0.06, 0.10, 0.16, 0.88 * fade)
            self._draw_pill(cr, toast_x, toast_y, toast_w, toast_h, toast_h / 2.0)
            cr.fill_preserve()
            cr.set_source_rgba(r_acc, g_acc, b_acc, 0.45 * fade)
            cr.set_line_width(1.0)
            cr.stroke()

            cr.set_source_rgba(1.0, 1.0, 1.0, 0.95 * fade)
            cr.move_to(toast_x + toast_pad_x, toast_y + toast_pad_y)
            PangoCairo.show_layout(cr, self.layout_toast)

    def _on_draw(self, widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()

        if w <= 10 or h <= 10:
            return False

        self._ensure_layouts()
        r_acc, g_acc, b_acc = [c / 255.0 for c in self.primary_accent]
        s_r, s_g, s_b = [c / 255.0 for c in getattr(self, "secondary_accent", (200, 160, 180))]

        # Derive ambient text tint from album cover art primary palette
        tint_r = min(1.0, 0.60 + 0.40 * r_acc)
        tint_g = min(1.0, 0.60 + 0.40 * g_acc)
        tint_b = min(1.0, 0.60 + 0.40 * b_acc)

        # 1. Ambient Particles
        for p in self.particles:
            px = p['x'] * w
            py = p['y'] * h
            cr.set_source_rgba(r_acc, g_acc, b_acc, p['alpha'])
            cr.arc(px, py, p['r'], 0, 2 * math.pi)
            cr.fill()

        # 2. Expanding Shockwave Rings (skip in constellation mode to keep cosmos clean)
        current_style = STYLE_ALIASES.get(getattr(self, "anim_style", "apple_sing"), getattr(self, "anim_style", "apple_sing"))
        if current_style != "constellation":
            for sw in self.shockwaves:
                cr.set_source_rgba(r_acc, g_acc, b_acc, sw['alpha'])
                cr.set_line_width(1.8)
                cr.arc(sw['x'], sw['y'], sw['r'], 0, 2 * math.pi)
                cr.stroke()

        center_y = h * 0.48
        cur_t = self._get_smooth_time() + self.latency_offset

        # 3. Live Audio Reactive Beat / Vocal Energy (Cava)
        bars = self.cava.get_bars() if self.cava else [3.0] * 10
        vocal_energy = sum(bars[3:7]) / 4.0
        norm_vocal = max(0.0, min(1.0, (vocal_energy - 3.0) / 13.0))
        beat_energy = max(0.0, min(1.0, (sum(bars[0:3]) / 3.0 - 3.0) / 13.0))
        energy = max(0.05, (norm_vocal * 0.75) + (beat_energy * 0.25))

        # Empty / Instrumental State
        if not self.kinetic_lines and not self.raw_lines:
            desc = Pango.FontDescription('Google Sans Flex Bold 18')
            self.layout_ctx.set_font_description(desc)
            self.layout_ctx.set_alignment(Pango.Alignment.CENTER)
            self.layout_ctx.set_width(int((w - 48.0) * Pango.SCALE))
            self.layout_ctx.set_text('󰎆  Instrumental or lyrics unavailable', -1)
            lw, lh = self.layout_ctx.get_pixel_size()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.40)
            cr.move_to((w - lw) / 2.0, center_y - (lh / 2.0))
            PangoCairo.show_layout(cr, self.layout_ctx)
            return False

        # Unsynced fallback
        if not self.is_synced:
            desc = Pango.FontDescription('Google Sans Flex Bold 18')
            self.layout_ctx.set_font_description(desc)
            self.layout_ctx.set_alignment(Pango.Alignment.CENTER)
            self.layout_ctx.set_width(int((w - 48.0) * Pango.SCALE))
            y = 40.0
            for _, txt in self.raw_lines[:15]:
                self.layout_ctx.set_text(txt, -1)
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.65)
                cr.move_to(24.0, y)
                PangoCairo.show_layout(cr, self.layout_ctx)
                _, lh = self.layout_ctx.get_pixel_size()
                y += lh + 18.0
            return False

        # Check if song is in Intro phase (before first lyric line begins)
        first_line = self.kinetic_lines[0]
        if cur_t < first_line['start']:
            num_pill_bars = 5
            pill_w = 4.0
            pill_gap = 6.0
            start_bx = (w / 2.0) - ((num_pill_bars * (pill_w + pill_gap) - pill_gap) / 2.0)
            for b_i in range(num_pill_bars):
                frac = b_i / max(1, num_pill_bars - 1)
                bar_r = r_acc * (1.0 - frac) + s_r * frac
                bar_g = g_acc * (1.0 - frac) + s_g * frac
                bar_b = b_acc * (1.0 - frac) + s_b * frac
                bar_h = 6.0 + (bars[b_i * 2] / 16.0) * 28.0
                bx = start_bx + b_i * (pill_w + pill_gap)
                by = center_y - 22.0 - (bar_h / 2.0)
                cr.set_source_rgba(bar_r, bar_g, bar_b, 0.45 + (bars[b_i * 2] / 16.0) * 0.45)
                self._draw_pill(cr, bx, by, pill_w, bar_h, 2.0)
                cr.fill()

            desc = Pango.FontDescription('Google Sans Flex Bold 15')
            self.layout_ctx.set_font_description(desc)
            self.layout_ctx.set_alignment(Pango.Alignment.CENTER)
            self.layout_ctx.set_width(int((w - 48.0) * Pango.SCALE))
            self.layout_ctx.set_text("󰎆  Intro", -1)
            cr.set_source_rgba(tint_r, tint_g, tint_b, 0.55)
            cr.move_to(24.0, center_y + 4.0)
            PangoCairo.show_layout(cr, self.layout_ctx)

            # Preview upcoming first line in subtle dimmed text tinted with album palette
            desc_first = Pango.FontDescription('Google Sans Flex Bold 17')
            self.layout_ctx.set_font_description(desc_first)
            self.layout_ctx.set_alignment(Pango.Alignment.CENTER)
            self.layout_ctx.set_width(int((w - 48.0) * Pango.SCALE))
            self.layout_ctx.set_text(first_line['text'], -1)
            cr.set_source_rgba(tint_r, tint_g, tint_b, 0.35)
            cr.move_to(24.0, center_y + 36.0)
            PangoCairo.show_layout(cr, self.layout_ctx)

            self._draw_hud_toast(cr, w, r_acc, g_acc, b_acc)
            return False

        active_idx = max(0, min(len(self.kinetic_lines) - 1, self.active_line_idx))
        active_line = self.kinetic_lines[active_idx]

        active_w_idx = -1
        for w_i, w_obj in enumerate(active_line.get('words', [])):
            if cur_t >= w_obj['start']:
                active_w_idx = w_i
            else:
                break

        current_style = STYLE_ALIASES.get(getattr(self, "anim_style", "apple_sing"), getattr(self, "anim_style", "apple_sing"))

        # =====================================================================
        # MODE 1: CELESTIAL CONSTELLATION STAR MAP (Organic Criss-Cross Asterisms)
        # =====================================================================
        if current_style == "constellation":
            # If line is finished, all words are visible in completed constellation state
            is_line_ended = (cur_t > active_line['end'])
            # Only trigger extended pause if gap is huge (> 4.5s)
            is_huge_pause = is_line_ended and (cur_t < active_line['start'] + active_line.get('gap', 0.0) - 0.5) and (active_line.get('gap', 0.0) > 4.5)
            if is_huge_pause:
                if active_idx + 1 < len(self.kinetic_lines):
                    next_layout_data = self._get_line_layout(active_idx + 1, w)
                    if next_layout_data and 'context_layout' in next_layout_data:
                        cr.set_source_rgba(tint_r, tint_g, tint_b, 0.28)
                        cr.move_to(24.0, center_y + 42.0)
                        PangoCairo.show_layout(cr, next_layout_data['context_layout'])
                self._draw_hud_toast(cr, w, r_acc, g_acc, b_acc)
                return False

            c_layout = self._get_constellation_layout(active_idx, w, h)
            if c_layout and c_layout.get('nodes'):
                nodes = c_layout['nodes']
                c_words = c_layout['words']
                total_w = len(c_words)

                # Determine effective active word index
                if is_line_ended:
                    eff_active_w = total_w - 1
                else:
                    eff_active_w = active_w_idx

                # If line hasn't started yet, do not reveal future points early
                if eff_active_w < 0:
                    self._draw_hud_toast(cr, w, r_acc, g_acc, b_acc)
                    return False

                # Number of currently visible nodes: only up to eff_active_w!
                # Upcoming points/paths are strictly hidden until their word arrives
                visible_count = min(total_w, eff_active_w + 1)

                # -------------------------------------------------------------
                # 1. Constellation Connecting Lines (FIRST - lines drawn behind)
                # -------------------------------------------------------------
                for i in range(eff_active_w):
                    x0, y0 = nodes[i]['x'], nodes[i]['y']
                    x1, y1 = nodes[i + 1]['x'], nodes[i + 1]['y']
                    if i < eff_active_w - 1 or is_line_ended:
                        # Completed past line segment
                        cr.set_source_rgba(r_acc, g_acc, b_acc, 0.68)
                        cr.set_line_width(1.6)
                        cr.move_to(x0, y0)
                        cr.line_to(x1, y1)
                        cr.stroke()
                    elif i == eff_active_w - 1:
                        # Dynamic live starlight connection shooting to newly appearing point
                        w_obj = c_words[eff_active_w]
                        elapsed = max(0.0, cur_t - w_obj['start'])
                        w_dur = max(0.10, w_obj['duration'])
                        shoot_dur = min(0.35, max(0.12, w_dur * 0.85))
                        draw_frac = min(1.0, elapsed / shoot_dur)
                        cur_x = x0 + (x1 - x0) * draw_frac
                        cur_y = y0 + (y1 - y0) * draw_frac
                        cr.set_source_rgba(r_acc, g_acc, b_acc, 0.95)
                        cr.set_line_width(1.8)
                        cr.move_to(x0, y0)
                        cr.line_to(cur_x, cur_y)
                        cr.stroke()

                # -------------------------------------------------------------
                # 2. Diamond Stars (SECOND - drawn ON TOP of lines, overlapping)
                # -------------------------------------------------------------
                for i in range(visible_count):
                    cx, cy = nodes[i]['x'], nodes[i]['y']
                    is_active = (i == eff_active_w and not is_line_ended)

                    if is_active:
                        w_obj = c_words[i]
                        elapsed = max(0.0, cur_t - w_obj['start'])
                        w_dur_safe = max(0.08, w_obj['duration'])
                        pop_dur = max(0.20, min(0.40, w_dur_safe * 0.85))
                        p_norm = min(1.0, elapsed / pop_dur)
                        spring = math.sin(p_norm * math.pi) * ((1.0 - p_norm) ** 0.5)

                        scale_star = 1.0 + (0.35 + energy * 0.20) * spring
                        scale_text = 1.0 + (0.12 + energy * 0.10) * spring

                        # Outer delicate diamond ring
                        cr.set_line_width(1.3)
                        cr.set_source_rgba(r_acc, g_acc, b_acc, 0.55 * (1.0 - 0.2 * p_norm))
                        self._draw_diamond_star(cr, cx, cy, 24.0 * scale_star, 8.0 * scale_star)
                        cr.stroke()

                        # Core solid star
                        cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                        self._draw_diamond_star(cr, cx, cy, 12.0 * scale_star, 4.0 * scale_star)
                        cr.fill()

                        # Cross starlight rays (clean, razor sharp)
                        ray_len = (28.0 + energy * 6.0) * scale_star
                        cr.set_source_rgba(r_acc, g_acc, b_acc, 0.75)
                        cr.set_line_width(1.0)
                        cr.move_to(cx - ray_len, cy); cr.line_to(cx + ray_len, cy)
                        cr.move_to(cx, cy - ray_len); cr.line_to(cx, cy + ray_len)
                        cr.stroke()

                    else:
                        # Past solid diamond star (crisp node)
                        cr.set_source_rgba(r_acc, g_acc, b_acc, 0.85)
                        self._draw_diamond_star(cr, cx, cy, 7.5, 2.5)
                        cr.fill()

                # -------------------------------------------------------------
                # 3. Words (THIRD - drawn ON TOP of lines and stars, overlapping)
                # -------------------------------------------------------------
                for i in range(visible_count):
                    cx, cy = nodes[i]['x'], nodes[i]['y']
                    pos_above = nodes[i].get('pos_above', cy >= (h * 0.49))
                    is_active = (i == eff_active_w and not is_line_ended)

                    if is_active:
                        w_obj = c_words[i]
                        elapsed = max(0.0, cur_t - w_obj['start'])
                        w_dur_safe = max(0.08, w_obj['duration'])
                        pop_dur = max(0.20, min(0.40, w_dur_safe * 0.85))
                        p_norm = min(1.0, elapsed / pop_dur)
                        spring = math.sin(p_norm * math.pi) * ((1.0 - p_norm) ** 0.5)
                        scale_text = 1.0 + (0.12 + energy * 0.10) * spring

                        # Active word typography (30pt bold pure white) - Cached layout
                        la = nodes[i]['layout_act']
                        tw = nodes[i]['twa']
                        th = nodes[i]['tha']

                        text_x = cx - (tw / 2.0)
                        text_x = max(24.0, min(w - tw - 24.0, text_x))
                        text_y = cy - th - 20.0 if pos_above else cy + 24.0
                        text_y = max(12.0, min(h - th - 12.0, text_y))

                        cr.save()
                        cr.translate(cx, text_y + (th / 2.0))
                        cr.scale(scale_text, scale_text)
                        cr.translate(-cx, -(text_y + (th / 2.0)))
                        cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                        cr.move_to(text_x, text_y)
                        PangoCairo.show_layout(cr, la)
                        cr.restore()

                    else:
                        # Past word typography (15pt Google Sans Flex Medium) - Cached layout
                        lp = nodes[i]['layout_past']
                        tw = nodes[i]['twp']
                        th = nodes[i]['thp']

                        text_x = cx - (tw / 2.0)
                        text_x = max(20.0, min(w - tw - 20.0, text_x))
                        text_y = cy - th - 16.0 if pos_above else cy + 18.0
                        text_y = max(10.0, min(h - th - 10.0, text_y))

                        cr.set_source_rgba(0.92, 0.90, 0.88, 0.82)
                        cr.move_to(text_x, text_y)
                        PangoCairo.show_layout(cr, lp)

                self._draw_hud_toast(cr, w, r_acc, g_acc, b_acc)
                return False

        # =====================================================================
        # MODE 2-6: MULTI-LINE KINETIC TYPOGRAPHY (Apple Sing, Impact, etc.)
        # =====================================================================
        layout_data = self._get_line_layout(active_idx, w)
        if not layout_data:
            return False

        is_rap = layout_data['is_rap']
        total_hero_h = layout_data['total_h']
        line_offset = (self.smooth_line_idx - float(active_idx)) * 48.0
        hero_start_y = center_y - (total_hero_h / 2.0) - line_offset
        hero_end_y = hero_start_y + total_hero_h

        # Directional motion blur during line scroll transition
        scroll_diff = float(active_idx) - self.smooth_line_idx
        blur_v = max(-8.0, min(8.0, scroll_diff * 12.0))
        has_motion_blur = abs(blur_v) > 0.5

        # Instrumental pause between lines
        is_paused = (cur_t > active_line['end'] + 0.35) and (cur_t < active_line['start'] + active_line['gap'] - 0.2)
        if is_paused:
            num_pill_bars = 5
            pill_w = 4.0
            pill_gap = 6.0
            start_bx = (w / 2.0) - ((num_pill_bars * (pill_w + pill_gap) - pill_gap) / 2.0)
            for b_i in range(num_pill_bars):
                frac = b_i / max(1, num_pill_bars - 1)
                bar_r = r_acc * (1.0 - frac) + s_r * frac
                bar_g = g_acc * (1.0 - frac) + s_g * frac
                bar_b = b_acc * (1.0 - frac) + s_b * frac
                v_h = 6.0 + (bars[b_i * 2] / 16.0) * 26.0
                bx = start_bx + b_i * (pill_w + pill_gap)
                by = center_y - (v_h / 2.0)
                cr.set_source_rgba(bar_r, bar_g, bar_b, 0.40 + (bars[b_i * 2] / 16.0) * 0.45)
                self._draw_pill(cr, bx, by, pill_w, v_h, 2.0)
                cr.fill()

            if active_idx + 1 < len(self.kinetic_lines):
                next_layout_data = self._get_line_layout(active_idx + 1, w)
                if next_layout_data and 'context_layout' in next_layout_data:
                    cr.set_source_rgba(tint_r, tint_g, tint_b, 0.28)
                    cr.move_to(24.0, center_y + 42.0)
                    PangoCairo.show_layout(cr, next_layout_data['context_layout'])

            self._draw_hud_toast(cr, w, r_acc, g_acc, b_acc)
            return False

        # ---------------------------------------------------------------------
        # Context Framing: Previous Line (Guaranteed clearance ABOVE hero)
        # ---------------------------------------------------------------------
        if active_idx > 0:
            prev_layout_data = self._get_line_layout(active_idx - 1, w)
            if prev_layout_data and 'context_layout' in prev_layout_data:
                prev_l = prev_layout_data['context_layout']
                prev_h = prev_layout_data['context_h']
                prev_y = hero_start_y - prev_h - 22.0
                if prev_y > 10:
                    prev_alpha = min(0.38, max(0.06, (prev_y - 10.0) / 40.0 * 0.38))
                    if has_motion_blur:
                        cr.set_source_rgba(r_acc, g_acc, b_acc, prev_alpha * 0.40)
                        cr.move_to(24.0, prev_y - blur_v * 0.5)
                        PangoCairo.show_layout(cr, prev_l)
                    cr.set_source_rgba(tint_r, tint_g, tint_b, prev_alpha)
                    cr.move_to(24.0, prev_y)
                    PangoCairo.show_layout(cr, prev_l)

        for r in layout_data['rows']:
            for mw in r['words']:
                w_idx = mw['idx']
                w_start = mw['start']
                w_dur = max(0.06, mw['duration'])
                word_x = mw['x']
                word_y = hero_start_y + mw['y']
                cx_word = mw['cx']
                cy_word = hero_start_y + mw['cy']

                if w_idx == active_w_idx:
                    elapsed = max(0.0, cur_t - w_start)
                    w_dur_safe = max(0.08, w_dur)
                    pop_dur = max(0.18, min(0.38, w_dur_safe * 0.85))
                    p_norm = min(1.0, elapsed / pop_dur)
                    vocal_p = min(1.0, elapsed / w_dur_safe)

                    # 1. Apple Sing Fluid Wipe (Progressive syllable clip)
                    if current_style == "apple_sing":
                        pulse = math.sin(vocal_p * math.pi)
                        scale = 1.0 + (0.06 + energy * 0.05) * pulse
                        lift = 2.0 * pulse

                        cr.save()
                        cr.translate(cx_word, cy_word - lift)
                        cr.scale(scale, scale)
                        cr.translate(-cx_word, -(cy_word - lift))
                        draw_x = cx_word - (mw['pw'] / 2.0)
                        draw_y = (cy_word - lift) - (mw['ph'] / 2.0)

                        # Dimmed base in album tint
                        cr.set_source_rgba(tint_r, tint_g, tint_b, 0.38)
                        cr.move_to(draw_x, draw_y)
                        PangoCairo.show_layout(cr, mw['layout'])

                        # Fluid progressive syllable clip mask
                        cr.save()
                        clip_w = mw['pw'] * max(0.08, vocal_p)
                        cr.rectangle(draw_x - 1.0, draw_y - 2.0, clip_w + 2.0, mw['ph'] + 4.0)
                        cr.clip()
                        cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                        cr.move_to(draw_x, draw_y)
                        PangoCairo.show_layout(cr, mw['layout'])
                        cr.restore()

                        cr.restore()

                    # 2. Impact Bounce (Elastic Overshoot & Speed Shards)
                    elif current_style == "impact_bounce":
                        spring = math.sin(p_norm * math.pi) * ((1.0 - p_norm) ** 0.5)
                        scale = 1.0 + (0.24 + energy * 0.18) * spring
                        lift = (5.0 + energy * 4.0) * spring
                        tilt = ((w_idx % 2) * 2 - 1) * 0.035 * spring

                        if spring > 0.08:
                            for trail_frac, trail_alpha, trail_col in [
                                (0.48, 0.36, (r_acc, g_acc, b_acc)),
                                (0.82, 0.20, (s_r, s_g, s_b))
                            ]:
                                t_lift = lift * (1.0 - trail_frac)
                                t_scale = 1.0 + (scale - 1.0) * (1.0 - trail_frac * 0.4)
                                cr.save()
                                cr.translate(cx_word, cy_word - t_lift)
                                cr.scale(t_scale, t_scale)
                                cr.rotate(tilt * (1.0 - trail_frac))
                                cr.translate(-cx_word, -(cy_word - t_lift))
                                cr.set_source_rgba(trail_col[0], trail_col[1], trail_col[2], trail_alpha * spring)
                                cr.move_to(cx_word - (mw['pw'] / 2.0), (cy_word - t_lift) - (mw['ph'] / 2.0))
                                PangoCairo.show_layout(cr, mw['layout'])
                                cr.restore()

                        cr.save()
                        cr.translate(cx_word, cy_word - lift)
                        cr.scale(scale, scale)
                        cr.rotate(tilt)
                        cr.translate(-cx_word, -(cy_word - lift))
                        draw_x = cx_word - (mw['pw'] / 2.0)
                        draw_y = (cy_word - lift) - (mw['ph'] / 2.0)

                        cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                        cr.move_to(draw_x, draw_y)
                        PangoCairo.show_layout(cr, mw['layout'])
                        cr.restore()

                    # 3. Rolling Flip (3D Perspective Squish & Roll)
                    elif current_style == "rolling_flip":
                        flip_p = min(1.0, elapsed / pop_dur)
                        sy = math.cos(flip_p * math.pi * 0.5)
                        sx = 1.0 + 0.08 * (1.0 - flip_p)
                        lift = 3.5 * (1.0 - flip_p)

                        cr.save()
                        cr.translate(cx_word, cy_word - lift)
                        cr.scale(sx, max(0.12, abs(sy)))
                        cr.translate(-cx_word, -(cy_word - lift))
                        draw_x = cx_word - (mw['pw'] / 2.0)
                        draw_y = (cy_word - lift) - (mw['ph'] / 2.0)

                        if flip_p < 0.8:
                            cr.set_source_rgba(s_r, s_g, s_b, 0.40 * (1.0 - flip_p))
                            cr.move_to(draw_x + 2.0, draw_y + 2.5)
                            PangoCairo.show_layout(cr, mw['layout'])

                        cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                        cr.move_to(draw_x, draw_y)
                        PangoCairo.show_layout(cr, mw['layout'])
                        cr.restore()

                    # 4. Minimal Wave (Sinusoidal Silk Float & Luminescence)
                    elif current_style == "minimal_wave":
                        wave = math.sin(vocal_p * math.pi)
                        lift = (4.5 + energy * 3.0) * wave
                        scale = 1.0 + (0.08 + energy * 0.06) * wave

                        cr.save()
                        cr.translate(cx_word, cy_word - lift)
                        cr.scale(scale, scale)
                        cr.translate(-cx_word, -(cy_word - lift))
                        draw_x = cx_word - (mw['pw'] / 2.0)
                        draw_y = (cy_word - lift) - (mw['ph'] / 2.0)

                        col_r = r_acc + (1.0 - r_acc) * vocal_p
                        col_g = g_acc + (1.0 - g_acc) * vocal_p
                        col_b = b_acc + (1.0 - b_acc) * vocal_p
                        cr.set_source_rgba(col_r, col_g, col_b, 1.0)
                        cr.move_to(draw_x, draw_y)
                        PangoCairo.show_layout(cr, mw['layout'])
                        cr.restore()

                    # 5. Cyber Glitch (Chromatic Prism Split)
                    elif current_style == "glitch_flicker":
                        snap = (1.0 - p_norm) ** 1.6
                        scale = 1.0 + (0.22 + energy * 0.20) * snap
                        lift = 3.0 * snap
                        glitch_dx = (((w_idx * 7) % 5) - 2) * 2.0 * snap

                        cr.save()
                        cr.translate(cx_word + glitch_dx, cy_word - lift)
                        cr.scale(scale, scale)
                        cr.translate(-(cx_word + glitch_dx), -(cy_word - lift))
                        draw_x = (cx_word + glitch_dx) - (mw['pw'] / 2.0)
                        draw_y = (cy_word - lift) - (mw['ph'] / 2.0)

                        if snap > 0.06:
                            chroma = (3.5 + energy * 4.0) * snap
                            cr.set_source_rgba(r_acc, g_acc, b_acc, 0.60 * snap)
                            cr.move_to(draw_x - chroma, draw_y)
                            PangoCairo.show_layout(cr, mw['layout'])

                            cr.set_source_rgba(s_r, s_g, s_b, 0.60 * snap)
                            cr.move_to(draw_x + chroma, draw_y)
                            PangoCairo.show_layout(cr, mw['layout'])

                        cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                        cr.move_to(draw_x, draw_y)
                        PangoCairo.show_layout(cr, mw['layout'])
                        cr.restore()

                    else:
                        cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                        cr.move_to(word_x, word_y)
                        PangoCairo.show_layout(cr, mw['layout'])

                elif w_idx < active_w_idx:
                    cr.set_source_rgba(1.0, 1.0, 1.0, 0.88)
                    cr.move_to(word_x, word_y)
                    PangoCairo.show_layout(cr, mw['layout'])

                else:
                    cr.set_source_rgba(tint_r, tint_g, tint_b, 0.28)
                    cr.move_to(word_x, word_y)
                    PangoCairo.show_layout(cr, mw['layout'])

        # Context Framing: Next Line
        if active_idx + 1 < len(self.kinetic_lines):
            next_layout_data = self._get_line_layout(active_idx + 1, w)
            if next_layout_data and 'context_layout' in next_layout_data:
                next_l = next_layout_data['context_layout']
                next_y = hero_end_y + 22.0
                if next_y < h - 10:
                    next_alpha = min(0.32, max(0.06, (h - 10.0 - next_y) / 40.0 * 0.32))
                    if has_motion_blur:
                        cr.set_source_rgba(r_acc, g_acc, b_acc, next_alpha * 0.40)
                        cr.move_to(24.0, next_y - blur_v * 0.5)
                        PangoCairo.show_layout(cr, next_l)
                    cr.set_source_rgba(tint_r, tint_g, tint_b, next_alpha)
                    cr.move_to(24.0, next_y)
                    PangoCairo.show_layout(cr, next_l)

        self._draw_hud_toast(cr, w, r_acc, g_acc, b_acc)
        return False


# Main Zenify Application Window
# ==============================================================================
class StarkifyApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Zenify")
        self.set_role("zenify")
        self.set_default_size(1020, 660)
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
            self.lyrics_canvas.set_palette(p_rgb, s_rgb)
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
        player_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        player_root.get_style_context().add_class("stark-apple-container")

        body_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body_box.set_hexpand(True)
        body_box.set_vexpand(True)

        # ---------------------------------------------------------------------
        # Left Column: Cover Art, Metadata, Slim Scrubber, Minimal Controls
        # ---------------------------------------------------------------------
        self.left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.left_col.get_style_context().add_class("stark-showcase-left")
        self.left_col.set_valign(Gtk.Align.CENTER)
        body_box.pack_start(self.left_col, False, False, 0)

        # Square Artwork Showcase (240x240 - compact for max lyrics expansion)
        art_frame = Gtk.Box()
        art_frame.get_style_context().add_class("stark-showcase-art-frame")
        self.showcase_art_img = Gtk.Image()
        self.showcase_art_img.set_size_request(240, 240)
        art_frame.pack_start(self.showcase_art_img, True, True, 0)
        self.left_col.pack_start(art_frame, False, False, 0)

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

        self.left_col.pack_start(meta_row, False, False, 0)

        # Slim Progress Scrubber
        self.showcase_scrubber = AppleMusicScrubber(on_seek_cb=self._on_seek, height=14)
        self.left_col.pack_start(self.showcase_scrubber, False, False, 0)

        # Scrubber Timestamps: Elapsed (left), Remaining (right)
        time_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.showcase_time_elapsed = Gtk.Label(label="0:00")
        self.showcase_time_elapsed.get_style_context().add_class("stark-scrubber-time")
        time_row.pack_start(self.showcase_time_elapsed, False, False, 0)

        time_row.pack_start(Gtk.Box(), True, True, 0)

        self.showcase_time_remaining = Gtk.Label(label="-0:00")
        self.showcase_time_remaining.get_style_context().add_class("stark-scrubber-time")
        time_row.pack_end(self.showcase_time_remaining, False, False, 0)
        self.left_col.pack_start(time_row, False, False, 0)

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

        self.left_col.pack_start(ctrl_deck, False, False, 0)

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
        self.left_col.pack_start(vol_box, False, False, 0)

        # ---------------------------------------------------------------------
        # Right Column: 60FPS Kinetic Typography Edit Canvas & Style Selector
        # ---------------------------------------------------------------------
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        right_box.get_style_context().add_class("stark-kinetic-lyrics-box")
        body_box.pack_start(right_box, True, True, 0)

        # Sleek Top Toolbar with Preset Animation Menu
        lyrics_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lyrics_toolbar.get_style_context().add_class("stark-lyrics-toolbar")
        lyrics_toolbar.set_margin_top(6)
        lyrics_toolbar.set_margin_bottom(2)
        lyrics_toolbar.set_margin_end(14)

        tag_lbl = Gtk.Label(label="󰎆  LYRICS")
        tag_lbl.get_style_context().add_class("stark-lyrics-tag")
        lyrics_toolbar.pack_start(tag_lbl, False, False, 14)

        spacer = Gtk.Box()
        lyrics_toolbar.pack_start(spacer, True, True, 0)

        # Style Menu Button
        self.btn_anim_style = Gtk.MenuButton()
        self.btn_anim_style.get_style_context().add_class("stark-lyrics-style-btn")
        raw_saved = self.player.state.get("anim_style", "apple_sing")
        saved_style = STYLE_ALIASES.get(raw_saved, raw_saved)
        if saved_style not in ANIMATION_STYLES:
            saved_style = "apple_sing"
        initial_info = ANIMATION_STYLES[saved_style]
        self.btn_anim_style.set_label(f"{initial_info['icon']}  {initial_info['name']}")

        style_menu = Gtk.Menu()
        style_menu.get_style_context().add_class("stark-style-menu")
        for sk, sd in ANIMATION_STYLES.items():
            mi = Gtk.MenuItem(label=f"{sd['icon']}  {sd['name']}  —  {sd['desc']}")
            mi.connect("activate", lambda w, k=sk: self._on_select_anim_style(k))
            style_menu.append(mi)
        style_menu.show_all()
        self.btn_anim_style.set_popup(style_menu)
        lyrics_toolbar.pack_end(self.btn_anim_style, False, False, 0)

        right_box.pack_start(lyrics_toolbar, False, False, 0)

        self.lyrics_canvas = CinematicLyricsCanvas(on_seek_cb=self._on_seek)
        self.lyrics_canvas.anim_style = saved_style
        right_box.pack_start(self.lyrics_canvas, True, True, 0)

        player_root.pack_start(body_box, True, True, 0)

        # Minimalist Bottom Player Bar for Constellation Mode (Sides the big image, gives large canvas)
        self.constellation_bottom_bar = self._build_constellation_bottom_bar()
        self.constellation_bottom_bar.show_all()
        self.constellation_bottom_bar.set_no_show_all(True)
        player_root.pack_end(self.constellation_bottom_bar, False, False, 0)

        self.left_col.show_all()
        self.left_col.set_no_show_all(True)

        # Initial visibility: if constellation mode, hide left_col and show bottom bar
        is_constellation = (saved_style == "constellation")
        self.left_col.set_visible(not is_constellation)
        self.constellation_bottom_bar.set_visible(is_constellation)

        return player_root

    def _build_constellation_bottom_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        bar.get_style_context().add_class("stark-constellation-bar")
        bar.set_margin_start(16)
        bar.set_margin_end(16)
        bar.set_margin_bottom(12)
        bar.set_margin_top(4)

        # 1. Left: Mini Cover Art + Title & Artist
        left_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        left_box.set_size_request(240, -1)

        art_frame = Gtk.Box()
        art_frame.get_style_context().add_class("stark-docked-art-frame")
        self.constellation_art_img = Gtk.Image()
        self.constellation_art_img.set_size_request(38, 38)
        art_frame.pack_start(self.constellation_art_img, False, False, 0)
        left_box.pack_start(art_frame, False, False, 0)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_valign(Gtk.Align.CENTER)
        self.constellation_title_lbl = Gtk.Label(label=self.player.state.get("title", "Ready to Play"))
        self.constellation_title_lbl.set_xalign(0.0)
        self.constellation_title_lbl.set_ellipsize(3)
        self.constellation_title_lbl.get_style_context().add_class("stark-docked-title")
        info_box.pack_start(self.constellation_title_lbl, False, False, 0)

        self.constellation_artist_lbl = Gtk.Label(label=self.player.state.get("artist", "Zenify Audio"))
        self.constellation_artist_lbl.set_xalign(0.0)
        self.constellation_artist_lbl.set_ellipsize(3)
        self.constellation_artist_lbl.get_style_context().add_class("stark-docked-artist")
        info_box.pack_start(self.constellation_artist_lbl, False, False, 0)
        left_box.pack_start(info_box, True, True, 0)
        bar.pack_start(left_box, False, False, 0)

        # 2. Center: Minimalist Playback Controls & Slim Scrubber
        center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        center_box.set_hexpand(True)
        center_box.set_valign(Gtk.Align.CENTER)

        ctrl_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        ctrl_row.set_halign(Gtk.Align.CENTER)

        btn_prev = Gtk.Button(label=GLYPHS["prev"])
        btn_prev.get_style_context().add_class("stark-playback-btn")
        btn_prev.connect("clicked", lambda w: self.player.play_prev())
        ctrl_row.pack_start(btn_prev, False, False, 0)

        self.constellation_btn_play = Gtk.Button(label=GLYPHS["play"])
        self.constellation_btn_play.get_style_context().add_class("stark-playback-main-btn")
        self.constellation_btn_play.connect("clicked", lambda w: self.player.toggle_play())
        ctrl_row.pack_start(self.constellation_btn_play, False, False, 0)

        btn_next = Gtk.Button(label=GLYPHS["next"])
        btn_next.get_style_context().add_class("stark-playback-btn")
        btn_next.connect("clicked", lambda w: self.player.play_next())
        ctrl_row.pack_start(btn_next, False, False, 0)
        center_box.pack_start(ctrl_row, False, False, 0)

        # Scrubber Row with Times
        scrub_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.constellation_time_elapsed = Gtk.Label(label="0:00")
        self.constellation_time_elapsed.get_style_context().add_class("stark-scrubber-time")
        scrub_row.pack_start(self.constellation_time_elapsed, False, False, 0)

        self.constellation_scrubber = AppleMusicScrubber(on_seek_cb=self._on_seek, height=10)
        scrub_row.pack_start(self.constellation_scrubber, True, True, 0)

        self.constellation_time_remaining = Gtk.Label(label="-0:00")
        self.constellation_time_remaining.get_style_context().add_class("stark-scrubber-time")
        scrub_row.pack_end(self.constellation_time_remaining, False, False, 0)
        center_box.pack_start(scrub_row, False, False, 0)

        bar.pack_start(center_box, True, True, 0)

        # 3. Right: Volume Slider
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        right_box.set_size_request(180, -1)
        right_box.set_halign(Gtk.Align.END)
        right_box.set_valign(Gtk.Align.CENTER)

        v_icon = Gtk.Label(label=GLYPHS["volume"])
        v_icon.get_style_context().add_class("stark-vol-icon")
        right_box.pack_start(v_icon, False, False, 0)

        vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        vol_scale.set_value(self.player.state.get("volume", 80))
        vol_scale.set_draw_value(False)
        vol_scale.set_hexpand(True)
        vol_scale.connect("value-changed", self._on_volume_changed)
        right_box.pack_start(vol_scale, True, True, 0)

        bar.pack_end(right_box, False, False, 0)
        return bar

    def _on_select_anim_style(self, style_key):
        style_key = STYLE_ALIASES.get(style_key, style_key)
        if style_key not in ANIMATION_STYLES:
            return
        sd = ANIMATION_STYLES[style_key]
        self.lyrics_canvas.set_anim_style(style_key)
        self.btn_anim_style.set_label(f"{sd['icon']}  {sd['name']}")

        # Large space for Constellation mode: side the big image, show bottom controls
        is_constellation = (style_key == "constellation")
        if hasattr(self, 'left_col'):
            self.left_col.set_visible(not is_constellation)
        if hasattr(self, 'constellation_bottom_bar'):
            self.constellation_bottom_bar.set_visible(is_constellation)

        try:
            self.player.state["anim_style"] = style_key
            self.player._save_state()
        except Exception:
            pass

    def _cycle_anim_style(self):
        keys = list(ANIMATION_STYLES.keys())
        cur = getattr(self.lyrics_canvas, "anim_style", "constellation")
        cur = STYLE_ALIASES.get(cur, cur)
        idx = (keys.index(cur) + 1) % len(keys) if cur in keys else 0
        self._on_select_anim_style(keys[idx])

    # =========================================================================
    # Synced Lyrics Loading
    # =========================================================================
    def _load_lyrics_for_track(self, title, artist, duration=0):
        key = f"{title}_{artist}"
        if key == self._last_loaded_track_key:
            return
        self._last_loaded_track_key = key

        def _worker():
            lines, is_synced, raw_text, words = fetch_lyrics(title, artist, duration)
            GLib.idle_add(self.lyrics_canvas.set_lyrics, lines, is_synced, raw_text, words)

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
        if dur > 0:
            prog = min(1.0, max(0.0, target_sec / dur))
            self.showcase_scrubber.set_progress(prog)
            self.docked_scrubber.set_progress(prog)
            if hasattr(self, 'constellation_scrubber'):
                self.constellation_scrubber.set_progress(prog)
            elapsed_str = format_duration(target_sec)
            remaining_str = format_remaining(dur, target_sec)
            self.showcase_time_elapsed.set_label(elapsed_str)
            self.showcase_time_remaining.set_label(remaining_str)
            self.docked_cur_time.set_label(elapsed_str)
            if hasattr(self, 'constellation_time_elapsed'):
                self.constellation_time_elapsed.set_label(elapsed_str)
                self.constellation_time_remaining.set_label(remaining_str)
        if hasattr(self, 'lyrics_canvas'):
            self.lyrics_canvas.update_position(target_sec, self.player.state.get("is_playing", False))

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
            engine = self.player.history_mgr.rec_engine
            tracks = engine.fetch_collaborative_similar("Travis Scott", limit=8)
            tracks += engine.fetch_collaborative_similar("The Weeknd", limit=8)
        elif cat_key == "hiphop":
            engine = self.player.history_mgr.rec_engine
            tracks = engine.fetch_lastfm_top_tracks("Travis Scott", limit=8)
            tracks += engine.fetch_lastfm_top_tracks("Metro Boomin", limit=6)
        elif cat_key == "phonk":
            engine = self.player.history_mgr.rec_engine
            tracks = engine.fetch_tag_top_tracks("phonk", limit=8)
            tracks += engine.fetch_tag_top_tracks("ambient", limit=6)
        elif cat_key == "rnb":
            engine = self.player.history_mgr.rec_engine
            tracks = engine.fetch_lastfm_top_tracks("The Weeknd", limit=8)
            tracks += engine.fetch_lastfm_top_tracks("Frank Ocean", limit=6)
        elif cat_key == "cinematic":
            engine = self.player.history_mgr.rec_engine
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
        if tracks and isinstance(tracks[0], dict):
            first_t = tracks[0]
            self._load_art_image(first_t.get("art_url", ""), self.banner_art_img, size=88,
                                title=first_t.get("title", ""), artist=first_t.get("artist", ""))

        cur_title = self.player.state.get("title", "").lower()

        for idx, track in enumerate(tracks, start=1):
            if not isinstance(track, dict):
                continue
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
            self._load_art_image(track.get("art_url", ""), thumb_img, size=40,
                                title=track.get("title", ""), artist=track.get("artist", ""))
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

            if dur <= 0 and track.get("title") and track.get("artist"):
                def _fetch_dur(d_lbl_ref, trk):
                    meta = StarkPlayerBackend.resolve_track_metadata(trk.get("title", ""), trk.get("artist", ""))
                    if meta:
                        new_dur = meta.get("duration", 0)
                        if new_dur > 0:
                            trk["duration"] = new_dur
                            GLib.idle_add(d_lbl_ref.set_label, format_duration(new_dur))
                        if meta.get("art_url") and ("2a96cbd8" in trk.get("art_url", "") or not trk.get("art_url")):
                            trk["art_url"] = meta["art_url"]
                threading.Thread(target=_fetch_dur, args=(d_lbl, track), daemon=True).start()

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
    def _load_art_image(self, art_url, gtk_image, size=40, title="", artist=""):
        def _worker():
            resolved_url = art_url
            if not resolved_url or "2a96cbd8" in resolved_url:
                if title and artist:
                    meta = StarkPlayerBackend.resolve_track_metadata(title, artist)
                    if meta and meta.get("art_url"):
                        resolved_url = meta["art_url"]

            cache_file = None
            if resolved_url and "2a96cbd8" not in resolved_url:
                fn = hashlib.md5(resolved_url.encode("utf-8")).hexdigest() + f"_{size}.jpg"
                p = os.path.join(THUMB_CACHE_DIR, fn)
                if os.path.exists(p) and os.path.getsize(p) > 300:
                    cache_file = p
                else:
                    try:
                        req = urllib.request.Request(resolved_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=4.0) as resp, open(p, "wb") as f:
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

        # 1. Update Title & Artist Labels (only if changed to avoid unnecessary GTK layout passes)
        if self.is_visible():
            if self.showcase_title_lbl.get_label() != title:
                self.showcase_title_lbl.set_label(title)
                self.docked_title_lbl.set_label(title)
                if hasattr(self, 'constellation_title_lbl'):
                    self.constellation_title_lbl.set_label(title)
            if self.showcase_artist_lbl.get_label() != artist:
                self.showcase_artist_lbl.set_label(artist)
                self.docked_artist_lbl.set_label(artist)
                if hasattr(self, 'constellation_artist_lbl'):
                    self.constellation_artist_lbl.set_label(artist)

            ticker_text = f"Now Playing: {title} • {artist}"
            if self.header_ticker_lbl.get_label() != ticker_text:
                self.header_ticker_lbl.set_label(ticker_text)

            # 2. Update Play/Pause Buttons
            glyph = GLYPHS["pause"] if is_playing else GLYPHS["play"]
            if self.btn_showcase_play.get_label() != glyph:
                self.btn_showcase_play.set_label(glyph)
                self.btn_docked_play.set_label(glyph)
                if hasattr(self, 'constellation_btn_play'):
                    self.constellation_btn_play.set_label(glyph)

            # 3. Update Progress Scrubber & Times
            self.showcase_scrubber.set_progress(prog)
            self.docked_scrubber.set_progress(prog)
            if hasattr(self, 'constellation_scrubber'):
                self.constellation_scrubber.set_progress(prog)

            elapsed_str = format_duration(pos)
            remaining_str = format_remaining(dur, pos) if dur > 0 else "-0:00"
            if self.showcase_time_elapsed.get_label() != elapsed_str:
                self.showcase_time_elapsed.set_label(elapsed_str)
                self.docked_cur_time.set_label(elapsed_str)
                if hasattr(self, 'constellation_time_elapsed'):
                    self.constellation_time_elapsed.set_label(elapsed_str)

            if self.showcase_time_remaining.get_label() != remaining_str:
                self.showcase_time_remaining.set_label(remaining_str)
                if hasattr(self, 'constellation_time_remaining'):
                    self.constellation_time_remaining.set_label(remaining_str)

            dur_str = format_duration(dur)
            if self.docked_total_time.get_label() != dur_str:
                self.docked_total_time.set_label(dur_str)

        # 4. Cover Art & Mesh Palette Sync
        is_dummy = (not art_path or "075f428c" in art_path or "2a96cbd8" in art_path or not os.path.exists(art_path))
        if is_dummy and title not in ("Ready to Play", "Nothing Playing") and artist:
            if not getattr(self, "_resolving_current_art", False):
                self._resolving_current_art = True
                def _bg_resolve_current(cur_t, cur_a):
                    try:
                        meta = StarkPlayerBackend.resolve_track_metadata(cur_t, cur_a)
                        if meta and meta.get("art_url") and "2a96cbd8" not in meta["art_url"]:
                            new_url = meta["art_url"]
                            fn = hashlib.md5(new_url.encode("utf-8")).hexdigest() + ".jpg"
                            p = os.path.join(THUMB_CACHE_DIR, fn)
                            if not os.path.exists(p) or os.path.getsize(p) < 300:
                                try:
                                    r = requests.get(new_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4.0)
                                    if r.status_code == 200 and len(r.content) > 300:
                                        with open(p, "wb") as f:
                                            f.write(r.content)
                                except Exception:
                                    pass
                            if os.path.exists(p) and os.path.getsize(p) > 300:
                                self.player.state["art_path"] = p
                                self.player.state["art_url"] = new_url
                                self._last_synced_art = p
                                GLib.idle_add(self._sync_art_and_palette, p)
                    finally:
                        self._resolving_current_art = False
                threading.Thread(target=_bg_resolve_current, args=(title, artist), daemon=True).start()

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
        self.lyrics_canvas.update_position(pos, is_playing)

        return True

    def _sync_art_and_palette(self, art_path):
        if not art_path or not os.path.exists(art_path) or "075f428c" in art_path or "2a96cbd8" in art_path:
            art_path = os.path.join(ASSETS_DIR, "after_dark.png")

        def _worker():
            try:
                p_rgb, s_rgb = extract_art_palette(art_path)
                GLib.idle_add(self._update_dynamic_gradient, p_rgb, s_rgb)
            except Exception as e:
                print(f"[Palette Sync] Error extracting palette: {e}")

            try:
                # Left Showcase Artwork (240x240 - compact for max lyrics expansion)
                pb_showcase = GdkPixbuf.Pixbuf.new_from_file_at_scale(art_path, 240, 240, False)
                GLib.idle_add(self.showcase_art_img.set_from_pixbuf, pb_showcase)

                # Bottom Docked Artwork (44x44)
                pb_mini = GdkPixbuf.Pixbuf.new_from_file_at_scale(art_path, 44, 44, False)
                GLib.idle_add(self.docked_art_img.set_from_pixbuf, pb_mini)

                # Constellation Bottom Bar Artwork (38x38)
                if hasattr(self, 'constellation_art_img'):
                    pb_con = GdkPixbuf.Pixbuf.new_from_file_at_scale(art_path, 38, 38, False)
                    GLib.idle_add(self.constellation_art_img.set_from_pixbuf, pb_con)
            except Exception as e:
                print(f"[Art Sync] Error loading pixbuf: {e}")

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
        # Lyric Sync Offset Nudge: [ / ] (coarse 0.5s), { / } (fine 0.1s), 0 (reset)
        elif val in (Gdk.KEY_bracketleft, Gdk.KEY_braceleft):
            if not isinstance(self.get_focus(), Gtk.Entry):
                delta = -0.1 if val == Gdk.KEY_braceleft else -0.5
                self.lyrics_canvas.nudge_offset(delta)
                return True
        elif val in (Gdk.KEY_bracketright, Gdk.KEY_braceright):
            if not isinstance(self.get_focus(), Gtk.Entry):
                delta = 0.1 if val == Gdk.KEY_braceright else 0.5
                self.lyrics_canvas.nudge_offset(delta)
                return True
        elif val == Gdk.KEY_0:
            if not isinstance(self.get_focus(), Gtk.Entry):
                self.lyrics_canvas.reset_offset()
                return True
        # Cycle Lyric Animation Preset: S / s
        elif val in (Gdk.KEY_s, Gdk.KEY_S):
            if not isinstance(self.get_focus(), Gtk.Entry):
                self._cycle_anim_style()
                return True
        return False

    def _hide_or_quit(self):
        self.lyrics_canvas.pause_cava()
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
                    elif data == "show":
                        GLib.idle_add(self._show_window)
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
                    elif data.startswith("nudge "):
                        try:
                            delta = float(data.split(" ", 1)[1])
                            GLib.idle_add(self.lyrics_canvas.nudge_offset, delta)
                        except Exception:
                            pass
                    elif data == "reset_offset":
                        GLib.idle_add(self.lyrics_canvas.reset_offset)
                    elif data.startswith("style "):
                        s_name = data.split(" ", 1)[1].strip()
                        GLib.idle_add(self._on_select_anim_style, s_name)
                    elif data in ("cycle_style", "next_style"):
                        GLib.idle_add(self._cycle_anim_style)
                    elif data.startswith("seek "):
                        try:
                            pos = float(data.split(" ", 1)[1])
                            GLib.idle_add(self.player.seek, pos)
                        except Exception:
                            pass
                    elif data.startswith("play_track "):
                        try:
                            parts = data.split(" ", 1)[1].split("|")
                            t_title = parts[0]
                            t_artist = parts[1] if len(parts) > 1 else ""
                            t_art = parts[2] if len(parts) > 2 else ""
                            t_yt = parts[3] if len(parts) > 3 else ""
                            GLib.idle_add(self._on_play_track, {"title": t_title, "artist": t_artist, "art_url": t_art, "yt_id": t_yt})
                        except Exception:
                            pass
                    conn.close()
                except Exception:
                    pass

        threading.Thread(target=server_loop, daemon=True).start()

    def _toggle_visibility(self):
        if self.is_visible():
            self.lyrics_canvas.pause_cava()
            self.hide()
        else:
            self.show()
            self.lyrics_canvas.resume_cava()
            # Ensure correct visibility according to active preset
            saved_style = getattr(self.lyrics_canvas, "anim_style", "apple_sing")
            is_con = (saved_style == "constellation")
            if hasattr(self, "constellation_bottom_bar"):
                self.constellation_bottom_bar.set_visible(is_con)
            if hasattr(self, "left_col"):
                self.left_col.set_visible(not is_con)
            self.present()
            self.lyrics_canvas.queue_draw()

    def _show_window(self):
        if not self.is_visible():
            self._toggle_visibility()
        else:
            self.present()


LOCK_FILE = "/tmp/stark_spotify.lock"
_lock_fd = None


def acquire_single_instance_lock():
    global _lock_fd
    try:
        import fcntl
        _lock_fd = open(LOCK_FILE, "a+")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (IOError, OSError):
        return False


def send_ipc_command(cmd="toggle"):
    if os.path.exists(UI_SOCKET):
        for _ in range(5):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(0.6)
                s.connect(UI_SOCKET)
                s.sendall(f"{cmd}\n".encode("utf-8"))
                s.close()
                return True
            except Exception:
                time.sleep(0.06)
    return False


def main():
    is_toggle = ("--toggle" in sys.argv)

    if not acquire_single_instance_lock():
        cmd = "toggle" if is_toggle else "show"
        send_ipc_command(cmd)
        sys.exit(0)

    import atexit, signal
    app = StarkifyApp()

    def _cleanup_handler(*args):
        try:
            app.lyrics_canvas.cleanup()
        except Exception:
            pass
        if os.path.exists(UI_SOCKET):
            try:
                os.remove(UI_SOCKET)
            except Exception:
                pass
        sys.exit(0)

    atexit.register(_cleanup_handler)
    signal.signal(signal.SIGINT, _cleanup_handler)
    signal.signal(signal.SIGTERM, _cleanup_handler)

    app.show_all()
    # Explicitly enforce constellation visibility after initial show_all
    saved_style = getattr(app.lyrics_canvas, "anim_style", "apple_sing")
    is_con = (saved_style == "constellation")
    if hasattr(app, "constellation_bottom_bar"):
        app.constellation_bottom_bar.set_visible(is_con)
    if hasattr(app, "left_col"):
        app.left_col.set_visible(not is_con)
    app.present()
    Gtk.main()


if __name__ == "__main__":
    main()
