from __future__ import annotations

import sys
import unittest
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.prompt_intake_mission_match import same_mission_request  # noqa: E402


class PromptIntakeMissionMatchTestCase(unittest.TestCase):
    def test_matches_english_same_mission_with_specific_overlap(self) -> None:
        mission = {
            "task_id": "compact-mission-recovery",
            "goal": "fix compact mission recovery before creating a new mission",
            "completion_criteria": ["compact mission recovery tests pass"],
        }

        self.assertTrue(
            same_mission_request(
                "continue to fix compact mission recovery and verify tests", mission
            )
        )

    def test_rejects_english_unrelated_mission_despite_generic_actions(self) -> None:
        mission = {
            "task_id": "release-cleanup",
            "goal": "finish release cleanup references",
            "completion_criteria": ["release tests pass"],
        }

        self.assertFalse(
            same_mission_request(
                "continue to fix billing checkout bug and verify tests", mission
            )
        )

    def test_matches_chinese_same_mission_with_shared_phrase(self) -> None:
        mission = {
            "task_id": "compact-recovery",
            "goal": "修复 compact 后的压缩恢复逻辑",
            "completion_criteria": ["压缩恢复回归测试通过"],
        }

        self.assertTrue(same_mission_request("继续修复压缩恢复，验证测试", mission))

    def test_rejects_chinese_unrelated_mission_despite_generic_actions(self) -> None:
        mission = {
            "task_id": "compact-recovery",
            "goal": "修复 compact 后的压缩恢复逻辑",
            "completion_criteria": ["压缩恢复回归测试通过"],
        }

        self.assertFalse(same_mission_request("继续修复账单结算错误，验证测试", mission))


if __name__ == "__main__":
    unittest.main()
