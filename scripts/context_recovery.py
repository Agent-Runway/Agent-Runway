#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = REPO_ROOT / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.store import RuntimeStore  # noqa: E402
from dynamic_context import DEFAULT_CONTEXT_PATH, lint_records, parse_jsonl  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover Agent-Runway continuation context")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--session-id", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def recover(cwd: Path, session_id: str = "", task_id: str = "") -> dict[str, Any]:
    workspace = cwd.resolve()
    checked = ["project_sqlite"]
    mission = sqlite_candidate(workspace, session_id.strip(), task_id.strip())
    if mission is not None:
        return {
            "classification": "continue_current_mission",
            "should_activate_agent_runway": True,
            "source": "project_sqlite_workspace",
            "checked_sources": checked,
            "mission": mission,
            "required_first_actions": ["read mission_status", "export_handoff_packet", "verify latest receipts"],
        }
    context = dynamic_context_candidate(workspace)
    checked.extend(context["checked_sources"])
    if context["mission"] is not None:
        return {
            "classification": "recover_from_dynamic_context",
            "should_activate_agent_runway": True,
            "source": context["source"],
            "checked_sources": checked,
            "advisory_only": True,
            "mission": context["mission"],
            "required_first_actions": ["verify mission_status", "export_handoff_packet", "inspect files before acting"],
        }
    return clarification_payload(checked)


def sqlite_candidate(workspace: Path, session_id: str, task_id: str) -> dict[str, Any] | None:
    db_path = workspace / ".agent-runway" / "state.db"
    if not db_path.exists():
        return None
    store = RuntimeStore(db_path=str(db_path))
    if session_id:
        mission = store.get_active_mission(session_id, task_id or None)
        if mission is not None:
            return mission_payload(mission)
    missions = store.list_active_missions_by_cwd(str(workspace))
    if task_id:
        missions = [mission for mission in missions if mission.task_id == task_id]
    if len(missions) != 1:
        return None
    return mission_payload(missions[0])


def dynamic_context_candidate(workspace: Path) -> dict[str, Any]:
    for rel_path in candidate_context_paths(workspace):
        path = workspace / rel_path
        if not path.exists():
            continue
        records, parse_errors = parse_jsonl(path)
        if lint_records(records, parse_errors):
            continue
        if records:
            return {"source": rel_path.as_posix(), "checked_sources": [rel_path.as_posix()], "mission": record_payload(records[-1][1])}
    return {"source": "", "checked_sources": context_source_names(workspace), "mission": None}


def candidate_context_paths(workspace: Path) -> list[Path]:
    paths = [DEFAULT_CONTEXT_PATH]
    compatibility = Path("agent-runway") / "dynamic-context.jsonl"
    if (workspace / compatibility).exists():
        paths.append(compatibility)
    return paths


def context_source_names(workspace: Path) -> list[str]:
    return [path.as_posix() for path in candidate_context_paths(workspace)]


def mission_payload(mission: Any) -> dict[str, Any]:
    return {
        "session_id": mission.session_id,
        "task_id": mission.task_id,
        "goal": mission.goal,
        "status": mission.status,
    }


def record_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": str(record.get("session_id", "")),
        "task_id": str(record.get("task_id", "")),
        "summary": str(record.get("summary", "")),
    }


def clarification_payload(checked: list[str]) -> dict[str, Any]:
    return {
        "classification": "clarification_required",
        "should_activate_agent_runway": False,
        "checked_sources": checked,
        "required_user_question": "No active Agent-Runway mission or dynamic context is recoverable. What should I continue?",
    }


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(payload["classification"])


def main() -> int:
    args = parse_args()
    emit(recover(args.cwd, args.session_id, args.task_id), args.as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
