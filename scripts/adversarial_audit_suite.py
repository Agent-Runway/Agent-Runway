#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.adversarial_audit import gate_violations, lint_records, read_records, summarize


def load_examples(root: Path) -> list[dict[str, object]]:
    return read_records([root / "references" / "adversarial-audit-examples.md"])


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/adversarial_audit_suite.py <skill-root>")
        return 1
    started = time.time()
    root = Path(sys.argv[1]).resolve()
    records = load_examples(root)
    cases = {
        "lint_examples_case": not lint_records(records),
        "blocking_finding_blocks_case": bool(
            gate_violations(records, ["runtime_gate_adversary"], [], 999)
        ),
        "missing_receipt_cannot_block_case": _missing_receipt_case(root),
        "stale_audit_case": bool(gate_violations(records, [], [], 999)),
        "learning_seed_not_evidence_case": _learning_seed_case(root),
        "banned_phrase_rejected_case": _banned_phrase_case(root),
        "summary_reports_blockers_case": bool(summarize(records)["unresolved_blockers"]),
    }
    payload = {
        "cases": cases,
        "elapsed_seconds": round(time.time() - started, 3),
        "passed": all(cases.values()),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["passed"] else 2


def _missing_receipt_case(root: Path) -> bool:
    records = read_records([root / "mcp" / "tests" / "fixtures" / "adversarial_audit" / "missing_receipt_blocking_bad.jsonl"])
    return any("blocking finding requires executable evidence" in issue for issue in lint_records(records))


def _learning_seed_case(root: Path) -> bool:
    records = read_records([root / "mcp" / "tests" / "fixtures" / "adversarial_audit" / "learning_seed_only_bad.jsonl"])
    return any("Project Learning Ledger cannot satisfy" in issue for issue in lint_records(records))


def _banned_phrase_case(root: Path) -> bool:
    records = read_records([root / "mcp" / "tests" / "fixtures" / "adversarial_audit" / "banned_phrase_bad.jsonl"])
    return any("banned proof-of-safety phrase" in issue for issue in lint_records(records))


if __name__ == "__main__":
    raise SystemExit(main())
