from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_FILE = CACHE_DIR / "lyrics_cache.json"
TRANSLATION_CACHE_FILE = CACHE_DIR / "translation_cache.json"

APP_NAME = "Desktop Musik Lirik"
APP_VERSION = "1.0.0"

WINDOW_WIDTH = 920
WINDOW_HEIGHT = 560
MIN_WINDOW_WIDTH = 560
MIN_WINDOW_HEIGHT = 340

DEFAULT_OPACITY = 0.94
IDLE_OPACITY = 0.72

POLL_INTERVAL_SECONDS = 1.2
UI_TICK_MS = 90
QUEUE_POLL_MS = 180
HTTP_TIMEOUT_SECONDS = 12
TRANSLATE_TIMEOUT_SECONDS = 12

CACHE_TTL_SECONDS = 60 * 60 * 24 * 14
MISS_TTL_SECONDS = 60 * 15

LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
LRCLIB_GET_URL = "https://lrclib.net/api/get"
LYRICS_OVH_URL = "https://api.lyrics.ovh/v1"
GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
LYRICS_CACHE_VERSION = "lyrics-v3"

LYRIC_LINE_SPACING = 18
LYRIC_TOP_PADDING = 96

WINDOW_TITLE_IGNORE = {
    "youtube",
    "youtube music",
    "google chrome",
    "microsoft edge",
}

BROWSER_SUFFIXES = (
    " - youtube music - google chrome",
    " - youtube music - microsoft edge",
    " - youtube - google chrome",
    " - youtube - microsoft edge",
    " - google chrome",
    " - microsoft edge",
    " - chrome",
    " - edge",
)

NOISE_PATTERNS = (
    r"\((official|music)\s+(video|audio|lyric|lyrics)\)",
    r"\[(official|music)\s+(video|audio|lyric|lyrics)\]",
    r"\((official)\)",
    r"\[(official)\]",
    r"\((audio|lyrics?)\)",
    r"\[(audio|lyrics?)\]",
    r"\((live|visualizer|karaoke|performance)\)",
    r"\[(live|visualizer|karaoke|performance)\]",
    r"\((remastered?|version)\)",
    r"\[(remastered?|version)\]",
    r"\b(official|lyrics?|audio|video|mv|hd|4k)\b",
)

COLORS = {
    "window": "#06080c",
    "panel": "#10141c",
    "panel_border": "#1f2835",
    "panel_soft": "#161d28",
    "text": "#f8fafc",
    "muted": "#94a3b8",
    "subtle": "#64748b",
    "accent": "#7dd3fc",
    "accent_soft": "#38bdf8",
    "highlight": "#f8fafc",
    "past": "#cbd5e1",
    "future": "#8b98a9",
    "inactive": "#64748b",
    "danger": "#f87171",
}
