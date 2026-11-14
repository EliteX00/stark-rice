#!/usr/bin/env python3
"""
J.A.R.V.I.S. Tony Stark Level Neural HUD Panel
Persona: J.A.R.V.I.S. (Tony Stark's British AI Assistant)
Brain: NVIDIA NIM (Nemotron 3.5 Bolt)
Voice: Deepgram Aura-2 (aura-2-pluto-en)
Window Class: jarvis-hud (880x560 floating Hyprland HUD)
"""

import os
import sys
import math
import time
import json
import glob
import threading
import subprocess
import urllib.request
import re
import cairo
import warnings
warnings.filterwarnings("ignore")

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

# Import backend methods from jarvis_chat
DIR = os.path.dirname(os.path.abspath(__file__))
if DIR not in sys.path:
    sys.path.insert(0, DIR)

try:
    from jarvis_chat import (
        query_jarvis,
        speak_text,
        execute_action,
        get_telemetry,
        get_boot_greeting,
        load_config,
    )
except ImportError:
    # Fallback placeholders if imported outside
    def query_jarvis(q, h): return f"Stark system online, Sir. Acknowledged: '{q}'", None
    def speak_text(t, wait=False): pass
    def execute_action(a): pass
    def get_telemetry(): return "Telemetry Nominal"
    def get_boot_greeting(): return "Good morning, Sir. All Stark systems operational."
    def load_config(): return {}


# ==============================================================================
# CAIRO HELPER FUNCTIONS
# ==============================================================================
def draw_rounded_rect(cr, x, y, w, h, r):
    cr.new_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


# ==============================================================================
# 1. ANIMATED ARC REACTOR CORE HOLOGRAPHIC WIDGET
# ==============================================================================
class ArcReactorCore(Gtk.DrawingArea):
    """Animated Arc Reactor with rotating notched rings and dynamic voice harmonic waves."""
    def __init__(self, width=410, height=92):
        super().__init__()
        self.set_size_request(width, height)
        self.angle_outer = 0.0
        self.angle_inner = 0.0
        self.pulse = 0.0
        self.state = "IDLE"  # "IDLE", "THINKING", "SPEAKING"
        self.wave_phase = 0.0
        self.connect("draw", self.on_draw)

    def tick(self):
        speed_mult = 2.8 if self.state == "THINKING" else (1.8 if self.state == "SPEAKING" else 1.0)
        self.angle_outer -= 0.012 * speed_mult
        self.angle_inner += 0.022 * speed_mult
        self.wave_phase += 0.08 * speed_mult
        self.pulse = (math.sin(self.wave_phase * 1.5) + 1.0) / 2.0
        self.queue_draw()

    def set_state(self, new_state):
        self.state = new_state
        self.queue_draw()

    def on_draw(self, widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        cx = w / 2.0
        cy = h / 2.0 - 6.0

        # Background Subtle Glow Field
        bg_grad = cairo.RadialGradient(cx, cy, 0, cx, cy, 140)
        bg_grad.add_color_stop_rgba(0.0, 0.0, 0.75, 1.0, 0.08 + 0.06 * self.pulse)
        bg_grad.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, 0.0)
        cr.set_source(bg_grad)
        cr.arc(cx, cy, 140, 0, 2 * math.pi)
        cr.fill()

        # Outer Segmented Laser Ring (radius 36)
        cr.set_source_rgba(0.0, 0.85, 1.0, 0.35 + 0.15 * self.pulse)
        cr.set_line_width(1.2)
        cr.arc(cx, cy, 36, 0, 2 * math.pi)
        cr.stroke()

        # 24 Laser Ticks on Outer Ring
        for i in range(24):
            ang = i * (2 * math.pi / 24) + self.angle_outer
            r1 = 37.0
            r2 = 41.0 if (i % 6 == 0) else 39.5
            x1 = cx + math.cos(ang) * r1
            y1 = cy + math.sin(ang) * r1
            x2 = cx + math.cos(ang) * r2
            y2 = cy + math.sin(ang) * r2
            cr.set_line_width(1.8 if (i % 6 == 0) else 1.0)
            cr.set_source_rgba(0.0, 0.95, 1.0, 0.85 if (i % 6 == 0) else 0.45)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

        # Inner Rotating Segmented Chevrons (radius 26)
        for j in range(8):
            a1 = j * (2 * math.pi / 8) + self.angle_inner
            a2 = a1 + (math.pi / 7)
            cr.arc(cx, cy, 26, a1, a2)
            cr.set_source_rgba(0.2, 0.75, 1.0, 0.70 + 0.20 * self.pulse)
            cr.set_line_width(2.2)
            cr.stroke()

        # Arc Reactor Core Plasma (radius 18)
        core_grad = cairo.RadialGradient(cx, cy, 0, cx, cy, 20)
        core_grad.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.98)
        core_grad.add_color_stop_rgba(0.35, 0.0, 0.90, 1.0, 0.85)
        core_grad.add_color_stop_rgba(0.80, 0.0, 0.45, 0.95, 0.30)
        core_grad.add_color_stop_rgba(1.0, 0.0, 0.15, 0.35, 0.0)
        cr.set_source(core_grad)
        cr.arc(cx, cy, 20, 0, 2 * math.pi)
        cr.fill()

        # Voice / Harmonic Waveform Ribbons extending left & right
        wave_amp = 16.0 if self.state == "SPEAKING" else (12.0 if self.state == "THINKING" else 6.0)
        for direction, start_x in [(-1, cx - 52), (1, cx + 52)]:
            cr.save()
            cr.set_source_rgba(0.0, 0.85, 1.0, 0.75)
            cr.set_line_width(1.3)
            cr.move_to(start_x, cy)
            num_steps = 18
            for k in range(1, num_steps + 1):
                wx = start_x + direction * (k * 7.5)
                decay = math.exp(-k * 0.09)
                wy = cy + math.sin(k * 0.45 + self.wave_phase) * (wave_amp * decay)
                cr.line_to(wx, wy)
            cr.stroke()
            cr.restore()

        # HUD Core Monospace Label Below
        state_text = "SYNCED" if self.state == "IDLE" else self.state
        state_col = (0.0, 0.85, 1.0) if self.state == "IDLE" else ((0.95, 0.75, 0.2) if self.state == "THINKING" else (0.75, 0.5, 1.0))
        cr.select_font_face("JetBrainsMono Nerd Font", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(8.5)
        text_str = f"J.A.R.V.I.S. NEURAL CORE  •  NEMOTRON 3.5  •  [{state_text}]"
        ext = cr.text_extents(text_str)
        cr.set_source_rgba(state_col[0], state_col[1], state_col[2], 0.85)
        cr.move_to(cx - ext.width / 2.0, h - 6.0)
        cr.show_text(text_str)

        return False


# ==============================================================================
# 2. ANIMATED TACTICAL RADAR WIDGET (3D SWEEP & BLIPS)
# ==============================================================================
class TacticalRadarWidget(Gtk.DrawingArea):
    """Animated radar reticle with continuous sweep cone and dynamic target blips."""
    def __init__(self, width=220, height=115):
        super().__init__()
        self.set_size_request(width, height)
        self.angle_radar = 0.0
        self.blips = [
            {"az": 0.75, "dist": 0.45, "alpha": 0.0},
            {"az": 2.20, "dist": 0.72, "alpha": 0.0},
            {"az": 4.10, "dist": 0.58, "alpha": 0.0},
            {"az": 5.40, "dist": 0.85, "alpha": 0.0},
        ]
        self.connect("draw", self.on_draw)

    def tick(self):
        self.angle_radar = (self.angle_radar + 0.038) % (2 * math.pi)
        # Check if radar arm passed over blips
        for b in self.blips:
            diff = abs(self.angle_radar - b["az"])
            if diff < 0.06 or diff > (2 * math.pi - 0.06):
                b["alpha"] = 1.0
            else:
                b["alpha"] = max(0.0, b["alpha"] - 0.015)
        self.queue_draw()

    def on_draw(self, widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        rx = w / 2.0
        ry = h / 2.0 - 5.0
        max_r = 46.0

        # Concentric Distance Rings
        for r in [16.0, 31.0, max_r]:
            cr.arc(rx, ry, r, 0, 2 * math.pi)
            cr.set_source_rgba(0.0, 0.85, 1.0, 0.20)
            cr.set_line_width(0.9)
            cr.stroke()

        # Crosshairs
        cr.set_source_rgba(0.0, 0.85, 1.0, 0.16)
        cr.set_line_width(0.9)
        cr.move_to(rx - max_r - 4, ry)
        cr.line_to(rx + max_r + 4, ry)
        cr.move_to(rx, ry - max_r - 4)
        cr.line_to(rx, ry + max_r + 4)
        cr.stroke()

        # Sweep Cone Gradient (sector behind sweep arm)
        sweep_spread = 0.65
        cr.save()
        cr.move_to(rx, ry)
        cr.arc(rx, ry, max_r, self.angle_radar - sweep_spread, self.angle_radar)
        cr.close_path()
        grad = cairo.RadialGradient(rx, ry, 0, rx, ry, max_r)
        grad.add_color_stop_rgba(0.0, 0.0, 0.85, 1.0, 0.32)
        grad.add_color_stop_rgba(1.0, 0.0, 0.85, 1.0, 0.04)
        cr.set_source(grad)
        cr.fill()
        cr.restore()

        # Sweep Leading Razor Line
        cr.move_to(rx, ry)
        cr.line_to(rx + math.cos(self.angle_radar) * max_r, ry + math.sin(self.angle_radar) * max_r)
        cr.set_source_rgba(0.85, 0.95, 1.0, 0.95)
        cr.set_line_width(1.3)
        cr.stroke()

        # Target Blips
        for b in self.blips:
            if b["alpha"] > 0.05:
                bx = rx + math.cos(b["az"]) * (b["dist"] * max_r)
                by = ry + math.sin(b["az"]) * (b["dist"] * max_r)
                cr.arc(bx, by, 2.2, 0, 2 * math.pi)
                cr.set_source_rgba(0.2, 0.85, 0.6, b["alpha"])
                cr.fill()

        # HUD Coordinates
        deg = int(math.degrees(self.angle_radar))
        cr.select_font_face("JetBrainsMono Nerd Font", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(7.5)
        coord_str = f"RADAR ACTIVE • HDG {deg:03d}° • RNG 14.8km"
        ext = cr.text_extents(coord_str)
        cr.set_source_rgba(0.55, 0.75, 0.9, 0.8)
        cr.move_to(rx - ext.width / 2.0, h - 3)
        cr.show_text(coord_str)

        return False


# ==============================================================================
# 3. CIRCULAR ARC HARDWARE METERS (CPU, RAM, GPU)
# ==============================================================================
class CircularHardwareGauges(Gtk.DrawingArea):
    """3 Circular gauges displaying live CPU, RAM, and GPU hardware metrics."""
    def __init__(self, width=220, height=72):
        super().__init__()
        self.set_size_request(width, height)
        self.cpu_pct = 0.22
        self.ram_pct = 0.52
        self.ram_str = "3.1G"
        self.gpu_pct = 0.12
        self.connect("draw", self.on_draw)

    def set_stats(self, cpu_pct, ram_pct, ram_str, gpu_pct):
        self.cpu_pct = max(0.04, min(1.0, cpu_pct))
        self.ram_pct = max(0.04, min(1.0, ram_pct))
        self.ram_str = ram_str
        self.gpu_pct = max(0.04, min(1.0, gpu_pct))
        self.queue_draw()

    def on_draw(self, widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()

        gauges = [
            ("CPU", f"{int(self.cpu_pct * 100)}%", self.cpu_pct, (0.0, 0.85, 1.0)),
            ("RAM", self.ram_str, self.ram_pct, (0.75, 0.50, 1.0)),
            ("GPU", f"{int(self.gpu_pct * 100)}%", self.gpu_pct, (0.22, 0.75, 0.98)),
        ]

        slot_w = w / 3.0
        rad = 18.0
        start_ang = math.pi * 0.75
        end_ang = math.pi * 2.25

        for i, (label, val_str, pct, col) in enumerate(gauges):
            mx = slot_w * i + slot_w / 2.0
            my = 26.0

            # Background Trough Arc (270 deg)
            cr.arc(mx, my, rad, start_ang, end_ang)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
            cr.set_line_width(3.0)
            cr.stroke()

            # Active Arc
            active_end = start_ang + pct * (end_ang - start_ang)
            cr.arc(mx, my, rad, start_ang, active_end)
            cr.set_source_rgba(col[0], col[1], col[2], 0.95)
            cr.set_line_width(3.0)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.stroke()

            # Center Value
            cr.select_font_face("JetBrainsMono Nerd Font", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(7.5)
            cr.set_source_rgba(0.92, 0.96, 1.0, 0.95)
            ext = cr.text_extents(val_str)
            cr.move_to(mx - ext.width / 2.0, my + 3.0)
            cr.show_text(val_str)

            # Label Below
            cr.set_font_size(8.0)
            cr.set_source_rgba(0.55, 0.65, 0.8, 0.85)
            ext_l = cr.text_extents(label)
            cr.move_to(mx - ext_l.width / 2.0, my + rad + 13.0)
            cr.show_text(label)

        return False


# ==============================================================================
# 4. MAIN J.A.R.V.I.S. HUD WINDOW
# ==============================================================================
class JarvisHudWindow(Gtk.Window):
    def __init__(self):
        super().__init__(Gtk.WindowType.TOPLEVEL)
        self.set_title("J.A.R.V.I.S. Core Console")
        self.set_wmclass("jarvis-hud", "jarvis-hud")
        self.set_name("jarvis-hud")
        self.set_default_size(880, 560)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Make window transparent for rounded Cairo obsidian glass
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.connect("draw", self.on_window_draw)

        # Allow dragging window from top bar
        self.drag_start_pos = None

        # Data & State
        self.history = []
        self.current_workspace_dir = os.path.expanduser("~/Projects")
        self.is_processing = False

        self._init_layout()
        self._init_css()

        # 30 FPS Animation Timer (Arc Reactor & Radar)
        GLib.timeout_add(33, self.anim_tick)
        # 1-second Telemetry Update Timer
        GLib.timeout_add_seconds(1, self.telemetry_tick)

        # Initial Boot Greeting
        GLib.timeout_add(350, self.boot_greeting_dispatch)

    def _init_css(self):
        css_data = b"""
        * {
            font-family: "JetBrainsMono Nerd Font", "Google Sans Flex", sans-serif;
            outline: none;
            border: none;
            text-shadow: none;
        }

        #jarvis-hud {
            background-color: transparent;
        }

        .hud-tab-btn {
            background-color: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(0, 240, 255, 0.18);
            border-radius: 6px;
            color: #94a3b8;
            font-size: 8.5px;
            font-weight: 600;
            padding: 3px 6px;
        }
        .hud-tab-btn:hover {
            background-color: rgba(0, 240, 255, 0.12);
            color: #00f0ff;
        }

        .hud-file-item {
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 5px;
            padding: 4px 8px;
            margin-bottom: 3px;
        }
        .hud-file-item:hover {
            background-color: rgba(0, 240, 255, 0.09);
            border-color: rgba(0, 240, 255, 0.25);
        }

        .jarvis-input {
            background-color: rgba(10, 16, 26, 0.70);
            border: 1px solid rgba(0, 240, 255, 0.35);
            border-radius: 18px;
            color: #e2e8f0;
            font-size: 11px;
            padding: 8px 16px;
        }
        .jarvis-input:focus {
            border: 1px solid #00f0ff;
            background-color: rgba(10, 20, 35, 0.90);
        }

        .hud-chip-btn {
            background-color: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(0, 240, 255, 0.22);
            border-radius: 11px;
            color: #cbd5e1;
            font-size: 8.5px;
            font-weight: 500;
            padding: 3px 8px;
        }
        .hud-chip-btn:hover {
            background-color: rgba(0, 240, 255, 0.18);
            border-color: #00f0ff;
            color: #ffffff;
        }

        .hud-close-btn {
            background: transparent;
            color: #94a3b8;
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 4px;
        }
        .hud-close-btn:hover {
            color: #f87171;
            background-color: rgba(248, 113, 113, 0.15);
        }

        /* Custom Scrollbar */
        scrollbar trough {
            background: transparent;
        }
        scrollbar slider {
            background-color: rgba(0, 240, 255, 0.25);
            border-radius: 3px;
            min-width: 4px;
        }
        scrollbar slider:hover {
            background-color: rgba(0, 240, 255, 0.60);
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css_data)
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _init_layout(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(12)
        main_box.set_margin_left(16)
        main_box.set_margin_right(16)

        # ----------------- TITLEBAR -----------------
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        title_lbl = Gtk.Label(label="// STARK INDUSTRIES NEURAL INTERFACE // J.A.R.V.I.S. CORE v4.8")
        title_lbl.set_xalign(0.0)
        title_lbl.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.0, 0.9, 1.0, 0.9))
        title_box.pack_start(title_lbl, True, True, 4)

        # Status Pills
        for text, col_rgba in [
            ("ONLINE ●", (0.2, 0.85, 0.6, 0.95)),
            ("NEMOTRON-3.5", (0.0, 0.85, 1.0, 0.95)),
            ("AURA-PLUTO", (0.75, 0.50, 1.0, 0.95)),
            ("T4 READY", (0.22, 0.75, 0.98, 0.95))
        ]:
            plbl = Gtk.Label(label=text)
            plbl.set_margin_left(4)
            plbl.set_margin_right(4)
            plbl.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(*col_rgba))
            plbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font 8.5"))
            title_box.pack_start(plbl, False, False, 2)

        # Close Button
        close_btn = Gtk.Button(label="✕")
        close_btn.get_style_context().add_class("hud-close-btn")
        close_btn.connect("clicked", lambda b: self.destroy())
        title_box.pack_end(close_btn, False, False, 2)

        main_box.pack_start(title_box, False, False, 6)

        # ----------------- 3-COLUMN BODY -----------------
        cols_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)

        # 1. LEFT COLUMN: WORKSPACE FILE NAVIGATOR (225px)
        self.left_box = self._create_left_column()
        cols_box.pack_start(self.left_box, False, False, 0)

        # 2. CENTER COLUMN: ARC REACTOR & CHAT STREAM (425px)
        self.center_box = self._create_center_column()
        cols_box.pack_start(self.center_box, True, True, 0)

        # 3. RIGHT COLUMN: TACTICAL RADAR & TELEMETRY (210px)
        self.right_box = self._create_right_column()
        cols_box.pack_start(self.right_box, False, False, 0)

        main_box.pack_start(cols_box, True, True, 4)
        self.add(main_box)

    # ----------------- COLUMN 1: LEFT NAVIGATOR -----------------
    def _create_left_column(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        col.set_size_request(225, -1)

        # Header
        hlbl = Gtk.Label(label="// WORKSPACE DIRECTORY")
        hlbl.set_xalign(0.0)
        hlbl.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.55, 0.65, 0.8, 0.9))
        hlbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font Bold 9"))
        col.pack_start(hlbl, False, False, 0)

        # Quick Switch Tabs
        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for label, path in [
            ("Projects", "~/Projects"),
            ("Rice", "~/.config/stark-rice"),
            ("Hypr", "~/.config/hypr"),
            ("Bin", "~/.local/bin"),
        ]:
            b = Gtk.Button(label=label)
            b.get_style_context().add_class("hud-tab-btn")
            b.connect("clicked", lambda btn, p=path: self._switch_directory(p))
            tab_box.pack_start(b, True, True, 0)
        col.pack_start(tab_box, False, False, 2)

        # Path Breadcrumb
        self.path_lbl = Gtk.Label(label="~/Projects")
        self.path_lbl.set_xalign(0.0)
        self.path_lbl.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.0, 0.85, 1.0, 0.85))
        self.path_lbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font 8.5"))
        col.pack_start(self.path_lbl, False, False, 2)

        # File List ScrolledWindow
        self.file_scroll = Gtk.ScrolledWindow()
        self.file_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.file_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.file_scroll.add(self.file_list_box)
        col.pack_start(self.file_scroll, True, True, 2)

        # Bottom Info Bar
        self.dir_stats_lbl = Gtk.Label(label="Scanning directory...")
        self.dir_stats_lbl.set_xalign(0.0)
        self.dir_stats_lbl.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.45, 0.55, 0.7, 0.8))
        self.dir_stats_lbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font 8"))
        col.pack_start(self.dir_stats_lbl, False, False, 2)

        # Load initial files
        self._populate_file_list(self.current_workspace_dir)
        return col

    def _switch_directory(self, target_path):
        resolved = os.path.expanduser(target_path)
        if os.path.isdir(resolved):
            self.current_workspace_dir = resolved
            self.path_lbl.set_text(target_path)
            self._populate_file_list(resolved)

    def _populate_file_list(self, folder):
        for child in self.file_list_box.get_children():
            self.file_list_box.remove(child)

        try:
            entries = os.listdir(folder)
            entries = sorted(entries, key=lambda s: (not os.path.isdir(os.path.join(folder, s)), s.lower()))
            total_size = 0
            count = 0

            for name in entries:
                if name.startswith(".") and name not in (".config", ".local"):
                    continue
                full_path = os.path.join(folder, name)
                is_dir = os.path.isdir(full_path)
                
                # Icon & Color
                if is_dir:
                    icon = ""
                    col = Gdk.RGBA(0.22, 0.75, 0.98, 0.95)
                    size_str = "DIR"
                elif name.endswith(".py"):
                    icon = ""
                    col = Gdk.RGBA(0.0, 0.85, 1.0, 0.95)
                    sz = os.path.getsize(full_path) / 1024.0
                    total_size += sz
                    size_str = f"{sz:.1f}K"
                elif name.endswith(".sh"):
                    icon = ""
                    col = Gdk.RGBA(0.2, 0.85, 0.6, 0.95)
                    sz = os.path.getsize(full_path) / 1024.0
                    total_size += sz
                    size_str = f"{sz:.1f}K"
                elif name.endswith(".json"):
                    icon = "󰈙"
                    col = Gdk.RGBA(0.95, 0.75, 0.25, 0.95)
                    sz = os.path.getsize(full_path) / 1024.0
                    total_size += sz
                    size_str = f"{sz:.1f}K"
                elif name.endswith(".css"):
                    icon = ""
                    col = Gdk.RGBA(0.75, 0.50, 1.0, 0.95)
                    sz = os.path.getsize(full_path) / 1024.0
                    total_size += sz
                    size_str = f"{sz:.1f}K"
                else:
                    icon = "󰈔"
                    col = Gdk.RGBA(0.65, 0.75, 0.85, 0.85)
                    sz = os.path.getsize(full_path) / 1024.0 if os.path.exists(full_path) else 0
                    total_size += sz
                    size_str = f"{sz:.1f}K"

                count += 1
                item_btn = Gtk.Button()
                item_btn.get_style_context().add_class("hud-file-item")
                
                ibox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                ilbl = Gtk.Label(label=f"{icon}  {name[:20]}")
                ilbl.set_xalign(0.0)
                ilbl.override_color(Gtk.StateFlags.NORMAL, col)
                ilbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font 8.5"))
                
                slbl = Gtk.Label(label=size_str)
                slbl.set_xalign(1.0)
                slbl.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.45, 0.55, 0.65, 0.8))
                slbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font 8"))
                
                ibox.pack_start(ilbl, True, True, 0)
                ibox.pack_end(slbl, False, False, 0)
                item_btn.add(ibox)

                # Click handler: open folder or log file click
                if is_dir:
                    item_btn.connect("clicked", lambda b, p=full_path: self._switch_directory(p))
                else:
                    item_btn.connect("clicked", lambda b, fn=name: self._log_event("FILE", f"Inspected: {fn}"))

                self.file_list_box.pack_start(item_btn, False, False, 0)

            self.file_list_box.show_all()
            self.dir_stats_lbl.set_text(f"{count} items • {total_size:.1f} KB in workspace")
        except Exception as e:
            self.dir_stats_lbl.set_text(f"Error scanning: {e}")

    # ----------------- COLUMN 2: CENTER NEURAL CONSOLE -----------------
    def _create_center_column(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        # Top: Arc Reactor Core
        self.arc_reactor = ArcReactorCore(width=410, height=88)
        col.pack_start(self.arc_reactor, False, False, 0)

        # Middle: Conversation Feed
        self.chat_scroll = Gtk.ScrolledWindow()
        self.chat_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.chat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.chat_scroll.add(self.chat_box)
        col.pack_start(self.chat_scroll, True, True, 2)

        # Bottom: Input Box
        input_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Ask J.A.R.V.I.S. or command system...")
        self.entry.get_style_context().add_class("jarvis-input")
        self.entry.connect("activate", self.on_input_submitted)
        input_box.pack_start(self.entry, False, False, 0)

        # Quick Action Chips
        chips_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chips = [
            ("󰔏 Telemetry", "Show system telemetry"),
            ("󰐊 Play/Pause", "Toggle music playback"),
            ("󰒭 Next Track", "Next song"),
            ("󰕾 Volume +", "Increase volume"),
            ("󰌾 Lock", "Lock screen"),
        ]
        for label, cmd_str in chips:
            btn = Gtk.Button(label=label)
            btn.get_style_context().add_class("hud-chip-btn")
            btn.connect("clicked", lambda b, c=cmd_str: self.submit_query(c))
            chips_box.pack_start(btn, True, True, 0)
        input_box.pack_start(chips_box, False, False, 0)

        col.pack_start(input_box, False, False, 2)
        return col

    # ----------------- COLUMN 3: RIGHT TELEMETRY DECK -----------------
    def _create_right_column(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        col.set_size_request(215, -1)

        # Header
        hlbl = Gtk.Label(label="// TACTICAL TELEMETRY")
        hlbl.set_xalign(0.0)
        hlbl.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.55, 0.65, 0.8, 0.9))
        hlbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font Bold 9"))
        col.pack_start(hlbl, False, False, 0)

        # Radar Reticle
        self.radar = TacticalRadarWidget(width=215, height=115)
        col.pack_start(self.radar, False, False, 2)

        # Circular Hardware Meters
        self.gauges = CircularHardwareGauges(width=215, height=68)
        col.pack_start(self.gauges, False, False, 2)

        # System Event Log Ticker Header
        log_lbl = Gtk.Label(label="// SYSTEM EVENT LOG")
        log_lbl.set_xalign(0.0)
        log_lbl.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.55, 0.65, 0.8, 0.9))
        log_lbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font Bold 9"))
        col.pack_start(log_lbl, False, False, 4)

        # Log Ticker Scroll
        self.log_scroll = Gtk.ScrolledWindow()
        self.log_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.log_scroll.add(self.log_box)
        col.pack_start(self.log_scroll, True, True, 2)

        # Initial Log Entries
        self._log_event("SYS", "Hyprland Wayland 1366x768 OK")
        self._log_event("AUD", "PipeWire sink connected")
        self._log_event("NIM", "Nemotron 3.5 Bolt Ready")
        self._log_event("TTS", "Deepgram Aura Pluto Ready")
        self._log_event("T4", "INT8 Tensor Cores Supported")

        return col

    def _log_event(self, tag, message):
        t_str = time.strftime("%H:%M:%S")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        
        tlbl = Gtk.Label(label=t_str)
        tlbl.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.4, 0.5, 0.6, 0.7))
        tlbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font 7.5"))
        
        tag_lbl = Gtk.Label(label=f"[{tag}]")
        tag_col = Gdk.RGBA(0.0, 0.85, 1.0, 0.95) if tag in ("SYS", "AUD") else Gdk.RGBA(0.2, 0.85, 0.6, 0.95)
        tag_lbl.override_color(Gtk.StateFlags.NORMAL, tag_col)
        tag_lbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font Bold 7.5"))

        mlbl = Gtk.Label(label=message[:20])
        mlbl.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.75, 0.85, 0.95, 0.85))
        mlbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font 7.5"))

        row.pack_start(tlbl, False, False, 0)
        row.pack_start(tag_lbl, False, False, 2)
        row.pack_start(mlbl, True, True, 0)
        
        self.log_box.pack_start(row, False, False, 0)
        self.log_box.show_all()
        # Auto scroll to bottom
        adj = self.log_scroll.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()))

    # ----------------- CONVERSATION STREAM LOGIC -----------------
    def add_message(self, sender, text, action=None):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        card.set_margin_left(4)
        card.set_margin_right(4)

        if sender == "Sir":
            card.get_style_context().add_class("hud-user-card")
            header_col = Gdk.RGBA(0.95, 0.75, 0.20, 0.95)
            card_bg_rgba = (0.35, 0.25, 0.05, 0.15)
            border_rgba = (0.95, 0.75, 0.20, 0.30)
        else:
            card.get_style_context().add_class("hud-jarvis-card")
            header_col = Gdk.RGBA(0.0, 0.85, 1.0, 0.95)
            card_bg_rgba = (0.0, 0.25, 0.45, 0.14)
            border_rgba = (0.0, 0.85, 1.0, 0.28)

        # Custom drawing for bubble
        def draw_bubble(widget, cr):
            w = widget.get_allocated_width()
            h = widget.get_allocated_height()
            draw_rounded_rect(cr, 1, 1, w - 2, h - 2, 8)
            cr.set_source_rgba(*card_bg_rgba)
            cr.fill()
            draw_rounded_rect(cr, 1, 1, w - 2, h - 2, 8)
            cr.set_source_rgba(*border_rgba)
            cr.set_line_width(1.0)
            cr.stroke()
            return False

        card.connect("draw", draw_bubble)

        # Header: Sender + Time
        t_str = time.strftime("%I:%M %p")
        hdr_lbl = Gtk.Label(label=f"{sender}  ›  {t_str}")
        hdr_lbl.set_xalign(0.0)
        hdr_lbl.set_margin_top(6)
        hdr_lbl.set_margin_left(10)
        hdr_lbl.override_color(Gtk.StateFlags.NORMAL, header_col)
        hdr_lbl.override_font(Pango.FontDescription("JetBrainsMono Nerd Font Bold 8.5"))
        card.pack_start(hdr_lbl, False, False, 0)

        # Body Text
        body_lbl = Gtk.Label(label=text)
        body_lbl.set_xalign(0.0)
        body_lbl.set_line_wrap(True)
        body_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        body_lbl.set_margin_left(10)
        body_lbl.set_margin_right(10)
        body_lbl.set_margin_bottom(6)
        body_lbl.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.92, 0.96, 1.0, 0.95))
        body_lbl.override_font(Pango.FontDescription("Google Sans Flex, JetBrainsMono Nerd Font 9.5"))
        card.pack_start(body_lbl, False, False, 0)

        # Optional Action Chip Badge
        if action:
            achip = Gtk.Label(label=f"󰓎 ACTION EXECUTED: {action}")
            achip.set_xalign(0.0)
            achip.set_margin_left(10)
            achip.set_margin_bottom(6)
            achip.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.2, 0.85, 0.6, 0.95))
            achip.override_font(Pango.FontDescription("JetBrainsMono Nerd Font Bold 7.5"))
            card.pack_start(achip, False, False, 0)

        self.chat_box.pack_start(card, False, False, 2)
        self.chat_box.show_all()

        # Scroll to bottom smoothly
        adj = self.chat_scroll.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()))

    def boot_greeting_dispatch(self):
        greeting = get_boot_greeting()
        self.add_message("J.A.R.V.I.S.", greeting)
        self.history.append({"role": "assistant", "content": greeting})
        threading.Thread(target=speak_text, args=(greeting, False), daemon=True).start()
        return False

    def on_input_submitted(self, entry):
        text = entry.get_text().strip()
        if not text:
            return
        entry.set_text("")
        self.submit_query(text)

    def submit_query(self, user_text):
        if self.is_processing:
            return
        self.is_processing = True
        self.add_message("Sir", user_text)
        self.history.append({"role": "user", "content": user_text})
        self.arc_reactor.set_state("THINKING")
        self._log_event("CMD", user_text[:18])

        # Background worker thread so UI 60 FPS stays perfectly smooth
        def worker():
            try:
                reply, action = query_jarvis(user_text, self.history)
            except Exception as e:
                reply = f"Apologies, Sir. Communication error: {e}"
                action = None

            GLib.idle_add(self._on_query_finished, reply, action)

        threading.Thread(target=worker, daemon=True).start()

    def _on_query_finished(self, reply, action):
        self.is_processing = False
        self.arc_reactor.set_state("SPEAKING")
        self.add_message("J.A.R.V.I.S.", reply, action)
        self.history.append({"role": "assistant", "content": reply})

        if action:
            self._log_event("ACT", action)
            execute_action(action)

        # Vocalize via Deepgram Aura in thread
        def speak_worker():
            try:
                speak_text(reply, wait=True)
            except Exception:
                pass
            GLib.idle_add(self.arc_reactor.set_state, "IDLE")

        threading.Thread(target=speak_worker, daemon=True).start()
        return False

    # ----------------- TIMERS -----------------
    def anim_tick(self):
        self.arc_reactor.tick()
        self.radar.tick()
        return True

    def telemetry_tick(self):
        # Update CPU, RAM, GPU in right column
        try:
            # 1. CPU
            cpu_pct = 0.22
            with open("/proc/loadavg", "r") as f:
                load = float(f.read().split()[0])
                cpu_pct = max(0.05, min(0.95, load / 4.0))

            # 2. RAM
            ram_pct = 0.52
            ram_str = "3.1G"
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
                tot = int(lines[0].split()[1]) / 1048576.0
                free = int(lines[1].split()[1]) / 1048576.0
                avail = int(lines[2].split()[1]) / 1048576.0 if len(lines) > 2 else free
                used = max(0.0, tot - avail)
                ram_pct = used / max(tot, 1.0)
                ram_str = f"{used:.1f}G"

            # 3. GPU
            gpu_pct = 0.12
            if os.path.exists("/sys/class/drm/card1/gt_act_freq_mhz"):
                with open("/sys/class/drm/card1/gt_act_freq_mhz", "r") as f:
                    act = float(f.read().strip())
                span = 900.0
                gpu_pct = max(0.05, min(0.95, (act - 200.0) / span))

            self.gauges.set_stats(cpu_pct, ram_pct, ram_str, gpu_pct)
        except Exception:
            pass
        return True

    # ----------------- WINDOW CHROMA & OBSIDIAN GLASS -----------------
    def on_window_draw(self, widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()

        # Obsidian Frosted Glass Core (92% tint)
        draw_rounded_rect(cr, 1, 1, w - 2, h - 2, 18)
        cr.set_source_rgba(0.03, 0.05, 0.09, 0.94)
        cr.fill()

        # Crisp Holographic Cyan Border
        draw_rounded_rect(cr, 1, 1, w - 2, h - 2, 18)
        cr.set_source_rgba(0.0, 0.85, 1.0, 0.22)
        cr.set_line_width(1.2)
        cr.stroke()

        # Header Divider
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
        cr.set_line_width(1.0)
        cr.move_to(16, 42)
        cr.line_to(w - 16, 42)
        cr.stroke()

        # Column Dividers
        cr.move_to(242, 44)
        cr.line_to(242, h - 16)
        cr.move_to(664, 44)
        cr.line_to(664, h - 16)
        cr.stroke()

        return False


# ==============================================================================
# ENTRY POINT
# ==============================================================================
def main():
    GLib.set_prgname("jarvis-hud")
    GLib.set_application_name("jarvis-hud")
    win = JarvisHudWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
