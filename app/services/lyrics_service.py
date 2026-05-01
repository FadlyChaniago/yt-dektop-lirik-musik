from __future__ import annotations

import json
import time
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

import requests

from app import config
from app.models import LyricLine, LyricsResult, SongInfo
from app.services.cache_service import LyricsCache
from app.services.song_normalizer import build_song_queries, clean_song_title, split_artist_variants, split_track_variants
from app.utils.lrc_parser import parse_lrc, plain_text_to_lines
from app.utils.text_codec import repair_text


class LyricsService:
    def __init__(self, cache: LyricsCache) -> None:
        self.cache = cache
        self.headers = {
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json",
        }

    def get_lyrics(self, song: SongInfo) -> tuple[LyricsResult | None, str]:
        cache_key = self._cache_key(song)
        cached = self.cache.get(cache_key)
        if cached:
            if cached.get("status") == "ok":
                return LyricsResult.from_dict(cached["data"]), "cache"
            return None, cached.get("reason", "Lirik tidak ditemukan.")

        try:
            result = self._fetch_from_network(song)
        except requests.RequestException as exc:
            return None, self._format_network_error(exc)

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

    def invalidate(self, song: SongInfo) -> None:
        self.cache.delete(self._cache_key(song))

    def _fetch_from_network(self, song: SongInfo) -> LyricsResult | None:
        all_results: dict[str, dict[str, Any]] = {}
        request_errors: list[requests.RequestException] = []

        for candidate in self._build_search_candidates(song):
            try:
                for item in self._search(candidate):
                    self._merge_result(all_results, item)
            except requests.RequestException as exc:
                request_errors.append(exc)

        for candidate in self._build_exact_candidates(song):
            try:
                item = self._get_exact_match(candidate)
            except requests.RequestException as exc:
                request_errors.append(exc)
                continue

            if item:
                self._merge_result(all_results, item)

        if not all_results:
            try:
                fallback_result = self._fetch_from_lyrics_ovh(song)
            except requests.RequestException as exc:
                request_errors.append(exc)
                fallback_result = None

            if fallback_result is not None:
                return fallback_result

        if not all_results:
            if request_errors:
                raise request_errors[-1]
            return None

        ranked = sorted(
            all_results.values(),
            key=lambda item: self._score_result(item, song),
            reverse=True,
        )

        best_match = self._normalize_result_item(ranked[0])
        synced_lyrics = str(best_match.get("syncedLyrics") or "")
        plain_lyrics = str(best_match.get("plainLyrics") or "")
        instrumental = bool(best_match.get("instrumental", False))

        if instrumental and not synced_lyrics and not plain_lyrics:
            return None

        if synced_lyrics:
            lines = parse_lrc(synced_lyrics, fallback_duration=song.duration_seconds)
            synced = True
            timing_mode = "synced"
        else:
            lines = plain_text_to_lines(plain_lyrics)
            synced = False
            timing_mode = "plain"
            if lines:
                lines = self._estimate_line_timing(lines, song)
                if lines and any(line.start_time is not None for line in lines):
                    timing_mode = "estimated"

        if not lines:
            return None

        return LyricsResult(
            track_name=repair_text(str(best_match.get("trackName", "") or song.track)),
            artist_name=repair_text(str(best_match.get("artistName", "") or song.artist)),
            album_name=repair_text(str(best_match.get("albumName", "") or song.album)),
            source="lrclib",
            synced=synced,
            timing_mode=timing_mode,
            instrumental=instrumental,
            plain_lyrics=repair_text(plain_lyrics),
            fetched_at=time.time(),
            lines=lines,
        )

    def _build_search_candidates(self, song: SongInfo) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        seen: set[tuple[tuple[str, str], ...]] = set()

        def add(*, track: str = "", artist: str = "", album: str = "", query: str = "") -> None:
            track_value = clean_song_title(track)
            artist_value = clean_song_title(artist)
            album_value = clean_song_title(album)
            query_value = clean_song_title(query)
            if not track_value and not query_value:
                return
            payload: dict[str, str] = {}
            if query_value:
                payload["q"] = query_value
            if track_value:
                payload["track_name"] = track_value
            if artist_value:
                payload["artist_name"] = artist_value
            if album_value:
                payload["album_name"] = album_value

            key = tuple(sorted((name, value.lower()) for name, value in payload.items()))
            if key in seen:
                return
            seen.add(key)
            candidates.append(payload)

        add(track=song.track, artist=song.artist, album=song.album)
        add(track=song.query_text, artist=song.artist, album=song.album)
        add(query=song.query_text)
        add(query=song.track)

        for track, artist in build_song_queries(song):
            add(track=track, artist=artist, album=song.album)
            add(track=track)
            if artist:
                add(track=track, artist=artist)
            add(query=f"{artist} {track}".strip())
            add(query=f"{track} {artist}".strip())

        return candidates

    def _build_exact_candidates(self, song: SongInfo) -> list[dict[str, str | int]]:
        if not song.duration_seconds:
            return []

        candidates: list[dict[str, str | int]] = []
        seen: set[tuple[str, str, str, int]] = set()
        duration = max(int(round(song.duration_seconds)), 1)

        def add(track: str, artist: str = "", album: str = "") -> None:
            track_value = clean_song_title(track)
            artist_value = clean_song_title(artist)
            album_value = clean_song_title(album)
            if not track_value or not artist_value:
                return

            key = (
                track_value.lower(),
                artist_value.lower(),
                album_value.lower(),
                duration,
            )
            if key in seen:
                return
            seen.add(key)
            payload: dict[str, str | int] = {
                "track_name": track_value,
                "artist_name": artist_value,
                "duration": duration,
            }
            if album_value:
                payload["album_name"] = album_value
            candidates.append(payload)

        add(song.track, song.artist, song.album)
        add(song.query_text, song.artist, song.album)

        artist_queries = [(track, artist) for track, artist in build_song_queries(song) if artist]
        for track, artist in artist_queries[:1]:
            add(track, artist, song.album)

        return candidates

    def _fetch_from_lyrics_ovh(self, song: SongInfo) -> LyricsResult | None:
        for track, artist in build_song_queries(song):
            if not track or not artist:
                continue

            for track_variant in split_track_variants(track):
                for artist_variant in split_artist_variants(artist):
                    lyrics = self._fetch_lyrics_ovh_text(track_variant, artist_variant)
                    if not lyrics:
                        continue

                    lines = plain_text_to_lines(lyrics)
                    lines = self._estimate_line_timing(lines, song)
                    if not lines:
                        continue

                    return LyricsResult(
                        track_name=track_variant,
                        artist_name=artist_variant,
                        album_name=song.album,
                        source="lyrics.ovh",
                        synced=False,
                        timing_mode="estimated" if any(line.start_time is not None for line in lines) else "plain",
                        instrumental=False,
                        plain_lyrics=lyrics,
                        fetched_at=time.time(),
                        lines=lines,
                    )

        return None

    def _fetch_lyrics_ovh_text(self, track: str, artist: str) -> str:
        url = f"{config.LYRICS_OVH_URL}/{quote(artist, safe='')}/{quote(track, safe='')}"
        response = requests.get(
            url,
            headers=self.headers,
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )

        if response.status_code == 404:
            return ""
        response.raise_for_status()

        payload = self._decode_json_response(response)
        if not isinstance(payload, dict):
            return ""

        lyrics = repair_text(str(payload.get("lyrics", "") or "")).strip()
        return lyrics

    def _estimate_line_timing(self, lines: list[LyricLine], song: SongInfo) -> list[LyricLine]:
        if not lines:
            return lines

        duration = song.duration_seconds
        if duration is None or duration <= 0:
            return lines

        total_lines = len(lines)
        intro_padding = min(max(duration * 0.05, 1.5), 8.0)
        outro_padding = min(max(duration * 0.02, 1.0), 4.0)
        usable_duration = max(duration - intro_padding - outro_padding, total_lines * 1.8)

        weights = [self._line_weight(line.text) for line in lines]
        total_weight = sum(weights) or float(total_lines)
        current_time = intro_padding

        estimated_lines: list[LyricLine] = []
        for index, line in enumerate(lines):
            ratio = weights[index] / total_weight
            segment_duration = max(1.8, usable_duration * ratio)
            if index == total_lines - 1:
                end_time = duration
            else:
                end_time = min(duration, current_time + segment_duration)

            estimated_lines.append(
                LyricLine(
                    text=line.text,
                    start_time=current_time,
                    end_time=end_time,
                )
            )
            current_time = end_time

        return estimated_lines

    @staticmethod
    def _line_weight(text: str) -> float:
        value = text.strip()
        if not value:
            return 1.0
        if value.startswith("[") and value.endswith("]"):
            return 1.8

        char_count = len(value.replace(" ", ""))
        word_count = max(len(value.split()), 1)
        return max(1.4, (char_count * 0.18) + (word_count * 0.6))

    def _search(self, params: dict[str, str]) -> list[dict[str, Any]]:
        try:
            payload = self._request_json(config.LRCLIB_SEARCH_URL, params)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {400, 404}:
                return []
            raise

        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict) and payload.get("trackName"):
            return [payload]
        return []

    def _get_exact_match(self, params: dict[str, str | int]) -> dict[str, Any] | None:
        try:
            payload = self._request_json(config.LRCLIB_GET_URL, params)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {400, 404}:
                return None
            raise

        if isinstance(payload, dict) and payload.get("trackName"):
            return payload
        return None

    def _request_json(self, url: str, params: dict[str, str | int]) -> Any:
        response = requests.get(
            url,
            headers=self.headers,
            params=params,
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return self._decode_json_response(response)

    def _merge_result(self, all_results: dict[str, dict[str, Any]], item: dict[str, Any]) -> None:
        normalized = self._normalize_result_item(item)
        item_key = str(normalized.get("id") or self._result_fingerprint(normalized))
        all_results[item_key] = normalized

    def _normalize_result_item(self, item: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(item)
        for field in ("trackName", "artistName", "albumName", "plainLyrics", "syncedLyrics"):
            value = normalized.get(field)
            if isinstance(value, str):
                normalized[field] = repair_text(value)
        return normalized

    def _result_fingerprint(self, item: dict[str, Any]) -> str:
        track_name = clean_song_title(str(item.get("trackName", "") or ""))
        artist_name = clean_song_title(str(item.get("artistName", "") or ""))
        album_name = clean_song_title(str(item.get("albumName", "") or ""))
        return f"{track_name}|{artist_name}|{album_name}"

    def _score_result(self, item: dict[str, Any], song: SongInfo) -> float:
        track_name = clean_song_title(str(item.get("trackName", "") or ""))
        artist_name = clean_song_title(str(item.get("artistName", "") or ""))
        album_name = clean_song_title(str(item.get("albumName", "") or ""))

        query_target = clean_song_title(song.query_text)
        album_target = clean_song_title(song.album)
        query_pairs = build_song_queries(song)

        score = 0.0
        score += 20 * self._similarity(f"{artist_name} {track_name}", query_target)
        score += 65 * self._best_track_similarity(track_name, query_pairs, query_target)
        score += 25 * self._best_artist_similarity(artist_name, query_pairs)

        if album_target and album_name:
            score += 10 * self._similarity(album_name, album_target)

        if item.get("syncedLyrics"):
            score += 18
        if item.get("plainLyrics"):
            score += 6
        if item.get("instrumental"):
            score -= 25

        return score

    def _best_track_similarity(
        self,
        track_name: str,
        query_pairs: list[tuple[str, str]],
        query_target: str,
    ) -> float:
        best = self._similarity(track_name, query_target)
        for track_target, _artist_target in query_pairs:
            best = max(best, self._similarity(track_name, track_target))
        return best

    def _best_artist_similarity(
        self,
        artist_name: str,
        query_pairs: list[tuple[str, str]],
    ) -> float:
        best = 0.0
        for _track_target, artist_target in query_pairs:
            if not artist_target:
                continue
            best = max(best, self._similarity(artist_name, artist_target))
        return best

    def _cache_key(self, song: SongInfo) -> str:
        return f"{config.LYRICS_CACHE_VERSION}:{song.cache_key()}"

    @staticmethod
    def _decode_json_response(response: requests.Response) -> Any:
        try:
            return json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return response.json()

    @staticmethod
    def _format_network_error(exc: requests.RequestException) -> str:
        if isinstance(exc, requests.Timeout):
            return "Request lirik timeout. Coba Refresh lagi."
        if isinstance(exc, requests.ConnectionError):
            return "Koneksi ke layanan lirik gagal. Coba cek internet lalu Refresh."

        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            status_code = exc.response.status_code
            if status_code >= 500:
                return "Layanan lirik sedang bermasalah. Coba lagi beberapa saat."
            if status_code == 429:
                return "Layanan lirik sedang rate limit. Coba lagi sebentar."

        return "Gagal mengambil lirik dari provider. Coba Refresh atau ganti lagu."

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        left_value = " ".join(left.lower().split())
        right_value = " ".join(right.lower().split())
        if not left_value or not right_value:
            return 0.0
        return SequenceMatcher(None, left_value, right_value).ratio()
