from __future__ import annotations

import re
from typing import Iterable

from app import config
from app.models import SongInfo


def compact_spaces(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_text(value: str) -> str:
    return compact_spaces(value.lower())


def strip_browser_suffix(title: str) -> str:
    cleaned = compact_spaces(title)
    lowered = cleaned.lower()
    for suffix in config.BROWSER_SUFFIXES:
        if lowered.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            cleaned = compact_spaces(cleaned)
            lowered = cleaned.lower()
            break
    return cleaned


def clean_song_title(value: str) -> str:
    cleaned = strip_browser_suffix(value)
    cleaned = cleaned.replace("•", " - ")
    cleaned = cleaned.replace("|", " - ")
    cleaned = cleaned.replace("_", " ")

    for pattern in config.NOISE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s*-\s*topic$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" -")
    return compact_spaces(cleaned)


def extract_song_candidates(raw_title: str) -> list[tuple[str, str]]:
    cleaned = clean_song_title(raw_title)
    if not cleaned:
        return []

    candidates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(track: str, artist: str = "") -> None:
        track_value = compact_spaces(track)
        artist_value = compact_spaces(artist)
        if not track_value:
            return
        key = (track_value.lower(), artist_value.lower())
        if key in seen:
            return
        seen.add(key)
        candidates.append((track_value, artist_value))

    add(cleaned, "")

    parts = [compact_spaces(part) for part in cleaned.split(" - ") if compact_spaces(part)]
    if len(parts) >= 2:
        left = parts[0]
        right = " - ".join(parts[1:])
        add(right, left)
        add(left, right)

    if len(parts) >= 3:
        add(" - ".join(parts[1:]), parts[0])
        add(parts[-1], " - ".join(parts[:-1]))

    return candidates


def song_from_window_title(title: str, source_app: str) -> SongInfo | None:
    cleaned = clean_song_title(title)
    if not cleaned or cleaned.lower() in config.WINDOW_TITLE_IGNORE:
        return None

    candidates = extract_song_candidates(cleaned)
    if candidates:
        track, artist = candidates[0]
    else:
        track, artist = cleaned, ""

    return SongInfo(
        track=track,
        artist=artist,
        raw_title=cleaned,
        source_app=source_app,
        detection_method="window_title",
        confidence=0.55,
    )


def guess_browser_from_title(title: str) -> str:
    lowered = title.lower()
    if "edge" in lowered:
        return "microsoft-edge"
    if "chrome" in lowered:
        return "google-chrome"
    return "browser"


def titles_match_browser_rules(titles: Iterable[str]) -> list[str]:
    matched: list[str] = []
    for title in titles:
        lowered = title.lower().strip()
        if not lowered:
            continue
        if "youtube" not in lowered:
            continue
        if "chrome" not in lowered and "edge" not in lowered:
            continue
        matched.append(title.strip())
    return matched
