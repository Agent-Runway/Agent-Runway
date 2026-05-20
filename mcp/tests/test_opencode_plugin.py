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
PLUGIN_PATH = REPO_ROOT / ".opencode" / "plugins" / "agent-runway.js"
VALID_SECRET = "a" * 64


def require_node(testcase: unittest.TestCase) -> None:
    if shutil.which("node") is None:
        testcase.skipTest("node is required to execute the OpenCode plugin")


def agent_runway_config(db_path: Path, secret_path: Path | None = None) -> dict:
    environment = {
        "ILH_DB_PATH": str(db_path),
        "ILH_OPENCODE_BRIDGE": "1",
    }
    if secret_path is not None:
        environment["ILH_SECRET_PATH"] = str(secret_path)
    return {"mcp": {"agent-runway": {"environment": environment}}}


def clean_env(*keys: str) -> dict[str, str]:
    env = os.environ.copy()
    for key in keys:
        env.pop(key, None)
    return env


def run_process(
    args: list[str], cwd: Path, env: dict[str, str], stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )


def write_node_script(path: Path, source: str) -> None:
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def write_plugin_session_runner(path: Path) -> None:
    write_node_script(
        path,
        """
        import { existsSync } from "node:fs";
        import { join } from "node:path";
        import { pathToFileURL } from "node:url";

        const pluginUrl = `${pathToFileURL(process.env.AGENT_RUNWAY_OPENCODE_PLUGIN).href}?t=${Date.now()}`;
        const plugin = (await import(pluginUrl)).default;
        const server = await plugin.server();
        await server.event({ event: { type: "session.created", sessionID: "opencode-env-test", info: { cwd: process.env.PROJECT_CWD } } });
        console.log(JSON.stringify({
          configuredStateExists: existsSync(process.env.CONFIGURED_DB_PATH),
          defaultStateExists: existsSync(join(process.env.PROJECT_CWD, ".agent-runway", "state.db")),
        }));
        """,
    )


def write_bytecode_capture_runtime(root: Path) -> tuple[Path, Path]:
    plugin_dir = root / ".opencode" / "plugins"
    script_dir = root / "scripts"
    plugin_dir.mkdir(parents=True)
    script_dir.mkdir()
    shutil.copyfile(PLUGIN_PATH, plugin_dir / "agent-runway.js")
    (script_dir / "bridge_helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (script_dir / "opencode_plugin_bridge.py").write_text(
        textwrap.dedent(
            """
            import json
            import os
            import sys
            import bridge_helper

            Path = __import__("pathlib").Path
            Path(os.environ["BRIDGE_ENV_CAPTURE"]).write_text(
                json.dumps({
                    "ILH_DB_PATH": os.environ.get("ILH_DB_PATH"),
                    "PYTHONDONTWRITEBYTECODE": os.environ.get("PYTHONDONTWRITEBYTECODE"),
                    "helper": bridge_helper.VALUE,
                }),
                encoding="utf-8",
            )
            sys.stdout.write(json.dumps({"recorded": True}))
            """
        ),
        encoding="utf-8",
    )
    return plugin_dir, script_dir


def write_bytecode_runner(path: Path) -> None:
    write_node_script(
        path,
        """
        import { pathToFileURL } from "node:url";

        const pluginUrl = `${pathToFileURL(process.env.AGENT_RUNWAY_OPENCODE_PLUGIN).href}?t=${Date.now()}`;
        const plugin = (await import(pluginUrl)).default;
        const server = await plugin.server();
        await server.event({ event: { type: "session.created", sessionID: "bytecode-test", info: { cwd: process.cwd() } } });
        """,
    )


def write_after_payload_capture_bridge(path: Path, capture: Path) -> None:
    path.write_text(
        textwrap.dedent(
            f"""
            import json
            import sys

            event_name = sys.argv[1]
            payload = json.loads(sys.stdin.read() or "{{}}")
            if event_name == "pre-tool-use":
                sys.stdout.write(json.dumps({{"decision": "allow"}}))
            else:
                with open({str(capture)!r}, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                sys.stdout.write(json.dumps({{"recorded": True}}))
            """
        ),
        encoding="utf-8",
    )


def write_after_payload_runner(path: Path) -> None:
    write_node_script(
        path,
        """
        import { pathToFileURL } from "node:url";

        const pluginUrl = `${pathToFileURL(process.env.AGENT_RUNWAY_OPENCODE_PLUGIN).href}?t=${Date.now()}`;
        const plugin = (await import(pluginUrl)).default;
        const server = await plugin.server();
        await server["tool.execute.after"](
          { sessionID: "exit-forward", cwd: process.env.PROJECT_CWD, tool: "bash", args: { command: "pytest -q" } },
          { output: "failed", stderr: "err", exit: 3, exitCode: "4", exit_code: "5", metadata: { exitCode: 6 } }
        );
        console.log(JSON.stringify({ ok: true }));
        """,
    )


def run_opencode_before_hook(
    testcase: unittest.TestCase, command: str, secret_path: Path, bridge_enabled: bool = True
) -> dict:
    require_node(testcase)
    script = textwrap.dedent(
        f"""
        import {{ pathToFileURL }} from "node:url";
        const pluginUrl = pathToFileURL({json.dumps(str(PLUGIN_PATH))}).href;
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
    proc = run_process(["node", "--input-type=module", "-e", script], REPO_ROOT, env)
    testcase.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
    return last_json_line(proc.stdout)


def run_opencode_before_hook_with_stubbed_bridge(testcase: unittest.TestCase, stdout_text: str) -> dict:
    require_node(testcase)
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
        fs.copyFileSync({json.dumps(str(PLUGIN_PATH))}, path.join(pluginDir, "agent-runway.js"));
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
    proc = run_process(["node", "--input-type=module", "-e", script], REPO_ROOT, env)
    testcase.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
    return last_json_line(proc.stdout)


def run_opencode_before_hook_with_config_content(testcase: unittest.TestCase, config: dict) -> dict:
    require_node(testcase)
    script = textwrap.dedent(
        f"""
        import {{ pathToFileURL }} from "node:url";
        const pluginUrl = pathToFileURL({json.dumps(str(PLUGIN_PATH))}).href;
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
    proc = run_process(["node", "--input-type=module", "-e", script], REPO_ROOT, env)
    testcase.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
    return last_json_line(proc.stdout)


def last_json_line(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"unexpected node output: {stdout!r}")


def copy_bridge_runtime(repo: Path) -> tuple[Path, Path]:
    scripts_dir = repo / "scripts"
    mcp_dir = repo / "mcp"
    scripts_dir.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "scripts" / "opencode_plugin_bridge.py", scripts_dir / "opencode_plugin_bridge.py")
    shutil.copyfile(REPO_ROOT / "scripts" / "claude_hooks.py", scripts_dir / "claude_hooks.py")
    shutil.copytree(
        REPO_ROOT / "mcp" / "agent_runway_runtime",
        mcp_dir / "agent_runway_runtime",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return scripts_dir, mcp_dir


class OpenCodePluginTests(unittest.TestCase):
    def test_plugin_source_forwards_input_args_and_fails_closed_on_ask(self) -> None:
        plugin_text = PLUGIN_PATH.read_text(encoding="utf-8")
        self.assertIn("ILH_OPENCODE_BRIDGE", plugin_text)
        self.assertIn("tool_input: input.args || {}", plugin_text)
        self.assertNotIn("tool_input: output.args || {}", plugin_text)
        self.assertIn("proc.error", plugin_text)
        self.assertIn("stderr: output.stderr", plugin_text)
        self.assertIn("exitCode: output.exitCode", plugin_text)
        self.assertIn("exit_code: output.exit_code", plugin_text)
        self.assertIn("bridge returned no decision", plugin_text)
        self.assertIn("bridge returned invalid decision", plugin_text)
        self.assertIn("Array.isArray(result)", plugin_text)
        self.assertIn('result.decision === "ask"', plugin_text)
        self.assertIn("host confirmation", plugin_text)

    def test_plugin_passes_configured_agent_runway_environment_to_bridge(self) -> None:
        require_node(self)
        with tempfile.TemporaryDirectory(prefix="agent-runway-opencode-plugin-") as raw:
            tmp = Path(raw)
            project_dir = tmp / "project"
            project_dir.mkdir()
            configured_db = tmp / "configured-state.db"
            secret_path = tmp / "secret.key"
            secret_path.write_text(VALID_SECRET, encoding="utf-8")
            script = tmp / "run-plugin.mjs"
            write_plugin_session_runner(script)
            env = clean_env("ILH_DB_PATH", "ILH_SECRET_PATH", "ILH_OPENCODE_BRIDGE")
            env.update({
                "AGENT_RUNWAY_OPENCODE_PLUGIN": str(PLUGIN_PATH),
                "CONFIGURED_DB_PATH": str(configured_db),
                "OPENCODE_CONFIG_CONTENT": json.dumps(agent_runway_config(configured_db, secret_path)),
                "PROJECT_CWD": str(project_dir),
                "PYTHONDONTWRITEBYTECODE": "1",
            })
            proc = run_process(["node", str(script)], project_dir, env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["configuredStateExists"])
            self.assertFalse(payload["defaultStateExists"])

    def test_plugin_disables_python_bytecode_for_bridge_process(self) -> None:
        require_node(self)
        with tempfile.TemporaryDirectory(prefix="agent-runway-opencode-bytecode-") as raw:
            tmp = Path(raw)
            plugin_dir, script_dir = write_bytecode_capture_runtime(tmp)
            capture = tmp / "bridge-env.json"
            runner = tmp / "run-plugin.mjs"
            write_bytecode_runner(runner)
            env = clean_env("ILH_DB_PATH", "ILH_SECRET_PATH", "ILH_OPENCODE_BRIDGE", "PYTHONDONTWRITEBYTECODE")
            env.update({
                "AGENT_RUNWAY_OPENCODE_PLUGIN": str(plugin_dir / "agent-runway.js"),
                "BRIDGE_ENV_CAPTURE": str(capture),
                "OPENCODE_CONFIG_CONTENT": json.dumps(agent_runway_config(tmp / "configured-state.db")),
            })
            proc = run_process(["node", str(runner)], tmp, env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(payload["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertFalse((script_dir / "__pycache__").exists())

    def test_plugin_after_hook_forwards_output_exit_aliases_to_bridge(self) -> None:
        require_node(self)
        with tempfile.TemporaryDirectory(prefix="agent-runway-opencode-exit-") as raw:
            tmp = Path(raw)
            project_dir = tmp / "project"
            project_dir.mkdir()
            plugin_dir = tmp / ".opencode" / "plugins"
            scripts_dir = tmp / "scripts"
            plugin_dir.mkdir(parents=True)
            scripts_dir.mkdir()
            shutil.copyfile(PLUGIN_PATH, plugin_dir / "agent-runway.js")
            capture = tmp / "post-payload.json"
            write_after_payload_capture_bridge(scripts_dir / "opencode_plugin_bridge.py", capture)
            runner = tmp / "run-plugin.mjs"
            write_after_payload_runner(runner)
            env = clean_env("ILH_OPENCODE_BRIDGE", "OPENCODE_CONFIG_CONTENT")
            env.update(
                {
                    "AGENT_RUNWAY_OPENCODE_PLUGIN": str(plugin_dir / "agent-runway.js"),
                    "ILH_OPENCODE_BRIDGE": "1",
                    "PROJECT_CWD": str(project_dir),
                }
            )

            proc = run_process(["node", str(runner)], project_dir, env)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('{"ok":true}', proc.stdout.replace(" ", ""))
            payload = json.loads(capture.read_text(encoding="utf-8"))
            tool_response = payload["tool_response"]
            self.assertEqual(tool_response["exit"], 3)
            self.assertEqual(tool_response["exitCode"], "4")
            self.assertEqual(tool_response["exit_code"], "5")
            self.assertEqual(tool_response["metadata"]["exitCode"], 6)

    def test_plugin_forces_python_bytecode_env_even_when_process_disables_it(self) -> None:
        require_node(self)
        with tempfile.TemporaryDirectory(prefix="agent-runway-opencode-bytecode-override-") as raw:
            tmp = Path(raw)
            plugin_dir, _script_dir = write_bytecode_capture_runtime(tmp)
            capture = tmp / "bridge-env.json"
            runner = tmp / "run-plugin.mjs"
            write_bytecode_runner(runner)
            env = clean_env("ILH_DB_PATH", "ILH_SECRET_PATH", "ILH_OPENCODE_BRIDGE")
            env.update({
                "AGENT_RUNWAY_OPENCODE_PLUGIN": str(plugin_dir / "agent-runway.js"),
                "BRIDGE_ENV_CAPTURE": str(capture),
                "OPENCODE_CONFIG_CONTENT": json.dumps(agent_runway_config(tmp / "configured-state.db")),
                "PYTHONDONTWRITEBYTECODE": "0",
            })
            proc = run_process(["node", str(runner)], tmp, env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(payload["PYTHONDONTWRITEBYTECODE"], "1")

    def test_python_bridge_forces_bytecode_env_on_import(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-runway-bridge-bytecode-override-") as raw:
            tmp = Path(raw)
            scripts_dir, _mcp_dir = copy_bridge_runtime(tmp / "repo")
            project_dir = tmp / "project"
            project_dir.mkdir()
            env = clean_env("ILH_DB_PATH", "ILH_SECRET_PATH", "OPENCODE_CONFIG_CONTENT")
            env["PYTHONDONTWRITEBYTECODE"] = "0"
            code = (
                "import os, sys; "
                f"sys.path.insert(0, {str(scripts_dir)!r}); "
                "import opencode_plugin_bridge; "
                "print(os.environ.get('PYTHONDONTWRITEBYTECODE'))"
            )
            proc = run_process([sys.executable, "-c", code], project_dir, env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "1")

    def test_python_bridge_loads_config_environment_before_hooks_import(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-runway-bridge-env-") as raw:
            tmp = Path(raw)
            scripts_dir, mcp_dir = copy_bridge_runtime(tmp / "repo")
            project_dir = tmp / "project"
            config_dir = project_dir / ".opencode"
            config_dir.mkdir(parents=True)
            configured_db = tmp / "configured-state.db"
            secret_path = tmp / "secret.key"
            secret_path.write_text(VALID_SECRET, encoding="utf-8")
            config = agent_runway_config(configured_db, secret_path)
            (config_dir / "opencode.json").write_text(json.dumps(config), encoding="utf-8")
            env = clean_env("ILH_DB_PATH", "ILH_SECRET_PATH", "PYTHONDONTWRITEBYTECODE")
            payload = {"session_id": "bridge-env-test", "host": "OpenCode", "cwd": str(project_dir)}
            proc = run_process(
                [sys.executable, str(scripts_dir / "opencode_plugin_bridge.py"), "session-created"],
                project_dir,
                env,
                json.dumps(payload),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(configured_db.exists())
            self.assertFalse((project_dir / ".agent-runway" / "state.db").exists())
            self.assertFalse((scripts_dir / "__pycache__").exists())
        self.assertFalse((mcp_dir / "agent_runway_runtime" / "__pycache__").exists())

    def test_python_bridge_without_config_db_defaults_to_event_project_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-runway-bridge-project-state-") as raw:
            tmp = Path(raw)
            scripts_dir, _mcp_dir = copy_bridge_runtime(tmp / "repo")
            project_dir = tmp / "project"
            project_dir.mkdir()
            secret_path = tmp / "secret.key"
            secret_path.write_text(VALID_SECRET, encoding="utf-8")
            env = clean_env("ILH_DB_PATH", "OPENCODE_CONFIG_CONTENT", "OPENCODE_CONFIG_PATH")
            env["ILH_SECRET_PATH"] = str(secret_path)
            env["ILH_OPENCODE_BRIDGE"] = "1"
            sandbox_home = tmp / "home"
            sandbox_home.mkdir()
            env["HOME"] = str(sandbox_home)
            env["USERPROFILE"] = str(sandbox_home)
            payload = {"session_id": "bridge-project-state", "host": "OpenCode", "cwd": str(project_dir)}

            proc = run_process(
                [sys.executable, str(scripts_dir / "opencode_plugin_bridge.py"), "session-created"],
                project_dir,
                env,
                json.dumps(payload),
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((project_dir / ".agent-runway" / "state.db").exists())
            self.assertFalse((tmp / "repo" / ".agent-runway" / "state.db").exists())

    def test_python_bridge_without_config_db_denies_event_project_state_reads(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-runway-bridge-project-guard-") as raw:
            tmp = Path(raw)
            scripts_dir, _mcp_dir = copy_bridge_runtime(tmp / "repo")
            project_dir = tmp / "project"
            project_dir.mkdir()
            project_db = project_dir / ".agent-runway" / "state.db"
            secret_path = tmp / "secret.key"
            secret_path.write_text(VALID_SECRET, encoding="utf-8")
            env = clean_env("ILH_DB_PATH", "OPENCODE_CONFIG_CONTENT", "OPENCODE_CONFIG_PATH")
            env["ILH_SECRET_PATH"] = str(secret_path)
            env["ILH_OPENCODE_BRIDGE"] = "1"
            sandbox_home = tmp / "home"
            sandbox_home.mkdir()
            env["HOME"] = str(sandbox_home)
            env["USERPROFILE"] = str(sandbox_home)
            payload = {
                "session_id": "bridge-project-state-guard",
                "host": "OpenCode",
                "cwd": str(project_dir),
                "tool_name": "read",
                "tool_input": {"filePath": str(project_db)},
            }

            proc = run_process(
                [sys.executable, str(scripts_dir / "opencode_plugin_bridge.py"), "pre-tool-use"],
                project_dir,
                env,
                json.dumps(payload),
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            response = json.loads(proc.stdout)
            self.assertEqual("deny", response["decision"])

    def test_plugin_and_bridge_load_trailing_comma_opencode_config(self) -> None:
        require_node(self)
        with tempfile.TemporaryDirectory(prefix="agent-runway-opencode-jsonc-") as raw:
            tmp = Path(raw)
            runtime_root = tmp / "runtime"
            project_dir = runtime_root / "project"
            config_dir = project_dir / ".opencode"
            config_dir.mkdir(parents=True)
            scripts_dir, mcp_dir = copy_bridge_runtime(runtime_root)
            plugin_dir = runtime_root / ".opencode" / "plugins"
            plugin_dir.mkdir(parents=True)
            shutil.copyfile(PLUGIN_PATH, plugin_dir / "agent-runway.js")
            configured_db = tmp / "configured-state.db"
            config_dir.joinpath("opencode.json").write_text(
                '{\n  "mcp": {\n    "agent-runway": {\n      "environment": {\n        "ILH_DB_PATH": ' + json.dumps(str(configured_db)) + ',\n        "ILH_OPENCODE_BRIDGE": "1",\n      },\n    },\n  },\n}\n',
                encoding="utf-8",
            )
            runner = tmp / "run-plugin.mjs"
            write_plugin_session_runner(runner)
            env = clean_env("ILH_DB_PATH", "ILH_SECRET_PATH", "ILH_OPENCODE_BRIDGE", "OPENCODE_CONFIG_CONTENT")
            env.update({
                "AGENT_RUNWAY_OPENCODE_PLUGIN": str(plugin_dir / "agent-runway.js"),
                "CONFIGURED_DB_PATH": str(configured_db),
                "PROJECT_CWD": str(project_dir),
                "PYTHONPATH": str(scripts_dir),
            })
            proc = run_process(["node", str(runner)], project_dir, env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["configuredStateExists"])
            self.assertFalse(payload["defaultStateExists"])
        self.assertFalse((mcp_dir / "agent_runway_runtime" / "__pycache__").exists())

    def test_plugin_filters_empty_bridge_environment_keys(self) -> None:
        require_node(self)
        with tempfile.TemporaryDirectory(prefix="agent-runway-opencode-empty-env-") as raw:
            tmp = Path(raw)
            plugin_dir = tmp / ".opencode" / "plugins"
            scripts_dir = tmp / "scripts"
            plugin_dir.mkdir(parents=True)
            scripts_dir.mkdir()
            shutil.copyfile(PLUGIN_PATH, plugin_dir / "agent-runway.js")
            capture = tmp / "bridge-env.json"
            (scripts_dir / "opencode_plugin_bridge.py").write_text(
                textwrap.dedent(
                    """
                    import json
                    import os
                    import sys

                    Path = __import__("pathlib").Path
                    Path(os.environ["BRIDGE_ENV_CAPTURE"]).write_text(
                        json.dumps({
                            "has_empty_key": "" in os.environ,
                            "ILH_DB_PATH": os.environ.get("ILH_DB_PATH"),
                        }),
                        encoding="utf-8",
                    )
                    sys.stdout.write(json.dumps({"recorded": True}))
                    """
                ),
                encoding="utf-8",
            )
            runner = tmp / "run-plugin.mjs"
            write_bytecode_runner(runner)
            env = clean_env("ILH_DB_PATH", "ILH_SECRET_PATH", "ILH_OPENCODE_BRIDGE")
            env.update({
                "AGENT_RUNWAY_OPENCODE_PLUGIN": str(plugin_dir / "agent-runway.js"),
                "BRIDGE_ENV_CAPTURE": str(capture),
                "OPENCODE_CONFIG_CONTENT": json.dumps(
                    {"mcp": {"agent-runway": {"environment": {"ILH_DB_PATH": str(tmp / "state.db"), "": "bad", "ILH_OPENCODE_BRIDGE": "1"}}}}
                ),
            })

            proc = run_process(["node", str(runner)], tmp, env)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(capture.read_text(encoding="utf-8"))
            self.assertFalse(payload["has_empty_key"])
            self.assertEqual(str(tmp / "state.db"), payload["ILH_DB_PATH"])

    def test_before_hook_is_disabled_without_env_or_config_fallback(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            secret_path = Path(td) / "secret.key"
            secret_path.write_text(VALID_SECRET + "\n", encoding="utf-8")
            payload = run_opencode_before_hook(self, "git push origin main", secret_path, bridge_enabled=False)
        self.assertFalse(payload["threw"], payload)

    def test_after_hook_is_disabled_by_default(self) -> None:
        require_node(self)
        script = textwrap.dedent(
            f"""
            import {{ pathToFileURL }} from "node:url";
            const pluginUrl = pathToFileURL({json.dumps(str(PLUGIN_PATH))}).href;
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
        proc = run_process(["node", "--input-type=module", "-e", script], REPO_ROOT, env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('{"ok":true}', proc.stdout.replace(" ", ""))

    def test_before_hook_runtime_uses_input_args_not_output_args(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            secret_path = Path(td) / "secret.key"
            secret_path.write_text(VALID_SECRET + "\n", encoding="utf-8")
            payload = run_opencode_before_hook(self, f"cat {secret_path}", secret_path)
        self.assertTrue(payload["threw"], payload)
        self.assertRegex(payload["message"].lower(), "secret|bridge unavailable")

    def test_before_hook_runtime_fails_closed_on_ask(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            secret_path = Path(td) / "secret.key"
            secret_path.write_text(VALID_SECRET + "\n", encoding="utf-8")
            payload = run_opencode_before_hook(self, "git push origin main", secret_path)
        self.assertTrue(payload["threw"], payload)
        self.assertRegex(payload["message"].lower(), "host confirmation|bridge unavailable")

    def test_before_hook_can_enable_bridge_via_opencode_config_content(self) -> None:
        payload = run_opencode_before_hook_with_config_content(
            self,
            {"mcp": {"agent-runway": {"environment": {"ILH_OPENCODE_BRIDGE": "1"}}}},
        )
        self.assertTrue(payload["threw"], payload)
        self.assertIn("host confirmation", payload["message"].lower())

    def test_before_hook_runtime_fails_closed_when_bridge_returns_no_output(self) -> None:
        payload = run_opencode_before_hook_with_stubbed_bridge(
            self,
            "#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n",
        )
        self.assertTrue(payload["threw"], payload)
        self.assertIn("no decision", payload["message"].lower())

    def test_before_hook_runtime_fails_closed_when_bridge_returns_invalid_json(self) -> None:
        payload = run_opencode_before_hook_with_stubbed_bridge(self, "#!/usr/bin/env python3\nprint('not-json')\n")
        self.assertTrue(payload["threw"], payload)

    def test_before_hook_runtime_fails_closed_when_bridge_returns_invalid_shape(self) -> None:
        payload = run_opencode_before_hook_with_stubbed_bridge(self, "#!/usr/bin/env python3\nprint('[]')\n")
        self.assertTrue(payload["threw"], payload)
        self.assertIn("invalid decision", payload["message"].lower())

    def test_before_hook_runtime_fails_closed_when_bridge_returns_unknown_decision(self) -> None:
        payload = run_opencode_before_hook_with_stubbed_bridge(
            self,
            '#!/usr/bin/env python3\nprint(\'{"decision": "maybe", "reason": "ambiguous"}\')\n',
        )
        self.assertTrue(payload["threw"], payload)

if __name__ == "__main__":
    unittest.main()
