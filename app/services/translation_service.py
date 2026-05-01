from __future__ import annotations

import hashlib
import json
import time

import requests

from app import config
from app.models import LyricLine, LyricsResult
from app.services.cache_service import LyricsCache
from app.utils.text_codec import repair_text


class LyricsTranslationService:
    def __init__(self, cache: LyricsCache) -> None:
        self.cache = cache
        self.headers = {
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json",
        }

    def translate_lyrics(
        self,
        lyrics: LyricsResult,
        *,
        target_language: str = "id",
    ) -> tuple[LyricsResult | None, str]:
        cache_key = self._cache_key(lyrics, target_language)
        cached = self.cache.get(cache_key)
        if cached:
            if cached.get("status") == "ok":
                return LyricsResult.from_dict(cached["data"]), "cache"
            return None, str(cached.get("reason", "Terjemahan tidak tersedia."))

        try:
            translated_lines = self._translate_lines(lyrics.lines, target_language)
        except requests.RequestException as exc:
            return None, f"Gagal menerjemahkan lirik: {exc}"
        except ValueError:
            return None, "Format hasil terjemahan tidak valid."

        if not translated_lines:
            self.cache.set(
                cache_key,
                {"status": "miss", "reason": "Terjemahan tidak tersedia."},
                ttl_seconds=config.MISS_TTL_SECONDS,
            )
            return None, "Terjemahan tidak tersedia."

        result = LyricsResult(
            track_name=lyrics.track_name,
            artist_name=lyrics.artist_name,
            album_name=lyrics.album_name,
            source=f"{lyrics.source}:{target_language}",
            synced=lyrics.synced,
            instrumental=lyrics.instrumental,
            plain_lyrics="\n".join(line.text for line in translated_lines),
            fetched_at=time.time(),
            lines=translated_lines,
        )

        self.cache.set(
            cache_key,
            {"status": "ok", "data": result.to_dict()},
            ttl_seconds=config.CACHE_TTL_SECONDS,
        )
        return result, "network"

    def _translate_lines(
        self,
        lines: list[LyricLine],
        target_language: str,
    ) -> list[LyricLine]:
        translated_lines: list[LyricLine | None] = [None] * len(lines)
        batch_indexes: list[int] = []
        batch_texts: list[str] = []

        def flush_batch() -> None:
            if not batch_texts:
                return

            translated = self._translate_batch(batch_texts, target_language)
            if len(translated) != len(batch_indexes):
                batch_indexes.clear()
                batch_texts.clear()
                raise ValueError("Jumlah hasil terjemahan tidak sesuai.")

            for translated_text, line_index in zip(translated, batch_indexes, strict=False):
                original = lines[line_index]
                translated_lines[line_index] = LyricLine(
                    text=translated_text,
                    start_time=original.start_time,
                    end_time=original.end_time,
                )

            batch_indexes.clear()
            batch_texts.clear()

        for index, line in enumerate(lines):
            if not self._should_translate(line.text):
                flush_batch()
                translated_lines[index] = LyricLine(
                    text=line.text,
                    start_time=line.start_time,
                    end_time=line.end_time,
                )
                continue

            batch_indexes.append(index)
            batch_texts.append(line.text)
            if len(batch_texts) >= 12:
                flush_batch()

        flush_batch()

        if any(line is None for line in translated_lines):
            return []

        return [line for line in translated_lines if line is not None]

    def _translate_batch(self, texts: list[str], target_language: str) -> list[str]:
        separator = "\n__LRC_BREAK_9F6C__\n"
        translated = self._translate_text(separator.join(texts), target_language)
        parts = [repair_text(part.strip()) for part in translated.split(separator)]
        if len(parts) == len(texts):
            return parts

        return [self._translate_text(text, target_language).strip() for text in texts]

    def _translate_text(self, text: str, target_language: str) -> str:
        response = requests.get(
            config.GOOGLE_TRANSLATE_URL,
            headers=self.headers,
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": target_language,
                "dt": "t",
                "q": text,
            },
            timeout=config.TRANSLATE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        payload = json.loads(response.content.decode("utf-8"))
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
            return text

        translated_parts: list[str] = []
        for part in payload[0]:
            if isinstance(part, list) and part:
                translated_parts.append(str(part[0] or ""))
        return repair_text("".join(translated_parts)) or text

    def _cache_key(self, lyrics: LyricsResult, target_language: str) -> str:
        base = "\n".join(
            f"{line.start_time}:{line.end_time}:{line.text}"
            for line in lyrics.lines
        )
        digest = hashlib.sha1(
            f"{lyrics.artist_name}|{lyrics.track_name}|{target_language}|{base}".encode("utf-8")
        ).hexdigest()
        return f"translate:{target_language}:{digest}"

    @staticmethod
    def _should_translate(text: str) -> bool:
        value = text.strip()
        if not value:
            return False
        if value.startswith("[") and value.endswith("]"):
            return False
        return True
