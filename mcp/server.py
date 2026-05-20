from __future__ import annotations

import json
import math
import os
import re
import sys
import traceback
import unicodedata
from datetime import datetime, timezone
from functools import wraps
from inspect import signature
from pathlib import Path
from typing import Any, Callable

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent.resolve()
sys.path = [p for p in sys.path if Path(p or ".").resolve() != PROJECT_ROOT]
sys.path.insert(0, str(THIS_DIR))

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError as exc:  # pragma: no cover
    if exc.name not in {"mcp", "mcp.server", "mcp.server.fastmcp"}:
        raise

    class FastMCP:  # type: ignore[override]
        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self):
            def decorator(func):
                return func

            return decorator

        def run(self) -> None:
            raise RuntimeError(
                "The MCP SDK is not installed. Install the `mcp` package to run this server over stdio."
            )


from agent_runway_runtime.adversarial_audit import audit_stop_gate, budget_usage, gate_violations
from agent_runway_runtime.adversarial_audit_schema import PROFILES
from agent_runway_runtime.store import RuntimeStore
from agent_runway_runtime.host_tool_taxonomy import EXECUTION_TOOLS, MUTATION_TOOLS, OBSERVATION_TOOLS
from agent_runway_runtime.debug_logging import write_debug_log
from agent_runway_runtime.prompt_intake import classify_prompt_intake
from agent_runway_runtime.detection_text import strip_invisible_controls

mcp = FastMCP("agent-runway")
store = RuntimeStore()

BUDGET_EXHAUSTED_GUIDANCE = (
    "Budget is exhausted. Do not claim another verified slice; wrap up by "
    "summarizing evidence, unverified items, known risks, and the legal next action."
)
RETRY_BUDGET_EXHAUSTED_GUIDANCE = (
    "Retry budget is exhausted. If local retries are still blocked, use "
    "stuck_escalation with materially different recorded attempts; otherwise "
    "continue only with a high-value non-retry slice."
)
DEFAULT_BUDGET_GUIDANCE = (
    "Continue only with a high-value reversible slice that respects the mission "
    "budgets and red lines."
)
MISSION_RECEIPT_SCAN_LIMIT = 100000
SUBAGENT_TOOL_CALLS_PER_PARENT_SLICE = 10
MAX_RUNNING_SUBAGENTS_PER_MISSION = 5
MAX_COMPLETION_CRITERION_CHARS = 2000
DEFAULT_CHILD_MAX_ELAPSED_SECONDS = 3600
SUBAGENT_CONTEXT_MODES = {"fresh", "fork", "resumed", "team", "unknown"}
SUBAGENT_WORKSPACE_KINDS = {
    "shared_checkout",
    "worktree",
    "local_sandbox",
    "cloud_sandbox",
    "unknown",
}
SUBAGENT_STOP_STATUSES = {"completed", "failed", "abandoned", "rejected"}
SUBAGENT_TERMINAL_STATUSES = SUBAGENT_STOP_STATUSES
SUBAGENT_REVERIFY_WORKSPACES = {"worktree", "local_sandbox", "cloud_sandbox"}
AUTHORIZATION_KINDS = {"scoped_approval", "standing_boundary"}
BROAD_AUTHORIZATION_SCOPE_MARKERS = frozenset({"*", "all", "full"})

LEGAL_STOP_CONDITIONS = {
    "slice_verified",
    "frontier_exhausted",
    "user_information_required",
    "approval_required",
    "interpretation_deadlock",
    "stuck_escalation",
}
SOFT_STOP_CONDITIONS = {"user_information_required", "approval_required"}
TRUSTED_MUTATION_RECEIPT_SOURCES = frozenset({"claude-hook", "opencode-plugin"})
REPEATED_STOP_LIMIT = 2


def _runtime_tool(func: Callable[..., Any]) -> Callable[..., Any]:
    return mcp.tool()(_log_runtime_tool_errors(func))


def _log_runtime_tool_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            call = {"args": args, "kwargs": kwargs}
            write_debug_log("runtime_tool.error", _runtime_tool_error_details(func, call, exc))
            raise

    return wrapper


def _runtime_tool_error_details(
    func: Callable[..., Any], call: dict[str, Any], exc: Exception
) -> dict[str, Any]:
    arguments = _runtime_tool_arguments(func, call["args"], call["kwargs"])
    return {
        "tool_name": func.__name__,
        "exception_type": type(exc).__name__,
        "error_message": str(exc),
        "session_id": arguments.get("session_id"),
        "task_id": arguments.get("task_id"),
        "receipt_ids": _runtime_tool_receipt_ids(arguments),
        "argument_names": sorted(arguments),
        "argument_types": {key: type(value).__name__ for key, value in arguments.items()},
        "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
    }


def _runtime_tool_arguments(
    func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    bound = signature(func).bind_partial(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def _runtime_tool_receipt_ids(arguments: dict[str, Any]) -> Any:
    for key in ("receipt_ids", "evidence_receipt_ids"):
        if key in arguments:
            return arguments[key]
    criterion_map = arguments.get("criterion_receipt_map")
    if not isinstance(criterion_map, list):
        return None
    return [item.get("receipt_ids") for item in criterion_map if isinstance(item, dict)]

# Word-boundary regex patterns. Substring matching produced too many false positives
# (e.g. "shoulder", "i think about", "should i rerun"). The new patterns target the
# concrete hedging shapes that actually leak into work summaries while sparing
# legitimate uses like "the user asked whether i should rerun".
ASSERTION_SIGNAL_PATTERNS = (
    re.compile(r"\bshould (?:work|pass|be fine|resolve|fix|return|now)\b", re.IGNORECASE),
    re.compile(r"\bshould be (?:enough|ok|okay|good|sufficient|adequate|correct|right)\b", re.IGNORECASE),
    re.compile(r"\bprobably\b", re.IGNORECASE),
    re.compile(r"\b(?:most\s+)?likely\s+(?:correct|fine|fixed|done|resolved|good|ready|complete|works?|passes?)\b", re.IGNORECASE),
    re.compile(r"\b(?:maybe|perhaps)\s+(?:(?:it|this|that)\s+is\s+)?(?:done|correct|fixed|resolved|fine|ready|complete|good)\b", re.IGNORECASE),
    re.compile(r"\b(?:might|may)\s+(?:be\s+)?(?:resolved|fixed|correct|fine|done|complete|ready|work|pass)\b", re.IGNORECASE),
    re.compile(r"\bi believe\b", re.IGNORECASE),
    re.compile(r"\b(?:i think|i'?m thinking)\s+(?:it|this|that|the|these|those|everything|all|we|changes?)\b", re.IGNORECASE),
    re.compile(r"\bi\s+(?:feel|guess|assume|expect|hope)\s+(?:it|this|that|the|these|those|everything|all|we|changes?|implementation|patch|fix)\b", re.IGNORECASE),
    re.compile(r"\bi\s+feel\s+like\s+(?:it|this|that|the\s+(?:change|implementation|patch|fix)|these\s+changes?)\s+(?:is|are|was|were|will be)?\s*(?:done|correct|fixed|resolved|fine|ready|complete|good|acceptable|working|passing)\b", re.IGNORECASE),
    re.compile(r"\bi(?: would|'d|\u2019d)\s+(?:say|guess)\b", re.IGNORECASE),
    re.compile(r"\bas far as i can tell\b", re.IGNORECASE),
    re.compile(r"\bpresumably\b", re.IGNORECASE),
    re.compile(r"\bno reason why\s+(?:it|this|that|the change|the implementation)?\s*(?:should|would|will|could)\s+not\s+(?:work|pass|be\s+(?:fine|ok|good|correct|fixed|resolved))\b", re.IGNORECASE),
    re.compile(r"\b(?:i see|there is) no reason why\s+(?:it|this|that|the change|the implementation)?\s*(?:should|would|will|could)\s+(?:fail|break|regress)\b", re.IGNORECASE),
    re.compile(r"(?:\b(?:i\s+see\s+|there(?:\s+is|'s)\s+)no reason (?:why )?not to\s+(?:accept|approve|complete|close|merge|ship|refuse|reject)\b|(?:^|[.!?;:]\s*)no reason (?:why )?not to\s+(?:accept|approve|complete|close|merge|ship|refuse|reject)\b)", re.IGNORECASE),
    re.compile(r"(?:\b(?:i\s+see\s+|there(?:\s+is|'s)\s+)nothing wrong with\s+(?:accepting|approving|completing|closing|merging|shipping|refusing|rejecting)\b|(?:^|[.!?;:]\s*)nothing wrong with\s+(?:accepting|approving|completing|closing|merging|shipping|refusing|rejecting)\b)", re.IGNORECASE),
    re.compile(r"\blooks correct\b", re.IGNORECASE),
    re.compile(r"\b(?:seems|looks|appears)\s+(?:correct|fixed|fine|good|right|resolved|done|complete|ready|ok|okay)\b", re.IGNORECASE),
    re.compile(r"\b(?:seems|appears) to\b", re.IGNORECASE),
    re.compile(r"\b(?:seemed|appeared) to\b", re.IGNORECASE),
    re.compile(r"\bi['\u2019]?m confident\b", re.IGNORECASE),
    re.compile(r"\bit works\b", re.IGNORECASE),
    re.compile(r"\bdeber[ií]a\s+(?:funcionar|pasar|estar\s+(?:bien|correcto|listo))\b", re.IGNORECASE),
    re.compile(r"\bparece\s+(?:correcto|bien|listo|resuelto)\b", re.IGNORECASE),
    re.compile(r"\bprobablemente\s+(?:funciona|est[aá]\s+(?:bien|correcto|listo|resuelto))\b", re.IGNORECASE),
    re.compile(r"\bcreo\s+que\s+(?:funciona|est[aá]\s+(?:bien|correcto|listo|resuelto))\b", re.IGNORECASE),
    re.compile(r"\bno hay raz[oó]n para\s+(?:rechazar|no aceptar)\b", re.IGNORECASE),
    re.compile(r"\bdevrait\s+(?:marcher|fonctionner|passer)\b", re.IGNORECASE),
    re.compile(r"\bsemble\s+(?:correct|bon|r[eé]solu|termin[eé]|pr[eê]t)\b", re.IGNORECASE),
    re.compile(r"\bprobablement\s+(?:correct|bon|r[eé]solu|termin[eé]|pr[eê]t)\b", re.IGNORECASE),
    re.compile(r"\bje pense que\s+(?:(?:ça|ca|cela|ceci)\s+)?(?:marche|fonctionne|est\s+(?:correct|bon|pr[eê]t))\b", re.IGNORECASE),
    re.compile(r"\bpas de raison de\s+(?:refuser|rejeter)\b", re.IGNORECASE),
    re.compile(r"\bsollte\s+(?:funktionieren|klappen|bestehen)\b", re.IGNORECASE),
    re.compile(r"\bscheint\s+(?:korrekt|richtig|gut|fertig|bereit)\b", re.IGNORECASE),
    re.compile(r"\bwahrscheinlich\s+(?:korrekt|richtig|gut|fertig|bereit)\b", re.IGNORECASE),
    re.compile(r"\bich glaube(?:,)?\s+(?:(?:es|das|dies)\s+)?(?:funktioniert|ist\s+(?:korrekt|richtig|gut|fertig))\b", re.IGNORECASE),
    re.compile(r"\bkein grund (?:zur ablehnung|abzulehnen)\b", re.IGNORECASE),
    re.compile(r"\bdeveria\s+(?:funcionar|passar|estar\s+(?:correto|pronto|bom))\b", re.IGNORECASE),
    re.compile(r"\bparece\s+(?:correto|bom|pronto|resolvido)\b", re.IGNORECASE),
    re.compile(r"\bprovavelmente\s+(?:funciona|est[aá]\s+(?:correto|pronto|bom))\b", re.IGNORECASE),
    re.compile(r"\bacho que\s+(?:funciona|est[aá]\s+(?:correto|pronto|bom))\b", re.IGNORECASE),
    re.compile(r"\bn[aã]o h[aá] raz[aã]o para\s+(?:rejeitar|recusar)\b", re.IGNORECASE),
    re.compile(r"(?:動くはず|大丈夫そう|動くと思う|たぶん大丈夫|おそらく大丈夫|拒否する理由がない)", re.IGNORECASE),
    re.compile(r"(?:작동할 거예요|작동할 것입니다|괜찮을 것 같아요|아마 될 거예요|거절할 이유가 없다)", re.IGNORECASE),
    re.compile(r"应该(?:就|已经)?(?:可以了|没问题|能过|通过|好了|行了|对了|完成了|解决了)", re.IGNORECASE),
    re.compile(r"应该(?:够了|差不多了)", re.IGNORECASE),
    re.compile(r"(?:就|应该就)行了", re.IGNORECASE),
    re.compile(r"大概(?:没问题|行了|可以|好了)", re.IGNORECASE),
    re.compile(r"(?:感觉|估计|似乎|好像)(?:应该|已经)?(?:没问题|可以|好了|行了|解决了)", re.IGNORECASE),
    re.compile(r"估计应该可以", re.IGNORECASE),
    re.compile(r"(?:按说|理论上)(?:应该)?(?:是)?(?:可以|可以了|没问题|好了|行了)", re.IGNORECASE),
    re.compile(r"不出意外(?:的话)?应该(?:可以|没问题)", re.IGNORECASE),
    re.compile(r"应该不会(?:出问题|出错|失败|有问题)(?:了)?", re.IGNORECASE),
    re.compile(r"应该不用(?:再查|继续|再改|再跑)(?:了)?", re.IGNORECASE),
    re.compile(r"看起来对了", re.IGNORECASE),
    re.compile(r"(?:没有|没)(?:什么|任何)?理由不(?:接受|批准|通过|完成|关闭|合并|发布|拒绝|驳回)(?!这句|这种|原文|表达|措辞|这个表达)", re.IGNORECASE),
    re.compile(r"看不出(?:有)?(?:什么|任何)?问题(?!这句|这个|这种|原文|表达|措辞)", re.IGNORECASE),
    re.compile(r"看着(?:没问题|可以了|好了|行了)", re.IGNORECASE),
    re.compile(r"我觉得(?:这次)?能过", re.IGNORECASE),
    re.compile(r"我觉得(?:没问题|可以了|好了|行了|差不多了|是这样了)", re.IGNORECASE),
    re.compile(r"(?:感觉|好像|似乎)(?:应该|已经)?(?:差不多了|差不多)(?!这句|这个|这种|原文|表达|措辞)", re.IGNORECASE),
)

EXTERNAL_QUOTE_MARKERS_EN = (
    'user wrote',
    'user said',
    'user told',
    'the user told',
    'user mentioned',
    'the user mentioned',
    'user stated',
    'the user stated',
    'user claimed',
    'the user claimed',
    'per the user',
    'issue thread said',
    'bug thread',
    'issue thread',
    'the thread said',
    'quoted from',
)

EXTERNAL_QUOTE_MARKERS_ZH = (
    '工单里写了',
    '用户说',
    '日志写',
    '日志写道',
    '日志显示',
    '日志记录',
    '报告称',
    '报告写',
    '报告写道',
    '报告写明',
    '报告指出',
    '用户提到',
    '用户反馈',
    '用户告诉',
    '对方说',
    '原文',
    '描述中说',
    '原话',
    '写的是',
    '引用',
    '文档原话',
)

EXTERNAL_QUOTE_MARKERS_MULTI_LANG = (
    'el usuario dijo',
    'l\'utilisateur a dit',
    'der nutzer sagte',
    'o usuário disse',
    'ユーザーは言った',
    '사용자가 말했다',
)


def _has_assertion_language(text: str) -> bool:
    normalized_text = unicodedata.normalize("NFKC", strip_invisible_controls(text))
    lowered = normalized_text.lower()
    has_assertion = any(pattern.search(normalized_text) for pattern in ASSERTION_SIGNAL_PATTERNS)
    if not has_assertion:
        return False
    if (
        ('"' in normalized_text)
        or ("'" in normalized_text)
        or ('“' in normalized_text and '”' in normalized_text)
        or ('「' in normalized_text and '」' in normalized_text)
        or ('『' in normalized_text and '』' in normalized_text)
        or ('«' in normalized_text and '»' in normalized_text)
        or ('‹' in normalized_text and '›' in normalized_text)
    ) and (
        any(marker in lowered for marker in EXTERNAL_QUOTE_MARKERS_EN)
        or any(marker in normalized_text for marker in EXTERNAL_QUOTE_MARKERS_ZH)
        or any(marker in lowered for marker in EXTERNAL_QUOTE_MARKERS_MULTI_LANG)
    ):
        trailing_text = re.sub(r'".*?"|\'.*?\'|“.*?”|「.*?」|『.*?』|«.*?»|‹.*?›', ' ', normalized_text)
        return any(pattern.search(trailing_text) for pattern in ASSERTION_SIGNAL_PATTERNS)
    return True


def _string_list(values: list[str] | None) -> list[str]:
    return [v.strip() for v in (values or []) if isinstance(v, str) and v.strip()]


def _receipt_id_list(values: Any, field_name: str = "receipt_ids") -> list[str]:
    if (
        not isinstance(values, list)
        or not all(isinstance(value, str) and value.strip() for value in values)
    ):
        raise ValueError(f"{field_name} must be a list of non-empty receipt_id strings.")
    return [value.strip() for value in values]


def _require_unique_receipt_ids(receipt_ids: list[str], field_name: str = "receipt_ids") -> None:
    if len(receipt_ids) != len(set(receipt_ids)):
        raise ValueError(f"{field_name} contains duplicate receipt_id values.")


def _require_receipt_ids_present(receipt_ids: list[str], field_name: str = "receipt_ids") -> None:
    if not receipt_ids:
        raise ValueError(
            f"{field_name} must include at least one receipt_id; runtime-backed records "
            "require captured receipt evidence. Hosts without automatic receipt capture "
            "cannot satisfy this field with an empty list; report direct local evidence "
            "separately or fix the host receipt bridge instead of fabricating receipt ids."
        )


def _reject_subagent_handoff_receipt_ids(receipt_ids: list[str]) -> None:
    handoff_ids = [
        receipt_id
        for receipt_id in receipt_ids
        if receipt_id.startswith("subagent_handoff:")
    ]
    if handoff_ids:
        raise ValueError(
            "subagent handoff id is not a receipt; cite verified child receipt_id values instead: "
            f"{handoff_ids}"
        )


def _require_active_mission(session_id: str, task_id: str) -> Any:
    session_id = _required_identifier(session_id, "session_id")
    task_id = _required_identifier(task_id, "task_id")
    mission = store.get_active_mission(session_id, task_id)
    if mission is None:
        raise ValueError(
            f"No active mission for session_id={session_id!r}, task_id={task_id!r}. Call mission_lock first."
        )
    return mission


def _required_identifier(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not strip_invisible_controls(normalized).strip():
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


def _criterion_identity(value: str) -> str:
    visible = strip_invisible_controls(value)
    folded = unicodedata.normalize("NFKD", visible)
    without_marks = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip().casefold()


def _mission_payload_missing(tool_name: str, session_id: str, task_id: str) -> str:
    write_debug_log(
        "runtime_tool.validation_error",
        {
            "tool_name": tool_name,
            "error": "missing_mission",
            "session_id": session_id,
            "task_id": task_id,
        },
    )
    return json.dumps(
        {
            "tool": tool_name,
            "session_id": session_id,
            "task_id": task_id,
            "error": "No mission found for this session/task.",
        },
        ensure_ascii=False,
        indent=2,
    )


def _mission_or_none(session_id: str, task_id: str) -> Any | None:
    if not task_id:
        active_missions = store.list_active_missions(session_id)
        return active_missions[0] if len(active_missions) == 1 else None
    mission = store.get_active_mission(session_id, task_id)
    if mission is not None:
        return mission
    try:
        return store.get_mission(session_id, task_id)
    except KeyError:
        return None


def _mission_intake_payload(mission: Any) -> dict[str, Any]:
    return {
        "session_id": mission.session_id,
        "task_id": mission.task_id,
        "goal": mission.goal,
        "completion_criteria": mission.completion_criteria,
        "status": mission.status,
        "updated_at": mission.updated_at,
    }


def _ambiguous_session_mission_payload(missions: list[Any], base: dict[str, Any]) -> dict[str, Any]:
    payload = dict(base)
    payload.update({
        "classification": "ambiguous_session_mission",
        "should_activate_agent_runway": False,
        "confidence": 0.64,
        "candidate_missions": [_mission_intake_payload(mission) for mission in missions],
        "required_user_question": "Multiple active Agent-Runway missions exist in the same session; specify task_id.",
    })
    sources = list(payload.get("evidence_sources", []))
    if "multiple_session_missions" not in sources:
        sources.append("multiple_session_missions")
    payload["evidence_sources"] = sources
    payload.pop("mission", None)
    return payload


def _format_receipts(receipts: list[Any]) -> str:
    lines = []
    for record in receipts:
        fragment = f"{record.receipt_id} [{record.tool_name}]"
        if record.command_text:
            fragment += f" {record.command_text}"
        if record.exit_code is not None:
            fragment += f" exit={record.exit_code}"
        lines.append(fragment)
    return "\n".join(lines)


def _fresh_receipt_warning(receipts: list[Any]) -> list[str]:
    warnings: list[str] = []
    if receipts and all(
        receipt.tool_name in OBSERVATION_TOOLS for receipt in receipts
    ):
        warnings.append(
            "Only observational receipts were supplied. Make sure this turn genuinely contained a verified reduction."
        )
    if receipts and any(receipt.task_id is None for receipt in receipts):
        warnings.append(
            "Receipts are not mission-scoped. Prefer task-scoped receipts for load-bearing claims."
        )
    return warnings


def _taskless_receipt_ambiguity_violations(
    session_id: str, task_id: str, receipts: list[Any], context: str
) -> list[str]:
    if not any(receipt.task_id is None for receipt in receipts):
        return []
    active_task_ids = {
        mission.task_id for mission in store.list_active_missions(session_id)
    }
    if len(active_task_ids) <= 1:
        return []
    return [
        f"{context} cannot use taskless receipt evidence while multiple active missions exist "
        f"in this session: {sorted(active_task_ids)}. Provide task-scoped receipts for task_id={task_id!r}."
    ]


def _receipt_in_mission_scope(receipt: Any, task_id: str) -> bool:
    return receipt.task_id == task_id or receipt.task_id is None


def _get_mission_scope_receipts(
    receipt_ids: list[str], session_id: str, task_id: str
) -> list[Any]:
    order = {receipt_id: index for index, receipt_id in enumerate(receipt_ids)}
    receipts = [
        receipt
        for receipt in store.get_receipts(receipt_ids, session_id=session_id)
        if _receipt_in_mission_scope(receipt, task_id)
    ]
    return sorted(receipts, key=lambda receipt: order.get(receipt.receipt_id, len(order)))


def _receipt_scope_issues(receipt_ids: list[str], session_id: str, task_id: str | None) -> list[str]:
    rows = {receipt.receipt_id: receipt for receipt in store.get_receipts(receipt_ids)}
    issues: list[str] = []
    for receipt_id in receipt_ids:
        receipt = rows.get(receipt_id)
        if receipt is None:
            issues.append(f"receipt_id {receipt_id!r} was not found")
            continue
        if receipt.session_id != session_id:
            issues.append(
                f"receipt_id {receipt_id!r} belongs to session_id={receipt.session_id!r}, not {session_id!r}"
            )
            continue
        if task_id is not None and not _receipt_in_mission_scope(receipt, task_id):
            issues.append(
                f"receipt_id {receipt_id!r} belongs to task_id={receipt.task_id!r}, not {task_id!r}"
            )
    return issues


def _receipt_scope_error(receipt_ids: list[str], session_id: str, task_id: str | None) -> str:
    issues = _receipt_scope_issues(receipt_ids, session_id, task_id)
    if not issues:
        return "All referenced receipt_ids must exist and belong to this mission scope."
    return "; ".join(issues)


def _mission_scope_recent_receipts(
    session_id: str, task_id: str, mission: Any, limit: int
) -> list[Any]:
    start_seq = _mission_start_receipt_seq(mission)
    scan_limit = max(limit, MISSION_RECEIPT_SCAN_LIMIT)
    receipts = [
        receipt
        for receipt in store.list_recent_receipts(session_id, limit=scan_limit)
        if _receipt_in_mission_scope(receipt, task_id) and int(receipt.seq) > start_seq
    ]
    return receipts[:limit]


def _latest_mission_receipt_seq(session_id: str, task_id: str, mission: Any) -> int:
    receipts = _mission_scope_recent_receipts(
        session_id, task_id, mission, MISSION_RECEIPT_SCAN_LIMIT
    )
    return max((int(receipt.seq) for receipt in receipts), default=0)


def _latest_mission_mutation_seq(session_id: str, task_id: str, mission: Any) -> int:
    receipts = _mission_scope_recent_receipts(
        session_id, task_id, mission, MISSION_RECEIPT_SCAN_LIMIT
    )
    return max(
        (int(receipt.seq) for receipt in receipts if _receipt_is_mutation_evidence(receipt)),
        default=0,
    )

def _mission_start_receipt_seq(mission: Any) -> int:
    notes = getattr(mission, "notes", None) or {}
    try:
        return int(notes.get("mission_start_receipt_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _receipt_epoch_violations(mission: Any, receipts: list[Any], context: str) -> list[str]:
    start_seq = _mission_start_receipt_seq(mission)
    stale = [receipt.receipt_id for receipt in receipts if int(receipt.seq) <= start_seq]
    if not stale:
        return []
    return [
        f"{context} references stale receipt(s) from before the current mission lock: {stale}; "
        f"mission_start_receipt_seq={start_seq}. Re-run verification after mission_lock."
    ]


def _taskless_future_timestamp_violations(receipts: list[Any], context: str) -> list[str]:
    now = datetime.now(timezone.utc)
    future_taskless: list[str] = []
    for receipt in receipts:
        if receipt.task_id is not None:
            continue
        try:
            created_at = _parse_iso(receipt.created_at)
        except ValueError:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if created_at > now:
            future_taskless.append(receipt.receipt_id)
    if not future_taskless:
        return []
    return [
        f"{context} cannot use taskless receipt evidence with future timestamps: "
        f"{future_taskless}. Re-run verification through a mission or host-session binding."
    ]


def _require_subagent_span(session_id: str, task_id: str, child_span_id: str) -> Any:
    child_span_id = _required_identifier(child_span_id, "child_span_id")
    try:
        return store.get_subagent_span(session_id, task_id, child_span_id)
    except KeyError as exc:
        raise ValueError(f"Unknown child_span_id for this mission: {child_span_id!r}") from exc


def _require_non_terminal_subagent_span(span: Any) -> None:
    if span.status in SUBAGENT_TERMINAL_STATUSES:
        raise ValueError(
            f"child_span_id {span.child_span_id!r} is already terminal with status {span.status!r}."
        )


def _jsonable_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    return dict(value)


def _validated_delegated_budget(
    delegated_budget: dict[str, Any], mission: Any, session_id: str, task_id: str
) -> dict[str, Any]:
    budget = _jsonable_dict(delegated_budget, "delegated_budget")
    known_numeric_limits = {"max_slices", "max_tool_calls", "max_elapsed_seconds"}
    for key, value in budget.items():
        if key in known_numeric_limits and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise ValueError(f"delegated_budget.{key} must be an integer >= 1.")
    if not budget:
        return budget

    mission_budget = _budget_snapshot(session_id, task_id, mission)
    max_slices = budget.get("max_slices")
    if isinstance(max_slices, int) and max_slices > mission_budget["slices_remaining"]:
        raise ValueError(
            "delegated_budget.max_slices exceeds parent slices_remaining "
            f"{mission_budget['slices_remaining']}."
        )
    max_tool_calls = budget.get("max_tool_calls")
    tool_call_ceiling = (
        mission_budget["slices_remaining"] * SUBAGENT_TOOL_CALLS_PER_PARENT_SLICE
    )
    if isinstance(max_tool_calls, int) and max_tool_calls > tool_call_ceiling:
        raise ValueError(
            "delegated_budget.max_tool_calls exceeds parent derived tool-call ceiling "
            f"{tool_call_ceiling}."
        )
    max_elapsed_seconds = budget.get("max_elapsed_seconds")
    time_remaining_minutes = mission_budget["time_remaining_minutes"]
    if (
        isinstance(max_elapsed_seconds, int)
        and time_remaining_minutes is not None
        and max_elapsed_seconds > time_remaining_minutes * 60
    ):
        raise ValueError(
            "delegated_budget.max_elapsed_seconds exceeds parent time_remaining_seconds "
            f"{time_remaining_minutes * 60}."
        )
    if (
        isinstance(max_elapsed_seconds, int)
        and time_remaining_minutes is None
        and max_elapsed_seconds > DEFAULT_CHILD_MAX_ELAPSED_SECONDS
    ):
        raise ValueError(
            "delegated_budget.max_elapsed_seconds exceeds default parentless child time ceiling "
            f"{DEFAULT_CHILD_MAX_ELAPSED_SECONDS}."
        )
    return budget


def _validated_adversarial_profiles(profiles: list[str] | None) -> list[str]:
    values = _string_list(profiles)
    unknown = [profile for profile in values if profile not in PROFILES]
    if unknown:
        raise ValueError(f"unknown adversarial profile: {unknown}")
    return values


def _running_subagent_count(session_id: str, task_id: str) -> int:
    return sum(
        1
        for span in store.list_subagent_spans(session_id, task_id)
        if span.status not in SUBAGENT_TERMINAL_STATUSES
    )


def _dict_list(
    value: Any, field_name: str, *, allow_empty: bool = True
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{field_name} must be a list of objects.")
    if not allow_empty and not value:
        raise ValueError(f"{field_name} must contain at least one object.")
    return [dict(item) for item in value]


def _verified_claims(value: Any) -> list[dict[str, Any]]:
    claims = _dict_list(value, "verified_claims", allow_empty=False)
    if not all(str(claim.get("claim", "")).strip() for claim in claims):
        raise ValueError("verified_claims entries must include non-empty claim text.")
    return claims


def _require_subagent_enum(value: str, allowed: set[str], field_name: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if normalized not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}.")
    return normalized


def _subagent_span_payload(span: Any, handoffs: list[Any] | None = None) -> dict[str, Any]:
    handoffs = handoffs or []
    latest = handoffs[-1] if handoffs else None
    receipt_ids = {receipt_id for handoff in handoffs for receipt_id in handoff.receipt_ids}
    activity = _subagent_activity_payload(span)
    return {
        "child_span_id": span.child_span_id,
        "session_id": span.session_id,
        "task_id": span.task_id,
        "host": span.host,
        "subagent_type": span.subagent_type,
        "host_child_id": span.host_child_id,
        "context_mode": span.context_mode,
        "workspace_kind": span.workspace_kind,
        "status": span.status,
        "delegated_scope": span.delegated_scope,
        "delegated_budget": span.delegated_budget,
        "budget_consumed": span.budget_consumed,
        "started_at": span.started_at,
        "ended_at": span.ended_at,
        **activity,
        "parent_receipt_seq": span.parent_receipt_seq,
        "terminal_receipt_seq": span.terminal_receipt_seq,
        "handoff_count": len(handoffs),
        "verified_receipt_count": len(receipt_ids),
        "latest_handoff": None if latest is None else _subagent_handoff_payload(latest),
    }


def _subagent_activity_payload(span: Any) -> dict[str, Any]:
    latest_receipt_at = _latest_child_receipt_at(span)
    last_activity_at = span.ended_at or latest_receipt_at or span.started_at
    idle_minutes = 0
    if span.status not in SUBAGENT_TERMINAL_STATUSES:
        idle_minutes = _minutes_since(last_activity_at)
    return {
        "last_receipt_at": latest_receipt_at,
        "last_activity_at": last_activity_at,
        "idle_minutes": idle_minutes,
    }


def _latest_child_receipt_at(span: Any) -> str | None:
    mission = _mission_or_none(span.session_id, span.task_id)
    if mission is None:
        receipts = store.list_recent_receipts(
            span.session_id, task_id=span.task_id, limit=MISSION_RECEIPT_SCAN_LIMIT
        )
    else:
        receipts = _mission_scope_recent_receipts(
            span.session_id, span.task_id, mission, MISSION_RECEIPT_SCAN_LIMIT
        )
    for receipt in receipts:
        if (receipt.metadata or {}).get("child_span_id") == span.child_span_id:
            return receipt.created_at
    return None


def _subagent_handoff_payload(handoff: Any) -> dict[str, Any]:
    return {
        "handoff_id": handoff.handoff_id,
        "child_span_id": handoff.child_span_id,
        "summary": handoff.summary,
        "verified_claims": handoff.verified_claims,
        "receipt_ids": handoff.receipt_ids,
        "risks": handoff.risks,
        "unverified_items": handoff.unverified_items,
        "created_at": handoff.created_at,
    }


def _subagent_receipt_span_violations(receipts: list[Any], child_span_id: str) -> list[str]:
    mismatched = [
        receipt.receipt_id
        for receipt in receipts
        if receipt.metadata.get("child_span_id") != child_span_id
    ]
    nested = [
        receipt.receipt_id
        for receipt in receipts
        if (receipt.metadata or {}).get("nested_child_span_id")
    ]
    violations: list[str] = []
    if mismatched:
        violations.append(
            "subagent handoff receipt(s) must include matching metadata.child_span_id "
            f"for {child_span_id!r}: {mismatched}"
        )
    if nested:
        violations.append(
            "subagent handoff receipt(s) must not carry nested_child_span_id metadata: "
            f"{nested}"
        )
    return violations


def _child_receipt_readiness_violations(
    receipts: list[Any],
    session_id: str,
    task_id: str,
    handoffs_by_child: dict[str, list[Any]] | None = None,
) -> list[str]:
    handoffs_by_child = handoffs_by_child or {}
    violations: list[str] = []
    for receipt in receipts:
        child_span_id = receipt.metadata.get("child_span_id")
        if not child_span_id:
            continue
        try:
            span = store.get_subagent_span(session_id, task_id, child_span_id)
        except KeyError:
            violations.append(
                f"child receipt {receipt.receipt_id!r} references unknown child_span_id {child_span_id!r}."
            )
            continue
        if child_span_id in handoffs_by_child:
            handoffs = handoffs_by_child[child_span_id]
        else:
            handoffs = store.list_subagent_handoffs(session_id, task_id, child_span_id)
        handoff_receipts = {rid for handoff in handoffs for rid in handoff.receipt_ids}
        if receipt.receipt_id not in handoff_receipts:
            violations.append(
                f"child receipt {receipt.receipt_id!r} requires a child handoff before parent completion."
            )
        if span.status != "completed":
            violations.append(
                f"child receipt {receipt.receipt_id!r} belongs to child_span_id {child_span_id!r} with status {span.status!r}; expected completed."
            )
    return violations


def _child_reverification_violations(
    receipts: list[Any], session_id: str, task_id: str, criterion: str = ""
) -> list[str]:
    parent_execution_seq = max(
        (
            receipt.seq
            for receipt in receipts
            if receipt.tool_name in EXECUTION_TOOLS
            and not receipt.metadata.get("child_span_id")
        ),
        default=0,
    )
    violations: list[str] = []
    for receipt in receipts:
        child_span_id = receipt.metadata.get("child_span_id")
        if not child_span_id:
            continue
        try:
            span = store.get_subagent_span(session_id, task_id, child_span_id)
        except KeyError:
            prefix = f"criterion {criterion!r} " if criterion else ""
            violations.append(
                f"{prefix}child receipt {receipt.receipt_id!r} references unknown child_span_id {child_span_id!r}."
            )
            continue
        if span.workspace_kind not in SUBAGENT_REVERIFY_WORKSPACES:
            continue
        required_seq = max(receipt.seq, span.terminal_receipt_seq)
        if parent_execution_seq > required_seq:
            continue
        prefix = f"criterion {criterion!r} " if criterion else ""
        violations.append(
            f"{prefix}child receipt {receipt.receipt_id!r} from child_span_id {child_span_id!r} "
            f"workspace_kind={span.workspace_kind!r} requires later parent re-verification."
        )
    return violations


def _receipts_show_non_observational_progress(receipts: list[Any]) -> bool:
    return any(
        receipt.tool_name in EXECUTION_TOOLS or _receipt_is_mutation_evidence(receipt)
        for receipt in receipts
    )


def _receipt_can_enter_child_reverification(receipt: Any, known_child_span_ids: set[str]) -> bool:
    child_span_id = (receipt.metadata or {}).get("child_span_id")
    if not child_span_id:
        return True
    return child_span_id in known_child_span_ids


def _open_child_span_violations(spans: list[Any]) -> list[str]:
    open_spans = [
        span.child_span_id
        for span in spans
        if span.status not in SUBAGENT_TERMINAL_STATUSES
    ]
    if not open_spans:
        return []
    return [f"Parent completion blocked by running child span(s): {open_spans}"]


def _failed_child_span_violations(
    spans: list[Any],
    known_risks: list[str] | None,
    unverified_items: list[str] | None,
) -> list[str]:
    disclosures = "\n".join(_string_list(known_risks) + _string_list(unverified_items))
    undisclosed = [
        span.child_span_id
        for span in spans
        if span.status in {"failed", "abandoned", "rejected"}
        and span.child_span_id not in disclosures
    ]
    if not undisclosed:
        return []
    return [
        "failed child span(s) must be disclosed in known_risks or "
        f"unverified_items: {undisclosed}"
    ]


def _numeric_budget_overruns(span: Any) -> dict[str, dict[str, float]]:
    overruns: dict[str, dict[str, float]] = {}
    for key, limit in span.delegated_budget.items():
        consumed_key = key.removeprefix("max_")
        consumed = span.budget_consumed.get(consumed_key, span.budget_consumed.get(key))
        if isinstance(limit, (int, float)) and isinstance(consumed, (int, float)):
            if consumed > limit:
                overruns[key] = {"limit": limit, "consumed": consumed}
    return overruns


def _child_budget_overrun_violations(
    spans: list[Any],
    known_risks: list[str] | None,
    unverified_items: list[str] | None,
) -> list[str]:
    disclosures = "\n".join(_string_list(known_risks) + _string_list(unverified_items))
    undisclosed = {
        span.child_span_id: overruns
        for span in spans
        if (overruns := _numeric_budget_overruns(span))
        and span.child_span_id not in disclosures
    }
    if not undisclosed:
        return []
    return [
        "subagent budget overrun(s) must be disclosed in known_risks or "
        f"unverified_items: {undisclosed}"
    ]


def _missing_child_handoff_disclosures(
    spans: list[Any],
    handoffs_by_child: dict[str, list[Any]],
    known_risks: list[str] | None,
    unverified_items: list[str] | None,
) -> list[str]:
    parent_risks = _string_list(known_risks)
    parent_unverified = _string_list(unverified_items)
    missing: list[str] = []
    for span in spans:
        for handoff in handoffs_by_child.get(span.child_span_id, []):
            for risk in handoff.risks:
                if risk not in parent_risks:
                    missing.append(f"risk from {span.child_span_id}: {risk}")
            for item in handoff.unverified_items:
                if item not in parent_unverified:
                    missing.append(f"unverified item from {span.child_span_id}: {item}")
    if not missing:
        return []
    return [f"child handoff disclosures must be carried into parent completion: {missing}"]


def _minutes_since(iso_text: str) -> int:
    start = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - start
    return max(int(delta.total_seconds() // 60), 0)


def _has_substantive_interpretation_reason(text: str) -> bool:
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    if len(cjk_chars) >= 12:
        return True
    tokens = re.findall(r"\b\w+\b", text.lower())
    distinct_tokens = {token for token in tokens if len(token) > 1}
    return len(distinct_tokens) >= 5


def _has_substantive_governance_text(text: str) -> bool:
    if _visible_stripped_length(text) < 8:
        return False
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    if len(cjk_chars) >= 6:
        return True
    tokens = re.findall(r"\b\w+\b", text.lower())
    distinct_tokens = {token for token in tokens if len(token) > 2}
    return len(distinct_tokens) >= 2


def _has_substantive_governance_list_item(text: str) -> bool:
    if _visible_stripped_length(text) >= 6:
        return True
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    if len(cjk_chars) >= 4:
        return True
    tokens = re.findall(r"\b\w+\b", text.lower())
    meaningful_tokens = [token for token in tokens if len(token) > 1]
    return len(meaningful_tokens) >= 2


def _pending_local_work_scan_text(text: str) -> str:
    chars: list[str] = []
    for char in str(text or ""):
        if char in {" ", "\t", "\n", "\r"}:
            chars.append(" ")
        elif not strip_invisible_controls(char):
            chars.append(" ")
        else:
            chars.append(char)
    normalized = unicodedata.normalize("NFKC", "".join(chars))
    return re.sub(r"\s+", " ", normalized).strip()


def _mentions_pending_local_work(text: str) -> bool:
    scan_text = _pending_local_work_scan_text(text)
    lowered = scan_text.lower()
    compact = re.sub(r"\s+", "", scan_text)
    if _negates_pending_local_work(lowered, compact):
        return False
    patterns = (
        r"\bnext\s+(?:local\s+)?(?:slice|step|action|task|work)\b",
        r"\bnext\s+(?:high-?value\s+)?(?:campaign|frontier)\b",
        r"\bfuture\s+research\s+budget\b",
        r"\bnew\s+alpha(?:-| )source\b",
        r"\btemplate\s+redesign\b",
        r"\bstill\s+need\s+to\b",
        r"\bremaining\s+(?:work|task|action)s?\b",
        r"\bremaining\s+local\b",
        r"\bcontinue\s+(?:with|to|the)\b",
        r"\bfollow-?up\s+(?:work|task|action)s?\b",
    )
    cjk_markers = ("下一步", "下一个", "后续", "继续", "仍需", "还需", "待处理")
    return any(re.search(pattern, lowered) for pattern in patterns) or any(
        marker in compact for marker in cjk_markers
    )


def _negates_pending_local_work(lowered: str, text: str) -> bool:
    latin_patterns = (
        r"\bno\s+remaining\s+(?:work|task|action)s?\b",
        r"\bno\s+further\s+(?:in-scope\s+)?(?:local\s+)?(?:work|tasks?|actions?)\b",
        r"\bcannot\s+continue\s+(?:with|to)\b",
        r"\bcan't\s+continue\s+(?:with|to)\b",
        r"\bnot\s+continue\s+(?:with|to)\b",
    )
    cjk_markers = ("无需后续", "不需要后续", "无法继续", "不能继续", "后续结论继续绑定")
    return any(re.search(pattern, lowered) for pattern in latin_patterns) or any(
        marker in text for marker in cjk_markers
    )


def _pending_local_work_texts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return _string_list(value)
    return [str(value)]


def _pending_local_work_conflict_violations(
    claim_label: str,
    field_values: dict[str, Any],
) -> list[str]:
    violations: list[str] = []
    for field_name, value in field_values.items():
        texts = _pending_local_work_texts(value)
        if any(_mentions_pending_local_work(text) for text in texts):
            violations.append(
                f"{field_name} mentions pending local work; do not claim {claim_label} while local follow-up remains."
            )
    return violations


def _invisible_control_list_violations(field_name: str, values: list[str]) -> list[str]:
    violations: list[str] = []
    for index, value in enumerate(values):
        violations.extend(_invisible_control_violations(f"{field_name}[{index}]", value))
    return violations


def _visible_stripped_length(text: str) -> int:
    return len(strip_invisible_controls(text).strip())


def _invisible_control_violations(field_name: str, text: str) -> list[str]:
    if strip_invisible_controls(text) == text:
        return []
    return [f"{field_name} contains invisible/control characters."]


def _reject_invisible_controls(field_name: str, text: str) -> None:
    violations = _invisible_control_violations(field_name, text)
    if violations:
        raise ValueError(violations[0])


def _reject_invisible_controls_in_list(field_name: str, values: list[str]) -> None:
    for index, value in enumerate(values):
        _reject_invisible_controls(f"{field_name}[{index}]", value)


def _criterion_is_observational_analysis(criterion: str) -> bool:
    lowered = criterion.lower()
    english_analysis_heads = ("analyze", "review", "investigate", "research", "inspect")
    english_artifacts = (
        "baseline",
        "coverage",
        "case",
        "cases",
        "matrices",
        "matrix",
        "model",
        "notes",
        "plan",
        "report",
        "result",
        "results",
        "strategies",
        "strategy",
        "structure",
        "summaries",
        "summary",
        "suite",
        "suites",
        "themes",
        "variation",
    )
    chinese_analysis_heads = ("分析", "审阅", "研究", "调研", "检查")
    chinese_artifacts = ("计划", "报告", "摘要", "策略", "矩阵", "主题", "结构", "差异", "机制")
    return (
        any(head in lowered for head in english_analysis_heads)
        and any(artifact in lowered for artifact in english_artifacts)
    ) or (
        any(head in criterion for head in chinese_analysis_heads)
        and any(artifact in criterion for artifact in chinese_artifacts)
    )


LATIN_NEGATED_ACTION_PREFIXES = (
    r"do\s+not",
    r"don't",
    r"must\s+not",
    r"mustn't",
    r"should\s+not",
    r"shouldn't",
    r"cannot",
    r"can't",
    r"may\s+not",
    r"shall\s+not",
    r"never",
    r"without",
    r"avoid",
    r"refrain\s+from",
    r"skip",
    r"omit",
    r"ne\s+pas",
    r"ne\s+jamais",
    r"sans",
    r"no",
    r"sin",
    r"nicht",
    r"kein(?:e[rsnm]?)?",
    r"não",
    r"sem",
)

LATIN_DOUBLE_NEGATION_PREFIXES = (
    r"not\s+(?:do\s+not|avoid|refrain\s+from|skip|omit)",
    r"no\s+dejar\s+de",
    r"não\s+deixar\s+de",
    r"ne\s+pas\s+(?:éviter|s'abstenir\s+de)",
)

CJK_NEGATED_ACTION_PREFIXES = (
    "绝对不能",
    "严格禁止",
    "不得",
    "不可",
    "不能",
    "不要",
    "禁止",
    "避免",
    "无需",
    "不应",
    "不准",
    "未",
    "勿",
    "别",
    "不",
    "実行禁止",
    "変更禁止",
    "書き込み禁止",
    "してはいけない",
    "してはならない",
    "しないでください",
    "しない",
    "하지 마",
    "하지마",
    "하면 안",
    "금지",
    "않",
    "말고",
)

CJK_DOUBLE_NEGATION_PREFIXES = ("不是不", "并非不", "不能不", "不得不", "不是未")

EXECUTION_ACTION_WORDS = {
    "add", "added", "adding", "build", "building", "check", "compile",
    "compiling", "confirm", "confirmed", "confirming", "configure", "configured",
    "configuring", "correct", "corrected",
    "correcting", "debug", "debugged", "debugging", "deploy", "deployed",
    "deploying", "detect", "document", "documented", "documenting", "ensure",
    "ensured", "ensuring", "execute", "executing", "executar", "executer",
    "exécuter", "ejecutar", "ausführen", "validar", "valider", "validieren",
    "fix", "fixed", "fixing", "fuzz",
    "fuzzing", "harvest", "implement", "implemented", "implementing", "improve",
    "improved", "improving", "lint", "migrate", "migrated", "migrating",
    "mine", "optimize", "optimized", "optimizing", "pass", "profile", "profiling",
    "refactor", "refactored", "refactoring", "render", "rendering", "repair",
    "repaired", "repairing", "resolve", "resolved", "resolving", "run", "running",
    "scan", "scanning", "simulate", "simulating", "test", "tests", "validate",
    "validated", "validating", "verify",
}
EXECUTION_CJK_ACTIONS = (
    "运行", "回测", "扫描", "渲染", "编译", "执行", "检测", "模拟", "验证",
    "修复", "解决", "实现", "添加", "调试", "确保", "修正", "実行", "テスト",
    "検証", "ビルド", "スキャン", "실행", "테스트", "검증", "빌드", "스캔",
)
MUTATION_ACTION_WORDS = {
    "actualizar", "add", "added", "adding", "andern", "configure", "configured",
    "configuring", "correct", "corrected", "correcting", "create", "created",
    "creating", "debug", "debugged", "debugging", "delete", "deleted",
    "deleting", "deploy", "deployed", "deploying", "document", "documented",
    "documenting", "edit", "editing", "ensure", "ensured", "ensuring", "escrever",
    "escribir", "fix", "fixed", "fixing", "implement", "implemented", "implementing",
    "improve", "improved", "improving", "migrate", "migrated", "migrating",
    "modificar", "modifier", "modify", "modified", "modifying", "optimize",
    "optimized", "optimizing", "patch", "patching", "ppt", "refactor", "refactored",
    "refactoring", "remove", "removed", "removing", "repair", "repaired", "repairing",
    "resolve", "resolved",
    "resolving", "rewrite", "rewriting", "revise", "revising", "schreiben",
    "update", "updated", "updating", "write",
    "writing", "wrote", "ändern", "atualizar",
}
MUTATION_CJK_ACTIONS = (
    "撰写", "修改", "更新", "删除", "重构", "创建", "新增", "移除", "终稿", "文案",
    "幻灯片", "修复", "解决", "实现", "添加", "调试", "确保", "修正", "変更",
    "編集", "書く", "작성", "수정", "업데이트", "삭제",
)
MUTATION_ACTION_PHRASES = (
    "file changed", "file change", "changed file", "slide deck", "chapter draft",
    "storyboard draft", "landing page copy", "marketing copy",
)
OBSERVATIONAL_ACTION_ARTIFACT_PATTERNS = (
    r"tests?\s+(?:case|cases|coverage|matrix|matrices|note|notes|plan|plans|report|reports|strategy|strategies|suite|suites)",
    r"benchmark\s+(?:baseline|baselines|plan|plans|report|reports|result|results|summary|summaries)",
    r"(?:build|change|config|configuration|deploy(?:ment)?|migration|patch|release|update|validation|verification)\s+(?:note|notes|plan|plans|report|reports|strategy|strategies|summary|summaries)",
)
CJK_OBSERVATIONAL_ACTION_ARTIFACT_PATTERNS = (
    r"(?:测试|验证|更新|修复|补丁|发布|部署|迁移|配置)(?:计划|报告|摘要|策略|矩阵)",
)


def _has_unnegated_action(
    criterion: str,
    latin_needles: set[str] | None = None,
    cjk_needles: tuple[str, ...] = (),
    latin_phrases: tuple[str, ...] = (),
) -> bool:
    lowered = criterion.lower()
    for phrase in latin_phrases:
        for match in re.finditer(re.escape(phrase), lowered):
            if not _is_latin_action_negated(lowered, match.start()):
                return True
    for needle in latin_needles or set():
        for match in re.finditer(rf"\b{re.escape(needle)}\b", lowered):
            if not _is_latin_action_negated(lowered, match.start()):
                return True
    for needle in cjk_needles:
        for match in re.finditer(re.escape(needle), criterion):
            if not _is_cjk_action_negated(criterion, match.start(), match.end()):
                return True
    return False


def _is_latin_action_negated(lowered: str, start: int) -> bool:
    prefix = lowered[max(0, start - 90) : start]
    segment = _latin_negation_segment(prefix)
    if _has_recent_latin_double_negation(segment):
        return False
    return any(re.search(rf"(?:^|\W){pattern}\b", segment) for pattern in LATIN_NEGATED_ACTION_PREFIXES)


def _latin_negation_segment(prefix: str) -> str:
    boundary_pattern = r"[.;:!?]|\b(?:but|however|except|instead)\b"
    boundaries = [match.end() for match in re.finditer(boundary_pattern, prefix)]
    if not boundaries:
        return prefix
    return prefix[boundaries[-1] :]


def _has_recent_latin_double_negation(prefix: str) -> bool:
    if any(re.search(rf"(?:^|\W){pattern}\b", prefix) for pattern in LATIN_DOUBLE_NEGATION_PREFIXES):
        return True
    skip_pattern = r"\b(?:do\s+not|don't|must\s+not|should\s+not|cannot|can't|never|no)\s+skip\b"
    return bool(re.search(skip_pattern, prefix))


def _is_cjk_action_negated(criterion: str, start: int, end: int) -> bool:
    prefix = criterion[max(0, start - 64) : start]
    segment = _cjk_negation_segment(prefix)
    suffix = criterion[end : min(len(criterion), end + 10)]
    if any(marker in segment for marker in CJK_DOUBLE_NEGATION_PREFIXES):
        return False
    if any(marker in segment for marker in CJK_NEGATED_ACTION_PREFIXES):
        return True
    return any(marker in suffix for marker in ("しない", "禁止", "하지 마", "하지마", "금지"))


def _cjk_negation_segment(prefix: str) -> str:
    boundary = -1
    for marker in ("。", "；", ";", ".", "!", "?", "！", "？", "，", ",", "但是", "但", "而是"):
        index = prefix.rfind(marker)
        if index > boundary:
            boundary = index + len(marker)
    if boundary < 0:
        return prefix
    return prefix[boundary:]


def _criterion_requires_execution_receipt(criterion: str) -> bool:
    if any(phrase in criterion for phrase in ("运行机制", "运行原理", "运行逻辑")) and any(
        phrase in criterion for phrase in ("研究", "分析", "调研")
    ):
        return False
    match_text = _without_observational_action_artifacts(criterion)
    matched = _has_unnegated_action(match_text, EXECUTION_ACTION_WORDS, EXECUTION_CJK_ACTIONS)
    if not matched and _criterion_is_observational_analysis(criterion):
        return False
    return matched


def _without_observational_action_artifacts(criterion: str) -> str:
    if not _criterion_is_observational_analysis(criterion):
        return criterion
    head = r"\b(?:analyze|review|investigate|research|inspect)\s+(?:the\s+)?"
    stripped = criterion
    for pattern in OBSERVATIONAL_ACTION_ARTIFACT_PATTERNS:
        stripped = re.sub(f"{head}{pattern}\\b", " ", stripped, flags=re.IGNORECASE)
    for pattern in CJK_OBSERVATIONAL_ACTION_ARTIFACT_PATTERNS:
        stripped = re.sub(rf"(?:分析|审阅|研究|调研|检查){pattern}", " ", stripped)
    return stripped


def _criterion_requires_mutation_receipt(criterion: str) -> bool:
    match_text = _without_observational_action_artifacts(criterion)
    matched = _has_unnegated_action(
        match_text, MUTATION_ACTION_WORDS, MUTATION_CJK_ACTIONS, MUTATION_ACTION_PHRASES
    )
    if not matched and _criterion_is_observational_analysis(criterion):
        return False
    return matched


def _criterion_has_semantic_support(criterion: str, receipts: list[Any]) -> bool:
    requires_execution = _criterion_requires_execution_receipt(criterion)
    requires_mutation = _criterion_requires_mutation_receipt(criterion)

    if requires_execution and not any(
        receipt.tool_name in EXECUTION_TOOLS for receipt in receipts
    ):
        return False
    if requires_mutation and not any(_receipt_is_mutation_evidence(receipt) for receipt in receipts):
        return False
    return True


def _receipt_is_mutation_evidence(receipt: Any) -> bool:
    return (
        receipt.tool_name in MUTATION_TOOLS
        and str(getattr(receipt, "source", "")).strip() in TRUSTED_MUTATION_RECEIPT_SOURCES
    )


def _budget_snapshot(
    session_id: str, task_id: str, mission: Any | None = None
) -> dict[str, Any]:
    mission = mission or _require_active_mission(session_id, task_id)
    payload = {
        **_budget_usage_payload(session_id, task_id, mission),
        **_approval_freshness_payload(session_id, task_id),
    }
    audit_budget = (mission.notes or {}).get("adversarial_audit_budget") or {}
    if audit_budget:
        audit_records = (mission.notes or {}).get("adversarial_audit_records") or []
        audit_usage = {}
        if audit_records:
            audit_usage = budget_usage(audit_records, audit_budget)
        return {
            **payload,
            "adversarial_audit_budget": audit_budget,
            "adversarial_audit_usage": audit_usage,
        }
    return payload


def _budget_usage_payload(session_id: str, task_id: str, mission: Any) -> dict[str, Any]:
    wall_clock_elapsed = _minutes_since(mission.created_at)
    last_activity_at = _latest_mission_activity_at(session_id, task_id, mission)
    active = _active_work_payload(session_id, task_id, mission)
    elapsed_minutes = active["elapsed_minutes"]
    time_budget = int((mission.notes or {}).get("time_budget_minutes") or 0)
    budget_elapsed = max(elapsed_minutes, wall_clock_elapsed)
    time_remaining = max(time_budget - budget_elapsed, 0) if time_budget else None
    retries_used = _distinct_retry_count(session_id, task_id)
    retries_remaining = max(mission.retry_budget - retries_used, 0)
    slices_remaining = max(mission.slice_budget - mission.slice_count, 0)
    payload: dict[str, Any] = {
        "elapsed_minutes": elapsed_minutes,
        "wall_clock_elapsed_minutes": wall_clock_elapsed,
        "mission_idle_minutes": _minutes_since(last_activity_at),
        "last_activity_at": last_activity_at,
        "receipt_window_minutes": active["receipt_window_minutes"],
        "receipt_duration_minutes": active["receipt_duration_minutes"],
        "time_budget_minutes": time_budget,
        "time_remaining_minutes": time_remaining,
        "slice_budget": mission.slice_budget,
        "slice_count": mission.slice_count,
        "slices_remaining": slices_remaining,
        "retry_budget": mission.retry_budget,
        "retries_used": retries_used,
        "retries_remaining": retries_remaining,
    }
    exhausted = _budget_exhaustion_flags(payload)
    return {
        **payload,
        **exhausted,
        "time_pressure": _budget_time_pressure(payload, exhausted),
        "budget_exhausted": any(exhausted.values()),
        "wrap_up_guidance": _wrap_up_guidance(exhausted),
    }


def _latest_mission_activity_at(session_id: str, task_id: str, mission: Any) -> str:
    candidates = [mission.created_at]
    receipts = _mission_scope_recent_receipts(session_id, task_id, mission, 1)
    if receipts:
        candidates.append(receipts[0].created_at)
    latest_turn = store.latest_approval(session_id, task_id, gate_type="turn_end_gate")
    if latest_turn is not None:
        candidates.append(latest_turn.created_at)
    return max(candidates, key=_parse_iso)


def _active_work_payload(session_id: str, task_id: str, mission: Any) -> dict[str, int]:
    receipts = _mission_scope_recent_receipts(
        session_id, task_id, mission, MISSION_RECEIPT_SCAN_LIMIT
    )
    window_minutes = 0
    if len(receipts) >= 2:
        times = [_parse_iso(receipt.created_at) for receipt in receipts]
        window_minutes = max(int((max(times) - min(times)).total_seconds() // 60), 0)
    duration_minutes = _receipt_duration_minutes(receipts)
    return {
        "elapsed_minutes": duration_minutes,
        "receipt_window_minutes": window_minutes,
        "receipt_duration_minutes": duration_minutes,
    }


def _receipt_duration_minutes(receipts: list[Any]) -> int:
    seconds = 0.0
    for receipt in receipts:
        duration = (receipt.metadata or {}).get("duration_seconds")
        if (
            not isinstance(duration, bool)
            and isinstance(duration, (int, float))
            and duration > 0
            and math.isfinite(float(duration))
        ):
            seconds += float(duration)
    return int(seconds // 60)


def _parse_iso(iso_text: str) -> datetime:
    return datetime.fromisoformat(iso_text.replace("Z", "+00:00"))


def _distinct_retry_count(session_id: str, task_id: str) -> int:
    return len(
        {
            attempt.strategy_fingerprint
            for attempt in store.list_stuck_attempts(session_id, task_id)
        }
    )


def _approval_freshness_payload(session_id: str, task_id: str) -> dict[str, bool]:
    latest_turn = store.latest_approval(session_id, task_id, gate_type="turn_end_gate")
    latest_completion = store.latest_approval(
        session_id, task_id, gate_type="completion_gate"
    )
    latest_authorization = store.latest_approval(
        session_id, task_id, gate_type="user_authorization"
    )
    return {
        "latest_turn_gate_fresh": store.is_approval_fresh(
            latest_turn, session_id, task_id
        ),
        "latest_completion_gate_fresh": store.is_approval_fresh(
            latest_completion, session_id, task_id
        ),
        "latest_user_authorization_fresh": store.is_approval_fresh(
            latest_authorization, session_id, task_id
        ),
    }


def _budget_exhaustion_flags(payload: dict[str, Any]) -> dict[str, bool]:
    return {
        "slice_budget_exhausted": payload["slices_remaining"] == 0,
        "retry_budget_exhausted": payload["retries_remaining"] == 0,
        "time_budget_exhausted": bool(
            payload["time_budget_minutes"] and payload["time_remaining_minutes"] == 0
        ),
    }


def _budget_time_pressure(payload: dict[str, Any], exhausted: dict[str, bool]) -> str:
    if exhausted["slice_budget_exhausted"] or exhausted["time_budget_exhausted"]:
        return "exhausted"
    time_budget = payload["time_budget_minutes"]
    if time_budget:
        ratio = payload["time_remaining_minutes"] / time_budget
    else:
        ratio = 1.0
    min_ratio = min(
        ratio,
        payload["slices_remaining"] / payload["slice_budget"],
    )
    if min_ratio <= 0.25:
        return "high"
    if min_ratio <= 0.5:
        return "medium"
    return "low"


def _wrap_up_guidance(exhausted: dict[str, bool]) -> str:
    if exhausted["slice_budget_exhausted"] or exhausted["time_budget_exhausted"]:
        return BUDGET_EXHAUSTED_GUIDANCE
    if exhausted["retry_budget_exhausted"]:
        return RETRY_BUDGET_EXHAUSTED_GUIDANCE
    return DEFAULT_BUDGET_GUIDANCE


def _authorization_payload(
    session_id: str,
    task_id: str,
    approval: Any | None = None,
    requested_action_scope: str = "",
) -> dict[str, Any] | None:
    approval = approval or store.latest_approval(
        session_id, task_id, gate_type="user_authorization"
    )
    if approval is None:
        return None
    meta = approval.meta or {}
    requested_action_scope = _normalized_authorization_scope(requested_action_scope)
    recorded_action_scope = _normalized_authorization_scope(meta.get("action_scope", ""))
    scope_matches_requested_action = None
    if requested_action_scope:
        scope_matches_requested_action = recorded_action_scope == requested_action_scope
    fresh = store.is_approval_fresh(approval, session_id, task_id)
    if requested_action_scope:
        fresh = fresh and bool(scope_matches_requested_action)
    return {
        "token": approval.token,
        "approved": approval.approved,
        "reason": approval.reason,
        "fresh": fresh,
        "action_scope": meta.get("action_scope", ""),
        "approval_scope": meta.get("approval_scope", ""),
        "authorization_kind": meta.get("authorization_kind", "scoped_approval"),
        "requested_action_scope": requested_action_scope,
        "scope_matches_requested_action": scope_matches_requested_action,
        "irreversible": bool(meta.get("irreversible", False)),
        "user_statement_excerpt": meta.get("user_statement_excerpt", ""),
        "expires_at": approval.expires_at,
        "after_receipt_seq": approval.after_receipt_seq,
    }


def _adversarial_audit_violations(mission: Any, latest_receipt_seq: int) -> list[str]:
    notes = mission.notes or {}
    if not notes.get("adversarial_audit_required"):
        return []
    records = notes.get("adversarial_audit_records") or []
    profiles = _string_list(notes.get("adversarial_audit_profiles"))
    claims = _string_list(notes.get("adversarial_audit_claims"))
    if not isinstance(records, list):
        return ["adversarial audit records must be a list"]
    return gate_violations(records, profiles, claims, latest_receipt_seq)


def _adversarial_audit_status(mission: Any, latest_receipt_seq: int) -> dict[str, Any]:
    notes = mission.notes or {}
    required = bool(notes.get("adversarial_audit_required"))
    records = notes.get("adversarial_audit_records") or []
    profiles = _string_list(notes.get("adversarial_audit_profiles"))
    claims = _string_list(notes.get("adversarial_audit_claims"))
    violations = _adversarial_audit_violations(mission, latest_receipt_seq)
    return {
        "required": required,
        "profiles": profiles,
        "claims": claims,
        "record_count": len(records) if isinstance(records, list) else 0,
        "violations": violations,
        "passed": required and not violations,
    }


@_runtime_tool
def mission_lock(
    session_id: str,
    task_id: str,
    goal: str,
    completion_criteria: list[str],
    scope_boundary: str = "",
    red_lines: list[str] | None = None,
    slice_budget: int = 24,
    retry_budget: int = 3,
    host: str = "unknown",
    cwd: str = ".",
    host_session_id: str = "",
    verification_plan: list[str] | None = None,
    evidence_map: list[dict[str, Any]] | None = None,
    assumptions: list[str] | None = None,
    defaults_chosen: list[str] | None = None,
    open_unknowns: list[str] | None = None,
    degradation_mode: str = "",
    decision_records_required: bool = False,
    counterexample_required: bool = False,
    benchmark_targets: list[str] | None = None,
    time_budget_minutes: int = 0,
    risk_budget: str = "",
    adversarial_audit_required: bool = False,
    adversarial_audit_profiles: list[str] | None = None,
    adversarial_audit_claims: list[str] | None = None,
    adversarial_audit_budget: dict[str, Any] | None = None,
    adversarial_audit_records: list[dict[str, Any]] | None = None,
) -> str:
    """
    Lock or refresh a mission for a specific session/task namespace.

    Third-generation changes:
    - mission notes can store verification planning, evidence mapping, and explicit budget fields
    - completion can require decision records or counterexample checks when the mission warrants it
    """
    session_id = _required_identifier(session_id, "session_id")
    task_id = _required_identifier(task_id, "task_id")
    goal = str(goal or "")
    criteria = _string_list(completion_criteria)
    scope_boundary_text = str(scope_boundary or "")
    red_line_items = _string_list(red_lines)
    _reject_invisible_controls("goal", goal)
    _reject_invisible_controls_in_list("completion_criteria", criteria)
    _reject_invisible_controls("scope_boundary", scope_boundary_text)
    _reject_invisible_controls_in_list("red_lines", red_line_items)
    if not goal.strip():
        raise ValueError("goal must not be empty")
    if not criteria:
        raise ValueError("Provide at least one concrete completion criterion.")
    too_long = [
        criterion
        for criterion in criteria
        if _visible_stripped_length(criterion) > MAX_COMPLETION_CRITERION_CHARS
    ]
    if too_long:
        raise ValueError(
            "completion criterion is too long; "
            f"max visible length is {MAX_COMPLETION_CRITERION_CHARS} characters."
        )
    if len(criteria) != len({_criterion_identity(criterion) for criterion in criteria}):
        raise ValueError("duplicate completion criterion is not allowed")
    if slice_budget < 1 or retry_budget < 1:
        raise ValueError("slice_budget and retry_budget must be >= 1")
    if time_budget_minutes < 0:
        raise ValueError("time_budget_minutes must be >= 0")
    binding_session = str(host_session_id or "").strip()
    if binding_session:
        binding_session = _required_identifier(binding_session, "host_session_id")

    audit_profiles = _validated_adversarial_profiles(adversarial_audit_profiles)
    audit_claims = _string_list(adversarial_audit_claims)
    _reject_invisible_controls_in_list("adversarial_audit_claims", audit_claims)
    if adversarial_audit_required and not audit_profiles:
        raise ValueError(
            "adversarial_audit_required requires at least one adversarial_audit_profile."
        )
    if adversarial_audit_required and not audit_claims:
        raise ValueError(
            "adversarial_audit_required requires at least one adversarial_audit_claim."
        )
    audit_budget = (
        {}
        if adversarial_audit_budget is None
        else _jsonable_dict(adversarial_audit_budget, "adversarial_audit_budget")
    )
    if adversarial_audit_required and not audit_budget:
        raise ValueError(
            "adversarial_audit_required requires non-empty adversarial_audit_budget."
        )
    if audit_budget:
        budget_usage([], audit_budget)

    notes = {
        "host": host,
        "cwd": cwd,
        "verification_plan": _string_list(verification_plan),
        "evidence_map": evidence_map or [],
        "assumptions": _string_list(assumptions),
        "defaults_chosen": _string_list(defaults_chosen),
        "open_unknowns": _string_list(open_unknowns),
        "degradation_mode": degradation_mode.strip(),
        "decision_records_required": bool(decision_records_required),
        "counterexample_required": bool(counterexample_required),
        "benchmark_targets": _string_list(benchmark_targets),
        "time_budget_minutes": time_budget_minutes,
        "risk_budget": risk_budget.strip(),
        "adversarial_audit_required": bool(adversarial_audit_required),
        "adversarial_audit_profiles": audit_profiles,
        "adversarial_audit_claims": audit_claims,
        "adversarial_audit_budget": audit_budget,
        "adversarial_audit_records": adversarial_audit_records or [],
    }

    store.ensure_session(session_id=session_id, host=host, cwd=cwd)
    active_missions = store.list_active_missions(session_id)
    conflicting_active = [mission for mission in active_missions if mission.task_id != task_id]
    mission = store.create_mission(
        session_id=session_id,
        task_id=task_id,
        goal=goal.strip(),
        completion_criteria=criteria,
        scope_boundary=scope_boundary_text.strip(),
        red_lines=red_line_items,
        slice_budget=slice_budget,
        retry_budget=retry_budget,
        notes=notes,
    )
    if binding_session:
        store.bind_host_session_to_mission(binding_session, mission, source="mission_lock")

    lines = [
        "MISSION LOCKED",
        f"session_id: {mission.session_id}",
        f"task_id: {mission.task_id}",
        f"goal: {mission.goal}",
        f"slice_budget: {mission.slice_budget}",
        f"retry_budget: {mission.retry_budget}",
        "completion_criteria:",
    ]
    for index, criterion in enumerate(mission.completion_criteria, start=1):
        lines.append(f"  {index}. {criterion}")
    if mission.scope_boundary:
        lines.append(f"scope_boundary: {mission.scope_boundary}")
    if mission.red_lines:
        lines.append("red_lines:")
        for index, item in enumerate(mission.red_lines, start=1):
            lines.append(f"  {index}. {item}")
    if notes["verification_plan"]:
        lines.append(f"verification_plan_steps: {len(notes['verification_plan'])}")
    if notes["evidence_map"]:
        lines.append(f"evidence_map_entries: {len(notes['evidence_map'])}")
    if notes["counterexample_required"]:
        lines.append("counterexample_required: yes")
    if notes["decision_records_required"]:
        lines.append("decision_records_required: yes")
    if notes["time_budget_minutes"]:
        lines.append(f"time_budget_minutes: {notes['time_budget_minutes']}")
    if notes["risk_budget"]:
        lines.append(f"risk_budget: {notes['risk_budget']}")
    if binding_session:
        lines.append(f"host_session_id: {binding_session}")
        lines.append("binding_written: yes")
    else:
        lines.append("binding_written: no")
    if notes["adversarial_audit_required"]:
        lines.append("adversarial_audit_required: yes")
        lines.append(f"adversarial_audit_profiles: {len(notes['adversarial_audit_profiles'])}")
    if conflicting_active:
        lines.append("has_active_mission: yes")
        lines.append("suggested_action: mission_resume")
        lines.append(
            f"active_mission_candidates: {json.dumps([mission.task_id for mission in conflicting_active], ensure_ascii=False)}"
        )
        lines.append(
            "resume_warning: this session already has other active mission(s); prefer mission_resume for continuation instead of fragmenting the main line."
        )
    lines.append(
        "Call turn_end_gate before stopping, and completion_gate before declaring done."
    )
    return "\n".join(lines)


@_runtime_tool
def mission_resume(session_id: str, task_id: str, host_session_id: str = "") -> str:
    session_id = _required_identifier(session_id, "session_id")
    task_id = _required_identifier(task_id, "task_id")
    mission = _mission_or_none(session_id, task_id)
    if mission is None:
        return _mission_payload_missing("mission_resume", session_id, task_id)
    if mission.status != "active":
        raise ValueError("mission_resume requires an active mission.")

    host_session = str(host_session_id or "").strip()
    if host_session:
        host_session = _required_identifier(host_session, "host_session_id")
    if host_session:
        store.bind_host_session_to_mission(host_session, mission, source="mission_resume")

    budget = _budget_snapshot(session_id, task_id, mission)
    latest_turn = store.latest_approval(session_id, task_id, gate_type="turn_end_gate")
    latest_completion = store.latest_approval(session_id, task_id, gate_type="completion_gate")

    lines = [
        "MISSION RESUMED",
        f"session_id: {mission.session_id}",
        f"task_id: {mission.task_id}",
        f"status: {mission.status}",
        f"slice_count: {mission.slice_count}/{mission.slice_budget}",
        f"mission_start_receipt_seq: {_mission_start_receipt_seq(mission)}",
        f"latest_turn_gate_fresh: {str(store.is_approval_fresh(latest_turn, session_id, task_id)).lower()}",
        f"latest_completion_gate_fresh: {str(store.is_approval_fresh(latest_completion, session_id, task_id)).lower()}",
    ]
    if host_session:
        lines.append(f"host_session_id: {host_session}")
        lines.append("binding_refreshed: yes")
    lines.append(f"time_pressure: {budget['time_pressure']}")
    lines.append("next_action_required: inspect mission_status or export_handoff_packet, then continue from the last verified frontier.")
    return "\n".join(lines)


@_runtime_tool
def list_recent_receipts(session_id: str, task_id: str = "", limit: int = 10) -> str:
    session_id = _required_identifier(session_id, "session_id")
    task_scope = task_id.strip()
    bounded_limit = max(1, min(limit, 50))
    active_missions = [] if task_scope else store.list_active_missions(session_id)
    mission = _mission_or_none(session_id, task_scope) if task_scope else None
    if not task_scope and len(active_missions) == 1:
        mission = active_missions[0]
    if mission is None:
        receipts = store.list_recent_receipts(
            session_id=session_id, task_id=task_scope or None, limit=bounded_limit
        )
    else:
        receipts = _mission_scope_recent_receipts(
            session_id, mission.task_id, mission, bounded_limit
        )
    if not receipts:
        return "No receipts recorded for this scope yet. If host hooks are installed, perform work and inspect again."
    return _format_receipts(receipts)


@_runtime_tool
def budget_status(session_id: str, task_id: str) -> str:
    session_id = _required_identifier(session_id, "session_id")
    task_scope = task_id.strip()
    mission = _mission_or_none(session_id, task_scope)
    if mission is None:
        return _mission_payload_missing("budget_status", session_id, task_scope)
    task_scope = mission.task_id
    return json.dumps(
        _budget_snapshot(session_id, task_scope, mission), ensure_ascii=False, indent=2
    )


@_runtime_tool
def prompt_intake_gate(
    session_id: str,
    user_message: str,
    cwd: str = ".",
    task_id: str = "",
    previous_assistant_state: dict[str, Any] | None = None,
    workspace_state: dict[str, Any] | None = None,
    memory_hint: dict[str, Any] | None = None,
) -> str:
    """
    Classify short or ambiguous user prompts into a mission-intake directive.

    This does not rewrite user intent or enforce host behavior. It returns a
    structured directive so hosts or agents can hydrate Agent-Runway state first.
    """
    session_id = _required_identifier(session_id, "session_id")
    requested_task = task_id.strip() or None
    active_missions = store.list_active_missions(session_id, requested_task)
    active = active_missions[0] if len(active_missions) == 1 else None
    bound = store.bound_active_mission_for_host_session(session_id) if active is None else None
    if requested_task and bound is not None and bound.task_id != requested_task:
        bound = None
    workspace = store.list_active_missions_by_cwd(cwd) if cwd.strip() else []
    if requested_task:
        workspace = [mission for mission in workspace if mission.task_id == requested_task]
    if active is not None:
        workspace = [m for m in workspace if m.session_id != active.session_id]
    if bound is not None:
        workspace = [
            m for m in workspace
            if (m.session_id, m.task_id) != (bound.session_id, bound.task_id)
        ]
    payload = classify_prompt_intake(
        user_message=user_message,
        current_session_id=session_id,
        active_mission=_mission_intake_payload(active) if active else None,
        bound_mission=_mission_intake_payload(bound) if bound else None,
        workspace_missions=[_mission_intake_payload(mission) for mission in workspace],
        previous_assistant_state=previous_assistant_state,
        workspace_state=workspace_state,
        memory_hint=memory_hint,
    )
    if len(active_missions) > 1 and payload["classification"] not in {
        "authorization_not_granted",
        "scoped_authorization_reply",
    }:
        payload = _ambiguous_session_mission_payload(active_missions, payload)
    return json.dumps(payload, ensure_ascii=False, indent=2)


@_runtime_tool
def record_user_authorization(
    session_id: str,
    task_id: str,
    action_scope: str,
    approval_scope: str,
    user_statement_excerpt: str,
    irreversible: bool = False,
    ttl_seconds: int = 1800,
    authorization_kind: str = "scoped_approval",
) -> str:
    mission = _require_active_mission(session_id, task_id)
    session_id = mission.session_id
    task_id = mission.task_id
    action_scope = _required_identifier(action_scope, "action_scope")
    approval_scope = _required_identifier(approval_scope, "approval_scope")
    user_statement_excerpt = _required_identifier(
        user_statement_excerpt, "user_statement_excerpt"
    )
    _reject_invisible_controls("action_scope", action_scope)
    _reject_invisible_controls("approval_scope", approval_scope)
    _reject_invisible_controls("user_statement_excerpt", user_statement_excerpt)
    authorization_kind = authorization_kind.strip() or "scoped_approval"
    if authorization_kind not in AUTHORIZATION_KINDS:
        raise ValueError("authorization_kind must be scoped_approval or standing_boundary.")
    if authorization_kind == "standing_boundary" and bool(irreversible):
        raise ValueError(
            "standing_boundary does not allow irreversible authorization; use a fresh scoped_approval for irreversible actions."
        )
    ttl: int | None = None
    if authorization_kind == "scoped_approval":
        ttl_value = int(ttl_seconds)
        if ttl_value < 0:
            raise ValueError("ttl_seconds must be >= 0 for scoped_approval.")
        ttl = max(60, min(ttl_value, 7200))
    approval = store.create_approval(
        session_id=session_id,
        task_id=task_id,
        gate_type="user_authorization",
        approved=True,
        reason="user authorization recorded",
        after_receipt_seq=store.latest_receipt_seq(session_id),
        ttl_seconds=ttl,
        meta={
            "action_scope": action_scope,
            "approval_scope": approval_scope,
            "authorization_kind": authorization_kind,
            "irreversible": bool(irreversible),
            "user_statement_excerpt": user_statement_excerpt,
        },
    )
    lines = [
        "USER AUTHORIZATION RECORDED",
        f"authorization_token: {approval.token}",
        f"action_scope: {action_scope}",
        f"approval_scope: {approval_scope}",
        f"authorization_kind: {authorization_kind}",
        f"irreversible: {bool(irreversible)}",
        f"expires_at: {approval.expires_at}",
    ]
    return "\n".join(lines)


@_runtime_tool
def authorization_status(session_id: str, task_id: str, action_scope: str = "") -> str:
    session_id = _required_identifier(session_id, "session_id")
    task_scope = task_id.strip()
    mission = _mission_or_none(session_id, task_scope)
    if mission is None:
        return _mission_payload_missing("authorization_status", session_id, task_scope)
    task_scope = mission.task_id
    payload = _authorization_payload(session_id, task_scope, requested_action_scope=action_scope)
    return json.dumps(
        {"task_id": mission.task_id, "authorization": payload},
        ensure_ascii=False,
        indent=2,
    )


def _normalized_authorization_scope(text: str) -> str:
    return " ".join(strip_invisible_controls(str(text or "")).split()).casefold()


@_runtime_tool
def register_subagent_start(
    session_id: str,
    task_id: str,
    subagent_type: str,
    delegated_scope: str,
    delegated_budget: dict[str, Any],
    host: str = "unknown",
    host_child_id: str = "",
    context_mode: str = "fresh",
    workspace_kind: str = "shared_checkout",
) -> str:
    mission = _require_active_mission(session_id, task_id)
    session_id = mission.session_id
    task_id = mission.task_id
    subagent_type = _required_identifier(subagent_type, "subagent_type")
    delegated_scope = _required_identifier(delegated_scope, "delegated_scope")
    host_child_id = host_child_id.strip()
    if not strip_invisible_controls(host_child_id).strip():
        host_child_id = ""
    running_count = _running_subagent_count(session_id, task_id)
    if running_count >= MAX_RUNNING_SUBAGENTS_PER_MISSION:
        raise ValueError(
            "running subagent limit exceeded for this mission; "
            f"max_running_subagents={MAX_RUNNING_SUBAGENTS_PER_MISSION}."
        )
    span = store.create_subagent_span(
        session_id,
        task_id,
        {
            "host": host.strip() or "unknown",
            "subagent_type": subagent_type,
            "host_child_id": host_child_id,
            "context_mode": _require_subagent_enum(
                context_mode, SUBAGENT_CONTEXT_MODES, "context_mode"
            ),
            "workspace_kind": _require_subagent_enum(
                workspace_kind, SUBAGENT_WORKSPACE_KINDS, "workspace_kind"
            ),
            "delegated_scope": delegated_scope,
            "delegated_budget": _validated_delegated_budget(
                delegated_budget, mission, session_id, task_id
            ),
        },
    )
    return json.dumps(_subagent_span_payload(span), ensure_ascii=False, indent=2)


@_runtime_tool
def record_subagent_handoff(
    session_id: str,
    task_id: str,
    child_span_id: str,
    summary: str,
    verified_claims: list[dict[str, Any]],
    receipt_ids: list[str],
    risks: list[str] | None = None,
    unverified_items: list[str] | None = None,
) -> str:
    mission = _require_active_mission(session_id, task_id)
    session_id = mission.session_id
    task_id = mission.task_id
    span = _require_subagent_span(session_id, task_id, child_span_id)
    _require_non_terminal_subagent_span(span)
    if _visible_stripped_length(summary) < 20:
        raise ValueError("summary is too short.")
    receipt_ids = _receipt_id_list(receipt_ids)
    if not receipt_ids:
        raise ValueError("subagent handoff requires at least one receipt_id.")
    _require_unique_receipt_ids(receipt_ids)
    receipts = _get_mission_scope_receipts(receipt_ids, session_id, task_id)
    if len(receipts) != len(set(receipt_ids)):
        raise ValueError(_receipt_scope_error(receipt_ids, session_id, task_id))
    stale_receipts = _receipt_epoch_violations(mission, receipts, "subagent handoff")
    if stale_receipts:
        raise ValueError("; ".join(stale_receipts))
    taskless_ambiguity = _taskless_receipt_ambiguity_violations(
        session_id, task_id, receipts, "subagent handoff"
    )
    if taskless_ambiguity:
        raise ValueError("; ".join(taskless_ambiguity))
    span_violations = _subagent_receipt_span_violations(receipts, child_span_id.strip())
    if span_violations:
        raise ValueError("; ".join(span_violations))
    invalid = [receipt.receipt_id for receipt in receipts if not store.verify_receipt(receipt)]
    if invalid:
        raise ValueError(f"subagent handoff references invalid receipt signature(s): {invalid}")
    handoff = store.record_subagent_handoff(
        child_span_id.strip(),
        session_id,
        task_id,
        {
            "summary": summary.strip(),
            "verified_claims": _verified_claims(verified_claims),
            "receipt_ids": [receipt.receipt_id for receipt in receipts],
            "risks": _string_list(risks),
            "unverified_items": _string_list(unverified_items),
        },
    )
    return json.dumps(_subagent_handoff_payload(handoff), ensure_ascii=False, indent=2)


@_runtime_tool
def register_subagent_stop(
    session_id: str,
    task_id: str,
    child_span_id: str,
    status: str,
    budget_consumed: dict[str, Any] | None = None,
    transcript_ref: str = "",
    artifact_refs: list[str] | None = None,
    last_message: str = "",
) -> str:
    mission = _require_active_mission(session_id, task_id)
    session_id = mission.session_id
    task_id = mission.task_id
    existing = _require_subagent_span(session_id, task_id, child_span_id)
    _require_non_terminal_subagent_span(existing)
    span = store.stop_subagent_span(
        session_id,
        task_id,
        child_span_id.strip(),
        {
            "status": _require_subagent_enum(status, SUBAGENT_STOP_STATUSES, "status"),
            "budget_consumed": _jsonable_dict(budget_consumed or {}, "budget_consumed"),
            "transcript_ref": transcript_ref.strip(),
            "artifact_refs": _string_list(artifact_refs),
            "last_message": last_message.strip(),
        },
    )
    handoffs = store.list_subagent_handoffs(session_id, task_id, span.child_span_id)
    return json.dumps(_subagent_span_payload(span, handoffs), ensure_ascii=False, indent=2)


@_runtime_tool
def subagent_status(session_id: str, task_id: str) -> str:
    session_id = _required_identifier(session_id, "session_id")
    mission = _mission_or_none(session_id, task_id.strip())
    if mission is None:
        return _mission_payload_missing("subagent_status", session_id, task_id.strip())
    spans = store.list_subagent_spans(session_id, mission.task_id)
    handoffs_by_child: dict[str, list[Any]] = {}
    for handoff in store.list_subagent_handoffs(session_id, mission.task_id):
        handoffs_by_child.setdefault(handoff.child_span_id, []).append(handoff)
    payloads = []
    summary = {
        "total": len(spans),
        "running": 0,
        "completed": 0,
        "failed": 0,
        "abandoned": 0,
        "rejected": 0,
    }
    for span in spans:
        handoffs = handoffs_by_child.get(span.child_span_id, [])
        payloads.append(_subagent_span_payload(span, handoffs))
        summary[span.status] = summary.get(span.status, 0) + 1
    return json.dumps(
        {"task_id": mission.task_id, "summary": summary, "child_spans": payloads},
        ensure_ascii=False,
        indent=2,
    )


@_runtime_tool
def verify_receipt_integrity(
    session_id: str, receipt_ids: list[str], task_id: str = ""
) -> str:
    session_id = _required_identifier(session_id, "session_id")
    scoped_task = task_id.strip() or None
    receipt_ids = _receipt_id_list(receipt_ids)
    _require_receipt_ids_present(receipt_ids)
    _require_unique_receipt_ids(receipt_ids)
    if scoped_task is None:
        receipts = store.get_receipts(receipt_ids, session_id=session_id)
    else:
        receipts = _get_mission_scope_receipts(receipt_ids, session_id, scoped_task)
    if not receipts:
        write_debug_log(
            "verify_receipt_integrity.no_receipts",
            {"session_id": session_id, "task_id": scoped_task, "receipt_ids": receipt_ids},
        )
        raise ValueError(_receipt_scope_error(receipt_ids, session_id, scoped_task))
    if len(receipts) != len(set(receipt_ids)):
        raise ValueError(_receipt_scope_error(receipt_ids, session_id, scoped_task))
    results = []
    all_valid = True
    for receipt in receipts:
        valid = store.verify_receipt(receipt)
        all_valid = all_valid and valid
        results.append(
            {
                "receipt_id": receipt.receipt_id,
                "tool_name": receipt.tool_name,
                "task_id": receipt.task_id,
                "valid": valid,
            }
        )
    return json.dumps(
        {"all_valid": all_valid, "results": results}, ensure_ascii=False, indent=2
    )


@_runtime_tool
def record_stuck_attempt(
    session_id: str,
    task_id: str,
    strategy_fingerprint: str,
    summary: str,
    receipt_ids: list[str],
) -> str:
    mission = _require_active_mission(session_id, task_id)
    session_id = mission.session_id
    task_id = mission.task_id
    receipt_ids = _receipt_id_list(receipt_ids)
    _require_receipt_ids_present(receipt_ids)
    _require_unique_receipt_ids(receipt_ids)
    receipts = _get_mission_scope_receipts(receipt_ids, session_id, task_id)
    if len(receipts) != len(set(receipt_ids)):
        raise ValueError(_receipt_scope_error(receipt_ids, session_id, task_id))
    stale_receipts = _receipt_epoch_violations(mission, receipts, "stuck attempt")
    if stale_receipts:
        raise ValueError("; ".join(stale_receipts))
    taskless_ambiguity = _taskless_receipt_ambiguity_violations(
        session_id, task_id, receipts, "stuck attempt"
    )
    if taskless_ambiguity:
        raise ValueError("; ".join(taskless_ambiguity))
    strategy = _required_identifier(strategy_fingerprint, "strategy_fingerprint")
    summary = str(summary or "")
    _reject_invisible_controls("strategy_fingerprint", strategy)
    existing_strategies = {
        attempt.strategy_fingerprint
        for attempt in store.list_stuck_attempts(session_id, task_id)
    }
    if strategy not in existing_strategies and len(existing_strategies) >= mission.retry_budget:
        raise ValueError(
            "retry_budget is exhausted; do not record another distinct stuck strategy "
            f"without refreshing the mission. retry_budget={mission.retry_budget}."
        )
    if not strategy_fingerprint.strip():
        raise ValueError("strategy_fingerprint must not be empty")
    _reject_invisible_controls("summary", summary)
    if not summary.strip():
        raise ValueError("summary must not be empty")

    attempt = store.record_stuck_attempt(
        session_id=session_id,
        task_id=task_id,
        strategy_fingerprint=strategy,
        summary=summary.strip(),
        receipt_ids=[r.receipt_id for r in receipts],
    )
    attempts = store.list_stuck_attempts(session_id, task_id)
    remaining = max(
        mission.retry_budget - len({a.strategy_fingerprint for a in attempts}), 0
    )
    return (
        "STUCK ATTEMPT RECORDED\n"
        f"attempt_id: {attempt.attempt_id}\n"
        f"distinct_strategies_seen: {len({a.strategy_fingerprint for a in attempts})}\n"
        f"retry_budget_remaining: {remaining}"
    )


@_runtime_tool
def record_decision_record(
    session_id: str,
    task_id: str,
    title: str,
    choice_made: str,
    alternatives_rejected: list[str],
    evidence_receipt_ids: list[str],
    reversibility: str = "reversible",
    reopen_triggers: list[str] | None = None,
) -> str:
    mission = _require_active_mission(session_id, task_id)
    session_id = mission.session_id
    task_id = mission.task_id
    evidence_receipt_ids = _receipt_id_list(evidence_receipt_ids, "evidence_receipt_ids")
    _require_receipt_ids_present(evidence_receipt_ids, "evidence_receipt_ids")
    _require_unique_receipt_ids(evidence_receipt_ids, "evidence_receipt_ids")
    receipts = _get_mission_scope_receipts(evidence_receipt_ids, session_id, task_id)
    if len(receipts) != len(set(evidence_receipt_ids)):
        raise ValueError(_receipt_scope_error(evidence_receipt_ids, session_id, task_id))
    stale_receipts = _receipt_epoch_violations(mission, receipts, "decision record")
    if stale_receipts:
        raise ValueError("; ".join(stale_receipts))
    taskless_ambiguity = _taskless_receipt_ambiguity_violations(
        session_id, task_id, receipts, "decision record"
    )
    if taskless_ambiguity:
        raise ValueError("; ".join(taskless_ambiguity))
    if not title.strip() or not choice_made.strip():
        raise ValueError("title and choice_made must not be empty")
    if not _has_substantive_governance_text(title) or not _has_substantive_governance_text(
        choice_made
    ):
        raise ValueError("decision record requires specific title and choice_made text.")
    if not _string_list(alternatives_rejected):
        raise ValueError("decision record requires at least one specific alternative.")
    if any(
        not _has_substantive_governance_list_item(item)
        for item in _string_list(alternatives_rejected)
    ):
        raise ValueError("decision record alternatives_rejected entries must be specific.")
    if reopen_triggers is not None and any(
        not _has_substantive_governance_list_item(item)
        for item in _string_list(reopen_triggers)
    ):
        raise ValueError("decision record reopen_triggers entries must be specific.")
    record = store.record_decision_record(
        session_id=session_id,
        task_id=task_id,
        title=title.strip(),
        choice_made=choice_made.strip(),
        alternatives_rejected=_string_list(alternatives_rejected),
        evidence_receipt_ids=[r.receipt_id for r in receipts],
        reversibility=reversibility.strip() or "reversible",
        reopen_triggers=_string_list(reopen_triggers),
    )
    return (
        "DECISION RECORDED\n"
        f"decision_id: {record.decision_id}\n"
        f"title: {record.title}\n"
        f"reversibility: {record.reversibility}"
    )


@_runtime_tool
def record_counterexample_check(
    session_id: str,
    task_id: str,
    hypothesis: str,
    attempted_disconfirmers: list[str],
    outcome: str,
    receipt_ids: list[str],
    surviving_risk: str = "",
) -> str:
    mission = _require_active_mission(session_id, task_id)
    session_id = mission.session_id
    task_id = mission.task_id
    receipt_ids = _receipt_id_list(receipt_ids)
    _require_receipt_ids_present(receipt_ids)
    _require_unique_receipt_ids(receipt_ids)
    receipts = _get_mission_scope_receipts(receipt_ids, session_id, task_id)
    if len(receipts) != len(set(receipt_ids)):
        raise ValueError(_receipt_scope_error(receipt_ids, session_id, task_id))
    stale_receipts = _receipt_epoch_violations(mission, receipts, "counterexample check")
    if stale_receipts:
        raise ValueError("; ".join(stale_receipts))
    taskless_ambiguity = _taskless_receipt_ambiguity_violations(
        session_id, task_id, receipts, "counterexample check"
    )
    if taskless_ambiguity:
        raise ValueError("; ".join(taskless_ambiguity))
    if not hypothesis.strip():
        raise ValueError("hypothesis must not be empty")
    if not _has_substantive_governance_text(hypothesis):
        raise ValueError("counterexample check requires a specific hypothesis.")
    attempted = _string_list(attempted_disconfirmers)
    if not attempted:
        raise ValueError("Provide at least one attempted disconfirmer.")
    if any(not _has_substantive_governance_list_item(item) for item in attempted):
        raise ValueError("counterexample check attempted_disconfirmers must be specific.")
    if not outcome.strip():
        raise ValueError("outcome must not be empty")
    if not _has_substantive_governance_text(outcome):
        raise ValueError("counterexample check requires a specific outcome.")
    check = store.record_counterexample_check(
        session_id=session_id,
        task_id=task_id,
        hypothesis=hypothesis.strip(),
        attempted_disconfirmers=attempted,
        outcome=outcome.strip(),
        receipt_ids=[r.receipt_id for r in receipts],
        surviving_risk=surviving_risk.strip(),
    )
    return (
        "COUNTEREXAMPLE CHECK RECORDED\n"
        f"check_id: {check.check_id}\n"
        f"hypothesis: {check.hypothesis}\n"
        f"surviving_risk: {check.surviving_risk or 'none stated'}"
    )


@_runtime_tool
def turn_end_gate(
    session_id: str,
    task_id: str,
    stop_condition: str,
    work_summary: str,
    receipt_ids: list[str],
    pending_actions_identified: list[str] | None = None,
    reason_for_stopping: str = "",
    assumptions_remaining: list[str] | None = None,
    known_risks: list[str] | None = None,
    unverified_items: list[str] | None = None,
) -> str:
    mission = _require_active_mission(session_id, task_id)
    session_id = mission.session_id
    task_id = mission.task_id
    stop_condition = stop_condition.strip()
    if stop_condition not in LEGAL_STOP_CONDITIONS:
        raise ValueError(
            f"stop_condition must be one of: {sorted(LEGAL_STOP_CONDITIONS)}"
        )
    if _visible_stripped_length(work_summary) < 20:
        raise ValueError(
            "work_summary is too short. Describe what actually changed, tested, or ruled out."
        )

    receipt_ids = _receipt_id_list(receipt_ids)
    _require_receipt_ids_present(receipt_ids)
    _require_unique_receipt_ids(receipt_ids)
    receipts = _get_mission_scope_receipts(receipt_ids, session_id, task_id)
    if not receipts:
        write_debug_log(
            "turn_end_gate.no_receipts",
            {"session_id": session_id, "task_id": task_id, "receipt_ids": receipt_ids},
        )
        raise ValueError(_receipt_scope_error(receipt_ids, session_id, task_id))
    if len(receipts) != len(set(receipt_ids)):
        raise ValueError(_receipt_scope_error(receipt_ids, session_id, task_id))

    pending = _string_list(pending_actions_identified)
    assumptions = _string_list(assumptions_remaining)
    risks = _string_list(known_risks)
    unverified = _string_list(unverified_items)
    violations: list[str] = []
    violations.extend(_invisible_control_violations("work_summary", work_summary))
    violations.extend(
        _invisible_control_violations("reason_for_stopping", reason_for_stopping)
    )
    violations.extend(
        _invisible_control_list_violations("pending_actions_identified", pending)
    )
    violations.extend(
        _invisible_control_list_violations("assumptions_remaining", assumptions)
    )
    violations.extend(_invisible_control_list_violations("known_risks", risks))
    violations.extend(_invisible_control_list_violations("unverified_items", unverified))
    warnings = _fresh_receipt_warning(receipts)
    budget = _budget_snapshot(session_id, task_id, mission)
    violations.extend(_receipt_epoch_violations(mission, receipts, "turn_end_gate"))
    violations.extend(
        _taskless_receipt_ambiguity_violations(
            session_id, task_id, receipts, "turn_end_gate"
        )
    )
    violations.extend(_taskless_future_timestamp_violations(receipts, "turn_end_gate"))
    if mission.slice_count >= mission.slice_budget and stop_condition == "slice_verified":
        violations.append(
            "slice_budget is exhausted; refresh the mission or stop legally instead of claiming another verified slice."
        )
    if (
        budget["time_budget_minutes"]
        and budget["time_remaining_minutes"] == 0
        and stop_condition == "slice_verified"
    ):
        violations.append(
            "time budget is exhausted; refresh the mission, complete the task, or stop legally instead of claiming another verified slice."
        )

    if stop_condition == "frontier_exhausted" and mission.slice_count < 1:
        violations.append(
            "frontier_exhausted requires at least one previously verified slice before claiming no local frontier remains."
        )

    if stop_condition in {"slice_verified", "frontier_exhausted"}:
        subagent_spans = store.list_subagent_spans(session_id, task_id)
        handoffs_by_child: dict[str, list[Any]] = {}
        for handoff in store.list_subagent_handoffs(session_id, task_id):
            handoffs_by_child.setdefault(handoff.child_span_id, []).append(handoff)

        violations.extend(
            _child_receipt_readiness_violations(
                receipts, session_id, task_id, handoffs_by_child
            )
        )
        violations.extend(_open_child_span_violations(subagent_spans))
        violations.extend(_failed_child_span_violations(subagent_spans, risks, unverified))
        violations.extend(_child_budget_overrun_violations(subagent_spans, risks, unverified))
        violations.extend(
            _missing_child_handoff_disclosures(
                subagent_spans, handoffs_by_child, risks, unverified
            )
        )

    notes = mission.notes or {}
    if notes.get("adversarial_audit_required"):
        audit_budget = notes.get("adversarial_audit_budget") or {}
        audit_records = notes.get("adversarial_audit_records") or []
        if isinstance(audit_budget, dict) and isinstance(audit_records, list) and audit_budget:
            audit_usage = budget_usage(audit_records, audit_budget)
            audit_gate = audit_stop_gate(audit_usage, audit_budget, stop_condition)
            if not audit_gate["allowed"]:
                violations.append(
                    f"adversarial audit budget is exhausted; {audit_gate['reason']}"
                )

    if _has_assertion_language(work_summary):
        violations.append(
            "work_summary relies on assertion language instead of concrete action language."
        )

    if stop_condition in {"slice_verified", "frontier_exhausted"} and pending:
        violations.append(
            "pending_actions_identified must be empty when claiming the slice is verified or the frontier is exhausted."
        )
    if stop_condition in {"slice_verified", "frontier_exhausted"}:
        violations.extend(
            _pending_local_work_conflict_violations(
                "the slice/frontier is done",
                {
                    "work_summary": work_summary,
                    "reason_for_stopping": reason_for_stopping,
                    "assumptions_remaining": assumptions,
                    "known_risks": risks,
                    "unverified_items": unverified,
                },
            )
        )

    if (
        stop_condition in SOFT_STOP_CONDITIONS
        and _visible_stripped_length(reason_for_stopping) == 0
    ):
        violations.append(f"{stop_condition} requires a precise reason_for_stopping.")

    if stop_condition == "interpretation_deadlock" and (
        _visible_stripped_length(reason_for_stopping) < 30
        or not _has_substantive_interpretation_reason(reason_for_stopping)
    ):
        violations.append(
            "interpretation_deadlock requires a concrete explanation of the unresolved interpretations."
        )

    soft_stop_count = int((mission.notes or {}).get("soft_stop_count", 0))
    deadlock_count = int((mission.notes or {}).get("interpretation_deadlock_count", 0))
    if stop_condition in SOFT_STOP_CONDITIONS and soft_stop_count >= REPEATED_STOP_LIMIT:
        violations.append(
            f"{stop_condition} has been used too many times without real progress; stop looping and either make progress or escalate."
        )
    if stop_condition == "interpretation_deadlock" and deadlock_count >= REPEATED_STOP_LIMIT:
        violations.append(
            "interpretation_deadlock has been used too many times without real progress; stop looping and either make progress or use stuck_escalation."
        )

    if stop_condition == "stuck_escalation":
        attempts = store.list_stuck_attempts(session_id, task_id)
        distinct = {a.strategy_fingerprint for a in attempts}
        if len(distinct) < mission.retry_budget:
            violations.append(
                f"stuck_escalation requires at least {mission.retry_budget} materially different recorded attempts; found {len(distinct)}."
            )
        if _visible_stripped_length(reason_for_stopping) < 30:
            violations.append(
                "stuck_escalation requires a precise explanation of why further local retries are no longer justified."
            )
        if notes.get("counterexample_required") and not store.list_counterexample_checks(
            session_id, task_id
        ):
            violations.append(
                "stuck_escalation requires a recorded counterexample check when the mission requires counterexample evidence."
            )
        if notes.get("decision_records_required") and not store.list_decision_records(
            session_id, task_id
        ):
            violations.append(
                "stuck_escalation requires a recorded decision record when the mission requires decision-record evidence."
            )
        latest_receipt_seq = _latest_mission_receipt_seq(session_id, task_id, mission)
        violations.extend(_adversarial_audit_violations(mission, latest_receipt_seq))

    after_receipt_seq = max(
        max(r.seq for r in receipts),
        store.latest_receipt_seq(session_id),
    )
    if violations:
        approval = store.create_approval(
            session_id=session_id,
            task_id=task_id,
            gate_type="turn_end_gate",
            approved=False,
            reason="; ".join(violations),
            after_receipt_seq=after_receipt_seq,
            ttl_seconds=60,
            meta={"warnings": warnings, "stop_condition": stop_condition},
        )
        lines = ["REJECTED", *[f"- {item}" for item in violations]]
        if warnings:
            lines.append("warnings:")
            lines.extend(f"- {item}" for item in warnings)
        if budget["budget_exhausted"]:
            lines.append(f"wrap_up_guidance: {budget['wrap_up_guidance']}")
        lines.append(f"rejection_token: {approval.token}")
        return "\n".join(lines)

    if stop_condition == "slice_verified":
        mission = store.increment_slice(session_id, task_id)
        if (soft_stop_count or deadlock_count) and _receipts_show_non_observational_progress(receipts):
            notes = dict(mission.notes or {})
            if soft_stop_count:
                notes["soft_stop_count"] = 0
            if deadlock_count:
                notes["interpretation_deadlock_count"] = 0
            mission = store.update_mission_notes(session_id, task_id, notes)
    if stop_condition in SOFT_STOP_CONDITIONS:
        notes = dict(mission.notes or {})
        notes["soft_stop_count"] = soft_stop_count + 1
        mission = store.update_mission_notes(session_id, task_id, notes)
    if stop_condition == "interpretation_deadlock":
        notes = dict(mission.notes or {})
        notes["interpretation_deadlock_count"] = deadlock_count + 1
        mission = store.update_mission_notes(session_id, task_id, notes)
    approval = store.create_approval(
        session_id=session_id,
        task_id=task_id,
        gate_type="turn_end_gate",
        approved=True,
        reason=stop_condition,
        after_receipt_seq=after_receipt_seq,
        ttl_seconds=900,
        meta={
            "warnings": warnings,
            "assumptions_remaining": assumptions,
            "known_risks": risks,
            "unverified_items": unverified,
            "stop_condition": stop_condition,
            "pending_actions_identified": pending,
            "receipt_ids": [r.receipt_id for r in receipts],
            "latest_stuck_attempt_id": store.latest_stuck_attempt_id(session_id, task_id),
            "mission_active_after_gate": mission.status == "active",
            "slice_count": mission.slice_count,
        },
    )

    lines = [
        "APPROVED",
        f"approval_token: {approval.token}",
        f"stop_condition: {stop_condition}",
        f"slice_count: {mission.slice_count}/{mission.slice_budget}",
        f"receipts: {', '.join(r.receipt_id for r in receipts)}",
    ]
    if stop_condition == "slice_verified" and mission.slice_count > 0 and mission.slice_count % 3 == 0:
        lines.append("goal_alignment_check_due: yes")
    if stop_condition == "slice_verified" and mission.status == "active":
        lines.append("mission_active: continue remaining local work; do not claim final completion without completion_gate")
    if assumptions:
        lines.append(
            f"assumptions_remaining: {json.dumps(assumptions, ensure_ascii=False)}"
        )
    if risks:
        lines.append(f"known_risks: {json.dumps(risks, ensure_ascii=False)}")
    if unverified:
        lines.append(f"unverified_items: {json.dumps(unverified, ensure_ascii=False)}")
    lines.append(f"time_pressure: {budget['time_pressure']}")
    if warnings:
        lines.append(f"warnings: {json.dumps(warnings, ensure_ascii=False)}")
    return "\n".join(lines)


def _completion_gate_arguments(
    completion_summary: str,
    criterion_receipt_map: list[dict[str, Any]] | None,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    if isinstance(completion_summary, list) and isinstance(criterion_receipt_map, str):
        completion_summary, criterion_receipt_map = criterion_receipt_map, completion_summary
    if not isinstance(completion_summary, str):
        raise ValueError("completion_summary must be a string.")
    if criterion_receipt_map is None:
        return completion_summary, [], [
            "criterion_receipt_map is required; every completion criterion must map to one or more receipt_id values."
        ]
    if not isinstance(criterion_receipt_map, list):
        raise ValueError("criterion_receipt_map must be a list of criterion mapping objects.")
    return completion_summary, criterion_receipt_map, []


def _disclosure_text_contains(text: str, required: str) -> bool:
    required_identity = _constraint_disclosure_identity(required)
    if not required_identity:
        return False
    text_identity = _constraint_disclosure_identity(text)
    if re.fullmatch(r"[a-z0-9_]+", required_identity):
        return re.search(
            rf"(?<!\w){re.escape(required_identity)}(?!\w)", text_identity
        ) is not None
    return required_identity in text_identity


def _constraint_disclosure_identity(value: str) -> str:
    visible = strip_invisible_controls(value)
    folded = unicodedata.normalize("NFKD", visible)
    without_marks = "".join(char for char in folded if not unicodedata.combining(char))
    comparable = "".join(
        " " if unicodedata.category(char)[0] in {"P", "S"} else char
        for char in without_marks
    )
    return re.sub(r"\s+", " ", comparable).strip().casefold()


def _mission_boundary_disclosure_violations(mission: Any, completion_summary: str) -> list[str]:
    violations: list[str] = []
    if mission.scope_boundary and not _disclosure_text_contains(
        completion_summary, mission.scope_boundary
    ):
        violations.append(
            "completion_summary must explicitly disclose the mission scope_boundary before completion."
        )

    missing_red_lines = [
        item
        for item in mission.red_lines
        if not _disclosure_text_contains(completion_summary, item)
    ]
    if missing_red_lines:
        violations.append(
            f"completion_summary must explicitly disclose mission red_lines before completion: {missing_red_lines}"
        )
    return violations


def _completion_turn_gate_violations(
    session_id: str, task_id: str, receipt_ids: list[str]
) -> list[str]:
    latest_turn = store.latest_approval(session_id, task_id, gate_type="turn_end_gate")
    if latest_turn is None:
        return [
            "completion_gate requires a fresh approved turn_end_gate before completion."
        ]
    latest_turn_meta = latest_turn.meta or {}
    try:
        turn_stuck_attempt_id = int(latest_turn_meta.get("latest_stuck_attempt_id") or 0)
    except (TypeError, ValueError):
        turn_stuck_attempt_id = 0
    if turn_stuck_attempt_id < store.latest_stuck_attempt_id(session_id, task_id):
        return [
            "completion_gate requires a new verified slice after the latest stuck attempt."
        ]
    if not store.is_approval_fresh(latest_turn, session_id, task_id):
        return [
            "completion_gate requires a fresh approved turn_end_gate before completion."
        ]
    if not latest_turn.approved:
        return [
            "completion_gate requires a fresh approved turn_end_gate before completion."
        ]
    stop_condition = latest_turn_meta.get("stop_condition", "")
    if stop_condition not in {"slice_verified", "frontier_exhausted"}:
        return [
            "latest turn_end_gate stop_condition must be slice_verified or "
            f"frontier_exhausted before completion; got {stop_condition!r}."
        ]
    turn_receipt_ids = set(_receipt_id_list(latest_turn_meta.get("receipt_ids", [])))
    if not turn_receipt_ids:
        return ["latest turn_end_gate must declare the receipt_ids it verified before completion."]
    missing = [receipt_id for receipt_id in receipt_ids if receipt_id not in turn_receipt_ids]
    if missing:
        return [
            "completion_gate receipt_ids must be covered by the latest approved turn_end_gate; "
            f"missing from turn gate: {missing}"
        ]
    return []


@_runtime_tool
def completion_gate(
    session_id: str,
    task_id: str,
    completion_summary: str,
    criterion_receipt_map: list[dict[str, Any]] | None = None,
    unverified_items: list[str] | None = None,
    known_risks: list[str] | None = None,
) -> str:
    mission = _require_active_mission(session_id, task_id)
    session_id = mission.session_id
    task_id = mission.task_id
    completion_summary, criterion_receipt_map, violations = _completion_gate_arguments(
        completion_summary, criterion_receipt_map
    )
    if _visible_stripped_length(completion_summary) < 20:
        raise ValueError("completion_summary is too short.")
    violations.extend(
        _invisible_control_violations("completion_summary", completion_summary)
    )
    completion_known_risks = _string_list(known_risks)
    completion_unverified_items = _string_list(unverified_items)
    violations.extend(
        _invisible_control_list_violations("known_risks", completion_known_risks)
    )
    violations.extend(
        _invisible_control_list_violations(
            "unverified_items", completion_unverified_items
        )
    )

    provided_receipt_ids: list[str] = []
    mapping_by_criterion: dict[str, list[str]] = {}
    for entry in criterion_receipt_map:
        if not isinstance(entry, dict):
            raise ValueError("criterion_receipt_map entries must be objects.")
        criterion = str(entry.get("criterion", "")).strip()
        ids = _receipt_id_list(entry.get("receipt_ids", []))
        if not criterion or not ids:
            raise ValueError(
                "Each criterion_receipt_map entry must include criterion and receipt_ids."
            )
        if criterion in mapping_by_criterion:
            raise ValueError(f"duplicate criterion mapping is not allowed: {criterion!r}")
        _require_unique_receipt_ids(ids, f"criterion {criterion!r} receipt_ids")
        _reject_subagent_handoff_receipt_ids(ids)
        mapping_by_criterion[criterion] = ids
        provided_receipt_ids.extend(ids)

    if len(provided_receipt_ids) != len(set(provided_receipt_ids)):
        raise ValueError("receipt_ids may not be reused across multiple criteria.")
    violations.extend(_completion_turn_gate_violations(session_id, task_id, provided_receipt_ids))

    criteria = mission.completion_criteria
    missing = [
        criterion for criterion in criteria if criterion not in mapping_by_criterion
    ]
    extra = [
        criterion for criterion in mapping_by_criterion if criterion not in criteria
    ]

    receipts = _get_mission_scope_receipts(provided_receipt_ids, session_id, task_id)
    warnings = _fresh_receipt_warning(receipts)
    if len(receipts) != len(set(provided_receipt_ids)):
        write_debug_log(
            "completion_gate.missing_receipts",
            {"session_id": session_id, "task_id": task_id, "receipt_ids": provided_receipt_ids},
        )
        raise ValueError(_receipt_scope_error(provided_receipt_ids, session_id, task_id))
    receipt_map = {receipt.receipt_id: receipt for receipt in receipts}

    if missing:
        violations.append(f"Missing criterion mappings: {missing}")
    if extra:
        violations.append(f"Unknown criterion mappings: {extra}")
    subagent_spans = store.list_subagent_spans(session_id, task_id)
    known_child_span_ids = {span.child_span_id for span in subagent_spans}
    handoffs_by_child: dict[str, list[Any]] = {}
    if subagent_spans:
        for handoff in store.list_subagent_handoffs(session_id, task_id):
            handoffs_by_child.setdefault(handoff.child_span_id, []).append(handoff)
    violations.extend(_receipt_epoch_violations(mission, receipts, "completion_gate"))
    violations.extend(
        _taskless_receipt_ambiguity_violations(
            session_id, task_id, receipts, "completion_gate"
        )
    )
    violations.extend(_taskless_future_timestamp_violations(receipts, "completion_gate"))
    violations.extend(
        _child_receipt_readiness_violations(
            receipts, session_id, task_id, handoffs_by_child
        )
    )
    violations.extend(_open_child_span_violations(subagent_spans))
    violations.extend(
        _failed_child_span_violations(
            subagent_spans, completion_known_risks, completion_unverified_items
        )
    )
    violations.extend(
        _child_budget_overrun_violations(
            subagent_spans, completion_known_risks, completion_unverified_items
        )
    )
    violations.extend(
        _missing_child_handoff_disclosures(
            subagent_spans,
            handoffs_by_child,
            completion_known_risks,
            completion_unverified_items,
        )
    )

    for criterion, ids in mapping_by_criterion.items():
        criterion_receipts: list[Any] = []
        for rid in ids:
            receipt = receipt_map.get(rid)
            if receipt is None:
                violations.append(
                    f"criterion {criterion!r} references unknown receipt_id {rid!r}"
                )
                continue
            criterion_receipts.append(receipt)
            if not store.verify_receipt(receipt):
                violations.append(
                    f"criterion {criterion!r} references invalid receipt signature {rid!r}"
                )
            if receipt.tool_name in EXECUTION_TOOLS and receipt.exit_code != 0:
                violations.append(
                    f"criterion {criterion!r} references failed execution receipt {rid!r} (tool={receipt.tool_name}, exit={receipt.exit_code})"
                )
        if criterion_receipts and not _criterion_has_semantic_support(
            criterion, criterion_receipts
        ):
            violations.append(
                f"criterion {criterion!r} has semantic mismatch: supplied receipts do not provide the required execution evidence."
            )
        violations.extend(
            _child_reverification_violations(
                [
                    receipt
                    for receipt in criterion_receipts
                    if _receipt_can_enter_child_reverification(receipt, known_child_span_ids)
                ],
                session_id,
                task_id,
                criterion,
            )
        )

    # Stale-evidence guard only applies to criteria that semantically require
    # execution. Pure mutation criteria such as writing or slide updates should
    # not be forced to supply a post-edit execution receipt.
    latest_mutation_seq = _latest_mission_mutation_seq(session_id, task_id, mission)
    if latest_mutation_seq > 0:
        for criterion, ids in mapping_by_criterion.items():
            if not _criterion_requires_execution_receipt(criterion):
                continue
            criterion_receipts = [receipt_map[rid] for rid in ids if rid in receipt_map]
            if not criterion_receipts:
                continue
            fresh_verification_seq = max(
                (
                    r.seq
                    for r in criterion_receipts
                    if r.tool_name in EXECUTION_TOOLS and r.seq >= latest_mutation_seq
                ),
                default=0,
            )
            if fresh_verification_seq == 0:
                violations.append(
                    f"criterion {criterion!r} has stale evidence: no verification receipt "
                    f"exists at or after the last mutation seq={latest_mutation_seq}; re-verify after edits."
                )

    if _has_assertion_language(completion_summary):
        violations.append(
            "completion_summary relies on assertion language instead of verified results."
        )
    violations.extend(
        _pending_local_work_conflict_violations(
            "task completion",
            {
                "completion_summary": completion_summary,
                "known_risks": completion_known_risks,
                "unverified_items": completion_unverified_items,
            },
        )
    )
    violations.extend(_mission_boundary_disclosure_violations(mission, completion_summary))

    notes = mission.notes or {}
    if notes.get("counterexample_required") and not store.list_counterexample_checks(
        session_id, task_id
    ):
        violations.append(
            "Mission requires at least one recorded counterexample check before completion."
        )
    if notes.get("decision_records_required") and not store.list_decision_records(
        session_id, task_id
    ):
        violations.append(
            "Mission requires at least one recorded decision record before completion."
        )

    latest_receipt_seq = _latest_mission_receipt_seq(session_id, task_id, mission)
    violations.extend(_adversarial_audit_violations(mission, latest_receipt_seq))

    after_receipt_seq = max(
        max((receipt.seq for receipt in receipts), default=latest_receipt_seq),
        store.latest_receipt_seq(session_id),
    )

    if violations:
        approval = store.create_approval(
            session_id=session_id,
            task_id=task_id,
            gate_type="completion_gate",
            approved=False,
            reason="; ".join(violations),
            after_receipt_seq=after_receipt_seq,
            ttl_seconds=60,
            meta={
                "completion_summary": completion_summary,
                "criterion_receipt_map": criterion_receipt_map,
                "warnings": warnings,
            },
        )
        lines = [
            "REJECTED",
            *[f"- {item}" for item in violations],
            f"rejection_token: {approval.token}",
        ]
        if warnings:
            lines.append("warnings:")
            lines.extend(f"- {item}" for item in warnings)
        return "\n".join(lines)

    completion_notes = dict(notes)
    completion_notes.update(
        {
            "completion_summary": completion_summary.strip(),
            "unverified_items": completion_unverified_items,
            "known_risks": completion_known_risks,
            "criterion_receipt_map": criterion_receipt_map,
        }
    )
    mission = store.mark_completed(session_id, task_id, notes=completion_notes)
    approval = store.create_approval(
        session_id=session_id,
        task_id=task_id,
        gate_type="completion_gate",
        approved=True,
        reason="criteria satisfied",
        after_receipt_seq=after_receipt_seq,
        ttl_seconds=1800,
        meta={"criterion_receipt_map": criterion_receipt_map, "warnings": warnings},
    )
    lines = [
        "APPROVED",
        f"approval_token: {approval.token}",
        f"task_id: {mission.task_id}",
        f"status: {mission.status}",
        f"receipts_used: {len(receipts)}",
    ]
    remaining_active = store.list_active_missions(session_id)
    if remaining_active:
        task_ids = [item.task_id for item in remaining_active]
        lines.append(f"active_missions_remaining: {len(remaining_active)}")
        lines.append(f"remaining_active_task_ids: {json.dumps(task_ids, ensure_ascii=False)}")
        lines.append("next_action_required: continue remaining active mission(s)")
        lines.append(f"next_active_task_id: {task_ids[0]}")
    if completion_unverified_items:
        lines.append(
            f"unverified_items: {json.dumps(completion_unverified_items, ensure_ascii=False)}"
        )
    if completion_known_risks:
        lines.append(
            f"known_risks: {json.dumps(completion_known_risks, ensure_ascii=False)}"
        )
    if warnings:
        lines.append(f"warnings: {json.dumps(warnings, ensure_ascii=False)}")
    lines.append("Completion gate approved for this task.")
    return "\n".join(lines)


@_runtime_tool
def export_handoff_packet(session_id: str, task_id: str) -> str:
    session_id = _required_identifier(session_id, "session_id")
    task_scope = task_id.strip()
    mission = _mission_or_none(session_id, task_scope)
    if mission is None:
        return _mission_payload_missing("export_handoff_packet", session_id, task_scope)
    task_scope = mission.task_id
    recent_receipts = _mission_scope_recent_receipts(session_id, task_scope, mission, 5)
    decisions = store.list_decision_records(session_id, task_scope)
    counterexamples = store.list_counterexample_checks(session_id, task_scope)
    latest_turn = store.latest_approval(session_id, task_scope, gate_type="turn_end_gate")
    latest_completion = store.latest_approval(
        session_id, task_scope, gate_type="completion_gate"
    )
    latest_authorization = store.latest_approval(
        session_id, task_scope, gate_type="user_authorization"
    )
    budget_status = _budget_snapshot(session_id, task_scope, mission)
    payload = {
        "schema_version": "1.0",
        "mission": _handoff_mission_payload(mission),
        "budget_status": budget_status,
        "latest_receipts": [_handoff_receipt_payload(receipt) for receipt in recent_receipts],
        "decision_records": [_handoff_decision_payload(record) for record in decisions],
        "counterexample_checks": [_handoff_counterexample_payload(check) for check in counterexamples],
        "latest_turn_gate": _handoff_gate_payload(latest_turn, session_id, task_scope),
        "latest_completion_gate": _handoff_gate_payload(latest_completion, session_id, task_scope),
        "latest_user_authorization": _authorization_payload(
            session_id, task_scope, latest_authorization
        ),
        "adversarial_audit_status": _adversarial_audit_status(
            mission, _latest_mission_receipt_seq(mission.session_id, mission.task_id, mission)
        ),
        "criterion_coverage": (mission.notes or {}).get("criterion_receipt_map", []),
        "known_risks": (mission.notes or {}).get("known_risks", []),
        "unverified_items": (mission.notes or {}).get("unverified_items", []),
        "recommended_next_action": budget_status["wrap_up_guidance"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _handoff_mission_payload(mission: Any) -> dict[str, Any]:
    return {
        "session_id": mission.session_id,
        "task_id": mission.task_id,
        "goal": mission.goal,
        "status": mission.status,
        "completion_criteria": mission.completion_criteria,
        "scope_boundary": mission.scope_boundary,
        "red_lines": mission.red_lines,
        "notes": mission.notes,
        "mission_start_receipt_seq": _mission_start_receipt_seq(mission),
    }


def _handoff_receipt_payload(receipt: Any) -> dict[str, Any]:
    return {
        "receipt_id": receipt.receipt_id,
        "tool_name": receipt.tool_name,
        "command_text": receipt.command_text,
        "exit_code": receipt.exit_code,
        "seq": receipt.seq,
    }


def _handoff_decision_payload(record: Any) -> dict[str, Any]:
    return {
        "decision_id": record.decision_id,
        "title": record.title,
        "choice_made": record.choice_made,
        "alternatives_rejected": record.alternatives_rejected,
        "reversibility": record.reversibility,
        "reopen_triggers": record.reopen_triggers,
    }


def _handoff_counterexample_payload(check: Any) -> dict[str, Any]:
    return {
        "check_id": check.check_id,
        "hypothesis": check.hypothesis,
        "attempted_disconfirmers": check.attempted_disconfirmers,
        "outcome": check.outcome,
        "surviving_risk": check.surviving_risk,
    }


def _handoff_gate_payload(approval: Any | None, session_id: str, task_id: str) -> dict[str, Any] | None:
    if approval is None:
        return None
    return {
        "token": approval.token,
        "approved": approval.approved,
        "reason": approval.reason,
        "fresh": store.is_approval_fresh(approval, session_id, task_id),
        "meta": approval.meta,
    }
@_runtime_tool
def mission_status(session_id: str, task_id: str = "") -> str:
    session_id = _required_identifier(session_id, "session_id")
    task_scope = task_id.strip()
    mission = _mission_or_none(session_id, task_scope)
    if mission is None:
        if not task_scope:
            active_missions = store.list_active_missions(session_id)
            if len(active_missions) > 1:
                write_debug_log(
                    "runtime_tool.validation_error",
                    {
                        "tool_name": "mission_status",
                        "error": "ambiguous_active_missions",
                        "session_id": session_id,
                        "task_id": task_scope,
                        "active_task_ids": [mission.task_id for mission in active_missions],
                    },
                )
                return json.dumps(
                    {
                        "error": "Multiple active missions; specify task_id.",
                        "candidate_missions": [
                            _mission_intake_payload(active_mission)
                            for active_mission in active_missions
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
        return _mission_payload_missing("mission_status", session_id, task_scope)
    latest_turn = store.latest_approval(
        mission.session_id, mission.task_id, gate_type="turn_end_gate"
    )
    latest_completion = store.latest_approval(
        mission.session_id, mission.task_id, gate_type="completion_gate"
    )
    latest_authorization = store.latest_approval(
        mission.session_id, mission.task_id, gate_type="user_authorization"
    )
    last_receipt_seq = _latest_mission_receipt_seq(mission.session_id, mission.task_id, mission)
    attempts = store.list_stuck_attempts(mission.session_id, mission.task_id)
    distinct_attempts = len({attempt.strategy_fingerprint for attempt in attempts})
    decision_count = len(
        store.list_decision_records(mission.session_id, mission.task_id)
    )
    counterexample_count = len(
        store.list_counterexample_checks(mission.session_id, mission.task_id)
    )
    notes = mission.notes or {}
    budget = _budget_snapshot(mission.session_id, mission.task_id, mission)
    lines = [
        f"status: {mission.status}",
        f"session_id: {mission.session_id}",
        f"task_id: {mission.task_id}",
        f"goal: {mission.goal}",
        f"slice_count: {mission.slice_count}/{mission.slice_budget}",
        f"retry_usage: {distinct_attempts}/{mission.retry_budget}",
        f"last_receipt_seq: {last_receipt_seq}",
        f"mission_start_receipt_seq: {_mission_start_receipt_seq(mission)}",
        f"decision_records: {decision_count}",
        f"counterexample_checks: {counterexample_count}",
    ]
    if mission.scope_boundary:
        lines.append(f"scope_boundary: {mission.scope_boundary}")
    lines.append("completion_criteria:")
    for index, criterion in enumerate(mission.completion_criteria, start=1):
        lines.append(f"  {index}. {criterion}")
    if mission.red_lines:
        lines.append("red_lines:")
        for index, item in enumerate(mission.red_lines, start=1):
            lines.append(f"  {index}. {item}")
    if notes.get("degradation_mode"):
        lines.append(f"degradation_mode: {notes['degradation_mode']}")
    if notes.get("time_budget_minutes"):
        lines.append(f"time_budget_minutes: {notes['time_budget_minutes']}")
    if notes.get("risk_budget"):
        lines.append(f"risk_budget: {notes['risk_budget']}")
    if notes.get("counterexample_required"):
        lines.append("counterexample_required: yes")
    if notes.get("decision_records_required"):
        lines.append("decision_records_required: yes")
    if notes.get("adversarial_audit_required"):
        audit_status = _adversarial_audit_status(mission, last_receipt_seq)
        lines.append(f"adversarial_audit_required: yes")
        lines.append(f"adversarial_audit_records: {audit_status['record_count']}")
        lines.append(f"adversarial_audit_passed: {audit_status['passed']}")
        if audit_status["violations"]:
            lines.append(f"adversarial_audit_violations: {json.dumps(audit_status['violations'], ensure_ascii=False)}")
    lines.append(f"time_remaining_minutes: {budget['time_remaining_minutes']}")
    lines.append(f"slices_remaining: {budget['slices_remaining']}")
    lines.append(f"retries_remaining: {budget['retries_remaining']}")
    lines.append(f"time_pressure: {budget['time_pressure']}")
    if latest_turn:
        lines.append(
            f"latest_turn_gate: {latest_turn.token} approved={latest_turn.approved} after_receipt_seq={latest_turn.after_receipt_seq}"
        )
        lines.append(
            f"latest_turn_gate_fresh: {store.is_approval_fresh(latest_turn, mission.session_id, mission.task_id)}"
        )
    if latest_completion:
        lines.append(
            f"latest_completion_gate: {latest_completion.token} approved={latest_completion.approved} after_receipt_seq={latest_completion.after_receipt_seq}"
        )
        lines.append(
            f"latest_completion_gate_fresh: {store.is_approval_fresh(latest_completion, mission.session_id, mission.task_id)}"
        )
    if latest_authorization:
        lines.append(
            f"latest_user_authorization: {latest_authorization.token} approved={latest_authorization.approved} after_receipt_seq={latest_authorization.after_receipt_seq}"
        )
        lines.append(
            f"latest_user_authorization_fresh: {store.is_approval_fresh(latest_authorization, mission.session_id, mission.task_id)}"
        )
    if mission.slice_count and mission.slice_count % 3 == 0:
        lines.append("goal_alignment_check_due: yes")
    return "\n".join(lines)


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    mcp.run()
