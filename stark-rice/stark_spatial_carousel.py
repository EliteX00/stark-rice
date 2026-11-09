#!/usr/bin/env python3
"""
Zenify Cover Flow Canvas - Modern Glassmorphic Work of Art
===========================================================
Inspired by modern Apple Music & Dribbble glassmorphic spatial design:
- Silky blurred ambient glow dynamically generated from album artwork colors.
- True 3D perspective Cover Flow with smooth spring dampening.
- Frosted glass cards with centered typography, real album art, and soft drop shadows.
- Zero CPU when stationary: animation timer strictly runs during motion (~200ms).
"""

import os
import sys
import math
import time
import threading
import urllib.request
import hashlib

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
import cairo
from PIL import Image, ImageFilter

CONFIG_DIR = os.path.expanduser("~/.config/stark-rice")
ASSETS_DIR = os.path.join(CONFIG_DIR, "assets")
THUMB_CACHE_DIR = os.path.join(ASSETS_DIR, "album_thumbs")
os.makedirs(THUMB_CACHE_DIR, exist_ok=True)


def rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class StarkCoverFlowCanvas(Gtk.DrawingArea):
    """
    3D Spatial Cover Flow canvas with dynamic blurred ambient background.
    """
    def __init__(self, on_track_play=None, on_focus_change=None):
        super().__init__()
        self.on_track_play = on_track_play
        self.on_focus_change = on_focus_change
        self.tracks = []
        self.target_idx = 0.0
        self.current_idx = 0.0
        self.last_reported_idx = -1

        # Image & Background Caches
        self.surface_cache = {}
        self.bg_cache = {}
        self.loading_arts = set()
        self.current_bg_surface = None
        self.current_art_path = None

        # Interaction & Animation
        self._anim_timer_id = None
        self.hovered_idx = None
        self.hover_arrow = None  # "left" or "right"

        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.LEAVE_NOTIFY_MASK |
            Gdk.EventMask.SCROLL_MASK
        )

        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_button_press)
        self.connect("motion-notify-event", self._on_motion_notify)
        self.connect("leave-notify-event", self._on_leave_notify)
        self.connect("scroll-event", self._on_scroll)
        self.set_can_focus(True)

    def set_tracks(self, tracks):
        self.tracks = tracks or []
        self.target_idx = 0.0
        self.current_idx = 0.0
        self.last_reported_idx = -1
        if self.tracks:
            self._update_center_bg(self.tracks[0])
        self.queue_draw()

    def set_active_playback(self, title, artist, art_path):
        if art_path and os.path.exists(art_path) and art_path != self.current_art_path:
            self.current_art_path = art_path
            self._load_bg_from_file_async(art_path)

    def scroll_to_next(self):
        if not self.tracks:
            return
        max_idx = len(self.tracks) - 1
        new_target = min(max_idx, round(self.target_idx) + 1)
        self._set_target(new_target)

    def scroll_to_prev(self):
        if not self.tracks:
            return
        new_target = max(0, round(self.target_idx) - 1)
        self._set_target(new_target)

    def _set_target(self, target):
        if not self.tracks:
            return
        self.target_idx = max(0, min(len(self.tracks) - 1, target))
        if not self._anim_timer_id:
            # 50 FPS (20ms) timer ONLY while moving!
            self._anim_timer_id = GLib.timeout_add(20, self._on_anim_step)

    def _on_anim_step(self):
        diff = self.target_idx - self.current_idx
        if abs(diff) < 0.003:
            self.current_idx = float(self.target_idx)
            self._anim_timer_id = None
            self._check_focus_change()
            self.queue_draw()
            return False  # Stop timer, 0% CPU!

        self.current_idx += diff * 0.22
        self._check_focus_change()
        self.queue_draw()
        return True

    def _check_focus_change(self):
        center_i = int(round(self.current_idx))
        if center_i != self.last_reported_idx and 0 <= center_i < len(self.tracks):
            self.last_reported_idx = center_i
            track = self.tracks[center_i]
            self._update_center_bg(track)
            if self.on_focus_change:
                self.on_focus_change(track, center_i)

    def _update_center_bg(self, track):
        art_path = track.get("art_path")
        art_url = track.get("art_url")
        if art_path and os.path.exists(art_path):
            self._load_bg_from_file_async(art_path)
        elif art_url:
            fn = hashlib.md5(art_url.encode("utf-8")).hexdigest() + ".jpg"
            p = os.path.join(THUMB_CACHE_DIR, fn)
            if os.path.exists(p) and os.path.getsize(p) > 500:
                self._load_bg_from_file_async(p)

    def _load_bg_from_file_async(self, file_path):
        if file_path in self.bg_cache:
            self.current_bg_surface = self.bg_cache[file_path]
            self.queue_draw()
            return

        def _worker():
            try:
                im = Image.open(file_path).convert("RGB")
                small = im.resize((64, 40), Image.Resampling.BILINEAR)
                blurred = small.filter(ImageFilter.GaussianBlur(radius=8))

                b_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 40)
                b_data = b_surf.get_data()
                for y in range(40):
                    for x in range(64):
                        r, g, b = blurred.getpixel((x, y))
                        # Subtle saturation and contrast boost
                        r = int(min(255, r * 0.85))
                        g = int(min(255, g * 0.85))
                        b = int(min(255, b * 0.85))
                        idx = (y * 64 + x) * 4
                        b_data[idx] = b
                        b_data[idx+1] = g
                        b_data[idx+2] = r
                        b_data[idx+3] = 255
                b_surf.mark_dirty()

                self.bg_cache[file_path] = b_surf
                self.current_bg_surface = b_surf
                GLib.idle_add(self.queue_draw)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _get_or_load_surface(self, track, target_w=230, target_h=215):
        art_url = track.get("art_url") or ""
        art_path = track.get("art_path") or ""
        cache_key = art_url or art_path or "default"

        if cache_key in self.surface_cache:
            return self.surface_cache[cache_key]

        local_file = None
        if art_path and os.path.exists(art_path):
            local_file = art_path
        elif art_url:
            fn = hashlib.md5(art_url.encode("utf-8")).hexdigest() + ".jpg"
            p = os.path.join(THUMB_CACHE_DIR, fn)
            if os.path.exists(p) and os.path.getsize(p) > 500:
                local_file = p

        if local_file:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(local_file, target_w, target_h, False)
                surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, target_w, target_h)
                cr = cairo.Context(surf)
                Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
                cr.paint()
                self.surface_cache[cache_key] = surf
                return surf
            except Exception:
                pass

        if not art_url and not art_path:
            title = track.get("title", "")
            artist = track.get("artist", "")
            search_key = f"{title}_{artist}"
            if title and search_key not in self.loading_arts:
                self.loading_arts.add(search_key)
                threading.Thread(target=self._search_and_download_art_async, args=(track, search_key, target_w, target_h), daemon=True).start()
            return None

        if art_url and cache_key not in self.loading_arts:
            self.loading_arts.add(cache_key)
            threading.Thread(target=self._download_art_async, args=(art_url, cache_key, target_w, target_h), daemon=True).start()

        return None

    def _search_and_download_art_async(self, track, search_key, target_w, target_h):
        try:
            import json, urllib.parse
            title = track.get("title", "")
            artist = track.get("artist", "")
            q = urllib.parse.quote(f"{title} {artist}")
            api_url = f"https://itunes.apple.com/search?term={q}&entity=song&limit=1"
            req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results", [])
                if results:
                    raw_art = results[0].get("artworkUrl100", "").replace("100x100bb", "600x600bb")
                    if raw_art:
                        track["art_url"] = raw_art
                        self._download_art_async(raw_art, raw_art, target_w, target_h)
                        # Also update background if this is the center card
                        curr_center = int(round(self.current_idx))
                        if 0 <= curr_center < len(self.tracks) and self.tracks[curr_center] is track:
                            self._update_center_bg(track)
                        return
        except Exception:
            pass
        finally:
            self.loading_arts.discard(search_key)

    def _download_art_async(self, url, cache_key, target_w, target_h):
        try:
            fn = hashlib.md5(url.encode("utf-8")).hexdigest() + ".jpg"
            dest = os.path.join(THUMB_CACHE_DIR, fn)
            if not os.path.exists(dest) or os.path.getsize(dest) < 500:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=4.0) as resp, open(dest, "wb") as f:
                    f.write(resp.read())

            if os.path.exists(dest):
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(dest, target_w, target_h, False)
                surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, target_w, target_h)
                cr = cairo.Context(surf)
                Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
                cr.paint()
                self.surface_cache[cache_key] = surf
                curr_center = int(round(self.current_idx))
                if 0 <= curr_center < len(self.tracks):
                    ctr_t = self.tracks[curr_center]
                    if ctr_t.get("art_url") == url or ctr_t.get("art_path") == dest:
                        self._load_bg_from_file_async(dest)
                GLib.idle_add(self.queue_draw)
        except Exception:
            pass
        finally:
            self.loading_arts.discard(cache_key)

    # -------------------------------------------------------------------------
    # Draw Routine (Apple Music / Dribbble Glass Artwork Canvas)
    # -------------------------------------------------------------------------
    def _on_draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        if w < 100 or h < 100:
            return False

        # 1. Silky Dynamic Ambient Glow Background
        if self.current_bg_surface:
            cr.save()
            cr.scale(w / 64.0, h / 40.0)
            cr.set_source_surface(self.current_bg_surface, 0, 0)
            cr.paint()
            cr.restore()
        else:
            # Fallback luxurious deep warm dark
            cr.set_source_rgba(0.08, 0.06, 0.06, 1.0)
            cr.paint()

        # Dark aesthetic vignette overlay
        vig = cairo.RadialGradient(w / 2.0, h * 0.45, 120, w / 2.0, h * 0.45, w * 0.75)
        vig.add_color_stop_rgba(0.0, 0.0, 0.0, 0.0, 0.08)
        vig.add_color_stop_rgba(0.7, 0.0, 0.0, 0.0, 0.45)
        vig.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, 0.75)
        cr.set_source(vig)
        cr.paint()

        if not self.tracks:
            self._draw_empty_state(cr, w, h)
            return False

        # 2. Draw 3D Cover Flow Cards
        card_w = 230.0
        card_h = 295.0
        cx = w / 2.0
        cy = (h / 2.0) - 20.0

        n_tracks = len(self.tracks)
        c_idx = self.current_idx

        # Render visible range: 3 cards on left, center, 3 cards on right
        min_i = max(0, int(math.floor(c_idx - 3.5)))
        max_i = min(n_tracks - 1, int(math.ceil(c_idx + 3.5)))

        indices = list(range(min_i, max_i + 1))
        # Layer ordering: Render outermost cards first, center card LAST
        indices.sort(key=lambda idx: abs(idx - c_idx), reverse=True)

        for idx in indices:
            offset = idx - c_idx
            track = self.tracks[idx]
            self._draw_3d_card(cr, track, idx, offset, cx, cy, card_w, card_h)

        # Subtle floating chevrons on sides
        self._draw_nav_chevrons(cr, w, h)
        return False

    def _draw_empty_state(self, cr, w, h):
        cr.save()
        cr.select_font_face("Rubik", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(16)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.7)
        txt = "Discovering personalized tracks..."
        ext = cr.text_extents(txt)
        cr.move_to((w - ext.width) / 2.0, (h / 2.0) - 20)
        cr.show_text(txt)
        cr.restore()

    def _draw_3d_card(self, cr, track, idx, offset, cx, cy, card_w, card_h):
        abs_off = abs(offset)
        if abs_off > 3.5:
            return

        scale = 1.0 / (1.0 + 0.22 * abs_off)
        alpha = 1.0 / (1.0 + 0.42 * abs_off)

        sign = -1.0 if offset < 0 else (1.0 if offset > 0 else 0.0)
        spacing = 175.0 if abs_off <= 1.0 else (175.0 + (abs_off - 1.0) * 115.0)
        pos_x = cx + (sign * spacing * (1.0 / (1.0 + 0.08 * abs_off)))
        pos_y = cy

        # 3D Yaw Rotation angle
        theta = offset * math.radians(24.0)
        cos_t = math.cos(theta)
        skew_y = -sign * 0.085 * min(abs_off, 2.0)

        is_center = (abs_off < 0.45)

        cr.save()
        cr.translate(pos_x, pos_y)

        # 3D Affine Perspective Transform
        mat = cairo.Matrix(
            cos_t * scale, skew_y * scale,
            0, scale,
            0, 0
        )
        cr.transform(mat)

        half_w = card_w / 2.0
        half_h = card_h / 2.0
        r_corner = 20.0

        # 1. Soft Physical Drop Shadow (creates genuine floating depth)
        cr.save()
        cr.translate(0, 18.0)
        rounded_rect(cr, -half_w, -half_h, card_w, card_h, r_corner)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.45 * alpha)
        cr.fill()
        cr.restore()

        # 2. Card Clip
        rounded_rect(cr, -half_w, -half_h, card_w, card_h, r_corner)
        cr.clip()

        # 3. Artwork Area (Top 74% of card)
        art_h = card_h * 0.74
        art_surf = self._get_or_load_surface(track, int(card_w), int(art_h))

        if art_surf:
            cr.save()
            sw = art_surf.get_width()
            sh = art_surf.get_height()
            cr.translate(-half_w, -half_h)
            cr.scale(card_w / float(sw), art_h / float(sh))
            cr.set_source_surface(art_surf, 0, 0)
            cr.paint_with_alpha(1.0 * alpha)
            cr.restore()
        else:
            # Elegant minimalist placeholder
            cr.rectangle(-half_w, -half_h, card_w, art_h)
            cr.set_source_rgba(0.12, 0.12, 0.16, 0.95 * alpha)
            cr.fill()

        # 4. Frosted Glass Footer (Bottom 26% of card)
        cr.rectangle(-half_w, -half_h + art_h, card_w, card_h - art_h)
        foot_pat = cairo.LinearGradient(0, -half_h + art_h, 0, half_h)
        foot_pat.add_color_stop_rgba(0.0, 0.1, 0.1, 0.12, 0.92 * alpha)
        foot_pat.add_color_stop_rgba(1.0, 0.05, 0.05, 0.07, 0.98 * alpha)
        cr.set_source(foot_pat)
        cr.fill()

        # 5. Centered Song Title & Artist (clean, award-winning typography)
        title_str = track.get("title", "Track")
        artist_str = track.get("artist", "Artist")

        # Title (Bold White, Centered)
        cr.select_font_face("Rubik", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(15 if is_center else 12.5)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.98 * alpha)
        trunc_t = self._truncate_text(cr, title_str, card_w - 28.0)
        t_ext = cr.text_extents(trunc_t)
        cr.move_to(-t_ext.width / 2.0, half_h - 40.0)
        cr.show_text(trunc_t)

        # Artist (Soft White, Centered)
        cr.select_font_face("Rubik", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(12 if is_center else 10.5)
        cr.set_source_rgba(0.85, 0.85, 0.9, 0.75 * alpha)
        trunc_a = self._truncate_text(cr, artist_str, card_w - 32.0)
        a_ext = cr.text_extents(trunc_a)
        cr.move_to(-a_ext.width / 2.0, half_h - 20.0)
        cr.show_text(trunc_a)

        # 6. Delicate Hairline Glass Border
        cr.reset_clip()
        rounded_rect(cr, -half_w, -half_h, card_w, card_h, r_corner)
        if is_center:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.38)
            cr.set_line_width(1.4)
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.18 * alpha)
            cr.set_line_width(1.0)
        cr.stroke()

        cr.restore()

    def _draw_nav_chevrons(self, cr, w, h):
        cr.save()
        cy = (h / 2.0) - 20.0

        # Left Chevron
        left_alpha = 0.85 if self.hover_arrow == "left" else 0.35
        cr.set_source_rgba(1.0, 1.0, 1.0, left_alpha)
        cr.set_line_width(2.5)
        cr.move_to(36, cy - 18); cr.line_to(22, cy); cr.line_to(36, cy + 18)
        cr.stroke()

        # Right Chevron
        right_alpha = 0.85 if self.hover_arrow == "right" else 0.35
        cr.set_source_rgba(1.0, 1.0, 1.0, right_alpha)
        cr.set_line_width(2.5)
        cr.move_to(w - 36, cy - 18); cr.line_to(w - 22, cy); cr.line_to(w - 36, cy + 18)
        cr.stroke()

        cr.restore()

    def _truncate_text(self, cr, text, max_w):
        if not text:
            return ""
        ext = cr.text_extents(text)
        if ext.width <= max_w:
            return text
        ellipsis = "…"
        while len(text) > 1 and cr.text_extents(text + ellipsis).width > max_w:
            text = text[:-1]
        return text + ellipsis

    def _on_button_press(self, widget, event):
        if not self.tracks:
            return False

        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        cy = (h / 2.0) - 20.0

        if event.x <= 55 and abs(event.y - cy) < 40:
            self.scroll_to_prev()
            return True
        if event.x >= w - 55 and abs(event.y - cy) < 40:
            self.scroll_to_next()
            return True

        cx = w / 2.0
        center_w = 230.0 / 2.0
        center_h = 295.0 / 2.0

        if abs(event.x - cx) <= center_w and abs(event.y - cy) <= center_h:
            curr_idx = int(round(self.current_idx))
            if 0 <= curr_idx < len(self.tracks):
                track = self.tracks[curr_idx]
                if self.on_track_play:
                    self.on_track_play(track, curr_idx)
                return True

        if event.x < cx - center_w:
            self.scroll_to_prev()
            return True
        elif event.x > cx + center_w:
            self.scroll_to_next()
            return True

        return False

    def _on_motion_notify(self, widget, event):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        cy = (h / 2.0) - 20.0

        prev_arrow = self.hover_arrow
        if event.x <= 55 and abs(event.y - cy) < 40:
            self.hover_arrow = "left"
        elif event.x >= w - 55 and abs(event.y - cy) < 40:
            self.hover_arrow = "right"
        else:
            self.hover_arrow = None

        if prev_arrow != self.hover_arrow:
            self.queue_draw()
        return False

    def _on_leave_notify(self, widget, event):
        if self.hover_arrow is not None:
            self.hover_arrow = None
            self.queue_draw()
        return False

    def _on_scroll(self, widget, event):
        if event.direction == Gdk.ScrollDirection.UP or (event.delta_y and event.delta_y < 0):
            self.scroll_to_prev()
            return True
        elif event.direction == Gdk.ScrollDirection.DOWN or (event.delta_y and event.delta_y > 0):
            self.scroll_to_next()
            return True
        elif event.direction == Gdk.ScrollDirection.LEFT:
            self.scroll_to_prev()
            return True
        elif event.direction == Gdk.ScrollDirection.RIGHT:
            self.scroll_to_next()
            return True
        return False
