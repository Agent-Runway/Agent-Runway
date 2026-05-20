from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
VALID_SECRET_RE = re.compile(r"^[0-9a-f]{64}$")


def load_host_blocking_experiments_module():
    module_path = REPO_ROOT / "scripts" / "host_blocking_experiments.py"
    spec = importlib.util.spec_from_file_location("host_blocking_experiments", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HostBlockingExperimentsTestCase(unittest.TestCase):
    def test_claude_experiment_writes_runtime_store_compatible_secret(self) -> None:
        module = load_host_blocking_experiments_module()
        settings = {
            "hooks": {
                "PreToolUse": [{"hooks": [{"command": "python noop"}]}],
                "Stop": [{"hooks": [{"command": "python noop"}]}],
            }
        }
        hook_results = [
            {
                "returncode": 0,
                "stdout": json.dumps({"hookSpecificOutput": {"permissionDecision": "ask"}}),
                "stderr": "",
            },
            {
                "returncode": 0,
                "stdout": json.dumps({"continue": False}),
                "stderr": "",
            },
        ]

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            with (
                mock.patch.object(module, "generated_settings", return_value=settings),
                mock.patch.object(module, "invoke_hook", side_effect=hook_results),
                mock.patch.object(module, "prepare_active_mission", return_value=None),
            ):
                result = module.experiment_claude(tmp)

            secret_value = (tmp / "secret.key").read_text(encoding="utf-8").strip()
            self.assertTrue(result["passed"])
            self.assertRegex(secret_value, VALID_SECRET_RE)

    def test_opencode_experiment_writes_runtime_store_compatible_secret(self) -> None:
        module = load_host_blocking_experiments_module()
        settings = {"mcp": {"agent-runway": {"environment": {}}}}
        run_result = {
            "returncode": 0,
            "stdout": json.dumps({"blocked": True, "message": "state path blocked"}),
            "stderr": "",
        }

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            with (
                mock.patch.object(module, "generated_settings", return_value=settings),
                mock.patch.object(module, "run", return_value=run_result),
            ):
                result = module.experiment_opencode(tmp)

            secret_value = (tmp / "secret.key").read_text(encoding="utf-8").strip()
            self.assertTrue(result["passed"])
            self.assertRegex(secret_value, VALID_SECRET_RE)


if __name__ == "__main__":
    unittest.main()
