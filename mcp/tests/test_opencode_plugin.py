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
    def test_plugin_passes_configured_agent_runway_environment_to_bridge(self) -> None:
        require_node(self)
        with tempfile.TemporaryDirectory(prefix="agent-runway-opencode-plugin-") as raw:
            tmp = Path(raw)
            project_dir = tmp / "project"
            project_dir.mkdir()
            configured_db = tmp / "configured-state.db"
            secret_path = tmp / "secret.key"
            secret_path.write_text("secret", encoding="utf-8")
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
            secret_path.write_text("secret", encoding="utf-8")
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

if __name__ == "__main__":
    unittest.main()
