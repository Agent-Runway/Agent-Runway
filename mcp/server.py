from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent.resolve()
sys.path = [p for p in sys.path if Path(p or ".").resolve() != PROJECT_ROOT]
sys.path.insert(0, str(THIS_DIR))

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover

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
from agent_runway_runtime.store import RuntimeStore
from agent_runway_runtime.host_tool_taxonomy import EXECUTION_TOOLS, MUTATION_TOOLS, OBSERVATION_TOOLS
from agent_runway_runtime.debug_logging import write_debug_log

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

LEGAL_STOP_CONDITIONS = {
    "slice_verified",
    "frontier_exhausted",
    "user_information_required",
    "approval_required",
    "interpretation_deadlock",
    "stuck_escalation",
}

# Word-boundary regex patterns. Substring matching produced too many false positives
# (e.g. "shoulder", "i think about", "should i rerun"). The new patterns target the
# concrete hedging shapes that actually leak into work summaries while sparing
# legitimate uses like "the user asked whether i should rerun".
ASSERTION_SIGNAL_PATTERNS = (
    re.compile(r"\bshould (?:work|pass|be fine|resolve|fix|return|now)\b", re.IGNORECASE),
    re.compile(r"\bshould be (?:enough|ok)\b", re.IGNORECASE),
    re.compile(r"\bprobably\b", re.IGNORECASE),
    re.compile(r"\bi believe\b", re.IGNORECASE),
    re.compile(r"\b(?:i think|i'?m thinking)\s+(?:it|this|that|the)\b", re.IGNORECASE),
    re.compile(r"\blooks correct\b", re.IGNORECASE),
    re.compile(r"\bseems to\b", re.IGNORECASE),
    re.compile(r"\bappears to\b", re.IGNORECASE),
    re.compile(r"\bi['\u2019]?m confident\b", re.IGNORECASE),
    re.compile(r"\bit works\b", re.IGNORECASE),
    re.compile(r"应该(?:可以了|没问题|能过|通过)", re.IGNORECASE),
    re.compile(r"应该(?:够了|差不多了)", re.IGNORECASE),
    re.compile(r"大概没问题", re.IGNORECASE),
    re.compile(r"看起来对了", re.IGNORECASE),
    re.compile(r"我觉得(?:这次)?能过", re.IGNORECASE),
)


def _has_assertion_language(text: str) -> bool:
    lowered = text.lower()
    external_quote_markers_en = (
        'user wrote',
        'user said',
        'issue thread said',
        'bug thread',
        'issue thread',
        'the thread said',
        'quoted from',
    )
    external_quote_markers_zh = (
        '工单里写了',
        '用户在',
        '原话',
        '写的是',
        '引用',
        '文档原话',
    )
    has_assertion = any(pattern.search(text) for pattern in ASSERTION_SIGNAL_PATTERNS)
    if not has_assertion:
        return False
    if (('"' in text) or ('“' in text and '”' in text)) and (
        any(marker in lowered for marker in external_quote_markers_en)
        or any(marker in text for marker in external_quote_markers_zh)
    ):
        trailing_text = re.sub(r'".*?"|“.*?”', ' ', text)
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


def _require_active_mission(session_id: str, task_id: str) -> Any:
    mission = store.get_active_mission(session_id, task_id)
    if mission is None:
        raise ValueError(
            f"No active mission for session_id={session_id!r}, task_id={task_id!r}. Call mission_lock first."
        )
    return mission


def _mission_payload_missing() -> str:
    return json.dumps(
        {"error": "No mission found for this session/task."},
        ensure_ascii=False,
        indent=2,
    )


def _mission_or_none(session_id: str, task_id: str) -> Any | None:
    mission = store.get_active_mission(session_id, task_id)
    if mission is not None:
        return mission
    try:
        return store.get_mission(session_id, task_id)
    except KeyError:
        return None


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
    if receipts and all(receipt.task_id is None for receipt in receipts):
        warnings.append(
            "Receipts are not mission-scoped. Prefer task-scoped receipts for load-bearing claims."
        )
    return warnings


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


def _latest_mission_tool_seq(
    session_id: str, task_id: str, mission: Any, tool_names: frozenset[str]
) -> int:
    receipts = _mission_scope_recent_receipts(
        session_id, task_id, mission, MISSION_RECEIPT_SCAN_LIMIT
    )
    return max(
        (int(receipt.seq) for receipt in receipts if receipt.tool_name in tool_names),
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


def _criterion_is_observational_analysis(criterion: str) -> bool:
    lowered = criterion.lower()
    english_analysis_heads = ("analyze", "review", "investigate", "research", "inspect")
    english_artifacts = ("plan", "report", "themes", "structure", "variation", "model")
    chinese_analysis_heads = ("分析", "审阅", "研究", "调研", "检查")
    chinese_artifacts = ("计划", "报告", "主题", "结构", "差异", "机制")
    return (
        any(head in lowered for head in english_analysis_heads)
        and any(artifact in lowered for artifact in english_artifacts)
    ) or (
        any(head in criterion for head in chinese_analysis_heads)
        and any(artifact in criterion for artifact in chinese_artifacts)
    )


def _criterion_requires_execution_receipt(criterion: str) -> bool:
    if _criterion_is_observational_analysis(criterion):
        lowered = criterion.lower()
        if not any(
            token in lowered
            for token in (
                " run ",
                " execute ",
                " compile ",
                " render ",
                " simulate ",
                " scan ",
                " fuzz ",
                " benchmark ",
                " profile ",
                "检测",
                "扫描",
                "运行",
                "回测",
                "渲染",
                "执行",
            )
        ):
            return False
    lowered = criterion.lower()
    if any(phrase in criterion for phrase in ("运行机制", "运行原理", "运行逻辑")) and any(
        phrase in criterion for phrase in ("研究", "分析", "调研")
    ):
        return False
    english_tokens = set(re.findall(r"\b[a-z]+\b", lowered))
    english_needles = {
        "test",
        "tests",
        "build",
        "lint",
        "pass",
        "verify",
        "run",
        "execute",
        "compile",
        "check",
        "render",
        "simulate",
        "scan",
        "fuzz",
        "profile",
        "detect",
        "harvest",
        "mine",
    }
    chinese_needles = ("运行", "回测", "扫描", "渲染", "编译", "执行", "检测", "模拟", "验证")
    matched = bool(english_tokens & english_needles) or any(
        needle in criterion for needle in chinese_needles
    )
    if not matched and _criterion_is_observational_analysis(criterion):
        return False
    return matched


def _criterion_requires_mutation_receipt(criterion: str) -> bool:
    if _criterion_is_observational_analysis(criterion):
        lowered = criterion.lower()
        if not any(
            token in lowered
            for token in (
                " draft ",
                " edit ",
                " write ",
                " update ",
                " revise ",
                " modify ",
                " patch ",
                "撰写",
                "修改",
                "更新",
            )
        ):
            return False
    lowered = criterion.lower()
    english_tokens = set(re.findall(r"\b[a-z]+\b", lowered))
    english_needles = {
        "modify",
        "modified",
        "update",
        "updated",
        "edit",
        "write",
        "wrote",
        "patch",
        "rewrite",
        "revise",
        "ppt",
    }
    english_phrases = (
        "file changed",
        "file change",
        "changed file",
        "slide deck",
        "chapter draft",
        "storyboard draft",
        "landing page copy",
        "marketing copy",
    )
    chinese_needles = ("撰写", "修改", "更新", "删除", "重构", "创建", "新增", "移除", "终稿", "文案", "幻灯片")
    matched = bool(english_tokens & english_needles) or any(
        phrase in lowered for phrase in english_phrases
    ) or any(needle in criterion for needle in chinese_needles)
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
    if requires_mutation and not any(
        receipt.tool_name in MUTATION_TOOLS for receipt in receipts
    ):
        return False
    return True


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
    active = _active_work_payload(session_id, task_id, mission)
    elapsed_minutes = active["elapsed_minutes"]
    time_budget = int((mission.notes or {}).get("time_budget_minutes") or 0)
    time_remaining = max(time_budget - elapsed_minutes, 0) if time_budget else None
    retries_used = _distinct_retry_count(session_id, task_id)
    retries_remaining = max(mission.retry_budget - retries_used, 0)
    slices_remaining = max(mission.slice_budget - mission.slice_count, 0)
    payload: dict[str, Any] = {
        "elapsed_minutes": elapsed_minutes,
        "wall_clock_elapsed_minutes": wall_clock_elapsed,
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
    session_id: str, task_id: str, approval: Any | None = None
) -> dict[str, Any] | None:
    approval = approval or store.latest_approval(
        session_id, task_id, gate_type="user_authorization"
    )
    if approval is None:
        return None
    meta = approval.meta or {}
    return {
        "token": approval.token,
        "approved": approval.approved,
        "reason": approval.reason,
        "fresh": store.is_approval_fresh(approval, session_id, task_id),
        "action_scope": meta.get("action_scope", ""),
        "approval_scope": meta.get("approval_scope", ""),
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


@mcp.tool()
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
    criteria = _string_list(completion_criteria)
    if not goal.strip():
        raise ValueError("goal must not be empty")
    if not criteria:
        raise ValueError("Provide at least one concrete completion criterion.")
    if len(criteria) != len(set(criteria)):
        raise ValueError("duplicate completion criterion is not allowed")
    if slice_budget < 1 or retry_budget < 1:
        raise ValueError("slice_budget and retry_budget must be >= 1")
    if time_budget_minutes < 0:
        raise ValueError("time_budget_minutes must be >= 0")

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
        "adversarial_audit_profiles": _string_list(adversarial_audit_profiles),
        "adversarial_audit_claims": _string_list(adversarial_audit_claims),
        "adversarial_audit_budget": adversarial_audit_budget or {},
        "adversarial_audit_records": adversarial_audit_records or [],
    }

    store.ensure_session(session_id=session_id, host=host, cwd=cwd)
    mission = store.create_mission(
        session_id=session_id,
        task_id=task_id,
        goal=goal.strip(),
        completion_criteria=criteria,
        scope_boundary=scope_boundary.strip(),
        red_lines=_string_list(red_lines),
        slice_budget=slice_budget,
        retry_budget=retry_budget,
        notes=notes,
    )

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
    if notes["adversarial_audit_required"]:
        lines.append("adversarial_audit_required: yes")
        lines.append(f"adversarial_audit_profiles: {len(notes['adversarial_audit_profiles'])}")
    lines.append(
        "Call turn_end_gate before stopping, and completion_gate before declaring done."
    )
    return "\n".join(lines)


@mcp.tool()
def list_recent_receipts(session_id: str, task_id: str = "", limit: int = 10) -> str:
    task_scope = task_id.strip()
    bounded_limit = max(1, min(limit, 50))
    mission = _mission_or_none(session_id, task_scope) if task_scope else store.get_active_mission(session_id)
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


@mcp.tool()
def budget_status(session_id: str, task_id: str) -> str:
    task_scope = task_id.strip()
    mission = _mission_or_none(session_id, task_scope)
    if mission is None:
        return _mission_payload_missing()
    return json.dumps(
        _budget_snapshot(session_id, task_scope, mission), ensure_ascii=False, indent=2
    )


@mcp.tool()
def record_user_authorization(
    session_id: str,
    task_id: str,
    action_scope: str,
    approval_scope: str,
    user_statement_excerpt: str,
    irreversible: bool = False,
    ttl_seconds: int = 1800,
) -> str:
    _require_active_mission(session_id, task_id)
    if (
        not action_scope.strip()
        or not approval_scope.strip()
        or not user_statement_excerpt.strip()
    ):
        raise ValueError(
            "action_scope, approval_scope, and user_statement_excerpt must not be empty."
        )
    ttl_seconds = max(60, min(int(ttl_seconds), 7200))
    approval = store.create_approval(
        session_id=session_id,
        task_id=task_id,
        gate_type="user_authorization",
        approved=True,
        reason="user authorization recorded",
        after_receipt_seq=store.latest_receipt_seq(session_id),
        ttl_seconds=ttl_seconds,
        meta={
            "action_scope": action_scope.strip(),
            "approval_scope": approval_scope.strip(),
            "irreversible": bool(irreversible),
            "user_statement_excerpt": user_statement_excerpt.strip(),
        },
    )
    lines = [
        "USER AUTHORIZATION RECORDED",
        f"authorization_token: {approval.token}",
        f"action_scope: {action_scope.strip()}",
        f"approval_scope: {approval_scope.strip()}",
        f"irreversible: {bool(irreversible)}",
        f"expires_at: {approval.expires_at}",
    ]
    return "\n".join(lines)


@mcp.tool()
def authorization_status(session_id: str, task_id: str) -> str:
    task_scope = task_id.strip()
    mission = _mission_or_none(session_id, task_scope)
    if mission is None:
        return _mission_payload_missing()
    payload = _authorization_payload(session_id, task_scope)
    return json.dumps(
        {"task_id": mission.task_id, "authorization": payload},
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def verify_receipt_integrity(
    session_id: str, receipt_ids: list[str], task_id: str = ""
) -> str:
    scoped_task = task_id.strip() or None
    receipt_ids = _receipt_id_list(receipt_ids)
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


@mcp.tool()
def record_stuck_attempt(
    session_id: str,
    task_id: str,
    strategy_fingerprint: str,
    summary: str,
    receipt_ids: list[str],
) -> str:
    mission = _require_active_mission(session_id, task_id)
    receipt_ids = _receipt_id_list(receipt_ids)
    _require_unique_receipt_ids(receipt_ids)
    receipts = _get_mission_scope_receipts(receipt_ids, session_id, task_id)
    if len(receipts) != len(set(receipt_ids)):
        raise ValueError("Every receipt_id must exist and belong to this session/task.")
    stale_receipts = _receipt_epoch_violations(mission, receipts, "stuck attempt")
    if stale_receipts:
        raise ValueError("; ".join(stale_receipts))
    if not strategy_fingerprint.strip():
        raise ValueError("strategy_fingerprint must not be empty")
    if not summary.strip():
        raise ValueError("summary must not be empty")

    attempt = store.record_stuck_attempt(
        session_id=session_id,
        task_id=task_id,
        strategy_fingerprint=strategy_fingerprint.strip(),
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


@mcp.tool()
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
    evidence_receipt_ids = _receipt_id_list(evidence_receipt_ids, "evidence_receipt_ids")
    _require_unique_receipt_ids(evidence_receipt_ids, "evidence_receipt_ids")
    receipts = _get_mission_scope_receipts(evidence_receipt_ids, session_id, task_id)
    if len(receipts) != len(set(evidence_receipt_ids)):
        raise ValueError(
            "Every evidence_receipt_id must exist and belong to this mission scope."
        )
    stale_receipts = _receipt_epoch_violations(mission, receipts, "decision record")
    if stale_receipts:
        raise ValueError("; ".join(stale_receipts))
    if not title.strip() or not choice_made.strip():
        raise ValueError("title and choice_made must not be empty")
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


@mcp.tool()
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
    receipt_ids = _receipt_id_list(receipt_ids)
    _require_unique_receipt_ids(receipt_ids)
    receipts = _get_mission_scope_receipts(receipt_ids, session_id, task_id)
    if len(receipts) != len(set(receipt_ids)):
        raise ValueError(
            "Every receipt_id must exist and belong to this mission scope."
        )
    stale_receipts = _receipt_epoch_violations(mission, receipts, "counterexample check")
    if stale_receipts:
        raise ValueError("; ".join(stale_receipts))
    if not hypothesis.strip():
        raise ValueError("hypothesis must not be empty")
    if not _string_list(attempted_disconfirmers):
        raise ValueError("Provide at least one attempted disconfirmer.")
    if not outcome.strip():
        raise ValueError("outcome must not be empty")
    check = store.record_counterexample_check(
        session_id=session_id,
        task_id=task_id,
        hypothesis=hypothesis.strip(),
        attempted_disconfirmers=_string_list(attempted_disconfirmers),
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


@mcp.tool()
def turn_end_gate(
    session_id: str,
    task_id: str,
    stop_condition: str,
    work_summary: str,
    receipt_ids: list[str],
    pending_actions_identified: list[str] | None = None,
    reason_for_stopping: str = "",
    assumptions_remaining: list[str] | None = None,
) -> str:
    mission = _require_active_mission(session_id, task_id)
    stop_condition = stop_condition.strip()
    if stop_condition not in LEGAL_STOP_CONDITIONS:
        raise ValueError(
            f"stop_condition must be one of: {sorted(LEGAL_STOP_CONDITIONS)}"
        )
    if len(work_summary.strip()) < 20:
        raise ValueError(
            "work_summary is too short. Describe what actually changed, tested, or ruled out."
        )

    receipt_ids = _receipt_id_list(receipt_ids)
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
    violations: list[str] = []
    warnings = _fresh_receipt_warning(receipts)
    budget = _budget_snapshot(session_id, task_id, mission)
    violations.extend(_receipt_epoch_violations(mission, receipts, "turn_end_gate"))

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

    if (
        stop_condition in {"user_information_required", "approval_required"}
        and not reason_for_stopping.strip()
    ):
        violations.append(f"{stop_condition} requires a precise reason_for_stopping.")

    if stop_condition == "interpretation_deadlock" and (
        len(reason_for_stopping.strip()) < 30
        or not _has_substantive_interpretation_reason(reason_for_stopping)
    ):
        violations.append(
            "interpretation_deadlock requires a concrete explanation of the unresolved interpretations."
        )

    if stop_condition == "stuck_escalation":
        attempts = store.list_stuck_attempts(session_id, task_id)
        distinct = {a.strategy_fingerprint for a in attempts}
        if len(distinct) < mission.retry_budget:
            violations.append(
                f"stuck_escalation requires at least {mission.retry_budget} materially different recorded attempts; found {len(distinct)}."
            )
        if len(reason_for_stopping.strip()) < 30:
            violations.append(
                "stuck_escalation requires a precise explanation of why further local retries are no longer justified."
            )

    after_receipt_seq = max(r.seq for r in receipts)
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
            "stop_condition": stop_condition,
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
    if assumptions:
        lines.append(
            f"assumptions_remaining: {json.dumps(assumptions, ensure_ascii=False)}"
        )
    lines.append(f"time_pressure: {budget['time_pressure']}")
    if warnings:
        lines.append(f"warnings: {json.dumps(warnings, ensure_ascii=False)}")
    return "\n".join(lines)


@mcp.tool()
def completion_gate(
    session_id: str,
    task_id: str,
    criterion_receipt_map: list[dict[str, Any]],
    completion_summary: str,
    unverified_items: list[str] | None = None,
    known_risks: list[str] | None = None,
) -> str:
    mission = _require_active_mission(session_id, task_id)
    if len(completion_summary.strip()) < 20:
        raise ValueError("completion_summary is too short.")

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
        mapping_by_criterion[criterion] = ids
        provided_receipt_ids.extend(ids)

    criteria = mission.completion_criteria
    missing = [
        criterion for criterion in criteria if criterion not in mapping_by_criterion
    ]
    extra = [
        criterion for criterion in mapping_by_criterion if criterion not in criteria
    ]

    receipts = _get_mission_scope_receipts(provided_receipt_ids, session_id, task_id)
    if len(receipts) != len(set(provided_receipt_ids)):
        write_debug_log(
            "completion_gate.missing_receipts",
            {"session_id": session_id, "task_id": task_id, "receipt_ids": provided_receipt_ids},
        )
        raise ValueError(_receipt_scope_error(provided_receipt_ids, session_id, task_id))
    receipt_map = {receipt.receipt_id: receipt for receipt in receipts}

    violations: list[str] = []
    if missing:
        violations.append(f"Missing criterion mappings: {missing}")
    if extra:
        violations.append(f"Unknown criterion mappings: {extra}")
    violations.extend(_receipt_epoch_violations(mission, receipts, "completion_gate"))

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
            if receipt.exit_code not in (None, 0):
                violations.append(
                    f"criterion {criterion!r} references failed execution receipt {rid!r} (tool={receipt.tool_name}, exit={receipt.exit_code})"
                )
        if criterion_receipts and not _criterion_has_semantic_support(
            criterion, criterion_receipts
        ):
            violations.append(
                f"criterion {criterion!r} has semantic mismatch: supplied receipts do not provide the required execution evidence."
            )

    # Stale-evidence guard only applies to criteria that semantically require
    # execution. Pure mutation criteria such as writing or slide updates should
    # not be forced to supply a post-edit execution receipt.
    latest_mutation_seq = _latest_mission_tool_seq(session_id, task_id, mission, MUTATION_TOOLS)
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
        (receipt.seq for receipt in receipts),
        default=latest_receipt_seq,
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
            meta={"completion_summary": completion_summary},
        )
        lines = [
            "REJECTED",
            *[f"- {item}" for item in violations],
            f"rejection_token: {approval.token}",
        ]
        return "\n".join(lines)

    completion_notes = dict(notes)
    completion_notes.update(
        {
            "completion_summary": completion_summary.strip(),
            "unverified_items": _string_list(unverified_items),
            "known_risks": _string_list(known_risks),
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
        meta={"criterion_receipt_map": criterion_receipt_map},
    )
    lines = [
        "APPROVED",
        f"approval_token: {approval.token}",
        f"task_id: {mission.task_id}",
        f"status: {mission.status}",
        f"receipts_used: {len(receipts)}",
    ]
    if unverified_items:
        lines.append(
            f"unverified_items: {json.dumps(_string_list(unverified_items), ensure_ascii=False)}"
        )
    if known_risks:
        lines.append(
            f"known_risks: {json.dumps(_string_list(known_risks), ensure_ascii=False)}"
        )
    lines.append("You may now declare the task complete.")
    return "\n".join(lines)


@mcp.tool()
def export_handoff_packet(session_id: str, task_id: str) -> str:
    task_scope = task_id.strip()
    mission = _mission_or_none(session_id, task_scope)
    if mission is None:
        return _mission_payload_missing()
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
    payload = {
        "mission": {
            "session_id": mission.session_id,
            "task_id": mission.task_id,
            "goal": mission.goal,
            "status": mission.status,
            "completion_criteria": mission.completion_criteria,
            "scope_boundary": mission.scope_boundary,
            "red_lines": mission.red_lines,
            "slice_budget": mission.slice_budget,
            "slice_count": mission.slice_count,
            "retry_budget": mission.retry_budget,
            "notes": mission.notes,
            "mission_start_receipt_seq": _mission_start_receipt_seq(mission),
        },
        "budget_status": _budget_snapshot(session_id, task_scope, mission),
        "latest_receipts": [
            {
                "receipt_id": receipt.receipt_id,
                "tool_name": receipt.tool_name,
                "command_text": receipt.command_text,
                "exit_code": receipt.exit_code,
                "seq": receipt.seq,
            }
            for receipt in recent_receipts
        ],
        "decision_records": [
            {
                "decision_id": record.decision_id,
                "title": record.title,
                "choice_made": record.choice_made,
                "alternatives_rejected": record.alternatives_rejected,
                "reversibility": record.reversibility,
                "reopen_triggers": record.reopen_triggers,
            }
            for record in decisions
        ],
        "counterexample_checks": [
            {
                "check_id": check.check_id,
                "hypothesis": check.hypothesis,
                "attempted_disconfirmers": check.attempted_disconfirmers,
                "outcome": check.outcome,
                "surviving_risk": check.surviving_risk,
            }
            for check in counterexamples
        ],
        "latest_turn_gate": None
        if latest_turn is None
        else {
            "token": latest_turn.token,
            "approved": latest_turn.approved,
            "reason": latest_turn.reason,
            "fresh": store.is_approval_fresh(latest_turn, session_id, task_scope),
        },
        "latest_completion_gate": None
        if latest_completion is None
        else {
            "token": latest_completion.token,
            "approved": latest_completion.approved,
            "reason": latest_completion.reason,
            "fresh": store.is_approval_fresh(latest_completion, session_id, task_scope),
        },
        "latest_user_authorization": _authorization_payload(
            session_id, task_scope, latest_authorization
        ),
        "adversarial_audit_status": _adversarial_audit_status(
            mission, _latest_mission_receipt_seq(mission.session_id, mission.task_id, mission)
        ),
        "criterion_coverage": (mission.notes or {}).get("criterion_receipt_map", []),
        "known_risks": (mission.notes or {}).get("known_risks", []),
        "unverified_items": (mission.notes or {}).get("unverified_items", []),
        "recommended_next_action": _budget_snapshot(session_id, task_scope, mission)[
            "wrap_up_guidance"
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def mission_status(session_id: str, task_id: str = "") -> str:
    task_scope = task_id.strip()
    mission = store.get_active_mission(session_id, task_scope or None)
    if mission is None and task_scope:
        mission = store.get_mission(session_id, task_scope)
    if mission is None:
        return "No active mission found for this session."
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
