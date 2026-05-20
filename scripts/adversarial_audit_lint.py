#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.adversarial_audit import lint_records, read_records


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/adversarial_audit_lint.py <audit-records...>")
        return 1
    paths = [Path(item) for item in sys.argv[1:]]
    records = read_records(paths)
    issues = lint_records(records)
    payload = {"record_count": len(records), "issues": issues, "passed": not issues}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
