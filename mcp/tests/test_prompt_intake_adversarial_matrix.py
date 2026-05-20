from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class PromptIntakeAdversarialMatrixTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        self.cwd = Path(self.temp_dir.name) / "repo"
        self.cwd.mkdir()
        os.environ["ILH_DB_PATH"] = str(self.db_path)
        os.environ["ILH_SECRET_PATH"] = str(self.secret_path)

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

    def intake(self, message: str, **kwargs) -> dict:
        payload = self.server.prompt_intake_gate(
            session_id=kwargs.pop("session_id", "s1"),
            user_message=message,
            cwd=kwargs.pop("cwd", str(self.cwd)),
            **kwargs,
        )
        return json.loads(payload)

    def lock_mission(self) -> None:
        self.server.mission_lock(
            session_id="s1",
            task_id="t1",
            goal="finish t1",
            completion_criteria=["tests pass"],
            cwd=str(self.cwd),
        )

    def previous_authorization_question(self) -> dict:
        return {
            "asked_user_authorization": True,
            "action_scope": "git push gitea main",
            "approval_scope": "push verified commit to gitea/main",
        }

    def test_inline_code_and_reference_action_words_are_ordinary(self) -> None:
        cases = [
            "What does `git push origin main` do?",
            "Explain the command `git push` before we use it.",
            "Summarize the pre-release checklist.",
            "Explain push notifications, not git push.",
            "Read the release/v1.2 branch naming notes.",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ordinary_prompt", payload["classification"])
                self.assertFalse(payload["should_activate_agent_runway"])
                self.assertNotIn("external_side_effect_request", payload["evidence_sources"])

    def test_merge_rebase_tag_publish_archive_actions_activate(self) -> None:
        cases = [
            "merge this branch and rebase main",
            "create the release tag and publish the package",
            "archive the old release branch after the merge",
            "drop the old tag, publish the package, and archive the notes",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("new_agent_runway_mission", payload["classification"])
                self.assertTrue(payload["should_activate_agent_runway"])
                self.assertIn("external_side_effect_request", payload["evidence_sources"])

    def test_merge_rebase_tag_publish_archive_reference_contexts_are_ordinary(self) -> None:
        cases = [
            "Explain the merge conflict resolution strategy.",
            "What is a rebase workflow?",
            "Summarize the release notes archive format.",
            "Read the git archive format documentation.",
            "What does tag mean in semantic versioning?",
            "Summarize package publish safety rules.",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ordinary_prompt", payload["classification"])
                self.assertFalse(payload["should_activate_agent_runway"])
                self.assertNotIn("external_side_effect_request", payload["evidence_sources"])

    def test_programming_continue_references_do_not_resume_active_mission(self) -> None:
        self.lock_mission()
        cases = [
            "What does continue mean in Python?",
            "Maybe continue is a JavaScript keyword?",
            "continue pairs with break in loop control flow",
            "Let's continue reading the docs about continue statements",
            "I want you to continue explaining the continue keyword in Python",
            "Why don't we continue discussing loop control-flow statements",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ordinary_prompt", payload["classification"])
                self.assertFalse(payload["is_continuation"])
                self.assertFalse(payload["should_activate_agent_runway"])

    def test_true_continue_still_resumes_active_mission_after_programming_guard(self) -> None:
        self.lock_mission()
        cases = [
            "Let's continue",
            "Maybe continue",
            "Let's continue reading API.md",
            "I want you to continue with the bug audit",
            "Why don't we continue with the next verified slice",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("continue_current_mission", payload["classification"])
                self.assertTrue(payload["is_continuation"])
                self.assertEqual("t1", payload["mission"]["task_id"])

    def test_external_side_effect_questions_are_not_execution_requests(self) -> None:
        cases = [
            "Should I push this branch?",
            "Do you want me to deploy this?",
            "Should we release this today?",
            "我要推送吗？",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ordinary_prompt", payload["classification"])
                self.assertFalse(payload["authority_boundary"]["authorization_inferred"])

    def test_previous_authorization_question_rejects_negative_replies(self) -> None:
        self.lock_mission()
        cases = ["no", "nope", "nein", "non", "não", "不", "不行", "不可以", "否", "いや", "아니요"]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(
                    message,
                    previous_assistant_state=self.previous_authorization_question(),
                )
                self.assertEqual("authorization_not_granted", payload["classification"])
                self.assertFalse(payload["authority_boundary"]["authorization_inferred"])

    def test_previous_authorization_question_does_not_treat_questions_as_approval(self) -> None:
        self.lock_mission()
        cases = ["yes?", "go ahead?", "can you proceed?", "可以吗？"]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(
                    message,
                    previous_assistant_state=self.previous_authorization_question(),
                )
                self.assertEqual("authorization_not_granted", payload["classification"])
                self.assertFalse(payload["authority_boundary"]["authorization_inferred"])

    def test_previous_authorization_question_rejects_local_only_limits(self) -> None:
        self.lock_mission()
        cases = [
            "yes, local only",
            "continue local only",
            "go ahead locally only",
            "可以，只做本地",
            "只继续本地工作",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(
                    message,
                    previous_assistant_state=self.previous_authorization_question(),
                )
                self.assertEqual("authorization_not_granted", payload["classification"])
                self.assertFalse(payload["authority_boundary"]["authorization_inferred"])

    def test_active_mission_still_accepts_continuation_questions_without_authority_prompt(self) -> None:
        self.lock_mission()

        payload = self.intake("Can you continue?")

        self.assertEqual("continue_current_mission", payload["classification"])
        self.assertTrue(payload["is_continuation"])


if __name__ == "__main__":
    unittest.main()
