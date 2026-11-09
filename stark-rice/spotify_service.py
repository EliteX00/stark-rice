#!/usr/bin/env python3
"""
Stark Rice Spotify Service
Handles OAuth 2.0 PKCE/Authorization Code Flow, Token Refresh,
Official Spotify Search, and User Account Taste Profile (Top Tracks, Liked Songs, Recents).
"""

import os
import sys
import time
import json
import base64
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
import threading

CONFIG_DIR = os.path.expanduser("~/.config/stark-rice")
AUTH_FILE = os.path.join(CONFIG_DIR, "spotify_auth.json")
CACHE_FILE = os.path.join(CONFIG_DIR, "spotify_taste_cache.json")

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

if (not CLIENT_ID or not CLIENT_SECRET) and os.path.exists(AUTH_FILE):
    try:
        with open(AUTH_FILE) as f:
            _d = json.load(f)
            CLIENT_ID = CLIENT_ID or _d.get("client_id", "")
            CLIENT_SECRET = CLIENT_SECRET or _d.get("client_secret", "")
    except Exception:
        pass
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "user-top-read user-library-read user-read-recently-played playlist-read-private"


class CallbackServer(BaseHTTPRequestHandler):
    auth_code = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/callback":
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params:
                CallbackServer.auth_code = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = """
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Zenify • Spotify Connected</title>
                    <style>
                        body { background: #0b0f19; color: #fff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
                        .card { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 20px; padding: 40px; text-align: center; max-width: 400px; box-shadow: 0 20px 40px rgba(0,0,0,0.5); }
                        h1 { color: #1DB954; font-size: 28px; margin: 0 0 10px; }
                        p { color: #94a3b8; font-size: 14px; line-height: 1.5; }
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h1>Spotify Connected</h1>
                        <p>Zenify has been authorized with your Spotify account. You can close this tab and return to your music.</p>
                    </div>
                </body>
                </html>
                """
                self.wfile.write(html.encode("utf-8"))
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Authorization failed or denied.")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Quiet stdout


class SpotifyService:
    def __init__(self):
        self.auth_data = self._load_auth()

    def _load_auth(self):
        if os.path.exists(AUTH_FILE):
            try:
                with open(AUTH_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_auth(self):
        try:
            os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
            with open(AUTH_FILE, "w") as f:
                json.dump(self.auth_data, f, indent=2)
        except Exception:
            pass

    def is_authenticated(self):
        return bool(self.auth_data.get("refresh_token"))

    def start_auth_flow(self):
        """Starts a local HTTP server and opens browser for Spotify OAuth."""
        CallbackServer.auth_code = None
        server = HTTPServer(("127.0.0.1", 8888), CallbackServer)
        server.timeout = 300

        auth_params = {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "show_dialog": "true"
        }
        auth_url = f"https://accounts.spotify.com/authorize?{urllib.parse.urlencode(auth_params)}"
        print(f"\n[Spotify OAuth] Opening browser to authorize Spotify account:\n{auth_url}\n")
        
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass

        # Handle single request
        start_t = time.time()
        while not CallbackServer.auth_code and (time.time() - start_t) < 300:
            server.handle_request()

        server.server_close()

        if CallbackServer.auth_code:
            print("[Spotify OAuth] Received authorization code. Exchanging for tokens...")
            return self._exchange_code_for_tokens(CallbackServer.auth_code)
        else:
            print("[Spotify OAuth] Timed out waiting for authorization callback.", file=sys.stderr)
            return False

    def _exchange_code_for_tokens(self, code):
        auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI
        }).encode()

        req = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=data,
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                tokens = json.loads(resp.read().decode())
                self.auth_data = {
                    "access_token": tokens.get("access_token"),
                    "refresh_token": tokens.get("refresh_token"),
                    "expires_at": int(time.time()) + int(tokens.get("expires_in", 3600)) - 60,
                    "scope": tokens.get("scope", "")
                }
                self._save_auth()
                print("[Spotify OAuth] Authorization successful! Tokens saved.")
                return True
        except Exception as e:
            print(f"[Spotify OAuth] Token exchange failed: {e}", file=sys.stderr)
            return False

    def get_valid_token(self):
        """Returns a valid access token, auto-refreshing if expired."""
        if not self.is_authenticated():
            return None

        # Check expiration
        expires_at = self.auth_data.get("expires_at", 0)
        if time.time() < expires_at and self.auth_data.get("access_token"):
            return self.auth_data.get("access_token")

        # Refresh
        refresh_token = self.auth_data.get("refresh_token")
        if not refresh_token:
            return None

        auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }).encode()

        req = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=data,
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                tokens = json.loads(resp.read().decode())
                self.auth_data["access_token"] = tokens.get("access_token")
                self.auth_data["expires_at"] = int(time.time()) + int(tokens.get("expires_in", 3600)) - 60
                if tokens.get("refresh_token"):
                    self.auth_data["refresh_token"] = tokens.get("refresh_token")
                self._save_auth()
                return self.auth_data["access_token"]
        except Exception:
            return None

    def search_tracks(self, query, limit=10):
        """Searches Spotify official catalog with user token."""
        token = self.get_valid_token()
        if not token:
            return []

        url = f"https://api.spotify.com/v1/search?q={urllib.parse.quote(query)}&type=track&limit={limit}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                items = data.get("tracks", {}).get("items", [])
                results = []
                for it in items:
                    artists = ", ".join([a.get("name", "") for a in it.get("artists", [])])
                    art_url = ""
                    images = it.get("album", {}).get("images", [])
                    if images:
                        art_url = images[0].get("url", "")

                    results.append({
                        "title": it.get("name", ""),
                        "artist": artists,
                        "album": it.get("album", {}).get("name", ""),
                        "art_url": art_url,
                        "duration": int(it.get("duration_ms", 0) / 1000),
                        "popularity": it.get("popularity", 0),
                        "spotify_id": it.get("id", "")
                    })
                return results
        except Exception:
            return []

    def get_account_taste(self):
        """Pulls user top tracks, liked songs, and recently played from Spotify."""
        token = self.get_valid_token()
        if not token:
            return []

        tracks = []
        seen = set()

        endpoints = [
            ("https://api.spotify.com/v1/me/top/tracks?limit=25&time_range=short_term", "items"),
            ("https://api.spotify.com/v1/me/top/tracks?limit=25&time_range=medium_term", "items"),
            ("https://api.spotify.com/v1/me/tracks?limit=30", "items_nested"),
            ("https://api.spotify.com/v1/me/player/recently-played?limit=30", "items_history")
        ]

        for url, kind in endpoints:
            try:
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    data = json.loads(resp.read().decode())
                    items = data.get("items", [])
                    for raw in items:
                        it = raw if kind == "items" else (raw.get("track") if isinstance(raw, dict) else None)
                        if not it or not isinstance(it, dict) or not it.get("name"):
                            continue

                        name = it.get("name", "")
                        artists = ", ".join([a.get("name", "") for a in it.get("artists", [])])
                        k = f"{name.lower()} - {artists.lower()}"
                        if k in seen:
                            continue
                        seen.add(k)

                        images = it.get("album", {}).get("images", [])
                        art_url = images[0].get("url", "") if images else ""

                        tracks.append({
                            "title": name,
                            "artist": artists,
                            "art_url": art_url,
                            "duration": int(it.get("duration_ms", 0) / 1000),
                            "spotify_id": it.get("id", "")
                        })
            except Exception:
                pass

        return tracks


def main():
    service = SpotifyService()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--auth":
            ok = service.start_auth_flow()
            if ok:
                taste = service.get_account_taste()
                print(f"Successfully retrieved {len(taste)} personalized tracks from your Spotify account!")
        elif cmd == "--status":
            auth = service.is_authenticated()
            print("Spotify Authenticated:", auth)
            if auth:
                token = service.get_valid_token()
                print("Valid Token:", bool(token))
        elif cmd == "--search":
            q = sys.argv[2] if len(sys.argv) > 2 else "After Dark"
            res = service.search_tracks(q)
            print(json.dumps(res, indent=2))
        elif cmd == "--taste":
            taste = service.get_account_taste()
            print(json.dumps(taste, indent=2))
    else:
        auth = service.is_authenticated()
        print("Spotify Authenticated:", auth)


if __name__ == "__main__":
    main()
