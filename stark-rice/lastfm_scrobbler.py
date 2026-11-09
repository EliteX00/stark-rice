#!/usr/bin/env python3
"""
Last.fm Authentication and Scrobbler for Zenify / Stark Rice
"""

import sys
import os
import time
import json
import hashlib
import requests

CONFIG_DIR = os.path.expanduser("~/.config/stark-rice")
AUTH_FILE = os.path.join(CONFIG_DIR, "lastfm_auth.json")

API_KEY = os.environ.get("LASTFM_API_KEY", "")
SECRET = os.environ.get("LASTFM_SECRET", "")

if not API_KEY and os.path.exists(AUTH_FILE):
    try:
        with open(AUTH_FILE) as f:
            _d = json.load(f)
            API_KEY = _d.get("api_key", "")
            SECRET = _d.get("secret", "")
    except Exception:
        pass


def sign_call(params, secret=SECRET):
    sig_str = "".join(f"{k}{params[k]}" for k in sorted(params.keys())) + secret
    return hashlib.md5(sig_str.encode("utf-8")).hexdigest()


def get_session(token):
    params = {
        "api_key": API_KEY,
        "method": "auth.getSession",
        "token": token
    }
    params["api_sig"] = sign_call(params)
    params["format"] = "json"

    try:
        r = requests.get("https://ws.audioscrobbler.com/2.0/", params=params, timeout=15)
        data = r.json()
        if "session" in data:
            session_info = {
                "api_key": API_KEY,
                "secret": SECRET,
                "username": data["session"]["name"],
                "session_key": data["session"]["key"]
            }
            with open(AUTH_FILE, "w") as f:
                json.dump(session_info, f, indent=2)
            print(f"Successfully authenticated as {session_info['username']}!")
            return session_info
        else:
            print("Response:", data)
    except Exception as e:
        print("Request error:", e)
    return None


def scrobble_track(session_key, title, artist, timestamp):
    params = {
        "api_key": API_KEY,
        "method": "track.scrobble",
        "sk": session_key,
        "track": title,
        "artist": artist,
        "timestamp": str(int(timestamp))
    }
    params["api_sig"] = sign_call(params)
    params["format"] = "json"

    try:
        r = requests.post("https://ws.audioscrobbler.com/2.0/", data=params, timeout=6)
        res = r.json()
        if "scrobbles" in res and res["scrobbles"].get("@attr", {}).get("accepted", 0) > 0:
            return True
        print(f"Scrobble result for '{title}':", res)
    except Exception as e:
        print(f"Error scrobbling '{title}':", e)
    return False


def scrobble_list(session_key, tracks):
    now = int(time.time())
    count = 0
    # Spread out timestamps realistically across the past few hours
    for i, t in enumerate(tracks):
        ts = now - ((len(tracks) - i) * 240)
        ok = scrobble_track(session_key, t["title"], t["artist"], ts)
        if ok:
            count += 1
            print(f"  ✓ Scrobbled [{count}/{len(tracks)}]: {t['artist']} - {t['title']}")
        time.sleep(0.3)
    return count


if __name__ == "__main__":
    token = sys.argv[1] if len(sys.argv) > 1 else ""
    if not token:
        print("Usage: python3 lastfm_scrobbler.py <auth_token>")
        sys.exit(1)
    print(f"Checking authorization for token: {token}...")
    sess = get_session(token)
    if sess:
        print("Authenticated! Proceeding to scrobble curated list...")
        # Curated 19 tracks
        CHOSEN_TRACKS = [
            {"title": "FE!N", "artist": "Travis Scott"},
            {"title": "Nightcrawler", "artist": "Travis Scott"},
            {"title": "All The Stars", "artist": "Kendrick Lamar"},
            {"title": "Hope", "artist": "XXXTENTACION"},
            {"title": "Up Up And Away", "artist": "Juice WRLD"},
            {"title": "MEMORIES", "artist": "347Aidan"},
            {"title": "Beat It", "artist": "Michael Jackson"},
            {"title": "Starboy", "artist": "The Weeknd"},
            {"title": "I Was Never There", "artist": "The Weeknd"},
            {"title": "Trouble", "artist": "Frank Ocean"},
            {"title": "Sunflower", "artist": "Post Malone & Swae Lee"},
            {"title": "Let Go", "artist": "Beau Young Prince"},
            {"title": "Cinnamon Girl", "artist": "Lana Del Rey"},
            {"title": "Summertime Sadness", "artist": "Lana Del Rey"},
            {"title": "Self Aware", "artist": "Temper City"},
            {"title": "bye (Altare Remix)", "artist": "Ariana Grande"},
            {"title": "snowfall", "artist": "øneheart x reidenshi"},
            {"title": "Interstellar Soundtrack", "artist": "Hans Zimmer"},
            {"title": "Faded", "artist": "Alan Walker"}
        ]
        n = scrobble_list(sess["session_key"], CHOSEN_TRACKS)
        print(f"Successfully scrobbled {n} tracks to user {sess['username']}!")
    else:
        print("Not yet authorized. Please click 'Yes, allow access' in your browser.")
