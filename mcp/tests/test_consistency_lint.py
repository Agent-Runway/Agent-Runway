from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class ConsistencyLintTestCase(unittest.TestCase):
    def test_consistency_lint_rejects_project_learning_mcp_tools(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir(parents=True)
            (root / "mcp").mkdir(parents=True)
            (root / "scripts").mkdir(parents=True)

            (root / "SKILL.md").write_text(
                "runtime-capability-matrix.md\n"
                "runtime-claim-manifest.json\n"
                "generation-4-scorecards.md\n"
                "current-release.md\n"
                "project-learning-ledger-policy.md\n",
                encoding="utf-8",
            )
            (root / "mcp" / "README.md").write_text("# MCP\n", encoding="utf-8")
            (root / "references" / "release-gates.md").write_text(
                "consistency lint\nclaim-parity audit\nledger guard\npackage validation gate\nproject_learning_lint\n",
                encoding="utf-8",
            )
            (root / "references" / "quickstart.md").write_text(
                "consistency lint\nclaim-parity audit\nproject learning lint\nledger guard\npackage validation gate\n",
                encoding="utf-8",
            )
            (root / "references" / "current-release.md").write_text(
                "v0.35\n15-gate\npackage_skill_validation\nproject_learning_lint\nreceipt nonce\n",
                encoding="utf-8",
            )
            (root / "references" / "project-learning-ledger-policy.md").write_text(
                "Memory is not evidence\nPreference is not authorization\nMemory Routing\nNon-Goals\n",
                encoding="utf-8",
            )
            (root / "references" / "project-learning-ledger.jsonl").write_text("", encoding="utf-8")
            (root / "references" / "project-learning-ledger.schema.json").write_text("{}", encoding="utf-8")
            (root / "references" / "runtime-capability-matrix.md").write_text("matrix\n", encoding="utf-8")
            (root / "references" / "runtime-claim-manifest.json").write_text(json.dumps({"claims": []}), encoding="utf-8")
            (root / "mcp" / "server.py").write_text(
                "def mission_lock():\n    pass\n\n"
                "def record_project_learning():\n    pass\n\n"
                "def query_project_learning():\n    pass\n",
                encoding="utf-8",
            )
            (root / "scripts" / "release_gate.py").write_text(
                "scripts/consistency_lint.py\n"
                "scripts/claim_parity_audit.py\n"
                "scripts/project_learning_lint.py\n"
                "scripts/ledger_guard.py\n"
                "scripts/package_skill_check.py\n"
                "scripts/release_static_checks.py\n",
                encoding="utf-8",
            )
            (root / "scripts" / "project_learning_lint.py").write_text("", encoding="utf-8")
            (root / "scripts" / "project_learning_query.py").write_text("", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "consistency_lint.py"), str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["passed"])
        self.assertIn(
            "mcp server must not expose def record_project_learning",
            payload["issues"],
        )
        self.assertIn(
            "mcp server must not expose def query_project_learning",
            payload["issues"],
        )

    def test_consistency_lint_requires_project_learning_non_goals_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir(parents=True)
            (root / "mcp").mkdir(parents=True)
            (root / "scripts").mkdir(parents=True)

            (root / "SKILL.md").write_text(
                "runtime-capability-matrix.md\n"
                "runtime-claim-manifest.json\n"
                "generation-4-scorecards.md\n"
                "current-release.md\n"
                "project-learning-ledger-policy.md\n",
                encoding="utf-8",
            )
            (root / "mcp" / "README.md").write_text("# MCP\n", encoding="utf-8")
            (root / "references" / "release-gates.md").write_text(
                "consistency lint\nclaim-parity audit\nledger guard\npackage validation gate\nproject_learning_lint\n",
                encoding="utf-8",
            )
            (root / "references" / "quickstart.md").write_text(
                "consistency lint\nclaim-parity audit\nproject learning lint\nledger guard\npackage validation gate\n",
                encoding="utf-8",
            )
            (root / "references" / "current-release.md").write_text(
                "v0.35\n15-gate\npackage_skill_validation\nproject_learning_lint\nreceipt nonce\n",
                encoding="utf-8",
            )
            (root / "references" / "project-learning-ledger-policy.md").write_text(
                "Memory is not evidence\nPreference is not authorization\nMemory Routing\n",
                encoding="utf-8",
            )
            (root / "references" / "project-learning-ledger.jsonl").write_text("", encoding="utf-8")
            (root / "references" / "project-learning-ledger.schema.json").write_text("{}", encoding="utf-8")
            (root / "references" / "runtime-capability-matrix.md").write_text("matrix\n", encoding="utf-8")
            (root / "references" / "runtime-claim-manifest.json").write_text(json.dumps({"claims": []}), encoding="utf-8")
            (root / "mcp" / "server.py").write_text("def mission_lock():\n    pass\n", encoding="utf-8")
            (root / "scripts" / "release_gate.py").write_text(
                "scripts/consistency_lint.py\n"
                "scripts/claim_parity_audit.py\n"
                "scripts/project_learning_lint.py\n"
                "scripts/ledger_guard.py\n"
                "scripts/package_skill_check.py\n"
                "scripts/release_static_checks.py\n",
                encoding="utf-8",
            )
            (root / "scripts" / "project_learning_lint.py").write_text("", encoding="utf-8")
            (root / "scripts" / "project_learning_query.py").write_text("", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "consistency_lint.py"), str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["passed"])
        self.assertIn(
            "project learning policy missing phrase: Non-Goals",
            payload["issues"],
        )

    def test_consistency_lint_fails_when_bridge_hook_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir(parents=True)
            (root / "mcp").mkdir(parents=True)
            (root / "scripts").mkdir(parents=True)

            (root / "SKILL.md").write_text(
                "runtime-capability-matrix.md\n"
                "runtime-claim-manifest.json\n"
                "generation-4-scorecards.md\n"
                "current-release.md\n"
                "project-learning-ledger-policy.md\n",
                encoding="utf-8",
            )
            (root / "mcp" / "README.md").write_text("# MCP\n", encoding="utf-8")
            (root / "references" / "release-gates.md").write_text(
                "consistency lint\nclaim-parity audit\nledger guard\npackage validation gate\nproject_learning_lint\n",
                encoding="utf-8",
            )
            (root / "references" / "quickstart.md").write_text(
                "consistency lint\nclaim-parity audit\nproject learning lint\nledger guard\npackage validation gate\n",
                encoding="utf-8",
            )
            (root / "references" / "current-release.md").write_text(
                "v0.35\n15-gate\npackage_skill_validation\nproject_learning_lint\nreceipt nonce\n",
                encoding="utf-8",
            )
            (root / "references" / "project-learning-ledger-policy.md").write_text(
                "Memory is not evidence\nPreference is not authorization\nMemory Routing\n",
                encoding="utf-8",
            )
            (root / "references" / "project-learning-ledger.jsonl").write_text("", encoding="utf-8")
            (root / "references" / "project-learning-ledger.schema.json").write_text("{}", encoding="utf-8")
            (root / "references" / "runtime-capability-matrix.md").write_text(
                "| Capability | soft mode | hosted mode |\n"
                "|---|---|---|\n"
                "| bridge gate | advisory | enforced |\n",
                encoding="utf-8",
            )
            (root / "references" / "runtime-claim-manifest.json").write_text(
                json.dumps(
                    {
                        "claims": [
                            {
                                "id": "opencode-plugin-bridge",
                                "required_files": ["scripts/opencode_plugin_bridge.py"],
                                "required_tools": [],
                                "required_hooks": ["pre_tool_use"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "mcp" / "server.py").write_text("def mission_lock():\n    pass\n", encoding="utf-8")
            (root / "scripts" / "claude_hooks.py").write_text(
                "def pre_tool_use():\n    pass\n",
                encoding="utf-8",
            )
            (root / "scripts" / "opencode_plugin_bridge.py").write_text(
                "def post_tool_use():\n    pass\n",
                encoding="utf-8",
            )
            (root / "scripts" / "release_gate.py").write_text(
                "scripts/consistency_lint.py\n"
                "scripts/claim_parity_audit.py\n"
                "scripts/project_learning_lint.py\n"
                "scripts/ledger_guard.py\n"
                "scripts/package_skill_check.py\n"
                "scripts/release_static_checks.py\n",
                encoding="utf-8",
            )
            (root / "scripts" / "project_learning_lint.py").write_text("", encoding="utf-8")
            (root / "scripts" / "project_learning_query.py").write_text("", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "consistency_lint.py"), str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["passed"])
        self.assertIn(
            "claim opencode-plugin-bridge references missing hook: pre_tool_use",
            payload["issues"],
        )

    def test_consistency_lint_rejects_old_opencode_bridge_mcp_only_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir(parents=True)
            (root / "mcp").mkdir(parents=True)
            (root / "scripts").mkdir(parents=True)

            (root / "SKILL.md").write_text(
                "runtime-capability-matrix.md\n"
                "runtime-claim-manifest.json\n"
                "generation-4-scorecards.md\n"
                "current-release.md\n"
                "project-learning-ledger-policy.md\n",
                encoding="utf-8",
            )
            (root / "mcp" / "README.md").write_text("# MCP\n", encoding="utf-8")
            (root / "README.md").write_text(
                "Project Learning Ledger\n"
                "Change `ILH_OPENCODE_BRIDGE` from `\"0\"` to `\"1\"` inside the generated `mcp.agent-runway.environment` block.\n",
                encoding="utf-8",
            )
            (root / "README_cn.md").write_text("Project Learning Ledger\n", encoding="utf-8")
            (root / "references" / "release-gates.md").write_text(
                "consistency lint\nclaim-parity audit\nledger guard\npackage validation gate\nproject_learning_lint\n",
                encoding="utf-8",
            )
            (root / "references" / "quickstart.md").write_text(
                "consistency lint\nclaim-parity audit\nproject learning lint\nledger guard\npackage validation gate\n",
                encoding="utf-8",
            )
            (root / "references" / "current-release.md").write_text(
                "v0.35\n15-gate\npackage_skill_validation\nproject_learning_lint\nreceipt nonce\n",
                encoding="utf-8",
            )
            (root / "references" / "project-learning-ledger-policy.md").write_text(
                "Memory is not evidence\nPreference is not authorization\nMemory Routing\nNon-Goals\nThreat Model\n"
                "read-only mcp query\ncontrolled mcp write tools\nsqlite index cache\nmarkdown export\ncross-project import\n",
                encoding="utf-8",
            )
            (root / "references" / "project-learning-ledger.jsonl").write_text("", encoding="utf-8")
            (root / "references" / "project-learning-ledger.schema.json").write_text("{}", encoding="utf-8")
            (root / "references" / "runtime-capability-matrix.md").write_text("matrix\n", encoding="utf-8")
            (root / "references" / "runtime-claim-manifest.json").write_text(json.dumps({"claims": []}), encoding="utf-8")
            (root / "references" / "examples.md").write_text(
                "Example 3: project learning ledger JSONL snippets\n`pitfall`\n`runbook`\n`preference`\n`invariant`\n",
                encoding="utf-8",
            )
            (root / "mcp" / "server.py").write_text("def mission_lock():\n    pass\n", encoding="utf-8")
            (root / "scripts" / "release_gate.py").write_text(
                "scripts/consistency_lint.py\n"
                "scripts/claim_parity_audit.py\n"
                "scripts/project_learning_lint.py\n"
                "scripts/ledger_guard.py\n"
                "scripts/package_skill_check.py\n"
                "scripts/release_static_checks.py\n",
                encoding="utf-8",
            )
            (root / "scripts" / "project_learning_lint.py").write_text("", encoding="utf-8")
            (root / "scripts" / "project_learning_query.py").write_text("", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "consistency_lint.py"), str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["passed"])
        self.assertIn(
            "readme preserves the old misleading ILH_OPENCODE_BRIDGE MCP-environment-only guidance",
            payload["issues"],
        )

    def test_consistency_lint_requires_opencode_bridge_discovery_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir(parents=True)
            (root / "mcp").mkdir(parents=True)
            (root / "scripts").mkdir(parents=True)

            (root / "SKILL.md").write_text(
                "runtime-capability-matrix.md\n"
                "runtime-claim-manifest.json\n"
                "generation-4-scorecards.md\n"
                "current-release.md\n"
                "project-learning-ledger-policy.md\n",
                encoding="utf-8",
            )
            (root / "mcp" / "README.md").write_text("# MCP\n", encoding="utf-8")
            (root / "README.md").write_text(
                "Project Learning Ledger\n"
                "Set `ILH_OPENCODE_BRIDGE=1` in your OpenCode configuration.\n",
                encoding="utf-8",
            )
            (root / "README_cn.md").write_text("Project Learning Ledger\n", encoding="utf-8")
            (root / "references" / "release-gates.md").write_text(
                "consistency lint\nclaim-parity audit\nledger guard\npackage validation gate\nproject_learning_lint\n",
                encoding="utf-8",
            )
            (root / "references" / "quickstart.md").write_text(
                "consistency lint\nclaim-parity audit\nproject learning lint\nledger guard\npackage validation gate\n",
                encoding="utf-8",
            )
            (root / "references" / "current-release.md").write_text(
                "v0.35\n15-gate\npackage_skill_validation\nproject_learning_lint\nreceipt nonce\n",
                encoding="utf-8",
            )
            (root / "references" / "project-learning-ledger-policy.md").write_text(
                "Memory is not evidence\nPreference is not authorization\nMemory Routing\nNon-Goals\nThreat Model\n"
                "read-only mcp query\ncontrolled mcp write tools\nsqlite index cache\nmarkdown export\ncross-project import\n",
                encoding="utf-8",
            )
            (root / "references" / "project-learning-ledger.jsonl").write_text("", encoding="utf-8")
            (root / "references" / "project-learning-ledger.schema.json").write_text("{}", encoding="utf-8")
            (root / "references" / "runtime-capability-matrix.md").write_text("matrix\n", encoding="utf-8")
            (root / "references" / "runtime-claim-manifest.json").write_text(json.dumps({"claims": []}), encoding="utf-8")
            (root / "references" / "examples.md").write_text(
                "Example 3: project learning ledger JSONL snippets\n`pitfall`\n`runbook`\n`preference`\n`invariant`\n",
                encoding="utf-8",
            )
            (root / "mcp" / "server.py").write_text("def mission_lock():\n    pass\n", encoding="utf-8")
            (root / "scripts" / "release_gate.py").write_text(
                "scripts/consistency_lint.py\n"
                "scripts/claim_parity_audit.py\n"
                "scripts/project_learning_lint.py\n"
                "scripts/ledger_guard.py\n"
                "scripts/package_skill_check.py\n"
                "scripts/release_static_checks.py\n",
                encoding="utf-8",
            )
            (root / "scripts" / "project_learning_lint.py").write_text("", encoding="utf-8")
            (root / "scripts" / "project_learning_query.py").write_text("", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "consistency_lint.py"), str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["passed"])
        self.assertIn(
            "readme missing OpenCode bridge discovery guidance: .opencode/plugins/",
            payload["issues"],
        )


if __name__ == "__main__":
    unittest.main()
