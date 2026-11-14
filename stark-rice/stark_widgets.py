#!/usr/bin/env python3
"""
Stark Rice Desktop Widgets
1:1 Pixel-Perfect Implementation matching reference image:
- Upper-Left: Typography Clock, Date & Greeting (No blur outline, pure text)
- Top-Right: System Monitor Frosted Glass Card (Waveform sparkline, CPU/RAM/GPU/Temp)
- Bottom-Left: Music Player Frosted Glass Card (After Dark / Mr.Kitty, Visualizer, Controls)
- Bottom-Right: Dual-Pane Terminal & Tony Stark Quote Frosted Glass Card
"""

import os
import sys
import time
import json
import socket
import math
import random
import subprocess
import threading
import atexit
from collections import deque

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, GtkLayerShell, Pango
import cairo

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(CONFIG_DIR, "assets")
CSS_FILE = os.path.join(CONFIG_DIR, "widgets.css")


def make_window_transparent(win):
    win.set_app_paintable(True)
    screen = win.get_screen()
    visual = screen.get_rgba_visual()
    if visual:
        win.set_visual(visual)

    def on_draw(widget, cr):
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        return False

    win.connect("draw", on_draw)


def get_rounded_pixbuf(path, size=64, radius=8):
    if not path or not os.path.exists(path):
        return None
    try:
        src = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, False)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        cr = cairo.Context(surf)
        cr.arc(size - radius, radius, radius, -math.pi / 2, 0)
        cr.arc(size - radius, size - radius, radius, 0, math.pi / 2)
        cr.arc(radius, size - radius, radius, math.pi / 2, math.pi)
        cr.arc(radius, radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, src, 0, 0)
        cr.paint()
        return Gdk.pixbuf_get_from_surface(surf, 0, 0, size, size)
    except Exception:
        return None


def draw_bezier_curve(cr, points):
    n = len(points)
    if n < 2:
        return
    cr.move_to(points[0][0], points[0][1])
    if n == 2:
        cr.line_to(points[1][0], points[1][1])
        return

    for i in range(n - 1):
        p0 = points[max(i - 1, 0)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(i + 2, n - 1)]

        cp1_x = p1[0] + (p2[0] - p0[0]) / 6.0
        cp1_y = p1[1] + (p2[1] - p0[1]) / 6.0
        cp2_x = p2[0] - (p3[0] - p1[0]) / 6.0
        cp2_y = p2[1] - (p3[1] - p1[1]) / 6.0

        cr.curve_to(cp1_x, cp1_y, cp2_x, cp2_y, p2[0], p2[1])


class GlowingSparkline(Gtk.DrawingArea):
    """Real-time Bezier sparkline with continuous 50 FPS smooth flow, zero-gap probe dot, and assembly sweep."""
    def __init__(self, color_rgb=(0.22, 0.74, 0.97), width=252, height=15):
        super().__init__()
        self.color_rgb = color_rgb
        self.width = width
        self.height = height
        self.num_intervals = 16
        # Buffer holds num_intervals + 2 points (18 points) so the line extends past w at all offsets
        self.target_points = self.num_intervals + 2
        self.data = [0.20] * self.target_points
        self.anim_progress = 1.0
        self.last_metric_time = time.time()
        self.update_interval = 1.0
        self.set_size_request(width, height)
        self.connect("draw", self.on_draw)

    def set_data(self, new_data, anim_progress=1.0):
        if len(new_data) < self.target_points:
            pad = [new_data[0]] * (self.target_points - len(new_data))
            self.data = pad + list(new_data)
        else:
            self.data = list(new_data[-self.target_points:])
        self.anim_progress = anim_progress
        self.last_metric_time = time.time()
        self.queue_draw()

    def tick_flow(self):
        """Called by 50 FPS animation loop to smoothly animate horizontal stream flow."""
        self.queue_draw()

    def on_draw(self, widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()

        n = len(self.data)
        if n < 2:
            return False

        r, g, b = self.color_rgb
        pad_top = 2
        pad_bottom = 2
        avail_h = max(h - pad_top - pad_bottom, 1)

        # Assemble sweep clipping: draws from left to right during boot
        draw_w = w * max(0.01, min(1.0, self.anim_progress))
        cr.save()
        cr.rectangle(0, 0, draw_w, h)
        cr.clip()

        # Continuous smooth scrolling offset (0.0 -> 1.0 between metric updates)
        elapsed = time.time() - self.last_metric_time
        offset = min(max(elapsed / self.update_interval, 0.0), 1.0)

        step = w / float(self.num_intervals)
        points = []
        for i, val in enumerate(self.data):
            clamped = max(0.05, min(0.95, float(val)))
            y = h - pad_bottom - (clamped * avail_h)
            x = (i - offset) * step
            points.append((x, y))

        # 1. Subtle gradient shading fill under curve
        cr.save()
        draw_bezier_curve(cr, points)
        cr.line_to(w + 30, h)
        cr.line_to(-30, h)
        cr.close_path()

        grad = cairo.LinearGradient(0, pad_top, 0, h)
        grad.add_color_stop_rgba(0.0, r, g, b, 0.32)
        grad.add_color_stop_rgba(0.5, r, g, b, 0.12)
        grad.add_color_stop_rgba(1.0, r, g, b, 0.02)
        cr.set_source(grad)
        cr.fill()
        cr.restore()

        # 2. Glowing outer stroke
        draw_bezier_curve(cr, points)
        cr.set_source_rgba(r, g, b, 0.35)
        cr.set_line_width(2.6)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke()

        # 3. Clean laser core stroke (seamlessly runs through entire span)
        draw_bezier_curve(cr, points)
        cr.set_source_rgba(0.92, 0.98, 1.0, 0.95)
        cr.set_line_width(1.1)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke()

        # 4. Terminal glowing node seamlessly centered on the curve at the right edge
        if self.anim_progress >= 0.92:
            v_prev = self.data[-2]
            v_next = self.data[-1]
            interp_v = v_prev + offset * (v_next - v_prev)
            clamped_node = max(0.05, min(0.95, float(interp_v)))
            node_y = h - pad_bottom - (clamped_node * avail_h)
            node_x = min(w - 2.0, draw_w - 2.0)

            cr.arc(node_x, node_y, 2.0, 0, 2 * math.pi)
            cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
            cr.fill()

        cr.restore()
        return False


class CavaVisualizerEngine:
    """Real-time 10-band audio spectrum analyzer powered by CAVA & PipeWire."""
    def __init__(self, num_bars=10):
        self.num_bars = num_bars
        self.raw_bars = [3.0] * num_bars
        self.is_running = True
        self.proc = None
        self._cfg_file = os.path.join(CONFIG_DIR, "cava_widget.conf")
        self._ensure_config()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _ensure_config(self):
        cfg = f"""[general]
bars = {self.num_bars}
framerate = 50
autosens = 1
sensitivity = 140
lower_cutoff_freq = 50
higher_cutoff_freq = 11000

[input]
method = pipewire
source = auto

[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 16
bar_delimiter = 59
frame_delimiter = 10
channels = mono
mono_option = average

[smoothing]
monstercat = 1
waves = 0
noise_reduction = 40
"""
        try:
            with open(self._cfg_file, "w") as f:
                f.write(cfg)
        except Exception:
            pass

    def _run_loop(self):
        while self.is_running:
            try:
                self.proc = subprocess.Popen(
                    ["cava", "-p", self._cfg_file],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1
                )
                for line in self.proc.stdout:
                    if not self.is_running:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    parts = [int(p) for p in line.split(";") if p.isdigit()]
                    if len(parts) >= self.num_bars:
                        # Map 0..16 to bar height range 3.0 .. 16.0
                        self.raw_bars = [3.0 + (min(16, max(0, v)) / 16.0) * 13.0 for v in parts[:self.num_bars]]
                if self.proc:
                    self.proc.wait()
            except Exception:
                pass
            time.sleep(1.0)

    def get_bars(self):
        return list(self.raw_bars)

    def stop(self):
        self.is_running = False
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass


class MusicWaveformBar(Gtk.DrawingArea):
    """Progress gradient line with stylized visualizer bars."""
    def __init__(self, progress=0.0, width=220, height=18):
        super().__init__()
        self.progress = progress
        self.width = width
        self.height = height
        self.bars = [3.0] * 10
        self.set_size_request(width, height)
        self.connect("draw", self.on_draw)

    def on_draw(self, widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()

        # Draw Progress Bar Line (Left side, ~65% of width)
        line_w = int(w * 0.65)
        line_y = h / 2.0
        line_h = 3.0

        # Progress background trough
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.12)
        cr.set_line_width(line_h)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(2, line_y)
        cr.line_to(line_w, line_y)
        cr.stroke()

        # Progress filled gradient (cyan -> purple)
        fill_x = max(4, int(line_w * self.progress))
        grad = cairo.LinearGradient(2, line_y, fill_x, line_y)
        grad.add_color_stop_rgba(0.0, 0.22, 0.74, 0.97, 1.0)
        grad.add_color_stop_rgba(1.0, 0.75, 0.52, 0.99, 1.0)
        cr.set_source(grad)
        cr.move_to(2, line_y)
        cr.line_to(fill_x, line_y)
        cr.stroke()

        # Draw Audio Visualizer Bars (Right side, ~30% of width)
        vis_start_x = line_w + 14
        vis_avail_w = w - vis_start_x - 4
        bar_count = len(self.bars)
        bar_w = 2.0
        bar_gap = (vis_avail_w - (bar_count * bar_w)) / max(bar_count - 1, 1)

        cr.set_source_rgba(0.88, 0.92, 0.98, 0.90)
        for i, bh in enumerate(self.bars):
            bx = vis_start_x + i * (bar_w + bar_gap)
            by1 = line_y - (bh / 2.0)
            by2 = line_y + (bh / 2.0)
            cr.move_to(bx, by1)
            cr.line_to(bx, by2)
        cr.set_line_width(bar_w)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.stroke()

        return False


# ==============================================================================
# 1. UPPER-LEFT CLOCK & GREETING WIDGET (PURE TYPOGRAPHY, NO BLUR OUTLINE)
# ==============================================================================
class StarkClockWidget(Gtk.Window):
    def __init__(self):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 48)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, 65)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_namespace(self, "stark-clock")
        make_window_transparent(self)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.get_style_context().add_class("clock-widget-box")

        self.time_lbl = Gtk.Label(label=time.strftime("%H:%M"))
        self.time_lbl.set_xalign(0.0)
        self.time_lbl.get_style_context().add_class("stark-clock-time")

        self.date_lbl = Gtk.Label(label=time.strftime("%a, %b %d"))
        self.date_lbl.set_xalign(0.0)
        self.date_lbl.get_style_context().add_class("stark-clock-date")

        self.greeting_lbl = Gtk.Label(label=self._get_greeting())
        self.greeting_lbl.set_xalign(0.0)
        self.greeting_lbl.get_style_context().add_class("stark-clock-greeting")

        vbox.pack_start(self.time_lbl, False, False, 0)
        vbox.pack_start(self.date_lbl, False, False, 0)
        vbox.pack_start(self.greeting_lbl, False, False, 0)

        self.add(vbox)

    def _get_greeting(self):
        h = time.localtime().tm_hour
        if 5 <= h < 12:
            return "Good Morning, EliteX."
        elif 12 <= h < 17:
            return "Good Afternoon, EliteX."
        elif 17 <= h < 22:
            return "Good Evening, EliteX."
        else:
            return "Good Night, EliteX."

    def update(self):
        self.time_lbl.set_text(time.strftime("%H:%M"))
        self.date_lbl.set_text(time.strftime("%a, %b %d"))
        self.greeting_lbl.set_text(self._get_greeting())


# ==============================================================================
# 2. TOP-RIGHT SYSTEM MONITOR FROSTED GLASS CARD (MINIMALIST ALL-GRAPH HUD)
# ==============================================================================
class StarkSysmonWidget(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.prev_idle = 0
        self.prev_total = 0
        
        # Live History Deques (18 points each for seamless zero-gap Bezier stream)
        self.cpu_history = deque([0.18, 0.20, 0.22, 0.25, 0.20, 0.18, 0.24, 0.28, 0.22, 0.18, 0.20, 0.22, 0.24, 0.22, 0.20, 0.22, 0.25, 0.22], maxlen=24)
        self.ram_history = deque([0.55, 0.56, 0.58, 0.60, 0.62, 0.65, 0.68, 0.69, 0.70, 0.70, 0.71, 0.70, 0.70, 0.71, 0.72, 0.71, 0.70, 0.71], maxlen=24)
        self.gpu_history = deque([0.08, 0.10, 0.12, 0.15, 0.10, 0.08, 0.14, 0.18, 0.15, 0.12, 0.10, 0.12, 0.10, 0.12, 0.14, 0.12, 0.10, 0.12], maxlen=24)
        self.temp_history = deque([0.25, 0.26, 0.26, 0.27, 0.28, 0.27, 0.26, 0.27, 0.28, 0.27, 0.26, 0.27, 0.26, 0.27, 0.28, 0.27, 0.26, 0.27], maxlen=24)
        
        self.latest_cpu = 0.22
        self.latest_ram = 3.2
        self.latest_ram_tot = 6.0
        self.latest_gpu = 0.12
        self.latest_temp = 28
        self._init_cpu()

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 48)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 28)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_namespace(self, "stark-sysmon")
        make_window_transparent(self)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.get_style_context().add_class("stark-glass-card")
        card.set_size_request(280, 195)

        # Header Box with Status Dot
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header_lbl = Gtk.Label(label="System Monitor")
        header_lbl.set_xalign(0.0)
        header_lbl.get_style_context().add_class("sysmon-header")
        header_dot = Gtk.Label(label="●")
        header_dot.get_style_context().add_class("sysmon-status-dot")
        header_box.pack_start(header_lbl, True, True, 0)
        header_box.pack_end(header_dot, False, False, 0)
        card.pack_start(header_box, False, False, 0)

        # Helper to construct a smooth glowing graph stat block
        def create_stat_block(label_text, init_val, color_rgb, color_class):
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            
            top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            lbl = Gtk.Label(label=label_text)
            lbl.set_xalign(0.0)
            lbl.get_style_context().add_class("stat-label")
            
            val = Gtk.Label(label=init_val)
            val.set_xalign(1.0)
            val.get_style_context().add_class("stat-val")
            val.get_style_context().add_class(color_class)
            
            top_row.pack_start(lbl, True, True, 0)
            top_row.pack_end(val, False, False, 0)
            vbox.pack_start(top_row, False, False, 0)
            
            spark = GlowingSparkline(color_rgb=color_rgb, width=252, height=15)
            vbox.pack_start(spark, False, False, 0)
            return vbox, val, spark

        # 1. CPU Sparkline (Cyan #00f0ff)
        self.cpu_box, self.cpu_val, self.cpu_spark = create_stat_block("CPU", "22%", (0.0, 0.85, 1.0), "stat-val-cpu")
        card.pack_start(self.cpu_box, False, False, 1)

        # 2. RAM Sparkline (Electric Violet #c084fc)
        self.ram_box, self.ram_val, self.ram_spark = create_stat_block("RAM", "3.2G / 6.0G", (0.75, 0.50, 1.0), "stat-val-ram")
        card.pack_start(self.ram_box, False, False, 1)

        # 3. GPU Sparkline (Azure Blue #38bdf8)
        self.gpu_box, self.gpu_val, self.gpu_spark = create_stat_block("GPU", "12%", (0.22, 0.75, 0.98), "stat-val-gpu")
        card.pack_start(self.gpu_box, False, False, 1)

        # 4. TEMP Sparkline (Emerald Mint #34d399)
        self.temp_box, self.temp_val, self.temp_spark = create_stat_block("TEMP", "28°C", (0.20, 0.85, 0.60), "stat-val-temp")
        card.pack_start(self.temp_box, False, False, 1)

        self.add(card)

    def _init_cpu(self):
        try:
            with open('/proc/stat', 'r') as f:
                fields = [float(x) for x in f.readline().strip().split()[1:]]
            self.prev_idle = fields[3] + fields[4]
            self.prev_total = sum(fields)
        except Exception:
            pass

    def set_anim_progress(self, progress):
        """Assembles graph curves and counts up digital readouts during boot-up."""
        p = max(0.01, min(1.0, progress))
        self.cpu_spark.set_data(list(self.cpu_history), anim_progress=p)
        self.ram_spark.set_data(list(self.ram_history), anim_progress=p)
        self.gpu_spark.set_data(list(self.gpu_history), anim_progress=p)
        self.temp_spark.set_data(list(self.temp_history), anim_progress=p)
        
        if p < 0.95:
            self.cpu_val.set_text(f"{int(self.latest_cpu * p * 100)}%")
            self.ram_val.set_text(f"{self.latest_ram * p:.1f}G / {self.latest_ram_tot:.0f}G")
            self.gpu_val.set_text(f"{int(self.latest_gpu * p * 100)}%")
            self.temp_val.set_text(f"{int(self.latest_temp * p)}°C")
        else:
            self.cpu_val.set_text(f"{int(self.latest_cpu * 100)}%")
            self.ram_val.set_text(f"{self.latest_ram:.1f}G / {self.latest_ram_tot:.0f}G")
            self.gpu_val.set_text(f"{int(self.latest_gpu * 100)}%")
            self.temp_val.set_text(f"{int(self.latest_temp)}°C")

    def update(self):
        # 1. Live CPU calculation
        try:
            with open('/proc/stat', 'r') as f:
                fields = [float(x) for x in f.readline().strip().split()[1:]]
            idle = fields[3] + fields[4]
            total = sum(fields)
            diff_idle = idle - self.prev_idle
            diff_total = total - self.prev_total
            self.prev_idle = idle
            self.prev_total = total
            if diff_total > 0:
                cpu_pct = max(0.04, min(0.98, (diff_total - diff_idle) / diff_total))
            else:
                cpu_pct = 0.20
            self.latest_cpu = cpu_pct
            self.cpu_history.append(cpu_pct)
            self.cpu_spark.set_data(list(self.cpu_history))
            self.cpu_val.set_text(f"{int(cpu_pct * 100)}%")
        except Exception:
            pass

        # 2. Live RAM calculation
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
            mem_tot = int(lines[0].split()[1]) / 1048576.0
            mem_free = int(lines[1].split()[1]) / 1048576.0
            mem_avail = int(lines[2].split()[1]) / 1048576.0 if len(lines) > 2 else mem_free
            mem_used = max(0.0, mem_tot - mem_avail)
            ram_pct = mem_used / max(mem_tot, 1.0)
            self.latest_ram = mem_used
            self.latest_ram_tot = mem_tot
            self.ram_history.append(ram_pct)
            self.ram_spark.set_data(list(self.ram_history))
            self.ram_val.set_text(f"{mem_used:.1f}G / {mem_tot:.0f}G")
        except Exception:
            pass

        # 3. Live GPU calculation
        try:
            gpu_pct = 0.12
            # Check Intel DRM frequency
            if os.path.exists('/sys/class/drm/card1/gt_act_freq_mhz'):
                with open('/sys/class/drm/card1/gt_act_freq_mhz', 'r') as f:
                    act_mhz = float(f.read().strip())
                max_mhz = 1100.0
                min_mhz = 200.0
                if os.path.exists('/sys/class/drm/card1/gt_max_freq_mhz'):
                    with open('/sys/class/drm/card1/gt_max_freq_mhz', 'r') as f:
                        max_mhz = float(f.read().strip())
                if os.path.exists('/sys/class/drm/card1/gt_min_freq_mhz'):
                    with open('/sys/class/drm/card1/gt_min_freq_mhz', 'r') as f:
                        min_mhz = float(f.read().strip())
                span = max(max_mhz - min_mhz, 1.0)
                gpu_pct = max(0.05, min(0.95, (act_mhz - min_mhz) / span))
            self.latest_gpu = gpu_pct
            self.gpu_history.append(gpu_pct)
            self.gpu_spark.set_data(list(self.gpu_history))
            self.gpu_val.set_text(f"{int(gpu_pct * 100)}%")
        except Exception:
            pass

        # 4. Live Temp calculation
        try:
            temp_c = 28
            for path in ['/sys/class/thermal/thermal_zone0/temp', '/sys/class/thermal/thermal_zone1/temp', '/sys/class/thermal/thermal_zone2/temp']:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        temp_c = int(int(f.read().strip()) / 1000)
                    break
            self.latest_temp = temp_c
            # Scale 20C-80C to 0.05-0.95
            temp_pct = max(0.05, min(0.95, (temp_c - 20) / 60.0))
            self.temp_history.append(temp_pct)
            self.temp_spark.set_data(list(self.temp_history))
            self.temp_val.set_text(f"{temp_c}°C")
        except Exception:
            pass

    def vis_tick(self):
        """Drives the silky 50 FPS constant horizontal flow of all 4 graphs."""
        self.cpu_spark.tick_flow()
        self.ram_spark.tick_flow()
        self.gpu_spark.tick_flow()
        self.temp_spark.tick_flow()


# ==============================================================================
# 2.5 TOP-RIGHT WEATHER FROSTED GLASS CARD (ACCUWEATHER - TEOK)
# ==============================================================================
class StarkWeatherWidget(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.weather_service_script = os.path.expanduser("~/.config/stark-rice/weather_service.py")
        self.cache_file = os.path.expanduser("~/.config/stark-rice/weather_cache.json")
        self.is_fetching = False

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 255)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 28)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_namespace(self, "stark-weather")
        make_window_transparent(self)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        card.get_style_context().add_class("stark-glass-card")
        card.set_size_request(205, 116)

        # Header: City Name + AccuWeather Pill
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.city_lbl = Gtk.Label(label="Weather")
        self.city_lbl.set_xalign(0.0)
        self.city_lbl.get_style_context().add_class("weather-city-lbl")

        badge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        badge_box.get_style_context().add_class("weather-badge")
        self.badge_lbl = Gtk.Label(label="ACCUWEATHER")
        self.badge_lbl.get_style_context().add_class("weather-badge-text")
        badge_box.pack_start(self.badge_lbl, False, False, 0)

        header_row.pack_start(self.city_lbl, True, True, 0)
        header_row.pack_end(badge_box, False, False, 0)
        card.pack_start(header_row, False, False, 0)

        # Main Info Row: Large Icon + Temp + Condition
        main_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        self.icon_lbl = Gtk.Label(label="\uf185")
        self.icon_lbl.get_style_context().add_class("weather-main-icon")
        self.icon_lbl.get_style_context().add_class("weather-icon-sun")

        vinfo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.temp_lbl = Gtk.Label(label="29°C")
        self.temp_lbl.set_xalign(0.0)
        self.temp_lbl.get_style_context().add_class("weather-temp-val")

        self.cond_lbl = Gtk.Label(label="Clear")
        self.cond_lbl.set_xalign(0.0)
        self.cond_lbl.get_style_context().add_class("weather-cond-text")

        vinfo.pack_start(self.temp_lbl, False, False, 0)
        vinfo.pack_start(self.cond_lbl, False, False, 0)

        main_row.pack_start(self.icon_lbl, False, False, 0)
        main_row.pack_start(vinfo, True, True, 0)
        card.pack_start(main_row, False, False, 2)

        # Hairline separator
        sep = Gtk.Box()
        sep.get_style_context().add_class("weather-sub-divider")
        card.pack_start(sep, False, False, 2)

        # Sub-metrics Row (Feels Like, Humidity, High/Low Range)
        metrics_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)

        self.feel_lbl = Gtk.Label()
        self.feel_lbl.set_markup('<span font_family="JetBrainsMono Nerd Font" color="#38bdf8">\uf2c9</span> <span color="#cbd5e1" font_weight="500">32°</span>')

        self.humid_lbl = Gtk.Label()
        self.humid_lbl.set_markup('<span font_family="JetBrainsMono Nerd Font" color="#38bdf8">\uf043</span> <span color="#cbd5e1" font_weight="500">53%</span>')

        self.range_lbl = Gtk.Label()
        self.range_lbl.set_markup('<span font_family="JetBrainsMono Nerd Font" color="#38bdf8">\U000f0504</span> <span color="#cbd5e1" font_weight="500">29°/19°</span>')

        metrics_row.pack_start(self.feel_lbl, True, True, 0)
        metrics_row.pack_start(self.humid_lbl, True, True, 0)
        metrics_row.pack_start(self.range_lbl, True, True, 0)
        card.pack_start(metrics_row, False, False, 1)

        # EventBox for click-to-refresh
        eb = Gtk.EventBox()
        eb.add(card)
        eb.set_tooltip_text("AccuWeather • Click to refresh")
        eb.connect("button-press-event", self._on_card_clicked)
        self.add(eb)

        # Instant load from cache & async background refresh
        self.update_from_cache()
        self.refresh_weather_async()

    def _on_card_clicked(self, widget, event):
        self.refresh_weather_async(force=True)
        return False

    def update_from_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    data = json.load(f)
                self.apply_weather_data(data)
            except Exception:
                pass

    def apply_weather_data(self, data):
        if not data:
            return
        city = data.get("city", "Weather")
        temp = data.get("temp_c", 29)
        cond = data.get("condition", "Clear")
        glyph = data.get("icon_glyph", "\uf185")
        feel = data.get("feels_like_c", temp)
        humid = data.get("humidity", 50)
        wind = data.get("wind_kmh", 5)
        temp_max = data.get("temp_max_c", temp + 2)
        temp_min = data.get("temp_min_c", temp - 6)
        is_day = data.get("is_daytime", True)

        self.city_lbl.set_text(city)
        self.temp_lbl.set_text(f"{temp}°C")
        self.cond_lbl.set_text(cond)
        self.icon_lbl.set_text(glyph)

        # Condition-based glyph coloring
        ctx = self.icon_lbl.get_style_context()
        ctx.remove_class("weather-icon-sun")
        ctx.remove_class("weather-icon-cloud")
        ctx.remove_class("weather-icon-rain")
        ctx.remove_class("weather-icon-night")

        if not is_day:
            ctx.add_class("weather-icon-night")
        elif any(w in cond.lower() for w in ["rain", "shower", "drizzle", "storm"]):
            ctx.add_class("weather-icon-rain")
        elif any(w in cond.lower() for w in ["cloud", "overcast", "fog", "hazy"]):
            ctx.add_class("weather-icon-cloud")
        else:
            ctx.add_class("weather-icon-sun")

        self.feel_lbl.set_markup(f'<span font_family="JetBrainsMono Nerd Font" color="#38bdf8">\uf2c9</span> <span color="#cbd5e1" font_weight="500">{feel}°</span>')
        self.humid_lbl.set_markup(f'<span font_family="JetBrainsMono Nerd Font" color="#38bdf8">\uf043</span> <span color="#cbd5e1" font_weight="500">{humid}%</span>')
        self.range_lbl.set_markup(f'<span font_family="JetBrainsMono Nerd Font" color="#38bdf8">\U000f0504</span> <span color="#cbd5e1" font_weight="500">{temp_max}°/{temp_min}°</span>')

    def refresh_weather_async(self, force=False):
        if self.is_fetching:
            return
        self.is_fetching = True

        def _worker():
            try:
                cmd = ["python3", self.weather_service_script]
                if force:
                    cmd.append("--refresh")
                out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8")
                data = json.loads(out)
                GLib.idle_add(self._on_fetch_complete, data)
            except Exception:
                GLib.idle_add(self._on_fetch_complete, None)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_fetch_complete(self, data):
        self.is_fetching = False
        if data:
            self.apply_weather_data(data)


# ==============================================================================
# 3. BOTTOM-LEFT MUSIC PLAYER FROSTED GLASS CARD (EXCLUSIVE TO ZENIFY)
# ==============================================================================
class StarkMusicWidget(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.current_art_path = None
        self.player_script = os.path.expanduser("~/.config/stark-rice/stark_player.py")
        self.spotify_script = os.path.expanduser("~/.config/stark-rice/stark_spotify.py")
        self.state_file = os.path.expanduser("~/.config/stark-rice/music_state.json")
        self.is_playing = False
        self.current_duration = 0.0
        self.target_progress = 0.0

        # Dedicated CAVA audio spectrum analyzer engine
        self.cava = CavaVisualizerEngine(num_bars=10)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, 45)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, 20)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_namespace(self, "stark-music")
        make_window_transparent(self)

        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        card.get_style_context().add_class("stark-glass-card")
        card.set_size_request(370, 115)

        # Album Art (Always Gtk.Image with rounded corners)
        self.art_img = Gtk.Image()
        self.art_img.get_style_context().add_class("music-art-img")
        fallback_art = os.path.join(ASSETS_DIR, "after_dark.png")
        pix = get_rounded_pixbuf(fallback_art, 64, 8)
        if pix:
            self.art_img.set_from_pixbuf(pix)
        card.pack_start(self.art_img, False, False, 0)

        # Right Info Column
        info_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        self.title_lbl = Gtk.Label(label="Zenify Audio")
        self.title_lbl.set_xalign(0.0)
        self.title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_lbl.set_max_width_chars(24)
        self.title_lbl.get_style_context().add_class("music-title-text")

        self.artist_lbl = Gtk.Label(label="Ready to play")
        self.artist_lbl.set_xalign(0.0)
        self.artist_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist_lbl.set_max_width_chars(26)
        self.artist_lbl.get_style_context().add_class("music-artist-text")

        # Waveform & Progress area
        self.wave_bar = MusicWaveformBar(progress=0.0, width=220, height=18)

        # Controls row (Strictly routed to Zenify / stark_player.py, zero playerctl)
        ctrls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        prev_btn = Gtk.Button(label="⏮")
        prev_btn.get_style_context().add_class("music-ctrl-btn")
        prev_btn.connect("clicked", lambda w: subprocess.Popen(["python3", self.player_script, "--prev"]))

        self.play_btn = Gtk.Button(label="▶")
        self.play_btn.get_style_context().add_class("music-ctrl-btn")
        self.play_btn.connect("clicked", lambda w: subprocess.Popen(["python3", self.player_script, "--toggle"]))

        next_btn = Gtk.Button(label="⏭")
        next_btn.get_style_context().add_class("music-ctrl-btn")
        next_btn.connect("clicked", lambda w: subprocess.Popen(["python3", self.player_script, "--next"]))

        ctrls_box.pack_start(prev_btn, False, False, 0)
        ctrls_box.pack_start(self.play_btn, False, False, 0)
        ctrls_box.pack_start(next_btn, False, False, 0)

        info_vbox.pack_start(self.title_lbl, False, False, 0)
        info_vbox.pack_start(self.artist_lbl, False, False, 0)
        info_vbox.pack_start(self.wave_bar, False, False, 4)
        info_vbox.pack_start(ctrls_box, False, False, 2)

        card.pack_start(info_vbox, True, True, 0)

        # Click card to open/toggle Zenify player UI
        card_event = Gtk.EventBox()
        card_event.add(card)
        card_event.connect("button-press-event", self._on_card_click)
        self.add(card_event)

        # Run initial sync
        self.update_state()

    def _on_card_click(self, widget, event):
        subprocess.Popen(["python3", self.spotify_script, "--toggle"])
        return False

    def _query_mpv_state(self):
        sock_path = "/tmp/stark_player.sock"
        if not os.path.exists(sock_path):
            return None
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.08)
            s.connect(sock_path)
            cmd = (
                json.dumps({"command": ["get_property", "time-pos"]}) + "\n" +
                json.dumps({"command": ["get_property", "duration"]}) + "\n" +
                json.dumps({"command": ["get_property", "pause"]}) + "\n" +
                json.dumps({"command": ["get_property", "idle-active"]}) + "\n"
            )
            s.sendall(cmd.encode("utf-8"))
            data = b""
            while True:
                chunk = s.recv(2048)
                if not chunk:
                    break
                data += chunk
                if data.count(b"\n") >= 4:
                    break
            s.close()
            lines = data.decode("utf-8", errors="ignore").strip().split("\n")
            props = []
            for line in lines:
                try:
                    res = json.loads(line)
                    props.append(res.get("data"))
                except Exception:
                    props.append(None)
            pos = props[0] if len(props) > 0 and isinstance(props[0], (int, float)) else None
            dur = props[1] if len(props) > 1 and isinstance(props[1], (int, float)) else None
            pause = props[2] if len(props) > 2 and isinstance(props[2], bool) else False
            idle = props[3] if len(props) > 3 and isinstance(props[3], bool) else False
            if idle:
                return {"is_playing": False, "position": 0.0, "duration": 0.0, "progress": 0.0}
            if dur is not None and dur > 0 and pos is not None:
                return {
                    "is_playing": not pause,
                    "position": float(pos),
                    "duration": float(dur),
                    "progress": min(1.0, max(0.0, float(pos) / float(dur)))
                }
            return None
        except Exception:
            return None

    def update_state(self):
        """Reads Zenify state from disk and mpv IPC socket (called every 250ms)."""
        # 1. Track metadata from state file
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    st = json.load(f)
                title = st.get("title", "")
                artist = st.get("artist", "")
                progress = float(st.get("progress", 0.0))
                self.is_playing = bool(st.get("is_playing", False))
                self.current_duration = float(st.get("duration", 0.0))
                self.target_progress = max(0.0, min(1.0, progress))
                art_path = st.get("art_path")

                if title and title != self.title_lbl.get_text():
                    self.title_lbl.set_text(title)
                    self.artist_lbl.set_text(artist if artist else "Zenify")

                if art_path and art_path != self.current_art_path and os.path.exists(art_path):
                    pix = get_rounded_pixbuf(art_path, 64, 8)
                    if pix:
                        self.art_img.set_from_pixbuf(pix)
                        self.current_art_path = art_path
            except Exception:
                pass

        # 2. Query mpv directly for live, zero-latency playback position & status
        mpv_st = self._query_mpv_state()
        if mpv_st:
            self.is_playing = mpv_st["is_playing"]
            self.current_duration = mpv_st["duration"]
            self.target_progress = mpv_st["progress"]

        self.play_btn.set_label("⏸" if self.is_playing else "▶")
        if abs(self.wave_bar.progress - self.target_progress) > 0.015:
            self.wave_bar.progress = self.target_progress

    def vis_tick(self):
        """Ultra-smooth 50 FPS animation tick with CAVA audio FFT reaction and smooth lerp."""
        if self.is_playing:
            targets = self.cava.get_bars()
        else:
            targets = [3.0] * 10

        # Snappy rise to beats, graceful decay
        for i in range(len(self.wave_bar.bars)):
            cur = self.wave_bar.bars[i]
            tgt = targets[i]
            diff = tgt - cur
            rate = 0.42 if diff > 0 else 0.20
            self.wave_bar.bars[i] = cur + (diff * rate)

        # Smooth progress interpolation between 250ms state updates
        if self.is_playing and self.current_duration > 0:
            step = 0.020 / self.current_duration  # 20ms tick
            self.wave_bar.progress = min(1.0, max(0.0, self.wave_bar.progress + step))

        self.wave_bar.queue_draw()
        return True

    def cleanup(self):
        if hasattr(self, 'cava') and self.cava:
            self.cava.stop()


# ==============================================================================
# 4. BOTTOM-RIGHT DUAL-PANE TERMINAL & TONY STARK QUOTE FROSTED GLASS CARD
# ==============================================================================
class StarkQuoteWidget(Gtk.Window):
    def __init__(self):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, 45)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 30)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_namespace(self, "stark-quote")
        make_window_transparent(self)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.get_style_context().add_class("stark-glass-card")
        card.set_size_request(240, 76)

        # Tony Stark Quote
        quote_lbl = Gtk.Label(label="\"Sometimes you gotta\nrun before you can walk.\"")
        quote_lbl.set_xalign(0.0)
        quote_lbl.set_line_wrap(True)
        quote_lbl.get_style_context().add_class("quote-text")

        author_lbl = Gtk.Label(label="— Tony Stark")
        author_lbl.set_xalign(1.0)
        author_lbl.get_style_context().add_class("quote-author")

        card.pack_start(quote_lbl, True, True, 0)
        card.pack_end(author_lbl, False, False, 0)

        self.add(card)

    def update(self):
        pass


# ==============================================================================
# MAIN APPLICATION CONTROLLER WITH HOLOGRAPHIC BOOT ANIMATION
# ==============================================================================
class StarkWidgetsApp:
    def __init__(self):
        self._load_css()

        self.clock_win = StarkClockWidget()
        self.sysmon_win = StarkSysmonWidget()
        self.weather_win = StarkWeatherWidget()
        self.music_win = StarkMusicWidget()
        self.quote_win = StarkQuoteWidget()

        self.all_windows = [
            self.clock_win,
            self.sysmon_win,
            self.weather_win,
            self.music_win,
            self.quote_win
        ]

        # Initial zero-opacity state before boot materialization
        for win in self.all_windows:
            win.set_opacity(0.0)
            win.show_all()

        # Prime initial hardware stats
        self.sysmon_win.update()

        # Start Sequential Holographic Boot Animation Loop (16ms / 60 FPS)
        # Sequence: 1. System Monitor -> 2. Weather -> 3. Quote -> 4. Music -> 5. Clock
        self.seq_timeline = [
            ("sysmon", self.sysmon_win, 0.0),
            ("weather", self.weather_win, 0.38),
            ("quote", self.quote_win, 0.76),
            ("music", self.music_win, 1.14),
            ("clock", self.clock_win, 1.52),
        ]
        self.item_dur = 0.48
        self.boot_duration = 2.10
        self.boot_start_time = time.time()
        GLib.timeout_add(16, self._boot_animation_tick)

        # Regular 1s tick for clock, sysmon & quote
        GLib.timeout_add_seconds(1, self.tick)
        # 250ms tick for music state updates
        GLib.timeout_add(250, self.music_state_tick)
        # Ultra-smooth 20ms (50 FPS) visualizer animation loop
        GLib.timeout_add(20, self.vis_tick)
        # 10-minute periodic weather refresh tick
        GLib.timeout_add_seconds(600, self.weather_tick)

        atexit.register(self.cleanup)

    def _boot_animation_tick(self):
        elapsed = time.time() - self.boot_start_time
        if elapsed >= self.boot_duration:
            for _, win, _ in self.seq_timeline:
                win.set_opacity(1.0)
            self.sysmon_win.set_anim_progress(1.0)
            return False

        for name, win, t_start in self.seq_timeline:
            rel = elapsed - t_start
            if rel < 0.0:
                win.set_opacity(0.0)
                if name == "sysmon":
                    self.sysmon_win.set_anim_progress(0.01)
            elif rel < self.item_dur:
                # Longer, detailed high-tech ionization micro-flicker
                t_ms = rel * 1000.0
                if t_ms < 50:
                    op = 0.05 + (t_ms / 50.0) * 0.70
                elif t_ms < 110:
                    op = 0.18 + ((t_ms - 50) / 60.0) * 0.10
                elif t_ms < 180:
                    op = 0.90 + ((t_ms - 110) / 70.0) * 0.05
                elif t_ms < 240:
                    op = 0.28 + ((t_ms - 180) / 60.0) * 0.15
                elif t_ms < 330:
                    op = 0.96 + ((t_ms - 240) / 90.0) * 0.03
                elif t_ms < 400:
                    op = 0.82 + ((t_ms - 330) / 70.0) * 0.18
                else:
                    op = 1.0
                win.set_opacity(max(0.0, min(1.0, op)))
                if name == "sysmon":
                    p = max(0.02, min(1.0, rel / self.item_dur))
                    self.sysmon_win.set_anim_progress(p)
            else:
                win.set_opacity(1.0)
                if name == "sysmon":
                    self.sysmon_win.set_anim_progress(1.0)

        return True

    def cleanup(self):
        try:
            self.music_win.cleanup()
        except Exception:
            pass

    def _load_css(self):
        css_provider = Gtk.CssProvider()
        try:
            css_provider.load_from_path(CSS_FILE)
            screen = Gdk.Screen.get_default()
            Gtk.StyleContext.add_provider_for_screen(
                screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
            )
        except Exception as e:
            print("CSS load error:", e)

    def tick(self):
        self.clock_win.update()
        self.sysmon_win.update()
        self.quote_win.update()
        return True

    def weather_tick(self):
        self.weather_win.refresh_weather_async()
        return True

    def music_state_tick(self):
        self.music_win.update_state()
        return True

    def vis_tick(self):
        self.music_win.vis_tick()
        self.sysmon_win.vis_tick()
        return True


if __name__ == "__main__":
    app = StarkWidgetsApp()
    Gtk.main()
