from __future__ import annotations

import sys
import unittest
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from agent_runway_runtime.prompt_intake_signals import (  # noqa: E402
    continuation_language,
    explicit_skill,
    has_external_side_effect,
    is_false_positive_context,
    is_high_autonomy,
    normalize_text,
    text_signal,
)


class PromptIntakeSignalTestCase(unittest.TestCase):
    def test_continuation_normalizes_case_accents_width_and_politeness(self) -> None:
        cases = {
            " PLEASE   CONTINUE!!! ": "en",
            "ＣＯＮＴＩＮＵＥ": "en",
            "continúa por favor": "es",
            "CONTINUEZ S'IL VOUS PLAÎT": "fr",
            "OK 继续，谢谢": "zh",
            "bitte weiter": "de",
        }

        for message, language in cases.items():
            with self.subTest(message=message):
                self.assertEqual(language, continuation_language(normalize_text(message)))

    def test_continuation_normalizes_zero_width_and_control_characters(self) -> None:
        cases = {
            "con\u200btinue": "en",
            "contin\x00ua": "es",
            "继\u200d续": "zh",
            "wei\x1fter": "de",
        }

        for message, language in cases.items():
            with self.subTest(message=message):
                self.assertEqual(language, continuation_language(normalize_text(message)))

    def test_continuation_detects_natural_language_requests(self) -> None:
        cases = {
            "I want you to continue": "en",
            "Let's continue": "en",
            "Why don't we continue": "en",
            "Maybe continue": "en",
        }

        for message, language in cases.items():
            with self.subTest(message=message):
                self.assertEqual(language, continuation_language(normalize_text(message)))

    def test_continuation_normalizes_invisible_marks(self) -> None:
        cases = {
            "con\u034ftinue": "en",
            "con\ufe00tinue": "en",
            "contin\ufe0fua": "es",
        }

        for message, language in cases.items():
            with self.subTest(message=message):
                self.assertEqual(language, continuation_language(normalize_text(message)))

    def test_action_signal_matching_respects_latin_word_boundaries(self) -> None:
        ordinary_cases = [
            "Explain the contest rules",
            "Study pushdown automata",
            "Read the release notes",
            "A suffix can contain fix as letters",
        ]

        for message in ordinary_cases:
            with self.subTest(message=message):
                self.assertFalse(is_high_autonomy(message))
                self.assertFalse(has_external_side_effect(message))

    def test_chinese_action_signal_matching_respects_negated_and_completed_context(self) -> None:
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
                self.assertFalse(is_high_autonomy(message))
                self.assertFalse(has_external_side_effect(message))

    def test_chinese_completed_marker_does_not_suppress_follow_on_actions(self) -> None:
        cases = [
            "已阅读报告，继续修复并验证",
            "已经看完日志，请继续测试并修复",
            "已确认问题，接着推送修复分支",
        ]

        for message in cases:
            with self.subTest(message=message):
                self.assertTrue(is_high_autonomy(message))

    def test_destructive_terms_in_reference_context_are_not_side_effects(self) -> None:
        cases = [
            "Explain the merge conflict resolution strategy.",
            "Summarize git archive format behavior.",
            "Read the database drop table migration notes.",
        ]

        for message in cases:
            with self.subTest(message=message):
                self.assertFalse(has_external_side_effect(message))

    def test_real_multistep_action_signals_still_match(self) -> None:
        cases = [
            "fix the bug and run tests",
            "verify the patch then commit",
            "修复这个问题并验证",
        ]

        for message in cases:
            with self.subTest(message=message):
                self.assertTrue(is_high_autonomy(message))

    def test_external_side_effect_signal_requires_real_action_word(self) -> None:
        self.assertTrue(has_external_side_effect("push the verified commit"))
        self.assertTrue(has_external_side_effect("继续推送"))
        self.assertTrue(has_external_side_effect("删除远端分支"))
        self.assertTrue(has_external_side_effect("移除旧标签"))
        self.assertTrue(has_external_side_effect("清空旧表"))
        self.assertTrue(has_external_side_effect("截断发布记录"))
        self.assertTrue(has_external_side_effect("remove the remote tag"))
        self.assertTrue(has_external_side_effect("truncate the published changelog"))
        self.assertTrue(has_external_side_effect("push `origin main`"))
        self.assertTrue(has_external_side_effect("run `git push gitea main`"))
        self.assertTrue(has_external_side_effect("force-push the repaired branch"))
        self.assertFalse(has_external_side_effect("write release notes"))
        self.assertFalse(has_external_side_effect("阅读删除远端分支的安全策略"))
        self.assertFalse(has_external_side_effect("explain pushdown automata"))

    def test_inline_code_reference_context_does_not_hide_real_directives(self) -> None:
        directive = "yes, run `git push gitea main`"

        self.assertFalse(is_false_positive_context(directive, text_signal(directive)))

    def test_false_positive_context_is_narrow_not_question_wide(self) -> None:
        self.assertFalse(
            is_false_positive_context(
                "Can you fix it and run tests?",
                text_signal("Can you fix it and run tests?"),
            )
        )

    def test_programming_continue_context_includes_common_language_terms(self) -> None:
        cases = [
            "continue is a keyword",
            "continue in JavaScript exits to the next loop iteration",
            "continue pairs with break in loop control flow",
            "Maybe continue is a Python keyword?",
            "Let's continue reading the docs about continue statements",
            "I want you to continue explaining the continue keyword in Python",
        ]

        for message in cases:
            with self.subTest(message=message):
                self.assertTrue(is_false_positive_context(message, text_signal(message)))
        self.assertTrue(
            is_false_positive_context(
                "What does continue mean?",
                text_signal("What does continue mean?"),
            )
        )
        self.assertTrue(
            is_false_positive_context(
                "继续推送吗？",
                text_signal("继续推送吗？"),
            )
        )

    def test_explicit_skill_allows_common_hyphen_and_space_variants(self) -> None:
        cases = ["agent-runway", "Agent Runway", "Agent_Runway", "Agent–Runway", "/agent"]

        for message in cases:
            with self.subTest(message=message):
                self.assertTrue(explicit_skill(message))

    def test_explicit_skill_normalizes_zero_width_and_control_characters(self) -> None:
        cases = ["agent\u200brunway", "agent\x00-runway", "/ag\u200dent"]

        for message in cases:
            with self.subTest(message=message):
                self.assertTrue(explicit_skill(message))

    def test_explicit_skill_does_not_match_plural_agent_route(self) -> None:
        self.assertFalse(explicit_skill("Open /agents to inspect configured workers."))


if __name__ == "__main__":
    unittest.main()
