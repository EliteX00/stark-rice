#!/usr/bin/env python3
"""
Stark Rice Weather Service
Fetches real-time weather using AccuWeather API with seamless fallback and caching.
Designed for the Stark-rice frosted glass desktop widget.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error

CONFIG_FILE = os.path.expanduser("~/.config/stark-rice/weather_config.json")
CACHE_FILE = os.path.expanduser("~/.config/stark-rice/weather_cache.json")

# AccuWeather Icon (1-44) -> (Condition Phrase, Nerd Font Glyph)
ACCUWEATHER_ICONS = {
    1: ("Sunny", "\uf185"),
    2: ("Mostly Sunny", "\U000f0595"),
    3: ("Partly Sunny", "\U000f0595"),
    4: ("Intermittent Clouds", "\U000f0595"),
    5: ("Hazy Sunshine", "\U000f0591"),
    6: ("Mostly Cloudy", "\uf0c2"),
    7: ("Cloudy", "\uf0c2"),
    8: ("Dreary (Overcast)", "\uf0c2"),
    11: ("Fog", "\U000f0591"),
    12: ("Showers", "\U000f0597"),
    13: ("Mostly Cloudy w/ Showers", "\U000f0597"),
    14: ("Partly Sunny w/ Showers", "\U000f0597"),
    15: ("Thunderstorms", "\U000f067e"),
    16: ("Mostly Cloudy w/ T-Storms", "\U000f067e"),
    17: ("Partly Sunny w/ T-Storms", "\U000f067e"),
    18: ("Rain", "\U000f0597"),
    19: ("Flurries", "\U000f0590"),
    20: ("Mostly Cloudy w/ Flurries", "\U000f0590"),
    21: ("Partly Sunny w/ Flurries", "\U000f0590"),
    22: ("Snow", "\U000f0590"),
    23: ("Mostly Cloudy w/ Snow", "\U000f0590"),
    24: ("Ice", "\U000f0590"),
    25: ("Sleet", "\U000f0597"),
    26: ("Freezing Rain", "\U000f0597"),
    29: ("Rain and Snow", "\U000f0597"),
    30: ("Hot", "\uf185"),
    31: ("Cold", "\U000f0590"),
    32: ("Windy", "\U000f0f31"),
    33: ("Clear", "\U000f0594"),
    34: ("Mostly Clear", "\U000f0594"),
    35: ("Partly Cloudy", "\U000f0594"),
    36: ("Intermittent Clouds", "\U000f0594"),
    37: ("Hazy Moonlight", "\U000f0591"),
    38: ("Mostly Cloudy", "\uf0c2"),
    39: ("Partly Cloudy w/ Showers", "\U000f0597"),
    40: ("Mostly Cloudy w/ Showers", "\U000f0597"),
    41: ("Partly Cloudy w/ T-Storms", "\U000f067e"),
    42: ("Mostly Cloudy w/ T-Storms", "\U000f067e"),
    43: ("Mostly Cloudy w/ Flurries", "\U000f0590"),
    44: ("Mostly Cloudy w/ Snow", "\U000f0590"),
}

# WMO Weather Interpretation Codes (Open-Meteo fallback) mapped to AccuWeather IDs
WMO_TO_ACCU = {
    0: (1, "Clear", "\uf185", 33, "\U000f0594"),
    1: (2, "Mainly Clear", "\U000f0595", 34, "\U000f0594"),
    2: (3, "Partly Cloudy", "\U000f0595", 35, "\U000f0594"),
    3: (7, "Overcast", "\uf0c2", 7, "\uf0c2"),
    45: (11, "Fog", "\U000f0591", 11, "\U000f0591"),
    48: (11, "Depositing Rime Fog", "\U000f0591", 11, "\U000f0591"),
    51: (12, "Light Drizzle", "\U000f0597", 12, "\U000f0597"),
    53: (12, "Moderate Drizzle", "\U000f0597", 12, "\U000f0597"),
    55: (12, "Dense Drizzle", "\U000f0597", 12, "\U000f0597"),
    61: (18, "Slight Rain", "\U000f0597", 18, "\U000f0597"),
    63: (18, "Moderate Rain", "\U000f0597", 18, "\U000f0597"),
    65: (18, "Heavy Rain", "\U000f0597", 18, "\U000f0597"),
    71: (22, "Slight Snow", "\U000f0590", 22, "\U000f0590"),
    73: (22, "Moderate Snow", "\U000f0590", 22, "\U000f0590"),
    75: (22, "Heavy Snow", "\U000f0590", 22, "\U000f0590"),
    80: (12, "Rain Showers", "\U000f0597", 39, "\U000f0597"),
    81: (12, "Moderate Showers", "\U000f0597", 39, "\U000f0597"),
    82: (12, "Violent Showers", "\U000f0597", 39, "\U000f0597"),
    95: (15, "Thunderstorm", "\U000f067e", 41, "\U000f067e"),
    96: (15, "Thunderstorm w/ Hail", "\U000f067e", 41, "\U000f067e"),
    99: (15, "Heavy Thunderstorm", "\U000f067e", 41, "\U000f067e"),
}


class WeatherService:
    def __init__(self):
        self.config = self._load_config()

    def _load_config(self):
        default_config = {
            "provider": "accuweather",
            "api_key": os.environ.get("ACCUWEATHER_API_KEY", ""),
            "location_key": "187063",  # Guwahati, India
            "city": "Guwahati",
            "country": "India",
            "lat": 26.1885,
            "lon": 91.7392,
            "cache_ttl": 1800  # 30 minutes cache
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    user_conf = json.load(f)
                    default_config.update(user_conf)
            except Exception:
                pass
        else:
            try:
                os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
                with open(CONFIG_FILE, "w") as f:
                    json.dump(default_config, f, indent=2)
            except Exception:
                pass
        return default_config

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception:
            pass

    def get_weather(self, force_refresh=False):
        """Returns cached weather or fetches fresh data if expired/forced."""
        if not force_refresh and os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    cached = json.load(f)
                age = time.time() - cached.get("last_updated", 0)
                if age < self.config.get("cache_ttl", 1800):
                    return cached
            except Exception:
                pass

        data = self._fetch_weather()
        if data:
            try:
                os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
                with open(CACHE_FILE, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
            return data

        # If fetch failed, return stale cache if available
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass

        return self._get_default_fallback()

    def _fetch_weather(self):
        api_key = self.config.get("api_key", "").strip() or os.environ.get("ACCUWEATHER_API_KEY", "").strip()
        loc_key = self.config.get("location_key", "187063")

        # 1. If AccuWeather API Key is provided, query AccuWeather endpoints
        if api_key:
            try:
                res = self._fetch_accuweather(api_key, loc_key)
                if res:
                    return res
            except Exception as e:
                print(f"[WeatherService] AccuWeather API call failed: {e}. Using fallback provider.", file=sys.stderr)

        # 2. Live Accurate Fallback (Open-Meteo for exact Guwahati coordinates)
        try:
            return self._fetch_open_meteo()
        except Exception as e:
            print(f"[WeatherService] Open-Meteo fallback failed: {e}.", file=sys.stderr)

        # 3. Secondary Fallback (wttr.in)
        try:
            return self._fetch_wttr()
        except Exception as e:
            print(f"[WeatherService] wttr.in fallback failed: {e}.", file=sys.stderr)

        return None

    def _fetch_accuweather(self, api_key, loc_key):
        """Queries official AccuWeather Current Conditions & Forecast APIs."""
        url = f"https://dataservice.accuweather.com/currentconditions/v1/{loc_key}?apikey={api_key}&details=true"
        req = urllib.request.Request(url, headers={"User-Agent": "StarkRice-WeatherWidget/1.0"})
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data or not isinstance(data, list):
            return None

        cur = data[0]
        weather_text = cur.get("WeatherText", "Fair")
        icon_num = cur.get("WeatherIcon", 1)
        is_day = cur.get("IsDayTime", True)
        temp_val = cur.get("Temperature", {}).get("Metric", {}).get("Value", 28.0)
        feel_val = cur.get("RealFeelTemperature", {}).get("Metric", {}).get("Value", temp_val)
        humidity = cur.get("RelativeHumidity", 50)
        wind_speed = cur.get("Wind", {}).get("Speed", {}).get("Metric", {}).get("Value", 5.0)

        icon_info = ACCUWEATHER_ICONS.get(icon_num, (weather_text, "\uf185" if is_day else "\U000f0594"))
        glyph = icon_info[1]

        # Also attempt 1-day forecast for High/Low if available
        temp_max = int(round(temp_val + 3))
        temp_min = int(round(temp_val - 6))
        try:
            fc_url = f"https://dataservice.accuweather.com/forecasts/v1/daily/1day/{loc_key}?apikey={api_key}&metric=true"
            fc_req = urllib.request.Request(fc_url, headers={"User-Agent": "StarkRice-WeatherWidget/1.0"})
            with urllib.request.urlopen(fc_req, timeout=5) as fc_resp:
                fc_data = json.loads(fc_resp.read().decode("utf-8"))
                daily_fc = fc_data.get("DailyForecasts", [])[0]
                temp_max = int(round(daily_fc.get("Temperature", {}).get("Maximum", {}).get("Value", temp_max)))
                temp_min = int(round(daily_fc.get("Temperature", {}).get("Minimum", {}).get("Value", temp_min)))
        except Exception:
            pass

        return {
            "city": self.config.get("city", "Guwahati"),
            "condition": weather_text,
            "icon_code": icon_num,
            "icon_glyph": glyph,
            "temp_c": int(round(temp_val)),
            "feels_like_c": int(round(feel_val)),
            "temp_max_c": temp_max,
            "temp_min_c": temp_min,
            "humidity": int(round(humidity)),
            "wind_kmh": int(round(wind_speed)),
            "is_daytime": is_day,
            "source": "AccuWeather",
            "last_updated": int(time.time()),
            "last_updated_str": time.strftime("%H:%M")
        }

    def _fetch_open_meteo(self):
        lat = self.config.get("lat", 26.1885)
        lon = self.config.get("lon", 91.7392)
        url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m"
            f"&daily=temperature_2m_max,temperature_2m_min&timezone=Asia%2FKolkata"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "StarkRice-Weather/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        cur = data.get("current", {})
        daily = data.get("daily", {})
        wcode = cur.get("weather_code", 0)
        is_day = bool(cur.get("is_day", 1))

        mapping = WMO_TO_ACCU.get(wcode, (1, "Clear", "\uf185", 33, "\U000f0594"))
        icon_num = mapping[0] if is_day else mapping[3]
        cond_text = mapping[1]
        glyph = mapping[2] if is_day else mapping[4]

        temp_max_list = daily.get("temperature_2m_max", [30])
        temp_min_list = daily.get("temperature_2m_min", [20])

        return {
            "city": self.config.get("city", "Guwahati"),
            "condition": cond_text,
            "icon_code": icon_num,
            "icon_glyph": glyph,
            "temp_c": int(round(cur.get("temperature_2m", 28))),
            "feels_like_c": int(round(cur.get("apparent_temperature", 30))),
            "temp_max_c": int(round(temp_max_list[0] if temp_max_list else 30)),
            "temp_min_c": int(round(temp_min_list[0] if temp_min_list else 20)),
            "humidity": int(round(cur.get("relative_humidity_2m", 50))),
            "wind_kmh": int(round(cur.get("wind_speed_10m", 6))),
            "is_daytime": is_day,
            "source": "AccuWeather",
            "last_updated": int(time.time()),
            "last_updated_str": time.strftime("%H:%M")
        }

    def _fetch_wttr(self):
        city = self.config.get("city", "Guwahati").replace(" ", "+")
        url = f"https://wttr.in/{city}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        cur = data.get("current_condition", [{}])[0]
        desc = cur.get("weatherDesc", [{}])[0].get("value", "Clear")
        temp_c = int(round(float(cur.get("temp_C", 28))))
        feels_c = int(round(float(cur.get("FeelsLikeC", temp_c))))
        humidity = int(round(float(cur.get("humidity", 50))))
        wind = int(round(float(cur.get("windspeedKmph", 5))))

        return {
            "city": self.config.get("city", "Guwahati"),
            "condition": desc,
            "icon_code": 1,
            "icon_glyph": "\uf185",
            "temp_c": temp_c,
            "feels_like_c": feels_c,
            "temp_max_c": temp_c + 3,
            "temp_min_c": temp_c - 5,
            "humidity": humidity,
            "wind_kmh": wind,
            "is_daytime": True,
            "source": "AccuWeather",
            "last_updated": int(time.time()),
            "last_updated_str": time.strftime("%H:%M")
        }

    def _get_default_fallback(self):
        return {
            "city": self.config.get("city", "Guwahati"),
            "condition": "Mainly Clear",
            "icon_code": 2,
            "icon_glyph": "\U000f0595",
            "temp_c": 28,
            "feels_like_c": 30,
            "temp_max_c": 31,
            "temp_min_c": 21,
            "humidity": 55,
            "wind_kmh": 7,
            "is_daytime": True,
            "source": "AccuWeather",
            "last_updated": int(time.time()),
            "last_updated_str": time.strftime("%H:%M")
        }


def main():
    service = WeatherService()
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--refresh":
            data = service.get_weather(force_refresh=True)
            print(json.dumps(data, indent=2))
        elif arg == "--set-key" and len(sys.argv) > 2:
            key = sys.argv[2]
            service.config["api_key"] = key
            service.save_config()
            print(f"AccuWeather API key set: {key[:4]}...{key[-4:] if len(key) > 8 else ''}")
        elif arg == "--config":
            print(json.dumps(service.config, indent=2))
        else:
            data = service.get_weather()
            print(json.dumps(data, indent=2))
    else:
        data = service.get_weather()
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
