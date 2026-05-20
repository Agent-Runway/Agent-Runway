from __future__ import annotations

import importlib
import ast
import json
import os
import tempfile
import unittest
from pathlib import Path


class RuntimeContractEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)
        os.environ["ILH_HARNESS_SECRET"] = "a" * 64

        import sys

        mcp_root = str(Path(__file__).resolve().parents[1])
        if mcp_root not in sys.path:
            sys.path.insert(0, mcp_root)
        self.server = importlib.import_module("server")
        self.server = importlib.reload(self.server)
        self.store = self.server.store

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)
        os.environ.pop("ILH_HARNESS_SECRET", None)

    def make_receipt(self, task_id: str = "t1"):
        return self.store.record_receipt(
            session_id="s1",
            task_id=task_id,
            source="test",
            tool_name="Bash",
            command_text="pytest -q",
            exit_code=0,
            metadata={"stdout_sha256": "abc"},
        )

    def approve_turn_for_receipt(self, task_id: str, receipt_id: str) -> None:
        approved = self.server.turn_end_gate(
            "s1",
            task_id,
            "slice_verified",
            "Verified the current slice with direct receipt evidence before completion.",
            [receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def runtime_tool_names_from_source(self) -> set[str]:
        source_path = Path(__file__).resolve().parents[1] / "server.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        return {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and any(
                getattr(decorator, "id", "") == "_runtime_tool"
                for decorator in node.decorator_list
            )
        }

    def test_mission_lock_reports_verification_plan_and_evidence_map_counts(self) -> None:
        locked = self.server.mission_lock(
            "s1",
            "notes-task",
            "goal",
            ["criterion"],
            verification_plan=["pytest tests/", "ruff check ."],
            evidence_map=[{"criterion": "criterion", "tool": "pytest"}],
        )

        self.assertIn("verification_plan_steps: 2", locked)
        self.assertIn("evidence_map_entries: 1", locked)

    def test_mission_resume_rejects_missing_mission_before_binding(self) -> None:
        result = json.loads(self.server.mission_resume("s1", "missing-task"))

        self.assertEqual("mission_resume", result["tool"])
        self.assertEqual("No mission found for this session/task.", result["error"])

    def test_mission_resume_refreshes_host_session_binding(self) -> None:
        self.server.mission_lock("mission-session", "resume-task", "goal", ["criterion"])

        resumed = self.server.mission_resume(
            "mission-session",
            "resume-task",
            host_session_id="host-session",
        )

        self.assertIn("MISSION RESUMED", resumed)
        self.assertIn("binding_refreshed: yes", resumed)
        bound = self.store.bound_active_mission_for_host_session("host-session")
        self.assertIsNotNone(bound)
        self.assertEqual("mission-session", bound.session_id)
        self.assertEqual("resume-task", bound.task_id)

    def test_mission_lock_warns_when_other_active_mission_exists_in_same_session(self) -> None:
        self.server.mission_lock("s1", "task-a", "goal a", ["criterion a"])

        locked = self.server.mission_lock("s1", "task-b", "goal b", ["criterion b"])

        self.assertIn("has_active_mission: yes", locked)
        self.assertIn("suggested_action: mission_resume", locked)
        self.assertIn("task-a", locked)
        self.assertIn("resume_warning:", locked)

    def test_mission_lock_writes_host_session_binding_when_provided(self) -> None:
        locked = self.server.mission_lock(
            "mission-session",
            "bound-task",
            "goal",
            ["criterion"],
            host_session_id="host-session",
        )

        self.assertIn("binding_written: yes", locked)
        self.assertIn("host_session_id: host-session", locked)
        bound = self.store.bound_active_mission_for_host_session("host-session")
        self.assertIsNotNone(bound)
        self.assertEqual("mission-session", bound.session_id)
        self.assertEqual("bound-task", bound.task_id)

    def test_mission_lock_without_host_session_id_does_not_create_rehydration_binding(self) -> None:
        locked = self.server.mission_lock(
            "mission-session",
            "bound-task",
            "goal",
            ["criterion"],
        )

        self.assertIn("binding_written: no", locked)
        self.assertNotIn("host_session_id:", locked)
        bound = self.store.bound_active_mission_for_host_session("mission-session")
        self.assertIsNone(bound)

    def test_host_session_binding_rejects_invisible_only_identifier(self) -> None:
        with self.assertRaisesRegex(ValueError, "host_session_id must not be empty"):
            self.server.mission_lock(
                "mission-session",
                "bound-task",
                "goal",
                ["criterion"],
                host_session_id="\u200b",
            )
        with self.assertRaises(KeyError):
            self.store.get_mission("mission-session", "bound-task")

        self.server.mission_lock("mission-session", "resume-task", "goal", ["criterion"])
        with self.assertRaisesRegex(ValueError, "host_session_id must not be empty"):
            self.server.mission_resume(
                "mission-session",
                "resume-task",
                host_session_id="\u200b",
            )

    def test_mission_status_reports_scope_boundary_red_lines_and_degradation_mode(self) -> None:
        self.server.mission_lock(
            "s1",
            "status-task",
            "goal",
            ["criterion"],
            scope_boundary="frontend only",
            red_lines=["no DB changes"],
            degradation_mode="mcp-only-no-hooks",
        )

        status = self.server.mission_status("s1", "status-task")

        self.assertIn("scope_boundary: frontend only", status)
        self.assertIn("red_lines:", status)
        self.assertIn("no DB changes", status)
        self.assertIn("degradation_mode: mcp-only-no-hooks", status)

    def test_mission_status_returns_json_when_mission_is_missing(self) -> None:
        status = json.loads(self.server.mission_status("s1", "missing-task"))

        self.assertEqual("No mission found for this session/task.", status["error"])

    def test_mission_status_returns_json_when_session_has_no_missions(self) -> None:
        status = json.loads(self.server.mission_status("s1", ""))

        self.assertEqual("No mission found for this session/task.", status["error"])

    def test_mission_status_returns_json_for_missing_task_even_with_active_neighbor(self) -> None:
        self.server.mission_lock("s1", "active-task", "goal", ["criterion"])

        status = json.loads(self.server.mission_status("s1", "missing-task"))

        self.assertEqual("No mission found for this session/task.", status["error"])

    def test_mission_lock_rejects_blank_session_and_task_ids(self) -> None:
        cases = [
            {"session_id": "", "task_id": "t1"},
            {"session_id": "   ", "task_id": "t1"},
            {"session_id": "\t", "task_id": "t1"},
            {"session_id": "\n", "task_id": "t1"},
            {"session_id": "\u200b", "task_id": "t1"},
            {"session_id": "\x00", "task_id": "t1"},
            {"session_id": "s1", "task_id": ""},
            {"session_id": "s1", "task_id": "   "},
            {"session_id": "s1", "task_id": "\t"},
            {"session_id": "s1", "task_id": " \n\t "},
            {"session_id": "s1", "task_id": "\u200b"},
            {"session_id": "s1", "task_id": "\x00"},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, "must not be empty"):
                    self.server.mission_lock(
                        kwargs["session_id"], kwargs["task_id"], "goal", ["criterion"]
                    )

    def test_all_runtime_tools_reject_blank_session_ids(self) -> None:
        calls = {
            "mission_lock": lambda: self.server.mission_lock(" ", "t1", "goal", ["criterion"]),
            "mission_resume": lambda: self.server.mission_resume(" ", "t1"),
            "list_recent_receipts": lambda: self.server.list_recent_receipts(" ", "t1"),
            "budget_status": lambda: self.server.budget_status(" ", "t1"),
            "prompt_intake_gate": lambda: self.server.prompt_intake_gate(" ", "继续"),
            "record_user_authorization": lambda: self.server.record_user_authorization(
                " ", "t1", "push gitea", "single push", "approved"
            ),
            "authorization_status": lambda: self.server.authorization_status(" ", "t1"),
            "register_subagent_start": lambda: self.server.register_subagent_start(
                " ", "t1", "reviewer", "review scope", {}
            ),
            "record_subagent_handoff": lambda: self.server.record_subagent_handoff(
                " ",
                "t1",
                "child-1",
                "Collected concrete child evidence for this delegated task.",
                [],
                ["receipt-1"],
            ),
            "register_subagent_stop": lambda: self.server.register_subagent_stop(
                " ", "t1", "child-1", "completed"
            ),
            "subagent_status": lambda: self.server.subagent_status(" ", "t1"),
            "verify_receipt_integrity": lambda: self.server.verify_receipt_integrity(
                " ", ["receipt-1"], "t1"
            ),
            "record_stuck_attempt": lambda: self.server.record_stuck_attempt(
                " ", "t1", "strategy", "Recorded a concrete failed strategy.", ["receipt-1"]
            ),
            "record_decision_record": lambda: self.server.record_decision_record(
                " ",
                "t1",
                "choose scoped evidence",
                "reject blank namespace writes",
                ["accept blank namespace writes"],
                ["receipt-1"],
            ),
            "record_counterexample_check": lambda: self.server.record_counterexample_check(
                " ",
                "t1",
                "blank session could create polluted state",
                ["submitted a blank session id"],
                "runtime rejected the blank namespace",
                ["receipt-1"],
            ),
            "turn_end_gate": lambda: self.server.turn_end_gate(
                " ",
                "t1",
                "slice_verified",
                "Tried to claim a verified slice from a blank session namespace.",
                ["receipt-1"],
            ),
            "completion_gate": lambda: self.server.completion_gate(
                " ",
                "t1",
                "Tried to complete a task from a blank session namespace.",
                [{"criterion": "criterion", "receipt_ids": ["receipt-1"]}],
            ),
            "export_handoff_packet": lambda: self.server.export_handoff_packet(" ", "t1"),
            "mission_status": lambda: self.server.mission_status(" ", ""),
        }
        expected_tool_names = {
            "mission_lock",
            "mission_resume",
            "list_recent_receipts",
            "budget_status",
            "prompt_intake_gate",
            "record_user_authorization",
            "authorization_status",
            "register_subagent_start",
            "record_subagent_handoff",
            "register_subagent_stop",
            "subagent_status",
            "verify_receipt_integrity",
            "record_stuck_attempt",
            "record_decision_record",
            "record_counterexample_check",
            "turn_end_gate",
            "completion_gate",
            "export_handoff_packet",
            "mission_status",
        }
        self.assertEqual(expected_tool_names, self.runtime_tool_names_from_source())
        self.assertEqual(expected_tool_names, set(calls))

        for tool_name, call in calls.items():
            with self.subTest(tool_name=tool_name):
                with self.assertRaisesRegex(ValueError, "session_id must not be empty"):
                    call()

    def test_write_and_gate_tools_reject_blank_task_ids(self) -> None:
        self.server.mission_lock("s1", "t1", "goal", ["criterion"])
        receipt = self.make_receipt("t1")
        calls = {
            "record_user_authorization": lambda: self.server.record_user_authorization(
                "s1", " ", "push gitea", "single push", "approved"
            ),
            "register_subagent_start": lambda: self.server.register_subagent_start(
                "s1", " ", "reviewer", "review scope", {}
            ),
            "record_subagent_handoff": lambda: self.server.record_subagent_handoff(
                "s1",
                " ",
                "child-1",
                "Collected concrete child evidence for this delegated task.",
                [],
                [receipt.receipt_id],
            ),
            "register_subagent_stop": lambda: self.server.register_subagent_stop(
                "s1", " ", "child-1", "completed"
            ),
            "record_stuck_attempt": lambda: self.server.record_stuck_attempt(
                "s1", " ", "strategy", "Recorded a concrete failed strategy.", [receipt.receipt_id]
            ),
            "record_decision_record": lambda: self.server.record_decision_record(
                "s1",
                " ",
                "choose scoped evidence",
                "reject blank namespace writes",
                ["accept blank namespace writes"],
                [receipt.receipt_id],
            ),
            "record_counterexample_check": lambda: self.server.record_counterexample_check(
                "s1",
                " ",
                "blank task could create polluted state",
                ["submitted a blank task id"],
                "runtime rejected the blank namespace",
                [receipt.receipt_id],
            ),
            "turn_end_gate": lambda: self.server.turn_end_gate(
                "s1",
                " ",
                "slice_verified",
                "Tried to claim a verified slice from a blank task namespace.",
                [receipt.receipt_id],
            ),
            "completion_gate": lambda: self.server.completion_gate(
                "s1",
                " ",
                "Tried to complete a task from a blank task namespace.",
                [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
            ),
        }

        for tool_name, call in calls.items():
            with self.subTest(tool_name=tool_name):
                with self.assertRaisesRegex(ValueError, "task_id must not be empty"):
                    call()

    def test_completion_gate_rejects_future_freshness_baseline_attack(self) -> None:
        self.server.mission_lock(
            "s1",
            "freshness-attack",
            "goal",
            ["criterion"],
            adversarial_audit_required=True,
            adversarial_audit_profiles=["runtime_gate_adversary"],
            adversarial_audit_claims=["claim-1"],
            adversarial_audit_budget={
                "max_hypotheses": 2,
                "max_executable_attacks": 1,
                "max_runtime_seconds": 10,
                "max_retries_per_attack": 1,
                "max_output_bytes": 1000,
                "max_generated_artifacts": 1,
            },
            adversarial_audit_records=[
                {
                    "record_type": "audit_plan",
                    "plan_id": "plan-1",
                    "profile": "runtime_gate_adversary",
                    "target_claims": ["claim-1"],
                    "audit_scope": {
                        "target_claims": ["claim-1"],
                        "target_files": ["mcp/server.py"],
                        "allowed_attack_types": ["stale_evidence"],
                        "excluded_actions": ["network"],
                    },
                    "audit_budget": {
                        "max_hypotheses": 2,
                        "max_executable_attacks": 1,
                        "max_runtime_seconds": 10,
                        "max_retries_per_attack": 1,
                        "max_output_bytes": 1000,
                        "max_generated_artifacts": 1,
                    },
                    "freshness_baseline": {
                        "latest_receipt_seq": 99999,
                        "timestamp": "2026-05-18T00:00:00Z",
                    },
                },
                {
                    "record_type": "audit_attempt",
                    "attempt_id": "attempt-1",
                    "plan_id": "plan-1",
                    "profile": "runtime_gate_adversary",
                    "target_claims": ["claim-1"],
                    "hypothesis": "future sequence baseline may hide stale audit coverage",
                    "attack_type": "stale_evidence",
                    "execution_receipts": ["receipt-1"],
                    "outcome": "attack_failed",
                    "timestamp": "2026-05-18T00:00:01Z",
                }
            ],
        )
        receipt = self.make_receipt("freshness-attack")

        rejected = self.server.completion_gate(
            "s1",
            "freshness-attack",
            "Mapped the criterion to a fresh receipt while the audit baseline attempts a future-seq bypass.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("freshness_baseline.latest_receipt_seq", rejected)

    def test_completion_gate_requires_scope_and_red_line_disclosure(self) -> None:
        self.server.mission_lock(
            "s1",
            "boundary-disclosure",
            "goal",
            ["criterion"],
            scope_boundary="Only edit runtime gate behavior.",
            red_lines=["Do not push to any remote."],
        )
        receipt = self.make_receipt("boundary-disclosure")

        rejected = self.server.completion_gate(
            "s1",
            "boundary-disclosure",
            "Mapped the criterion to a fresh receipt but omitted the mission boundary disclosures.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("scope_boundary", rejected)
        self.assertIn("red_lines", rejected)

    def test_completion_gate_accepts_explicit_scope_and_red_line_disclosure(self) -> None:
        self.server.mission_lock(
            "s1",
            "boundary-disclosure-ok",
            "goal",
            ["criterion"],
            scope_boundary="Only edit runtime gate behavior.",
            red_lines=["Do not push to any remote."],
        )
        receipt = self.make_receipt("boundary-disclosure-ok")
        self.approve_turn_for_receipt("boundary-disclosure-ok", receipt.receipt_id)

        approved = self.server.completion_gate(
            "s1",
            "boundary-disclosure-ok",
            "Mapped the criterion to fresh runtime evidence. Scope boundary observed: only edit runtime gate behavior. Red line observed: do not push to any remote.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("APPROVED", approved)

    def test_completion_gate_boundary_disclosure_normalizes_punctuation_and_chinese(self) -> None:
        self.server.mission_lock(
            "s1",
            "boundary-disclosure-zh",
            "goal",
            ["criterion"],
            scope_boundary="只修改 runtime gate，不改发布脚本。",
            red_lines=["不推送远端。"],
        )
        receipt = self.make_receipt("boundary-disclosure-zh")
        self.approve_turn_for_receipt("boundary-disclosure-zh", receipt.receipt_id)

        approved = self.server.completion_gate(
            "s1",
            "boundary-disclosure-zh",
            "Mapped criterion evidence. Scope boundary observed: 只修改 runtime gate 不改发布脚本. Red line observed: 不推送远端",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("APPROVED", approved)

    def test_completion_gate_boundary_disclosure_allows_chinese_adjacent_text(self) -> None:
        self.server.mission_lock(
            "s1",
            "boundary-disclosure-zh-adjacent",
            "goal",
            ["criterion"],
            scope_boundary="只修改 runtime gate",
            red_lines=["不推送远端"],
        )
        receipt = self.make_receipt("boundary-disclosure-zh-adjacent")
        self.approve_turn_for_receipt(
            "boundary-disclosure-zh-adjacent", receipt.receipt_id
        )

        approved = self.server.completion_gate(
            "s1",
            "boundary-disclosure-zh-adjacent",
            "Mapped criterion evidence. Scope boundary observed: 本次只修改 runtime gate。Red line observed: 确认不推送远端。",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("APPROVED", approved)

    def test_completion_gate_boundary_disclosure_requires_token_boundary(self) -> None:
        self.server.mission_lock(
            "s1",
            "boundary-token",
            "goal",
            ["criterion"],
            scope_boundary="push",
            red_lines=[],
        )
        receipt = self.make_receipt("boundary-token")

        rejected = self.server.completion_gate(
            "s1",
            "boundary-token",
            "Mapped criterion evidence and mentioned pushdown automata without disclosing the actual boundary.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("scope_boundary", rejected)

    def test_gate_tools_reject_invisible_only_ids_before_lookup(self) -> None:
        self.server.mission_lock("s1", "visible-task", "goal", ["criterion"])
        receipt = self.make_receipt("visible-task")
        calls = {
            "turn_end_gate_session": lambda: self.server.turn_end_gate(
                "\u200b",
                "visible-task",
                "slice_verified",
                "Tried to claim a verified slice using an invisible-only session id.",
                [receipt.receipt_id],
            ),
            "turn_end_gate_task": lambda: self.server.turn_end_gate(
                "s1",
                "\u200b",
                "slice_verified",
                "Tried to claim a verified slice using an invisible-only task id.",
                [receipt.receipt_id],
            ),
            "completion_gate_session": lambda: self.server.completion_gate(
                "\u200b",
                "visible-task",
                "Tried to complete a task using an invisible-only session id.",
                [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
            ),
            "completion_gate_task": lambda: self.server.completion_gate(
                "s1",
                "\u200b",
                "Tried to complete a task using an invisible-only task id.",
                [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
            ),
        }

        for name, call in calls.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "must not be empty"):
                    call()

    def test_user_authorization_rejects_blank_scope_fields_without_recording(self) -> None:
        self.server.mission_lock("s1", "authorization-scope", "goal", ["criterion"])
        cases = [
            {"action_scope": " ", "approval_scope": "single push", "excerpt": "approved"},
            {"action_scope": "\u200b", "approval_scope": "single push", "excerpt": "approved"},
            {"action_scope": "push gitea", "approval_scope": "\t", "excerpt": "approved"},
            {"action_scope": "push gitea", "approval_scope": "\x00", "excerpt": "approved"},
            {"action_scope": "push gitea", "approval_scope": "single push", "excerpt": "\n"},
            {"action_scope": "push gitea", "approval_scope": "single push", "excerpt": "\u200b"},
        ]

        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, "must not be empty"):
                    self.server.record_user_authorization(
                        "s1",
                        "authorization-scope",
                        kwargs["action_scope"],
                        kwargs["approval_scope"],
                        kwargs["excerpt"],
                    )
        self.assertIsNone(
            self.store.latest_approval("s1", "authorization-scope", "user_authorization")
        )

    def test_lookup_tools_resolve_whitespace_task_scope_to_unique_active_mission(self) -> None:
        self.server.mission_lock("s1", "unique-active", "goal", ["criterion"])
        receipt = self.make_receipt("unique-active")
        self.server.turn_end_gate(
            "s1",
            "unique-active",
            "slice_verified",
            "Recorded one verified slice so lookup APIs can expose mission-scoped state.",
            [receipt.receipt_id],
        )
        self.server.record_user_authorization(
            "s1",
            "unique-active",
            "push gitea",
            "single push",
            "approved",
        )

        budget = json.loads(self.server.budget_status("s1", " "))
        auth = json.loads(self.server.authorization_status("s1", "\t"))
        handoff = json.loads(self.server.export_handoff_packet("s1", "\n"))

        self.assertEqual("unique-active", auth["task_id"])
        self.assertEqual("unique-active", handoff["mission"]["task_id"])
        self.assertEqual(1, budget["slice_count"])
        self.assertTrue(budget["latest_turn_gate_fresh"])
        self.assertTrue(handoff["latest_turn_gate"]["fresh"])
        self.assertTrue(handoff["latest_user_authorization"]["fresh"])

    def test_mission_lock_rejects_invalid_budget_values(self) -> None:
        cases = [
            ({"slice_budget": 0}, "slice_budget"),
            ({"retry_budget": 0}, "retry_budget"),
            ({"time_budget_minutes": -1}, "time_budget_minutes"),
        ]
        for kwargs, fragment in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, fragment):
                    self.server.mission_lock("s1", "bad-budget", "goal", ["criterion"], **kwargs)

    def test_mission_lock_rejects_unknown_adversarial_audit_profiles(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown adversarial profile"):
            self.server.mission_lock(
                "s1",
                "bad-profile",
                "goal",
                ["criterion"],
                adversarial_audit_required=True,
                adversarial_audit_profiles=["nonexistent_profile"],
            )

    def test_mission_lock_rejects_required_adversarial_audit_without_profile_or_claims(self) -> None:
        cases = [
            (
                {},
                "adversarial_audit_profile",
            ),
            (
                {"adversarial_audit_profiles": ["runtime_gate_adversary"]},
                "adversarial_audit_claim",
            ),
        ]
        for kwargs, fragment in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, fragment):
                    self.server.mission_lock(
                        "s1",
                        f"bad-required-audit-{fragment}",
                        "goal",
                        ["criterion"],
                        adversarial_audit_required=True,
                        **kwargs,
                    )

    def test_mission_lock_rejects_extremely_long_completion_criteria(self) -> None:
        long_criterion = "x" * (self.server.MAX_COMPLETION_CRITERION_CHARS + 1)

        with self.assertRaisesRegex(ValueError, "completion criterion"):
            self.server.mission_lock("s1", "long-criterion", "goal", [long_criterion])

    def test_completion_gate_rejects_direct_completion_when_no_turn_gate_exists(self) -> None:
        self.server.mission_lock("s1", "direct-completion", "goal", ["criterion"])
        receipt = self.make_receipt("direct-completion")

        rejected = self.server.completion_gate(
            "s1",
            "direct-completion",
            "Completed directly with concrete criterion-to-receipt evidence in one slice.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("fresh approved turn_end_gate", rejected)
        status = self.server.mission_status("s1", "direct-completion")
        self.assertIn("status: active", status)
        self.assertNotIn("latest_turn_gate:", status)

    def test_completion_gate_rejects_after_rejected_pending_turn_end_gate(self) -> None:
        self.server.mission_lock("s1", "pending-turn", "goal", ["criterion"])
        receipt = self.make_receipt("pending-turn")
        turn = self.server.turn_end_gate(
            "s1",
            "pending-turn",
            "slice_verified",
            "Verified one slice but still listed local work that must be done later.",
            [receipt.receipt_id],
            pending_actions_identified=["run full regression"],
        )
        self.assertIn("REJECTED", turn)

        rejected = self.server.completion_gate(
            "s1",
            "pending-turn",
            "Attempted to complete after the latest turn gate had explicit pending work.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("fresh approved turn_end_gate", rejected)

    def test_completion_gate_rejects_receipts_not_covered_by_latest_turn_gate(self) -> None:
        self.server.mission_lock("s1", "turn-receipt-binding", "goal", ["criterion"])
        first_turn_receipt = self.make_receipt("turn-receipt-binding")
        completion_receipt = self.make_receipt("turn-receipt-binding")
        latest_turn_receipt = self.make_receipt("turn-receipt-binding")
        approved_turn = self.server.turn_end_gate(
            "s1",
            "turn-receipt-binding",
            "slice_verified",
            "Verified one slice with direct evidence before completion.",
            [first_turn_receipt.receipt_id, latest_turn_receipt.receipt_id],
        )
        self.assertIn("APPROVED", approved_turn)

        rejected = self.server.completion_gate(
            "s1",
            "turn-receipt-binding",
            "Attempted to complete using a receipt not covered by the latest turn gate.",
            [{"criterion": "criterion", "receipt_ids": [completion_receipt.receipt_id]}],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("covered by the latest approved turn_end_gate", rejected)

    def test_completion_gate_rejects_after_stuck_escalation_without_new_verified_slice(self) -> None:
        self.server.mission_lock(
            "s1",
            "stuck-then-complete",
            "goal",
            ["tests pass"],
            retry_budget=1,
        )
        failed = self.make_receipt("stuck-then-complete")
        self.server.record_stuck_attempt(
            "s1",
            "stuck-then-complete",
            "first-strategy",
            "first concrete strategy reproduced the failure",
            [failed.receipt_id],
        )
        escalation = self.server.turn_end_gate(
            "s1",
            "stuck-then-complete",
            "stuck_escalation",
            "Exhausted the configured retry budget with concrete recorded failed attempts.",
            [failed.receipt_id],
            reason_for_stopping="all retry strategies were exhausted and further local retries are not justified",
        )
        self.assertIn("APPROVED", escalation)
        rejected = self.server.completion_gate(
            "s1",
            "stuck-then-complete",
            "Attempted to complete after stuck escalation without a new verified slice gate.",
            [{"criterion": "tests pass", "receipt_ids": [failed.receipt_id]}],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("latest turn_end_gate stop_condition", rejected)

    def test_completion_gate_rejects_after_stuck_attempt_without_new_verified_slice(self) -> None:
        self.server.mission_lock(
            "s1",
            "stuck-attempt-then-complete",
            "goal",
            ["tests pass"],
            retry_budget=2,
        )
        success = self.make_receipt("stuck-attempt-then-complete")
        failed = self.store.record_receipt(
            session_id="s1",
            task_id="stuck-attempt-then-complete",
            source="test",
            tool_name="Bash",
            command_text="pytest failing-path.py",
            exit_code=1,
            metadata={"stdout_sha256": "failed"},
        )
        self.approve_turn_for_receipt("stuck-attempt-then-complete", success.receipt_id)
        self.server.record_stuck_attempt(
            "s1",
            "stuck-attempt-then-complete",
            "failing-path",
            "recorded a later failed path after the verified slice",
            [failed.receipt_id],
        )

        rejected = self.server.completion_gate(
            "s1",
            "stuck-attempt-then-complete",
            "Attempted to complete using a verified slice from before a stuck attempt.",
            [{"criterion": "tests pass", "receipt_ids": [success.receipt_id]}],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("new verified slice", rejected)

    def test_mission_lock_rejects_visually_duplicate_completion_criteria(self) -> None:
        cases = [
            ["Fix Bug", "fix bug"],
            ["fix bug\u200b", "fix bug"],
            ["fix bug\x00", "fix bug"],
            ["Cafe\u0301 report", "café report"],
            ["update\ufe0f report", "UPDATE report"],
        ]
        for index, criteria in enumerate(cases):
            with self.subTest(criteria=criteria):
                with self.assertRaisesRegex(
                    ValueError, "duplicate completion criterion|invisible/control"
                ):
                    self.server.mission_lock("s1", f"visual-dup-{index}", "goal", criteria)

    def test_mission_lock_allows_distinct_completion_criteria_after_normalization(self) -> None:
        result = self.server.mission_lock(
            "s1",
            "distinct-criteria",
            "goal",
            ["fix parser", "fix renderer"],
        )

        self.assertIn("MISSION LOCKED", result)
        status = self.server.mission_status("s1", "distinct-criteria")
        self.assertIn("fix parser", status)
        self.assertIn("fix renderer", status)

    def test_completion_gate_still_requires_exact_stored_criterion_text(self) -> None:
        self.server.mission_lock("s1", "exact-criterion", "goal", ["Fix Parser"])
        receipt = self.make_receipt("exact-criterion")

        rejected = self.server.completion_gate(
            "s1",
            "exact-criterion",
            "Mapped a case-folded criterion variant to prove storage text remains exact.",
            [{"criterion": "fix parser", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("Missing criterion mappings", rejected)
        self.assertIn("Unknown criterion mappings", rejected)

    def test_record_decision_record_rejects_trivial_quality_text(self) -> None:
        self.server.mission_lock("s1", "decision-quality", "goal", ["criterion"])
        receipt = self.make_receipt("decision-quality")

        with self.assertRaisesRegex(ValueError, "decision record"):
            self.server.record_decision_record(
                "s1",
                "decision-quality",
                "ok",
                "do it",
                ["other"],
                [receipt.receipt_id],
                "reversible",
                ["later"],
            )

    def test_record_counterexample_check_rejects_trivial_quality_text(self) -> None:
        self.server.mission_lock("s1", "counterexample-quality", "goal", ["criterion"])
        receipt = self.make_receipt("counterexample-quality")

        with self.assertRaisesRegex(ValueError, "counterexample check"):
            self.server.record_counterexample_check(
                "s1",
                "counterexample-quality",
                "ok",
                ["check"],
                "done",
                [receipt.receipt_id],
                "risk",
            )

    def test_record_counterexample_check_rejects_vague_outcome_even_with_specific_context(
        self,
    ) -> None:
        cases = [
            ("english", "done"),
            ("chinese", "完成"),
            ("german", "erledigt"),
            ("french", "terminé"),
            ("spanish", "hecho"),
            ("portuguese", "feito"),
            ("japanese", "完了"),
            ("korean", "완료"),
        ]
        for index, (language, outcome) in enumerate(cases, start=1):
            task_id = f"counterexample-outcome-quality-{index}"
            with self.subTest(language=language, outcome=outcome):
                self.server.mission_lock("s1", task_id, "goal", ["criterion"])
                receipt = self.make_receipt(task_id)

                with self.assertRaisesRegex(ValueError, "specific outcome"):
                    self.server.record_counterexample_check(
                        "s1",
                        task_id,
                        "task-scoped receipt proves the current mission boundary",
                        ["submitted a sibling-task receipt against the same gate"],
                        outcome,
                        [receipt.receipt_id],
                        "cross-host attribution could still hide provenance drift",
                    )

    def test_record_counterexample_check_rejects_empty_outcome_before_specificity_check(
        self,
    ) -> None:
        self.server.mission_lock("s1", "counterexample-empty-outcome", "goal", ["criterion"])
        receipt = self.make_receipt("counterexample-empty-outcome")

        with self.assertRaisesRegex(ValueError, "outcome must not be empty"):
            self.server.record_counterexample_check(
                "s1",
                "counterexample-empty-outcome",
                "task-scoped receipt proves the current mission boundary",
                ["submitted a sibling-task receipt against the same gate"],
                " ",
                [receipt.receipt_id],
                "cross-host attribution could still hide provenance drift",
            )

    def test_record_counterexample_check_accepts_specific_multilingual_outcomes(
        self,
    ) -> None:
        cases = [
            (
                "counterexample-outcome-english",
                "sibling-task receipt was rejected before the governance record was accepted",
            ),
            ("counterexample-outcome-chinese", "相邻任务证据已被拒绝保留残余风险"),
            (
                "counterexample-outcome-german",
                "Der Beleg der Nebenaufgabe wurde vor der Annahme abgelehnt",
            ),
            (
                "counterexample-outcome-french",
                "Le reçu de tâche voisine a été rejeté avant acceptation",
            ),
            (
                "counterexample-outcome-spanish",
                "El recibo de tarea vecina fue rechazado antes de aceptar el registro",
            ),
            (
                "counterexample-outcome-portuguese",
                "O recibo da tarefa vizinha foi rejeitado antes da aceitação",
            ),
            (
                "counterexample-outcome-japanese",
                "隣接タスク証拠は受理前に拒否され残余リスクを残した",
            ),
            (
                "counterexample-outcome-korean",
                "인접 작업 증거는 승인 전에 거부되었고 잔여 위험이 남았다",
            ),
        ]
        for task_id, outcome in cases:
            with self.subTest(task_id=task_id):
                self.server.mission_lock("s1", task_id, "goal", ["criterion"])
                receipt = self.make_receipt(task_id)

                counterexample = self.server.record_counterexample_check(
                    "s1",
                    task_id,
                    "task-scoped receipt proves the current mission boundary",
                    ["submitted a sibling-task receipt against the same gate"],
                    outcome,
                    [receipt.receipt_id],
                    "cross-host attribution could still hide provenance drift",
                )

                self.assertIn("COUNTEREXAMPLE CHECK RECORDED", counterexample)

    def test_governance_records_accept_concise_but_specific_quality_text(self) -> None:
        self.server.mission_lock("s1", "governance-quality", "goal", ["criterion"])
        receipt = self.make_receipt("governance-quality")

        decision = self.server.record_decision_record(
            "s1",
            "governance-quality",
            "keep host-scoped receipt path",
            "accept task-scoped host receipt only",
            ["accept taskless receipt by default"],
            [receipt.receipt_id],
            "reversible",
            ["host starts emitting scoped receipts"],
        )
        counterexample = self.server.record_counterexample_check(
            "s1",
            "governance-quality",
            "task-scoped receipt proves the right mission boundary",
            ["tried a sibling-task receipt against the same gate"],
            "sibling-task receipt was rejected before the governance record was accepted",
            [receipt.receipt_id],
            "cross-host attribution could still hide provenance drift",
        )

        self.assertIn("DECISION RECORDED", decision)
        self.assertIn("COUNTEREXAMPLE CHECK RECORDED", counterexample)

    def test_turn_end_gate_rejects_pending_actions_on_verified_stop_conditions(self) -> None:
        cases = [
            ("slice_verified", "Verified the current slice with direct receipt evidence."),
            ("frontier_exhausted", "Exhausted all reachable work frontiers with direct receipt evidence."),
        ]
        for stop_condition, summary in cases:
            task_id = f"pending-{stop_condition}"
            with self.subTest(stop_condition=stop_condition):
                self.server.mission_lock("s1", task_id, "goal", ["criterion"])
                receipt = self.make_receipt(task_id)

                rejected = self.server.turn_end_gate(
                    "s1",
                    task_id,
                    stop_condition,
                    summary,
                    [receipt.receipt_id],
                    pending_actions_identified=["still need to run linter"],
                )

                self.assertIn("REJECTED", rejected)

    def test_turn_end_gate_rejects_hidden_pending_actions_in_stop_reason(self) -> None:
        cases = [
            ("hidden-pending-en", "Bounded slice complete; next local slice is the archive verification matrix."),
            ("hidden-pending-followup", "The follow-up work is to inspect the archive bug matrix."),
            ("hidden-pending-cn", "当前切片已验证；下一步继续处理归档验证矩阵。"),
            ("hidden-pending-cn-todo", "当前切片已验证；待办是继续处理归档验证矩阵。"),
        ]
        for task_id, reason in cases:
            with self.subTest(reason=reason):
                self.server.mission_lock("s1", task_id, "goal", ["criterion"])
                receipt = self.make_receipt(task_id)

                rejected = self.server.turn_end_gate(
                    "s1",
                    task_id,
                    "slice_verified",
                    "Verified the current bounded slice with direct receipt evidence.",
                    [receipt.receipt_id],
                    reason_for_stopping=reason,
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("pending", rejected.lower())

    def test_turn_end_gate_rejects_pending_actions_hidden_in_work_summary(self) -> None:
        self.server.mission_lock("s1", "hidden-summary", "goal", ["criterion"])
        receipt = self.make_receipt("hidden-summary")

        rejected = self.server.turn_end_gate(
            "s1",
            "hidden-summary",
            "frontier_exhausted",
            "Exhausted the frontier for now; next step is to continue the remaining local repair slice after this stop.",
            [receipt.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("work_summary", rejected)

    def test_turn_end_gate_rejects_pending_actions_hidden_in_assumptions_remaining(self) -> None:
        self.server.mission_lock("s1", "hidden-assumptions", "goal", ["criterion"])
        receipt = self.make_receipt("hidden-assumptions")

        rejected = self.server.turn_end_gate(
            "s1",
            "hidden-assumptions",
            "frontier_exhausted",
            "Exhausted the currently reachable frontier with direct evidence and bounded scope reporting.",
            [receipt.receipt_id],
            assumptions_remaining=["后续继续执行剩余本地回归和导出。"],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("assumptions_remaining", rejected)

    def test_turn_end_gate_rejects_hidden_high_value_continuation_debt(self) -> None:
        self.server.mission_lock(
            "s1",
            "long-horizon-research",
            "long horizon factor mining",
            ["current slice is machine-checkable"],
            slice_budget=10,
            time_budget_minutes=90,
        )
        receipt = self.make_receipt("long-horizon-research")

        rejected = self.server.turn_end_gate(
            "s1",
            "long-horizon-research",
            "slice_verified",
            "Verified the current bounded research slice with direct receipt evidence.",
            [receipt.receipt_id],
            pending_actions_identified=[],
            reason_for_stopping=(
                "The current bounded judgement slice is verified. Starting the next "
                "campaign would require a separate bounded startup."
            ),
            assumptions_remaining=[
                "The next highest-value campaign remains new alpha source or template redesign."
            ],
            known_risks=["Future research budget still needs a bounded execution plan."],
            unverified_items=["No new alpha-source/template-redesign campaign was started."],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("assumptions_remaining", rejected)
        self.assertIn("known_risks", rejected)
        self.assertIn("unverified_items", rejected)

    def test_turn_end_gate_allows_next_step_wording_for_approval_required(self) -> None:
        self.server.mission_lock("s1", "approval-next-step", "goal", ["criterion"])
        receipt = self.make_receipt("approval-next-step")

        approved = self.server.turn_end_gate(
            "s1",
            "approval-next-step",
            "approval_required",
            "Identified an externally visible next step that requires explicit user approval.",
            [receipt.receipt_id],
            pending_actions_identified=["push to Gitea after approval"],
            reason_for_stopping="The next step is externally visible and requires explicit approval before execution.",
        )

        self.assertIn("APPROVED", approved)

    def test_turn_end_gate_allows_negated_pending_work_wording_for_frontier_exhausted(self) -> None:
        cases = [
            ("frontier-no-remaining", "No remaining work is locally reachable after the verified checks."),
            ("frontier-cannot-continue", "Cannot continue with local work because every available path is blocked."),
            ("frontier-cn-no-followup", "无需后续本地工作，当前可达任务边界已经耗尽。"),
        ]
        for task_id, reason in cases:
            with self.subTest(reason=reason):
                self.server.mission_lock("s1", task_id, "goal", ["criterion"])
                first = self.make_receipt(task_id)
                first_gate = self.server.turn_end_gate(
                    "s1",
                    task_id,
                    "slice_verified",
                    "Verified the current evidence before checking frontier exhaustion.",
                    [first.receipt_id],
                )
                self.assertIn("APPROVED", first_gate)
                receipt = self.make_receipt(task_id)

                approved = self.server.turn_end_gate(
                    "s1",
                    task_id,
                    "frontier_exhausted",
                    "Verified the current evidence and found no reachable local continuation path.",
                    [receipt.receipt_id],
                    reason_for_stopping=reason,
                )

                self.assertIn("APPROVED", approved)

    def test_turn_end_gate_allows_pending_actions_for_user_information_required(self) -> None:
        self.server.mission_lock("s1", "info-task", "goal", ["criterion"])
        receipt = self.make_receipt("info-task")

        approved = self.server.turn_end_gate(
            "s1",
            "info-task",
            "user_information_required",
            "Need user-provided credentials before the next execution step can proceed.",
            [receipt.receipt_id],
            pending_actions_identified=["run tests after user provides DSN"],
            reason_for_stopping="Cannot test the database path without credentials supplied by the user.",
        )

        self.assertIn("APPROVED", approved)

    def test_turn_end_gate_propagates_assumptions_remaining(self) -> None:
        self.server.mission_lock("s1", "assumption-task", "goal", ["criterion"])
        receipt = self.make_receipt("assumption-task")

        approved = self.server.turn_end_gate(
            "s1",
            "assumption-task",
            "slice_verified",
            "Verified the core path with direct execution evidence for this slice.",
            [receipt.receipt_id],
            assumptions_remaining=["assuming test env matches prod"],
        )

        self.assertIn("assuming test env matches prod", approved)

    def test_turn_end_gate_warns_verified_slice_is_not_final_completion(self) -> None:
        self.server.mission_lock("s1", "active-slice-warning", "goal", ["criterion"])
        receipt = self.make_receipt("active-slice-warning")

        approved = self.server.turn_end_gate(
            "s1",
            "active-slice-warning",
            "slice_verified",
            "Verified one bounded slice with direct receipt evidence and preserved remaining mission work.",
            [receipt.receipt_id],
        )

        self.assertIn("APPROVED", approved)
        self.assertIn("mission_active", approved)
        self.assertIn("completion_gate", approved)
        packet = json.loads(self.server.export_handoff_packet("s1", "active-slice-warning"))
        turn_meta = packet["latest_turn_gate"]["meta"]
        self.assertTrue(turn_meta["mission_active_after_gate"])

    def test_completion_gate_preserves_existing_mission_notes(self) -> None:
        self.server.mission_lock("s1", "completion-notes-task", "goal", ["tests pass"])
        notes = dict(self.store.get_mission("s1", "completion-notes-task").notes)
        notes["custom"] = "keep"
        self.store.update_mission_notes("s1", "completion-notes-task", notes)
        receipt = self.make_receipt("completion-notes-task")
        self.approve_turn_for_receipt("completion-notes-task", receipt.receipt_id)

        approved = self.server.completion_gate(
            "s1",
            "completion-notes-task",
            "Mapped the tests pass criterion to a fresh pytest receipt while preserving notes.",
            [{"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}],
        )

        completed = self.store.get_mission("s1", "completion-notes-task")
        self.assertIn("APPROVED", approved)
        self.assertEqual("completed", completed.status)
        self.assertEqual("keep", completed.notes["custom"])
        self.assertIn("mission_start_receipt_seq", completed.notes)
        self.assertIn("completion_summary", completed.notes)

    def test_completion_gate_rejects_pending_local_work_in_completion_summary(self) -> None:
        self.server.mission_lock("s1", "completion-summary-pending", "goal", ["criterion"])
        receipt = self.make_receipt("completion-summary-pending")

        rejected = self.server.completion_gate(
            "s1",
            "completion-summary-pending",
            "Completed the task with direct evidence; next step is to continue the remaining local repair slice.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("completion_summary", rejected)

    def test_completion_gate_rejects_pending_local_work_in_known_risks(self) -> None:
        self.server.mission_lock("s1", "completion-risk-pending", "goal", ["criterion"])
        receipt = self.make_receipt("completion-risk-pending")

        rejected = self.server.completion_gate(
            "s1",
            "completion-risk-pending",
            "Completed the task with direct evidence and explicit reporting.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
            known_risks=["Residual risk: 下一步 still need to continue the remaining local repair slice."],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("known_risks", rejected)

    def test_completion_gate_rejects_pending_local_work_in_unverified_items(self) -> None:
        self.server.mission_lock("s1", "completion-unverified-pending", "goal", ["criterion"])
        receipt = self.make_receipt("completion-unverified-pending")

        rejected = self.server.completion_gate(
            "s1",
            "completion-unverified-pending",
            "Completed the task with direct evidence and explicit reporting.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
            unverified_items=['User asked to "continue the remaining local packaging check" later.'],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("unverified_items", rejected)

    def test_completion_gate_without_active_mission_raises_before_approval(self) -> None:
        receipt = self.make_receipt("missing-task")

        with self.assertRaisesRegex(ValueError, "No active mission"):
            self.server.completion_gate(
                "s1",
                "missing-task",
                "Tried to complete a task that has no active mission.",
                [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
            )
        self.assertIsNone(
            self.store.latest_approval("s1", "missing-task", "completion_gate")
        )

    def test_turn_end_gate_without_active_mission_raises_before_approval(self) -> None:
        receipt = self.make_receipt("missing-task")

        with self.assertRaisesRegex(ValueError, "No active mission"):
            self.server.turn_end_gate(
                "s1",
                "missing-task",
                "slice_verified",
                "Tried to claim a verified slice for a task that has no active mission.",
                [receipt.receipt_id],
            )
        self.assertIsNone(
            self.store.latest_approval("s1", "missing-task", "turn_end_gate")
        )

    def test_completion_gate_after_completion_raises_no_active_mission(self) -> None:
        self.server.mission_lock("s1", "done-task", "goal", ["criterion"])
        receipt = self.make_receipt("done-task")
        self.approve_turn_for_receipt("done-task", receipt.receipt_id)
        first = self.server.completion_gate(
            "s1",
            "done-task",
            "Completed the task with verified evidence and a concrete completion summary.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        self.assertIn("APPROVED", first)
        with self.assertRaisesRegex(ValueError, "No active mission"):
            self.server.completion_gate(
                "s1",
                "done-task",
                "Attempted to complete the same task again with the same evidence.",
                [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
            )

    def test_turn_end_gate_after_completion_raises_no_active_mission(self) -> None:
        self.server.mission_lock("s1", "done-turn-task", "goal", ["criterion"])
        receipt = self.make_receipt("done-turn-task")
        self.approve_turn_for_receipt("done-turn-task", receipt.receipt_id)
        self.server.completion_gate(
            "s1",
            "done-turn-task",
            "Completed the task with verified evidence and a concrete completion summary.",
            [{"criterion": "criterion", "receipt_ids": [receipt.receipt_id]}],
        )

        with self.assertRaisesRegex(ValueError, "No active mission"):
            self.server.turn_end_gate(
                "s1",
                "done-turn-task",
                "slice_verified",
                "Tried to claim another verified slice after the mission was already completed.",
                [receipt.receipt_id],
            )


if __name__ == "__main__":
    unittest.main()
