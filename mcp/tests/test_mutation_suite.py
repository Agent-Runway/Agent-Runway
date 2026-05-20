from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import importlib.util


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_mutation_suite_module():
    module_path = REPO_ROOT / "scripts" / "adversarial_mutation_suite.py"
    spec = importlib.util.spec_from_file_location("adversarial_mutation_suite", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MutationSuiteTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "mcp").mkdir(parents=True)
        (self.root / "scripts").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_remove_budget_status_from_handoff_mutates_current_server_format(self) -> None:
        mutate_remove_budget_status_from_handoff = load_mutation_suite_module().mutate_remove_budget_status_from_handoff

        server_path = self.root / "mcp" / "server.py"
        server_path.write_text(
            'payload = {\n    "budget_status": _budget_snapshot(session_id, task_scope, mission),\n}\n',
            encoding="utf-8",
        )

        mutate_remove_budget_status_from_handoff(self.root)
        mutated = server_path.read_text(encoding="utf-8")
        self.assertIn('"budget_status_removed": _budget_snapshot(session_id, task_id, mission),', mutated)
        self.assertNotIn('"budget_status": _budget_snapshot(session_id, task_scope, mission),', mutated)

    def test_remove_authorization_handoff_mutates_current_server_format(self) -> None:
        mutate_remove_authorization_handoff = load_mutation_suite_module().mutate_remove_authorization_handoff

        server_path = self.root / "mcp" / "server.py"
        server_path.write_text(
            'payload = {\n    "latest_user_authorization": _authorization_payload(session_id, task_id, latest_authorization),\n}\n',
            encoding="utf-8",
        )

        mutate_remove_authorization_handoff(self.root)
        mutated = server_path.read_text(encoding="utf-8")
        self.assertIn('"latest_user_authorization_removed": _authorization_payload(session_id, task_id, latest_authorization),', mutated)
        self.assertNotIn('"latest_user_authorization": _authorization_payload(session_id, task_id, latest_authorization),', mutated)

    def test_remove_authorization_handoff_mutates_multiline_current_server_format(self) -> None:
        mutate_remove_authorization_handoff = load_mutation_suite_module().mutate_remove_authorization_handoff

        server_path = self.root / "mcp" / "server.py"
        server_path.write_text(
            'payload = {\n    "latest_user_authorization": _authorization_payload(\n        session_id, task_id, latest_authorization\n    ),\n}\n',
            encoding="utf-8",
        )

        mutate_remove_authorization_handoff(self.root)
        mutated = server_path.read_text(encoding="utf-8")
        self.assertIn('"latest_user_authorization_removed": _authorization_payload(', mutated)
        self.assertNotIn('"latest_user_authorization": _authorization_payload(', mutated)

    def test_release_gate_without_parity_mutates_current_builder_format(self) -> None:
        mutate_release_gate_without_parity = load_mutation_suite_module().mutate_release_gate_without_parity

        release_gate_path = self.root / "scripts" / "release_gate.py"
        release_gate_path.write_text(
            "def build_ordered_checks(root):\n"
            "    return [\n"
            "        ('consistency_lint', 'run', [sys.executable, 'scripts/consistency_lint.py', str(root)], 30),\n"
            "        ('claim_parity_audit', 'run', [sys.executable, 'scripts/claim_parity_audit.py', str(root)], 30),\n"
            "        ('ledger_guard', 'run', [sys.executable, 'scripts/ledger_guard.py', str(root)], 30),\n"
            "    ]\n",
            encoding="utf-8",
        )

        mutate_release_gate_without_parity(self.root)
        mutated = release_gate_path.read_text(encoding="utf-8")
        self.assertNotIn("'claim_parity_audit'", mutated)

    def test_project_learning_mutants_run_tests_not_mutated_lint_directly(self) -> None:
        module = load_mutation_suite_module()

        cmd = module.command_for("project_learning", self.root)
        joined = " ".join(cmd)

        self.assertIn("unittest", joined)
        self.assertIn("discover", joined)
        self.assertIn("mcp/tests", joined.replace("\\", "/"))
        self.assertIn("test_project_learning.py", joined)
        self.assertNotIn("project_learning_lint.py", joined)

    def test_project_learning_mutant_catalog_covers_csv_required_lint_failures(self) -> None:
        module = load_mutation_suite_module()

        mutant_names = {item[0] for item in module.build_mutants()}

        self.assertIn("project_learning_completion_guard_removed", mutant_names)
        self.assertIn("project_learning_preference_auth_allowed", mutant_names)
        self.assertIn("project_learning_secret_scan_disabled", mutant_names)
        self.assertIn("project_learning_duplicate_ids_allowed", mutant_names)
        self.assertIn("project_learning_unknown_type_allowed", mutant_names)
        self.assertIn("project_learning_gate_removed", mutant_names)
        self.assertIn("adversarial_audit_gate_removed", mutant_names)
        self.assertIn("adversarial_audit_lint_removed", mutant_names)


if __name__ == "__main__":
    unittest.main()
