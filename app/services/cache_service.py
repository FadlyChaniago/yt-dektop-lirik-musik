from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class LyricsCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._loaded = False
        self._cache: dict[str, dict[str, Any]] = {}

    def _load(self) -> None:
        if self._loaded:
            return

        if self.path.exists():
            try:
                self._cache = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._cache = {}

        self._loaded = True

    def _flush(self) -> None:
        payload = json.dumps(self._cache, ensure_ascii=False, indent=2)
        self.path.write_text(payload, encoding="utf-8")

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            self._load()
            entry = self._cache.get(key)
            if not entry:
                return None

            expires_at = float(entry.get("expires_at", 0.0))
            if expires_at and expires_at < time.time():
                self._cache.pop(key, None)
                try:
                    self._flush()
                except OSError:
                    pass
                return None

            return entry.get("payload")

    def set(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        with self._lock:
            self._load()
            self._cache[key] = {
                "expires_at": time.time() + ttl_seconds,
                "payload": payload,
            }
            try:
                self._flush()
            except OSError:
                pass

    def delete(self, key: str) -> None:
        with self._lock:
            self._load()
            if key not in self._cache:
                return

            self._cache.pop(key, None)
            try:
                self._flush()
            except OSError:
                pass
