#!/usr/bin/env python3
"""
Zenify Discord Rich Presence (RPC) Daemon
==========================================
Rock-solid, zero-leak Discord Rich Presence for Zenify.
Connects directly to Discord's local UNIX socket (/run/user/1000/discord-ipc-0).
Features:
- Safe, non-blocking stream reads with exact buffer handling.
- Exponential backoff on disconnect (no socket spamming).
- Live dynamic scrubber timeline synced to mpv playback.
- Clean studio title and artist (no clutter).
- Official Spotify green logo badge.
- Single minimalist button: 'Play on Spotify'.
- Instant pause freeze and auto-clear on stop/exit.
"""

import os
import sys
import time
import json
import struct
import socket
import signal
import atexit
import urllib.parse
import re

CONFIG_DIR = os.path.expanduser("~/.config/stark-rice")
STATE_FILE = os.path.join(CONFIG_DIR, "music_state.json")
CONFIG_FILE = os.path.join(CONFIG_DIR, "zenify_config.json")
DEFAULT_CLIENT_ID = "1060514796564394014"
SPOTIFY_ICON = "https://raw.githubusercontent.com/walkxcode/dashboard-icons/main/png/spotify.png"

def get_client_id():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                return str(cfg.get("client_id", DEFAULT_CLIENT_ID))
        except Exception:
            pass
    return DEFAULT_CLIENT_ID

def clean_song_title(title, artist=""):
    t = title.strip()
    if " - " in t:
        parts = t.split(" - ", 1)
        if artist and artist.lower() in parts[0].lower():
            t = parts[1]
        elif not artist:
            artist = parts[0].strip()
            t = parts[1]

    t = re.sub(r'\s*[\(\[](?:Official|Lyric|Audio|Video|Visualizer|HD|4K|HQ|Remastered|Remaster|\d+K|MV|Music Video|Lyrics|Explicit|Audio Video|Music from|From the|Soundtrack)[^\)\]]*[\)\]]', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s*-\s*(?:Lyrics|Audio|Official Video|From the|Original Soundtrack)$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'[\U00010000-\U0010ffff]', '', t)
    return t.strip()

def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError("Socket connection closed by peer")
        buf.extend(chunk)
    return bytes(buf)

class ZenifyDiscordRPC:
    def __init__(self):
        self.client_id = get_client_id()
        self.sock = None
        self.connected = False
        self.last_track_key = None
        self.last_is_playing = None
        self.last_update_time = 0
        self.last_reported_pos = 0
        self.next_connect_time = 0

    def find_ipc_socket(self):
        bases = [
            f"/run/user/{os.getuid()}",
            os.environ.get("XDG_RUNTIME_DIR", ""),
            "/tmp"
        ]
        for base in bases:
            if not base or not os.path.isdir(base):
                continue
            for i in range(10):
                path = os.path.join(base, f"discord-ipc-{i}")
                if os.path.exists(path):
                    return path
        return None

    def connect(self):
        now = time.time()
        if now < self.next_connect_time:
            return False

        ipc_path = self.find_ipc_socket()
        if not ipc_path:
            self.next_connect_time = now + 8.0
            return False

        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(8.0)
            self.sock.connect(ipc_path)

            # Handshake opcode 0
            handshake = json.dumps({"v": 1, "client_id": self.client_id}).encode("utf-8")
            header = struct.pack("<II", 0, len(handshake))
            self.sock.sendall(header + handshake)

            resp_header = recv_exact(self.sock, 8)
            op, length = struct.unpack("<II", resp_header)
            resp_body = recv_exact(self.sock, length)
            data = json.loads(resp_body.decode("utf-8"))

            if op == 1 and data.get("evt") == "READY":
                self.connected = True
                self.next_connect_time = 0
                print(f"[Zenify RPC] Connected to Discord as {data.get('data', {}).get('user', {}).get('username')}")
                return True
            else:
                self.disconnect(backoff=8.0)
                return False
        except Exception as e:
            self.disconnect(backoff=8.0)
            return False

    def disconnect(self, backoff=5.0):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self.connected = False
        self.next_connect_time = time.time() + backoff

    def send_frame(self, opcode, payload):
        if not self.connected or not self.sock:
            return False
        try:
            self.sock.settimeout(8.0)
            body = json.dumps(payload).encode("utf-8")
            header = struct.pack("<II", opcode, len(body))
            self.sock.sendall(header + body)

            resp_h = recv_exact(self.sock, 8)
            op, length = struct.unpack("<II", resp_h)
            recv_exact(self.sock, length)
            return True
        except Exception as e:
            self.disconnect(backoff=5.0)
            return False

    def clear_activity(self):
        if not self.connected:
            return
        payload = {
            "cmd": "SET_ACTIVITY",
            "args": {
                "pid": os.getpid(),
                "activity": None
            },
            "nonce": str(time.time())
        }
        self.send_frame(1, payload)
        self.last_track_key = None

    def update_activity(self, title, artist, art_url, pos, duration, is_playing):
        clean_t = clean_song_title(title, artist)
        clean_a = artist.strip()

        if not clean_t or clean_t == "Nothing Playing":
            self.clear_activity()
            return

        now = time.time()
        start_ts = int(now - pos)
        end_ts = int(now - pos + duration) if duration > 0 else None

        search_q = urllib.parse.quote(f"{clean_t} {clean_a}")
        spotify_url = f"https://open.spotify.com/search/{search_q}"
        large_img = art_url if (art_url and art_url.startswith("http")) else SPOTIFY_ICON

        activity = {
            "type": 2,  # Listening to
            "details": clean_t[:127],
            "state": f"by {clean_a}"[:127] if clean_a else "Zenify Audio",
            "assets": {
                "large_image": large_img,
                "small_image": SPOTIFY_ICON,
                "small_text": "Spotify"
            },
            "buttons": [
                {"label": "Play on Spotify", "url": spotify_url}
            ]
        }

        # Real-time timeline: only provided when playing so pause cleanly freezes
        if is_playing and end_ts:
            activity["timestamps"] = {
                "start": start_ts,
                "end": end_ts
            }

        payload = {
            "cmd": "SET_ACTIVITY",
            "args": {
                "pid": os.getpid(),
                "activity": activity
            },
            "nonce": str(now)
        }

        self.send_frame(1, payload)
        self.last_update_time = now
        self.last_reported_pos = pos

    def tick(self):
        new_cid = get_client_id()
        if new_cid != self.client_id:
            self.client_id = new_cid
            self.disconnect(backoff=1.0)
            self.connect()

        if not self.connected:
            if not self.connect():
                return

        if not os.path.exists(STATE_FILE):
            return

        try:
            with open(STATE_FILE, "r") as f:
                st = json.load(f)
        except Exception:
            return

        title = st.get("title", "")
        artist = st.get("artist", "")
        art_url = st.get("art_url", "")
        pos = float(st.get("position", 0.0))
        dur = float(st.get("duration", 0.0))
        is_playing = bool(st.get("is_playing", False))

        track_key = f"{title}_{artist}"
        now = time.time()

        track_changed = (track_key != self.last_track_key)
        state_changed = (is_playing != self.last_is_playing)
        time_elapsed = now - self.last_update_time
        seek_detected = abs(pos - (self.last_reported_pos + time_elapsed)) > 3.5 if is_playing else False
        keepalive = (time_elapsed > 20.0)

        if track_changed or state_changed or seek_detected or keepalive:
            self.update_activity(title, artist, art_url, pos, dur, is_playing)
            self.last_track_key = track_key
            self.last_is_playing = is_playing

def main():
    rpc = ZenifyDiscordRPC()

    def cleanup():
        try:
            rpc.clear_activity()
            rpc.disconnect()
        except Exception:
            pass

    def sig_handler(sig, frame):
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    atexit.register(cleanup)

    print("[Zenify RPC] Starting daemon...")
    while True:
        try:
            rpc.tick()
        except Exception as e:
            print("[Zenify RPC] Error:", e)
        time.sleep(1.0)

if __name__ == "__main__":
    main()
