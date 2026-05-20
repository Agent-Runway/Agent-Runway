from __future__ import annotations

import re
from typing import Any

from agent_runway_runtime.prompt_intake_signals import normalize_text

MIN_KEYWORD_LENGTH = 3
MIN_MULTI_KEYWORD_OVERLAP = 2
MIN_CJK_SUBSTRING_LENGTH = 4
MIN_CJK_NGRAM_LENGTH = 4
MISSION_MATCH_STOP_WORDS = frozenset(
    "a an and bug complete continue fix finish go list mission ok okay on please run task test tests to todo verify with".split()
)


def same_mission_request(text: str, mission: dict[str, Any]) -> bool:
    request = keywords(text)
    criteria = mission.get("completion_criteria", [])
    criteria_text = " ".join(str(item) for item in criteria) if isinstance(criteria, list) else str(criteria)
    context = " ".join(str(mission.get(key, "")) for key in ("task_id", "goal")) + " " + criteria_text
    context_keywords = keywords(context)
    overlap = request & context_keywords
    if has_strong_cjk_overlap(request, context_keywords):
        return True
    return bool(overlap) if len(request) < MIN_MULTI_KEYWORD_OVERLAP else len(overlap) >= MIN_MULTI_KEYWORD_OVERLAP


def keywords(text: str) -> set[str]:
    return {
        token for token in re.split(r"[^0-9a-z\u4e00-\u9fff]+", normalize_text(text))
        if len(token) >= MIN_KEYWORD_LENGTH and token not in MISSION_MATCH_STOP_WORDS
    }


def has_strong_cjk_overlap(request: set[str], context: set[str]) -> bool:
    if any(_has_cjk_substring_overlap(left, right) for left in request for right in context):
        return True
    return bool(_cjk_ngrams(request) & _cjk_ngrams(context))


def _has_cjk_substring_overlap(left: str, right: str) -> bool:
    if not (_has_cjk(left) and _has_cjk(right)):
        return False
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= MIN_CJK_SUBSTRING_LENGTH and shorter in longer


def _has_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _cjk_ngrams(values: set[str]) -> set[str]:
    grams: set[str] = set()
    for value in values:
        cjk_chars = "".join(char for char in value if "\u4e00" <= char <= "\u9fff")
        grams.update(
            cjk_chars[index:index + MIN_CJK_NGRAM_LENGTH]
            for index in range(0, len(cjk_chars) - MIN_CJK_NGRAM_LENGTH + 1)
        )
    return grams
