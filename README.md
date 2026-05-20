<h1 align="center">Agent-Runway</h1>

<p align="center">
  <a href="../../issues"><img src="https://img.shields.io/badge/version-v0.37-blue" alt="Version" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License" /></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.11+-blue" alt="Python" /></a>
  <a href="https://linux.do"><img src="https://img.shields.io/badge/LinuxDo-community-feb106" alt="LinuxDo" /></a>
</p>

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

`Agent-Runway` is for the developers stuck typing "continue" over and over while AI coding tools stall mid-task. There's a name for this role: Continue Engineer. It replaces self-reported "I'm done" with a mission, a receipt ledger, budgets, and gates — an audit mechanism that rejects mid-task quitting and fake effort. Ships as a skill file, scales through an MCP runtime for structured state tracking, and can physically block stopping only when the Claude Code `Stop` hook is configured and active.

## 💪 What it can do

Read this as the capability snapshot first; the five-problem table right after it explains why each part exists.

| Capability | In practice |
|---|---|
| 🔒 Mission locking | Goal, criteria, scope, budgets, evidence map -> no vague success |
| ✍️ Signed receipts | Per-installation HMAC-signed -> inspectable, not rhetorical |
| 🚪 Completion gate | Fresh approved `turn_end_gate` plus every criterion mapped to covered receipts -> no unsupported "done" |
| 💰 Budget discipline | Slice/retry/time + `wrap_up_guidance` on exhaustion -> no infinite retry theater |
| 🛡️ Stale-evidence guard | After file edits, must re-verify -> prevents "edit then read" laundering |
| 🚫 Assertion-language gate | Multilingual patterns reject hedging in `turn_end_gate` / `completion_gate` summaries |
| 🔬 Counterexample | `record_counterexample_check` -> hypothesis + disconfirmers + outcome + surviving risk |
| 📝 Decision records | `record_decision_record` -> choice + rejected alternatives + reopen triggers |
| 🔐 Authorization | Irreversible actions require recorded, freshness-aware user approval; already-authorized commands are not asked about again |
| 🔄 Failure escalation | `record_stuck_attempt` -> materially different strategies only; escalation after retry budget |
| 📦 Handoff packet | Full JSON bundle across any host -> continuity without hidden memory |
| ⛔ Stop enforcement | Physical Stop blocking only with a configured Claude Code `Stop` hook; MCP/OpenCode/Pi/Codex/Cursor paths have no Stop-hook parity |
| ⚠️ Risk-event interception | Claude hooks can ask/deny risky shell commands and protected path reads; OpenCode bridge can fail closed when enabled; Pi CLI is extension-only |
| ⚖️ Value Gate | Only continue when high-impact, verifiable, low-expansion |
| 🧠 Project Learning Ledger | Project-local `.agent-runway` JSONL for pitfalls, runbooks, preferences, and invariants; advisory only, never evidence or authorization |
| 🧪 Adversarial Audit Gate | Bounded falsification for high-risk completion claims; never proof that bugs are absent |

## 🎯 The five problems this solves

Agents fail in a small set of predictable ways. Here are the five that matter, and how this project handles each.

| Problem | What happens | How it's fixed |
|---|---|---|
| Stops too early | Does one thing, freezes, waits for "continue" | Action frontier rule: keep going while the next step is still mission-aligned, reversible, and verifiable |
| Confidently wrong | Says "fixed" or "should pass" with no proof | Completion requires a gate with criterion-to-receipt mapping |
| Keeps polishing | Edits, audits, expands scope long after real work is done | Value Gate: only continue when impact is high and evidence gaps exist |
| Loses context | State drifts between turns | Handoff packets carry mission, evidence, budget, decisions, risks forward |
| Drifts past authority | Deploys, pushes, external calls without durable approval | Authorization records checked for freshness before irreversible actions; already-authorized commands are not asked about again, and commands outside that scope still require authorization |

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

Receipt-backed governance records also require actual captured receipt IDs. In Codex, Cursor, or any instructions-only MCP path without automatic tool receipt capture, an empty `receipt_ids` list is a capability gap signal, not a valid record; disclose direct local evidence separately or install/fix a host bridge rather than fabricating IDs.

## ⚙️ Runtime modes

| Capability | 📄 Skill files | 📄 Skill + ⚙️ MCP | 📄 Skill + ⚙️ MCP + 🧩 Host Assist | 📄 Skill + ⚙️ MCP + 🔒 Hooks |
|---|---|---|---|---|
| **What runs** | Skill files | Skill + MCP | Skill + MCP + assist | Skill + MCP + hooks |
| **Mission lock** | Rules | ✅ | ✅ | ✅ |
| **Receipt ledger** | ◽ | ✅ | ✅ | ✅ |
| **Budget discipline** | Rules | ✅ | ✅ | ✅ |
| **Gate decisions** | Advisory | ✅ | ✅ | ✅ |
| **Authorization records** | ◽ | ✅ | ✅ | ✅ |
| **Risk-event interception** | ◽ | ◽ | 🟡 host-specific | ✅ |
| **Stop enforcement** | ◽ | ◽ | ◽ | ✅ |
| **Typical strongest hosts** | Any Host | Codex, Cursor, VSCode | OpenCode, Pi CLI | Claude Code |

Shows the strongest mode currently claimed for each host; `🟡 host-specific` means the extra interception depends on the host.

OpenCode uses native MCP configuration by default. This repo includes the real bridge implementation at `.opencode/plugins/agent-runway.js`, but OpenCode does not auto-discover plugins from skill directories. It auto-loads local plugins only from project `.opencode/plugins/`, user `~/.config/opencode/plugins/`, or Windows `%USERPROFILE%\.config\opencode\plugins\` paths. If you want OpenCode tool events forwarded into the receipt ledger automatically, place a shim or symlink in one of those OpenCode plugin directories so it re-exports the skill plugin, then set `ILH_OPENCODE_BRIDGE=1`. This improves receipt capture, including shell exit-code propagation when OpenCode reports `exit`, `exitCode`, or `exit_code`, but it still does not provide Claude-style Stop-hook parity.

Pi CLI support is intentionally narrower. `python scripts/generate_host_config.py --host pi-cli --agent-runway-dir <agent-runway-dir>` emits an extension-only note, not native MCP config. The interception path: write a Pi extension that registers a `tool_call` callback via `pi.on("tool_call", ...)` and returns `{ block: true, reason: "..." }` to block dangerous tool calls; see `scripts/fixtures/pi_block_extension.js` as a template. Verified that `@mariozechner/pi-coding-agent@0.73.1` blocks an actual `bash` call through a Pi extension `tool_call` handler.

## 🔍 How The Gates Decide

The gates work on two layers: first they verify whether the evidence actually supports the claim, then they decide whether the next step is worth taking at all.

### Verification depth

The gates don't just check — they catch hand-waving at multiple levels:

- **Semantic matching.** The completion gate analyzes each criterion's wording. "Tests pass" or "build succeeds" demands execution receipts — a Read receipt won't cut it. "Edit" or "patch" demands mutation receipts. The gate rejects criteria whose intent doesn't match the evidence type supplied.
- **Turn-gate binding.** Completion requires a fresh approved `turn_end_gate`; every completion receipt must be covered by that latest turn gate, so agents cannot skip stop legality or swap in unreviewed receipts at completion time.
- **Post-mutation evidence.** After the last file edit, if no verification receipt exists at or after that sequence number for a criterion, the completion gate rejects it. No claiming "tests pass" with receipts from before the last change.
- **Assertion-language rejection.** `turn_end_gate` checks `work_summary` and `completion_gate` checks `completion_summary` for concrete hedging patterns across supported languages, such as "should work," "probably," "I believe," "seems to," "appears to," "looks correct," "I'm confident," or "it works." Concrete action language required.
- **Continuation-debt rejection.** A verified-slice stop cannot hide a still-local next high-value campaign, new alpha source, or template redesign inside assumptions, risks, or unverified items. Name it as real pending work and keep going, or use a legal soft stop when authority or information is actually missing.
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
| `mission_resume` | Resume active mission and refresh explicit host-session binding |
| `mission_status` | View mission, gate freshness, approvals |
| `budget_status` | Slices, retries, time remaining |
| `list_recent_receipts` | List captured receipts |
| `verify_receipt_integrity` | Verify receipt signatures |
| `record_stuck_attempt` | Record a materially different failure strategy |
| `record_decision_record` | Record a consequential reversible choice |
| `record_counterexample_check` | Record disconfirming check, observed outcome, and risk |
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
2. Clone Agent-Runway into the skills directory loaded by this CLI/host: git clone https://github.com/Agent-Runway/Agent-Runway <cli-skills-dir>/agent-runway
3. Install deps: pip install mcp
4. Generate config: python scripts/generate_host_config.py --agent-runway-dir <agent-runway-dir>
   If my host is not Claude Code, add --host opencode, --host codex, --host cursor, or --host pi-cli.
5. Merge the output JSON into the correct config target for my current host:
   - Claude Code -> the .claude/settings.json used by my Claude Code workspace or host config
   - OpenCode -> the OpenCode config file I actually use, such as ~/.config/opencode/opencode.json, ~/.config/opencode/config.json, %USERPROFILE%\.config\opencode\opencode.json, or %USERPROFILE%\.config\opencode\config.json
   - Codex/Cursor -> the MCP server config env section for that host
   - Pi CLI -> extension-only note; no native MCP config is emitted
6. If the host is OpenCode and I want automatic tool-event receipt capture, create ~/.config/opencode/plugins/agent-runway.js (or %USERPROFILE%\.config\opencode\plugins\agent-runway.js) with: export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
7. If the skill is installed somewhere else, adjust that re-export path to the actual skill location. Use a shim or symlink; do not blindly copy the raw plugin file unless you also preserve its relative path to scripts/opencode_plugin_bridge.py
8. Set ILH_OPENCODE_BRIDGE=1 in the generated OpenCode config or host environment, then restart OpenCode
9. Verify: python scripts/quick_validate.py <agent-runway-dir>
```

### Manual Setup

**Prerequisites:** Python 3.11+. Clone Agent-Runway into the skills directory loaded by your CLI or AI host: `git clone https://github.com/Agent-Runway/Agent-Runway <cli-skills-dir>/agent-runway`. This cloned directory is `<agent-runway-dir>` and contains `SKILL.md`, `scripts/`, and `mcp/`; it is not the host config file directory.

```bash
pip install mcp
```

### Configuration Steps

Installation means adding the config JSON to your AI tool's configuration file.

#### 1. Generate Configuration

Run the default command from `<agent-runway-dir>` to generate config JSON. It targets Claude Code unless you add `--host`.

```bash
python scripts/generate_host_config.py --agent-runway-dir <agent-runway-dir>
```

For OpenCode, Codex, Cursor, or Pi CLI, use the same command and add `--host opencode`, `--host codex`, `--host cursor`, or `--host pi-cli` before `--agent-runway-dir`.

Pi CLI output is an extension-only capability note. It is not a native MCP installer.

#### 2. Copy Config to Corresponding File

**Claude Code:** Copy the output JSON, merge into the `.claude/settings.json` used by your Claude Code workspace or host config.

**OpenCode:** Copy the output JSON, merge into your OpenCode config file, such as `~/.config/opencode/opencode.json`, `~/.config/opencode/config.json`, `%USERPROFILE%\.config\opencode\opencode.json`, `%USERPROFILE%\.config\opencode\config.json`, or another OpenCode config path you actively use

#### 2a. Optional: enable the OpenCode plugin bridge

OpenCode does not auto-discover the skill-internal bridge file. It only auto-loads plugins from project `.opencode/plugins/`, user `~/.config/opencode/plugins/`, or Windows `%USERPROFILE%\.config\opencode\plugins\`.

Create a shim in a real OpenCode plugin directory, for example `~/.config/opencode/plugins/agent-runway.js` or `%USERPROFILE%\.config\opencode\plugins\agent-runway.js`:

```js
export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
```

If your skill is installed somewhere else, change the re-export path to the actual skill location. Prefer a shim or symlink. Do not blindly copy the raw plugin file unless you also preserve its relative path to `scripts/opencode_plugin_bridge.py`.

Then set `ILH_OPENCODE_BRIDGE=1` in your OpenCode configuration. The bridge treats explicit values as authoritative in this order: host process environment, then OpenCode config content, then discovered config files such as `opencode.json` or `.opencode/opencode.json`. Keeping `ILH_OPENCODE_BRIDGE="1"` under `mcp.agent-runway.environment` in the generated config is therefore a valid enablement path once the shim exists, and an explicit `"0"` keeps the bridge disabled. Leave `ILH_DB_PATH` unset unless you intentionally want an explicit state file for this project; the bridge defaults to the event project's `.agent-runway/state.db`. The bridge still propagates configured environment values such as `ILH_SECRET_PATH` and disables Python bytecode writes to avoid project-local state/cache drift. Leave the bridge at `"0"` when native MCP state and manual receipt recording are enough.

**Codex:** Copy the `env` section from output, add to Codex MCP server config environment variables

**Cursor:** Copy the `env` section from output, add to Cursor MCP server config environment variables

#### 3. Verify Installation

```bash
python scripts/quick_validate.py <agent-runway-dir>
python -B -m pytest mcp/tests -q
python scripts/smoke_test.py
```

To reproduce host-level blocking evidence when Claude Code, OpenCode, Node, and npm are available:

```bash
python scripts/host_blocking_experiments.py
```

### Configuration Details

**Default runtime file locations:**
- Database: `.agent-runway/state.db` under the active project directory. Do not share the skill install directory as the default database across projects.
- Secret key: Linux/macOS `~/.config/agent-runway/secret.key`, Windows `%USERPROFILE%\.config\agent-runway\secret.key`
- Override with environment variables: `ILH_DB_PATH` / `ILH_SECRET_PATH`

**Windows notes:**
- Pass absolute paths to `--agent-runway-dir`; PowerShell `"$(Get-Location)"` is the tested form when you are inside the Agent-Runway skill directory
- Leave `ILH_DB_PATH` unset for normal project-local use. Set it only when you intentionally want a specific state file for that project; the runtime creates `.agent-runway` automatically
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
│   └── tests/                       # runtime and adapter tests
├── scripts/
│   ├── generate_host_config.py      # host config
│   ├── quick_validate.py            # structure check
│   ├── smoke_test.py                # runtime smoke test
│   ├── project_learning_lint.py     # project learning ledger lint
│   ├── project_learning_query.py    # bounded advisory ledger query
│   ├── context_recovery.py          # SQLite-first continuation recovery
│   ├── dynamic_context.py           # bounded mission-scoped context JSONL
│   ├── adversarial_audit_lint.py    # audit record lint
│   └── host_blocking_experiments.py # reproducible host blocking experiments
├── .opencode/
│   └── plugins/                     # optional OpenCode plugin bridge
└── references/                      # architecture, host, budget, receipt, parity, project learning
```

## ⚠️ Limits

- No configured Claude Code `Stop` hook → stop enforcement is advisory
- A receipt proves execution, not semantic correctness
- Secret or DB access degrades receipt trust
- With configured Claude Code hooks, secret-key reads are denied across path variants
- With configured Claude Code hooks, dangerous shell commands trigger confirmation before execution
- With configured Claude Code hooks, any new receipt after a gate approval makes that approval stale, so `Stop` requires a fresh gate decision
- With the optional OpenCode bridge enabled, `ask` decisions fail closed by denying the tool event; this is not a native confirmation dialog or Stop hook
- Pi CLI support is extension-only: tested `tool_call` blocking, not native MCP or Stop hook parity
- Codex and Cursor are MCP paths here; this repo does not claim automatic shell/read/edit receipt capture for them without an additional verified host bridge
- Project Learning Ledger is project-local only: keep ledger data under the active project's ignored `.agent-runway/`; memory is not evidence, and preference is not authorization
- Dynamic Context is project-local only: keep `.agent-runway/dynamic-context.jsonl` ignored, mission-scoped, capped at 100k bytes per record, and never use it as evidence or authorization

## 📄 License

MIT.
