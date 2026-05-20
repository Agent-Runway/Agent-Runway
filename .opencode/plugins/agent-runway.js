import { spawnSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const HERE = dirname(fileURLToPath(import.meta.url))
const BRIDGE_PATH = resolve(HERE, "../../scripts/opencode_plugin_bridge.py")
const PYTHON = process.env.ILH_PYTHON || (process.platform === "win32" ? "python" : "python3")

function readBridgeFlagFromObject(config) {
  const value = config?.mcp?.["agent-runway"]?.environment?.ILH_OPENCODE_BRIDGE
  if (value === "1" || value === 1 || value === true) {
    return true
  }
  if (value === "0" || value === 0 || value === false) {
    return false
  }
  return null
}

function readBridgeEnvironmentFromObject(config) {
  const environment = config?.mcp?.["agent-runway"]?.environment
  if (!environment || Array.isArray(environment) || typeof environment !== "object") {
    return null
  }
  return Object.fromEntries(
    Object.entries(environment)
      .filter((entry) => entry[1] !== undefined && entry[1] !== null)
      .map((entry) => [entry[0], String(entry[1])]),
  )
}

function readBridgeFlagFromConfigContent() {
  const content = process.env.OPENCODE_CONFIG_CONTENT
  if (!content) {
    return null
  }
  try {
    return readBridgeFlagFromObject(JSON.parse(content))
  } catch {
    return null
  }
}

function readBridgeEnvironmentFromConfigContent() {
  const content = process.env.OPENCODE_CONFIG_CONTENT
  if (!content) {
    return null
  }
  try {
    return readBridgeEnvironmentFromObject(JSON.parse(content))
  } catch {
    return null
  }
}

function readBridgeFlagFromConfigFile() {
  for (const candidate of configCandidates()) {
    try {
      if (!existsSync(candidate)) {
        continue
      }
      const content = readFileSync(candidate, "utf8")
      const decision = readBridgeFlagFromObject(JSON.parse(content))
      if (decision !== null) {
        return decision
      }
    } catch {
      continue
    }
  }
  return null
}

function readBridgeEnvironmentFromConfigFile() {
  for (const candidate of configCandidates()) {
    try {
      if (!existsSync(candidate)) {
        continue
      }
      const content = readFileSync(candidate, "utf8")
      const environment = readBridgeEnvironmentFromObject(JSON.parse(content))
      if (environment !== null) {
        return environment
      }
    } catch {
      continue
    }
  }
  return null
}

function configCandidates() {
  const home = homedir()
  return [
    process.env.OPENCODE_CONFIG_PATH,
    resolve(process.cwd(), ".opencode/opencode.json"),
    resolve(process.cwd(), "opencode.json"),
    resolve(home, ".config/opencode/opencode.json"),
    resolve(home, ".config/opencode/config.json"),
  ].filter(Boolean)
}

function isBridgeEnabled() {
  if (process.env.ILH_OPENCODE_BRIDGE === "1") {
    return true
  }
  if (process.env.ILH_OPENCODE_BRIDGE === "0") {
    return false
  }
  const contentDecision = readBridgeFlagFromConfigContent()
  if (contentDecision !== null) {
    return contentDecision
  }
  const fileDecision = readBridgeFlagFromConfigFile()
  if (fileDecision !== null) {
    return fileDecision
  }
  return false
}

const BRIDGE_ENABLED = isBridgeEnabled()
const BRIDGE_ENVIRONMENT = readBridgeEnvironmentFromConfigContent() || readBridgeEnvironmentFromConfigFile() || {}
const PYTHON_BRIDGE_ENVIRONMENT = { PYTHONDONTWRITEBYTECODE: "1", ...BRIDGE_ENVIRONMENT, ...process.env }

function runBridge(eventName, payload) {
  if (!BRIDGE_ENABLED) {
    return null
  }
  const proc = spawnSync(PYTHON, [BRIDGE_PATH, eventName], {
    input: JSON.stringify(payload),
    encoding: "utf8",
    env: PYTHON_BRIDGE_ENVIRONMENT,
  })
  if (proc.error) {
    throw new Error(`bridge unavailable: ${String(proc.error.message || proc.error)}`)
  }
  if (proc.status !== 0) {
    const detail = (proc.stderr || proc.stdout || "bridge execution failed").trim()
    throw new Error(detail)
  }
  const text = (proc.stdout || "").trim()
  if (!text) {
    throw new Error("bridge returned no decision")
  }
  const result = JSON.parse(text)
  if (Array.isArray(result) || typeof result !== "object" || result === null) {
    throw new Error("bridge returned invalid decision")
  }
  return result
}

export default {
  id: "agent-runway",
  server: async () => {
    return {
      event: async ({ event }) => {
        if (event.type === "session.created") {
          runBridge("session-created", {
            session_id: event.sessionID || "unknown",
            cwd: event.info?.cwd || process.cwd(),
            host: "OpenCode",
          })
        }
      },
      "tool.execute.before": async (input, output) => {
        if (!BRIDGE_ENABLED) {
          return
        }
        const result = runBridge("pre-tool-use", {
          session_id: input.sessionID,
          tool_name: input.tool,
          tool_input: input.args || {},
        })
        if (result && result.decision === "deny") {
          throw new Error(result.reason || "tool use denied by agent-runway")
        }
        if (result && result.decision === "ask") {
          throw new Error(result.reason || "tool use requires host confirmation by agent-runway")
        }
        if (result && result.decision !== "allow") {
          throw new Error(result.reason || "bridge returned invalid decision")
        }
      },
      "tool.execute.after": async (input, output) => {
        if (!BRIDGE_ENABLED) {
          return
        }
        runBridge("post-tool-use", {
          session_id: input.sessionID,
          tool_name: input.tool,
          tool_input: input.args || {},
          tool_response: {
            output: output.output,
            stderr: output.stderr,
            metadata: output.metadata || {},
          },
          hook_event_name: "OpenCodeToolExecuteAfter",
        })
      },
    }
  },
}
