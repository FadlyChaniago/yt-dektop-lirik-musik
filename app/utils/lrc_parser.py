from __future__ import annotations

import re

from app.models import LyricLine


TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2}(?:\.\d{1,3})?)\]")


def parse_lrc(lrc_text: str, fallback_duration: float | None = None) -> list[LyricLine]:
    lines: list[LyricLine] = []

    for raw_line in lrc_text.splitlines():
        timestamps = list(TIMESTAMP_RE.finditer(raw_line))
        if not timestamps:
            continue

        text = TIMESTAMP_RE.sub("", raw_line).strip()
        for match in timestamps:
            minutes = int(match.group(1))
            seconds = float(match.group(2))
            lines.append(
                LyricLine(
                    text=text or "[music]",
                    start_time=(minutes * 60) + seconds,
                    end_time=None,
                )
            )

    lines.sort(key=lambda line: line.start_time or 0.0)

    for index, line in enumerate(lines):
        next_line = lines[index + 1] if index + 1 < len(lines) else None
        if next_line and next_line.start_time is not None:
            line.end_time = next_line.start_time
        elif fallback_duration and fallback_duration > (line.start_time or 0.0):
            line.end_time = fallback_duration
        elif line.start_time is not None:
            line.end_time = line.start_time + 4.5

    return lines


def plain_text_to_lines(text: str) -> list[LyricLine]:
    return [LyricLine(text=line.strip()) for line in text.splitlines() if line.strip()]
