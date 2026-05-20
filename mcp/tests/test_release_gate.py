from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_release_gate_module():
    module_path = REPO_ROOT / "scripts" / "release_gate.py"
    spec = importlib.util.spec_from_file_location("release_gate", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_script_module(name: str):
    module_path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def adversarial_audit_required_artifacts() -> list[str]:
    return [
        "references/adversarial-audit.md",
        "references/adversarial-audit-rubric.md",
        "references/adversarial-audit-threat-model.md",
        "references/adversarial-audit-schema.json",
        "references/adversarial-audit-examples.md",
        "references/adversarial-audit-profiles.json",
        "scripts/adversarial_audit_lint.py",
        "scripts/adversarial_audit_suite.py",
        "mcp/agent_runway_runtime/adversarial_audit.py",
        "mcp/agent_runway_runtime/adversarial_audit_plan_edges.py",
        "mcp/agent_runway_runtime/adversarial_audit_reading.py",
        "mcp/tests/test_adversarial_audit.py",
        "mcp/tests/test_adversarial_audit_plan_edges.py",
        "mcp/tests/test_adversarial_audit_direct_helper_edges.py",
        "mcp/tests/test_adversarial_audit_read_errors.py",
        "mcp/tests/test_adversarial_audit_type_edges.py",
    ]


def opencode_bridge_required_artifacts() -> list[str]:
    return [
        ".opencode/plugins/agent-runway.js",
        "scripts/opencode_plugin_bridge.py",
        "mcp/tests/test_opencode_plugin.py",
        "mcp/tests/test_opencode_bridge_jsonc_parser.py",
        "mcp/tests/test_opencode_bridge_payload_edges.py",
        "mcp/tests/test_opencode_plugin_jsonc_edges.py",
        "mcp/tests/test_opencode_plugin_duration_edges.py",
        "mcp/tests/test_release_gate.py",
        "mcp/tests/test_hooks.py",
        "mcp/tests/test_hook_payload_edges.py",
        "mcp/tests/test_debug_logging.py",
    ]


def host_risk_interception_required_artifacts() -> list[str]:
    return [
        "scripts/claude_hooks.py",
        "mcp/agent_runway_runtime/debug_logging.py",
        "mcp/tests/test_hooks.py",
        "mcp/tests/test_hook_payload_edges.py",
        "mcp/tests/test_debug_logging.py",
        "references/runtime-capability-matrix.md",
    ]


class ReleaseGateTestCase(unittest.TestCase):
    def test_release_gate_declares_all_sixteen_mandatory_gates(self) -> None:
        module = load_release_gate_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checks = module.build_ordered_checks(root)
        names = [check[0] for check in checks]
        self.assertEqual(len(names), 16)
        self.assertEqual(names[0], "quick_validate")
        self.assertEqual(names[1], "package_skill_validation")
        self.assertIn("project_learning_lint", names)
        self.assertLess(names.index("claim_parity_audit"), names.index("project_learning_lint"))
        self.assertLess(names.index("project_learning_lint"), names.index("ledger_guard"))
        self.assertLess(names.index("benchmark_suite"), names.index("adversarial_audit_suite"))
        self.assertIn("adversarial_audit_suite", names)
        self.assertIn("quick_validate.py", " ".join(checks[0][2]))
        self.assertIn("package_skill_check.py", " ".join(checks[1][2]))
        for expected in [
            "evolution_ledger_updated",
            "generation4_scorecards_updated",
            "claims_reflected",
            "release_report_and_version",
        ]:
            self.assertIn(expected, names)

    def test_release_gate_runs_project_learning_lint_in_strict_mode_against_canonical_ledger(self) -> None:
        module = load_release_gate_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checks = module.build_ordered_checks(root)
        target = next(check for check in checks if check[0] == "project_learning_lint")
        self.assertEqual(target[1], "run")
        self.assertIn("project_learning_lint.py", " ".join(target[2]))
        self.assertIn("project-learning-ledger.jsonl", " ".join(target[2]))
        self.assertIn("--strict", target[2])

    def test_release_static_check_project_learning_valid_requires_core_artifacts(self) -> None:
        module = load_script_module("release_static_checks")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir(parents=True)
            (root / "scripts").mkdir(parents=True)
            (root / "references" / "project-learning-ledger-policy.md").write_text(
                "Memory is not evidence\nPreference is not authorization\nMemory Routing\nNon-Goals\n",
                encoding="utf-8",
            )
            (root / "references" / "project-learning-ledger.jsonl").write_text("", encoding="utf-8")
            (root / "references" / "project-learning-ledger.schema.json").write_text("{}", encoding="utf-8")
            (root / "scripts" / "project_learning_lint.py").write_text("print('ok')\n", encoding="utf-8")
            passed, issues = module.check(root, "project_learning_valid")
        self.assertFalse(passed)
        self.assertIn("missing project learning artifact: scripts/project_learning_query.py", issues)

    def test_release_static_check_adversarial_audit_valid_requires_edge_artifacts(self) -> None:
        module = load_script_module("release_static_checks")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel in adversarial_audit_required_artifacts()[:-1]:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("bounded falsification\nnever proves absence of bugs\nNo full multi-agent scheduler\n", encoding="utf-8")

            passed, issues = module.check(root, "adversarial_audit_valid")

        self.assertFalse(passed)
        self.assertIn(
            "missing adversarial audit artifact: mcp/tests/test_adversarial_audit_type_edges.py",
            issues,
        )

    def test_runtime_manifest_adversarial_claim_lists_edge_artifacts(self) -> None:
        manifest = json.loads((REPO_ROOT / "references" / "runtime-claim-manifest.json").read_text(encoding="utf-8"))
        claim = next(item for item in manifest["claims"] if item["id"] == "adversarial-audit-gate")

        for rel in adversarial_audit_required_artifacts():
            self.assertIn(rel, claim["required_files"])

    def test_runtime_manifest_opencode_claim_lists_edge_artifacts(self) -> None:
        manifest = json.loads((REPO_ROOT / "references" / "runtime-claim-manifest.json").read_text(encoding="utf-8"))
        claim = next(item for item in manifest["claims"] if item["id"] == "opencode-plugin-bridge")

        for rel in opencode_bridge_required_artifacts():
            self.assertIn(rel, claim["required_files"])

    def test_runtime_manifest_host_risk_claim_lists_payload_edge_artifacts(self) -> None:
        manifest = json.loads((REPO_ROOT / "references" / "runtime-claim-manifest.json").read_text(encoding="utf-8"))
        claim = next(item for item in manifest["claims"] if item["id"] == "host-risk-interception")

        for rel in host_risk_interception_required_artifacts():
            self.assertIn(rel, claim["required_files"])

    def test_runtime_manifest_receipt_claim_lists_scope_edge_artifacts(self) -> None:
        manifest = json.loads((REPO_ROOT / "references" / "runtime-claim-manifest.json").read_text(encoding="utf-8"))
        claim = next(item for item in manifest["claims"] if item["id"] == "receipt-integrity")

        self.assertIn("mcp/tests/test_receipt_scope_edges.py", claim["required_files"])
        self.assertIn("mcp/tests/test_receipt_scope_validation_edges.py", claim["required_files"])

    def test_release_static_check_release_report_and_version_demands_v036_and_16_gates(self) -> None:
        module = load_script_module("release_static_checks")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir(parents=True)
            (root / "scripts").mkdir(parents=True)
            (root / "scripts" / "release_gate.py").write_text(
                '("quick_validate", "run", [], 30)\n("package_skill_validation", "run", [], 30)\n',
                encoding="utf-8",
            )
            (root / "references" / "current-release.md").write_text("v0.35\n15-gate\npackage_skill_validation\nreceipt nonce\n", encoding="utf-8")
            passed, issues = module.check(root, "release_report_and_version")
        self.assertFalse(passed)
        self.assertTrue(any("instead of 16" in item for item in issues))
        self.assertTrue(any("missing 'v0.36'" in item or 'missing \"v0.36\"' in item for item in issues))

    def test_release_static_check_claims_reflected_requires_v036_claims(self) -> None:
        module = load_script_module("release_static_checks")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir(parents=True)
            (root / "scripts").mkdir(parents=True)
            (root / "mcp" / "tests").mkdir(parents=True)
            (root / ".opencode" / "plugins").mkdir(parents=True)
            (root / "references" / "runtime-claim-manifest.json").write_text(
                json.dumps(
                    {
                        "claims": [
                            {"id": "release-discipline"},
                            {"id": "opencode-plugin-bridge"},
                            {"id": "evolution-evidence"},
                            {"id": "project-learning-ledger"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            for rel in [
                "scripts/package_skill_check.py",
                "scripts/release_static_checks.py",
                "scripts/project_learning_lint.py",
                "scripts/project_learning_query.py",
                "scripts/adversarial_audit_lint.py",
                "scripts/adversarial_audit_suite.py",
                "mcp/tests/test_release_gate.py",
                "mcp/tests/test_project_learning.py",
                "mcp/tests/test_project_learning_lint.py",
                "mcp/tests/test_adversarial_audit.py",
                "mcp/tests/test_generate_host_config.py",
                "mcp/tests/test_runtime_regressions.py",
                "mcp/tests/test_receipt_scope_edges.py",
                "mcp/tests/test_receipt_scope_validation_edges.py",
                "scripts/host_blocking_experiments.py",
                "scripts/fixtures/pi_block_extension.js",
                "scripts/fixtures/opencode_block_experiment.mjs",
                ".opencode/plugins/agent-runway.js",
                "references/project-learning-ledger.jsonl",
                "references/project-learning-ledger.schema.json",
                "references/project-learning-ledger-policy.md",
                "references/adversarial-audit.md",
                "references/adversarial-audit-rubric.md",
                "references/adversarial-audit-threat-model.md",
                "references/adversarial-audit-schema.json",
                "references/adversarial-audit-examples.md",
                "references/adversarial-audit-profiles.json",
            ]:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ok\n", encoding="utf-8")
            passed, issues = module.check(root, "claims_reflected")
        self.assertFalse(passed)
        self.assertIn("manifest missing claim adversarial-audit-gate", issues)
        self.assertIn("manifest missing claim host-blocking-experiments", issues)

    def test_opencode_plugin_source_forwards_input_args_and_fails_closed_on_ask(self) -> None:
        plugin_text = (REPO_ROOT / ".opencode" / "plugins" / "agent-runway.js").read_text(encoding="utf-8")
        self.assertIn("ILH_OPENCODE_BRIDGE", plugin_text)
        self.assertIn("tool_input: input.args || {}", plugin_text)
        self.assertNotIn("tool_input: output.args || {}", plugin_text)
        self.assertIn("proc.error", plugin_text)
        self.assertIn("stderr: output.stderr", plugin_text)
        self.assertIn("bridge returned no decision", plugin_text)
        self.assertIn("bridge returned invalid decision", plugin_text)
        self.assertIn("Array.isArray(result)", plugin_text)
        self.assertIn('result.decision === "ask"', plugin_text)
        self.assertIn("host confirmation", plugin_text)

    def run_opencode_before_hook(
        self, command: str, secret_path: Path, bridge_enabled: bool = True
    ) -> dict:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for OpenCode plugin behavior test")
        plugin = (REPO_ROOT / ".opencode" / "plugins" / "agent-runway.js").as_posix()
        script = textwrap.dedent(
            f"""
            import {{ pathToFileURL }} from "node:url";
            const pluginUrl = pathToFileURL({json.dumps(str(REPO_ROOT / '.opencode' / 'plugins' / 'agent-runway.js'))}).href;
            const {{ default: plugin }} = await import(pluginUrl);
            const server = await plugin.server();
            try {{
              await server["tool.execute.before"](
                {{sessionID: "node-test", tool: "bash", args: {{command: {json.dumps(command)}}}}},
                {{args: {{}}}}
              );
              console.log(JSON.stringify({{threw: false}}));
            }} catch (error) {{
              console.log(JSON.stringify({{threw: true, message: String(error.message || error)}}));
            }}
            """
        )
        env = os.environ.copy()
        env["ILH_SECRET_PATH"] = str(secret_path)
        env["ILH_DB_PATH"] = str(secret_path.parent / "state.db")
        env["ILH_PYTHON"] = sys.executable
        if bridge_enabled:
            env["ILH_OPENCODE_BRIDGE"] = "1"
        else:
            env.pop("ILH_OPENCODE_BRIDGE", None)
            sandbox_home = secret_path.parent / "home"
            sandbox_home.mkdir(parents=True, exist_ok=True)
            env["HOME"] = str(sandbox_home)
            env["USERPROFILE"] = str(sandbox_home)
            env["OPENCODE_CONFIG_PATH"] = str(sandbox_home / "missing-opencode.json")
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        for line in reversed(proc.stdout.splitlines()):
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
        raise AssertionError(f"unexpected stubbed bridge output: {proc.stdout!r}")

    def run_opencode_before_hook_with_stubbed_bridge(self, stdout_text: str) -> dict:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for OpenCode plugin behavior test")
        script = textwrap.dedent(
            f"""
            import fs from "node:fs";
            import os from "node:os";
            import path from "node:path";
            import {{ pathToFileURL }} from "node:url";

            const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "agent-runway-bridge-"));
            const pluginDir = path.join(tmp, ".opencode", "plugins");
            const scriptsDir = path.join(tmp, "scripts");
            fs.mkdirSync(pluginDir, {{ recursive: true }});
            fs.mkdirSync(scriptsDir, {{ recursive: true }});
            fs.copyFileSync({json.dumps(str(REPO_ROOT / '.opencode' / 'plugins' / 'agent-runway.js'))}, path.join(pluginDir, "agent-runway.js"));
            fs.writeFileSync(path.join(scriptsDir, "opencode_plugin_bridge.py"), {json.dumps(stdout_text)}, "utf8");

            const pluginUrl = pathToFileURL(path.join(pluginDir, "agent-runway.js")).href;
            const {{ default: plugin }} = await import(pluginUrl);
            const server = await plugin.server();
            try {{
              await server["tool.execute.before"](
                {{sessionID: "node-test", tool: "bash", args: {{command: "pytest -q"}}}},
                {{args: {{}}}}
              );
              console.log(JSON.stringify({{threw: false}}));
            }} catch (error) {{
              console.log(JSON.stringify({{threw: true, message: String(error.message || error)}}));
            }}
            """
        )
        env = os.environ.copy()
        env["ILH_OPENCODE_BRIDGE"] = "1"
        env["ILH_PYTHON"] = sys.executable
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        for line in reversed(proc.stdout.splitlines()):
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
        raise AssertionError(f"unexpected stubbed bridge output: {proc.stdout!r}")

    def run_opencode_before_hook_with_config_content(self, config: dict) -> dict:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for OpenCode plugin behavior test")
        script = textwrap.dedent(
            f"""
            import {{ pathToFileURL }} from "node:url";
            const pluginUrl = pathToFileURL({json.dumps(str(REPO_ROOT / '.opencode' / 'plugins' / 'agent-runway.js'))}).href;
            const {{ default: plugin }} = await import(pluginUrl);
            const server = await plugin.server();
            try {{
              await server["tool.execute.before"](
                {{sessionID: "node-test", tool: "bash", args: {{command: "git push origin main"}}}},
                {{args: {{}}}}
              );
              console.log(JSON.stringify({{threw: false}}));
            }} catch (error) {{
              console.log(JSON.stringify({{threw: true, message: String(error.message || error)}}));
            }}
            """
        )
        env = os.environ.copy()
        env["ILH_PYTHON"] = sys.executable
        env.pop("ILH_OPENCODE_BRIDGE", None)
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        for line in reversed(proc.stdout.splitlines()):
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
        raise AssertionError(f"unexpected config-content bridge output: {proc.stdout!r}")

    def run_opencode_before_hook_with_config_file(self, config: dict) -> dict:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for OpenCode plugin behavior test")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            config_dir = root / ".opencode"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "opencode.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            script = textwrap.dedent(
                f"""
                import {{ pathToFileURL }} from "node:url";
                const pluginUrl = pathToFileURL({json.dumps(str(REPO_ROOT / '.opencode' / 'plugins' / 'agent-runway.js'))}).href;
                const {{ default: plugin }} = await import(pluginUrl);
                const server = await plugin.server();
                try {{
                  await server["tool.execute.before"](
                    {{sessionID: "node-test", tool: "bash", args: {{command: "git push origin main"}}}},
                    {{args: {{}}}}
                  );
                  console.log(JSON.stringify({{threw: false}}));
                }} catch (error) {{
                  console.log(JSON.stringify({{threw: true, message: String(error.message || error)}}));
                }}
                """
            )
            env = os.environ.copy()
            env["ILH_PYTHON"] = sys.executable
            env.pop("ILH_OPENCODE_BRIDGE", None)
            env.pop("OPENCODE_CONFIG_CONTENT", None)
            env.pop("OPENCODE_CONFIG_PATH", None)
            env["HOME"] = str(root)
            env["USERPROFILE"] = str(root)
            proc = subprocess.run(
                [node, "--input-type=module", "-e", script],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=30,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        for line in reversed(proc.stdout.splitlines()):
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
        raise AssertionError(f"unexpected config-file bridge output: {proc.stdout!r}")

    def test_opencode_before_hook_is_disabled_without_env_or_config_fallback(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            secret_path = Path(td) / "secret.key"
            secret_path.write_text("secret\n", encoding="utf-8")
            payload = self.run_opencode_before_hook(
                "git push origin main", secret_path, bridge_enabled=False
            )
        self.assertFalse(payload["threw"], payload)

    def test_opencode_after_hook_is_disabled_by_default(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for OpenCode plugin behavior test")
        script = textwrap.dedent(
            f"""
            import {{ pathToFileURL }} from "node:url";
            const pluginUrl = pathToFileURL({json.dumps(str(REPO_ROOT / '.opencode' / 'plugins' / 'agent-runway.js'))}).href;
            const {{ default: plugin }} = await import(pluginUrl);
            const server = await plugin.server();
            await server["tool.execute.after"](
              {{sessionID: "node-test", tool: "bash", args: {{command: "pytest -q"}}}},
              {{output: "OK", stderr: "", metadata: {{exitCode: 0}}}}
            );
            console.log(JSON.stringify({{ok: true}}));
            """
        )
        env = os.environ.copy()
        env["ILH_PYTHON"] = sys.executable
        env.pop("ILH_OPENCODE_BRIDGE", None)
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn('{"ok":true}', proc.stdout.replace(" ", ""))

    def test_sync_skill_mirrors_defaults_all_use_agent_runway_directory(self) -> None:
        module = load_script_module("sync_skill_mirrors")
        mirrors = module.default_mirrors()
        self.assertTrue(str(mirrors["opencode"]).endswith("skills\\agent-runway"))
        self.assertTrue(str(mirrors["codex"]).endswith("skills\\agent-runway"))
        self.assertTrue(str(mirrors["claude"]).endswith("skills\\agent-runway"))

    def test_release_files_excludes_agent_runway_state_dir_and_todo_csv_but_not_banner(self) -> None:
        module = load_script_module("release_files")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".agent-runway").mkdir()
            (root / ".agent-runway" / "state.db").write_text("db", encoding="utf-8")
            (root / "agent-runway-rename-evaluation TO DO list.csv").write_text("x", encoding="utf-8")
            (root / "agent-runway.png").write_bytes(b"png")
            (root / "README.md").write_text("readme", encoding="utf-8")
            files = module.collect_release_files(root)
        self.assertNotIn(Path(".agent-runway/state.db"), files)
        self.assertNotIn(Path("agent-runway-rename-evaluation TO DO list.csv"), files)
        self.assertIn(Path("agent-runway.png"), files)

    def test_opencode_before_hook_runtime_uses_input_args_not_output_args(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            secret_path = Path(td) / "secret.key"
            secret_path.write_text("secret\n", encoding="utf-8")
            payload = self.run_opencode_before_hook(f"cat {secret_path}", secret_path)
        self.assertTrue(payload["threw"], payload)
        self.assertRegex(payload["message"].lower(), "secret|bridge unavailable")

    def test_opencode_before_hook_runtime_fails_closed_on_ask(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            secret_path = Path(td) / "secret.key"
            secret_path.write_text("secret\n", encoding="utf-8")
            payload = self.run_opencode_before_hook("git push origin main", secret_path)
        self.assertTrue(payload["threw"], payload)
        self.assertRegex(payload["message"].lower(), "host confirmation|bridge unavailable")

    def test_opencode_before_hook_can_enable_bridge_via_opencode_config_content(self) -> None:
        payload = self.run_opencode_before_hook_with_config_content(
            {
                "mcp": {
                    "agent-runway": {
                        "environment": {
                            "ILH_OPENCODE_BRIDGE": "1",
                        }
                    }
                }
            }
        )
        self.assertTrue(payload["threw"], payload)
        self.assertIn("host confirmation", payload["message"].lower())

    def test_opencode_before_hook_can_enable_bridge_via_opencode_config_file(self) -> None:
        payload = self.run_opencode_before_hook_with_config_file(
            {
                "mcp": {
                    "agent-runway": {
                        "environment": {
                            "ILH_OPENCODE_BRIDGE": "1",
                        }
                    }
                }
            }
        )
        self.assertTrue(payload["threw"], payload)
        self.assertIn("host confirmation", payload["message"].lower())

    def test_opencode_env_zero_is_authoritative_over_config_content(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for OpenCode plugin behavior test")
        script = textwrap.dedent(
            f"""
            import {{ pathToFileURL }} from "node:url";
            const pluginUrl = pathToFileURL({json.dumps(str(REPO_ROOT / '.opencode' / 'plugins' / 'agent-runway.js'))}).href;
            const {{ default: plugin }} = await import(pluginUrl);
            const server = await plugin.server();
            try {{
              await server["tool.execute.before"](
                {{sessionID: "node-test", tool: "bash", args: {{command: "git push origin main"}}}},
                {{args: {{}}}}
              );
              console.log(JSON.stringify({{threw: false}}));
            }} catch (error) {{
              console.log(JSON.stringify({{threw: true, message: String(error.message || error)}}));
            }}
            """
        )
        env = os.environ.copy()
        env["ILH_PYTHON"] = sys.executable
        env["ILH_OPENCODE_BRIDGE"] = "0"
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps({
            "mcp": {"agent-runway": {"environment": {"ILH_OPENCODE_BRIDGE": "1"}}}
        })
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn('{"threw":false}', proc.stdout.replace(" ", ""))

    def test_opencode_malformed_config_content_falls_back_to_config_file(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for OpenCode plugin behavior test")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            config_dir = root / ".opencode"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "opencode.json").write_text(
                json.dumps({"mcp": {"agent-runway": {"environment": {"ILH_OPENCODE_BRIDGE": "1"}}}}),
                encoding="utf-8",
            )
            script = textwrap.dedent(
                f"""
                import {{ pathToFileURL }} from "node:url";
                const pluginUrl = pathToFileURL({json.dumps(str(REPO_ROOT / '.opencode' / 'plugins' / 'agent-runway.js'))}).href;
                const {{ default: plugin }} = await import(pluginUrl);
                const server = await plugin.server();
                try {{
                  await server["tool.execute.before"](
                    {{sessionID: "node-test", tool: "bash", args: {{command: "git push origin main"}}}},
                    {{args: {{}}}}
                  );
                  console.log(JSON.stringify({{threw: false}}));
                }} catch (error) {{
                  console.log(JSON.stringify({{threw: true, message: String(error.message || error)}}));
                }}
                """
            )
            env = os.environ.copy()
            env["ILH_PYTHON"] = sys.executable
            env.pop("ILH_OPENCODE_BRIDGE", None)
            env.pop("OPENCODE_CONFIG_PATH", None)
            env["OPENCODE_CONFIG_CONTENT"] = "{bad-json"
            env["HOME"] = str(root)
            env["USERPROFILE"] = str(root)
            proc = subprocess.run(
                [node, "--input-type=module", "-e", script],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=30,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("host confirmation", proc.stdout.lower())

    def test_opencode_explicit_config_path_is_authoritative_over_home_configs(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for OpenCode plugin behavior test")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            home_dir = root / "home"
            (home_dir / ".config" / "opencode").mkdir(parents=True, exist_ok=True)
            (home_dir / ".config" / "opencode" / "opencode.json").write_text(
                json.dumps({"mcp": {"agent-runway": {"environment": {"ILH_OPENCODE_BRIDGE": "1"}}}}),
                encoding="utf-8",
            )
            explicit_path = root / "explicit-opencode.json"
            explicit_path.write_text(
                json.dumps({"mcp": {"agent-runway": {"environment": {"ILH_OPENCODE_BRIDGE": "0"}}}}),
                encoding="utf-8",
            )
            script = textwrap.dedent(
                f"""
                import {{ pathToFileURL }} from "node:url";
                const pluginUrl = pathToFileURL({json.dumps(str(REPO_ROOT / '.opencode' / 'plugins' / 'agent-runway.js'))}).href;
                const {{ default: plugin }} = await import(pluginUrl);
                const server = await plugin.server();
                try {{
                  await server["tool.execute.before"](
                    {{sessionID: "node-test", tool: "bash", args: {{command: "git push origin main"}}}},
                    {{args: {{}}}}
                  );
                  console.log(JSON.stringify({{threw: false}}));
                }} catch (error) {{
                  console.log(JSON.stringify({{threw: true, message: String(error.message || error)}}));
                }}
                """
            )
            env = os.environ.copy()
            env["ILH_PYTHON"] = sys.executable
            env.pop("ILH_OPENCODE_BRIDGE", None)
            env.pop("OPENCODE_CONFIG_CONTENT", None)
            env.pop("OPENCODE_CONFIG_PATH", None)
            env["HOME"] = str(home_dir)
            env["USERPROFILE"] = str(home_dir)
            env["OPENCODE_CONFIG_PATH"] = str(explicit_path)
            proc = subprocess.run(
                [node, "--input-type=module", "-e", script],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=30,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn('{"threw":false}', proc.stdout.replace(" ", ""))

    def test_opencode_before_hook_runtime_fails_closed_when_bridge_returns_no_output(self) -> None:
        payload = self.run_opencode_before_hook_with_stubbed_bridge(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "sys.exit(0)\n"
        )
        self.assertTrue(payload["threw"], payload)
        self.assertIn("no decision", payload["message"].lower())

    def test_opencode_before_hook_runtime_fails_closed_when_bridge_returns_invalid_json(self) -> None:
        payload = self.run_opencode_before_hook_with_stubbed_bridge(
            "#!/usr/bin/env python3\n"
            "print('not-json')\n"
        )
        self.assertTrue(payload["threw"], payload)

    def test_opencode_before_hook_runtime_fails_closed_when_bridge_returns_invalid_shape(self) -> None:
        payload = self.run_opencode_before_hook_with_stubbed_bridge(
            "#!/usr/bin/env python3\n"
            "print('[]')\n"
        )
        self.assertTrue(payload["threw"], payload)
        self.assertIn("invalid decision", payload["message"].lower())

    def test_opencode_before_hook_runtime_fails_closed_when_bridge_returns_unknown_decision(self) -> None:
        payload = self.run_opencode_before_hook_with_stubbed_bridge(
            "#!/usr/bin/env python3\n"
            "print('{\"decision\": \"maybe\", \"reason\": \"ambiguous\"}')\n"
        )
        self.assertTrue(payload["threw"], payload)

    def test_configure_script_marks_non_claude_hosts_as_instructions_only(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "codex", "--project-dir", str(REPO_ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["mode"], "instructions_only")
        self.assertEqual(payload["host"], "codex")
        self.assertEqual(payload["host_display_name"], "Codex")
        self.assertIn("not a host-native installer", payload["note"])
        self.assertNotIn("hooks", payload)

    def test_configure_script_marks_vscode_and_cursor_as_instructions_only(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        for host, display_name in (("vscode", "VSCode"), ("cursor", "Cursor")):
            with self.subTest(host=host):
                proc = subprocess.run(
                    [sys.executable, str(script), "--host", host, "--project-dir", str(REPO_ROOT)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
                self.assertEqual(proc.returncode, 0)
                payload = json.loads(proc.stdout)
                self.assertEqual(payload["mode"], "instructions_only")
                self.assertEqual(payload["host"], host)
                self.assertEqual(payload["host_display_name"], display_name)
                self.assertIn("env", payload)
                self.assertNotIn("hooks", payload)

    def test_configure_script_emits_claude_code_hosted_settings(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "claude-code", "--project-dir", str(REPO_ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("mode", ""), "")
        self.assertIn("hooks", payload)
        self.assertIn("Stop", payload["hooks"])
        self.assertIn("SessionStart", payload["hooks"])
        self.assertIn("PreToolUse", payload["hooks"])
        self.assertIn("PostToolUse", payload["hooks"])
        self.assertIn("permissions", payload)
        self.assertIn("env", payload)
        self.assertEqual(
            payload["env"]["ILH_DB_PATH"],
            str(REPO_ROOT / ".agent-runway" / "state.db"),
        )
        self.assertTrue(payload["env"]["ILH_SECRET_PATH"].endswith("secret.key"))
        stop_command = payload["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn("python", stop_command)
        self.assertIn("claude_hooks.py", stop_command)
        self.assertTrue(stop_command.endswith(" stop"))
        self.assertIn(
            f"Read({payload['env']['ILH_SECRET_PATH']})",
            payload["permissions"]["deny"],
        )

    def test_configure_script_claude_permissions_cover_all_hook_risky_bash_patterns(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        hooks = load_script_module("claude_hooks")
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "claude-code", "--project-dir", str(REPO_ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        expected = {
            f"Bash({' '.join(pattern.split())}:*)"
            for pattern in hooks.DANGEROUS_BASH_PATTERNS
        }
        self.assertEqual(set(payload["permissions"]["ask"]), expected)

    def test_configure_script_quotes_hook_paths_for_windows_shells(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        project_dir = "C:\\Users\\Example User\\Agent-Runway"
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "claude-code", "--project-dir", project_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        stop_command = payload["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn('"C:\\Users\\Example User\\Agent-Runway\\scripts\\claude_hooks.py"', stop_command)
        self.assertNotIn("'C:\\Users\\Example User", stop_command)

    def test_configure_script_emits_native_opencode_config(self) -> None:
        script = REPO_ROOT / "scripts" / "generate_host_config.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--host", "opencode", "--project-dir", str(REPO_ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["mode"], "host_native_config")
        self.assertEqual(payload["host"], "opencode")
        self.assertEqual(payload["host_display_name"], "OpenCode")
        self.assertIn("$schema", payload)
        self.assertIn("mcp", payload)
        self.assertIn("agent-runway", payload["mcp"])
        server = payload["mcp"]["agent-runway"]
        self.assertEqual(server["type"], "local")
        self.assertIsInstance(server["command"], list)
        self.assertEqual(server["command"][0], "python")
        self.assertIn("environment", server)
        self.assertIn("ILH_DB_PATH", server["environment"])
        self.assertIn("ILH_SECRET_PATH", server["environment"])
        self.assertEqual(server["environment"]["ILH_OPENCODE_BRIDGE"], "0")
        self.assertEqual(server["command"][1], str(REPO_ROOT / "mcp" / "server.py"))
        self.assertEqual(server["environment"]["ILH_DB_PATH"], str(REPO_ROOT / ".agent-runway" / "state.db"))
        self.assertIn("falls back to OpenCode config content or config files", payload["note"])
        self.assertIn("shim or symlink", payload["note"])
        self.assertIn("permission", payload)
        self.assertIn("bash", payload["permission"])
        self.assertIn("read", payload["permission"])
        self.assertIn("edit", payload["permission"])
        self.assertIn("task", payload["permission"])
        self.assertIn("doom_loop", payload["permission"])
        self.assertEqual(payload["permission"]["bash"]["*"], "ask")
        self.assertEqual(payload["permission"]["task"]["*"], "ask")
        self.assertEqual(payload["permission"]["doom_loop"], "ask")
        self.assertEqual(payload["permission"]["read"]["*"], "allow")
        self.assertEqual(
            payload["permission"]["read"][payload["mcp"]["agent-runway"]["environment"]["ILH_SECRET_PATH"]],
            "deny",
        )
        self.assertNotIn("plugin", payload)
        self.assertNotIn("hooks", payload)

    def test_configure_script_supported_hosts_come_from_adapter_registry(self) -> None:
        script_text = (REPO_ROOT / "scripts" / "generate_host_config.py").read_text(encoding="utf-8")
        self.assertIn("SUPPORTED_HOST_KEYS", script_text)
        self.assertNotIn('SUPPORTED_HOSTS = ("claude-code", "codex", "opencode", "vscode", "cursor")', script_text)

    def test_package_skill_check_reports_when_official_packager_is_unavailable(self) -> None:
        script = REPO_ROOT / "scripts" / "package_skill_check.py"
        env = os.environ.copy()
        env["SKILL_CREATOR_PACKAGE_SCRIPT"] = str(REPO_ROOT / "scripts" / "missing-package-skill.py")
        proc = subprocess.run(
            [sys.executable, str(script), str(REPO_ROOT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            env=env,
            timeout=180,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertIsNone(payload["official_package_script"])
        self.assertFalse(payload["official_package_skill"]["available"])
        self.assertFalse(payload["official_package_validated"])
        self.assertTrue(payload["passed"])

    def test_check_gitea_release_detects_non_release_files_in_remote_tree(self) -> None:
        script = REPO_ROOT / "scripts" / "check_gitea_release.py"
        spec = importlib.util.spec_from_file_location("check_gitea_release", script)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        scripts_root = str(REPO_ROOT / "scripts")
        sys.path.insert(0, scripts_root)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "SKILL.md").write_text("skill\n", encoding="utf-8")
            (root / "README.md").write_text("readme\n", encoding="utf-8")
            (root / "mcp").mkdir(parents=True)
            (root / "mcp" / "server.py").write_text("print('ok')\n", encoding="utf-8")
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("internal notes\n", encoding="utf-8")

            non_release = module.find_non_release_files(root)

        self.assertEqual(non_release, [Path(".github/workflows/ci.yml"), Path("AGENTS.md")])
        sys.path.remove(scripts_root)


if __name__ == "__main__":
    unittest.main()
