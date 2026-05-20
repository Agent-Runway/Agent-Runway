#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
FIXTURE_ROOT = REPO_ROOT / "scripts" / "fixtures"
PI_EXTENSION_PATH = FIXTURE_ROOT / "pi_block_extension.js"
OPENCODE_EXPERIMENT_PATH = FIXTURE_ROOT / "opencode_block_experiment.mjs"


def executable(command: str) -> str:
    resolved = shutil.which(command)
    return resolved or command


def resolved_cmd(cmd: list[str] | str) -> list[str] | str:
    if isinstance(cmd, str) or not cmd:
        return cmd
    return [executable(cmd[0]), *cmd[1:]]


def run(cmd: list[str] | str, cwd: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
    stdin = env.get("__STDIN__")
    proc_env = dict(env)
    proc_env.pop("__STDIN__", None)
    proc = subprocess.run(
        resolved_cmd(cmd),
        cwd=str(cwd),
        env=proc_env,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=isinstance(cmd, str),
        timeout=timeout,
        check=False,
    )
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def tail(text: str, limit: int = 1600) -> str:
    return text[-limit:]


def cli_version(command: str, args: list[str]) -> dict[str, Any]:
    path = shutil.which(command)
    if path is None:
        return {"available": False, "path": None, "version": None}
    proc = subprocess.run([path, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    return {"available": True, "path": path, "version": proc.stdout.strip()}


def result(name: str, passed: bool, details: dict[str, Any], files: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "details": details,
        "failure_locator": {"likely_files": files},
    }


def base_env(tmp: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["ILH_DB_PATH"] = str(tmp / "state.db")
    env["ILH_SECRET_PATH"] = str(tmp / "secret.key")
    env["ILH_PYTHON"] = PYTHON
    return env


def generated_settings(host: str, secret_path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [PYTHON, "scripts/generate_host_config.py", "--host", host, "--project-dir", str(REPO_ROOT), "--secret-path", str(secret_path)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout)
    return json.loads(proc.stdout)


def invoke_hook(command: str, payload: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    hook_env = env.copy()
    hook_env["__STDIN__"] = json.dumps(payload)
    return run(command, REPO_ROOT, hook_env, 30)


def prepare_active_mission(env: dict[str, str]) -> None:
    old_env = {key: os.environ.get(key) for key in ["ILH_DB_PATH", "ILH_SECRET_PATH"]}
    os.environ.update({"ILH_DB_PATH": env["ILH_DB_PATH"], "ILH_SECRET_PATH": env["ILH_SECRET_PATH"]})
    sys.path.insert(0, str(REPO_ROOT / "mcp"))
    server = importlib.import_module("server")
    server = importlib.reload(server)
    server.mission_lock("claude-experiment", "stop-check", "goal", ["criterion"])
    server.store.record_receipt(
        session_id="claude-experiment",
        task_id="stop-check",
        source="test",
        tool_name="Bash",
        command_text="pytest -q",
        exit_code=0,
        metadata={},
    )
    for key, value in old_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def experiment_claude(tmp: Path) -> dict[str, Any]:
    env = base_env(tmp)
    Path(env["ILH_SECRET_PATH"]).write_text("secret", encoding="utf-8")
    settings = generated_settings("claude-code", Path(env["ILH_SECRET_PATH"]))
    pre_cmd = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    stop_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
    pre = invoke_hook(pre_cmd, {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}, env)
    prepare_active_mission(env)
    stop = invoke_hook(stop_cmd, {"session_id": "claude-experiment", "cwd": str(REPO_ROOT)}, env)
    pre_payload = json.loads(pre["stdout"] or "{}")
    stop_payload = json.loads(stop["stdout"] or "{}")
    passed = pre_payload.get("hookSpecificOutput", {}).get("permissionDecision") == "ask" and stop_payload.get("continue") is False
    return result("claude_code_configured_hooks", passed, {"pre": pre_payload, "stop": stop_payload}, ["scripts/claude_hooks.py", "scripts/generate_host_config.py"])


def install_pi_dependency(ext_dir: Path) -> dict[str, Any]:
    (ext_dir / "package.json").write_text(json.dumps({"type": "module", "dependencies": {"@mariozechner/pi-ai": "0.73.1"}}), encoding="utf-8")
    return run(["npm", "install", "--silent"], ext_dir, os.environ.copy(), 180)


def experiment_pi(tmp: Path) -> dict[str, Any]:
    ext_dir = tmp / "pi-extension"
    ext_dir.mkdir()
    extension = ext_dir / "agent-runway-pi-block.js"
    shutil.copyfile(PI_EXTENSION_PATH, extension)
    install = install_pi_dependency(ext_dir)
    sentinel = tmp / "pi-sentinel.txt"
    log_file = tmp / "pi-extension.log"
    env = os.environ.copy() | {"PI_BLOCK_SENTINEL": str(sentinel), "PI_BLOCK_LOG": str(log_file), "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"}
    cmd = ["npx", "-y", "@mariozechner/pi-coding-agent@0.73.1", "--no-extensions", "-e", str(extension), "--no-skills", "--no-context-files", "--provider", "agent-runway-local", "--model", "blocker", "--tools", "bash", "-p", "Trigger the blocking experiment."]
    proc = run(cmd, tmp, env, 180)
    log_text = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    passed = install["returncode"] == 0 and "blocked:bash" in log_text and not sentinel.exists()
    details = {"install_returncode": install["returncode"], "run_returncode": proc["returncode"], "log": log_text, "stdout_tail": tail(proc["stdout"]), "stderr_tail": tail(proc["stderr"])}
    return result("pi_cli_extension_tool_call_block", passed, details, ["Pi extension tool_call handler", "Pi custom provider streamSimple"])


def experiment_opencode(tmp: Path) -> dict[str, Any]:
    env = base_env(tmp)
    Path(env["ILH_SECRET_PATH"]).write_text("secret", encoding="utf-8")
    settings = generated_settings("opencode", Path(env["ILH_SECRET_PATH"]))
    settings["mcp"]["agent-runway"]["environment"]["ILH_OPENCODE_BRIDGE"] = "1"
    node_script = tmp / "opencode-plugin-experiment.mjs"
    shutil.copyfile(OPENCODE_EXPERIMENT_PATH, node_script)
    node_env = env | {"OPENCODE_CONFIG_CONTENT": json.dumps(settings), "AGENT_RUNWAY_OPENCODE_PLUGIN": str(REPO_ROOT / ".opencode" / "plugins" / "agent-runway.js")}
    proc = run(["node", str(node_script)], REPO_ROOT, node_env, 30)
    payload = json.loads(proc["stdout"] or "{}")
    passed = proc["returncode"] == 0 and payload.get("blocked") is True and "secret" in payload.get("message", "").lower()
    return result("opencode_plugin_bridge_configured_block", passed, {"payload": payload, "stderr_tail": tail(proc["stderr"])}, [".opencode/plugins/agent-runway.js", "scripts/opencode_plugin_bridge.py", "scripts/claude_hooks.py"])


def main() -> int:
    cli = {
        "claude": cli_version("claude", ["--version"]),
        "opencode": cli_version("opencode", ["--version"]),
        "node": cli_version("node", ["--version"]),
        "npm": cli_version("npm", ["--version"]),
    }
    with tempfile.TemporaryDirectory(prefix="agent-runway-host-exp-") as raw:
        tmp = Path(raw)
        experiments = [experiment_claude(tmp), experiment_pi(tmp), experiment_opencode(tmp)]
    payload = {"cli": cli, "experiments": experiments, "passed": all(item["passed"] for item in experiments)}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
