from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class SubagentDocsTestCase(unittest.TestCase):
    def test_subagent_supervision_doc_defines_runtime_honesty_rules(self) -> None:
        doc_path = REPO_ROOT / "references" / "subagent-supervision.md"
        text = doc_path.read_text(encoding="utf-8")

        required_phrases = [
            "Agent Runway does not launch every subagent",
            "child summary is not evidence",
            "subagent inheritance is not assumed",
            "parent authorization does not automatically flow to child",
            "memory is not evidence",
            "preference is not authorization",
            "L0 prompt-only supervision",
            "L1 proof-bundle import",
            "L2 shared MCP child receipts",
            "L3 hosted lifecycle/tool-hook supervision",
        ]
        for phrase in required_phrases:
            self.assertIn(phrase, text)

        forbidden_phrases = [
            "universal subagent launcher",
            "captures hidden chain-of-thought",
            "physical stop blocking across all hosts",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, text)

    def test_subagent_capability_matrix_scopes_host_guarantees(self) -> None:
        doc_path = REPO_ROOT / "references" / "subagent-capability-matrix.md"
        text = doc_path.read_text(encoding="utf-8")

        required_phrases = [
            "Claude Code",
            "OpenCode",
            "Codex",
            "Pi",
            "L0 prompt-only supervision",
            "L1 proof-bundle import",
            "L2 shared MCP child receipts",
            "L3 hosted lifecycle/tool-hook supervision",
            "stop enforceability",
            "context inheritance",
            "tool/MCP inheritance",
            "hook/event visibility",
            "budget visibility",
            "no physical stop blocking claim without host lifecycle stop hook",
        ]
        for phrase in required_phrases:
            self.assertIn(phrase, text)

        self.assertIn("Claude Code | L3", text)
        self.assertIn("OpenCode | L2", text)
        self.assertIn("Codex | L1", text)
        self.assertIn("Pi | L1", text)
        self.assertNotIn("OpenCode | L3", text)
        self.assertNotIn("Codex | L3", text)
        self.assertNotIn("Pi | L3", text)

    def test_subagent_supervision_doc_defines_evidence_glossary(self) -> None:
        text = (REPO_ROOT / "references" / "subagent-supervision.md").read_text(
            encoding="utf-8"
        )

        required_terms = [
            "child span",
            "child summary",
            "child receipt",
            "proof bundle",
            "child handoff",
            "imported child evidence",
            "delegated budget",
            "orphan child",
        ]
        for term in required_terms:
            self.assertIn(term, text)

        self.assertIn("can support completion only when", text)
        self.assertIn("advisory until parent verification", text)

    def test_subagent_runtime_consistency_doc_defines_five_layers(self) -> None:
        doc_path = REPO_ROOT / "references" / "subagent-runtime-consistency.md"
        text = doc_path.read_text(encoding="utf-8")

        required_phrases = [
            "LLM context",
            "tool permission",
            "workspace/sandbox",
            "ILH_DB_PATH/MCP server",
            "hook/plugin visibility",
            "child context may be fresh while child receipts share parent mission",
            "child runtime is not automatically identical to parent runtime",
        ]
        for phrase in required_phrases:
            self.assertIn(phrase, text)

        forbidden_phrases = [
            "child runtime is automatically identical",
            "subagents inherit all parent tools",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
