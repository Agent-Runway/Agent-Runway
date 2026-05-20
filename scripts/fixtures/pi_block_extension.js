import { appendFileSync } from "node:fs";
import { createAssistantMessageEventStream } from "@mariozechner/pi-ai";

const sentinel = process.env.PI_BLOCK_SENTINEL;
const logFile = process.env.PI_BLOCK_LOG;
const marker = "AGENT_RUNWAY_PI_BLOCK_TEST";

function log(line) {
  if (logFile) appendFileSync(logFile, `${line}\n`, "utf8");
}

function usage() {
  return {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: 0,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  };
}

function baseMessage(model) {
  return {
    role: "assistant",
    content: [],
    api: model.api,
    provider: model.provider,
    model: model.id,
    usage: usage(),
    stopReason: "stop",
    timestamp: Date.now(),
  };
}

function pushText(stream, output, text) {
  const contentIndex = output.content.length;
  output.content.push({ type: "text", text });
  stream.push({ type: "text_start", contentIndex, partial: output });
  stream.push({ type: "text_delta", contentIndex, delta: text, partial: output });
  stream.push({ type: "text_end", contentIndex, content: text, partial: output });
}

function pushToolCall(stream, output) {
  const command = `node -e "require('fs').writeFileSync(process.env.PI_BLOCK_SENTINEL, '${marker}')"`;
  const contentIndex = output.content.length;
  const toolCall = { type: "toolCall", id: "agent-runway-pi-block", name: "bash", arguments: { command } };
  output.content.push(toolCall);
  output.stopReason = "toolUse";
  stream.push({ type: "toolcall_start", contentIndex, partial: output });
  stream.push({ type: "toolcall_delta", contentIndex, delta: JSON.stringify(toolCall.arguments), partial: output });
  stream.push({ type: "toolcall_end", contentIndex, toolCall, partial: output });
}

function streamBlockingModel(model, context) {
  const stream = createAssistantMessageEventStream();
  queueMicrotask(() => {
    const output = baseMessage(model);
    stream.push({ type: "start", partial: output });
    const contextText = JSON.stringify(context);
    if (contextText.includes("blocked by Agent Runway Pi experiment")) {
      pushText(stream, output, "blocked result observed");
    } else {
      pushToolCall(stream, output);
    }
    stream.push({ type: "done", reason: output.stopReason, message: output });
    stream.end();
  });
  return stream;
}

export default function (pi) {
  pi.registerProvider("agent-runway-local", {
    api: "agent-runway-local",
    baseUrl: "http://127.0.0.1/agent-runway-local",
    apiKey: "agent-runway-local-test-key",
    models: [{
      id: "blocker",
      name: "Agent Runway Blocking Experiment",
      api: "agent-runway-local",
      reasoning: false,
      input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 4096,
      maxTokens: 1024,
    }],
    streamSimple: streamBlockingModel,
  });

  pi.on("tool_call", (event) => {
    const command = String(event.input?.command || "");
    log(`tool_call:${event.toolName}:${command}`);
    if (event.toolName === "bash" && command.includes(marker)) {
      log("blocked:bash");
      return { block: true, reason: "blocked by Agent Runway Pi experiment" };
    }
  });
}
