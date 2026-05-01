from __future__ import annotations

import time
from difflib import SequenceMatcher
from typing import Any

import requests

from app import config
from app.models import LyricsResult, SongInfo
from app.services.cache_service import LyricsCache
from app.services.song_normalizer import clean_song_title, extract_song_candidates
from app.utils.lrc_parser import parse_lrc, plain_text_to_lines


class LyricsService:
    def __init__(self, cache: LyricsCache) -> None:
        self.cache = cache
        self.headers = {
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json",
        }

    def get_lyrics(self, song: SongInfo) -> tuple[LyricsResult | None, str]:
        cache_key = song.cache_key()
        cached = self.cache.get(cache_key)
        if cached:
            if cached.get("status") == "ok":
                return LyricsResult.from_dict(cached["data"]), "cache"
            return None, cached.get("reason", "Lirik tidak ditemukan.")

        try:
            result = self._fetch_from_network(song)
        except requests.RequestException as exc:
            return None, f"Gagal mengambil lirik: {exc}"

        if result is None:
            self.cache.set(
                cache_key,
                {"status": "miss", "reason": "Lirik tidak ditemukan untuk lagu ini."},
                ttl_seconds=config.MISS_TTL_SECONDS,
            )
            return None, "Lirik tidak ditemukan untuk lagu ini."

        self.cache.set(
            cache_key,
            {"status": "ok", "data": result.to_dict()},
            ttl_seconds=config.CACHE_TTL_SECONDS,
        )
        return result, "network"

    def _fetch_from_network(self, song: SongInfo) -> LyricsResult | None:
        all_results: dict[int, dict[str, Any]] = {}

        for candidate in self._build_search_candidates(song):
            payload = self._search(candidate)
            for item in payload:
                try:
                    item_id = int(item.get("id"))
                except (TypeError, ValueError):
                    continue
                all_results[item_id] = item

        if not all_results:
            return None

        ranked = sorted(
            all_results.values(),
            key=lambda item: self._score_result(item, song),
            reverse=True,
        )

        best_match = ranked[0]
        synced_lyrics = best_match.get("syncedLyrics") or ""
        plain_lyrics = best_match.get("plainLyrics") or ""
        instrumental = bool(best_match.get("instrumental", False))

        if instrumental and not synced_lyrics and not plain_lyrics:
            return None

        if synced_lyrics:
            lines = parse_lrc(synced_lyrics, fallback_duration=song.duration_seconds)
            synced = True
        else:
            lines = plain_text_to_lines(plain_lyrics)
            synced = False

        if not lines:
            return None

        return LyricsResult(
            track_name=str(best_match.get("trackName", "") or song.track),
            artist_name=str(best_match.get("artistName", "") or song.artist),
            album_name=str(best_match.get("albumName", "") or song.album),
            source="lrclib",
            synced=synced,
            instrumental=instrumental,
            plain_lyrics=plain_lyrics,
            fetched_at=time.time(),
            lines=lines,
        )

    def _build_search_candidates(self, song: SongInfo) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()

        def add(track: str, artist: str = "", album: str = "") -> None:
            track_value = clean_song_title(track)
            artist_value = clean_song_title(artist)
            album_value = clean_song_title(album)
            if not track_value:
                return
            key = (track_value.lower(), artist_value.lower(), album_value.lower())
            if key in seen:
                return
            seen.add(key)

            payload = {"track_name": track_value}
            if artist_value:
                payload["artist_name"] = artist_value
            if album_value:
                payload["album_name"] = album_value
            candidates.append(payload)

        add(song.track, song.artist, song.album)
        add(song.query_text, song.artist, song.album)

        for track, artist in extract_song_candidates(song.query_text):
            add(track, artist, song.album)

        return candidates

    def _search(self, params: dict[str, str]) -> list[dict[str, Any]]:
        response = requests.get(
            config.LRCLIB_SEARCH_URL,
            headers=self.headers,
            params=params,
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict) and payload.get("trackName"):
            return [payload]
        return []

    def _score_result(self, item: dict[str, Any], song: SongInfo) -> float:
        track_name = clean_song_title(str(item.get("trackName", "") or ""))
        artist_name = clean_song_title(str(item.get("artistName", "") or ""))
        album_name = clean_song_title(str(item.get("albumName", "") or ""))

        track_target = clean_song_title(song.track or song.query_text)
        artist_target = clean_song_title(song.artist)
        query_target = clean_song_title(song.query_text)
        album_target = clean_song_title(song.album)

        score = 0.0
        score += 65 * self._similarity(track_name, track_target or query_target)
        score += 20 * self._similarity(f"{artist_name} {track_name}", query_target)

        if artist_target:
            score += 25 * self._similarity(artist_name, artist_target)

        if album_target and album_name:
            score += 10 * self._similarity(album_name, album_target)

        if item.get("syncedLyrics"):
            score += 18
        if item.get("plainLyrics"):
            score += 6
        if item.get("instrumental"):
            score -= 25

        return score

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        left_value = " ".join(left.lower().split())
        right_value = " ".join(right.lower().split())
        if not left_value or not right_value:
            return 0.0
        return SequenceMatcher(None, left_value, right_value).ratio()

