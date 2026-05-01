from __future__ import annotations

import threading
from collections.abc import Callable

from app import config
from app.models import SongInfo
from app.services.media_session import MediaSessionReader
from app.services.song_normalizer import (
    guess_browser_from_title,
    song_from_window_title,
    titles_match_browser_rules,
)


class BrowserWatcher(threading.Thread):
    def __init__(self, event_sink: Callable[[dict], None]) -> None:
        super().__init__(daemon=True)
        self.event_sink = event_sink
        self.stop_event = threading.Event()
        self.media_reader = MediaSessionReader()

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        while not self.stop_event.is_set():
            song = self._detect_current_song()
            self.event_sink({"type": "song_state", "song": song})
            self.stop_event.wait(config.POLL_INTERVAL_SECONDS)

    def _detect_current_song(self) -> SongInfo | None:
        media_song = self.media_reader.get_current_song()
        if media_song:
            return media_song
        return self._read_youtube_window_title()

    def _read_youtube_window_title(self) -> SongInfo | None:
        try:
            import pygetwindow as gw
        except Exception:
            return None

        try:
            titles = list(gw.getAllTitles())
        except Exception:
            return None

        matched = titles_match_browser_rules(titles)
        if not matched:
            return None

        matched.sort(
            key=lambda title: (
                "youtube music" in title.lower(),
                "google chrome" in title.lower() or "microsoft edge" in title.lower(),
                len(title),
            ),
            reverse=True,
        )

        selected = matched[0]
        source_app = guess_browser_from_title(selected)
        return song_from_window_title(selected, source_app)

