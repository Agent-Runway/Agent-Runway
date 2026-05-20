#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import sys
import time
from pathlib import Path

DEFAULT_TIMEOUT_SCALE = float(os.environ.get("ILH_TIMEOUT_SCALE", "1.0"))
# gate script path markers: scripts/package_skill_check.py scripts/release_static_checks.py scripts/project_learning_lint.py scripts/adversarial_audit_suite.py scripts/consistency_lint.py scripts/claim_parity_audit.py scripts/ledger_guard.py


def scaled_timeout(seconds: int) -> int:
    return max(1, int(seconds * DEFAULT_TIMEOUT_SCALE))


def build_ordered_checks(root: Path) -> list[tuple[str, str, list[str], int]]:
    quick_validate = root / "scripts" / "quick_validate.py"
    package_check = root / "scripts" / "package_skill_check.py"
    static_check = root / "scripts" / "release_static_checks.py"
    project_learning_lint = root / "scripts" / "project_learning_lint.py"
    adversarial_audit_suite = root / "scripts" / "adversarial_audit_suite.py"
    project_learning_ledger = root / "references" / "project-learning-ledger.jsonl"
    return [
        ("quick_validate", "run", [sys.executable, str(quick_validate), str(root)], 30),
        ("package_skill_validation", "run", [sys.executable, str(package_check), str(root)], 180),
        ("unit_tests", "run", [sys.executable, "-m", "unittest", "discover", "-s", "mcp/tests", "-p", "test_*.py"], 300),
        ("smoke_test", "run", [sys.executable, "scripts/smoke_test.py"], 45),
        ("consistency_lint", "run", [sys.executable, "scripts/consistency_lint.py", str(root)], 45),
        ("claim_parity_audit", "run", [sys.executable, "scripts/claim_parity_audit.py", str(root)], 45),
        ("project_learning_lint", "run", [sys.executable, str(project_learning_lint), str(project_learning_ledger), "--strict"], 30),
        ("ledger_guard", "run", [sys.executable, "scripts/ledger_guard.py", str(root)], 45),
        ("self_audit", "run", [sys.executable, "scripts/self_audit.py", str(root)], 90),
        ("benchmark_suite", "run", [sys.executable, "scripts/benchmark_suite.py", str(root)], 120),
        ("adversarial_audit_suite", "run", [sys.executable, str(adversarial_audit_suite), str(root)], 60),
        ("adversarial_mutation_suite", "run", [sys.executable, "scripts/adversarial_mutation_suite.py", str(root)], 300),
        ("evolution_ledger_updated", "run", [sys.executable, str(static_check), str(root), "evolution_ledger_updated"], 30),
        ("generation4_scorecards_updated", "run", [sys.executable, str(static_check), str(root), "generation4_scorecards_updated"], 30),
        ("claims_reflected", "run", [sys.executable, str(static_check), str(root), "claims_reflected"], 30),
        ("release_report_and_version", "run", [sys.executable, str(static_check), str(root), "release_report_and_version"], 30),
    ]


def run(cmd: list[str], cwd: Path, timeout_seconds: int) -> tuple[int, str, float]:
    started = time.time()
    timeout_seconds = scaled_timeout(timeout_seconds)
    tmp_name = ""
    proc: subprocess.Popen | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", delete=False) as output_file:
            tmp_name = output_file.name
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=output_file,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=(os.name == "posix"),
            )
            try:
                returncode = proc.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:  # pragma: no cover
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:  # pragma: no cover
                        proc.kill()
                    proc.wait(timeout=5)
                output_file.flush()
                output = Path(tmp_name).read_text(encoding="utf-8", errors="replace")
                output += f"\n[TIMEOUT] release gate subcheck exceeded {timeout_seconds} seconds"
                return 124, output, round(time.time() - started, 3)
        output = Path(tmp_name).read_text(encoding="utf-8", errors="replace")
        return returncode, output, round(time.time() - started, 3)
    except FileNotFoundError as exc:
        return 127, str(exc), round(time.time() - started, 3)
    finally:
        if tmp_name:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except Exception:
                pass


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/release_gate.py <skill-root>")
        return 1
    root = Path(sys.argv[1]).resolve()
    checks: dict[str, tuple[int, str, float]] = {}
    ordered_checks = build_ordered_checks(root)
    for idx, (name, mode, cmd, timeout_seconds) in enumerate(ordered_checks, start=1):
        if mode != "run":
            checks[name] = (2, f"[INVALID] release gate check {name} is not runnable", 0.0)
            continue
        print(f"[{idx}/{len(ordered_checks)}] running {name}", flush=True)
        checks[name] = run(cmd, root, timeout_seconds=timeout_seconds)
        code, _out, elapsed = checks[name]
        status = "PASSED" if code == 0 else "FAILED"
        print(f"[{idx}/{len(ordered_checks)}] {name}: {status} rc={code} elapsed={elapsed}s", flush=True)
    payload = {
        name: {"returncode": code, "passed": code == 0, "elapsed_seconds": elapsed, "output": out.strip()}
        for name, (code, out, elapsed) in checks.items()
    }
    payload["gate_count"] = len(ordered_checks)
    payload["timeout_scale"] = DEFAULT_TIMEOUT_SCALE
    payload["passed"] = all(item["passed"] for item in payload.values() if isinstance(item, dict) and "passed" in item)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
