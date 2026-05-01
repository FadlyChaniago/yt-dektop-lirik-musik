from __future__ import annotations


MOJIBAKE_HINTS = ("Ã", "â", "ð", "ã", "æ", "å", "�")


def repair_text(value: str) -> str:
    if not value:
        return value

    original = value
    for encoding in ("latin-1", "cp1252"):
        try:
            repaired = original.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue

        if repaired != original and _looks_healthier(original, repaired):
            return repaired

    return original


def _looks_healthier(original: str, repaired: str) -> bool:
    return _mojibake_score(repaired) < _mojibake_score(original)


def _mojibake_score(value: str) -> int:
    score = 0
    for hint in MOJIBAKE_HINTS:
        score += value.count(hint) * 2

    score += sum(1 for char in value if 0x80 <= ord(char) <= 0x9F)
    return score
