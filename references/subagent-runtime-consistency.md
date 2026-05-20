# Subagent Runtime Consistency

Runtime consistency is not a yes/no property. A child context may be fresh while child receipts share parent mission state through the Agent Runway MCP runtime. The parent must reason about each layer separately before trusting delegated work.

## Five Layers

| Layer | What Can Diverge | Required v0.37 Handling |
|---|---|---|
| LLM context | The child may start with a fresh prompt, a fork, a resumed context, or a teammate context. | Inject the child context contract explicitly; do not assume inherited mission knowledge. |
| tool permission | The child may have fewer, more, or different tools than the parent. | Record declared tool policy and reject claims that depend on unavailable or invisible tools. |
| workspace/sandbox | The child may run in a shared checkout, worktree, local sandbox, cloud sandbox, or unknown filesystem view. | Record `workspace_kind` and require parent re-verification when workspace provenance weakens the claim. |
| ILH_DB_PATH/MCP server | The child may or may not write to the same Agent Runway runtime database or MCP server. | Treat shared runtime receipts as L2; treat external logs as proof bundles until parent verification. |
| hook/plugin visibility | The host may expose child lifecycle, tool, and stop events, or only final text. | Claim L3 only when child start/tool/stop events are actually visible to hooks or plugins. |

## Rule

The child runtime is not automatically identical to parent runtime. A host row can upgrade only the layers it can actually observe. A weaker layer downgrades claims but does not loosen evidence rules.

## Practical Consequences

- A child can receive a fresh model context and still produce child receipts in the parent mission if `ILH_DB_PATH/MCP server` is shared.
- A child in a worktree can pass tests there, but parent completion still needs parent-side verification after merge or import.
- A child with prompt-only supervision can return useful directions, but parent completion must rely on parent receipts or imported evidence that has been re-verified.
- Tool/MCP inheritance and hook/plugin visibility must be stated as observed capability, not inferred from the parent session.
