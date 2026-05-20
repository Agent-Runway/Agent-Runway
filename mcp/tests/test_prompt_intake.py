from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class PromptIntakeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.secret_path = Path(self.temp_dir.name) / "secret.key"
        self.cwd_a = Path(self.temp_dir.name) / "repo-a"
        self.cwd_b = Path(self.temp_dir.name) / "repo-b"
        self.cwd_a.mkdir()
        self.cwd_b.mkdir()
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

    def intake(self, message: str, **kwargs) -> dict:
        payload = self.server.prompt_intake_gate(
            session_id=kwargs.pop("session_id", "s1"),
            user_message=message,
            cwd=kwargs.pop("cwd", str(self.cwd_a)),
            **kwargs,
        )
        return json.loads(payload)

    def lock_mission(
        self,
        session_id: str = "s1",
        task_id: str = "t1",
        cwd: Path | None = None,
        goal: str = "finish verified work",
    ) -> None:
        self.server.mission_lock(
            session_id=session_id,
            task_id=task_id,
            goal=goal,
            completion_criteria=["tests pass", "docs are honest"],
            host="OpenCode",
            cwd=str(cwd or self.cwd_a),
        )

    def test_explicit_short_skill_invocation_creates_mission_draft(self) -> None:
        payload = self.intake("/agent-runway 帮我完成 v0.38")

        self.assertEqual("new_agent_runway_mission", payload["classification"])
        self.assertTrue(payload["should_activate_agent_runway"])
        self.assertFalse(payload["is_continuation"])
        self.assertEqual(1.0, payload["confidence"])
        self.assertIn("explicit_skill_invocation", payload["evidence_sources"])
        self.assertIn("mission_draft", payload)
        self.assertIn("lock mission", " ".join(payload["required_first_actions"]))

    def test_implicit_high_autonomy_request_activates_without_skill_name(self) -> None:
        payload = self.intake("修复这个 bug，跑完整测试，然后提交并推送到 Gitea")

        self.assertEqual("new_agent_runway_mission", payload["classification"])
        self.assertTrue(payload["should_activate_agent_runway"])
        self.assertIn("high_autonomy_request", payload["evidence_sources"])
        self.assertIn("fresh authorization", payload["authority_boundary"]["external_side_effect"])
        self.assertIn("bounded", payload["normalized_request"].lower())

    def test_multilingual_short_continuation_resumes_active_mission(self) -> None:
        self.lock_mission()
        cases = {
            "en": "continue",
            "zh": "继续",
            "de": "mach weiter",
            "fr": "continuez",
            "es": "continúa",
            "pt": "continua",
            "ja": "続けて",
            "ko": "계속 진행",
        }

        for language, message in cases.items():
            with self.subTest(language=language):
                payload = self.intake(message)
                self.assertEqual("continue_current_mission", payload["classification"])
                self.assertTrue(payload["should_activate_agent_runway"])
                self.assertTrue(payload["is_continuation"])
                self.assertGreaterEqual(payload["confidence"], 0.9)
                self.assertEqual("s1", payload["mission"]["session_id"])
                self.assertEqual("t1", payload["mission"]["task_id"])
                self.assertIn("short_continuation_phrase", payload["evidence_sources"])
                self.assertIn("active_session_mission", payload["evidence_sources"])

    def test_compressed_session_resumes_unique_workspace_mission_by_cwd(self) -> None:
        self.lock_mission(session_id="old-session", task_id="release-hardening")

        payload = self.intake("go on", session_id="new-session")

        self.assertEqual("continue_current_mission", payload["classification"])
        self.assertTrue(payload["mission"]["needs_session_rebind"])
        self.assertEqual("old-session", payload["mission"]["session_id"])
        self.assertEqual("workspace_active_mission", payload["mission"]["source"])
        self.assertIn("handoff", " ".join(payload["required_first_actions"]))

    def test_continuation_without_recoverable_context_asks_clarification(self) -> None:
        payload = self.intake("weiter")

        self.assertEqual("ambiguous_continuation", payload["classification"])
        self.assertFalse(payload["should_activate_agent_runway"])
        self.assertTrue(payload["is_continuation"])
        self.assertIn("required_user_question", payload)
        self.assertIn("No active Agent-Runway mission", payload["required_user_question"])

    def test_different_cwd_does_not_resume_foreign_workspace_mission(self) -> None:
        self.lock_mission(session_id="old-session", task_id="other", cwd=self.cwd_b)

        payload = self.intake("continue", session_id="new-session", cwd=str(self.cwd_a))

        self.assertEqual("ambiguous_continuation", payload["classification"])
        self.assertNotIn("mission", payload)

    def test_multiple_workspace_missions_are_ambiguous_not_silently_chosen(self) -> None:
        self.lock_mission(session_id="old-a", task_id="task-a")
        self.lock_mission(session_id="old-b", task_id="task-b")

        payload = self.intake("continue", session_id="new-session")

        self.assertEqual("ambiguous_workspace_mission", payload["classification"])
        self.assertFalse(payload["should_activate_agent_runway"])
        self.assertEqual(2, len(payload["candidate_missions"]))
        self.assertIn("choose which mission", payload["required_user_question"])

    def test_completed_workspace_mission_is_not_resumed_after_compression(self) -> None:
        self.lock_mission(session_id="old-session", task_id="done-task")
        self.store.mark_completed("old-session", "done-task", {"reason": "test"})

        payload = self.intake("go on", session_id="new-session")

        self.assertEqual("ambiguous_continuation", payload["classification"])
        self.assertNotIn("mission", payload)

    def test_scoped_authorization_reply_requires_previous_authority_question(self) -> None:
        self.lock_mission()
        payload = self.intake(
            "continue",
            previous_assistant_state={
                "asked_user_authorization": True,
                "action_scope": "git push gitea main",
                "approval_scope": "push verified commit to gitea/main",
                "irreversible": False,
            },
        )

        self.assertEqual("scoped_authorization_reply", payload["classification"])
        self.assertTrue(payload["should_activate_agent_runway"])
        self.assertTrue(payload["authority_boundary"]["authorization_inferred"])
        self.assertEqual("git push gitea main", payload["authority_boundary"]["action_scope"])
        self.assertIn("record_user_authorization", " ".join(payload["required_first_actions"]))

    def test_unbound_yes_does_not_create_authorization(self) -> None:
        self.lock_mission()

        payload = self.intake("yes")

        self.assertEqual("ambiguous_confirmation", payload["classification"])
        self.assertFalse(payload["authority_boundary"]["authorization_inferred"])
        self.assertIn("required_user_question", payload)

    def test_unbound_push_continuation_does_not_create_authorization(self) -> None:
        self.lock_mission()

        payload = self.intake("继续推送")

        self.assertEqual("new_agent_runway_mission", payload["classification"])
        self.assertTrue(payload["should_activate_agent_runway"])
        self.assertFalse(payload["authority_boundary"]["authorization_inferred"])
        self.assertIn("fresh authorization", payload["authority_boundary"]["external_side_effect"])

    def test_code_quotes_and_questions_do_not_trigger_continuation(self) -> None:
        cases = [
            "What does continue mean in Python?",
            "```python\ncontinue\n```",
            "The user said \"continue\" in the issue.",
            "继续推送吗？",
        ]

        for message in cases:
            with self.subTest(message=message):
                payload = self.intake(message)
                self.assertEqual("ordinary_prompt", payload["classification"])
                self.assertFalse(payload["is_continuation"])
                self.assertFalse(payload["authority_boundary"]["authorization_inferred"])

    def test_output_always_includes_confidence_sources_and_capability_caveat(self) -> None:
        payload = self.intake("帮我修复并验证这个问题")

        self.assertIn("confidence", payload)
        self.assertIsInstance(payload["confidence"], float)
        self.assertIn("evidence_sources", payload)
        self.assertIsInstance(payload["evidence_sources"], list)
        self.assertIn("capability_caveat", payload)
        self.assertIn("MCP", payload["capability_caveat"])
        self.assertIn("host", payload["capability_caveat"].lower())

    def test_no_context_short_prompt_does_not_fabricate_from_memory(self) -> None:
        payload = self.intake(
            "continue",
            memory_hint={"summary": "A past unrelated memory says release hardening existed."},
        )

        self.assertEqual("ambiguous_continuation", payload["classification"])
        self.assertFalse(payload["should_activate_agent_runway"])
        self.assertNotIn("mission", payload)
        self.assertIn("no_recoverable_context", payload["evidence_sources"])
        self.assertIn("memory_not_evidence", payload["evidence_sources"])

    def test_workspace_hints_can_trigger_recovery_checks_without_fabricating_mission(self) -> None:
        payload = self.intake(
            "continue",
            workspace_state={
                "dirty_worktree": True,
                "previous_assistant_next_step": "run prompt intake tests",
            },
        )

        self.assertEqual("recover_context_before_continuing", payload["classification"])
        self.assertTrue(payload["should_activate_agent_runway"])
        self.assertNotIn("mission", payload)
        self.assertIn("dirty_worktree", payload["evidence_sources"])
        self.assertIn("previous_assistant_next_step", payload["evidence_sources"])
        self.assertIn("inspect git status", " ".join(payload["required_first_actions"]))

    def test_language_monitoring_domains_are_not_collapsed(self) -> None:
        payload = self.intake("continue")

        self.assertIn("language_monitoring", payload)
        self.assertEqual(
            ["activation", "continuation", "assertion_laundering", "authorization"],
            payload["language_monitoring"]["domains"],
        )
        self.assertEqual("registry_plus_state", payload["language_monitoring"]["strategy"])
        self.assertFalse(payload["language_monitoring"]["mega_regex"])

    def test_continuation_registry_exposes_required_languages(self) -> None:
        payload = self.intake("ordinary request")

        self.assertIn("continuation_registry", payload)
        self.assertEqual(
            ["de", "en", "es", "fr", "ja", "ko", "pt", "zh"],
            sorted(payload["continuation_registry"].keys()),
        )
        for phrases in payload["continuation_registry"].values():
            self.assertGreaterEqual(len(phrases), 2)

    def test_affirmative_reply_is_separate_from_continuation(self) -> None:
        payload = self.intake("go ahead")

        self.assertEqual("ambiguous_confirmation", payload["classification"])
        self.assertFalse(payload["is_continuation"])
        self.assertFalse(payload["authority_boundary"]["authorization_inferred"])
        self.assertIn("authorization_reply_signal", payload["evidence_sources"])


if __name__ == "__main__":
    unittest.main()
