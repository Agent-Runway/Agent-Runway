import { pathToFileURL } from "node:url";

const moduleUrl = `${pathToFileURL(process.env.AGENT_RUNWAY_OPENCODE_PLUGIN).href}?t=${Date.now()}`;
const plugin = (await import(moduleUrl)).default;
const server = await plugin.server();
let blocked = false;
let message = "";

try {
  await server["tool.execute.before"]({
    sessionID: "opencode-experiment",
    cwd: process.cwd(),
    tool: "read",
    args: { filePath: `${process.cwd()}/.agent-runway/state.db` },
  }, {});
} catch (error) {
  blocked = true;
  message = String(error?.message || error);
}

console.log(JSON.stringify({ blocked, message }));
