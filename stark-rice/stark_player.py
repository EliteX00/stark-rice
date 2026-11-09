#!/usr/bin/env python3
"""
Stark Audio Player Backend
===========================
Spotify metadata, playlists, and recommendations + YouTube (yt-dlp/mpv) audio playback engine.
With Listening History Tracking, Official Music Catalog Resolution (Spotify & iTunes),
Clean Track Sanitization (No long videos / YouTube spam), and Smart Continuous Autoplay.
"""

import sys
import os
import json
import time
import socket
import hashlib
import random
import requests
import re
import subprocess
import threading
import concurrent.futures
import sqlite3
import shutil
import urllib.parse
from urllib.parse import quote_plus
from ytmusicapi import YTMusic
from ytmusicapi.helpers import get_authorization

CONFIG_DIR = os.path.expanduser("~/.config/stark-rice")
ASSETS_DIR = os.path.join(CONFIG_DIR, "assets")
THUMB_CACHE_DIR = os.path.join(ASSETS_DIR, "album_thumbs")
STATE_FILE = os.path.join(CONFIG_DIR, "music_state.json")
HISTORY_FILE = os.path.join(CONFIG_DIR, "listening_history.json")
PLAYLIST_CACHE_FILE = os.path.join(CONFIG_DIR, "spotify_cache.json")
AUTH_FILE = os.path.join(CONFIG_DIR, "ytmusic_auth.json")
QUEUE_CACHE_FILE = os.path.join(CONFIG_DIR, "recommendation_queue.json")
LASTFM_AUTH_FILE = os.path.join(CONFIG_DIR, "lastfm_auth.json")
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "")
if not LASTFM_API_KEY and os.path.exists(LASTFM_AUTH_FILE):
    try:
        with open(LASTFM_AUTH_FILE) as f:
            LASTFM_API_KEY = json.load(f).get("api_key", "")
    except Exception:
        pass
SOCKET_PATH = "/tmp/stark_player.sock"

os.makedirs(THUMB_CACHE_DIR, exist_ok=True)

# Curated Spotify Official Playlists
SPOTIFY_PLAYLISTS = {
    "top_hits": {
        "id": "37i9dQZF1DXcBWIGoYBM5M",
        "name": "Today's Top Hits",
        "icon": "󰓇"
    },
    "synthwave": {
        "id": "37i9dQZF1DXdLEN7aqioXM",
        "name": "Retrowave & Synth",
        "icon": "󰎆"
    },
    "chill": {
        "id": "37i9dQZF1DX4WYpdgoIcn6",
        "name": "Chill Hits & Lo-Fi",
        "icon": "󰠃"
    },
    "rock": {
        "id": "37i9dQZF1DWXRqgorJj26U",
        "name": "Rock Classics",
        "icon": "󰓇"
    },
    "global_top": {
        "id": "37i9dQZEVXbMDoHDwVN2tF",
        "name": "Top 50 - Global",
        "icon": "󰋋"
    }
}

# Blacklist filter for YouTube playlist dumps, 10-hour loops, and compilation spam
SPAM_PATTERNS = [
    re.compile(r'\b(?:\d+|one|ten)\s*hours?(?:\s+loop)?\b', re.IGNORECASE),
    re.compile(r'\bfull\s+(?:album|discography|concert)\b', re.IGNORECASE),
    re.compile(r'\b(?:greatest\s+hits|best\s+songs|top\s+tracks|compilation|collection)\b', re.IGNORECASE),
    re.compile(r'\bevery\s+song\b', re.IGNORECASE),
    re.compile(r'\b10\s*hours\b', re.IGNORECASE),
    re.compile(r'\b1\s*hour\s+loop\b', re.IGNORECASE),
    re.compile(r'\b(?:over\s+slowed|slowed\s*\+\s*reverb|slowed\s+and\s+reverb|sped\s+up|bass\s+boosted)\b', re.IGNORECASE),
]

def is_valid_track(title, duration, is_official=False):
    """Rejects long videos, multi-track playlists, and spam compilations."""
    if not title:
        return False
    # Max duration 15 minutes (900s) for extended songs, minimum 30s
    if duration > 900 or (duration > 0 and duration < 30):
        return False
    if is_official:
        return True
    t_low = title.lower()
    for pat in SPAM_PATTERNS:
        if pat.search(t_low):
            return False
    return True

def sanitize_title(raw_title, artist=""):
    """Strips YouTube noise suffixes to restore original official song names."""
    t = raw_title.strip()
    if " - " in t:
        parts = t.split(" - ", 1)
        if artist and artist.lower() in parts[0].lower():
            t = parts[1]
        elif not artist:
            artist = parts[0].strip()
            t = parts[1]

    # Remove (Official Video), (Audio), (Lyrics), (Music from...), etc.
    t = re.sub(r'\s*[\(\[](?:Official|Lyric|Audio|Video|Visualizer|HD|4K|HQ|Remastered|Remaster|\d+K|MV|Music Video|Lyrics|Explicit|Audio Video|Music from|From the|Soundtrack)[^\)\]]*[\)\]]', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s*-\s*(?:Lyrics|Audio|Official Video|From the|Original Soundtrack)$', '', t, flags=re.IGNORECASE)
    # Remove unicode emojis
    t = re.sub(r'[\U00010000-\U0010ffff]', '', t)
    return t.strip()

def canonical_track_key(title, artist=""):
    """
    Produces a normalized canonical key for strict anti-duplicate matching.
    Strips ALL parenthetical annotations, bracket text, feature credits, and punctuation.
    """
    t = (title or "").lower().strip()
    t = re.sub(r'[\(\[][^\)\]]*[\)\]]', '', t)
    t = re.sub(r'\s+(?:feat|ft\.|featuring|with)\s+.*$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()

    a = (artist or "").lower().strip()
    a = re.split(r'[,&]|\s+feat\b|\s+ft\b', a)[0].strip()
    a = re.sub(r'[^\w\s]', '', a)
    a = re.sub(r'\s+', ' ', a).strip()
    return f"{t} - {a}"

def canonical_artist_key(artist):
    """Normalizes artist name for fatigue and clustering guards."""
    a = (artist or "").lower().strip()
    a = re.split(r'[,&]|\s+feat\b|\s+ft\b', a)[0].strip()
    a = re.sub(r'[^\w\s]', '', a)
    return re.sub(r'\s+', ' ', a).strip()


class TasteRecommendationEngine:
    """
    Hybrid Persistent Music Recommendation Engine
    - Contextual streaming graph from Deezer API (Smart Radio & Peer Artists)
    - Collaborative Filtering from Last.fm API (Audioscrobbler User Affinity Matrix)
    - Persistent listen dwell-time & skip cooldown integration
    - Pure transport: zero reliance on YouTube recommendation algorithms
    """
    def __init__(self):
        self.auth_file = AUTH_FILE
        self.is_authenticated = False
        try:
            if os.path.exists(self.auth_file):
                self.yt = YTMusic(self.auth_file)
                self.is_authenticated = True
            else:
                self.yt = YTMusic()
        except Exception:
            self.yt = None

        self.cached_queue = self._load_queue_cache()
        self._artist_id_cache = {}

    def _load_queue_cache(self):
        if os.path.exists(QUEUE_CACHE_FILE):
            try:
                with open(QUEUE_CACHE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_queue_cache(self):
        try:
            with open(QUEUE_CACHE_FILE, "w") as f:
                json.dump(self.cached_queue, f, indent=2)
        except Exception:
            pass

    def sync_cloud_history(self, video_id):
        if not self.is_authenticated or not self.yt or not video_id:
            return False
        def _do_sync():
            try:
                song = self.yt.get_song(video_id)
                self.yt.add_history_item(song)
            except Exception:
                pass
        threading.Thread(target=_do_sync, daemon=True).start()
        return True

    def _deezer_get(self, path):
        url = f"https://api.deezer.com/{path}"
        try:
            resp = requests.get(url, headers={"User-Agent": "ZenifyRecommender/1.0"}, timeout=4.5)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def _lastfm_get(self, method, params):
        params["method"] = method
        params["api_key"] = LASTFM_API_KEY
        params["format"] = "json"
        url = "https://ws.audioscrobbler.com/2.0/?" + urllib.parse.urlencode(params)
        try:
            resp = requests.get(url, headers={"User-Agent": "ZenifyRecommender/1.0"}, timeout=4.5)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def get_deezer_artist_id(self, artist_name):
        a_clean = artist_name.strip()
        if not a_clean or a_clean in ("Zenify", "YouTube"):
            return None
        if a_clean in self._artist_id_cache:
            return self._artist_id_cache[a_clean]
        res = self._deezer_get(f"search/artist?q={urllib.parse.quote(a_clean)}")
        data = res.get("data", [])
        if data:
            aid = data[0].get("id")
            self._artist_id_cache[a_clean] = aid
            return aid
        return None

    def fetch_lastfm_top_tracks(self, artist_name, limit=4):
        a_clean = artist_name.strip()
        if not a_clean or a_clean in ("Zenify", "YouTube"):
            return []
        res = self._lastfm_get("artist.gettoptracks", {"artist": a_clean, "limit": limit})
        tracks = []
        for t in res.get("toptracks", {}).get("track", [])[:limit]:
            title = sanitize_title(t.get("name", ""))
            art = t.get("artist", {}).get("name", a_clean)
            imgs = t.get("image", [])
            cover = ""
            if imgs:
                cover = imgs[-1].get("#text", "")
                if cover:
                    cover = cover.replace("/300x300/", "/600x600/")
            dur = int(t.get("duration", 0) or 0)
            if title and art and is_valid_track(title, dur, is_official=True):
                # Anti-romance filter
                low = f"{title.lower()} {art.lower()}"
                if any(bad in low for bad in ["love song", "mariah carey", "romance", "romantic", "sped up tiktok", "teen pop", "sweetheart", "lovesick", "acoustic love"]):
                    continue
                tracks.append({
                    "title": title,
                    "artist": art,
                    "art_url": cover,
                    "duration": dur,
                    "yt_id": "",
                    "source": f"Top Track ({art})"
                })
        return tracks

    def fetch_collaborative_similar(self, artist_name, limit=6):
        res = self._lastfm_get("artist.getsimilar", {"artist": artist_name, "limit": limit})
        similar = res.get("similarartists", {}).get("artist", [])
        if isinstance(similar, dict):
            similar = [similar]
        results = []
        for s in similar:
            s_name = s.get("name")
            s_match = float(s.get("match", 0.0))
            if s_name:
                results.append((s_name, s_match))
        return results

    def fetch_tag_top_tracks(self, tag, limit=8):
        res = self._lastfm_get("tag.gettoptracks", {"tag": tag, "limit": limit})
        tracks = []
        for t in res.get("tracks", {}).get("track", [])[:limit]:
            title = sanitize_title(t.get("name", ""))
            art = t.get("artist", {}).get("name", "")
            imgs = t.get("image", [])
            cover = imgs[-1].get("#text", "") if imgs else ""
            if cover:
                cover = cover.replace("/300x300/", "/600x600/")
            dur = int(t.get("duration", 0) or 0)
            if title and art and is_valid_track(title, dur, is_official=True):
                tracks.append({
                    "title": title,
                    "artist": art,
                    "art_url": cover,
                    "duration": dur,
                    "yt_id": "",
                    "source": f"Tag ({tag})"
                })
        return tracks

    def recommend_autoplay(self, current_title, current_artist, current_yt_id=None, recent_history=None, affinity_data=None):
        recent_history = recent_history or []
        affinity_data = affinity_data or {}
        now = int(time.time())
        cooldowns = affinity_data.get("cooldown_skips", {})
        artist_affinity = affinity_data.get("artist_affinity", {})
        track_affinity = affinity_data.get("track_affinity", {})
        last_played_map = affinity_data.get("last_played_at", {})

        # Strict Anti-Repeat: check the last 80 tracks in history
        recent_keys = {canonical_track_key(h.get("title", ""), h.get("artist", "")) for h in recent_history[:80]}
        if current_title and current_artist:
            recent_keys.add(canonical_track_key(current_title, current_artist))

        # Artist Fatigue Guard: check recent artists (max 2 consecutive from same artist)
        recent_artists = [canonical_artist_key(h.get("artist", "")) for h in recent_history[:2] if h.get("artist")]
        current_canonical_artist = canonical_artist_key(current_artist)
        overplayed_artist = None
        if len(recent_artists) >= 2 and recent_artists[0] == recent_artists[1] and recent_artists[0]:
            overplayed_artist = recent_artists[0]
        elif current_canonical_artist and len(recent_artists) >= 1 and recent_artists[0] == current_canonical_artist:
            overplayed_artist = current_canonical_artist

        def is_blocked(cand):
            c_t = cand.get("title", "")
            c_a = cand.get("artist", "")
            c_key = canonical_track_key(c_t, c_a)
            # Anti-romance filter
            low = f"{c_t.lower()} {c_a.lower()}"
            if any(bad in low for bad in ["love song", "mariah carey", "romance", "romantic", "sped up tiktok", "teen pop", "sweetheart", "lovesick", "acoustic love"]):
                return True
            # 1. Blocked if played within the last 80 tracks
            if c_key in recent_keys:
                return True
            # 2. Blocked if played within the last 4 hours (14400s)
            last_t = last_played_map.get(c_key, 0)
            if now - last_t < (4 * 3600):
                return True
            # 3. Blocked if in skip cooldown (48h)
            raw_k = f"{c_t.lower().strip()} - {c_a.lower().strip()}".strip()
            if (raw_k in cooldowns and now < cooldowns[raw_k]) or (c_key in cooldowns and now < cooldowns[c_key]):
                return True
            # 4. Artist clumping guard (don't play 3 in a row from same artist)
            if overplayed_artist and canonical_artist_key(c_a) == overplayed_artist:
                return True
            return False

        def score_candidate(cand):
            c_t = cand.get("title", "")
            c_a = cand.get("artist", "")
            raw_k = f"{c_t.lower().strip()} - {c_a.lower().strip()}".strip()
            score = 1.0 + (artist_affinity.get(c_a, 0.0) * 0.25) + (track_affinity.get(raw_k, 0.0) * 0.3)
            return score

        # 1. Take viable track from existing cached queue
        viable_cached = []
        for i, cand in enumerate(list(self.cached_queue)):
            if is_blocked(cand):
                continue
            sc = score_candidate(cand)
            viable_cached.append((sc, i, cand))

        if viable_cached:
            viable_cached.sort(key=lambda x: x[0], reverse=True)
            top_slice = viable_cached[:min(4, len(viable_cached))]
            weights = [max(0.1, x[0]) for x in top_slice]
            chosen_tuple = random.choices(top_slice, weights=weights, k=1)[0]
            best_idx = chosen_tuple[1]
            chosen = chosen_tuple[2]
            self.cached_queue.pop(best_idx)
            self._save_queue_cache()

            chosen_key = canonical_track_key(chosen.get("title", ""), chosen.get("artist", ""))
            last_played_map[chosen_key] = now
            return chosen

        # 2. Refill queue dynamically via Last.fm Collaborative Graph
        top_profile_artists = sorted(affinity_data.get("artist_counts", {}).items(), key=lambda x: x[1], reverse=True)
        profile_artists = [a[0] for a in top_profile_artists[:10] if a[0] not in ("Zenify", "YouTube")]
        if not profile_artists:
            profile_artists = ["Travis Scott", "Frank Ocean", "The Weeknd", "Lana Del Rey", "Juice WRLD", "Kendrick Lamar"]

        eligible_pool = [a for a in profile_artists if canonical_artist_key(a) != overplayed_artist]
        random.shuffle(eligible_pool)
        seed_artists = eligible_pool[:3]

        candidates = []
        for a in seed_artists:
            similar = self.fetch_collaborative_similar(a, limit=3)
            for sim_a, _ in similar:
                top_t = self.fetch_lastfm_top_tracks(sim_a, limit=3)
                candidates.extend(top_t)

        scored = []
        seen = set()
        for cand in candidates:
            c_key = canonical_track_key(cand.get("title", ""), cand.get("artist", ""))
            if c_key in seen or is_blocked(cand):
                continue
            seen.add(c_key)
            sc = score_candidate(cand)
            scored.append((sc, cand))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            top_slice = scored[:min(4, len(scored))]
            weights = [max(0.1, x[0]) for x in top_slice]
            chosen_tuple = random.choices(top_slice, weights=weights, k=1)[0]
            chosen = chosen_tuple[1]

            self.cached_queue = [x[1] for x in scored if canonical_track_key(x[1].get("title", ""), x[1].get("artist", "")) != canonical_track_key(chosen.get("title", ""), chosen.get("artist", ""))]
            self._save_queue_cache()

            chosen_key = canonical_track_key(chosen.get("title", ""), chosen.get("artist", ""))
            last_played_map[chosen_key] = now
            return chosen

        # Safe fallback: pick any non-blocked track from history
        for h in recent_history:
            if not is_blocked(h):
                return h

        return {
            "title": "Nights",
            "artist": "Frank Ocean",
            "duration": 307,
            "art_url": "",
            "yt_id": ""
        }

    def generate_daily_suggestions(self, top_artists, top_tracks, history):
        if not top_artists:
            top_artists = ["Travis Scott", "Frank Ocean", "The Weeknd", "Lana Del Rey", "Juice WRLD", "Kendrick Lamar"]

        candidates = []
        # First include user seed tracks from history if any
        for h in history[:15]:
            candidates.append({
                "title": h.get("title", ""),
                "artist": h.get("artist", ""),
                "art_url": h.get("art_url", ""),
                "duration": h.get("duration", 0),
                "yt_id": h.get("yt_id", ""),
                "source": "Seeded Taste Profile"
            })

        # Fetch Last.fm peer artist recommendations
        for art in top_artists[:5]:
            sim = self.fetch_collaborative_similar(art, limit=3)
            for sim_a, _ in sim:
                top_t = self.fetch_lastfm_top_tracks(sim_a, limit=2)
                for t in top_t:
                    t["source"] = f"Last.fm Collab (via {art})"
                    candidates.append(t)

        final_suggestions = []
        seen = set()
        for t in candidates:
            ttl = t.get("title", "").strip()
            art = t.get("artist", "").strip()
            if not ttl or not art:
                continue
            k = f"{ttl.lower()}_{art.lower()}"
            if k not in seen:
                seen.add(k)
                final_suggestions.append(t)

        return final_suggestions[:45]

class ListeningHistoryManager:
    """Tracks user listening history and generates YouTube-tailored recommendations."""
    def __init__(self):
        self.data = {
            "history": [],
            "artist_counts": {},
            "track_counts": {},
            "autoplay_enabled": True,
            "daily_mix": [],
            "daily_mix_date": ""
        }
        self._load()
        self.rec_engine = TasteRecommendationEngine()
        self.yt_engine = self.rec_engine

    def _load(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    self.data.update(json.load(f))
            except Exception:
                pass
        if "last_played_at" not in self.data:
            self.data["last_played_at"] = {}
        for h in self.data.get("history", []):
            k = canonical_track_key(h.get("title", ""), h.get("artist", ""))
            t = h.get("timestamp", 0)
            if k not in self.data["last_played_at"] or t > self.data["last_played_at"][k]:
                self.data["last_played_at"][k] = t

    def _save(self):
        try:
            with open(HISTORY_FILE, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    @property
    def autoplay_enabled(self):
        return self.data.get("autoplay_enabled", True)

    def set_autoplay(self, enabled):
        self.data["autoplay_enabled"] = bool(enabled)
        self._save()

    def record_listen(self, title, artist, art_url="", yt_id="", duration=0):
        clean_t = sanitize_title(title, artist)
        if not clean_t or clean_t in ("Nothing Playing", "Track"):
            return

        now = int(time.time())
        entry = {
            "title": clean_t,
            "artist": artist.strip(),
            "art_url": art_url,
            "yt_id": yt_id,
            "duration": duration,
            "timestamp": now,
            "time_str": time.strftime("%b %d, %H:%M")
        }

        self.data["history"].insert(0, entry)
        if len(self.data["history"]) > 300:
            self.data["history"] = self.data["history"][:300]

        if "last_played_at" not in self.data:
            self.data["last_played_at"] = {}
        c_key = canonical_track_key(clean_t, artist)
        self.data["last_played_at"][c_key] = now

        a_clean = artist.strip()
        if a_clean and a_clean != "YouTube":
            self.data["artist_counts"][a_clean] = self.data["artist_counts"].get(a_clean, 0) + 1

        t_key = f"{clean_t} - {a_clean}"
        self.data["track_counts"][t_key] = self.data["track_counts"].get(t_key, 0) + 1

        self._save()

        # Auto-scrobble to user's Last.fm account (mrmeowx)
        try:
            from lastfm_scrobbler import scrobble_track, AUTH_FILE
            if os.path.exists(AUTH_FILE):
                with open(AUTH_FILE, "r") as f:
                    auth_d = json.load(f)
                sk = auth_d.get("session_key")
                if sk:
                    threading.Thread(target=scrobble_track, args=(sk, clean_t, a_clean, now), daemon=True).start()
        except Exception:
            pass

    def record_dwell_affinity(self, title, artist, dwell_sec, duration):
        """
        Updates affinity scores and skip penalties based on actual watch time.
        - Dwell >= 45s or completion >= 40%: +3.0 track affinity, +1.5 artist affinity
        - Dwell < 25s (skip): -5.0 penalty, 48h cooldown
        """
        clean_t = sanitize_title(title, artist)
        if not clean_t or clean_t in ("Nothing Playing", "Track"):
            return

        t_key = f"{clean_t.lower()} - {artist.lower()}".strip()
        a_key = artist.strip()
        ratio = (dwell_sec / duration) if duration > 0 else 0.0

        if "track_affinity" not in self.data:
            self.data["track_affinity"] = {}
        if "artist_affinity" not in self.data:
            self.data["artist_affinity"] = {}
        if "cooldown_skips" not in self.data:
            self.data["cooldown_skips"] = {}

        now = int(time.time())

        # High Affinity: listened >= 45s or >= 40% completion
        if dwell_sec >= 45.0 or (duration > 15.0 and ratio >= 0.40):
            self.data["track_affinity"][t_key] = self.data["track_affinity"].get(t_key, 0.0) + 3.0
            if a_key:
                self.data["artist_affinity"][a_key] = self.data["artist_affinity"].get(a_key, 0.0) + 1.5
            # Clear any old cooldown
            self.data["cooldown_skips"].pop(t_key, None)
            print(f"[Affinity System] High engagement for '{clean_t}' ({int(dwell_sec)}s). Affinity score: {self.data['track_affinity'][t_key]}")

        # Skip / Low Affinity: skipped under 25s
        elif dwell_sec < 25.0 and (duration == 0 or ratio < 0.25):
            self.data["track_affinity"][t_key] = self.data["track_affinity"].get(t_key, 0.0) - 5.0
            self.data["cooldown_skips"][t_key] = now + (48 * 3600)  # 48h cooldown
            print(f"[Affinity System] Skipped early: '{clean_t}' ({int(dwell_sec)}s). Penalized & cooled down for 48h.")

        self._save()

    def get_top_artists(self, limit=5):
        sorted_artists = sorted(self.data.get("artist_counts", {}).items(), key=lambda x: x[1], reverse=True)
        return [a[0] for a in sorted_artists[:limit]]

    def get_top_tracks(self, limit=5):
        top = []
        seen = set()
        for h in self.data.get("history", []):
            k = h.get("title", "").lower()
            if k and k not in seen:
                seen.add(k)
                top.append(h)
                if len(top) >= limit:
                    break
        return top

    def get_history(self, limit=50):
        return self.data.get("history", [])[:limit]

    def get_daily_suggestions(self):
        today_str = time.strftime("%Y-%m-%d")
        if self.data.get("daily_mix") and self.data.get("daily_mix_date") == today_str and len(self.data["daily_mix"]) >= 10:
            return self.data["daily_mix"]

        return self.generate_daily_suggestions()

    def generate_daily_suggestions(self):
        top_artists = self.get_top_artists(limit=8)
        top_tracks = self.get_top_tracks(limit=8)

        # Check Spotify account taste (top tracks, liked songs, recently played)
        spotify_taste = []
        try:
            from spotify_service import SpotifyService
            sp = SpotifyService()
            if sp.is_authenticated():
                spotify_taste = sp.get_account_taste()
        except Exception:
            pass

        if spotify_taste:
            # Combine Spotify taste seeds with user top tracks
            seed_pool = [t.get("artist") for t in spotify_taste if t.get("artist")]
            top_artists = list(dict.fromkeys(seed_pool[:5] + top_artists))

        mix = self.rec_engine.generate_daily_suggestions(top_artists, top_tracks, self.data.get("history", []))

        # Merge with Spotify personal tracks if available
        if spotify_taste:
            seen = {f"{t.get('title','').lower()}_{t.get('artist','').lower()}" for t in mix}
            for sp_trk in spotify_taste[:10]:
                k = f"{sp_trk.get('title','').lower()}_{sp_trk.get('artist','').lower()}"
                if k not in seen:
                    seen.add(k)
                    mix.insert(0, sp_trk)

        self.data["daily_mix"] = mix
        self.data["daily_mix_date"] = time.strftime("%Y-%m-%d")
        self._save()
        return mix

    def recommend_autoplay_track(self, current_title, current_artist, current_yt_id=None):
        return self.rec_engine.recommend_autoplay(
            current_title, current_artist, current_yt_id,
            recent_history=self.data.get("history", []),
            affinity_data=self.data
        )


class StarkPlayerBackend:
    def __init__(self):
        self._ensure_mpv()
        self.history_mgr = ListeningHistoryManager()
        self.state = {
            "title": "Nothing Playing",
            "artist": "Zenify",
            "art_path": os.path.join(ASSETS_DIR, "after_dark.png"),
            "art_url": "",
            "is_playing": False,
            "position": 0.0,
            "duration": 0.0,
            "progress": 0.0,
            "volume": 80,
            "autoplay": self.history_mgr.autoplay_enabled
        }
        self.queue = []
        self.queue_index = -1
        self._last_played_title = ""
        self._was_playing = False
        self._load_cached_state()

        threading.Thread(target=self._autoplay_watcher, daemon=True).start()
        self._ensure_discord_rpc()

    def _ensure_discord_rpc(self):
        try:
            res = subprocess.run(["pgrep", "-f", "zenify_discord_rpc.py"], stdout=subprocess.PIPE)
            if not res.stdout.strip():
                rpc_script = os.path.join(CONFIG_DIR, "zenify_discord_rpc.py")
                if os.path.exists(rpc_script):
                    subprocess.Popen(["python3", rpc_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception:
            pass

    def _ensure_mpv(self):
        if os.path.exists(SOCKET_PATH):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(SOCKET_PATH)
                s.close()
                return True
            except Exception:
                try:
                    os.remove(SOCKET_PATH)
                except Exception:
                    pass

        cmd = [
            "mpv",
            "--idle=yes",
            "--no-video",
            "--no-audio-display",
            "--no-terminal",
            "--ytdl-format=bestaudio/best",
            "--ytdl-raw-options=extractor-args=youtube:player_client=android",
            "--volume=80",
            f"--input-ipc-server={SOCKET_PATH}"
        ]
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True
        )
        for _ in range(15):
            time.sleep(0.15)
            if os.path.exists(SOCKET_PATH):
                return True
        return False

    def send_mpv_cmd(self, command_list):
        self._ensure_mpv()
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(SOCKET_PATH)
            payload = json.dumps({"command": command_list}) + "\n"
            s.sendall(payload.encode("utf-8"))
            
            response_data = b""
            while True:
                chunk = s.recv(2048)
                if not chunk:
                    break
                response_data += chunk
                if b"\n" in chunk:
                    break
            s.close()
            lines = response_data.decode("utf-8", errors="ignore").strip().split("\n")
            for line in lines:
                try:
                    data = json.loads(line)
                    if "data" in data or "error" in data:
                        return data
                except Exception:
                    pass
            return {"error": "no valid json"}
        except Exception as e:
            return {"error": str(e)}

    def _cache_art_url(self, url):
        if not url or not url.startswith("http"):
            return os.path.join(ASSETS_DIR, "after_dark.png")
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
        dest_path = os.path.join(THUMB_CACHE_DIR, f"{url_hash}.jpg")
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            return dest_path
        try:
            r = requests.get(url, timeout=3.0)
            if r.status_code == 200:
                with open(dest_path, "wb") as f:
                    f.write(r.content)
                return dest_path
        except Exception:
            pass
        return os.path.join(ASSETS_DIR, "after_dark.png")

    def play_track(self, title, artist, art_url="", yt_id=""):
        """Plays track via YouTube audio stream in background while keeping Spotify clean metadata."""
        self._ensure_mpv()
        clean_t = sanitize_title(title, artist)

        # Record watch time affinity on the track that was just playing
        prev_title = self.state.get("title", "")
        prev_artist = self.state.get("artist", "")
        prev_pos = self.state.get("position", 0.0)
        prev_dur = self.state.get("duration", 0.0)
        if prev_title and prev_title != "Nothing Playing":
            self.history_mgr.record_dwell_affinity(prev_title, prev_artist, prev_pos, prev_dur)

        # YouTube stream resolution: search for the exact official song audio
        if yt_id:
            media_src = f"https://www.youtube.com/watch?v={yt_id}"
        else:
            media_src = f"ytdl://ytsearch1:{clean_t} {artist} official audio"

        self.send_mpv_cmd(["loadfile", media_src, "replace"])
        self.send_mpv_cmd(["set_property", "pause", False])

        if not art_url:
            try:
                found = self.search_official_catalog(f"{clean_t} {artist}", limit=1)
                if found and found[0].get("art_url"):
                    art_url = found[0].get("art_url")
            except Exception:
                pass

        art_local = self._cache_art_url(art_url)
        self.state["title"] = clean_t
        self.state["artist"] = artist
        self.state["art_url"] = art_url
        self.state["art_path"] = art_local
        self.state["yt_id"] = yt_id
        self.state["is_playing"] = True
        self.state["position"] = 0.0
        self.state["progress"] = 0.0
        self.state["autoplay"] = self.history_mgr.autoplay_enabled
        self._save_state()

        self.history_mgr.record_listen(clean_t, artist, art_url, yt_id)
        self._last_played_title = clean_t
        self._was_playing = True

        # Sync to YouTube account cloud watch history
        def _sync_cloud(t_name, a_name, vid):
            try:
                engine = self.history_mgr.yt_engine
                if not vid and engine.yt:
                    s = engine.yt.search(f"{t_name} {a_name}", filter="songs")
                    if s and s[0].get("videoId"):
                        vid = s[0].get("videoId")
                        self.state["yt_id"] = vid
                        self._save_state()
                if vid and engine.is_authenticated:
                    engine.sync_cloud_history(vid)
            except Exception:
                pass

        threading.Thread(target=_sync_cloud, args=(clean_t, artist, yt_id), daemon=True).start()

        try:
            msg = f"{clean_t} - {artist}"
            subprocess.run(["hyprctl", "notify", "0", "3000", "rgb(56,189,248)", f"󰓇 Playing: {msg}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def toggle_play(self):
        res = self.send_mpv_cmd(["cycle", "pause"])
        p_res = self.send_mpv_cmd(["get_property", "pause"])
        is_paused = p_res.get("data", False)
        self.state["is_playing"] = not is_paused
        self._save_state()
        return self.state["is_playing"]

    def seek(self, position_seconds):
        self.send_mpv_cmd(["seek", position_seconds, "absolute"])

    def play_next(self):
        """Advances to the next track using smart recommendation autoplay."""
        curr_t = self.state.get("title", "")
        curr_a = self.state.get("artist", "")
        curr_yt = self.state.get("yt_id", "")
        rec = self.history_mgr.recommend_autoplay_track(curr_t, curr_a, curr_yt)
        if rec:
            self.play_track(rec.get("title", "Song"), rec.get("artist", "Artist"), rec.get("art_url", ""), rec.get("yt_id", ""))
            return rec
        return None

    def play_prev(self):
        """Restarts track or plays previous track from history."""
        pos = self.state.get("position", 0.0)
        if pos > 3.0:
            self.seek(0)
            return None
        hist = self.history_mgr.get_history(5)
        if len(hist) > 1:
            prev_t = hist[1]
            self.play_track(prev_t.get("title", "Song"), prev_t.get("artist", "Artist"), prev_t.get("art_url", ""), prev_t.get("yt_id", ""))
            return prev_t
        self.seek(0)
        return None

    def set_volume(self, vol_pct):
        vol = max(0, min(100, int(vol_pct)))
        self.send_mpv_cmd(["set_property", "volume", vol])
        self.state["volume"] = vol
        self._save_state()

    def toggle_autoplay(self):
        new_val = not self.history_mgr.autoplay_enabled
        self.history_mgr.set_autoplay(new_val)
        self.state["autoplay"] = new_val
        self._save_state()
        status_str = "Enabled" if new_val else "Disabled"
        try:
            subprocess.run(["hyprctl", "notify", "0", "2000", "rgb(56,189,248)", f"󰒟 Autoplay: {status_str}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        return new_val

    def update_playback_metrics(self):
        try:
            pos_res = self.send_mpv_cmd(["get_property", "time-pos"])
            dur_res = self.send_mpv_cmd(["get_property", "duration"])
            pause_res = self.send_mpv_cmd(["get_property", "pause"])

            if "data" in pos_res and isinstance(pos_res["data"], (int, float)):
                self.state["position"] = float(pos_res["data"])
            if "data" in dur_res and isinstance(dur_res["data"], (int, float)):
                self.state["duration"] = float(dur_res["data"])
            if "data" in pause_res and isinstance(pause_res["data"], bool):
                self.state["is_playing"] = not pause_res["data"]

            if self.state.get("duration", 0) > 0:
                self.state["progress"] = min(1.0, max(0.0, self.state["position"] / self.state["duration"]))

            self.state["autoplay"] = self.history_mgr.autoplay_enabled
        except Exception:
            pass
        return self.state

    def _autoplay_watcher(self):
        while True:
            time.sleep(1.5)
            try:
                if not self.history_mgr.autoplay_enabled:
                    continue

                pos_res = self.send_mpv_cmd(["get_property", "time-pos"])
                dur_res = self.send_mpv_cmd(["get_property", "duration"])
                idle_res = self.send_mpv_cmd(["get_property", "idle-active"])

                pos = float(pos_res.get("data", 0)) if isinstance(pos_res.get("data"), (int, float)) else 0.0
                dur = float(dur_res.get("data", 0)) if isinstance(dur_res.get("data"), (int, float)) else 0.0
                is_idle = bool(idle_res.get("data", False))

                # Safeguard: if idle occurs without actually playing the song (pos < 5), do NOT auto-skip loop!
                if is_idle and self._was_playing and pos < 5.0 and dur == 0:
                    self._was_playing = False
                    self.state["is_playing"] = False
                    self._save_state()
                    continue

                finished = (dur > 10 and pos >= (dur - 2.5)) or (is_idle and self._was_playing and pos >= 8.0)
                if finished and self.state.get("title") != "Nothing Playing":
                    self._was_playing = False
                    curr_title = self.state.get("title", "")
                    curr_artist = self.state.get("artist", "")
                    curr_yt = self.state.get("yt_id", "")
                    
                    # Record watch time affinity on completed track
                    self.history_mgr.record_dwell_affinity(curr_title, curr_artist, pos, dur)

                    rec = self.history_mgr.recommend_autoplay_track(curr_title, curr_artist, curr_yt)
                    if rec:
                        print(f"Autoplay next song: {rec.get('title')} by {rec.get('artist')}")
                        self.play_track(
                            rec.get("title", "Recommended"),
                            rec.get("artist", "Artist"),
                            rec.get("art_url", ""),
                            rec.get("yt_id", "")
                        )
                        time.sleep(3.0)
            except Exception:
                pass

    def _save_state(self):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception:
            pass

    def _load_cached_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                    self.state.update(data)
            except Exception:
                pass

    @staticmethod
    def fetch_spotify_playlist(playlist_id):
        """Scrapes tracks from Spotify's official embed playlist."""
        url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
        try:
            r = requests.get(url, headers=headers, timeout=5.0)
            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
            if not m:
                return []
            data = json.loads(m.group(1))
            entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
            tracks_raw = entity.get("trackList", [])
            results = []
            for t in tracks_raw:
                dur_ms = t.get("duration", 0)
                dur_sec = int(dur_ms / 1000)
                clean_t = sanitize_title(t.get("title", "Unknown Track"), t.get("subtitle", ""))
                if is_valid_track(clean_t, dur_sec, is_official=True):
                    results.append({
                        "title": clean_t,
                        "artist": t.get("subtitle", "Unknown Artist"),
                        "art_url": t.get("displayImageUri") or t.get("album", {}).get("images", [{}])[0].get("url", ""),
                        "duration": dur_sec,
                        "uri": t.get("uri", "")
                    })
            return results
        except Exception as e:
            print(f"Error fetching playlist {playlist_id}: {e}", file=sys.stderr)
            return []

    @staticmethod
    def search_official_catalog(query, limit=16):
        """
        Searches the official music catalog (Spotify/Apple Music store API)
        with smart query cleaning and dual-engine fallback for independent/phonk/lo-fi artists.
        """
        # Normalize and clean search query (remove 'by', dashes, extra spaces)
        clean_q = re.sub(r'\s+by\s+', ' ', query, flags=re.IGNORECASE)
        clean_q = re.sub(r'[\-\–\—]', ' ', clean_q)
        clean_q = ' '.join(clean_q.split())

        results = []
        seen = set()

        # 1. Spotify Official Catalog (primary if authenticated)
        try:
            from spotify_service import SpotifyService
            sp = SpotifyService()
            if sp.is_authenticated():
                sp_results = sp.search_tracks(clean_q, limit=limit)
                for item in sp_results:
                    raw_title = item.get("title", "")
                    artist = item.get("artist", "Artist")
                    clean_t = sanitize_title(raw_title, artist)
                    dur = item.get("duration", 0)
                    key = f"{clean_t.lower()}_{artist.lower()}"
                    if key not in seen and is_valid_track(clean_t, dur, is_official=True):
                        seen.add(key)
                        results.append({
                            "title": clean_t,
                            "artist": artist,
                            "album": item.get("album", ""),
                            "duration": dur,
                            "art_url": item.get("art_url", "")
                        })
        except Exception:
            pass

        # 2. Official Store Catalog Fallback (iTunes / Apple Music)
        if len(results) < limit:
            url = "https://itunes.apple.com/search"
            params = {"term": clean_q, "media": "music", "entity": "song", "limit": limit}
            try:
                r = requests.get(url, params=params, timeout=3.5)
                if r.status_code == 200:
                    data = r.json()
                    for item in data.get("results", []):
                        dur = item.get("trackTimeMillis", 0) // 1000
                        raw_title = item.get("trackName", "")
                        artist = item.get("artistName", "Artist")
                        clean_t = sanitize_title(raw_title, artist)
                        key = f"{clean_t.lower()}_{artist.lower()}"
                        if key not in seen and is_valid_track(clean_t, dur, is_official=True):
                            seen.add(key)
                            art = item.get("artworkUrl100", "").replace("100x100bb", "300x300bb")
                            results.append({
                                "title": clean_t,
                                "artist": artist,
                                "duration": dur,
                                "art_url": art
                            })
            except Exception:
                pass

        # 3. Dual-Engine Fallback for independent / niche / phonk artists
        if len(results) < 4:
            try:
                cmd = ["yt-dlp", "--dump-json", f"ytsearch12:{clean_q}", "--flat-playlist", "--no-warnings"]
                out = subprocess.check_output(cmd, text=True, timeout=5.0)
                for line in out.strip().split("\n"):
                    if not line:
                        continue
                    d = json.loads(line)
                    raw_t = d.get("title", "")
                    uploader = d.get("uploader", "")
                    dur = int(d.get("duration", 0) or 0)
                    yt_id = d.get("id", "")

                    artist = uploader.replace(" - Topic", "").strip() if uploader else "Artist"
                    clean_t = sanitize_title(raw_t, artist)
                    key = f"{clean_t.lower()}_{artist.lower()}"

                    if key not in seen and is_valid_track(clean_t, dur, is_official=False):
                        seen.add(key)
                        thumbs = d.get("thumbnails", [])
                        art = thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/{yt_id}/hqdefault.jpg"
                        results.append({
                            "title": clean_t,
                            "artist": artist,
                            "duration": dur,
                            "art_url": art,
                            "yt_id": yt_id
                        })
                    if len(results) >= limit:
                        break
            except Exception:
                pass

        return results

def main():
    player = StarkPlayerBackend()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--toggle":
            is_playing = player.toggle_play()
            print("Playing" if is_playing else "Paused")
        elif cmd == "--state":
            st = player.update_playback_metrics()
            print(json.dumps(st))
        elif cmd in ("--play", "--play-query"):
            title = sys.argv[2] if len(sys.argv) > 2 else "Track"
            artist = sys.argv[3] if len(sys.argv) > 3 else "Artist"
            art = sys.argv[4] if len(sys.argv) > 4 else ""
            yt_id = sys.argv[5] if len(sys.argv) > 5 else ""
            player.play_track(title, artist, art, yt_id)
            print(f"Playing: {title} by {artist}")
        elif cmd == "--toggle-autoplay":
            val = player.toggle_autoplay()
            print("Autoplay:", val)
        elif cmd == "--next":
            nxt = player.play_next()
            if nxt:
                print(f"Playing next: {nxt.get('title')} by {nxt.get('artist')}")
        elif cmd == "--prev":
            player.play_prev()
            print("Previous track / rewind")
        elif cmd == "--sync-yt":
            ok = player.history_mgr.yt_engine.sync_from_chrome()
            print("YouTube session synced from Chrome:", ok)
        elif cmd == "--yt-status":
            auth = player.history_mgr.yt_engine.is_authenticated
            print("YouTube Account Authenticated:", auth)
            if auth and player.history_mgr.yt_engine.yt:
                try:
                    home = player.history_mgr.yt_engine.yt.get_home(limit=3)
                    print("Available Personal Sections:", [s.get("title") for s in home])
                except Exception as e:
                    print("Error reading home:", e)
        elif cmd == "--suggestions":
            sug = player.history_mgr.generate_daily_suggestions()
            print(json.dumps(sug, indent=2))
        elif cmd == "--history":
            h = player.history_mgr.get_history()
            print(json.dumps(h, indent=2))
        elif cmd == "--search":
            q = sys.argv[2] if len(sys.argv) > 2 else "synthwave"
            res = player.search_official_catalog(q)
            print(json.dumps(res, indent=2))
        elif cmd == "--playlist":
            pid = sys.argv[2] if len(sys.argv) > 2 else SPOTIFY_PLAYLISTS["top_hits"]["id"]
            tracks = player.fetch_spotify_playlist(pid)
            print(json.dumps(tracks))
        elif cmd == "--daemon":
            print("Running Stark Player metrics sync daemon...")
            while True:
                player.update_playback_metrics()
                time.sleep(1.0)
    else:
        st = player.update_playback_metrics()
        print(json.dumps(st, indent=2))

if __name__ == "__main__":
    main()
