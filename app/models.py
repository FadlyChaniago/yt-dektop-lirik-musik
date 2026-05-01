from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


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
            text=payload.get("text", ""),
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
    instrumental: bool = False
    plain_lyrics: str = ""
    fetched_at: float = 0.0
    lines: list[LyricLine] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        if self.artist_name and self.track_name:
            return f"{self.artist_name} - {self.track_name}"
        return self.track_name or "Lirik"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["lines"] = [line.to_dict() for line in self.lines]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LyricsResult":
        lines = [LyricLine.from_dict(item) for item in payload.get("lines", [])]
        return cls(
            track_name=payload.get("track_name", ""),
            artist_name=payload.get("artist_name", ""),
            album_name=payload.get("album_name", ""),
            source=payload.get("source", "cache"),
            synced=bool(payload.get("synced", False)),
            instrumental=bool(payload.get("instrumental", False)),
            plain_lyrics=payload.get("plain_lyrics", ""),
            fetched_at=float(payload.get("fetched_at", 0.0)),
            lines=lines,
        )

