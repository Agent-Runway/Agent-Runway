from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


class FindBug0515DeepenedGapTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["ILH_DB_PATH"] = str(Path(self.temp_dir.name) / "state.db")
        os.environ["ILH_SECRET_PATH"] = str(Path(self.temp_dir.name) / "secret.key")

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

    def make_receipt(
        self,
        session_id: str,
        task_id: str,
        *,
        tool_name: str = "Read",
        command_text: str = "notes.md",
    ):
        return self.store.record_receipt(
            session_id=session_id,
            task_id=task_id,
            source="deepened-gap-test",
            tool_name=tool_name,
            command_text=command_text,
            exit_code=0,
            metadata={},
        )

    def approve_verified_slice(self, task_id: str, receipt_id: str) -> None:
        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id=task_id,
            stop_condition="slice_verified",
            work_summary="Reviewed the artifact and mapped the fresh receipt before completion.",
            receipt_ids=[receipt_id],
        )
        self.assertIn("APPROVED", approved)

    def complete_with_read(self, task_id: str, criterion: str) -> str:
        self.server.mission_lock("s1", task_id, "goal", [criterion])
        receipt = self.make_receipt("s1", task_id)
        self.approve_verified_slice(task_id, receipt.receipt_id)
        return self.server.completion_gate(
            session_id="s1",
            task_id=task_id,
            criterion_receipt_map=[{"criterion": criterion, "receipt_ids": [receipt.receipt_id]}],
            completion_summary="Mapped the criterion to a read-only receipt to audit semantic support boundaries.",
        )

    def test_observational_wrapper_does_not_hide_work_verbs(self) -> None:
        cases = [
            ("obs-fix", "analyze bug report and fix the model"),
            ("obs-deploy", "review deployment plan and deploy the service"),
            ("obs-configure", "inspect rollout report and configure the service"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                self.server.mission_lock("s1", task_id, "goal", [criterion])
                receipt = self.make_receipt("s1", task_id)
                self.approve_verified_slice(task_id, receipt.receipt_id)

                rejected = self.server.completion_gate(
                    session_id="s1",
                    task_id=task_id,
                    criterion_receipt_map=[{"criterion": criterion, "receipt_ids": [receipt.receipt_id]}],
                    completion_summary="Mapped an observational wrapper with work verbs to a read receipt.",
                )

                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_pure_observational_analysis_still_allows_read_receipt(self) -> None:
        criterion = "analyze variation model"
        self.server.mission_lock("s1", "pure-observation", "goal", [criterion])
        receipt = self.make_receipt("s1", "pure-observation")
        self.approve_verified_slice("pure-observation", receipt.receipt_id)

        approved = self.server.completion_gate(
            session_id="s1",
            task_id="pure-observation",
            criterion_receipt_map=[{"criterion": criterion, "receipt_ids": [receipt.receipt_id]}],
            completion_summary="Mapped a pure observational analysis task to a read receipt.",
        )

        self.assertIn("APPROVED", approved)

    def test_observational_artifact_action_words_do_not_require_execution(self) -> None:
        cases = [
            ("obs-test-plan", "review test plan"),
            ("obs-test-suite", "review test suite"),
            ("obs-benchmark-report", "analyze benchmark report"),
            ("obs-deploy-strategy", "inspect deployment strategy"),
            ("obs-update-notes", "review update notes"),
            ("obs-verification-summary", "analyze verification summary"),
            ("obs-patch-report", "inspect patch report"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                approved = self.complete_with_read(task_id, criterion)

                self.assertIn("APPROVED", approved)

    def test_chinese_observational_artifact_action_words_allow_read_receipt(self) -> None:
        cases = [
            ("cn-obs-test-plan", "分析测试计划"),
            ("cn-obs-test-suite", "分析测试套件"),
            ("cn-obs-verification-report", "审阅验证报告"),
            ("cn-obs-update-report", "检查更新报告"),
            ("cn-obs-fix-report", "分析修复报告"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                approved = self.complete_with_read(task_id, criterion)

                self.assertIn("APPROVED", approved)

    def test_chinese_observational_artifacts_do_not_hide_follow_on_actions(self) -> None:
        cases = [
            ("cn-follow-run", "分析测试计划并运行回归测试"),
            ("cn-follow-punctuation-run", "分析测试计划；运行回归测试"),
            ("cn-follow-update", "审阅更新报告并更新文档"),
            ("cn-follow-fix", "检查修复报告并修复代码"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                rejected = self.complete_with_read(task_id, criterion)

                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_chinese_negated_observational_follow_on_actions_allow_read_receipt(self) -> None:
        cases = [
            ("cn-neg-follow-run", "分析测试计划并不运行回归测试"),
            ("cn-neg-follow-update", "审阅更新报告且不要更新文档"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                approved = self.complete_with_read(task_id, criterion)

                self.assertIn("APPROVED", approved)

    def test_chinese_double_negated_observational_follow_on_actions_require_action_evidence(self) -> None:
        criterion = "分析测试计划并不是不运行回归测试"

        rejected = self.complete_with_read("cn-double-neg-follow-run", criterion)

        self.assertIn("REJECTED", rejected)
        self.assertIn("semantic", rejected.lower())

    def test_observational_artifacts_do_not_hide_follow_on_actions(self) -> None:
        cases = [
            ("follow-run", "review test plan and run smoke tests"),
            ("follow-deploy", "inspect deployment strategy and deploy the service"),
            ("follow-patch", "analyze patch report and patch the code"),
            ("follow-optimize", "analyze benchmark report then optimize the module"),
            ("follow-update", "review update notes and update docs"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                rejected = self.complete_with_read(task_id, criterion)

                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_negated_follow_on_actions_still_allow_observational_receipts(self) -> None:
        cases = [
            ("negated-follow-run", "review test plan and do not run smoke tests"),
            ("negated-follow-deploy", "inspect deployment strategy without deploying the service"),
            ("negated-follow-update", "review update notes and avoid updating docs"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                approved = self.complete_with_read(task_id, criterion)

                self.assertIn("APPROVED", approved)

    def test_double_negated_follow_on_actions_require_action_evidence(self) -> None:
        cases = [
            ("double-follow-run", "review test plan and do not skip running smoke tests"),
            ("double-follow-update", "review update notes and do not skip updating docs"),
        ]
        for task_id, criterion in cases:
            with self.subTest(criterion=criterion):
                rejected = self.complete_with_read(task_id, criterion)

                self.assertIn("REJECTED", rejected)
                self.assertIn("semantic", rejected.lower())

    def test_stuck_escalation_respects_counterexample_required(self) -> None:
        self.server.mission_lock(
            "s1",
            "counterexample-stuck",
            "goal",
            ["criterion"],
            counterexample_required=True,
            retry_budget=1,
        )
        receipt = self.make_receipt(
            "s1", "counterexample-stuck", tool_name="Bash", command_text="pytest -q"
        )
        self.server.record_stuck_attempt(
            "s1",
            "counterexample-stuck",
            "strategy-a",
            "first failed strategy with direct output",
            [receipt.receipt_id],
        )

        rejected = self.server.turn_end_gate(
            session_id="s1",
            task_id="counterexample-stuck",
            stop_condition="stuck_escalation",
            work_summary="Recorded the failed strategy and tried to escalate without counterexample evidence.",
            receipt_ids=[receipt.receipt_id],
            reason_for_stopping="Retry budget is exhausted, but counterexample work has not been recorded.",
        )

        self.assertIn("REJECTED", rejected)
        self.assertIn("counterexample", rejected.lower())

    def test_stuck_escalation_with_counterexample_check_can_proceed(self) -> None:
        self.server.mission_lock(
            "s1",
            "counterexample-stuck-ok",
            "goal",
            ["criterion"],
            counterexample_required=True,
            retry_budget=1,
        )
        receipt = self.make_receipt(
            "s1", "counterexample-stuck-ok", tool_name="Bash", command_text="pytest -q"
        )
        self.server.record_stuck_attempt(
            "s1",
            "counterexample-stuck-ok",
            "strategy-a",
            "first failed strategy with direct output",
            [receipt.receipt_id],
        )
        self.server.record_counterexample_check(
            "s1",
            "counterexample-stuck-ok",
            "local retries may still find a solution",
            ["tried an independent command path"],
            "no new path survived the check",
            [receipt.receipt_id],
        )

        approved = self.server.turn_end_gate(
            session_id="s1",
            task_id="counterexample-stuck-ok",
            stop_condition="stuck_escalation",
            work_summary="Recorded stuck strategy and counterexample evidence before escalating.",
            receipt_ids=[receipt.receipt_id],
            reason_for_stopping="Retry budget is exhausted after a recorded counterexample check and further local retries repeat the same path.",
        )

        self.assertIn("APPROVED", approved)


if __name__ == "__main__":
    unittest.main()
