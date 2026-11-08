"""Small text helpers shared by risk rules and the offline rubric."""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_LATIN = re.compile(r"[A-Za-z0-9+]{2,}")


def char_count(text: str) -> int:
    """Count characters after removing whitespace.

    Channel budgets use this count so line breaks do not eat the limit.
    """

    return len(_WS.sub("", text))


def norm(text: str) -> str:
    return _WS.sub("", text).casefold()


def contains_phrase(text: str, phrase: str) -> bool:
    if not phrase or not phrase.strip():
        return False
    return norm(phrase) in norm(text)


def cjk_bigrams(text: str) -> list[str]:
    chars = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    return [a + b for a, b in zip(chars, chars[1:])]


def latin_tokens(text: str) -> list[str]:
    return [token.casefold() for token in _LATIN.findall(text)]


def find_phrases(
    text: str,
    phrases: list[str],
    exceptions: dict[str, list[str]] | None = None,
) -> list[str]:
    """Return phrases that occur in text, longest first, without double-counting spans.

    ``exceptions`` maps a phrase to longer surface forms that should not count.
    For example, 第一 inside 第一位 is an ingredient order, not a superlative.
    """

    exceptions = exceptions or {}
    occupied = [False] * len(text)
    hits: list[str] = []
    ordered = sorted({phrase for phrase in phrases if phrase}, key=len, reverse=True)
    for phrase in ordered:
        start = 0
        while True:
            index = text.find(phrase, start)
            if index < 0:
                break
            end = index + len(phrase)
            if any(occupied[index:end]):
                start = index + 1
                continue
            if _inside_any(text, index, end, exceptions.get(phrase, [])):
                start = index + 1
                continue
            hits.append(phrase)
            for cursor in range(index, end):
                occupied[cursor] = True
            start = end
    return hits


def _inside_any(text: str, start: int, end: int, forms: list[str]) -> bool:
    for form in forms:
        if not form:
            continue
        window_start = max(0, start - len(form) + 1)
        window_end = min(len(text), end + len(form) - 1)
        window = text[window_start:window_end]
        offset = 0
        while True:
            found = window.find(form, offset)
            if found < 0:
                break
            abs_start = window_start + found
            abs_end = abs_start + len(form)
            if abs_start <= start and end <= abs_end:
                return True
            offset = found + 1
    return False
