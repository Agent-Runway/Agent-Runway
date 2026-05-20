import { spawnSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const HERE = dirname(fileURLToPath(import.meta.url))
const BRIDGE_PATH = resolve(HERE, "../../scripts/opencode_plugin_bridge.py")
const PYTHON = process.env.ILH_PYTHON || (process.platform === "win32" ? "python" : "python3")

function parseConfigText(text) {
  const output = []
  let inString = false
  let escaping = false
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    if (inString) {
      output.push(char)
      if (escaping) {
        escaping = false
      } else if (char === "\\") {
        escaping = true
      } else if (char === '"') {
        inString = false
      }
      continue
    }
    if (char === '"') {
      inString = true
      output.push(char)
      continue
    }
    if (char === "/" && text[index + 1] === "/") {
      index += 2
      while (index < text.length && text[index] !== "\n" && text[index] !== "\r") {
        index += 1
      }
      output.push(text[index] || "")
      continue
    }
    if (char === "/" && text[index + 1] === "*") {
      index += 2
      while (index + 1 < text.length && !(text[index] === "*" && text[index + 1] === "/")) {
        index += 1
      }
      if (index + 1 >= text.length) {
        throw new SyntaxError("unterminated block comment in OpenCode config")
      }
      index += 1
      continue
    }
    if (char === ",") {
      let lookahead = nextSignificantConfigChar(text, index + 1)
      if (text[lookahead] === "}" || text[lookahead] === "]") {
        continue
      }
    }
    output.push(char)
  }
  return JSON.parse(output.join(""))
}

function nextSignificantConfigChar(text, startIndex) {
  let index = startIndex
  while (index < text.length) {
    if (/\s/.test(text[index])) {
      index += 1
      continue
    }
    if (text[index] === "/" && text[index + 1] === "/") {
      index += 2
      while (index < text.length && text[index] !== "\n" && text[index] !== "\r") {
        index += 1
      }
      continue
    }
    if (text[index] === "/" && text[index + 1] === "*") {
      index += 2
      while (index + 1 < text.length && !(text[index] === "*" && text[index + 1] === "/")) {
        index += 1
      }
      if (index + 1 >= text.length) {
        throw new SyntaxError("unterminated block comment in OpenCode config")
      }
      index += 2
      continue
    }
    break
  }
  return index
}

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
      .filter((entry) => entry[0].trim() && entry[1] !== undefined && entry[1] !== null)
      .map((entry) => [entry[0], String(entry[1])]),
  )
}

function readFromConfigContent(reader) {
  const content = process.env.OPENCODE_CONFIG_CONTENT
  if (!content) {
    return null
  }
  try {
    return reader(parseConfigText(content))
  } catch {
    return null
  }
}

function readFromConfigFile(reader) {
  for (const candidate of configCandidates()) {
    try {
      if (!existsSync(candidate)) {
        continue
      }
      const content = readFileSync(candidate, "utf8")
      const value = reader(parseConfigText(content))
      if (value !== null) {
        return value
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
  const contentDecision = readFromConfigContent(readBridgeFlagFromObject)
  if (contentDecision !== null) {
    return contentDecision
  }
  const fileDecision = readFromConfigFile(readBridgeFlagFromObject)
  if (fileDecision !== null) {
    return fileDecision
  }
  return false
}

const BRIDGE_ENABLED = isBridgeEnabled()
const BRIDGE_ENVIRONMENT = readFromConfigContent(readBridgeEnvironmentFromObject) || readFromConfigFile(readBridgeEnvironmentFromObject) || {}
const PYTHON_BRIDGE_ENVIRONMENT = { ...BRIDGE_ENVIRONMENT, ...process.env, PYTHONDONTWRITEBYTECODE: "1" }
const TOOL_START_TIMES = new Map()
const DENIED_TOOL_RUNS = new Set()

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

function toolRunKey(input) {
  return JSON.stringify({
    session_id: input.sessionID || "",
    tool_name: input.tool || "",
    tool_input: input.args || {},
  })
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
        const key = toolRunKey(input)
        const startedAt = Date.now()
        const result = runBridge("pre-tool-use", {
          session_id: input.sessionID,
          cwd: input.cwd || process.cwd(),
          tool_name: input.tool,
          tool_input: input.args || {},
        })
        if (result && result.decision === "deny") {
          DENIED_TOOL_RUNS.add(key)
          throw new Error(result.reason || "tool use denied by agent-runway")
        }
        if (result && result.decision === "ask") {
          DENIED_TOOL_RUNS.add(key)
          throw new Error(result.reason || "tool use requires host confirmation by agent-runway")
        }
        if (result && result.decision !== "allow") {
          DENIED_TOOL_RUNS.add(key)
          throw new Error(result.reason || "bridge returned invalid decision")
        }
        DENIED_TOOL_RUNS.delete(key)
        TOOL_START_TIMES.set(key, startedAt)
      },
      "tool.execute.after": async (input, output) => {
        if (!BRIDGE_ENABLED) {
          return
        }
        const key = toolRunKey(input)
        if (DENIED_TOOL_RUNS.has(key)) {
          DENIED_TOOL_RUNS.delete(key)
          return
        }
        const startedAt = TOOL_START_TIMES.get(key)
        TOOL_START_TIMES.delete(key)
        runBridge("post-tool-use", {
          session_id: input.sessionID,
          cwd: input.cwd || process.cwd(),
          tool_name: input.tool,
          tool_input: input.args || {},
          tool_response: {
            output: output.output,
            stderr: output.stderr,
            metadata: output.metadata || {},
            durationMs: output.durationMs ?? output.elapsedMs ?? output.metadata?.durationMs ?? (startedAt === undefined ? undefined : Date.now() - startedAt),
          },
          hook_event_name: "OpenCodeToolExecuteAfter",
        })
      },
    }
  },
}
