from __future__ import annotations

from typing import Any

from agent_runway_runtime.prompt_intake_mission_match import same_mission_request
from agent_runway_runtime.prompt_intake_registry import (
    CONTINUATION_PHRASES,
    LANGUAGE_MONITORING_DOMAINS,
)
from agent_runway_runtime.prompt_intake_signals import (
    has_external_side_effect,
    is_false_positive_context,
    is_high_autonomy,
    text_signal,
)


def classify_prompt_intake(
    user_message: str,
    current_session_id: str,
    active_mission: dict[str, Any] | None,
    bound_mission: dict[str, Any] | None,
    workspace_missions: list[dict[str, Any]],
    previous_assistant_state: dict[str, Any] | None = None,
    workspace_state: dict[str, Any] | None = None,
    memory_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = str(user_message or "")
    previous = previous_assistant_state or {}
    workspace = workspace_state or {}
    base = _base_payload()
    signal = text_signal(text)
    base["is_continuation"] = bool(signal["continuation_language"])
    base["evidence_sources"] = list(signal["evidence_sources"])

    if _asked_authorization(previous) and _looks_like_question(text):
        return _authorization_not_granted(base)
    if _asked_authorization(previous) and signal["authorization_denial"]:
        return _authorization_not_granted(base)
    if _asked_authorization(previous) and _is_reference_context(text):
        return _authorization_not_granted(base)
    if _asked_authorization(previous) and _is_reply_signal(signal):
        return _scoped_authorization(base, previous)
    if is_false_positive_context(text, signal):
        return _false_positive_ordinary(base, text)
    if _is_reference_context(text) and (is_high_autonomy(text) or has_external_side_effect(text)):
        return _false_positive_ordinary(base, text)
    if signal["todo_task_list"] and (active_mission or bound_mission or workspace_missions):
        base["normalized_request"] = text.strip()
        return _continuation(
            base, active_mission, bound_mission, workspace_missions, current_session_id, workspace,
            memory_hint, text, False,
        )
    if signal["continuation_language"] and (active_mission or bound_mission or workspace_missions):
        base["normalized_request"] = text.strip()
        return _continuation(
            base, active_mission, bound_mission, workspace_missions, current_session_id, workspace,
            memory_hint, text, is_high_autonomy(text) or has_external_side_effect(text),
        )
    if signal["todo_task_list"]:
        return _new_mission(base, text, "todo_task_list", 0.9)
    if signal["explicit_skill"]:
        return _new_mission(base, text, "explicit_skill_invocation", 1.0)
    if is_high_autonomy(text):
        payload = _new_mission(base, text, "high_autonomy_request", 0.88)
        if has_external_side_effect(text):
            _add_source(payload, "external_side_effect_request")
        return payload
    if has_external_side_effect(text):
        return _new_mission(base, text, "external_side_effect_request", 0.86)
    if signal["authorization_reply"] and not signal["continuation_language"]:
        return _ambiguous_confirmation(base)
    if signal["continuation_language"]:
        base["normalized_request"] = text.strip()
        return _continuation(
            base, active_mission, bound_mission, workspace_missions, current_session_id, workspace, memory_hint
        )
    return _ordinary(base, text)


def _base_payload() -> dict[str, Any]:
    return {
        "classification": "ordinary_prompt",
        "should_activate_agent_runway": False,
        "is_continuation": False,
        "confidence": 0.2,
        "normalized_request": "",
        "required_first_actions": [],
        "authority_boundary": _authority_boundary(False),
        "evidence_sources": [],
        "capability_caveat": _capability_caveat(),
        "language_monitoring": {
            "domains": LANGUAGE_MONITORING_DOMAINS,
            "strategy": "registry_plus_state",
            "mega_regex": False,
        },
        "continuation_registry": CONTINUATION_PHRASES,
    }


def _asked_authorization(previous: dict[str, Any]) -> bool:
    return bool(previous.get("asked_user_authorization"))


def _is_reply_signal(signal: dict[str, Any]) -> bool:
    return bool(signal["continuation_language"] or signal["authorization_reply"])


def _new_mission(base: dict[str, Any], text: str, source: str, confidence: float) -> dict[str, Any]:
    base.update({
        "classification": "new_agent_runway_mission",
        "should_activate_agent_runway": True,
        "confidence": confidence,
        "normalized_request": f"Use Agent-Runway for bounded execution: {text.strip()}",
        "required_first_actions": [
            "load agent-runway skill", "infer concrete criteria", "lock mission",
            "record TODO items in mission-backed tracking", "inspect repo state",
            "execute one bounded reversible slice",
        ],
        "mission_draft": _mission_draft(text),
    })
    _add_source(base, source)
    return base


def _mission_draft(text: str) -> dict[str, Any]:
    return {
        "goal": text.strip(),
        "criteria": [
            "infer scope from repository state and user request",
            "execute one verified slice at a time",
            "run relevant checks before claiming completion",
            "do not perform external side effects without fresh authorization",
        ],
        "first_slice": "inspect mission context, repository state, and verification surface",
    }


def _continuation(
    base: dict[str, Any], active: dict[str, Any] | None, bound: dict[str, Any] | None,
    workspace: list[dict[str, Any]],
    current_session_id: str, workspace_state: dict[str, Any], memory_hint: dict[str, Any] | None,
    text: str = "", require_same: bool = False,
) -> dict[str, Any]:
    if active:
        return _continue_or_new(base, active, "active_session_mission", current_session_id, text, require_same)
    if bound:
        return _continue_or_new(base, bound, "host_session_binding", current_session_id, text, require_same)
    if len(workspace) == 1:
        return _continue_or_new(base, workspace[0], "workspace_active_mission", current_session_id, text, require_same)
    if len(workspace) > 1:
        return _ambiguous_workspace(base, workspace)
    if _has_workspace_frontier(workspace_state):
        return _recover_context(base, workspace_state)
    return _ambiguous_continuation(base, bool(memory_hint))


def _continue_or_new(
    base: dict[str, Any], mission: dict[str, Any], source: str,
    current_session_id: str, text: str, require_same: bool,
) -> dict[str, Any]:
    if require_same and not same_mission_request(text, mission):
        payload = _new_mission(base, text, "mission_mismatch_new_request", 0.84)
        _add_source(payload, "mission_mismatch")
        return payload
    payload = _continue_with_mission(base, mission, source, current_session_id)
    if require_same:
        _add_source(payload, "same_mission_recovery")
    return payload


def _continue_with_mission(
    base: dict[str, Any], mission: dict[str, Any], source: str, current_session_id: str
) -> dict[str, Any]:
    mission_payload = dict(mission)
    mission_payload["source"] = source
    mission_payload["needs_session_rebind"] = mission["session_id"] != current_session_id
    base.update({
        "classification": "continue_current_mission",
        "should_activate_agent_runway": True,
        "confidence": 0.97 if source == "active_session_mission" else 0.93,
        "normalized_request": "Continue the active Agent-Runway mission from the last verified frontier.",
        "required_first_actions": [
            "load agent-runway skill", "read mission_status", "export or read handoff packet",
            "record TODO items in mission-backed tracking", "inspect git status",
            "identify the next reversible verified slice",
        ],
        "mission": mission_payload,
    })
    _add_source(base, source)
    return base


def _ambiguous_workspace(base: dict[str, Any], missions: list[dict[str, Any]]) -> dict[str, Any]:
    base.update({
        "classification": "ambiguous_workspace_mission",
        "confidence": 0.62,
        "candidate_missions": missions,
        "required_user_question": "Multiple active Agent-Runway missions exist; choose which mission to continue.",
    })
    _add_source(base, "multiple_workspace_missions")
    return base


def _recover_context(base: dict[str, Any], workspace: dict[str, Any]) -> dict[str, Any]:
    base.update({
        "classification": "recover_context_before_continuing",
        "should_activate_agent_runway": True,
        "confidence": 0.78,
        "normalized_request": "Recover project context before continuing; no mission is inferred.",
        "required_first_actions": [
            "load agent-runway skill", "inspect git status", "inspect recent receipts",
            "record TODO items in mission-backed tracking", "read available handoff packet",
            "ask one clarification if no action frontier is found",
        ],
    })
    for key in ("dirty_worktree", "previous_assistant_next_step", "todo_items"):
        if workspace.get(key):
            _add_source(base, key)
    return base


def _ambiguous_continuation(base: dict[str, Any], has_memory_hint: bool) -> dict[str, Any]:
    base.update({
        "classification": "ambiguous_continuation",
        "confidence": 0.42,
        "required_user_question": "No active Agent-Runway mission is recoverable. What should I continue?",
    })
    _add_source(base, "no_recoverable_context")
    if has_memory_hint:
        _add_source(base, "memory_not_evidence")
    return base


def _ambiguous_confirmation(base: dict[str, Any]) -> dict[str, Any]:
    base.update({
        "classification": "ambiguous_confirmation",
        "confidence": 0.46,
        "required_user_question": "This looks like a confirmation, but no scoped authorization question is active.",
    })
    return base


def _scoped_authorization(base: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    base.update({
        "classification": "scoped_authorization_reply",
        "should_activate_agent_runway": True,
        "confidence": 0.94,
        "required_first_actions": ["load agent-runway skill", "record_user_authorization", "verify authorization_status"],
        "authority_boundary": _authority_boundary(True, previous),
    })
    _add_source(base, "previous_authority_question")
    return base


def _authorization_not_granted(base: dict[str, Any]) -> dict[str, Any]:
    base.update({
        "classification": "authorization_not_granted",
        "confidence": 0.88,
        "required_user_question": "Authorization was limited or denied; continue only with reversible local work unless a fresh approval is granted.",
        "authority_boundary": _authority_boundary(False),
    })
    _add_source(base, "previous_authority_question")
    return base


def _ordinary(base: dict[str, Any], text: str) -> dict[str, Any]:
    base["normalized_request"] = text.strip()
    return base


def _false_positive_ordinary(base: dict[str, Any], text: str) -> dict[str, Any]:
    base["is_continuation"] = False
    base["evidence_sources"] = [
        source for source in base["evidence_sources"]
        if source != "short_continuation_phrase"
    ]
    _add_source(base, "false_positive_context")
    return _ordinary(base, text)


def _has_workspace_frontier(workspace: dict[str, Any]) -> bool:
    return bool(
        workspace.get("dirty_worktree")
        or workspace.get("previous_assistant_next_step")
        or workspace.get("todo_items")
    )


def _is_reference_context(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).casefold()
    markers = (
        "explain",
        "summarize",
        "what does",
        "what is",
        "read the",
        "safety rules",
        "archive format",
        "什么意思",
        "是什么意思",
        "安全策略",
    )
    return any(marker in normalized for marker in markers)


def _looks_like_question(text: str) -> bool:
    return "?" in text or "？" in text or "吗" in text


def _authority_boundary(inferred: bool, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = previous or {}
    return {
        "reversible_local_work": "allowed after context hydration",
        "external_side_effect": "requires fresh authorization unless already granted",
        "destructive_action": "not authorized",
        "authorization_inferred": inferred,
        "action_scope": previous.get("action_scope", ""),
        "approval_scope": previous.get("approval_scope", ""),
    }


def _capability_caveat() -> str:
    return "MCP can classify and return an intake directive; host pre-prompt injection requires a host user-message hook."


def _add_source(payload: dict[str, Any], source: str) -> None:
    if source not in payload["evidence_sources"]:
        payload["evidence_sources"].append(source)
