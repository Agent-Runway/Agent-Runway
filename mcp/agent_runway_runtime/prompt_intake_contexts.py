from __future__ import annotations

import re


def _release_notes_context(normalized: str) -> bool:
    return bool(re.search(r"\brelease(?:[- ]candidate)? notes?\b", normalized))


def _external_side_effect_reference_context(text: str, normalized: str) -> bool:
    if _inline_code_reference_context(text, normalized):
        return True
    reference_markers = (
        "explain",
        "summarize",
        "what does",
        "what is",
        "read the",
        "branch naming",
        "notifications",
        "notification",
        "checklist",
        "pre-release",
        "merge conflict",
        "git archive",
        "archive format",
        "database drop",
        "drop table",
        "archive format",
        "truncate mean",
        "truncate means",
        "安全策略",
        "是什么意思",
        "什么意思",
        "阅读",
        "解释",
    )
    if any(marker in normalized for marker in reference_markers):
        return True
    if re.search(r"\bforce[- ]push safety (?:rules?|polic(?:y|ies)|strateg(?:y|ies))\b", normalized):
        return True
    return bool(re.search(r"\brelease/[^\s]+\b", normalized))


def _has_inline_code_span(text: str) -> bool:
    return "`" in text


def _inline_code_reference_context(text: str, normalized: str) -> bool:
    if not _has_inline_code_span(text):
        return False
    return _external_side_effect_question(normalized) or _asks_about_continuation_word(normalized)


def _pushdown_context(normalized: str) -> bool:
    return bool(re.search(r"\bpush[- ]?down\b", normalized))


def _chinese_release_notes_context(normalized: str) -> bool:
    return "发布说明" in normalized


def _chinese_push_notification_context(normalized: str) -> bool:
    return "推送通知" in normalized


def _quoted_continuation_reference(text: str, normalized: str) -> bool:
    markers = ("user said", "user wrote", "the user said", "原话", "引用")
    return "continue" in normalized and '"continue"' in normalized and any(
        marker in normalized for marker in markers
    )


def _asks_about_continuation_word(normalized: str) -> bool:
    if "?" not in normalized and "？" not in normalized:
        return False
    explanation_markers = ("what does", "what is", "explain", "mean", "means", "什么意思", "解释")
    return any(marker in normalized for marker in explanation_markers)


def _asks_whether_to_continue_side_effect(normalized: str) -> bool:
    if "吗" not in normalized or "继续" not in normalized:
        return False
    return any(signal in normalized for signal in ("推送", "发布", "部署"))


def _external_side_effect_question(normalized: str) -> bool:
    question_markers = ("?", "？", "吗")
    if not any(marker in normalized for marker in question_markers):
        return False
    asking_markers = ("should i", "should we", "do you want me to", "我要")
    if any(marker in normalized for marker in asking_markers):
        return any(signal in normalized for signal in ("push", "deploy", "release", "推送", "发布", "部署"))
    return False


def _describes_programming_continue(normalized: str) -> bool:
    if "continue" not in normalized:
        return False
    programming_markers = (
        "python",
        "javascript",
        "keyword",
        "break",
        "loop",
        "loops",
        "control-flow",
        "control flow",
        "statement",
        "statements",
    )
    if any(marker in normalized for marker in programming_markers):
        return True
    explanation_markers = ("explain", "mean", "means")
    return any(marker in normalized for marker in explanation_markers) and (
        " keyword" in normalized or " statement" in normalized
    )
