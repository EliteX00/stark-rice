#!/usr/bin/env python3
"""
Stark Launcher - Bespoke Minimalist Frosted Glass App Launcher
Designed exclusively for Stark Rice / Hyprland.
Fast fuzzy matching, instant LayerShell popup, smooth keyboard navigation.
"""

import os
import sys
import math
import glob
import shlex
import socket
import cairo
import subprocess
import configparser

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, GtkLayerShell, Pango

SOCKET_PATH = "/tmp/stark_launcher.sock"


def get_desktop_apps():
    """Scans and caches desktop entries across the system."""
    apps = []
    seen_execs = set()
    search_dirs = [
        os.path.expanduser("~/.local/share/applications"),
        "/usr/local/share/applications",
        "/usr/share/applications",
        "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications")
    ]

    for sdir in search_dirs:
        if not os.path.isdir(sdir):
            continue
        for fpath in glob.glob(os.path.join(sdir, "*.desktop")):
            cp = configparser.ConfigParser(interpolation=None)
            try:
                cp.read(fpath, encoding='utf-8')
                if 'Desktop Entry' not in cp:
                    continue
                sec = cp['Desktop Entry']
                if sec.getboolean('NoDisplay', fallback=False):
                    continue
                if sec.getboolean('Hidden', fallback=False):
                    continue
                name = sec.get('Name', '').strip()
                exec_cmd = sec.get('Exec', '').strip()
                if not name or not exec_cmd:
                    continue

                icon = sec.get('Icon', '').strip()
                comment = sec.get('Comment', sec.get('GenericName', '')).strip()
                categories = sec.get('Categories', '').strip()
                terminal = sec.getboolean('Terminal', fallback=False)

                # Deduplicate by primary executable binary
                base_exec = exec_cmd.split()[0]
                if (name, base_exec) in seen_execs:
                    continue
                seen_execs.add((name, base_exec))

                # Primary clean category tag
                cat_tag = "App"
                if any(c in categories.lower() for c in ["development", "ide", "programming"]):
                    cat_tag = "Dev"
                elif any(c in categories.lower() for c in ["network", "webbrowser", "chat"]):
                    cat_tag = "Internet"
                elif any(c in categories.lower() for c in ["audio", "video", "media"]):
                    cat_tag = "Media"
                elif any(c in categories.lower() for c in ["utility", "accessories", "system"]):
                    cat_tag = "System"
                elif any(c in categories.lower() for c in ["graphics", "game"]):
                    cat_tag = "Graphics"

                apps.append({
                    "name": name,
                    "exec": exec_cmd,
                    "icon": icon,
                    "comment": comment,
                    "cat": cat_tag,
                    "terminal": terminal,
                    "file": fpath
                })
            except Exception:
                continue

    # Sort alphabetically by application name
    apps.sort(key=lambda x: x["name"].lower())
    return apps


class StarkLauncherWindow(Gtk.Window):
    def __init__(self, all_apps):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.all_apps = all_apps
        self.filtered_apps = []
        self.row_widgets = []
        self.selected_index = 0
        self.icon_theme = Gtk.IconTheme.get_default()

        # Initialize GtkLayerShell
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_namespace(self, "stark-launcher")
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        # Position: centered horizontally, 130px from top
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 130)
        self.set_size_request(540, 480)

        # Window transparency setup
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.connect("draw", self._on_draw_window)

        self.has_focused = False
        self.icon_cache = {}
        self._load_css()
        self._build_ui()

        self.connect("key-press-event", self._on_key_press)
        self.connect("focus-in-event", self._on_focus_in)
        self.connect("focus-out-event", self._on_focus_out)

        # Pre-realize for instant 0ms popup response
        self.realize()

        # Populate
        self._filter_apps("")

    def _on_draw_window(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        r = 18.0

        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        # Rounded rectangle outline
        cr.new_sub_path()
        cr.arc(w - r, r, r, -math.pi / 2, 0)
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

        # Frosted Glass Obsidian Fill
        cr.set_source_rgba(0.04, 0.07, 0.12, 0.94)
        cr.fill_preserve()

        # Neon Cyan Glow Border
        cr.set_source_rgba(0.22, 0.74, 0.97, 0.40)
        cr.set_line_width(1.5)
        cr.stroke()
        return False

    def _load_css(self):
        css_data = """
        * {
            font-family: "JetBrainsMono Nerd Font", "Google Sans Flex", sans-serif;
            text-shadow: none;
            box-shadow: none;
        }

        .stark-search-box {
            background-color: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 12px;
            padding: 4px 12px;
            margin-bottom: 8px;
            transition: all 0.18s ease;
        }

        .stark-search-box:focus-within {
            background-color: rgba(255, 255, 255, 0.08);
            border-color: #38bdf8;
            box-shadow: 0 0 12px rgba(56, 189, 248, 0.3);
        }

        .stark-search-icon {
            color: #38bdf8;
            font-size: 15px;
            margin-right: 8px;
        }

        .stark-search-entry {
            background: transparent;
            border: none;
            color: #ffffff;
            font-size: 14px;
            font-weight: 500;
            padding: 6px 0;
            caret-color: #38bdf8;
        }

        .stark-count-badge {
            background-color: rgba(56, 189, 248, 0.12);
            color: #38bdf8;
            border-radius: 8px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: 600;
        }

        .stark-divider {
            background-color: rgba(255, 255, 255, 0.08);
            min-height: 1px;
            margin: 4px 0 8px 0;
        }

        .stark-apps-list {
            background: transparent;
        }

        .stark-app-row {
            padding: 6px 10px;
            margin: 2px 4px;
            border-radius: 10px;
            background: transparent;
            border: 1px solid transparent;
            transition: all 0.12s ease;
        }

        .stark-app-row:hover {
            background-color: rgba(255, 255, 255, 0.06);
            border-color: rgba(255, 255, 255, 0.10);
        }

        .stark-app-row.selected {
            background-color: rgba(56, 189, 248, 0.18);
            border-color: rgba(56, 189, 248, 0.45);
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.15);
        }

        .stark-app-name {
            color: #f1f5f9;
            font-size: 13px;
            font-weight: 600;
        }

        .stark-app-row.selected .stark-app-name {
            color: #ffffff;
        }

        .stark-app-desc {
            color: #94a3b8;
            font-size: 11px;
        }

        .stark-app-badge {
            background-color: rgba(255, 255, 255, 0.05);
            color: #94a3b8;
            border-radius: 6px;
            padding: 2px 6px;
            font-size: 9px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }

        .stark-app-row.selected .stark-app-badge {
            background-color: rgba(56, 189, 248, 0.25);
            color: #e0f2fe;
        }

        .stark-footer {
            margin-top: 8px;
            padding-top: 6px;
        }

        .stark-footer-hint {
            color: #64748b;
            font-size: 10px;
            font-weight: 500;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css_data.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        container.set_size_request(520, 460)
        container.set_margin_top(16)
        container.set_margin_bottom(12)
        container.set_margin_left(16)
        container.set_margin_right(16)

        # 1. Search Bar
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        search_box.get_style_context().add_class("stark-search-box")

        search_icon = Gtk.Label(label="")
        search_icon.get_style_context().add_class("stark-search-icon")

        self.entry = Gtk.Entry()
        self.entry.get_style_context().add_class("stark-search-entry")
        self.entry.set_placeholder_text("Type to search applications...")
        self.entry.connect("changed", self._on_search_changed)
        self.entry.connect("activate", lambda w: self._launch_selected())

        self.count_badge = Gtk.Label(label="0 apps")
        self.count_badge.get_style_context().add_class("stark-count-badge")

        search_box.pack_start(search_icon, False, False, 0)
        search_box.pack_start(self.entry, True, True, 0)
        search_box.pack_end(self.count_badge, False, False, 0)
        container.pack_start(search_box, False, False, 0)

        # Hairline divider
        sep = Gtk.Box()
        sep.get_style_context().add_class("stark-divider")
        container.pack_start(sep, False, False, 0)

        # 2. Results List in ScrolledWindow
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_kinetic_scrolling(True)

        self.listbox = Gtk.ListBox()
        self.listbox.get_style_context().add_class("stark-apps-list")
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.connect("row-activated", self._on_row_clicked)

        self.scroll.add(self.listbox)
        container.pack_start(self.scroll, True, True, 0)

        # 3. Footer Shortcuts
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        footer.get_style_context().add_class("stark-footer")

        lbl1 = Gtk.Label()
        lbl1.set_markup('<span color="#38bdf8" font_weight="bold">↵</span> <span color="#94a3b8">launch</span>')
        lbl2 = Gtk.Label()
        lbl2.set_markup('<span color="#38bdf8" font_weight="bold">↑↓</span> <span color="#94a3b8">navigate</span>')
        lbl3 = Gtk.Label()
        lbl3.set_markup('<span color="#38bdf8" font_weight="bold">esc</span> <span color="#94a3b8">close</span>')

        footer.pack_start(lbl1, False, False, 0)
        footer.pack_start(lbl2, False, False, 0)
        footer.pack_start(lbl3, False, False, 0)

        # Right branding
        brand = Gtk.Label()
        brand.set_markup('<span color="#38bdf8" font_weight="bold">STARK</span> <span color="#64748b">LAUNCHER</span>')
        footer.pack_end(brand, False, False, 0)

        container.pack_end(footer, False, False, 0)

        self.add(container)

    def _get_icon_image(self, icon_name, size=32):
        if icon_name in self.icon_cache:
            return Gtk.Image.new_from_pixbuf(self.icon_cache[icon_name])

        pix = None
        if os.path.isabs(icon_name) and os.path.exists(icon_name):
            try:
                pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_name, size, size, True)
            except Exception:
                pass
        elif icon_name:
            try:
                info = self.icon_theme.lookup_icon(icon_name, size, Gtk.IconLookupFlags.GENERIC_FALLBACK)
                if info:
                    pix = info.load_icon()
            except Exception:
                pass

        if not pix:
            try:
                info = self.icon_theme.lookup_icon("application-x-executable", size, Gtk.IconLookupFlags.GENERIC_FALLBACK)
                if info:
                    pix = info.load_icon()
            except Exception:
                pass

        if pix:
            # Scale to size if needed
            if pix.get_width() != size or pix.get_height() != size:
                pix = pix.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
            self.icon_cache[icon_name] = pix
            return Gtk.Image.new_from_pixbuf(pix)

        img = Gtk.Image()
        img.set_pixel_size(size)
        img.set_from_icon_name("application-x-executable", Gtk.IconSize.DND)
        return img

    def _filter_apps(self, query):
        q = query.strip().lower()
        if not q:
            self.filtered_apps = list(self.all_apps)
        else:
            matches = []
            for app in self.all_apps:
                name_l = app["name"].lower()
                exec_l = app["exec"].lower()
                desc_l = app["comment"].lower()
                score = 0

                if name_l.startswith(q):
                    score = 100 - len(name_l)
                elif q in name_l:
                    score = 70 - len(name_l)
                elif exec_l.startswith(q):
                    score = 50
                elif q in desc_l:
                    score = 30
                elif q in app["cat"].lower():
                    score = 20

                if score > 0:
                    matches.append((score, app))

            matches.sort(key=lambda x: x[0], reverse=True)
            self.filtered_apps = [m[1] for m in matches]

        self._render_apps_list()

    def _render_apps_list(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)

        self.row_widgets = []
        limit = min(30, len(self.filtered_apps))

        for idx in range(limit):
            app = self.filtered_apps[idx]
            row = Gtk.ListBoxRow()
            row.get_style_context().add_class("stark-app-row")

            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

            # Icon
            icon_img = self._get_icon_image(app["icon"], 28)
            hbox.pack_start(icon_img, False, False, 0)

            # Info
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            title = Gtk.Label(label=app["name"])
            title.set_xalign(0.0)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.get_style_context().add_class("stark-app-name")

            desc_text = app["comment"] or app["exec"].split()[0]
            desc = Gtk.Label(label=desc_text)
            desc.set_xalign(0.0)
            desc.set_ellipsize(Pango.EllipsizeMode.END)
            desc.get_style_context().add_class("stark-app-desc")

            vbox.pack_start(title, False, False, 0)
            vbox.pack_start(desc, False, False, 0)
            hbox.pack_start(vbox, True, True, 0)

            # Tag
            badge = Gtk.Label(label=app["cat"])
            badge.get_style_context().add_class("stark-app-badge")
            hbox.pack_end(badge, False, False, 0)

            row.add(hbox)
            row.show_all()
            self.listbox.add(row)
            self.row_widgets.append(row)

        self.count_badge.set_text(f"{len(self.filtered_apps)} apps")
        self.selected_index = 0
        self._highlight_selection()

    def _highlight_selection(self):
        for i, row in enumerate(self.row_widgets):
            ctx = row.get_style_context()
            if i == self.selected_index:
                ctx.add_class("selected")
                adj = self.scroll.get_vadjustment()
                row_alloc = row.get_allocation()
                if row_alloc.height > 0:
                    y = row_alloc.y
                    if y < adj.get_value():
                        adj.set_value(y)
                    elif y + row_alloc.height > adj.get_value() + adj.get_page_size():
                        adj.set_value(y + row_alloc.height - adj.get_page_size())
            else:
                ctx.remove_class("selected")

    def _on_search_changed(self, entry):
        self._filter_apps(entry.get_text())

    def _on_focus_in(self, widget, event):
        self.has_focused = True
        return False

    def _on_focus_out(self, widget, event):
        if self.has_focused:
            self.hide_launcher()
        return False

    def _on_key_press(self, widget, event):
        keyval = event.keyval
        # Escape -> Close
        if keyval == Gdk.KEY_Escape:
            self.hide_launcher()
            return True

        # Down Arrow / Tab / Ctrl+N / Ctrl+J
        elif keyval in [Gdk.KEY_Down, Gdk.KEY_Tab] or (
            event.state & Gdk.ModifierType.CONTROL_MASK and keyval in [Gdk.KEY_n, Gdk.KEY_j]
        ):
            if self.row_widgets:
                self.selected_index = (self.selected_index + 1) % len(self.row_widgets)
                self._highlight_selection()
            return True

        # Up Arrow / Shift+Tab / Ctrl+P / Ctrl+K
        elif keyval in [Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab] or (
            event.state & Gdk.ModifierType.CONTROL_MASK and keyval in [Gdk.KEY_p, Gdk.KEY_k]
        ):
            if self.row_widgets:
                self.selected_index = (self.selected_index - 1 + len(self.row_widgets)) % len(self.row_widgets)
                self._highlight_selection()
            return True

        # Enter -> Launch
        elif keyval in [Gdk.KEY_Return, Gdk.KEY_KP_Enter]:
            self._launch_selected()
            return True

        return False

    def _on_row_clicked(self, listbox, row):
        for i, r in enumerate(self.row_widgets):
            if r == row:
                self.selected_index = i
                self._launch_selected()
                break

    def _launch_selected(self):
        if not self.filtered_apps or self.selected_index >= len(self.filtered_apps):
            return
        app = self.filtered_apps[self.selected_index]
        exec_str = app["exec"]

        # Clean field codes
        tokens = shlex.split(exec_str)
        cleaned = [t for t in tokens if not (t.startswith('%') and len(t) == 2)]

        if app.get("terminal"):
            cmd = ["kitty", "-e"] + cleaned
        else:
            cmd = cleaned

        try:
            subprocess.Popen(cmd, start_new_session=True)
        except Exception as e:
            print("Launch error:", e)

        self.hide_launcher()

    def show_launcher(self):
        self.has_focused = False
        self.entry.set_text("")
        self._filter_apps("")
        self.show_all()
        self.present()
        GLib.timeout_add(300, lambda: setattr(self, 'has_focused', True))
        self.entry.grab_focus()

    def hide_launcher(self):
        self.has_focused = False
        self.hide()


class LauncherDaemon:
    def __init__(self):
        # Save PID file for clean process management
        with open("/tmp/stark_launcher.pid", "w") as f:
            f.write(str(os.getpid()))

        self.apps = get_desktop_apps()
        self.win = StarkLauncherWindow(self.apps)
        self.is_visible = False

        self._setup_socket()

    def _setup_socket(self):
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass

        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(SOCKET_PATH)
        self.sock.listen(5)
        self.sock.setblocking(False)

        GLib.io_add_watch(self.sock.fileno(), GLib.IO_IN, self._on_socket_ready)

    def _on_socket_ready(self, source, condition):
        try:
            conn, _ = self.sock.accept()
            data = conn.recv(1024).decode('utf-8').strip()
            if data == "toggle":
                self.toggle()
            elif data == "show":
                self.show()
            elif data == "hide":
                self.hide()
            conn.sendall(b"ok\n")
            conn.close()
        except Exception:
            pass
        return True

    def toggle(self):
        if self.win.get_visible():
            self.hide()
        else:
            self.show()

    def show(self):
        self.win.show_launcher()

    def hide(self):
        self.win.hide_launcher()


def send_ipc(command):
    if not os.path.exists(SOCKET_PATH):
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(SOCKET_PATH)
        s.sendall(f"{command}\n".encode('utf-8'))
        s.recv(1024)
        s.close()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    action = "toggle"
    if len(sys.argv) > 1:
        if sys.argv[1] in ["--show", "show"]:
            action = "show"
        elif sys.argv[1] in ["--hide", "hide"]:
            action = "hide"
        elif sys.argv[1] in ["--toggle", "toggle"]:
            action = "toggle"
        elif sys.argv[1] in ["--daemon", "daemon"]:
            action = "daemon"

    # Try communicating with existing daemon
    if action != "daemon" and send_ipc(action):
        sys.exit(0)

    # Otherwise, start daemon and execute requested action
    daemon = LauncherDaemon()
    if action in ["toggle", "show"]:
        daemon.show()
    Gtk.main()
