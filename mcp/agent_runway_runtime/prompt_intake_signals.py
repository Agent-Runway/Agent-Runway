from __future__ import annotations

import re
import unicodedata

from agent_runway_runtime.prompt_intake_registry import (
    AUTHORIZATION_DENIAL_SIGNALS,
    AUTHORIZATION_REPLIES,
    CONTINUATION_PHRASES,
    EXTERNAL_SIDE_EFFECT_SIGNALS,
    HIGH_AUTONOMY_SIGNALS,
)
from agent_runway_runtime.detection_text import strip_invisible_controls
from agent_runway_runtime.prompt_intake_contexts import (
    _asks_about_continuation_word,
    _asks_whether_to_continue_side_effect,
    _chinese_push_notification_context,
    _chinese_release_notes_context,
    _describes_programming_continue,
    _external_side_effect_question,
    _external_side_effect_reference_context,
    _inline_code_reference_context,
    _pushdown_context,
    _quoted_continuation_reference,
    _release_notes_context,
)

LATIN_SIGNAL_PATTERNS = {
    "archive": r"archive",
    "complete": r"complete",
    "commit": r"commit",
    "delete": r"delete",
    "deploy": r"deploy",
    "drop": r"drop",
    "fix": r"fix",
    "force push": r"force\s+push",
    "merge": r"merge",
    "push": r"push",
    "publish": r"publish",
    "rebase": r"rebase",
    "release": r"release",
    "remove": r"remove",
    "tag": r"tag",
    "test": r"tests?",
    "truncate": r"truncate",
    "verify": r"verify|verified|verification",
}

POLITE_PREFIXES = (
    "ok",
    "okay",
    "please",
    "pls",
    "can you",
    "could you",
    "bitte",
    "por favor",
    "s'il vous plait",
    "请",
    "请你",
)
POLITE_SUFFIXES = POLITE_PREFIXES + ("thanks", "thank you", "谢谢", "ください", "해줘")


def text_signal(text: str) -> dict[str, object]:
    normalized = normalize_text(text)
    language = continuation_language(normalized)
    evidence: list[str] = []
    if language:
        evidence.append("short_continuation_phrase")
    todo_list = has_todo_task_list(text)
    if todo_list:
        evidence.append("todo_task_list")
    if explicit_skill(text):
        evidence.append("explicit_skill_invocation")
    if authorization_reply(normalized):
        evidence.append("authorization_reply_signal")
    if authorization_denial(normalized):
        evidence.append("authorization_denial_signal")
    return {
        "continuation_language": language,
        "authorization_reply": authorization_reply(normalized),
        "authorization_denial": authorization_denial(normalized),
        "explicit_skill": explicit_skill(text),
        "todo_task_list": todo_list,
        "evidence_sources": evidence,
    }


def normalize_text(text: str) -> str:
    stripped = unicodedata.normalize("NFKC", strip_invisible_controls(text)).strip()
    stripped = re.sub(r"^[\s\.,!！。;；:：'\"“”‘’()（）\[\]{}]+", "", stripped)
    stripped = re.sub(r"[\s\.,!！。;；:：'\"“”‘’()（）\[\]{}]+$", "", stripped)
    stripped = re.sub(r"\s+", " ", stripped).casefold()
    return fold_accents(stripped)


def fold_accents(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )


def continuation_language(normalized: str) -> str:
    candidates = _directive_variants(normalized)
    for language, phrases in CONTINUATION_PHRASES.items():
        normalized_phrases = {normalize_text(phrase) for phrase in phrases}
        if candidates & normalized_phrases:
            return language
        if _starts_with_phrase(candidates, normalized_phrases):
            return language
    if _natural_english_continuation(normalized):
        return "en"
    return ""


def authorization_reply(normalized: str) -> bool:
    candidates = _directive_variants(normalized)
    phrases = {normalize_text(phrase) for phrase in AUTHORIZATION_REPLIES}
    if candidates & phrases:
        return True
    return _starts_with_phrase(candidates, phrases)


def authorization_denial(normalized: str) -> bool:
    return any(_has_denial_signal(normalized, phrase) for phrase in _normalized_denial_signals())


def explicit_skill(text: str) -> bool:
    normalized = normalize_text(text)
    if re.search(r"(?<!\w)/agent(?![\w-])", normalized):
        return True
    return bool(re.search(r"\bagent[\s\-_\u2010-\u2015]*runway\b", normalized))


def has_todo_task_list(text: str) -> bool:
    if not re.search(r"(?im)^\s*#*\s*todos?\b", text):
        return False
    task_marker = r"(?:[-*+]\s+|\d+[.)]\s+)?\[(?:\s|x|X|\u2022|\-)\]"
    return bool(re.search(rf"(?m)^\s*{task_marker}", text))


def is_high_autonomy(text: str) -> bool:
    normalized = normalize_text(text)
    hits = {signal for signal in HIGH_AUTONOMY_SIGNALS if _has_action_signal(normalized, signal)}
    return len(hits) >= 2


def has_external_side_effect(text: str) -> bool:
    normalized = normalize_text(text)
    signals = {s for s in EXTERNAL_SIDE_EFFECT_SIGNALS if _has_action_signal(normalized, s)}
    if _external_side_effect_reference_context(text, normalized):
        return False
    if signals == {"release"} and _release_notes_context(normalized):
        return False
    if signals == {"push"} and _pushdown_context(normalized):
        return False
    if signals & {"发布"} and _chinese_release_notes_context(normalized):
        signals.discard("发布")
    if signals & {"推送"} and _chinese_push_notification_context(normalized):
        signals.discard("推送")
    return bool(signals)


def is_false_positive_context(text: str, signal: dict[str, object]) -> bool:
    normalized = normalize_text(text)
    if "```" in text:
        return True
    if _inline_code_reference_context(text, normalized):
        return True
    if _external_side_effect_question(normalized):
        return True
    if _quoted_continuation_reference(text, normalized):
        return True
    if _asks_whether_to_continue_side_effect(normalized):
        return True
    if _describes_programming_continue(normalized):
        return True
    if _asks_about_continuation_word(normalized):
        return True
    return False


def _directive_variants(normalized: str) -> set[str]:
    punct_as_space = re.sub(r"[\.,!！。;；:：，?？]+", " ", normalized)
    variants = {re.sub(r"\s+", " ", punct_as_space).strip()}
    changed = True
    while changed:
        changed = False
        for value in tuple(variants):
            for marker in POLITE_PREFIXES:
                changed |= _add_without_prefix(variants, value, marker)
            for marker in POLITE_SUFFIXES:
                changed |= _add_without_suffix(variants, value, marker)
    return {value for value in variants if value}


def _starts_with_phrase(candidates: set[str], phrases: set[str]) -> bool:
    return any(_candidate_starts_with_phrase(candidate, phrase) for candidate in candidates for phrase in phrases)


def _candidate_starts_with_phrase(candidate: str, phrase: str) -> bool:
    if not candidate.startswith(phrase) or candidate == phrase:
        return False
    rest = candidate[len(phrase):]
    return rest.startswith(" ") or _is_non_latin_phrase(phrase)


def _is_non_latin_phrase(phrase: str) -> bool:
    return any(ord(char) > 127 for char in phrase)


def _add_without_prefix(values: set[str], value: str, marker: str) -> bool:
    if value == marker or not value.startswith(marker):
        return False
    candidate = value[len(marker):].strip()
    if candidate in values:
        return False
    values.add(candidate)
    return True


def _add_without_suffix(values: set[str], value: str, marker: str) -> bool:
    if value == marker or not value.endswith(marker):
        return False
    candidate = value[: -len(marker)].strip()
    if candidate in values:
        return False
    values.add(candidate)
    return True


def _has_action_signal(normalized: str, signal: str) -> bool:
    if signal in LATIN_SIGNAL_PATTERNS:
        pattern = LATIN_SIGNAL_PATTERNS[signal]
        return bool(re.search(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])", normalized))
    for match in re.finditer(re.escape(signal), normalized):
        if not _cjk_action_context_blocked(normalized, match.start()):
            return True
    return False


def _natural_english_continuation(normalized: str) -> bool:
    return bool(
        re.search(
            r"\b(?:i\s+want\s+you\s+to|let'?s|why\s+don'?t\s+we|maybe)\s+"
            r"(?:continue|go\s+on|carry\s+on|proceed|keep\s+going)\b",
            normalized,
        )
    )


def _cjk_action_context_blocked(normalized: str, start: int) -> bool:
    prefix = normalized[max(0, start - 8) : start]
    if any(marker in prefix for marker in ("无需", "不需要", "不用", "不要", "别")):
        return True
    return prefix.endswith(("已", "已经"))


def _normalized_denial_signals() -> set[str]:
    return {normalize_text(phrase) for phrase in AUTHORIZATION_DENIAL_SIGNALS}


def _has_denial_signal(normalized: str, phrase: str) -> bool:
    if _is_latin_denial_phrase(phrase):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", normalized))
    return phrase in normalized


def _is_latin_denial_phrase(phrase: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9 '\-]*", phrase))
