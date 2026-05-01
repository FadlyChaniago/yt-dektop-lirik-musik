from __future__ import annotations

import re
from collections.abc import Iterable

from app import config
from app.models import SongInfo
from app.utils.text_codec import repair_text


FEATURE_ARTIST_RE = re.compile(r"\b(?:feat\.?|ft\.?|featuring)\b", re.IGNORECASE)
SEPARATOR_RE = re.compile(r"\s*(?:-|–|—|:|/|\|)\s*")
QUOTE_RE = re.compile(r"^[\'\"“”‘’]+|[\'\"“”‘’]+$")
LEADING_INDEX_RE = re.compile(r"^[\(\[]?\d{1,4}[\)\]]?\s*")
KNOWN_SUFFIX_RE = re.compile(
    r"\s*-\s*(?:youtube(?:\s+music)?|the first take|colors show|lyric video)$",
    re.IGNORECASE,
)


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
    cleaned = repair_text(strip_browser_suffix(value))
    cleaned = cleaned.replace("•", " - ")
    cleaned = cleaned.replace("|", " - ")
    cleaned = cleaned.replace("_", " ")
    cleaned = LEADING_INDEX_RE.sub("", cleaned)

    for pattern in config.NOISE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s*-\s*topic$", "", cleaned, flags=re.IGNORECASE)
    cleaned = KNOWN_SUFFIX_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" -")
    return compact_spaces(cleaned)


def strip_feature_suffix(value: str) -> str:
    cleaned = clean_song_title(value)
    parts = FEATURE_ARTIST_RE.split(cleaned, maxsplit=1)
    if parts:
        return compact_spaces(parts[0].strip(" -,/"))
    return cleaned


def split_artist_variants(value: str) -> list[str]:
    cleaned = clean_song_title(value)
    variants: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        normalized = compact_spaces(item)
        key = normalized.lower()
        if not normalized or key in seen:
            return
        seen.add(key)
        variants.append(normalized)

    add(cleaned)
    add(strip_feature_suffix(cleaned))

    pieces = re.split(r"\s*(?:,|&| x | and )\s*", strip_feature_suffix(cleaned), flags=re.IGNORECASE)
    for piece in pieces:
        add(piece)

    return variants


def split_track_variants(value: str) -> list[str]:
    cleaned = clean_song_title(value)
    variants: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        normalized = compact_spaces(QUOTE_RE.sub("", item).strip(" -"))
        key = normalized.lower()
        if not normalized or key in seen:
            return
        seen.add(key)
        variants.append(normalized)

    add(cleaned)
    add(strip_feature_suffix(cleaned))
    add(re.sub(r"\s*\((?:from|ost|soundtrack).*?\)$", "", cleaned, flags=re.IGNORECASE))

    return variants


def _add_song_candidate(
    candidates: list[tuple[str, str]],
    seen: set[tuple[str, str]],
    track: str,
    artist: str = "",
) -> None:
    track_variants = split_track_variants(track)
    artist_variants = split_artist_variants(artist) if artist else [""]

    for track_value in track_variants:
        for artist_value in artist_variants:
            key = (track_value.lower(), artist_value.lower())
            if not track_value or key in seen:
                continue
            seen.add(key)
            candidates.append((track_value, artist_value))


def extract_song_candidates(raw_title: str) -> list[tuple[str, str]]:
    cleaned = clean_song_title(raw_title)
    if not cleaned:
        return []

    candidates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    parts = [compact_spaces(part) for part in SEPARATOR_RE.split(cleaned) if compact_spaces(part)]

    if len(parts) >= 2:
        left = parts[0]
        right = " - ".join(parts[1:])
        _add_song_candidate(candidates, seen, right, left)
        _add_song_candidate(candidates, seen, left, right)

    if len(parts) >= 3:
        _add_song_candidate(candidates, seen, parts[-1], " - ".join(parts[:-1]))
        _add_song_candidate(candidates, seen, " - ".join(parts[1:]), parts[0])

    if len(parts) == 1:
        tokens = [token for token in cleaned.split(" ") if token]
        if len(tokens) >= 2:
            first_token = tokens[0]
            remainder = " ".join(tokens[1:])
            if re.search(r"\d|[._]", first_token) or first_token != first_token.title():
                _add_song_candidate(candidates, seen, remainder, first_token)

    _add_song_candidate(candidates, seen, cleaned, "")

    return candidates


def build_song_queries(song: SongInfo) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    _add_song_candidate(candidates, seen, song.track, song.artist)
    _add_song_candidate(candidates, seen, song.query_text, song.artist)

    for track, artist in extract_song_candidates(song.query_text):
        _add_song_candidate(candidates, seen, track, artist)

    return candidates


def song_from_window_title(title: str, source_app: str) -> SongInfo | None:
    cleaned = clean_song_title(title)
    if not cleaned or cleaned.lower() in config.WINDOW_TITLE_IGNORE:
        return None

    candidates = extract_song_candidates(cleaned)
    with_artist = next((candidate for candidate in candidates if candidate[1]), None)
    if with_artist:
        track, artist = with_artist
    elif candidates:
        track, artist = candidates[0]
    else:
        track, artist = cleaned, ""

    return SongInfo(
        track=track,
        artist=artist,
        raw_title=cleaned,
        source_app=source_app,
        detection_method="window_title",
        confidence=0.55 if artist else 0.45,
    )


def enrich_song_with_window_title(primary: SongInfo, fallback: SongInfo | None) -> SongInfo:
    if fallback is None:
        return primary

    primary_track = clean_song_title(primary.track)
    fallback_track = clean_song_title(fallback.track)
    primary_artist = clean_song_title(primary.artist)
    fallback_artist = clean_song_title(fallback.artist)

    should_merge_artist = not primary_artist and bool(fallback_artist)
    should_merge_track = bool(fallback_track) and (
        not primary_track or primary_track.lower() in fallback.raw_title.lower()
    )

    if not should_merge_artist and not should_merge_track:
        return primary

    return SongInfo(
        track=fallback_track or primary.track,
        artist=fallback_artist or primary.artist,
        album=primary.album,
        raw_title=fallback.raw_title or primary.raw_title,
        source_app=primary.source_app or fallback.source_app,
        detection_method=primary.detection_method,
        position_seconds=primary.position_seconds,
        duration_seconds=primary.duration_seconds,
        is_playing=primary.is_playing,
        detected_at=primary.detected_at,
        confidence=max(primary.confidence, fallback.confidence),
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
