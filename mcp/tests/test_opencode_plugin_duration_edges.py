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


def clean_env(*keys: str) -> dict[str, str]:
    env = os.environ.copy()
    for key in keys:
        env.pop(key, None)
    return env


def run_process(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )


def write_node_script(path: Path, source: str) -> None:
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def write_denied_then_after_runner(path: Path) -> None:
    write_node_script(
        path,
        """
        import { pathToFileURL } from "node:url";

        const pluginUrl = `${pathToFileURL(process.env.AGENT_RUNWAY_OPENCODE_PLUGIN).href}?t=${Date.now()}`;
        const plugin = (await import(pluginUrl)).default;
        const server = await plugin.server();
        const input = { sessionID: "duration-leak", tool: "bash", args: { command: "deny" } };
        try {
          await server["tool.execute.before"](input, {});
        } catch {}
        await server["tool.execute.after"](input, { output: "", stderr: "", metadata: {} });
        console.log(JSON.stringify({ captureExists: await import("node:fs").then(fs => fs.existsSync(process.env.CAPTURE_PATH)) }));
        """,
    )


class OpenCodePluginDurationEdgeTests(unittest.TestCase):
    def test_denied_pre_tool_does_not_leave_stale_duration_for_after_hook(self) -> None:
        require_node(self)
        with tempfile.TemporaryDirectory(prefix="agent-runway-opencode-duration-leak-") as raw:
            tmp = Path(raw)
            plugin_dir = tmp / ".opencode" / "plugins"
            scripts_dir = tmp / "scripts"
            plugin_dir.mkdir(parents=True)
            scripts_dir.mkdir()
            shutil.copyfile(PLUGIN_PATH, plugin_dir / "agent-runway.js")
            capture = tmp / "post-payload.json"
            write_fake_bridge(scripts_dir / "opencode_plugin_bridge.py", capture)
            runner = tmp / "run-denied-after.mjs"
            write_denied_then_after_runner(runner)
            env = clean_env("ILH_OPENCODE_BRIDGE", "OPENCODE_CONFIG_CONTENT")
            env.update(
                {
                    "AGENT_RUNWAY_OPENCODE_PLUGIN": str(plugin_dir / "agent-runway.js"),
                    "CAPTURE_PATH": str(capture),
                    "ILH_OPENCODE_BRIDGE": "1",
                }
            )

            proc = run_process(["node", str(runner)], tmp, env)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertFalse(payload["captureExists"])


def write_fake_bridge(path: Path, capture: Path) -> None:
    path.write_text(
        textwrap.dedent(
            f"""
            import json
            import sys

            event_name = sys.argv[1]
            payload = json.loads(sys.stdin.read() or "{{}}")
            if event_name == "pre-tool-use":
                sys.stdout.write(json.dumps({{"decision": "deny", "reason": "blocked"}}))
            else:
                with open({str(capture)!r}, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                sys.stdout.write(json.dumps({{"recorded": True}}))
            """
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
