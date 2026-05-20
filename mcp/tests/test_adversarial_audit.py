from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = REPO_ROOT / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))


def load_script_module(name: str):
    module_path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_plan(seq: int = 3) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "record_type": "audit_plan",
        "plan_id": "plan-runtime-1",
        "mission_id": "s1/t1",
        "task_id": "t1",
        "target_claims": ["completion gate rejects stale receipts"],
        "target_files": ["mcp/server.py"],
        "profiles_required": ["runtime_gate_adversary"],
        "audit_scope": {
            "target_claims": ["completion gate rejects stale receipts"],
            "target_files": ["mcp/server.py"],
            "allowed_attack_types": ["stale_evidence"],
            "excluded_actions": ["network", "deployment", "git push", "secret reads"],
        },
        "audit_budget": {
            "max_hypotheses": 2,
            "max_executable_attacks": 1,
            "max_runtime_seconds": 10,
            "max_retries_per_attack": 1,
            "max_output_bytes": 10000,
            "max_generated_artifacts": 1,
        },
        "freshness_baseline": {"latest_receipt_seq": seq},
        "created_at": "2026-05-09T00:00:00Z",
        "source_refs": [{"kind": "file", "path": "mcp/server.py", "summary": "target"}],
    }


def audit_attempt(outcome: str = "attack_failed") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "record_type": "audit_attempt",
        "attempt_id": "attempt-runtime-1",
        "plan_id": "plan-runtime-1",
        "profile": "runtime_gate_adversary",
        "target_claims": ["completion gate rejects stale receipts"],
        "hypothesis": "A stale receipt can satisfy a post-edit completion criterion.",
        "attack_type": "stale_evidence",
        "command_or_script": "python -m unittest mcp.tests.test_runtime",
        "artifact_paths": ["mcp/tests/test_runtime.py"],
        "execution_receipts": ["receipt-runtime-1"],
        "observed_result": "The gate rejected stale evidence.",
        "outcome": outcome,
        "residual_risk": "Only deterministic stale receipt path covered.",
        "created_at": "2026-05-09T00:00:01Z",
    }


def finding(disposition: str, severity: str = "info") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "record_type": "audit_finding",
        "finding_id": f"finding-{disposition}",
        "linked_attempt_ids": ["attempt-runtime-1"],
        "severity": severity,
        "reproducibility": "deterministic",
        "affected_claims": ["completion gate rejects stale receipts"],
        "affected_files": ["mcp/server.py"],
        "disposition": disposition,
        "required_action": "Add a regression test and rerun audit.",
        "residual_risk": "No broader fuzzing was attempted.",
        "created_at": "2026-05-09T00:00:02Z",
    }


def valid_records() -> list[dict[str, object]]:
    return [audit_plan(), audit_attempt(), finding("non_blocking")]


class AdversarialAuditTestCase(unittest.TestCase):
    def test_valid_records_pass_lint_and_gate(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        self.assertEqual([], audit.lint_records(valid_records()))
        self.assertEqual(
            [],
            audit.gate_violations(
                valid_records(), ["runtime_gate_adversary"], ["completion gate rejects stale receipts"], 3
            ),
        )

    def test_missing_scope_or_budget_fails_lint(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        broken = audit_plan()
        broken.pop("audit_budget")
        del broken["audit_scope"]["target_claims"]  # type: ignore[index]
        issues = "\n".join(audit.lint_records([broken]))
        self.assertIn("audit_plan requires audit_scope.target_claims", issues)
        self.assertIn("audit_plan requires audit_budget", issues)

    def test_no_receipt_or_low_severity_finding_cannot_block(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        no_receipt_attempt = audit_attempt("attack_succeeded")
        no_receipt_attempt["execution_receipts"] = []
        records = [audit_plan(), no_receipt_attempt, finding("blocking", "low")]
        issues = "\n".join(audit.lint_records(records))
        self.assertIn("blocking finding requires critical/high severity", issues)
        self.assertIn("blocking finding requires executable evidence", issues)

    def test_banned_proof_of_safety_phrase_fails_lint(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        records = valid_records()
        records[1]["observed_result"] = "The adversary proved safe behavior."
        self.assertIn("banned proof-of-safety phrase", "\n".join(audit.lint_records(records)))

    def test_nonblocking_dispositions_do_not_block_gate(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        for disposition in ["needs_reproduction", "false_positive", "non_blocking"]:
            records = [audit_plan(), audit_attempt("needs_reproduction"), finding(disposition)]
            self.assertEqual([], audit.gate_violations(records, ["runtime_gate_adversary"], [], 3))

    def test_stale_audit_fails_gate_after_target_mutation(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        issues = audit.gate_violations(valid_records(), ["runtime_gate_adversary"], [], 4)
        self.assertTrue(any("stale" in issue for issue in issues))

    def test_project_learning_can_seed_but_not_satisfy_evidence(self) -> None:
        audit = importlib.import_module("agent_runway_runtime.adversarial_audit")
        seeded_attempt = audit_attempt("attack_succeeded")
        seeded_attempt["execution_receipts"] = []
        seeded_attempt["source_refs"] = [{"kind": "project_learning", "use": "seed_only"}]
        issues = "\n".join(audit.lint_records([audit_plan(), seeded_attempt, finding("blocking", "high")]))
        self.assertIn("Project Learning Ledger cannot satisfy adversarial evidence", issues)

    def test_lint_cli_accepts_valid_jsonl_and_rejects_bad_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "good.jsonl"
            bad = Path(td) / "bad.jsonl"
            good.write_text("\n".join(json.dumps(item) for item in valid_records()), encoding="utf-8")
            bad.write_text(json.dumps({"schema_version": "1.0", "record_type": "audit_plan"}), encoding="utf-8")
            good_proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "adversarial_audit_lint.py"), str(good)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            bad_proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "adversarial_audit_lint.py"), str(bad)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        self.assertEqual(0, good_proc.returncode, good_proc.stdout)
        self.assertNotEqual(0, bad_proc.returncode, bad_proc.stdout)

    def test_release_gate_declares_independent_adversarial_audit_gate(self) -> None:
        module = load_script_module("release_gate")
        checks = module.build_ordered_checks(REPO_ROOT)
        names = [check[0] for check in checks]
        self.assertEqual(16, len(names))
        self.assertIn("adversarial_audit_suite", names)
        self.assertLess(names.index("benchmark_suite"), names.index("adversarial_audit_suite"))

    def test_completion_gate_rejects_required_unresolved_blocking_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            os.environ["ILH_DB_PATH"] = str(Path(td) / "state.db")
            os.environ["ILH_SECRET_PATH"] = str(Path(td) / "secret.key")
            server = importlib.reload(importlib.import_module("server"))
            server.mission_lock(
                "s1",
                "t1",
                "verify completion gate audit integration",
                ["tests pass"],
                adversarial_audit_required=True,
                adversarial_audit_profiles=["runtime_gate_adversary"],
                adversarial_audit_records=[audit_plan(99), audit_attempt("attack_succeeded"), finding("blocking", "high")],
            )
            receipt = server.store.record_receipt("s1", "test", "Bash", "pytest", 0, {}, task_id="t1")
            result = server.completion_gate(
                "s1",
                "t1",
                [{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
                "Completed tests with current execution evidence.",
            )
        self.assertIn("REJECTED", result)
        self.assertIn("finding-blocking", result)


if __name__ == "__main__":
    unittest.main()
