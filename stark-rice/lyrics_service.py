#!/usr/bin/env python3
"""
Lyrics Service - Ground-Truth Per-Word Synchronized Lyrics Engine
================================================================
Fetches millisecond-accurate word-level lyrics from NetEase Cloud Music (YRC)
and line-level lyrics from LRCLIB with natural phonetic word interpolation.
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


def interpolate_line_words(lines):
    """
    Interpolates per-word timings for line-level lyrics using natural phonetic duration.
    Returns: list of line dicts with words.
    """
    k_lines = []
    all_words = []
    n = len(lines)
    for i, (t_start, text) in enumerate(lines):
        t_next = lines[i + 1][0] if i + 1 < n else t_start + 4.0
        gap = max(0.4, t_next - t_start)
        raw_words = text.split()
        if not raw_words:
            continue

        estimates = []
        for w in raw_words:
            clean = re.sub(r'[^a-zA-Z0-9]', '', w)
            sylls = max(1, len(re.findall(r'[aeiouy]+', clean.lower())))
            est = 0.12 + (sylls * 0.08) + (len(clean) * 0.015)
            if w.endswith((',', ';')):
                est += 0.14
            elif w.endswith(('.', '!', '?')):
                est += 0.25
            estimates.append(est)

        natural_total = sum(estimates)
        scale = gap / natural_total if natural_total > 0 else 1.0
        if scale > 1.35:
            scale = 1.0

        cur_t = t_start
        line_words = []
        for w, est in zip(raw_words, estimates):
            w_dur = est * scale
            w_obj = {
                "text": w,
                "clean": re.sub(r'[^a-zA-Z0-9]', '', w),
                "start": cur_t,
                "end": cur_t + w_dur,
                "duration": w_dur
            }
            line_words.append(w_obj)
            all_words.append(w_obj)
            cur_t += w_dur

        wps = len(line_words) / gap if gap > 0 else 2.0
        k_lines.append({
            "start": t_start,
            "end": t_next,
            "gap": gap,
            "text": text,
            "words": line_words,
            "wps": wps
        })

    return k_lines, all_words


def parse_yrc_lines(yrc_raw):
    """
    Parses NetEase Cloud Music YRC (per-word synced format).
    Cleanly merges punctuation, asterisks, and hyphens into natural words.
    """
    k_lines = []
    all_words = []

    for raw_line in yrc_raw.splitlines():
        raw_line = raw_line.strip()
        if not raw_line or not raw_line.startswith('['):
            continue
        m_line = re.match(r'\[(\d+),(\d+)\](.*)', raw_line)
        if not m_line:
            continue
        l_start = int(m_line.group(1)) / 1000.0
        l_dur = int(m_line.group(2)) / 1000.0
        rest = m_line.group(3)

        raw_tokens = []
        for m in re.finditer(r'\((\d+),(\d+),\d+\)([^(\n]*)', rest):
            t_s = int(m.group(1)) / 1000.0
            t_d = int(m.group(2)) / 1000.0
            txt = m.group(3)
            raw_tokens.append({'start': t_s, 'dur': t_d, 'text': txt})

        if not raw_tokens:
            continue

        line_words = []
        cur_word = None
        for tok in raw_tokens:
            txt = tok['text']
            t_s = tok['start']
            t_d = tok['dur']
            clean_tok = re.sub(r'[^a-zA-Z0-9]', '', txt)

            # Pure punctuation (like ', ' or '?' or '!') -> merge to prev word
            if not clean_tok and line_words:
                line_words[-1]['text'] += txt.strip()
                line_words[-1]['end'] = max(line_words[-1]['end'], t_s + t_d)
                line_words[-1]['duration'] = line_words[-1]['end'] - line_words[-1]['start']
                if cur_word:
                    cur_word['ended_with_space'] = txt.endswith(' ')
                continue

            # Check if this token starts a NEW word or continues the previous one
            if cur_word is None or txt.startswith(' ') or cur_word.get('ended_with_space'):
                s_txt = txt.strip()
                if s_txt:
                    cur_word = {
                        'text': s_txt,
                        'clean': clean_tok or re.sub(r'[^a-zA-Z0-9]', '', s_txt),
                        'start': t_s,
                        'end': t_s + t_d,
                        'duration': max(0.06, t_d),
                        'ended_with_space': txt.endswith(' ')
                    }
                    line_words.append(cur_word)
                    all_words.append(cur_word)
            else:
                # Continuation of current word (like '*', hyphen, or word suffix)
                cur_word['text'] += txt.rstrip()
                cur_word['clean'] += clean_tok
                cur_word['end'] = t_s + t_d
                cur_word['duration'] = max(0.06, cur_word['end'] - cur_word['start'])
                cur_word['ended_with_space'] = txt.endswith(' ')

        if line_words:
            # Clean up temporary field
            for w in line_words:
                w.pop('ended_with_space', None)
            line_text = ' '.join(w['text'] for w in line_words)
            wps = len(line_words) / max(0.5, l_dur)
            k_lines.append({
                'start': l_start,
                'end': l_start + l_dur,
                'gap': l_dur,
                'text': line_text,
                'words': line_words,
                'wps': wps
            })

    return k_lines, all_words


def fetch_from_netease(title, artist):
    """
    Queries NetEase Cloud Music API for song and retrieves YRC (per-word) or LRC (line).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Referer": "https://music.163.com/"
    }
    clean_t = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
    clean_a = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip()
    q = f"{clean_t} {clean_a}"
    url = "https://music.163.com/api/search/get?s=" + urllib.parse.quote(q) + "&type=1&offset=0&limit=3"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=4.0) as r:
            data = json.loads(r.read().decode("utf-8"))
        songs = data.get("result", {}).get("songs", [])
        if not songs:
            return None
        sid = songs[0]["id"]
        lurl = f"https://music.163.com/api/song/lyric/v1?id={sid}&lv=1&kv=1&tv=-1&yv=1"
        req2 = urllib.request.Request(lurl, headers=headers)
        with urllib.request.urlopen(req2, timeout=4.0) as r2:
            ldata = json.loads(r2.read().decode("utf-8"))

        # 1. YRC Per-Word Synced Format
        yrc_raw = ldata.get("yrc", {}).get("lyric", "")
        if yrc_raw:
            k_lines, all_words = parse_yrc_lines(yrc_raw)
            if k_lines:
                return {
                    "source": "netease_yrc",
                    "is_synced": True,
                    "has_per_word": True,
                    "k_lines": k_lines,
                    "words": all_words,
                    "raw": yrc_raw
                }

        # 2. LRC Line-Level Synced Format
        lrc_raw = ldata.get("lrc", {}).get("lyric", "")
        if lrc_raw:
            parsed = parse_lrc(lrc_raw)
            if parsed:
                k_lines, all_words = interpolate_line_words(parsed)
                return {
                    "source": "netease_lrc",
                    "is_synced": True,
                    "has_per_word": False,
                    "k_lines": k_lines,
                    "words": all_words,
                    "raw": lrc_raw
                }
    except Exception:
        pass
    return None


def fetch_from_youtube_music(yt_id, title, artist):
    """
    Fetches plain lyrics directly from YouTube Music via ytmusicapi.
    """
    try:
        import ytmusicapi
        yt = ytmusicapi.YTMusic()
        video_id = yt_id
        if not video_id and title:
            clean_q = f"{title} {artist}".strip()
            results = yt.search(clean_q, filter="songs")
            if results and results[0].get("videoId"):
                video_id = results[0]["videoId"]
        if video_id:
            watch = yt.get_watch_playlist(video_id)
            lyrics_id = watch.get("lyrics")
            if lyrics_id:
                data = yt.get_lyrics(lyrics_id)
                raw_text = data.get("lyrics", "")
                if raw_text:
                    return raw_text
    except Exception:
        pass
    return ""


def fetch_lyrics(title, artist, duration=0, yt_id=""):
    """
    Fetches synchronized lyrics with ground-truth per-word timestamps.
    Returns: (k_lines, is_synced, raw_text, words)
    """
    if not title:
        return [], False, "", []

    clean_t = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
    clean_a = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip()
    key = hashlib.md5(f"{clean_t.lower()}_{clean_a.lower()}".encode("utf-8")).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{key}.json")

    # 1. Check local cache
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                k_lines = data.get("k_lines")
                words = data.get("words", [])
                raw = data.get("syncedLyrics", "")
                if k_lines and words:
                    return k_lines, True, raw, words

                raw_plain = data.get("plainLyrics")
                if raw_plain:
                    plain_lines = [{"start": 0.0, "end": 0.0, "text": l, "words": []} for l in raw_plain.split('\n') if l.strip()]
                    return plain_lines, False, raw_plain, []
        except Exception:
            pass

    # 2. Query NetEase Cloud Music (Per-Word YRC or Line-Level LRC)
    ncm = fetch_from_netease(clean_t, clean_a)
    if ncm:
        try:
            cache_payload = {
                "source": ncm["source"],
                "has_per_word": ncm["has_per_word"],
                "syncedLyrics": ncm["raw"],
                "k_lines": ncm["k_lines"],
                "words": ncm["words"]
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_payload, f)
        except Exception:
            pass
        return ncm["k_lines"], True, ncm["raw"], ncm["words"]

    # 3. Query LRCLIB API for Synced Timestamps
    try:
        q = urllib.parse.quote(f"{clean_t} {clean_a}")
        url = f"https://lrclib.net/api/search?q={q}"
        req = urllib.request.Request(url, headers={"User-Agent": "ZenifyMusic/1.0"})
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            results = json.loads(resp.read().decode("utf-8"))
            if results and isinstance(results, list):
                best_match = None
                for it in results:
                    if it.get("syncedLyrics"):
                        best_match = it
                        break
                if not best_match and results:
                    best_match = results[0]

                if best_match and best_match.get("syncedLyrics"):
                    raw_synced = best_match["syncedLyrics"]
                    parsed = parse_lrc(raw_synced)
                    k_lines, words = interpolate_line_words(parsed)
                    try:
                        with open(cache_path, "w", encoding="utf-8") as f:
                            json.dump({
                                "source": "lrclib",
                                "has_per_word": False,
                                "syncedLyrics": raw_synced,
                                "k_lines": k_lines,
                                "words": words
                            }, f)
                    except Exception:
                        pass
                    return k_lines, True, raw_synced, words
    except Exception:
        pass

    # 4. Direct YouTube Music Fetch (Plain Lyrics)
    yt_lyrics = fetch_from_youtube_music(yt_id, clean_t, clean_a)
    if yt_lyrics:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"plainLyrics": yt_lyrics, "source": "YouTube Music"}, f)
        except Exception:
            pass
        plain_lines = [{"start": 0.0, "end": 0.0, "text": l, "words": []} for l in yt_lyrics.split('\n') if l.strip()]
        return plain_lines, False, yt_lyrics, []

    # 5. Fallback to LRCLIB Plain Lyrics
    try:
        if 'best_match' in locals() and best_match and best_match.get("plainLyrics"):
            raw_plain = best_match["plainLyrics"]
            plain_lines = [{"start": 0.0, "end": 0.0, "text": l, "words": []} for l in raw_plain.split('\n') if l.strip()]
            return plain_lines, False, raw_plain, []
    except Exception:
        pass

    return [], False, "", []
