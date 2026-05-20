from __future__ import annotations

import importlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


class PromptIntakeEdgeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        self.cwd = Path(self.temp_dir.name) / "repo"
        self.cwd.mkdir()
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)
        os.environ["ILH_HARNESS_SECRET"] = "a" * 64

        import sys

        mcp_root = str(Path(__file__).resolve().parents[1])
        if mcp_root not in sys.path:
            sys.path.insert(0, mcp_root)
        self.server = importlib.import_module("server")
        self.server = importlib.reload(self.server)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("ILH_DB_PATH", None)
        os.environ.pop("ILH_SECRET_PATH", None)
        os.environ.pop("ILH_HARNESS_SECRET", None)

    def intake(self, message: str, **kwargs) -> dict:
        payload = self.server.prompt_intake_gate(
            session_id=kwargs.pop("session_id", "s1"),
            user_message=message,
            cwd=kwargs.pop("cwd", str(self.cwd)),
            **kwargs,
        )
        return json.loads(payload)

    def lock_mission(self, task_id: str = "t1", session_id: str = "s1") -> None:
        self.server.mission_lock(
            session_id=session_id,
            task_id=task_id,
            goal=f"finish {task_id}",
            completion_criteria=["tests pass"],
            cwd=str(self.cwd),
        )

    def set_status(self, task_id: str, status: str = "active", session_id: str = "s1") -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE missions SET status=? WHERE session_id=? AND task_id=?",
                (status, session_id, task_id),
            )

    def test_high_autonomy_question_still_activates_agent_runway(self) -> None:
        payload = self.intake("Can you fix this bug, run the tests, then commit?")

        self.assertEqual("new_agent_runway_mission", payload["classification"])
        self.assertTrue(payload["should_activate_agent_runway"])
        self.assertIn("high_autonomy_request", payload["evidence_sources"])

    def test_question_about_continuation_word_remains_ordinary(self) -> None:
        cases = [
            "What does continue mean in Python?",
            "Can you explain what 'continue' means?",
            "解释一下 继续 是什么意思？",
            "continue in Python loops is a control-flow statement",
            "Maybe continue is a Python keyword?",
            "Let's continue reading the docs about continue statements",
            "I want you to continue explaining the continue keyword in Python",
            "Why don't we continue discussing loop control-flow statements",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ordinary_prompt", payload["classification"])
                self.assertFalse(payload["is_continuation"])

    def test_latin_substrings_do_not_create_action_signals(self) -> None:
        payload = self.intake("Explain the contest about pushdown automata.")

        self.assertEqual("ordinary_prompt", payload["classification"])
        self.assertFalse(payload["should_activate_agent_runway"])
        self.assertNotIn("external_side_effect_request", payload["evidence_sources"])

    def test_reference_contexts_with_action_words_are_ordinary(self) -> None:
        cases = [
            "Explain push-down automata.",
            "Summarize the release-candidate notes.",
            "总结发布说明",
            "解释推送通知机制",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ordinary_prompt", payload["classification"])
                self.assertFalse(payload["should_activate_agent_runway"])

    def test_release_notes_are_not_external_side_effects(self) -> None:
        payload = self.intake("Summarize these release notes.")

        self.assertEqual("ordinary_prompt", payload["classification"])
        self.assertFalse(payload["should_activate_agent_runway"])

    def test_polite_and_mixed_short_continuations_resume_active_mission(self) -> None:
        self.lock_mission()
        cases = [
            "OK 继续",
            "OK 继续 严谨辩证 旁敲侧击 举一反三",
            "please continue",
            "continue please",
            "Continue if you have next steps, or stop and ask for clarification if unsure",
            "Can you continue?",
            "请继续",
            "请你继续",
            "继续开发",
            "接着处理",
            "继续，谢谢",
            "bitte weiter",
            "continúa por favor",
            "continuez s'il vous plaît",
            "続けてください",
            "계속해줘",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("continue_current_mission", payload["classification"])
                self.assertTrue(payload["is_continuation"])
                self.assertEqual("t1", payload["mission"]["task_id"])

    def test_natural_language_continuations_resume_active_mission(self) -> None:
        self.lock_mission()
        cases = [
            "I want you to continue",
            "Let's continue",
            "Why don't we continue",
            "Maybe continue",
            "I want you to keep going with the bug audit",
            "Let's proceed with the next verified slice",
            "Let's continue reading API.md",
            "Let's continue reading the failing test output",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("continue_current_mission", payload["classification"])
                self.assertTrue(payload["is_continuation"])
                self.assertEqual("active_session_mission", payload["mission"]["source"])
                self.assertEqual("t1", payload["mission"]["task_id"])

    def test_natural_language_continuations_without_context_do_not_fabricate_mission(self) -> None:
        cases = [
            "I want you to continue",
            "Let's continue",
            "Why don't we continue",
            "Maybe continue",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ambiguous_continuation", payload["classification"])
                self.assertTrue(payload["is_continuation"])
                self.assertNotIn("mission", payload)

    def test_polite_continuation_without_context_still_asks_clarification(self) -> None:
        payload = self.intake("please continue")

        self.assertEqual("ambiguous_continuation", payload["classification"])
        self.assertTrue(payload["is_continuation"])
        self.assertIn("No active Agent-Runway mission", payload["required_user_question"])

    def test_ambiguous_continuation_preserves_normalized_request(self) -> None:
        message = "continue with the bug audit after checking BUG-16"

        payload = self.intake(message)

        self.assertEqual("ambiguous_continuation", payload["classification"])
        self.assertEqual(message, payload["normalized_request"])

    def test_multiple_active_missions_in_same_session_are_ambiguous(self) -> None:
        self.lock_mission("task-a")
        self.lock_mission("task-b")

        payload = self.intake("continue")

        self.assertEqual("ambiguous_session_mission", payload["classification"])
        self.assertFalse(payload["should_activate_agent_runway"])
        self.assertEqual(2, len(payload["candidate_missions"]))
        self.assertIn("same session", payload["required_user_question"])

    def test_task_id_disambiguates_same_session_active_missions(self) -> None:
        self.lock_mission("task-a")
        self.lock_mission("task-b")

        payload = self.intake("continue", task_id="task-a")

        self.assertEqual("continue_current_mission", payload["classification"])
        self.assertEqual("task-a", payload["mission"]["task_id"])

    def test_task_id_for_inactive_mission_does_not_fallback_to_neighbor(self) -> None:
        self.lock_mission("task-a")
        self.lock_mission("task-b")
        self.set_status("task-a", "superseded")

        payload = self.intake("continue", task_id="task-a")

        self.assertEqual("ambiguous_continuation", payload["classification"])
        self.assertNotIn("mission", payload)

    def test_requested_task_id_can_rebind_matching_workspace_mission(self) -> None:
        self.lock_mission("task-a", session_id="old-session")
        self.lock_mission("task-b", session_id="old-session")

        payload = self.intake("continue", session_id="fresh-session", task_id="task-a")

        self.assertEqual("continue_current_mission", payload["classification"])
        self.assertEqual("task-a", payload["mission"]["task_id"])
        self.assertEqual("old-session", payload["mission"]["session_id"])
        self.assertTrue(payload["mission"]["needs_session_rebind"])
        self.assertIn("workspace_active_mission", payload["evidence_sources"])

    def test_compacted_same_mission_high_autonomy_continuation_resumes_workspace_mission(self) -> None:
        self.server.mission_lock(
            session_id="old-session",
            task_id="compact-mission-recovery",
            goal="fix compact mission recovery before creating a new mission",
            completion_criteria=["compact mission recovery tests pass"],
            cwd=str(self.cwd),
        )

        payload = self.intake(
            "continue to fix compact mission recovery, verify tests, and complete todo list",
            session_id="fresh-session",
        )

        self.assertEqual("continue_current_mission", payload["classification"])
        self.assertEqual("old-session", payload["mission"]["session_id"])
        self.assertEqual("compact-mission-recovery", payload["mission"]["task_id"])
        self.assertIn("same_mission_recovery", payload["evidence_sources"])

    def test_compacted_unrelated_high_autonomy_continuation_creates_new_mission(self) -> None:
        self.server.mission_lock(
            session_id="old-session",
            task_id="release-cleanup",
            goal="finish release cleanup references",
            completion_criteria=["release tests pass"],
            cwd=str(self.cwd),
        )

        payload = self.intake(
            "continue to fix billing checkout bug, verify tests, and complete todo list",
            session_id="fresh-session",
        )

        self.assertEqual("new_agent_runway_mission", payload["classification"])
        self.assertNotIn("mission", payload)

    def test_compacted_chinese_same_mission_continuation_resumes_workspace_mission(self) -> None:
        self.server.mission_lock(
            session_id="old-session",
            task_id="compact-recovery",
            goal="修复 compact 后的压缩恢复逻辑",
            completion_criteria=["压缩恢复回归测试通过"],
            cwd=str(self.cwd),
        )

        payload = self.intake("继续修复压缩恢复，验证测试，完成todo", session_id="fresh-session")

        self.assertEqual("continue_current_mission", payload["classification"])
        self.assertEqual("compact-recovery", payload["mission"]["task_id"])
        self.assertIn("same_mission_recovery", payload["evidence_sources"])

    def test_compacted_chinese_unrelated_continuation_creates_new_mission(self) -> None:
        self.server.mission_lock(
            session_id="old-session",
            task_id="compact-recovery",
            goal="修复 compact 后的压缩恢复逻辑",
            completion_criteria=["压缩恢复回归测试通过"],
            cwd=str(self.cwd),
        )

        payload = self.intake("继续修复账单结算错误，验证测试，完成todo", session_id="fresh-session")

        self.assertEqual("new_agent_runway_mission", payload["classification"])
        self.assertNotIn("mission", payload)

    def test_blank_cwd_does_not_recover_process_workspace_mission(self) -> None:
        self.server.mission_lock(
            session_id="old-session",
            task_id="process-cwd-task",
            goal="process cwd should not be inferred from blank host cwd",
            completion_criteria=["tests pass"],
            cwd=".",
        )

        payload = self.intake("continue", session_id="fresh-session", cwd="")

        self.assertEqual("ambiguous_continuation", payload["classification"])
        self.assertNotIn("mission", payload)

    def test_whitespace_cwd_does_not_recover_process_workspace_mission(self) -> None:
        self.server.mission_lock(
            session_id="old-session",
            task_id="whitespace-cwd-task",
            goal="whitespace cwd should not be inferred from process cwd",
            completion_criteria=["tests pass"],
            cwd=".",
        )

        for blank_cwd in [" ", "   ", "\t\n"]:
            with self.subTest(cwd=repr(blank_cwd)):
                payload = self.intake("continue", session_id="fresh-session", cwd=blank_cwd)

                self.assertEqual("ambiguous_continuation", payload["classification"])
                self.assertNotIn("mission", payload)

    def test_dot_cwd_recovers_explicit_process_workspace_mission(self) -> None:
        self.server.mission_lock(
            session_id="old-session",
            task_id="explicit-dot-cwd-task",
            goal="explicit dot cwd may recover the current process workspace",
            completion_criteria=["tests pass"],
            cwd=".",
        )

        payload = self.intake("continue", session_id="fresh-session", cwd=".")

        self.assertEqual("continue_current_mission", payload["classification"])
        self.assertEqual("workspace_active_mission", payload["mission"]["source"])
        self.assertEqual("explicit-dot-cwd-task", payload["mission"]["task_id"])

    def test_foreign_cwd_does_not_recover_process_workspace_mission(self) -> None:
        foreign_cwd = Path(self.temp_dir.name) / "foreign-repo"
        foreign_cwd.mkdir()
        self.server.mission_lock(
            session_id="old-session",
            task_id="process-cwd-task",
            goal="foreign cwd should not recover process cwd mission",
            completion_criteria=["tests pass"],
            cwd=".",
        )

        payload = self.intake("continue", session_id="fresh-session", cwd=str(foreign_cwd))

        self.assertEqual("ambiguous_continuation", payload["classification"])
        self.assertNotIn("mission", payload)

    def test_skill_name_variants_create_mission_draft(self) -> None:
        cases = [
            "Use Agent Runway to finish this verified slice",
            "请用 Agent–Runway 继续完成验证",
            "/agent help me finish the release hardening",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("new_agent_runway_mission", payload["classification"])
                self.assertIn("explicit_skill_invocation", payload["evidence_sources"])

    def test_scoped_authorization_accepts_multilingual_affirmatives(self) -> None:
        self.lock_mission()
        previous = {
            "asked_user_authorization": True,
            "action_scope": "git push gitea main",
            "approval_scope": "push verified commit to gitea/main",
        }
        cases = [
            "sí",
            "sí, hazlo",
            "oui",
            "ja",
            "sim",
            "はい",
            "네",
            "可以，推送",
            "yes, deploy now",
            "yes, publish now",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message, previous_assistant_state=previous)
                self.assertEqual("scoped_authorization_reply", payload["classification"])
                self.assertTrue(payload["authority_boundary"]["authorization_inferred"])

    def test_unbound_multilingual_affirmatives_do_not_authorize(self) -> None:
        for message in ["sí", "oui", "ja", "sim", "はい", "네"]:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ambiguous_confirmation", payload["classification"])
                self.assertFalse(payload["authority_boundary"]["authorization_inferred"])

    def test_authorization_denial_or_limit_is_not_inferred(self) -> None:
        self.lock_mission()
        previous = {
            "asked_user_authorization": True,
            "action_scope": "git push gitea main",
            "approval_scope": "push verified commit to gitea/main",
        }
        cases = [
            "continue locally, don't push",
            "yes, but do not push",
            "继续，但不要推送",
            "可以，但先别推送",
            "yes, but do not run `git push gitea main`",
            "继续，但不要运行 `git push gitea main`",
            "yes, only explain `git push gitea main`; do not push",
            "yes, explain `git push gitea main`",
            "yes, what is `git push gitea main`?",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message, previous_assistant_state=previous)
                self.assertEqual("authorization_not_granted", payload["classification"])
                self.assertFalse(payload["authority_boundary"]["authorization_inferred"])

    def test_authorization_reply_is_not_lost_inside_inline_code_or_reference_context(self) -> None:
        self.lock_mission()
        previous = {
            "asked_user_authorization": True,
            "action_scope": "git push gitea main",
            "approval_scope": "push verified commit to gitea/main",
        }
        cases = [
            "yes, run `git push gitea main`",
            "approved, run `git push gitea main`",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message, previous_assistant_state=previous)

                self.assertEqual("scoped_authorization_reply", payload["classification"])
                self.assertTrue(payload["authority_boundary"]["authorization_inferred"])
                self.assertNotIn("false_positive_context", payload["evidence_sources"])

    def test_authorization_reply_is_not_overridden_by_multiple_active_missions(self) -> None:
        self.lock_mission("task-a")
        self.lock_mission("task-b")
        previous = {
            "asked_user_authorization": True,
            "action_scope": "git push gitea main",
            "approval_scope": "push verified commit to gitea/main",
        }

        payload = self.intake("approved", previous_assistant_state=previous)

        self.assertEqual("scoped_authorization_reply", payload["classification"])
        self.assertNotIn("candidate_missions", payload)

    def test_authorization_denial_is_not_overridden_by_multiple_active_missions(self) -> None:
        self.lock_mission("task-a")
        self.lock_mission("task-b")
        previous = {
            "asked_user_authorization": True,
            "action_scope": "git push gitea main",
            "approval_scope": "push verified commit to gitea/main",
        }
        cases = [
            "no",
            "yes, but do not push",
            "继续，但不要推送",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message, previous_assistant_state=previous)
                self.assertEqual("authorization_not_granted", payload["classification"])
                self.assertFalse(payload["authority_boundary"]["authorization_inferred"])
                self.assertNotIn("candidate_missions", payload)

    def test_inline_code_directive_still_activates_external_side_effect_mission(self) -> None:
        payload = self.intake("run `git push gitea main`")

        self.assertEqual("new_agent_runway_mission", payload["classification"])
        self.assertTrue(payload["should_activate_agent_runway"])
        self.assertIn("external_side_effect_request", payload["evidence_sources"])

    def test_unbound_affirmative_with_inline_side_effect_is_not_swallowed_as_confirmation(self) -> None:
        payload = self.intake("yes, run `git push gitea main`")

        self.assertEqual("new_agent_runway_mission", payload["classification"])
        self.assertTrue(payload["should_activate_agent_runway"])
        self.assertFalse(payload["authority_boundary"]["authorization_inferred"])
        self.assertIn("external_side_effect_request", payload["evidence_sources"])
        self.assertNotIn("previous_authority_question", payload["evidence_sources"])

    def test_destructive_and_release_flow_requests_activate_agent_runway(self) -> None:
        cases = [
            "delete the stale branch",
            "force-push the repaired branch",
            "delete all branches and force push to main",
            "drop the old tag and publish the package",
            "remove the remote tag and truncate the published changelog",
            "merge this branch, rebase main, then archive the release notes",
            "delete the unsafe force-push safety note file",
            "remove the obsolete release notes archive",
            "删除远端分支",
            "移除旧标签",
            "清空旧表",
            "截断发布记录",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("new_agent_runway_mission", payload["classification"])
                self.assertTrue(payload["should_activate_agent_runway"])
                self.assertIn("external_side_effect_request", payload["evidence_sources"])

    def test_destructive_reference_contexts_remain_ordinary(self) -> None:
        cases = [
            "Explain force-push safety rules.",
            "Summarize the release notes archive format.",
            "What does database truncate mean?",
            "阅读删除远端分支的安全策略",
            "解释清空旧表是什么意思？",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ordinary_prompt", payload["classification"])
                self.assertFalse(payload["should_activate_agent_runway"])

    def test_chinese_negated_and_completed_actions_remain_ordinary(self) -> None:
        cases = [
            "无需修复",
            "不需要修复",
            "不用验证",
            "不要测试",
            "别推送",
            "别再推送",
            "已完成验证",
            "已经完成测试",
            "已经完成了验证",
            "已修复完成",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ordinary_prompt", payload["classification"])
                self.assertFalse(payload["should_activate_agent_runway"])

    def test_chinese_follow_on_actions_after_completed_context_activate(self) -> None:
        cases = [
            "已阅读报告，继续修复并验证",
            "已经看完日志，请继续测试并修复",
            "已确认问题，接着推送修复分支",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("new_agent_runway_mission", payload["classification"])
                self.assertTrue(payload["should_activate_agent_runway"])

    def test_destructive_terms_in_reference_context_remain_ordinary(self) -> None:
        cases = [
            "Explain the merge conflict resolution strategy.",
            "Summarize git archive format behavior.",
            "Read the database drop table migration notes.",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ordinary_prompt", payload["classification"])
                self.assertFalse(payload["should_activate_agent_runway"])


if __name__ == "__main__":
    unittest.main()
