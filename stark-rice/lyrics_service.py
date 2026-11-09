#!/usr/bin/env python3
"""
Lyrics Service - Millisecond-Accurate Synchronized LRC Engine
============================================================
Fetches synchronized LRC lyrics from LRCLIB and caches them locally.
"""

import os
import re
import json
import hashlib
import urllib.request
import urllib.parse

CACHE_DIR = os.path.expanduser("~/.config/stark-rice/assets/lyrics_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def parse_lrc(lrc_text):
    """
    Parses LRC format into a list of tuples: [(timestamp_seconds, text_line), ...]
    """
    if not lrc_text:
        return []
    lines = []
    pattern = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)')
    for l in lrc_text.strip().split('\n'):
        l = l.strip()
        m = pattern.match(l)
        if m:
            mins = int(m.group(1))
            secs = float(m.group(2))
            text = m.group(3).strip()
            if text:
                lines.append((mins * 60 + secs, text))
    lines.sort(key=lambda x: x[0])
    return lines


def fetch_lyrics(title, artist, duration=0):
    """
    Fetches synchronized lyrics. Returns (parsed_lines, is_synced, raw_text).
    """
    if not title:
        return [], False, ""

    # Clean title & artist for search
    clean_t = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
    clean_a = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip()
    key = hashlib.md5(f"{clean_t.lower()}_{clean_a.lower()}".encode("utf-8")).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{key}.json")

    # 1. Check local cache
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                raw_synced = data.get("syncedLyrics")
                if raw_synced:
                    return parse_lrc(raw_synced), True, raw_synced
                raw_plain = data.get("plainLyrics")
                if raw_plain:
                    # Treat plain lyrics as lines with 0 timestamp
                    plain_lines = [(0.0, l) for l in raw_plain.split('\n') if l.strip()]
                    return plain_lines, False, raw_plain
        except Exception:
            pass

    # 2. Query LRCLIB API
    try:
        q = urllib.parse.quote(f"{clean_t} {clean_a}")
        url = f"https://lrclib.net/api/search?q={q}"
        req = urllib.request.Request(url, headers={"User-Agent": "ZenifyMusic/1.0"})
        with urllib.request.urlopen(req, timeout=4.5) as resp:
            results = json.loads(resp.read().decode("utf-8"))
            if results and isinstance(results, list):
                # Prefer exact or synced match
                best_match = None
                for it in results:
                    if it.get("syncedLyrics"):
                        best_match = it
                        break
                if not best_match and results:
                    best_match = results[0]

                if best_match:
                    try:
                        with open(cache_path, "w", encoding="utf-8") as f:
                            json.dump(best_match, f)
                    except Exception:
                        pass

                    raw_synced = best_match.get("syncedLyrics")
                    if raw_synced:
                        return parse_lrc(raw_synced), True, raw_synced
                    raw_plain = best_match.get("plainLyrics")
                    if raw_plain:
                        plain_lines = [(0.0, l) for l in raw_plain.split('\n') if l.strip()]
                        return plain_lines, False, raw_plain
    except Exception:
        pass

    return [], False, ""
