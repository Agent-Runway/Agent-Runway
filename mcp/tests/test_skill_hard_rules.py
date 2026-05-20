from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_TEXT = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")


class SkillHardRulesTestCase(unittest.TestCase):
    def test_task_preflight_requires_project_agent_runway_jsonl_memory(self) -> None:
        self.assertIn("before every task", SKILL_TEXT)
        self.assertIn(".agent-runway/*.jsonl", SKILL_TEXT)
        self.assertIn(".agent-runway/project-learning-ledger.jsonl", SKILL_TEXT)

    def test_task_preflight_requires_project_key_files(self) -> None:
        self.assertIn("API.md", SKILL_TEXT)
        self.assertIn("SPEC.md", SKILL_TEXT)
        self.assertIn("before task execution", SKILL_TEXT)

    def test_todo_output_requires_mcp_control_plane_record(self) -> None:
        self.assertIn("Every visible TODO", SKILL_TEXT)
        self.assertIn("MCP", SKILL_TEXT)
        self.assertIn("mission control", SKILL_TEXT)

    def test_new_todo_items_default_to_append_at_end(self) -> None:
        self.assertIn("append new todo items to the end", SKILL_TEXT)
        self.assertIn("unless the user explicitly requests different ordering", SKILL_TEXT)
        self.assertIn("never drop unfinished todo items", SKILL_TEXT)

    def test_project_learning_is_not_evidence_or_authorization(self) -> None:
        self.assertIn("treat project learning as advisory context only", SKILL_TEXT)
        self.assertIn("memory is not evidence", SKILL_TEXT)
        self.assertIn("preference is not authorization", SKILL_TEXT)


if __name__ == "__main__":
    unittest.main()
