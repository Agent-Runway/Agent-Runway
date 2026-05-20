from __future__ import annotations

import unicodedata
from typing import Any


COMBINING_GRAPHEME_JOINER = "\u034f"


def strip_invisible_controls(text: str) -> str:
    return "".join(_visible_char(char) for char in text)


def strip_invisible_controls_deep(value: Any) -> Any:
    if isinstance(value, str):
        return strip_invisible_controls(value)
    if isinstance(value, list):
        return [strip_invisible_controls_deep(item) for item in value]
    if isinstance(value, dict):
        return {
            key: strip_invisible_controls_deep(item)
            for key, item in value.items()
        }
    return value


def _visible_char(char: str) -> str:
    if char in {" ", "\t", "\n", "\r"}:
        return char
    if char == COMBINING_GRAPHEME_JOINER or _is_variation_selector(char):
        return ""
    if unicodedata.category(char)[0] in {"C", "M"}:
        return ""
    return char


def _is_variation_selector(char: str) -> bool:
    codepoint = ord(char)
    return 0xFE00 <= codepoint <= 0xFE0F or 0xE0100 <= codepoint <= 0xE01EF
