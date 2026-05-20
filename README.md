# Agent-Runway

[![Version](https://img.shields.io/badge/version-v0.36-blue)](../../issues)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](https://python.org)

<p align="center">
  <a href="README.md">English</a> |
  <a href="README_cn.md">中文</a> |
  <a href="README_es.md">Español</a> |
  <a href="README_fr.md">Français</a> |
  <a href="README_de.md">Deutsch</a> |
  <a href="README_pt.md">Português</a> |
  <a href="README_ja.md">日本語</a> |
  <a href="README_ko.md">한국어</a>
</p>

<p align="center"><img src="agent-runway.png" alt="Agent-Runway" width="900" /></p>

Make AI drive toward goals, not burn through trust.

`Agent-Runway` is for the developers stuck typing "continue" over and over while AI coding tools stall mid-task. There's a name for this role: Continue Engineer. It replaces self-reported "I'm done" with a mission, a receipt ledger, budgets, and gates — an audit mechanism that rejects mid-task quitting and fake effort. Ships as a skill file, scales through an MCP runtime for structured state tracking, and in Claude Code can physically block the agent from stopping without approval.

## 💪 What it can do

Read this as the capability snapshot first; the five-problem table right after it explains why each part exists.

| Capability | In practice |
|---|---|
| 🔒 Mission locking | Goal, criteria, scope, budgets, evidence map -> no vague success |
| ✍️ Signed receipts | Per-installation HMAC-signed -> inspectable, not rhetorical |
| 🚪 Completion gate | Every criterion mapped to receipts -> no unsupported "done" |
| 💰 Budget discipline | Slice/retry/time + `wrap_up_guidance` on exhaustion -> no infinite retry theater |
| 🛡️ Stale-evidence guard | After file edits, must re-verify -> prevents "edit then read" laundering |
| 🚫 Assertion blocking | 9 regex patterns reject "should work" / "probably" / "I believe" |
| 🔬 Counterexample | `record_counterexample_check` -> hypothesis + disconfirmers + surviving risk |
| 📝 Decision records | `record_decision_record` -> choice + rejected alternatives + reopen triggers |
| 🔐 Authorization | Irreversible actions require recorded, freshness-aware user approval |
| 🔄 Failure escalation | `record_stuck_attempt` -> materially different strategies only; escalation after retry budget |
| 📦 Handoff packet | Full JSON bundle across any host -> continuity without hidden memory |
| ⛔ Stop enforcement | Physical stop blocking in Claude Code (Stop hook); advisory in Codex/OpenCode/Pi CLI |
| ⚠️ Dangerous command interception | 10 categories + secret path denial with cross-platform variant matching |
| ⚖️ Value Gate | Only continue when high-impact, verifiable, low-expansion |
| 🧠 Project Learning Ledger | Reviewable JSONL for project pitfalls, runbooks, preferences, and invariants; advisory only, never evidence or authorization |
| 🧪 Adversarial Audit Gate | Bounded falsification for high-risk completion claims; never proof that bugs are absent |

## 🎯 The five problems this solves

Agents fail in a small set of predictable ways. Here are the five that matter, and how this project handles each.

| Problem | What happens | How it's fixed |
|---|---|---|
| Stops too early | Does one thing, freezes, waits for "continue" | Action frontier rule: keep going while the next step is still mission-aligned, reversible, and verifiable |
| Confidently wrong | Says "fixed" or "should pass" with no proof | Completion requires a gate with criterion-to-receipt mapping |
| Keeps polishing | Edits, audits, expands scope long after real work is done | Value Gate: only continue when impact is high and evidence gaps exist |
| Loses context | State drifts between turns | Handoff packets carry mission, evidence, budget, decisions, risks forward |
| Drifts past authority | Deploys, pushes, external calls without durable approval | Authorization records checked for freshness before irreversible actions |

The root problem: agents are naturally good at making results sound right, but nobody supervises them.

## ⚙️ How it works

```
mission_lock → bounded slice → receipt → turn_end_gate → repeat → completion_gate → handoff
```

Each stage produces a concrete runtime artifact:

| Stage | Job | Artifact |
|---|---|---|
| Lock mission | Define goal, criteria, scope, budgets, red lines, evidence plan | Mission record |
| Execute slice | One concrete, reversible, mission-aligned unit of work | Tool activity |
| Capture receipt | Record what happened: command, exit code, hash, diff | Signed receipt |
| Turn gate | Check stop legality and receipt freshness before ending | Approval or rejection |
| Completion gate | Verify every criterion has supporting receipts | Criterion-to-receipt decision |
| Handoff | Bundle mission, evidence, budget, risk for the next turn | Handoff packet |

This is not a prompt that asks for evidence. It is structured state — mission object, receipt ledger, budget tracker, approval tokens, authorization records — that the agent reads and the gates enforce. When a mission is refreshed, old receipts are invalidated and cannot be used for the new completion decision. All five gating tools (turn gate, completion gate, stuck attempt, decision record, counterexample) enforce this rule uniformly.

## ⚙️ Runtime modes

| Capability | 📄 Skill files | 📄 Skill + ⚙️ MCP | 📄 Skill + ⚙️ MCP + 🧩 Host Assist | 📄 Skill + ⚙️ MCP + 🔒 Hooks |
|---|---|---|---|---|
| **What runs** | Skill files | Skill + MCP | Skill + MCP + assist | Skill + MCP + hooks |
| **Mission lock** | Rules | ✅ | ✅ | ✅ |
| **Receipt ledger** | ◽ | ✅ | ✅ | ✅ |
| **Budget discipline** | Rules | ✅ | ✅ | ✅ |
| **Gate decisions** | Advisory | ✅ | ✅ | ✅ |
| **Authorization records** | ◽ | ✅ | ✅ | ✅ |
| **Dangerous command interception** | ◽ | ◽ | 🟡 host-specific | ✅ |
| **Stop enforcement** | ◽ | ◽ | ◽ | ✅ |
| **Typical strongest hosts** | Any Host | Codex, Cursor, VSCode | OpenCode, Pi CLI | Claude Code |

Shows the strongest mode currently claimed for each host; `🟡 host-specific` means the extra interception depends on the host.

OpenCode uses native MCP configuration by default. This repo includes the real bridge implementation at `.opencode/plugins/agent-runway.js`, but OpenCode does not auto-discover plugins from skill directories. It auto-loads local plugins only from project `.opencode/plugins/`, user `~/.config/opencode/plugins/`, or Windows `%USERPROFILE%\.config\opencode\plugins\` paths. If you want OpenCode tool events forwarded into the receipt ledger automatically, place a shim or symlink in one of those OpenCode plugin directories so it re-exports the skill plugin, then set `ILH_OPENCODE_BRIDGE=1`. This improves receipt capture.

Pi CLI support is intentionally narrower. `python scripts/generate_host_config.py --host pi-cli --project-dir <project-root>` emits an extension-only note, not native MCP config. The interception path: write a Pi extension that registers a `tool_call` callback via `pi.on("tool_call", ...)` and returns `{ block: true, reason: "..." }` to block dangerous tool calls; see `scripts/fixtures/pi_block_extension.js` as a template. Verified that `@mariozechner/pi-coding-agent@0.73.1` blocks an actual `bash` call through a Pi extension `tool_call` handler.

## 🔍 How The Gates Decide

The gates work on two layers: first they verify whether the evidence actually supports the claim, then they decide whether the next step is worth taking at all.

### Verification depth

The gates don't just check — they catch hand-waving at multiple levels:

- **Semantic matching.** The completion gate analyzes each criterion's wording. "Tests pass" or "build succeeds" demands execution receipts — a Read receipt won't cut it. "Edit" or "patch" demands mutation receipts. The gate rejects criteria whose intent doesn't match the evidence type supplied.
- **Post-mutation evidence.** After the last file edit, if no verification receipt exists at or after that sequence number for a criterion, the completion gate rejects it. No claiming "tests pass" with receipts from before the last change.
- **Assertion language rejection.** Work summaries and completion summaries containing "should work," "probably," "I believe," "seems to," "appears to," "looks correct," "I'm confident," or "it works" trigger automatic gate denial. Concrete action language required.
- **Goal alignment checkpoint.** Every third approved slice triggers a "goal_alignment_check_due" nudge — are you still heading where the mission says you're heading?
- **Observation-only warnings.** If a turn provides only Read/Glob/Grep receipts with no execution, the turn gate warns: reading isn't progress.

### Value Gate

Before taking the next step, check whether it's still worth taking.

| Check | Question | Bar |
|---|---|---|
| Impact | Affect correctness, safety, release, install, trust? | High |
| Evidence gap | Claim stronger than the proof? | Yes |
| Blocker | Skip = real blocker? | Yes |
| Size | Bounded change? | Small |
| Expansion | Grows runtime/API surface? | No |
| Verification | Clear test or audit? | Yes |
| Stop | Obvious when to stop? | Yes |

Continue only when impact is high, an evidence gap or real blocker exists, verification is clear, expansion is low, and stop is explicit. Otherwise converge. Five categories to converge: wording preferences, API surface expansion without a matching high-risk problem, score optimization without safety/install/verifiability gains, more local changes after gates pass with no new defect, and work whose value and verification path can't be stated. Value Gate is a rule, not a tool — the runtime already enforces budgets, receipts, freshness, authorization, and criterion mapping. An Adversarial Audit Gate is also available for high-risk missions: a bounded adversary attempts to falsify completion claims with executable counterexamples. It is conditional, not a global tax; memory is not evidence, preference is not authorization.

## 🔧 Failure handling and escalation

When stuck, retries must be materially different. `record_stuck_attempt` only counts strategies that genuinely change the approach — repeating the same path doesn't register. Once the retry budget is exhausted, `stuck_escalation` triggers: escalate with evidence that local options are spent, not just "it still fails."

## 🛠️ MCP tools

| Tool | Purpose |
|---|---|
| `mission_lock` | Lock or refresh mission |
| `mission_status` | View mission, gate freshness, approvals |
| `budget_status` | Slices, retries, time remaining |
| `list_recent_receipts` | List captured receipts |
| `verify_receipt_integrity` | Verify receipt signatures |
| `record_stuck_attempt` | Record a materially different failure strategy |
| `record_decision_record` | Record a consequential reversible choice |
| `record_counterexample_check` | Record disconfirming check and risk |
| `record_user_authorization` | Record approval for irreversible actions |
| `authorization_status` | Check authorization freshness |
| `turn_end_gate` | Approve or reject turn end |
| `completion_gate` | Approve or reject completion via receipt mapping |
| `export_handoff_packet` | Export continuity bundle |

## 📦 Installation

### Let AI Help You Install

If you're in an AI tool, you can send this directly to the AI:

```text
Help me install Agent-Runway:

1. Prerequisites: Python 3.11+
2. Clone repo: git clone https://github.com/Agent-Runway/Agent-Runway
3. Install deps: pip install mcp
4. Generate config: python scripts/generate_host_config.py --host <current-host> --project-dir <repo-path>
5. Merge the output JSON into the correct config target for my current host:
   - Claude Code -> <repo-path>/.claude/settings.json
   - OpenCode -> the OpenCode config file I actually use, such as ~/.config/opencode/opencode.json, ~/.config/opencode/config.json, %USERPROFILE%\.config\opencode\opencode.json, or %USERPROFILE%\.config\opencode\config.json
   - Codex/Cursor -> the MCP server config env section for that host
   - Pi CLI -> extension-only note; no native MCP config is emitted
6. If the host is OpenCode and I want automatic tool-event receipt capture, create ~/.config/opencode/plugins/agent-runway.js (or %USERPROFILE%\.config\opencode\plugins\agent-runway.js) with: export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
7. If the skill is installed somewhere else, adjust that re-export path to the actual skill location. Use a shim or symlink; do not blindly copy the raw plugin file unless you also preserve its relative path to scripts/opencode_plugin_bridge.py
8. Set ILH_OPENCODE_BRIDGE=1 in the generated OpenCode config or host environment, then restart OpenCode
9. Verify: python scripts/quick_validate.py <repo-path>
```

### Manual Setup

**Prerequisites:** Python 3.11+, clone from GitHub: `https://github.com/Agent-Runway/Agent-Runway`

```bash
pip install mcp
```

### Configuration Steps

Installation means adding the config JSON to your AI tool's configuration file.

#### 1. Generate Configuration

Run the command to generate config JSON (replace `<project-root>` with actual path):

**Claude Code:**
```bash
python scripts/generate_host_config.py --project-dir <project-root>
```

**OpenCode:**
```bash
python scripts/generate_host_config.py --host opencode --project-dir <project-root>
```

**Codex / Cursor:**
```bash
python scripts/generate_host_config.py --host <codex|cursor> --project-dir <project-root>
```

**Pi CLI:**
```bash
python scripts/generate_host_config.py --host pi-cli --project-dir <project-root>
```

Pi CLI output is an extension-only capability note. It is not a native MCP installer.

#### 2. Copy Config to Corresponding File

**Claude Code:** Copy the output JSON, merge into `.claude/settings.json` in project root

**OpenCode:** Copy the output JSON, merge into your OpenCode config file, such as `~/.config/opencode/opencode.json`, `~/.config/opencode/config.json`, `%USERPROFILE%\.config\opencode\opencode.json`, `%USERPROFILE%\.config\opencode\config.json`, or another OpenCode config path you actively use

#### 2a. Optional: enable the OpenCode plugin bridge

OpenCode does not auto-discover the skill-internal bridge file. It only auto-loads plugins from project `.opencode/plugins/`, user `~/.config/opencode/plugins/`, or Windows `%USERPROFILE%\.config\opencode\plugins\`.

Create a shim in a real OpenCode plugin directory, for example `~/.config/opencode/plugins/agent-runway.js` or `%USERPROFILE%\.config\opencode\plugins\agent-runway.js`:

```js
export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
```

If your skill is installed somewhere else, change the re-export path to the actual skill location. Prefer a shim or symlink. Do not blindly copy the raw plugin file unless you also preserve its relative path to `scripts/opencode_plugin_bridge.py`.

Then set `ILH_OPENCODE_BRIDGE=1` in your OpenCode configuration. The bridge treats explicit values as authoritative in this order: host process environment, then OpenCode config content, then discovered config files such as `opencode.json` or `.opencode/opencode.json`. Keeping `ILH_OPENCODE_BRIDGE="1"` under `mcp.agent-runway.environment` in the generated config is therefore a valid enablement path once the shim exists, and an explicit `"0"` keeps the bridge disabled. When the bridge is enabled this way, it also passes the configured `ILH_DB_PATH` and `ILH_SECRET_PATH` into the Python bridge process and disables Python bytecode writes to avoid project-local state/cache drift. Leave it at `"0"` when native MCP state and manual receipt recording are enough.

**Codex:** Copy the `env` section from output, add to Codex MCP server config environment variables

**Cursor:** Copy the `env` section from output, add to Cursor MCP server config environment variables

#### 3. Verify Installation

```bash
python scripts/quick_validate.py <project-root>
python -m unittest discover -s mcp/tests -p "test_*.py"
python scripts/smoke_test.py
```

To reproduce host-level blocking evidence when Claude Code, OpenCode, Node, and npm are available:

```bash
python scripts/host_blocking_experiments.py
```

### Configuration Details

**Default runtime file locations:**
- Database: `.agent-runway/state.db` (under project root)
- Secret key: Linux/macOS `~/.config/agent-runway/secret.key`, Windows `%USERPROFILE%\.config\agent-runway\secret.key`
- Override with environment variables: `ILH_DB_PATH` / `ILH_SECRET_PATH`

**Windows notes:**
- Pass absolute paths to `--project-dir`; PowerShell `"$(Get-Location)"` is the tested form
- Keep `ILH_DB_PATH` under a writable project directory; the runtime creates `.agent-runway` automatically
- If `ILH_SECRET_PATH` is customized, put it outside the repository and avoid syncing it. The runtime attempts to tighten Windows ACLs with `icacls`; if that fails it prints an explicit warning instead of silently pretending the key is locked down

## 📂 Project files

```text
.
├── SKILL.md                         # constitution
├── README*.md                       # multilingual docs
├── mcp/
│   ├── server.py                    # runtime
│   ├── agent_runway_runtime/
│   │   └── store.py                 # state & receipt ledger
│   └── tests/                       # tests
├── scripts/
│   ├── generate_host_config.py      # host config
│   ├── quick_validate.py            # structure check
│   ├── package_skill_check.py       # package check
│   ├── release_gate.py              # 16-gate harness
│   ├── release_static_checks.py     # static checks
│   ├── project_learning_lint.py     # project learning ledger lint
│   ├── project_learning_query.py    # bounded advisory ledger query
│   └── host_blocking_experiments.py # reproducible host blocking experiments
├── .opencode/
│   └── plugins/                     # optional OpenCode plugin bridge
└── references/                      # architecture, host, budget, receipt, parity, release, project learning
```

## ⚠️ Limits

- No hooks → stop enforcement is advisory
- A receipt proves execution, not semantic correctness
- Secret or DB access degrades receipt trust
- With Host Hooks, secret-key reads are denied across path variants
- With Host Hooks, dangerous shell commands trigger confirmation before execution
- With Host Hooks, any new receipt after a gate approval makes that approval stale, so `Stop` requires a fresh gate decision
- OpenCode `ask` is fail-closed, not a confirmation dialog
- Pi CLI support is extension-only: tested `tool_call` blocking, not native MCP or Stop hook parity
- Codex and Cursor are MCP paths here
- Project Learning Ledger is advisory only: memory is not evidence, and preference is not authorization

## ✍️ Credits

- Publisher: babutree
- Collaborator: Codex

## 🙏 Acknowledgments

Thanks to the sincere, friendly, united, and professional Linux.do community.<a href="https://linux.do" target="_blank" rel="noopener noreferrer"><img src="https://camo.githubusercontent.com/36a8066e13b53b968451a780de4cd6a432adeb175522afe7a080562e4f4e2534/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f4c696e7578446f2d636f6d6d756e6974792d316636666665622f68747470733a2f2f6c696e75782e646f" alt="LinuxDo" /></a>

## 📄 License

MIT.
