#!/usr/bin/env python3
"""
J.A.R.V.I.S. Core Intelligence & Voice System
Persona: J.A.R.V.I.S. (Tony Stark's British AI Assistant)
Architecture: Two-Speed Brain
  - Speed 1 (Reflex Tier): Sub-millisecond direct hardware/media/app control & immediate feedback
  - Speed 2 (Agentic Tier): Antigravity autonomous system agent with immediate acoustic acknowledgment
Voice: Deepgram Aura-2 (aura-2-pluto-en)
"""

import os
import sys
import re
import json
import time
import random
import socket
import readline
import subprocess
import urllib.request
import atexit

CONFIG_PATHS = [
    os.path.expanduser("~/.config/stark-rice/jarvis_config.json"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_config.json")
]

HISTORY_FILE = os.path.expanduser("~/.config/stark-rice/jarvis_history")
SOCKET_PATH = "/tmp/stark_player.sock"
SPEECH_FILE = "/tmp/jarvis_speech.mp3"

DEFAULT_CONFIG = {
    "mode": "two-speed",
    "agent_backend": "antigravity",
    "antigravity_model": "gemini-3.8-flash-low",
    "antigravity_effort": "low",
    "nim_api_key": "",
    "deepgram_api_key": "",
    "model_name": "nvidia/nemotron-3.5-bolt-e4b",
    "voice_model": "aura-2-pluto-en",
    "playback_speed": 1.12,
    "spatial_reverb": False,
    "voice_enabled": True,
    "boot_greeting": True
}

# Terminal Colors
CYAN = "\033[96m"
BLUE = "\033[94m"
GOLD = "\033[93m"
GRAY = "\033[90m"
GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

ACK_PHRASES = [
    "Analyzing system parameters now, Sir...",
    "Investigating that for you immediately, Sir...",
    "Accessing system diagnostics, Sir...",
    "Allow me a moment to inspect that, Sir...",
    "Running that diagnostic protocol now, Sir...",
    "Reviewing system logs and workspaces, Sir..."
]


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    for path in CONFIG_PATHS:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                    cfg.update(user_cfg)
                    break
            except Exception:
                pass
    if "NIM_KEY" in os.environ:
        cfg["nim_api_key"] = os.environ["NIM_KEY"]
    if "DEEPGRAM_KEY" in os.environ:
        cfg["deepgram_api_key"] = os.environ["DEEPGRAM_KEY"]
    return cfg


config = load_config()
nim_api_key = config.get("nim_api_key", "")
deepgram_api_key = config.get("deepgram_api_key", "")
model_name = config.get("model_name", "nvidia/nemotron-3.5-bolt-e4b")
voice_model = config.get("voice_model", "aura-2-pluto-en")
playback_speed = float(config.get("playback_speed", 1.12))
spatial_reverb = bool(config.get("spatial_reverb", False))
voice_enabled = bool(config.get("voice_enabled", True))
agent_backend = config.get("agent_backend", "antigravity")
antigravity_model = config.get("antigravity_model", "gemini-3.8-flash-low")
antigravity_effort = config.get("antigravity_effort", "low")

current_speech_proc = None
last_response_text = ""


def get_current_music():
    """Returns (title, artist, is_playing)."""
    m_path = os.path.expanduser("~/.config/stark-rice/music_state.json")
    if os.path.exists(m_path):
        try:
            with open(m_path, "r", encoding="utf-8") as f:
                m = json.load(f)
                return m.get("title", "").strip(), m.get("artist", "").strip(), m.get("is_playing", False)
        except Exception:
            pass
    return "", "", False


def get_telemetry():
    """Gathers real-time machine and environment telemetry."""
    now_str = time.strftime("%A, %B %d, %I:%M %p")
    
    # Weather
    weather_info = "AccuWeather unavailable"
    w_path = os.path.expanduser("~/.config/stark-rice/weather_cache.json")
    if os.path.exists(w_path):
        try:
            with open(w_path, "r", encoding="utf-8") as f:
                w = json.load(f)
                weather_info = f"{w.get('city', 'Local')}: {w.get('temp_c')}°C, {w.get('condition')}"
                if "feels_like_c" in w:
                    weather_info += f" (feels like {w.get('feels_like_c')}°C)"
        except Exception:
            pass

    # Music state
    title, artist, is_playing = get_current_music()
    st = "Playing" if is_playing else "Paused"
    if title and artist:
        music_info = f"'{title}' by {artist} (Status: {st})"
    elif title:
        music_info = f"'{title}' (Status: {st})"
    else:
        music_info = "No track currently queued"

    # Memory & load
    mem_info = "Unknown"
    try:
        with open("/proc/meminfo", "r") as f:
            lines = f.readlines()
            mdict = {l.split(":")[0]: int(l.split(":")[1].strip().split()[0]) for l in lines[:10]}
            total_gb = mdict.get("MemTotal", 0) / 1024 / 1024
            avail_gb = mdict.get("MemAvailable", 0) / 1024 / 1024
            used_gb = total_gb - avail_gb
            mem_info = f"{used_gb:.1f} / {total_gb:.1f} GB"
    except Exception:
        pass

    load_avg = "Unknown"
    try:
        with open("/proc/loadavg", "r") as f:
            load_avg = f.read().split()[0]
    except Exception:
        pass

    telemetry = (
        f"Live System Telemetry:\n"
        f"- Current Time: {now_str}\n"
        f"- OS: Arch Linux (Hyprland Wayland Compositor)\n"
        f"- Weather: {weather_info}\n"
        f"- Current Music Track: {music_info}\n"
        f"- Memory: {mem_info} used | CPU Load: {load_avg}"
    )
    return telemetry


SYSTEM_PROMPT_BASE = (
    "You are J.A.R.V.I.S., Tony Stark's personal artificial intelligence system. "
    "You are a refined, polite, unflappable British gentleman with a calm baritone demeanor. "
    "Always address the user as 'Sir'. Keep responses concise (typically 1 to 2 sentences) "
    "so they are punchy and natural for text-to-speech delivery. "
    "Use natural punctuation, ellipses (...), and em-dashes (—) to give the speech engine breathing room.\n\n"
    "You have real-time access to Sir's Arch Linux system and Stark Rice environment."
)


def send_player_cmd(cmd_list):
    """Sends mpv IPC command to stark_player socket."""
    if os.path.exists(SOCKET_PATH):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.6)
            s.connect(SOCKET_PATH)
            s.sendall(json.dumps({"command": cmd_list}).encode("utf-8") + b"\n")
            s.close()
            return True
        except Exception:
            pass
    return False


def execute_action(action_name):
    """Executes a system action smoothly."""
    if not action_name:
        return
    act = action_name.lower().strip()
    try:
        if act == "music_pause":
            if not send_player_cmd(["set_property", "pause", True]):
                subprocess.run(["playerctl", "pause"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act in ("music_play", "music_resume"):
            if not send_player_cmd(["set_property", "pause", False]):
                subprocess.run(["playerctl", "play"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act == "music_toggle":
            if not send_player_cmd(["cycle", "pause"]):
                subprocess.run(["playerctl", "play-pause"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act == "music_next":
            if not send_player_cmd(["playlist-next"]):
                subprocess.run(["playerctl", "next"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act == "music_prev":
            if not send_player_cmd(["playlist-prev"]):
                subprocess.run(["playerctl", "previous"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act == "volume_up":
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act == "volume_down":
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act == "volume_mute":
            subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act.startswith("volume_set_"):
            pct_str = act.replace("volume_set_", "")
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{pct_str}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act in ("open_browser", "open_brave"):
            subprocess.Popen(["setsid", "brave-origin"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act in ("open_terminal", "open_kitty"):
            subprocess.Popen(["setsid", "kitty"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act in ("open_files", "open_thunar"):
            subprocess.Popen(["setsid", "thunar"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act in ("open_code", "open_vscode"):
            subprocess.Popen(["setsid", "code"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act in ("open_zenify", "open_spotify"):
            p = os.path.expanduser("~/.config/stark-rice/stark_spotify.py")
            subprocess.Popen(["python3", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act == "lock_screen":
            subprocess.Popen(["hyprlock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif act == "reload_ui":
            p = os.path.expanduser("~/.config/stark-rice/launch.sh")
            subprocess.Popen([p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"{GRAY}[Action Error: {e}]{RESET}")


def clean_text_for_speech(text):
    """Removes action tags, code blocks, and markdown for natural vocalization."""
    t = re.sub(r"\[ACTION:\s*[a-zA-Z0-9_-]+\]", "", text)
    t = re.sub(r"```[\s\S]*?```", "", t)  # strip code blocks
    t = re.sub(r"[*_~`#>]", "", t)        # strip markdown symbols
    t = re.sub(r"\|.*?\|", "", t)         # strip tables
    t = re.sub(r"\s+", " ", t).strip()
    return t


def speak_text(text, wait=False):
    """Synthesizes text with Deepgram Aura-2 and plays via mpv."""
    global current_speech_proc
    if not voice_enabled or not text:
        return
        
    spoken_text = clean_text_for_speech(text)
    if not spoken_text:
        return

    if current_speech_proc and current_speech_proc.poll() is None:
        try:
            current_speech_proc.terminate()
            current_speech_proc.wait(timeout=0.2)
        except Exception:
            pass

    try:
        url = f"https://api.deepgram.com/v1/speak?model={voice_model}"
        headers = {
            "Authorization": f"Token {deepgram_api_key}",
            "Content-Type": "application/json"
        }
        payload = json.dumps({"text": spoken_text}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers)
        
        with urllib.request.urlopen(req, timeout=12) as resp:
            audio_bytes = resp.read()
            
        if not audio_bytes:
            return
            
        with open(SPEECH_FILE, "wb") as f:
            f.write(audio_bytes)

        mpv_cmd = [
            "mpv",
            "--no-video",
            "--keep-open=no",
            "--really-quiet",
            f"--speed={playback_speed:.2f}"
        ]
        if spatial_reverb:
            mpv_cmd.append("--af=lavfi=[aecho=1.0:0.9:30:0.2]")
        mpv_cmd.append(SPEECH_FILE)

        current_speech_proc = subprocess.Popen(mpv_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if wait:
            try:
                current_speech_proc.wait()
            except KeyboardInterrupt:
                current_speech_proc.terminate()
                raise
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"{GRAY}[Voice Warning: {e}]{RESET}")


# ==============================================================================
# SPEED 1: REFLEX TIER (Sub-millisecond Direct Execution)
# ==============================================================================
def classify_reflex(user_input):
    """
    Evaluates query against fast reflex heuristics.
    Returns (is_reflex, reply_text, action_name).
    """
    t = user_input.lower().strip()
    title, artist, is_playing = get_current_music()
    track_phrase = f"'{title}' by {artist}" if (title and artist) else "current track"

    # 1. Volume Controls
    if re.search(r"\b(volume up|louder|increase volume|turn it up)\b", t):
        return True, "Increasing master volume, Sir.", "volume_up"
    if re.search(r"\b(volume down|quieter|decrease volume|lower volume|turn it down)\b", t):
        return True, "Lowering master volume, Sir.", "volume_down"
    
    m_vol = re.search(r"\b(?:set )?volume (?:to )?(\d{1,3})%?\b", t)
    if m_vol:
        val = max(0, min(100, int(m_vol.group(1))))
        return True, f"Adjusting master volume to {val} percent, Sir.", f"volume_set_{val}"
        
    if re.search(r"\b(mute|unmute|silence|toggle mute)\b", t):
        return True, "Toggling master audio mute, Sir.", "volume_mute"

    # 2. Media Playback Controls
    if re.search(r"\b(pause|stop music|hold track|pause song|pause music)\b", t):
        return True, f"Pausing {track_phrase}, Sir.", "music_pause"
    if re.search(r"\b(resume|play|unpause|start music|continue track)\b", t):
        return True, f"Resuming playback of {track_phrase}, Sir.", "music_play"
    if re.search(r"\b(next song|next track|skip song|skip track|skip)\b", t):
        return True, "Skipping to the next track, Sir.", "music_next"
    if re.search(r"\b(previous song|prev track|previous track|play previous|go back)\b", t):
        return True, "Returning to the previous track, Sir.", "music_prev"
    if re.search(r"\b(toggle music|play pause|toggle playback)\b", t):
        return True, f"Toggling media playback, Sir.", "music_toggle"
    if re.search(r"\b(what song is this|what are we listening to|what track is this|current song|now playing)\b", t):
        if title:
            return True, f"We are currently listening to {track_phrase}, Sir.", None
        return True, "There is currently no audio track loaded in the Stark Player, Sir.", None

    # 3. Fast Application Launchers
    if re.search(r"\b(open|launch) (brave|browser|internet|web)\b", t):
        return True, "Launching Brave Origin, Sir.", "open_browser"
    if re.search(r"\b(open|launch) (terminal|kitty|console)\b", t):
        return True, "Opening terminal window, Sir.", "open_terminal"
    if re.search(r"\b(open|launch) (files|thunar|file manager|explorer)\b", t):
        return True, "Opening file manager, Sir.", "open_files"
    if re.search(r"\b(open|launch) (code|vscode|editor)\b", t):
        return True, "Opening Visual Studio Code, Sir.", "open_code"
    if re.search(r"\b(open|launch) (spotify|zenify|music player)\b", t):
        return True, "Opening Stark Music Console, Sir.", "open_zenify"
    if re.search(r"\b(lock screen|lock system|lock pc)\b", t):
        return True, "Engaging workstation security lock, Sir.", "lock_screen"
    if re.search(r"\b(reload ui|restart desktop|reload waybar)\b", t):
        return True, "Re-initializing the Stark desktop environment, Sir.", "reload_ui"

    # 4. Instant Telemetry & Greetings
    if re.search(r"\b(what time is it|current time|what is the time|tell me the time)\b", t):
        t_now = time.strftime("%I:%M %p")
        return True, f"It is currently {t_now}, Sir.", None
    if re.search(r"\b(what day is it|what is the date|today's date|current date)\b", t):
        d_now = time.strftime("%A, %B %d, %Y")
        return True, f"Today is {d_now}, Sir.", None
    if re.search(r"\b(thank you|thanks jarvis|thanks|cheers)\b", t):
        return True, "Always a pleasure to be of service, Sir.", None
    if re.search(r"\b(hello|hi jarvis|hey jarvis|greetings)\b", t):
        return True, "At your command, Sir. What can I do for you today?", None

    return False, None, None


# ==============================================================================
# SPEED 2: ANTIGRAVITY AGENTIC TIER (Autonomous Reasoning & Tool Execution)
# ==============================================================================
def query_antigravity(user_input, history, telemetry):
    """Executes multi-step agentic query using the Antigravity engine."""
    prompt = (
        f"You are J.A.R.V.I.S., Tony Stark's personal artificial intelligence system operating on Sir's Arch Linux Hyprland workstation.\n"
        f"System Telemetry:\n{telemetry}\n\n"
        f"Sir's Request: \"{user_input}\"\n\n"
        f"Instructions:\n"
        f"1. Fulfill Sir's request directly using available system tools (run_command, hyprctl, file inspection, etc.) as needed.\n"
        f"2. Maintain your persona: refined, polite, unflappable British demeanor. Always address Sir.\n"
        f"3. Provide a clear, natural spoken summary (1-2 sentences) at the start for vocal delivery, followed by any diagnostic detail if relevant.\n"
        f"4. If you need Sir to execute an action (e.g. toggle playback, lock screen), append [ACTION: <action_name>] at the end."
    )
    
    cmd = [
        "agy",
        "--dangerously-skip-permissions",
        "--model", config.get("antigravity_model", "gemini-3.8-flash-low"),
        "--effort", config.get("antigravity_effort", "low"),
        "--disable-slash-commands",
        "-p", prompt
    ]
    
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
    if proc.returncode == 0 and proc.stdout.strip():
        raw_reply = proc.stdout.strip()
        action_match = re.search(r"\[ACTION:\s*([a-zA-Z0-9_-]+)\]", raw_reply)
        action = action_match.group(1) if action_match else None
        clean_reply = re.sub(r"\[ACTION:\s*[a-zA-Z0-9_-]+\]", "", raw_reply).strip()
        return clean_reply, action
    else:
        err = proc.stderr.strip() if proc.stderr else f"Exit code {proc.returncode}"
        raise RuntimeError(f"Antigravity execution failed: {err}")


def query_nim(user_input, history, telemetry):
    """Fallback query to NVIDIA NIM Nemotron."""
    system_prompt = f"{SYSTEM_PROMPT_BASE}\n\n{telemetry}"
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": user_input})
    
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {nim_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.6,
        "max_tokens": 160
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        raw_reply = data["choices"][0]["message"]["content"].strip()
        action_match = re.search(r"\[ACTION:\s*([a-zA-Z0-9_-]+)\]", raw_reply)
        action = action_match.group(1) if action_match else None
        clean_reply = re.sub(r"\[ACTION:\s*[a-zA-Z0-9_-]+\]", "", raw_reply).strip()
        return clean_reply, action


def query_jarvis(user_input, history, ack_callback=None):
    """
    Main Two-Speed Dispatcher:
    - Tier 1: Instant Reflex Classifier (<5ms)
    - Tier 2: Antigravity Agent with Immediate Acoustic Acknowledgment
    """
    # 1. Check Reflex Tier (Speed 1)
    is_reflex, reflex_reply, reflex_action = classify_reflex(user_input)
    if is_reflex:
        if reflex_action:
            execute_action(reflex_action)
        return reflex_reply, reflex_action

    # 2. Agentic Tier (Speed 2)
    # A. Acoustic Acknowledgment
    ack_text = random.choice(ACK_PHRASES)
    if ack_callback:
        try:
            ack_callback(ack_text)
        except Exception:
            pass

    telemetry = get_telemetry()

    # B. Run Primary Agent (Antigravity)
    if agent_backend == "antigravity":
        try:
            return query_antigravity(user_input, history, telemetry)
        except Exception as e:
            print(f"{GRAY}[Antigravity Warning: {e}, attempting NIM fallback]{RESET}")
            if nim_api_key:
                try:
                    return query_nim(user_input, history, telemetry)
                except Exception as e2:
                    print(f"{RED}[NIM Fallback Error: {e2}]{RESET}")
            return f"Apologies, Sir. Primary agent encountered an interruption: {e}", None

    # Fallback directly to NIM if backend configured as nim
    if nim_api_key:
        try:
            return query_nim(user_input, history, telemetry)
        except Exception as e:
            return f"Apologies, Sir. Communication anomaly detected: {e}", None

    return "Apologies, Sir. System backends are currently unreachable.", None


def print_banner():
    reverb_str = f"{GREEN}ON{RESET}" if spatial_reverb else f"{GRAY}OFF{RESET}"
    voice_str = f"{GREEN}ACTIVE{RESET}" if voice_enabled else f"{RED}MUTED{RESET}"
    
    banner = f"""{CYAN}{BOLD}
  ╔═══════════════════════════════════════════════════════════════════════════╗
  ║                        J . A . R . V . I . S .                            ║
  ║                 Just A Rather Very Intelligent System                     ║
  ║  Architecture: Two-Speed Brain (Antigravity Agent + Fast Reflex Core)    ║
  ║  Speed: {playback_speed:.2f}x  •  Acoustic: {reverb_str}  •  Voice: {voice_str}  •  Model: {antigravity_model:<14} ║
  ║  Controls: 'speed <val>' • 'reverb' • 'mute' • 'clear' • 'repeat' • 'q'  ║
  ╚═══════════════════════════════════════════════════════════════════════════╝{RESET}"""
  # Print the banner
    print(banner)


def show_system_status():
    """Prints live telemetry diagnostics."""
    tele = get_telemetry()
    print(f"\n{BLUE}{BOLD}[ SYSTEM DIAGNOSTICS & TELEMETRY ]{RESET}")
    for line in tele.splitlines():
        print(f"  {CYAN}›{RESET} {line}")
    print()


def get_boot_greeting():
    """Generates an appropriate time-aware greeting."""
    hour = time.localtime().tm_hour
    if 5 <= hour < 12:
        period = "Good morning"
    elif 12 <= hour < 17:
        period = "Good afternoon"
    elif 17 <= hour < 22:
        period = "Good evening"
    else:
        period = "Good evening"
    return f"{period}, Sir. Stark Rice environment is online and all systems are operational."


def init_readline():
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    if os.path.exists(HISTORY_FILE):
        try:
            readline.read_history_file(HISTORY_FILE)
        except Exception:
            pass
    readline.set_history_length(500)
    atexit.register(save_readline_history)


def save_readline_history():
    try:
        readline.write_history_file(HISTORY_FILE)
    except Exception:
        pass


def interactive_session():
    global voice_enabled, playback_speed, spatial_reverb, last_response_text
    init_readline()
    print_banner()
    
    greeting = get_boot_greeting()
    print(f"{CYAN}{BOLD}J.A.R.V.I.S.{RESET} {GRAY}›{RESET} {greeting}\n")
    speak_text(greeting, wait=False)
    
    history = []
    
    while True:
        try:
            user_input = input(f"{GOLD}{BOLD}Sir{RESET} {GRAY}›{RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{CYAN}{BOLD}J.A.R.V.I.S.{RESET} {GRAY}›{RESET} Good night, Sir.\n")
            speak_text("Good night, Sir.", wait=True)
            break
            
        if not user_input:
            continue
            
        lower = user_input.lower()
        if lower in ("exit", "quit", "q", "bye"):
            farewell = "Shutting down secondary protocols. Have a pleasant evening, Sir."
            print(f"{CYAN}{BOLD}J.A.R.V.I.S.{RESET} {GRAY}›{RESET} {farewell}\n")
            speak_text(farewell, wait=True)
            break
            
        if lower == "clear":
            history.clear()
            os.system("clear")
            print_banner()
            print(f"{GRAY}[Conversation memory cleared. System reset.]{RESET}\n")
            continue
            
        if lower == "mute":
            voice_enabled = not voice_enabled
            status = "enabled" if voice_enabled else "muted"
            print(f"{GRAY}[Voice output is now {status}.]{RESET}\n")
            continue

        if lower == "reverb":
            spatial_reverb = not spatial_reverb
            status = "enabled" if spatial_reverb else "disabled"
            print(f"{GRAY}[Spatial room reverb is now {status}.]{RESET}\n")
            continue

        if lower == "status":
            show_system_status()
            continue

        def cli_ack(ack_phrase):
            print(f"{CYAN}{BOLD}J.A.R.V.I.S.{RESET} {GRAY}›{RESET} {ack_phrase}")
            speak_text(ack_phrase, wait=False)

        try:
            reply, action = query_jarvis(user_input, history, ack_callback=cli_ack)
            last_response_text = reply
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": reply})
            
            print(f"{CYAN}{BOLD}J.A.R.V.I.S.{RESET} {GRAY}›{RESET} {reply}\n")
            
            if action:
                speak_text(reply, wait=True)
                time.sleep(0.12)
                execute_action(action)
            else:
                speak_text(reply, wait=False)
        except Exception as e:
            print(f"\n{RED}[Communication Error: {e}]{RESET}\n")


def main():
    args = sys.argv[1:]
    
    if "--boot" in args or "--greeting-only" in args:
        greeting = get_boot_greeting()
        print(f"J.A.R.V.I.S.: {greeting}")
        speak_text(greeting, wait=True)
        return

    if "--help" in args or "-h" in args:
        print("Usage:")
        print("  jarvis                    # Launch interactive J.A.R.V.I.S. CLI")
        print("  jarvis 'your question'    # One-shot command & voice response")
        print("  jarvis --toggle           # Toggle floating HUD window")
        print("  jarvis --boot             # Play startup system greeting")
        return

    if args:
        user_query = " ".join(args)
        reply, action = query_jarvis(user_query, [])
        print(f"{CYAN}{BOLD}J.A.R.V.I.S.{RESET} {GRAY}›{RESET} {reply}")
        speak_text(reply, wait=True)
        if action:
            time.sleep(0.12)
            execute_action(action)
        return

    interactive_session()


if __name__ == "__main__":
    main()
