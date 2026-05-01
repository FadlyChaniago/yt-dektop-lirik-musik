from __future__ import annotations

import asyncio
import time
from typing import Any

from app.models import SongInfo


def _seconds_from_duration(value: Any) -> float:
    if value is None:
        return 0.0

    if hasattr(value, "total_seconds"):
        try:
            return float(value.total_seconds())
        except Exception:
            return 0.0

    if hasattr(value, "duration"):
        try:
            return float(value.duration) / 10_000_000
        except Exception:
            return 0.0

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _read_enum_name(value: Any) -> str:
    if value is None:
        return ""
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)


class MediaSessionReader:
    def __init__(self) -> None:
        self.available = False
        self._manager_cls = None

        try:
            from winsdk.windows.media.control import (  # type: ignore
                GlobalSystemMediaTransportControlsSessionManager,
            )

            self._manager_cls = GlobalSystemMediaTransportControlsSessionManager
            self.available = True
        except Exception:
            self.available = False

    async def _get_song_async(self) -> SongInfo | None:
        if not self.available or self._manager_cls is None:
            return None

        manager = await self._manager_cls.request_async()
        sessions = list(manager.get_sessions())
        browser_sessions: list[SongInfo] = []

        for session in sessions:
            try:
                source_app = str(session.source_app_user_model_id).lower()
            except Exception:
                source_app = ""

            if "chrome" not in source_app and "edge" not in source_app:
                continue

            try:
                media = await session.try_get_media_properties_async()
                timeline = session.get_timeline_properties()
                playback = session.get_playback_info()
            except Exception:
                continue

            title = str(getattr(media, "title", "") or "").strip()
            artist = str(getattr(media, "artist", "") or "").strip()
            album = str(getattr(media, "album_title", "") or "").strip()

            if not title:
                continue

            position_seconds = _seconds_from_duration(getattr(timeline, "position", None))
            duration_seconds = _seconds_from_duration(getattr(timeline, "end_time", None))
            status_text = _read_enum_name(getattr(playback, "playback_status", None)).lower()
            is_playing = "playing" in status_text or not status_text

            browser_sessions.append(
                SongInfo(
                    track=title,
                    artist=artist,
                    album=album,
                    raw_title=f"{artist} - {title}".strip(" -"),
                    source_app=source_app,
                    detection_method="media_session",
                    position_seconds=max(position_seconds, 0.0),
                    duration_seconds=duration_seconds or None,
                    is_playing=is_playing,
                    detected_at=time.time(),
                    confidence=1.0,
                )
            )

        if not browser_sessions:
            return None

        browser_sessions.sort(
            key=lambda song: (
                song.is_playing,
                "youtube" in song.display_title.lower(),
                bool(song.artist),
                song.confidence,
            ),
            reverse=True,
        )
        return browser_sessions[0]

    def get_current_song(self) -> SongInfo | None:
        if not self.available:
            return None

        try:
            return asyncio.run(self._get_song_async())
        except Exception:
            return None

