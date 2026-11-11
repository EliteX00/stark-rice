#!/usr/bin/env python3
"""
J.A.R.V.I.S. Core Intelligence & Voice System
Persona: J.A.R.V.I.S. (Tony Stark's British AI Assistant)
Brain: NVIDIA NIM (Nemotron 3.5 Bolt)
Voice: Deepgram Aura-2 (aura-2-pluto-en)
"""

import os
import sys
import re
import json
import time
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

# Default settings
DEFAULT_CONFIG = {
    "nim_api_key": "",
    "deepgram_api_key": "",
    "model_name": "nvidia/nemotron-3.5-bolt-e4b",
    "voice_model": "aura-2-pluto-en",
    "playback_speed": 1.12,
    "spatial_reverb": False,
    "voice_enabled": True,
    "boot_greeting": True
}

# Colors
CYAN = "\033[96m"
BLUE = "\033[94m"
GOLD = "\033[93m"
GRAY = "\033[90m"
GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


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
    # Allow environment variable overrides
    if "NIM_KEY" in os.environ:
        cfg["nim_api_key"] = os.environ["NIM_KEY"]
    if "DEEPGRAM_KEY" in os.environ:
        cfg["deepgram_api_key"] = os.environ["DEEPGRAM_KEY"]
    return cfg


config = load_config()
nim_api_key = config["nim_api_key"]
deepgram_api_key = config["deepgram_api_key"]
model_name = config["model_name"]
voice_model = config["voice_model"]
playback_speed = float(config.get("playback_speed", 1.12))
spatial_reverb = bool(config.get("spatial_reverb", False))
voice_enabled = bool(config.get("voice_enabled", True))

current_speech_proc = None
last_response_text = ""


def get_telemetry():
    """Gathers real-time machine and environment telemetry."""
    now_str = time.strftime("%A, %B %d, %I:%M %p")
    
    # Weather from Stark Rice cache
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

    # Music state from Stark Player / Zenify
    music_info = "No track currently queued"
    m_path = os.path.expanduser("~/.config/stark-rice/music_state.json")
    if os.path.exists(m_path):
        try:
            with open(m_path, "r", encoding="utf-8") as f:
                m = json.load(f)
                title = m.get("title", "").strip()
                artist = m.get("artist", "").strip()
                st = "Playing" if m.get("is_playing") else "Paused"
                if title and artist:
                    music_info = f"'{title}' by {artist} (Status: {st})"
                elif title:
                    music_info = f"'{title}' (Status: {st})"
        except Exception:
            pass

    # System memory & load
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
    "You have real-time access to Sir's Arch Linux system and Stark Rice environment.\n\n"
    "Crucial Music Formatting Rule:\n"
    "Whenever Sir asks about music, or commands any playback action (pause, play, resume, status, skip, what song is this), "
    "you MUST ALWAYS explicitly include both the track name and artist in the exact phrasing format: '<Track Name> by <Artist>'.\n"
    "- When pausing: state that you are pausing '<Track Name> by <Artist>'.\n"
    "- When resuming or playing: state that you are resuming '<Track Name> by <Artist>'.\n"
    "- When asked what is playing or about the track: state that we are listening to '<Track Name> by <Artist>'.\n\n"
    "If Sir asks to perform a system action, include an action tag at the very end of your response, for example:\n"
    "[ACTION: music_pause]\n"
    "[ACTION: music_play]\n"
    "[ACTION: music_toggle]\n"
    "[ACTION: music_next]\n"
    "[ACTION: music_prev]\n"
    "[ACTION: volume_up]\n"
    "[ACTION: volume_down]\n"
    "[ACTION: volume_mute]\n"
    "[ACTION: open_zenify]\n"
    "[ACTION: lock_screen]\n"
    "[ACTION: reload_ui]\n"
    "Do not recite action tags in dialogue; append them cleanly at the end."
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
    """Removes action tags, code blocks, and markdown asterisks for natural vocalization."""
    # Remove action tags
    t = re.sub(r"\[ACTION:\s*[a-zA-Z0-9_-]+\]", "", text)
    # Remove markdown formatting
    t = re.sub(r"[*_~`#]", "", t)
    # Condense excess whitespace
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

    # Terminate prior speech so voices don't overlap
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


def query_jarvis(user_input, history):
    """Sends query to NVIDIA NIM Nemotron with live telemetry."""
    telemetry = get_telemetry()
    system_prompt = f"{SYSTEM_PROMPT_BASE}\n\n{telemetry}"
    
    messages = [{"role": "system", "content": system_prompt}]
    # Append recent conversation history
    messages.extend(history[-10:])
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
        
        # Parse action tag if present
        action_match = re.search(r"\[ACTION:\s*([a-zA-Z0-9_-]+)\]", raw_reply)
        action = action_match.group(1) if action_match else None
        clean_reply = re.sub(r"\[ACTION:\s*[a-zA-Z0-9_-]+\]", "", raw_reply).strip()
        
        return clean_reply, action


def print_banner():
    reverb_str = f"{GREEN}ON{RESET}" if spatial_reverb else f"{GRAY}OFF{RESET}"
    voice_str = f"{GREEN}ACTIVE{RESET}" if voice_enabled else f"{RED}MUTED{RESET}"
    
    w_path = os.path.expanduser("~/.config/stark-rice/weather_cache.json")
    weather_summary = "Ready"
    if os.path.exists(w_path):
        try:
            with open(w_path, "r", encoding="utf-8") as f:
                w = json.load(f)
                weather_summary = f"{w.get('temp_c')}°C {w.get('condition')}"
        except Exception:
            pass

    banner = f"""{CYAN}{BOLD}
  ╔═══════════════════════════════════════════════════════════════════════════╗
  ║                        J . A . R . V . I . S .                            ║
  ║                 Just A Rather Very Intelligent System                     ║
  ║  Brain: NVIDIA Nemotron 3.5 Bolt       •  Voice: Deepgram Pluto (Aura-2)  ║
  ║  Speed: {playback_speed:.2f}x  •  Acoustic: {reverb_str}  •  Voice: {voice_str}  •  Status: {weather_summary:<14} ║
  ║  Controls: 'speed <val>' • 'reverb' • 'mute' • 'clear' • 'repeat' • 'q'  ║
  ╚═══════════════════════════════════════════════════════════════════════════╝{RESET}"""
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

        if lower.startswith("speed "):
            try:
                val = float(lower.split(" ", 1)[1])
                playback_speed = max(0.7, min(2.5, val))
                print(f"{GRAY}[Playback speed set to {playback_speed:.2f}x.]{RESET}\n")
            except ValueError:
                print(f"{GRAY}[Usage example: speed 1.15]{RESET}\n")
            continue

        if lower in ("faster", "speed up"):
            playback_speed = min(2.5, round(playback_speed + 0.05, 2))
            print(f"{GRAY}[Playback speed increased to {playback_speed:.2f}x.]{RESET}\n")
            continue

        if lower in ("slower", "slow down"):
            playback_speed = max(0.7, round(playback_speed - 0.05, 2))
            print(f"{GRAY}[Playback speed decreased to {playback_speed:.2f}x.]{RESET}\n")
            continue
            
        if lower in ("replay", "repeat"):
            if last_response_text:
                print(f"{CYAN}{BOLD}J.A.R.V.I.S.{RESET} {GRAY}›{RESET} Replaying audio...\n")
                speak_text(last_response_text, wait=False)
            else:
                print(f"{GRAY}[No previous response to replay, Sir.]{RESET}\n")
            continue

        if lower in ("status", "diagnostics", "telemetry"):
            show_system_status()
            continue

        if lower in ("song", "track", "music", "playing", "now playing"):
            m_path = os.path.expanduser("~/.config/stark-rice/music_state.json")
            if os.path.exists(m_path):
                try:
                    with open(m_path, "r", encoding="utf-8") as f:
                        m = json.load(f)
                        t = m.get("title")
                        a = m.get("artist")
                        st = "playing" if m.get("is_playing") else "currently paused"
                        if t and a:
                            reply = f"We are listening to '{t}' by {a}, which is {st}, Sir."
                        else:
                            reply = "No active audio track is currently loaded, Sir."
                except Exception:
                    reply = "Unable to read current audio telemetry, Sir."
            else:
                reply = "No active audio track is currently loaded, Sir."
            print(f"{CYAN}{BOLD}J.A.R.V.I.S.{RESET} {GRAY}›{RESET} {reply}\n")
            speak_text(reply, wait=False)
            continue

        try:
            print(f"{GRAY}Thinking...{RESET}", end="\r", flush=True)
            reply, action = query_jarvis(user_input, history)
            last_response_text = reply
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": reply})
            
            # Clear thinking indicator
            print(" " * 24, end="\r")
            
            # Show reply
            print(f"{CYAN}{BOLD}J.A.R.V.I.S.{RESET} {GRAY}›{RESET} {reply}\n")
            
            # Speak first: if an action is pending, wait for vocal delivery to finish before executing
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
        print("  jarvis                    # Launch interactive J.A.R.V.I.S. HUD")
        print("  jarvis 'your question'    # One-shot command & voice response")
        print("  jarvis --boot             # Play startup system greeting")
        return

    if args:
        user_query = " ".join(args)
        reply, action = query_jarvis(user_query, [])
        print(f"{CYAN}{BOLD}J.A.R.V.I.S.{RESET} {GRAY}›{RESET} {reply}")
        # Wait for TTS to finish vocalization before executing system action
        speak_text(reply, wait=True)
        if action:
            time.sleep(0.12)
            execute_action(action)
        return

    interactive_session()


if __name__ == "__main__":
    main()
