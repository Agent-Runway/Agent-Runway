from __future__ import annotations

import importlib
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path


class SubagentSupervisionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")
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

    def lock_parent(self) -> None:
        self.server.mission_lock(
            "subagent-session",
            "parent-task",
            "delegate review work",
            ["tests pass"],
        )

    def start_child(self) -> dict:
        return json.loads(
            self.server.register_subagent_start(
                session_id="subagent-session",
                task_id="parent-task",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={
                    "max_slices": 2,
                    "max_tool_calls": 5,
                    "max_elapsed_seconds": 120,
                },
                host="claude-code",
                host_child_id="agent-123",
                context_mode="fresh",
                workspace_kind="shared_checkout",
            )
        )

    def start_child_in_workspace(self, workspace_kind: str) -> dict:
        return json.loads(
            self.server.register_subagent_start(
                session_id="subagent-session",
                task_id="parent-task",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={"max_tool_calls": 5},
                workspace_kind=workspace_kind,
            )
        )

    def child_receipt(self, child_span_id: str):
        return self.store.record_receipt(
            session_id="subagent-session",
            task_id="parent-task",
            source="child-test",
            tool_name="Bash",
            command_text="python -m unittest mcp.tests.test_subagent_supervision",
            exit_code=0,
            metadata={"child_span_id": child_span_id},
        )

    def parent_receipt(self):
        return self.store.record_receipt(
            session_id="subagent-session",
            task_id="parent-task",
            source="parent-test",
            tool_name="Bash",
            command_text="python -m unittest mcp.tests.test_runtime",
            exit_code=0,
            metadata={"stdout_sha256": "parent"},
        )

    def approve_parent_turn(
        self,
        receipt_ids: list[str],
        known_risks: list[str] | None = None,
        unverified_items: list[str] | None = None,
    ) -> None:
        approved = self.server.turn_end_gate(
            session_id="subagent-session",
            task_id="parent-task",
            stop_condition="slice_verified",
            work_summary="Verified the parent slice with direct evidence before completion.",
            receipt_ids=receipt_ids,
            known_risks=known_risks,
            unverified_items=unverified_items,
        )
        self.assertIn("APPROVED", approved)

    def test_register_subagent_start_creates_running_child_span(self) -> None:
        self.lock_parent()

        child = self.start_child()

        self.assertTrue(child["child_span_id"].startswith("child_"))
        self.assertEqual(child["status"], "running")
        self.assertEqual(child["subagent_type"], "code-reviewer")
        self.assertEqual(child["delegated_budget"]["max_tool_calls"], 5)
        status = json.loads(self.server.subagent_status("subagent-session", "parent-task"))
        self.assertEqual(status["summary"]["running"], 1)
        self.assertEqual(status["child_spans"][0]["child_span_id"], child["child_span_id"])

    def test_subagent_status_reports_zero_counts_without_children(self) -> None:
        self.lock_parent()

        status = json.loads(self.server.subagent_status("subagent-session", "parent-task"))

        self.assertEqual(status["summary"]["total"], 0)
        self.assertEqual(status["summary"]["running"], 0)
        self.assertEqual(status["summary"]["completed"], 0)
        self.assertEqual(status["summary"]["failed"], 0)
        self.assertEqual(status["child_spans"], [])

    def test_runtime_store_initializes_subagent_tables_and_indexes(self) -> None:
        expected_tables = {"subagent_spans", "subagent_handoffs"}
        expected_indexes = {"idx_subagent_spans_lookup", "idx_subagent_handoffs_lookup"}
        expected_columns = {"parent_receipt_seq", "terminal_receipt_seq"}

        with closing(sqlite3.connect(self.db_path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
            span_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(subagent_spans)").fetchall()
            }

        self.assertTrue(expected_tables <= tables)
        self.assertTrue(expected_indexes <= indexes)
        self.assertTrue(expected_columns <= span_columns)

    def test_register_subagent_start_rejects_invalid_context_mode(self) -> None:
        self.lock_parent()

        with self.assertRaisesRegex(ValueError, "context_mode"):
            self.server.register_subagent_start(
                session_id="subagent-session",
                task_id="parent-task",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={"max_slices": 1},
                context_mode="telepathy",
            )

    def test_register_subagent_start_rejects_invalid_workspace_kind(self) -> None:
        self.lock_parent()

        with self.assertRaisesRegex(ValueError, "workspace_kind"):
            self.server.register_subagent_start(
                session_id="subagent-session",
                task_id="parent-task",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={"max_slices": 1},
                workspace_kind="moonbase",
            )

    def test_register_subagent_start_accepts_dev_book_enums(self) -> None:
        self.lock_parent()

        child = json.loads(
            self.server.register_subagent_start(
                session_id="subagent-session",
                task_id="parent-task",
                subagent_type="code-reviewer",
                delegated_scope="review parser changes only",
                delegated_budget={"max_slices": 1},
                context_mode="fork",
                workspace_kind="local_sandbox",
            )
        )

        self.assertEqual(child["context_mode"], "fork")
        self.assertEqual(child["workspace_kind"], "local_sandbox")

    def test_record_subagent_handoff_rejects_summary_only_claims(self) -> None:
        self.lock_parent()
        child = self.start_child()

        with self.assertRaisesRegex(ValueError, "receipt_id"):
            self.server.record_subagent_handoff(
                session_id="subagent-session",
                task_id="parent-task",
                child_span_id=child["child_span_id"],
                summary="Child says the review is complete, but no receipts were supplied.",
                verified_claims=[{"claim": "review completed"}],
                receipt_ids=[],
                risks=[],
                unverified_items=[],
            )

    def test_record_subagent_handoff_rejects_parent_receipt_laundering(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.parent_receipt()

        with self.assertRaisesRegex(ValueError, "child_span_id"):
            self.server.record_subagent_handoff(
                session_id="subagent-session",
                task_id="parent-task",
                child_span_id=child["child_span_id"],
                summary="Child tried to cite a parent receipt as child evidence.",
                verified_claims=[{"claim": "targeted tests passed"}],
                receipt_ids=[receipt.receipt_id],
                risks=[],
                unverified_items=[],
            )

    def test_record_subagent_handoff_rejects_non_object_verified_claims(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])

        with self.assertRaisesRegex(ValueError, "verified_claims"):
            self.server.record_subagent_handoff(
                session_id="subagent-session",
                task_id="parent-task",
                child_span_id=child["child_span_id"],
                summary="Child tried to submit malformed verified claim entries.",
                verified_claims=["targeted tests passed"],
                receipt_ids=[receipt.receipt_id],
                risks=[],
                unverified_items=[],
            )

    def test_subagent_handoff_and_stop_roll_up_to_status(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])

        handoff = json.loads(
            self.server.record_subagent_handoff(
                session_id="subagent-session",
                task_id="parent-task",
                child_span_id=child["child_span_id"],
                summary="Child ran the requested test command and reported the receipt.",
                verified_claims=[{"claim": "targeted tests passed"}],
                receipt_ids=[receipt.receipt_id],
                risks=["parent must still review final diff"],
                unverified_items=[],
            )
        )
        stopped = json.loads(
            self.server.register_subagent_stop(
                session_id="subagent-session",
                task_id="parent-task",
                child_span_id=child["child_span_id"],
                status="completed",
                budget_consumed={"slices": 1, "tool_calls": 1, "elapsed_seconds": 10},
                transcript_ref="artifact://child-transcript",
                artifact_refs=["artifact://child-report"],
                last_message="Test receipt returned to parent.",
            )
        )

        status = json.loads(self.server.subagent_status("subagent-session", "parent-task"))
        span = status["child_spans"][0]
        self.assertEqual(handoff["receipt_ids"], [receipt.receipt_id])
        self.assertEqual(stopped["status"], "completed")
        self.assertEqual(status["summary"]["completed"], 1)
        self.assertEqual(span["handoff_count"], 1)
        self.assertEqual(span["verified_receipt_count"], 1)
        self.assertEqual(span["latest_handoff"]["receipt_ids"], [receipt.receipt_id])
        self.assertEqual(span["budget_consumed"]["tool_calls"], 1)

    def test_completion_gate_rejects_subagent_handoff_id_as_receipt(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])
        handoff = json.loads(
            self.server.record_subagent_handoff(
                session_id="subagent-session",
                task_id="parent-task",
                child_span_id=child["child_span_id"],
                summary="Child returned a real receipt, but parent tries to cite handoff id.",
                verified_claims=[{"claim": "targeted tests passed"}],
                receipt_ids=[receipt.receipt_id],
                risks=[],
                unverified_items=[],
            )
        )

        with self.assertRaisesRegex(ValueError, "handoff.*not.*receipt"):
            self.server.completion_gate(
                session_id="subagent-session",
                task_id="parent-task",
                criterion_receipt_map=[
                    {
                        "criterion": "tests pass",
                        "receipt_ids": [f"subagent_handoff:{handoff['handoff_id']}"],
                    }
                ],
                completion_summary="Parent tried to use the child handoff id as completion evidence.",
            )

    def test_completion_gate_rejects_child_receipt_without_handoff(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])

        rejected = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent tried to use a child receipt before child handoff.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("child handoff", rejected)

    def test_completion_gate_rejects_receipt_with_unknown_child_span(self) -> None:
        self.lock_parent()
        receipt = self.child_receipt("child_missing")

        rejected = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent tried to use a receipt from an unknown child span.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("unknown child_span_id", rejected)

    def test_completion_gate_rejects_while_child_span_is_running(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.parent_receipt()

        rejected = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent tried to complete while delegated child work was still running.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("running child span", rejected)
        self.assertIn(child["child_span_id"], rejected)

    def test_completion_gate_rejects_failed_child_without_disclosure(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.parent_receipt()
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="failed",
            budget_consumed={"tool_calls": 1},
            last_message="Child could not finish the delegated review.",
        )

        rejected = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent tried to complete without disclosing failed delegated work.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("failed child span", rejected)
        self.assertIn(child["child_span_id"], rejected)

    def test_completion_gate_accepts_failed_child_when_disclosed_as_risk(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.parent_receipt()
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="failed",
            budget_consumed={"tool_calls": 1},
            last_message="Child could not finish the delegated review.",
        )
        self.approve_parent_turn(
            [receipt.receipt_id],
            known_risks=[
                f"failed child span {child['child_span_id']} did not support completion evidence"
            ],
        )

        approved = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent completed using parent-owned verification and disclosed failed delegated work.",
            known_risks=[
                f"failed child span {child['child_span_id']} did not support completion evidence"
            ],
        )

        self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_child_budget_overrun_without_disclosure(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned evidence after exceeding delegated tool budget.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=[],
            unverified_items=[],
        )
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 6},
        )

        rejected = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent tried to treat over-budget delegated work as clean evidence.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("budget overrun", rejected)
        self.assertIn(child["child_span_id"], rejected)

    def test_completion_gate_accepts_child_budget_overrun_when_disclosed(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned evidence after exceeding delegated tool budget.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=[],
            unverified_items=[],
        )
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 6},
        )
        self.approve_parent_turn(
            [receipt.receipt_id],
            known_risks=[f"budget overrun for child span {child['child_span_id']} was reviewed"],
        )

        approved = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent used child evidence while disclosing delegated budget overrun.",
            known_risks=[f"budget overrun for child span {child['child_span_id']} was reviewed"],
        )

        self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_child_handoff_risks_without_disclosure(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned evidence but left a merge risk unresolved.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=["parent must inspect generated files before release"],
            unverified_items=["no package smoke test was run"],
        )
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 1},
        )

        rejected = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent tried to complete without carrying forward child handoff risks.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("child handoff", rejected)
        self.assertIn("parent must inspect generated files", rejected)
        self.assertIn("no package smoke test", rejected)

    def test_completion_gate_accepts_child_handoff_risks_when_disclosed(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned evidence but left a merge risk unresolved.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=["parent must inspect generated files before release"],
            unverified_items=["no package smoke test was run"],
        )
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 1},
        )
        self.approve_parent_turn(
            [receipt.receipt_id],
            known_risks=["parent must inspect generated files before release"],
            unverified_items=["no package smoke test was run"],
        )

        approved = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent completed while carrying forward child handoff disclosures.",
            known_risks=["parent must inspect generated files before release"],
            unverified_items=["no package smoke test was run"],
        )

        self.assertIn("APPROVED", approved)

    def test_turn_end_gate_rejects_failed_child_without_disclosure(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.parent_receipt()
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="failed",
            budget_consumed={"tool_calls": 1},
            last_message="Child could not finish the delegated review.",
        )

        rejected = self.server.turn_end_gate(
            session_id="subagent-session",
            task_id="parent-task",
            stop_condition="slice_verified",
            work_summary="Recorded a fresh parent verification receipt and tried to stop the slice as verified.",
            receipt_ids=[receipt.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("failed child span", rejected)
        self.assertIn(child["child_span_id"], rejected)

    def test_turn_end_gate_rejects_child_budget_overrun_without_disclosure(self) -> None:
        self.lock_parent()
        child = self.start_child()
        child_receipt = self.child_receipt(child["child_span_id"])
        parent_receipt = self.parent_receipt()
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned evidence after exceeding delegated tool budget.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[child_receipt.receipt_id],
            risks=[],
            unverified_items=[],
        )
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 6},
        )

        rejected = self.server.turn_end_gate(
            session_id="subagent-session",
            task_id="parent-task",
            stop_condition="slice_verified",
            work_summary="Recorded a parent verification receipt and tried to stop the slice as verified.",
            receipt_ids=[parent_receipt.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("budget overrun", rejected)
        self.assertIn(child["child_span_id"], rejected)

    def test_turn_end_gate_rejects_child_handoff_risks_without_rollup(self) -> None:
        self.lock_parent()
        child = self.start_child()
        child_receipt = self.child_receipt(child["child_span_id"])
        parent_receipt = self.parent_receipt()
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned evidence but left a merge risk unresolved.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[child_receipt.receipt_id],
            risks=["parent must inspect generated files before release"],
            unverified_items=["no package smoke test was run"],
        )
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 1},
            last_message="child returned delegated test evidence",
        )

        rejected = self.server.turn_end_gate(
            session_id="subagent-session",
            task_id="parent-task",
            stop_condition="frontier_exhausted",
            work_summary="Exhausted the reachable frontier for this parent slice with one direct parent verification receipt.",
            receipt_ids=[parent_receipt.receipt_id],
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("child handoff", rejected)
        self.assertIn("parent must inspect generated files", rejected)
        self.assertIn("no package smoke test", rejected)

    def test_completion_gate_accepts_child_receipt_after_handoff_and_stop(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned the receipt that supports the delegated test criterion.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=[],
            unverified_items=[],
        )
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 1},
        )
        self.approve_parent_turn([receipt.receipt_id])

        approved = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent used the completed child handoff receipt as delegated evidence.",
        )

        self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_sandbox_child_receipt_without_parent_reverify(self) -> None:
        self.lock_parent()
        child = self.start_child_in_workspace("local_sandbox")
        receipt = self.child_receipt(child["child_span_id"])
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned sandbox evidence that parent has not reverified.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=[],
            unverified_items=[],
        )
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 1},
        )

        rejected = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {"criterion": "tests pass", "receipt_ids": [receipt.receipt_id]}
            ],
            completion_summary="Parent tried to complete from sandbox child evidence without reverification.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("parent re-verification", rejected)
        self.assertIn(child["child_span_id"], rejected)

    def test_completion_gate_accepts_sandbox_child_receipt_with_parent_reverify(self) -> None:
        self.lock_parent()
        child = self.start_child_in_workspace("local_sandbox")
        receipt = self.child_receipt(child["child_span_id"])
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned sandbox evidence and parent reverified after it.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=[],
            unverified_items=[],
        )
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 1},
        )
        parent_receipt = self.parent_receipt()
        self.approve_parent_turn([receipt.receipt_id, parent_receipt.receipt_id])

        approved = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {
                    "criterion": "tests pass",
                    "receipt_ids": [receipt.receipt_id, parent_receipt.receipt_id],
                }
            ],
            completion_summary="Parent completed with sandbox child evidence and later parent reverification.",
        )

        self.assertIn("APPROVED", approved)

    def test_completion_gate_rejects_sandbox_reverify_from_different_criterion(self) -> None:
        self.server.mission_lock(
            "subagent-session",
            "parent-task",
            "delegate review work",
            ["sandbox tests pass", "final compile passes"],
        )
        child = self.start_child_in_workspace("local_sandbox")
        receipt = self.child_receipt(child["child_span_id"])
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned sandbox test evidence requiring parent-local re-verification.",
            verified_claims=[{"claim": "sandbox tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=[],
            unverified_items=[],
        )
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 1},
        )
        parent_receipt = self.parent_receipt()

        rejected = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {
                    "criterion": "sandbox tests pass",
                    "receipt_ids": [receipt.receipt_id],
                },
                {
                    "criterion": "final compile passes",
                    "receipt_ids": [parent_receipt.receipt_id],
                },
            ],
            completion_summary="Parent tried to use another criterion's verification for sandbox child evidence.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("criterion 'sandbox tests pass'", rejected)
        self.assertIn("parent re-verification", rejected)

    def test_completion_gate_rejects_sandbox_reverify_before_child_stop(self) -> None:
        self.lock_parent()
        child = self.start_child_in_workspace("local_sandbox")
        receipt = self.child_receipt(child["child_span_id"])
        parent_receipt = self.parent_receipt()
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned sandbox evidence after an earlier parent verification.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=[],
            unverified_items=[],
        )
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="completed",
            budget_consumed={"tool_calls": 1},
        )

        rejected = self.server.completion_gate(
            session_id="subagent-session",
            task_id="parent-task",
            criterion_receipt_map=[
                {
                    "criterion": "tests pass",
                    "receipt_ids": [receipt.receipt_id, parent_receipt.receipt_id],
                }
            ],
            completion_summary="Parent tried to count a verification that happened before child stop.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("parent re-verification", rejected)
        self.assertIn(child["child_span_id"], rejected)

    def test_subagent_status_repeated_reads_do_not_create_runtime_rows(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])
        self.server.record_subagent_handoff(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            summary="Child returned evidence for repeated status-read stability checks.",
            verified_claims=[{"claim": "targeted tests passed"}],
            receipt_ids=[receipt.receipt_id],
            risks=[],
            unverified_items=[],
        )

        for _ in range(25):
            payload = json.loads(self.server.subagent_status("subagent-session", "parent-task"))
            self.assertEqual(payload["summary"]["total"], 1)

        with closing(sqlite3.connect(self.db_path)) as conn:
            span_count = conn.execute("SELECT COUNT(*) FROM subagent_spans").fetchone()[0]
            handoff_count = conn.execute("SELECT COUNT(*) FROM subagent_handoffs").fetchone()[0]

        self.assertEqual(span_count, 1)
        self.assertEqual(handoff_count, 1)

    def test_register_subagent_stop_rejects_duplicate_terminal_update(self) -> None:
        self.lock_parent()
        child = self.start_child()
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="failed",
            budget_consumed={"tool_calls": 1},
        )

        with self.assertRaisesRegex(ValueError, "already terminal"):
            self.server.register_subagent_stop(
                session_id="subagent-session",
                task_id="parent-task",
                child_span_id=child["child_span_id"],
                status="completed",
                budget_consumed={"tool_calls": 2},
            )

    def test_store_stop_subagent_span_rejects_duplicate_terminal_update(self) -> None:
        self.lock_parent()
        child = self.start_child()
        self.store.stop_subagent_span(
            "subagent-session",
            "parent-task",
            child["child_span_id"],
            {
                "status": "failed",
                "budget_consumed": {"tool_calls": 1},
                "transcript_ref": "",
                "artifact_refs": [],
                "last_message": "",
            },
        )

        with self.assertRaisesRegex(ValueError, "already terminal"):
            self.store.stop_subagent_span(
                "subagent-session",
                "parent-task",
                child["child_span_id"],
                {
                    "status": "completed",
                    "budget_consumed": {"tool_calls": 2},
                    "transcript_ref": "",
                    "artifact_refs": [],
                    "last_message": "",
                },
            )

    def test_concurrent_store_stop_subagent_span_has_single_terminal_winner(self) -> None:
        self.lock_parent()
        child = self.start_child()
        successes = []
        errors: list[Exception] = []
        result_lock = threading.Lock()
        start = threading.Barrier(2)

        def worker(index: int, status: str) -> None:
            try:
                start.wait()
                span = self.store.stop_subagent_span(
                    "subagent-session",
                    "parent-task",
                    child["child_span_id"],
                    {
                        "status": status,
                        "budget_consumed": {"winner": index},
                        "transcript_ref": "",
                        "artifact_refs": [],
                        "last_message": f"terminal update {index}",
                    },
                )
                with result_lock:
                    successes.append((index, span))
            except Exception as exc:
                with result_lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(0, "failed")),
            threading.Thread(target=worker, args=(1, "completed")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, len(successes))
        self.assertEqual(1, len(errors))
        self.assertTrue(
            isinstance(errors[0], ValueError) and "already terminal" in str(errors[0])
        )
        winner_index, winner_span = successes[0]
        final = self.store.get_subagent_span(
            "subagent-session", "parent-task", child["child_span_id"]
        )
        self.assertEqual(winner_span.status, final.status)
        self.assertEqual({"winner": winner_index}, final.budget_consumed)
        self.assertEqual(f"terminal update {winner_index}", final.last_message)

    def test_record_subagent_handoff_rejects_after_terminal_stop(self) -> None:
        self.lock_parent()
        child = self.start_child()
        receipt = self.child_receipt(child["child_span_id"])
        self.server.register_subagent_stop(
            session_id="subagent-session",
            task_id="parent-task",
            child_span_id=child["child_span_id"],
            status="failed",
            budget_consumed={"tool_calls": 1},
        )

        with self.assertRaisesRegex(ValueError, "terminal"):
            self.server.record_subagent_handoff(
                session_id="subagent-session",
                task_id="parent-task",
                child_span_id=child["child_span_id"],
                summary="Child tried to add evidence after terminal failure status.",
                verified_claims=[{"claim": "targeted tests passed"}],
                receipt_ids=[receipt.receipt_id],
                risks=[],
                unverified_items=[],
            )


if __name__ == "__main__":
    unittest.main()
