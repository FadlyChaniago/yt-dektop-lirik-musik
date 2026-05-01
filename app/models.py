from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

from app.utils.text_codec import repair_text


def _compact(value: str) -> str:
    return " ".join(value.lower().strip().split())


@dataclass(slots=True)
class SongInfo:
    track: str
    artist: str = ""
    album: str = ""
    raw_title: str = ""
    source_app: str = ""
    detection_method: str = "unknown"
    position_seconds: float = 0.0
    duration_seconds: float | None = None
    is_playing: bool = True
    detected_at: float = 0.0
    confidence: float = 0.0

    @property
    def display_title(self) -> str:
        if self.artist and self.track:
            return f"{self.artist} - {self.track}"
        return self.track or self.raw_title or "Tidak ada lagu aktif"

    @property
    def query_text(self) -> str:
        return self.raw_title or self.display_title

    def cache_key(self) -> str:
        base = _compact(" | ".join([self.artist, self.track, self.raw_title]))
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()
        return digest


@dataclass(slots=True)
class LyricLine:
    text: str
    start_time: float | None = None
    end_time: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LyricLine":
        return cls(
            text=repair_text(str(payload.get("text", "") or "")),
            start_time=payload.get("start_time"),
            end_time=payload.get("end_time"),
        )


@dataclass(slots=True)
class LyricsResult:
    track_name: str
    artist_name: str
    album_name: str = ""
    source: str = "network"
    synced: bool = False
    timing_mode: str = "plain"
    instrumental: bool = False
    plain_lyrics: str = ""
    fetched_at: float = 0.0
    lines: list[LyricLine] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        if self.artist_name and self.track_name:
            return f"{self.artist_name} - {self.track_name}"
        return self.track_name or "Lirik"

    @property
    def has_timing(self) -> bool:
        return any(line.start_time is not None for line in self.lines)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["lines"] = [line.to_dict() for line in self.lines]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LyricsResult":
        lines = [LyricLine.from_dict(item) for item in payload.get("lines", [])]
        return cls(
            track_name=repair_text(str(payload.get("track_name", "") or "")),
            artist_name=repair_text(str(payload.get("artist_name", "") or "")),
            album_name=repair_text(str(payload.get("album_name", "") or "")),
            source=str(payload.get("source", "cache") or "cache"),
            synced=bool(payload.get("synced", False)),
            timing_mode=str(payload.get("timing_mode", "plain") or "plain"),
            instrumental=bool(payload.get("instrumental", False)),
            plain_lyrics=repair_text(str(payload.get("plain_lyrics", "") or "")),
            fetched_at=float(payload.get("fetched_at", 0.0)),
            lines=lines,
        )
