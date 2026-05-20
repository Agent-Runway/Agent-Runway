# Agent-Runway API.md

版本：2026-05-19
源码对象：当前工作树 / README 标识 `v0.37`
范围：当前源码中可见 MCP runtime tools、host hook/script API、Project Learning API，以及未来 API 建议。
原则：以 `mcp/server.py` 源码签名为当前实现准绳；`archive/repoter/API.md` 是迁移来源和产品分析材料，但本文件是项目根目录下的维护版 API 参考。
生命周期状态：`stable-candidate`、`beta`、`experimental`、`internal-maintenance`、`future-proposal`。

---

## 0. API 总览

Agent-Runway 当前不是单一 HTTP 服务，而是由以下 API 面组成：

1. **MCP runtime tools**：`mcp/server.py` 中用 `_runtime_tool` 暴露的 19 个工具，是 agent 与监督 runtime 的主交互面。
2. **SQLite-backed store API**：`mcp/agent_runway_runtime/store.py` 内部持久化层，不建议外部直接调用。
3. **Host hook API**：Claude Code hooks、OpenCode plugin bridge、Pi CLI extension 等宿主适配层。
4. **Release / validation script API**：quick validate、smoke test、package check、benchmark、mutation、claim parity、release gate 等维护脚本。
5. **Project Learning Ledger API**：以 `.agent-runway/project-learning-ledger.jsonl` 为 canonical file，提供 lint/query 脚本；当前不提供 MCP 写入工具。
6. **Dynamic Context JSONL API**：以 `.agent-runway/dynamic-context.jsonl` 为显式本地上下文快照，提供 append/lint/query 脚本；当前不提供 MCP 写入工具。
7. **Future API**：未来建议新增的项目学习查询、CI evidence import、host capability status、policy pack、dashboard/export 等 API。

当前 MCP tool inventory 由源码直接确认：

1. `mission_lock`
2. `mission_resume`
3. `list_recent_receipts`
4. `budget_status`
5. `prompt_intake_gate`
6. `record_user_authorization`
7. `authorization_status`
8. `register_subagent_start`
9. `record_subagent_handoff`
10. `register_subagent_stop`
11. `subagent_status`
12. `verify_receipt_integrity`
13. `record_stuck_attempt`
14. `record_decision_record`
15. `record_counterexample_check`
16. `turn_end_gate`
17. `completion_gate`
18. `export_handoff_packet`
19. `mission_status`

---

## 1. 生命周期策略

| 状态 | 含义 | 兼容性建议 |
|---|---|---|
| `stable-candidate` | 当前核心机制已经清晰，但建议到 v0.40 才冻结 | patch 不破坏参数；minor 可加可选字段；删除或重命名必须走 deprecation |
| `beta` | 当前可用但仍需要真实项目验证 | 可调整字段，但必须提供 migration note 和测试覆盖 |
| `experimental` | 新能力，仍需证明价值和边界 | 不承诺长期兼容，不应作为企业 API 依赖 |
| `internal-maintenance` | 维护、测试、发布脚本，不面向 agent 常规调用 | 可随 release harness 调整，但必须保持 release 文档同步 |
| `future-proposal` | 本文建议未来设计 | 不能当作当前实现，不能写进当前能力表 |

### 1.1 推荐冻结策略

- v0.38：继续收敛 release packaging、host capability truthfulness、API/doc 漂移和 CI 分层。
- v0.40：冻结核心 MCP tool 的参数兼容策略。
- v1.0：冻结 mission、receipt、gate、handoff 的 schema version，并提供机器可读 schema。

### 1.2 兼容性红线

1. 已有 `stable-candidate` 参数不得无提示删除。
2. 可新增可选参数，但默认值必须保持旧行为。
3. 返回 payload 增字段可以兼容；移除字段、改名、改变 approved/rejected 语义必须视为 breaking。
4. release-only 脚本可以重构路径，但 release gate 文档和 claim parity 必须同步。
5. future-proposal 不得被 README 当前能力表引用为已实现能力。

---

## 2. 核心对象模型

### 2.1 Session

表示某个宿主/agent 会话。主要字段由 runtime store 管理：

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_id` | `str` | 会话命名空间，由 host/agent 稳定传入 |
| `host` | `str` | 宿主标识，如 `claude-code`、`opencode`、`codex` |
| `cwd` | `str` | 当前项目路径，用于 workspace mission 恢复和 host 上下文 |
| `created_at` | timestamp | 首次记录时间 |
| `updated_at` | timestamp | 最近刷新时间 |

使用范围：隔离不同 agent 会话，防止 `task_id` 串台。

### 2.2 Mission

表示被监督的任务边界。关键字段包括：

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_id` | `str` | 与 session 绑定 |
| `task_id` | `str` | 与 `session_id` 组成复合命名空间 |
| `goal` | `str` | 可验证任务目标 |
| `scope_boundary` | `str` | 范围边界，防止任务扩散 |
| `completion_criteria` | `list[str]` | 完成标准 |
| `red_lines` | `list[str]` | 明确禁止事项 |
| `slice_budget` | `int` | 工作切片预算 |
| `slice_count` | `int` | 已消耗切片数 |
| `retry_budget` | `int` | 允许的实质不同重试次数 |
| `status` | `str` | active/completed 等状态 |
| `mission_start_receipt_seq` | `int` | mission epoch 起点，用于阻断 mission 创建前的旧证据污染 |
| `notes` | `dict` | 验证计划、证据映射、假设、对抗审计等扩展状态 |

生命周期：`mission_lock` 创建新 mission；当前 runtime 禁止 relock active mission，也禁止复用已经存在过的同一 `session_id/task_id`。`turn_end_gate` 推进 slice；`completion_gate` 完成；`export_handoff_packet` 输出交接。

### 2.3 Receipt

表示执行证据。关键字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `receipt_id` | `str` | 证据 ID |
| `session_id` | `str` | 会话命名空间 |
| `task_id` | `str` | 任务命名空间，可为空或任务内 |
| `seq` | `int` | session 内单调序号 |
| `tool_name` | `str` | 工具名 |
| `command_text` | `str` | 命令或操作文本 |
| `exit_code` | `int | None` | 执行退出码 |
| `metadata` | `dict` | stdout hash、host data 等元数据 |
| `signature` | `str` | HMAC 签名 |
| `created_at` | timestamp | 记录时间 |

安全语义：receipt 证明执行事实和上下文，不单独证明语义正确。completion gate 应要求 receipt 新鲜、签名有效、exit code 合法，并与 criterion 对应。`task_id` 为空的 taskless receipt provenance 较弱：当前实现只在单 active mission、mission epoch 不早于当前任务且无未来时间戳时允许其支撑门控，并应返回非 mission-scoped warning；多 active mission 或未来 `created_at` 的 taskless receipt 必须拒绝。

### 2.4 Approval / Authorization

Approval 既用于 runtime gate，也用于用户授权记录。授权相关关键字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `gate_type` | `str` | 如 `user_authorization`、`turn_end_gate`、`completion_gate` |
| `token` | `str` | 授权或 gate token |
| `approved` | `bool` | 是否通过 |
| `after_receipt_seq` | `int` | 授权/审批绑定的 receipt 序号 |
| `ttl_seconds` | `int` | 有效期 |
| `meta.action_scope` | `str` | 动作范围 |
| `meta.approval_scope` | `str` | 授权范围说明 |
| `meta.user_statement_excerpt` | `str` | 用户原话摘录 |
| `meta.irreversible` | `bool` | 是否不可逆或外部动作 |

语义边界：偏好不是授权；项目学习记录不是授权；授权必须有范围与新鲜度。

### 2.5 Subagent Span / Handoff

Subagent 相关数据用于监督子任务，不用于相信自然语言摘要本身。

| 对象 | 说明 |
|---|---|
| `subagent_span` | 子 agent 生命周期记录，含类型、host child id、context mode、workspace kind、delegated scope、delegated budget、状态 |
| `subagent_handoff` | 子 agent 交接记录，含 summary、verified claims、receipt ids、risks、unverified items |

子 agent handoff 必须引用经过验证的 child receipts；`subagent_handoff:*` 本身不是 receipt。

### 2.6 Project Learning Record

JSONL 文件中的项目级经验记录。类型包括：

- `pitfall`
- `runbook`
- `preference`
- `invariant`
- `memory_update`

关键边界：Project Learning 是 advisory memory，不是 completion evidence，不是 authorization。

---

## 3. MCP Runtime Tools

### 3.1 `mission_lock`

**生命周期：`stable-candidate`**
**用途：** 锁定任务边界，创建新的 active mission，记录目标、完成标准、预算、风险、验证计划和高阶约束。

#### 源码签名

```python
mission_lock(
    session_id: str,
    task_id: str,
    goal: str,
    completion_criteria: list[str],
    scope_boundary: str = "",
    red_lines: list[str] | None = None,
    slice_budget: int = 24,
    retry_budget: int = 3,
    host: str = "unknown",
    cwd: str = ".",
    host_session_id: str = "",
    verification_plan: list[str] | None = None,
    evidence_map: list[dict[str, Any]] | None = None,
    assumptions: list[str] | None = None,
    defaults_chosen: list[str] | None = None,
    open_unknowns: list[str] | None = None,
    degradation_mode: str = "",
    decision_records_required: bool = False,
    counterexample_required: bool = False,
    benchmark_targets: list[str] | None = None,
    time_budget_minutes: int = 0,
    risk_budget: str = "",
    adversarial_audit_required: bool = False,
    adversarial_audit_profiles: list[str] | None = None,
    adversarial_audit_claims: list[str] | None = None,
    adversarial_audit_budget: dict[str, Any] | None = None,
    adversarial_audit_records: list[dict[str, Any]] | None = None,
) -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 | 注意事项 |
|---|---|---:|---|---|
| `session_id` | `str` | 必填 | 会话隔离 | 应由宿主稳定传入 |
| `task_id` | `str` | 必填 | mission 标识 | 与 `session_id` 组成复合命名空间 |
| `goal` | `str` | 必填 | 任务目标 | 必须非空，应可验证；不能包含不可见/control 字符 |
| `completion_criteria` | `list[str]` | 必填 | 完成标准 | 至少 1 条，不允许重复；单条不能包含不可见/control 字符 |
| `scope_boundary` | `str` | `""` | 范围边界 | 防止任务扩散；不能包含不可见/control 字符 |
| `red_lines` | `list[str] | None` | `None` | 禁止事项 | 如不得 push、不得删库；单条不能包含不可见/control 字符 |
| `slice_budget` | `int` | `24` | 工作切片预算 | 必须 >= 1 |
| `retry_budget` | `int` | `3` | 重试预算 | 必须 >= 1 |
| `host` | `str` | `unknown` | 宿主标识 | 用于 capability truthfulness |
| `cwd` | `str` | `.` | 项目路径 | host config / prompt intake / receipt context |
| `host_session_id` | `str` | `""` | 显式 host 会话绑定 | 仅在非空时写入 host-session rehydration 绑定；默认不把 `session_id` 伪装成 host binding |
| `verification_plan` | `list[str] | None` | `None` | 验证计划 | 建议列出测试、构建、审计命令 |
| `evidence_map` | `list[dict[str, Any]] | None` | `None` | criterion → evidence 规划 | 当前建议使用，未来可增强 schema |
| `assumptions` | `list[str] | None` | `None` | 假设 | 应在 handoff 中保留 |
| `defaults_chosen` | `list[str] | None` | `None` | 默认决策 | 防止隐式决定不可追溯 |
| `open_unknowns` | `list[str] | None` | `None` | 未知项 | 影响 stop/gate 判断 |
| `degradation_mode` | `str` | `""` | 降级说明 | host 能力不足时使用 |
| `decision_records_required` | `bool` | `False` | 是否需要决策记录 | 高风险任务建议 true |
| `counterexample_required` | `bool` | `False` | 是否需要反例检查 | 重要 claims 建议 true |
| `benchmark_targets` | `list[str] | None` | `None` | benchmark 要求 | 用于 release/性能任务 |
| `time_budget_minutes` | `int` | `0` | 时间预算 | 必须 >= 0；0 表示未声明 |
| `risk_budget` | `str` | `""` | 风险预算 | 建议用 low/medium/high 或文字说明 |
| `adversarial_audit_required` | `bool` | `False` | 是否要求对抗审计 | 高风险 claim/release 任务可启用 |
| `adversarial_audit_profiles` | `list[str] | None` | `None` | 对抗审计 profile | 当 `adversarial_audit_required=true` 时必须至少 1 个，且必须来自 runtime schema 的已知 profile，如 `runtime_gate_adversary` |
| `adversarial_audit_claims` | `list[str] | None` | `None` | 被审 claim | 当 `adversarial_audit_required=true` 时必须至少 1 条，防止启用审计但没有明确被审声明 |
| `adversarial_audit_budget` | `dict[str, Any] | None` | `None` | 对抗审计预算 | 当 `adversarial_audit_required=true` 时必须是非空 object；字段必须符合审计预算 schema |
| `adversarial_audit_records` | `list[dict[str, Any]] | None` | `None` | 初始审计记录 | 当前谨慎使用 |

#### 返回

文本摘要，包含 mission lock 成功、session/task、goal、budgets、completion criteria、red lines、verification/evidence count，以及调用 `turn_end_gate` 和 `completion_gate` 的提示。

#### 重要校验

- `mission_lock` 不重置既有任务边界：同一 `session_id/task_id` 若已有 active mission，会拒绝 relock；若该组合已经存在过 completed/历史 mission，也会拒绝复用。需要继续任务时使用 `mission_resume`，需要新边界时使用新的 `task_id`。这比“重置旧 mission”更安全，因为它保留 decision/counterexample/stuck/receipt epoch 的审计连续性，避免旧证据或旧 approval 被洗白。
- `goal`、每条 `completion_criteria`、`scope_boundary`、每条 `red_lines` 和 `adversarial_audit_claims` 不能包含运行时会剥离的不可见/control 字符，避免视觉相同或隐藏字符污染 mission 边界与审计目标。
- 当 `adversarial_audit_required=true` 时，必须提供非空 `adversarial_audit_budget`，并且 budget 字段必须符合 runtime 的 adversarial audit budget schema；不能用 `{}` 表示启用审计预算。

#### Scope/red-line 执行边界

`scope_boundary` 和 `red_lines` 是 mission 级约束。当前 MCP runtime 会：

- 在 `mission_status` / `export_handoff_packet` 中持续暴露这些边界。
- 在 `completion_gate` 中要求 `completion_summary` 披露 mission 的 `scope_boundary` 和 `red_lines`，防止完成声明绕开边界。
- 拒绝这些字段中的不可见/control 字符。

当前 MCP runtime **不会**仅凭这些文本自动拦截任意 shell 命令或文件编辑。命令级 ask/deny 需要已配置的 host hooks / bridge / extension，且能力强度取决于具体 host。没有 host hook 时，scope/red-line enforcement 是 runtime disclosure + review gate，而不是物理命令阻断。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "fix-release-packaging",
  "goal": "Make Agent-Runway release packaging reproducible from a clean staging root.",
  "completion_criteria": [
    "quick_validate passes on source tree",
    "package_skill_check passes on clean staged package",
    "official package contains no release-forbidden files"
  ],
  "scope_boundary": "Do not add new product features; only fix release reproducibility.",
  "red_lines": ["Do not remove release tests from the repository", "Do not claim stable if package check fails"],
  "slice_budget": 6,
  "retry_budget": 2,
  "host": "claude-code",
  "cwd": "/repo/agent-runway",
  "verification_plan": [
    "python scripts/quick_validate.py .",
    "python archive/release-tests/package_skill_check.py ."
  ],
  "decision_records_required": true,
  "counterexample_required": true
}
```

#### 应用范围

- 每个中高风险任务开始前。
- 长任务、跨文件修改、发布、迁移、host config、文档声明变更。
- 需要防止“继续工程师”问题的多步骤任务。

#### 不适用

- 极小、可立即回答的普通问答。
- 无需 runtime 证据的纯解释性交流。

---

### 3.2 `mission_resume`

**生命周期：`stable-candidate`**
**用途：** 恢复一个已存在的 active mission，返回当前预算、新鲜度与下一步建议，并在显式提供 `host_session_id` 时刷新 host-session 绑定，供压缩上下文或新宿主会话后的后续 `prompt_intake_gate` 使用。

#### 源码签名

```python
mission_resume(session_id: str, task_id: str, host_session_id: str = "") -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 |
|---|---|---:|---|
| `session_id` | `str` | 必填 | mission 的 runtime 会话 |
| `task_id` | `str` | 必填 | mission 标识 |
| `host_session_id` | `str` | `""` | 显式 host 会话绑定；非空时刷新 rehydration 绑定 |

#### 返回

文本摘要，包含 mission status、slice usage、mission epoch、最新 turn/completion gate freshness、time pressure、下一步建议；若刷新绑定，会包含 `binding_refreshed: yes`。

#### 语义边界

- 只恢复已有 active mission；找不到 mission 时返回可解析 JSON 错误。
- 只在 `host_session_id` 非空时写 host-session 绑定。
- 不代表 host 自动调用该工具，不代表 pre-prompt 注入，也不代表物理 stop enforcement；这些仍取决于具体 host hook/adapter 能力。

---

### 3.3 `list_recent_receipts`

**生命周期：`stable-candidate`**
**用途：** 查询当前 session/task 最近 receipts，帮助 gate 和 handoff 选择证据。

#### 源码签名

```python
list_recent_receipts(session_id: str, task_id: str = "", limit: int = 10) -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 |
|---|---|---:|---|
| `session_id` | `str` | 必填 | 指定会话 |
| `task_id` | `str` | `""` | 为空时查询 session 下近期 receipts；有 active mission 时按 mission scope 查询 |
| `limit` | `int` | `10` | 返回数量上限，源码夹紧到 1..50 |

#### 返回

- 若无 receipt：返回 `No receipts recorded for this scope yet...`
- 若有 receipt：返回 `_format_receipts()` 的文本列表。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "fix-release-packaging",
  "limit": 5
}
```

#### 应用范围

- gate 前回看证据。
- handoff 前整理执行记录。
- 审计时定位最近失败命令。

---

### 3.4 `budget_status`

**生命周期：`stable-candidate`**
**用途：** 查询 mission 的 slice/retry/time/risk 等预算使用情况。

#### 源码签名

```python
budget_status(session_id: str, task_id: str) -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 |
|---|---|---:|---|
| `session_id` | `str` | 必填 | 会话 |
| `task_id` | `str` | 必填 | mission |

#### 返回

JSON 字符串，来自 `_budget_snapshot()`，通常包含 slice、retry、time remaining、budget exhausted、guidance 等字段。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "fix-release-packaging"
}
```

#### 应用范围

- 长任务中检查是否该收敛。
- 防止无限重试或伪勤奋。
- handoff 时输出预算快照。

---

### 3.5 `prompt_intake_gate`

**生命周期：`beta`**
**用途：** 在接到用户请求时做 prompt intake，识别任务类型、风险、是否需要 mission lock、是否存在已有状态或项目记忆提示。

#### 源码签名

```python
prompt_intake_gate(
    session_id: str,
    user_message: str,
    cwd: str = ".",
    task_id: str = "",
    previous_assistant_state: dict[str, Any] | None = None,
    workspace_state: dict[str, Any] | None = None,
    memory_hint: dict[str, Any] | None = None,
) -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 |
|---|---|---:|---|
| `session_id` | `str` | 必填 | 当前会话 |
| `user_message` | `str` | 必填 | 用户原始请求 |
| `cwd` | `str` | `.` | 当前项目路径 |
| `task_id` | `str` | `""` | 可选已有任务过滤 |
| `previous_assistant_state` | `dict[str, Any] | None` | `None` | 上一轮状态摘要 |
| `workspace_state` | `dict[str, Any] | None` | `None` | 工作区状态 |
| `memory_hint` | `dict[str, Any] | None` | `None` | 项目记忆提示 |

#### 返回

JSON 字符串，内容由 `classify_prompt_intake()` 生成；当同一 session 下匹配多个 active missions 时，会返回 ambiguous session mission payload。

#### 示例

```json
{
  "session_id": "codex-thread-77",
  "user_message": "Fix the packaging bug and update README claims accordingly.",
  "cwd": "/repo/agent-runway",
  "memory_hint": {
    "ledger_path": ".agent-runway/project-learning-ledger.jsonl"
  }
}
```

#### 应用范围

- 新任务开始前。
- 判断是否需要严肃 mission lock。
- 识别 `continue` / `继续` / 多语言继续信号。
- 辅助降低 prompt ambiguity。

#### 生命周期说明

该 API 与用户意图解析强相关，容易被误用为“自动规划器”。当前它只返回 directive，不强制 host 预注入；没有 user-message hook 的 host 不能声称自动 prompt intake enforcement。

---

### 3.6 `record_user_authorization`

**生命周期：`stable-candidate`**
**用途：** 记录用户对特定动作范围的授权。对已授权的命令不再反复询问；超出授权范围的命令仍需授权。

#### 源码签名

```python
record_user_authorization(
    session_id: str,
    task_id: str,
    action_scope: str,
    approval_scope: str,
    user_statement_excerpt: str,
    irreversible: bool = False,
    ttl_seconds: int = 1800,
    authorization_kind: str = "scoped_approval",
) -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 |
|---|---|---:|---|
| `session_id` | `str` | 必填 | 会话 |
| `task_id` | `str` | 必填 | mission，必须 active |
| `action_scope` | `str` | 必填 | 动作范围，如 `git push origin main` |
| `approval_scope` | `str` | 必填 | 授权范围说明 |
| `user_statement_excerpt` | `str` | 必填 | 用户原话摘录 |
| `irreversible` | `bool` | `False` | 是否不可逆/外部动作 |
| `ttl_seconds` | `int` | `1800` | `scoped_approval` 的授权有效期，源码夹紧到 60..7200 |
| `authorization_kind` | `str` | `scoped_approval` | `scoped_approval` 表示普通审批；`standing_boundary` 表示这条授权长期有效，不再重复询问同一命令/范围 |

#### 返回

文本摘要，包含 authorization token、action scope、approval scope、authorization kind、irreversible、expires_at。

#### 重要校验

- `action_scope`、`approval_scope` 和 `user_statement_excerpt` 不能包含运行时会剥离的不可见/control 字符，避免把视觉上相同或隐藏污染的授权范围写入 runtime state。
- `authorization_kind=standing_boundary` 不能与 `irreversible=true` 同用；不可逆或外部动作仍需要 fresh scoped approval。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "release-v0.38",
  "action_scope": "create GitHub release draft only",
  "approval_scope": "draft release, no publish",
  "user_statement_excerpt": "可以创建 draft，但不要正式发布",
  "irreversible": false,
  "ttl_seconds": 1800,
  "authorization_kind": "scoped_approval"
}
```

`authorization_kind="standing_boundary"` 只用于用户明确说某个命令或范围以后不用再问的情况，例如“Gitea 不需要我授权，但 GitHub 需要我授权”。这类记录写入 `expires_at: "never"`。`standing_boundary` 不允许 `irreversible=true`；删除、部署、force push、GitHub 发布等不可逆或公开副作用必须使用 fresh scoped approval。对已授权的命令不再反复询问；GitHub、部署、删除、force push 等超出授权范围的命令仍需单独授权。

#### 应用范围

- git push、发布、部署、删除、外部 API 调用等动作前。
- 和 host hooks 配合，防止模糊授权扩大化。

---

### 3.7 `authorization_status`

**生命周期：`stable-candidate`**
**用途：** 查询当前 mission 的授权状态。

#### 源码签名

```python
authorization_status(session_id: str, task_id: str, action_scope: str = "") -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 |
|---|---|---:|---|
| `session_id` | `str` | 必填 | 会话 |
| `task_id` | `str` | 必填 | mission |
| `action_scope` | `str` | `""` | 可选；要检查的当前动作范围。传入时会与已记录 `action_scope` 做规范化精确匹配 |

#### 返回

JSON 字符串：`{"task_id": ..., "authorization": ...}`。authorization payload 包含是否存在、freshness、authorization kind、expiry、`requested_action_scope`、`scope_matches_requested_action` 等状态。传入 `action_scope` 时，只有已记录 scope 与请求 scope 规范化后精确一致，`fresh` 才会保持 true；未传入时保留旧的 freshness 查询语义，并返回 `scope_matches_requested_action: null`。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "release-v0.38",
  "action_scope": "create GitHub release draft only"
}
```

#### 应用范围

- 高风险动作前检查。
- handoff 时说明授权是否仍然有效。
- MCP status 查询可以报告 scope 是否匹配；实际阻断仍取决于调用方或已配置 host hooks 是否在执行前使用该状态。

---

### 3.8 `register_subagent_start`

**生命周期：`beta`**
**用途：** 记录主 agent 委派子 agent / subagent 的开始状态。

#### 源码签名

```python
register_subagent_start(
    session_id: str,
    task_id: str,
    subagent_type: str,
    delegated_scope: str,
    delegated_budget: dict[str, Any],
    host: str = "unknown",
    host_child_id: str = "",
    context_mode: str = "fresh",
    workspace_kind: str = "shared_checkout",
) -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 |
|---|---|---:|---|
| `session_id` | `str` | 必填 | 主会话 |
| `task_id` | `str` | 必填 | active mission |
| `subagent_type` | `str` | 必填 | 子 agent 类型，如 `code-reviewer` |
| `delegated_scope` | `str` | 必填 | 委派范围 |
| `delegated_budget` | `dict[str, Any]` | 必填 | 子任务预算，必须是 JSON object；当前治理 `max_slices`、`max_tool_calls`、`max_elapsed_seconds` |
| `host` | `str` | `unknown` | 宿主 |
| `host_child_id` | `str` | `""` | 宿主 child id |
| `context_mode` | `str` | `fresh` | 上下文模式；必须属于源码允许集合 |
| `workspace_kind` | `str` | `shared_checkout` | 工作区类型；必须属于源码允许集合 |

#### 枚举约束

当前源码约束：

| 字段 | 允许值 |
|---|---|
| `context_mode` | `fresh`, `fork`, `resumed`, `team`, `unknown` |
| `workspace_kind` | `shared_checkout`, `worktree`, `local_sandbox`, `cloud_sandbox`, `unknown` |

#### delegated budget 约束

- `max_slices`、`max_tool_calls`、`max_elapsed_seconds` 必须是整数且 `>= 1`；`true/false` 不能伪装成整数。
- `max_slices` 不能超过父 mission 剩余 slice。
- `max_tool_calls` 不能超过父 mission 剩余 slice 推导出的工具调用上限。
- `max_elapsed_seconds` 不能超过父 mission 剩余时间；父 mission 未声明时间预算时，仍受默认子任务耗时上限约束。
- 同一 mission 同时 running 的 subagent 数量有 runtime 上限；已 terminal 的 child span 不计入 running 数。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "audit-readme",
  "subagent_type": "security-reviewer",
  "delegated_scope": "Review README claims against source code only",
  "delegated_budget": {"max_slices": 2, "max_tool_calls": 10, "max_elapsed_seconds": 1200},
  "host": "claude-code",
  "context_mode": "fresh",
  "workspace_kind": "shared_checkout"
}
```

#### 应用范围

- 多 agent 审计。
- 代码审查、文档审查、安全审查分工。

#### 风险

不要把子 agent 的自然语言摘要当证据。必须要求 receipt/handoff。

---

### 3.9 `record_subagent_handoff`

**生命周期：`beta`**
**用途：** 记录子 agent 的 handoff，总结已验证 claims、receipt IDs、风险和未验证项。

#### 源码签名

```python
record_subagent_handoff(
    session_id: str,
    task_id: str,
    child_span_id: str,
    summary: str,
    verified_claims: list[dict[str, Any]],
    receipt_ids: list[str],
    risks: list[str] | None = None,
    unverified_items: list[str] | None = None,
) -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 |
|---|---|---:|---|
| `session_id` | `str` | 必填 | 主会话 |
| `task_id` | `str` | 必填 | active mission |
| `child_span_id` | `str` | 必填 | 子 agent span |
| `summary` | `str` | 必填 | 摘要，源码要求至少 20 字符 |
| `verified_claims` | `list[dict[str, Any]]` | 必填 | 已验证 claims |
| `receipt_ids` | `list[str]` | 必填 | 子任务证据 receipts |
| `risks` | `list[str] | None` | `None` | 风险 |
| `unverified_items` | `list[str] | None` | `None` | 未验证项 |

#### 证据约束

- `receipt_ids` 必须非空、唯一。
- 每个 receipt 必须存在、属于当前 mission scope、属于该 `child_span_id`。
- receipt 必须通过签名验证。
- receipt 必须属于当前 mission epoch，不能引用 mission 创建前的旧证据。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "audit-readme",
  "child_span_id": "span-002",
  "summary": "README overclaims OpenCode stop parity; source supports native MCP plus optional bridge only.",
  "verified_claims": [
    {"claim": "OpenCode config exists", "evidence": ["mcp config file read"]},
    {"claim": "Stop parity not implemented", "evidence": ["host integration docs inspected"]}
  ],
  "receipt_ids": ["r_102", "r_103"],
  "risks": ["Docs may mislead enterprise users"],
  "unverified_items": ["Real OpenCode plugin runtime not tested on installed host"]
}
```

---

### 3.10 `register_subagent_stop`

**生命周期：`beta`**
**用途：** 记录子 agent 停止状态、预算消耗、artifact references 和最后消息。

#### 源码签名

```python
register_subagent_stop(
    session_id: str,
    task_id: str,
    child_span_id: str,
    status: str,
    budget_consumed: dict[str, Any] | None = None,
    transcript_ref: str = "",
    artifact_refs: list[str] | None = None,
    last_message: str = "",
) -> str
```

#### 参数

| 参数 | 类型 | 默认值 |
|---|---|---:|
| `session_id` | `str` | 必填 |
| `task_id` | `str` | 必填 |
| `child_span_id` | `str` | 必填 |
| `status` | `str` | 必填 |
| `budget_consumed` | `dict[str, Any] | None` | `None` |
| `transcript_ref` | `str` | `""` |
| `artifact_refs` | `list[str] | None` | `None` |
| `last_message` | `str` | `""` |

#### 枚举约束

当前源码允许 `status` 为：`completed`、`failed`、`abandoned`、`rejected`。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "audit-readme",
  "child_span_id": "span-002",
  "status": "completed",
  "budget_consumed": {"slices": 1},
  "artifact_refs": ["reports/readme-claim-audit.md"],
  "last_message": "Main risk is overclaiming host parity."
}
```

---

### 3.11 `subagent_status`

**生命周期：`beta`**
**用途：** 查询当前 mission 下子 agent spans 和 handoffs。

#### 源码签名

```python
subagent_status(session_id: str, task_id: str) -> str
```

#### 参数

| 参数 | 类型 | 默认值 |
|---|---|---:|
| `session_id` | `str` | 必填 |
| `task_id` | `str` | 必填 |

#### 返回

JSON 字符串，结构包含 `task_id`、`summary` 和 `child_spans`。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "audit-readme"
}
```

---

### 3.12 `verify_receipt_integrity`

**生命周期：`stable-candidate`**
**用途：** 验证 receipt 是否存在、签名是否有效、是否属于当前 session/task。

#### 源码签名

```python
verify_receipt_integrity(session_id: str, receipt_ids: list[str], task_id: str = "") -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 |
|---|---|---:|---|
| `session_id` | `str` | 必填 | 会话 |
| `receipt_ids` | `list[str]` | 必填 | receipt id 列表；必须非空唯一 |
| `task_id` | `str` | `""` | 可选任务约束 |

#### 返回

JSON 字符串，包含：

| 字段 | 说明 |
|---|---|
| `all_valid` | 是否全部签名有效 |
| `results` | 每个 receipt 的 `receipt_id`、`tool_name`、`task_id`、`valid` |

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "fix-release-packaging",
  "receipt_ids": ["r_001", "r_002"]
}
```

#### 应用范围

- completion gate 前。
- handoff 前。
- 对抗审计时检查旧证据/伪证据。

---

### 3.13 `record_stuck_attempt`

**生命周期：`stable-candidate`**
**用途：** 记录卡住后的实质不同尝试，防止重复同一失败动作。

#### 源码签名

```python
record_stuck_attempt(
    session_id: str,
    task_id: str,
    strategy_fingerprint: str,
    summary: str,
    receipt_ids: list[str],
) -> str
```

#### 参数

| 参数 | 类型 | 默认值 |
|---|---|---:|
| `session_id` | `str` | 必填 |
| `task_id` | `str` | 必填 |
| `strategy_fingerprint` | `str` | 必填 |
| `summary` | `str` | 必填 |
| `receipt_ids` | `list[str]` | 必填 |

#### 证据约束

`receipt_ids` 必须存在、非空、唯一、属于当前 mission scope，并且不早于当前 mission epoch。
空 `receipt_ids` 不是合法降级路径：治理记录是 runtime-backed record，必须引用已经捕获的 receipt evidence。若当前 host 没有自动 receipt capture，应把本地检查结果作为弱化的直接证据在回复中披露，或修复 host bridge / hook，使操作先产生 receipt；不得为了通过 API 伪造 receipt id。
`strategy_fingerprint` 和 `summary` 不能包含运行时会剥离的不可见/control 字符，避免用隐藏字符伪造不同重试策略或污染 stuck evidence 摘要。

#### 与完成门控的关系

记录 `record_stuck_attempt` 表示当前任务进入新的卡住/失败状态边界。若在某次 approved
`turn_end_gate` 之后又记录了新的 stuck attempt，旧 turn gate 不能继续支撑
`completion_gate`；完成前必须再次通过新的 `slice_verified` 或 `frontier_exhausted`
`turn_end_gate`。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "fix-tests",
  "strategy_fingerprint": "switch-from-full-unittest-to-targeted-failing-test",
  "summary": "Full suite timed out; isolated failing package check instead.",
  "receipt_ids": ["r_201"]
}
```

---

### 3.14 `record_decision_record`

**生命周期：`stable-candidate`**
**用途：** 记录重要设计、产品、发布决策及被拒绝替代方案。

#### 源码签名

```python
record_decision_record(
    session_id: str,
    task_id: str,
    title: str,
    choice_made: str,
    alternatives_rejected: list[str],
    evidence_receipt_ids: list[str],
    reversibility: str = "reversible",
    reopen_triggers: list[str] | None = None,
) -> str
```

#### 参数

| 参数 | 类型 | 默认值 |
|---|---|---:|
| `session_id` | `str` | 必填 |
| `task_id` | `str` | 必填 |
| `title` | `str` | 必填 |
| `choice_made` | `str` | 必填 |
| `alternatives_rejected` | `list[str]` | 必填 |
| `evidence_receipt_ids` | `list[str]` | 必填 |
| `reversibility` | `str` | `reversible` |
| `reopen_triggers` | `list[str] | None` | `None` |

#### 证据约束

`evidence_receipt_ids` 必须非空、唯一、属于当前 mission scope，并且不早于当前 mission epoch。无自动 receipt capture 的 host 不能用空数组创建 runtime-backed 决策记录；应先生成真实 receipt，或把该判断标为直接本地证据而不是 MCP 决策记录。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "project-learning-design",
  "title": "Use JSONL as canonical project learning store",
  "choice_made": "Use .agent-runway/project-learning-ledger.jsonl rather than SQLite for shared project memory.",
  "alternatives_rejected": ["SQLite-only shared memory", "Markdown as canonical source", "Vector store/RAG first"],
  "evidence_receipt_ids": ["r_310", "r_311"],
  "reversibility": "reversible",
  "reopen_triggers": ["Multiple agents need concurrent writes", "JSONL conflict rate becomes high"]
}
```

---

### 3.15 `record_counterexample_check`

**生命周期：`stable-candidate`**
**用途：** 记录对关键假设/claim 的反例检查，防止只找支持证据。

#### 源码签名

```python
record_counterexample_check(
    session_id: str,
    task_id: str,
    hypothesis: str,
    attempted_disconfirmers: list[str],
    outcome: str,
    receipt_ids: list[str],
    surviving_risk: str = "",
) -> str
```

#### 参数

| 参数 | 类型 | 默认值 |
|---|---|---:|
| `session_id` | `str` | 必填 |
| `task_id` | `str` | 必填 |
| `hypothesis` | `str` | 必填，必须是具体/实质性治理文本 |
| `attempted_disconfirmers` | `list[str]` | 必填，至少一项；每项必须具体 |
| `outcome` | `str` | 必填，必须是具体/实质性结果 |
| `receipt_ids` | `list[str]` | 必填，非空唯一 |
| `surviving_risk` | `str` | `""` |

#### 文本具体性约束

`hypothesis`、`attempted_disconfirmers` 和 `outcome` 不能只是 `ok`、`done`、
`checked`、`完成`、`erledigt`、`terminé`、`hecho`、`feito`、`完了`、
`완료` 这类短泛化词。当前 runtime 用可见长度、Unicode 词元数量和 CJK
字符数做启发式具体性检查；它能拒绝明显空泛的治理记录，但不应被描述为完整语义
分类器或所有泛化词黑名单。

#### 证据约束

当前实现要求 `receipt_ids` 非空、唯一、属于当前 mission scope，并且不早于当前 mission epoch。若 host 未能为 bash/read/apply_patch 等操作自动记录 Agent-Runway receipt，调用该工具会失败；这应作为 host bridge / receipt capture 问题排查，或降级为回复中的直接本地证据披露，而不是绕过为无 receipt 的反例记录。空 `receipt_ids` 不能代表“我在当前宿主做过检查”。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "release-v0.37-audit",
  "hypothesis": "The release gate fully passes in this unpacked working tree.",
  "attempted_disconfirmers": ["Run package_skill_check", "Run release_gate with timeout scale", "Inspect forbidden package members"],
  "outcome": "Disconfirmed: package_skill_check failed before the clean-root fix; after fix targeted package validation passes.",
  "receipt_ids": ["r_401"],
  "surviving_risk": "Actual official package_skill.py may be absent locally; fake official packager regression covers full-tree-copy risk."
}
```

---

### 3.16 `turn_end_gate`

**生命周期：`stable-candidate`**
**用途：** 每一轮停止前验证 stop condition 是否合法、是否有新鲜 receipts、是否还有明确可逆下一步。

#### 源码签名

```python
turn_end_gate(
    session_id: str,
    task_id: str,
    stop_condition: str,
    work_summary: str,
    receipt_ids: list[str],
    pending_actions_identified: list[str] | None = None,
    reason_for_stopping: str = "",
    assumptions_remaining: list[str] | None = None,
    known_risks: list[str] | None = None,
    unverified_items: list[str] | None = None,
) -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 |
|---|---|---:|---|
| `session_id` | `str` | 必填 | 会话 |
| `task_id` | `str` | 必填 | mission |
| `stop_condition` | `str` | 必填 | 停止原因 |
| `work_summary` | `str` | 必填 | 本轮做了什么，源码要求至少 20 字符 |
| `receipt_ids` | `list[str]` | 必填 | 本轮支撑 receipts，必须非空唯一 |
| `pending_actions_identified` | `list[str] | None` | `None` | 是否仍有下一步 |
| `reason_for_stopping` | `str` | `""` | 停止理由 |
| `assumptions_remaining` | `list[str] | None` | `None` | 剩余假设 |
| `known_risks` | `list[str] | None` | `None` | 已知风险披露；用于合法收口 failed / over-budget 子任务 |
| `unverified_items` | `list[str] | None` | `None` | 未验证项披露；用于合法收口缺口和子任务 handoff |

#### stop condition 源码枚举

| 值 | 语义 |
|---|---|
| `slice_verified` | 一个有 receipt 支撑的 bounded slice 已验证 |
| `frontier_exhausted` | 当前 action frontier 已耗尽 |
| `user_information_required` | 需要用户独占信息 |
| `approval_required` | 需要用户授权 |
| `interpretation_deadlock` | 存在无法本地消解的解释分歧 |
| `stuck_escalation` | 已记录足够实质不同尝试，进一步本地重试不再合理 |

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "fix-release-packaging",
  "stop_condition": "slice_verified",
  "work_summary": "Identified package_skill_check failure and isolated forbidden members in official package output.",
  "receipt_ids": ["r_501"],
  "pending_actions_identified": [],
  "reason_for_stopping": "End of bounded slice; next slice has clear fix path."
}
```

#### 重要语义

- 只有真实工作推进应消耗 slice。
- 等待授权或等待用户独占信息不应被当成工作 slice。
- receipt 应来自当前 mission epoch。
- taskless receipt 只在当前 session 只有单个 active mission 且 `created_at` 不在未来时可作为弱 provenance 证据使用；通过时会返回非 mission-scoped warning。多 active mission 或未来时间戳 taskless receipt 必须拒绝。
- 若 `stop_condition` 是 `slice_verified` 或 `frontier_exhausted`，`pending_actions_identified` 必须为空，且 `work_summary`、`reason_for_stopping`、`assumptions_remaining`、`known_risks`、`unverified_items` 不能写入仍可本地执行的 next step / 下一步 / 后续工作。长期任务中，`next high-value campaign`、`new alpha source`、`template redesign` 等仍属于 continuation debt；不能通过移入假设、风险或未验证项来把它伪装成已耗尽 frontier。
- `frontier_exhausted` 不能作为首个工作停止条件；当前实现要求至少已有一个 `slice_verified` 后，才能声明本地 action frontier 已耗尽。
- 通过的 `turn_end_gate` 会在 approval meta 中记录本次 gate 覆盖的 `receipt_ids`。后续 `completion_gate` 只能使用最新 fresh turn gate 覆盖过的 receipts。
- 通过的 `turn_end_gate` 还会记录当时最新 stuck attempt id；若之后出现新的 stuck attempt，旧 turn gate 不再 fresh，完成前必须重新验证 slice/frontier。
- `work_summary` 不能依赖“应该可以”“seems fixed”等断言语言，也不能包含会被运行时剥离的不可见/control 字符。
- `reason_for_stopping` 不能包含会被运行时剥离的不可见/control 字符。
- `pending_actions_identified`、`assumptions_remaining`、`known_risks` 和 `unverified_items` 不能包含不可见/control 字符。
- `slice_verified` 和 `frontier_exhausted` 会对 `work_summary`、`reason_for_stopping`、`assumptions_remaining`、`known_risks`、`unverified_items` 按可见文本和 NFKC 归一化后检查 pending local work；不能用 zero-width 字符或 fullwidth Latin 把 `next slice`、`next step`、`remaining work` 等继续信号拆开来绕过停止门。

---

### 3.17 `completion_gate`

**生命周期：`stable-candidate`**
**用途：** 任务完成前检查 completion criteria 是否有对应新鲜证据、是否存在未验证项和已知风险。

#### 源码签名

```python
completion_gate(
    session_id: str,
    task_id: str,
    completion_summary: str,
    criterion_receipt_map: list[dict[str, Any]] | None = None,
    unverified_items: list[str] | None = None,
    known_risks: list[str] | None = None,
) -> str
```

#### 参数

| 参数 | 类型 | 默认值 | 当前使用 |
|---|---|---:|---|
| `session_id` | `str` | 必填 | 会话 |
| `task_id` | `str` | 必填 | mission |
| `completion_summary` | `str` | 必填 | 完成摘要，源码要求至少 20 字符 |
| `criterion_receipt_map` | `list[dict[str, Any]] | None` | `None` | 完成标准到 receipt 的映射；当前必需 |
| `unverified_items` | `list[str] | None` | `None` | 未验证项 |
| `known_risks` | `list[str] | None` | `None` | 已知风险 |

#### 兼容性说明

当前实现保留历史 positional 调用兼容：如果第三个 positional 参数是
`criterion_receipt_map` list、第四个 positional 参数是 `completion_summary`
string，runtime 会按旧顺序交换解释。新代码应使用本文档签名或关键字参数；v0.40
冻结前应决定是否正式 deprecate 旧顺序，并保留 compatibility test 防止误删或误宣称。

#### `criterion_receipt_map` 结构

当前源码要求它是 list，每个元素必须是 object：

```json
[
  {
    "criterion": "quick_validate passes on source tree",
    "receipt_ids": ["r_601"]
  },
  {
    "criterion": "package_skill_check passes on clean staged package",
    "receipt_ids": ["r_602"]
  }
]
```

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "fix-release-packaging",
  "completion_summary": "Clean staging packaging now passes quick_validate and package_skill_check; README claims updated.",
  "criterion_receipt_map": [
    {"criterion": "quick_validate passes on source tree", "receipt_ids": ["r_601"]},
    {"criterion": "package_skill_check passes on clean staged package", "receipt_ids": ["r_602"]},
    {"criterion": "official package contains no release-forbidden files", "receipt_ids": ["r_603"]}
  ],
  "unverified_items": [],
  "known_risks": ["Full release gate still requires slow CI environment confirmation"]
}
```

#### 返回语义

- 通过：返回 `APPROVED`、approval token、task status、receipts used，并在仍有未完成任务时附带 `active_missions_remaining`、`remaining_active_task_ids`、`next_action_required` 和 `next_active_task_id`，避免把当前任务完成误读为全局完成。
- 拒绝：返回 `REJECTED`、violations、rejection token，可能包含 warnings。

#### 重要校验

- 每条 completion criterion 必须有映射。
- 不允许未知 criterion。
- receipt 必须存在、签名有效、属于当前 session，且属于当前 task 或满足 taskless 弱 provenance 例外，并属于当前 mission epoch。
- taskless receipt 可在单 active mission 中作为弱 provenance 证据使用并返回 warning；如果 session 内存在多个 active missions，或 taskless receipt 的 `created_at` 在当前时间之后，`completion_gate` 必须拒绝。
- 失败 execution receipt 不能支撑成功 criterion。
- mutation 后需要执行类 receipt 的 criterion 必须有新鲜验证。
- 如果 mission 要求 decision record 或 counterexample check，则缺失时拒绝完成。
- 如果 adversarial audit required 且存在 blocking violations，则拒绝完成。
- 如果 mission 设置了 `scope_boundary` 或 `red_lines`，`completion_summary` 必须披露这些边界；该检查防止完成声明绕过 mission 约束，但不等同于 host 级命令阻断。
- `completion_summary` 不能包含会被运行时剥离的不可见/control 字符。
- `known_risks` 和 `unverified_items` 不能包含不可见/control 字符。
- `completion_summary`、`known_risks` 和 `unverified_items` 会按可见文本和 NFKC 归一化后检查 pending local work；不能用 zero-width 字符或 fullwidth Latin 把继续信号拆开来绕过完成门。

#### 与 `turn_end_gate` 的关系

- `completion_gate` 前必须已经存在 fresh 且 approved 的 `turn_end_gate`，不能用 fresh receipt 直接绕过停止合法性检查。
- 不能通过过期、缺失或被拒绝的 turn gate 支撑完成。
- 最新 `turn_end_gate` 的 `stop_condition` 必须是 `slice_verified` 或 `frontier_exhausted`；`stuck_escalation`、`approval_required`、`user_information_required` 等软停止不能直接支撑完成。
- 最新 `turn_end_gate` 必须晚于或覆盖最新 stuck attempt；如果 stuck attempt 发生在最新 turn gate 之后，`completion_gate` 必须拒绝并要求新的 verified slice。
- `completion_gate` 使用的每个 receipt 必须被最新 approved `turn_end_gate` 的 `receipt_ids` 覆盖，避免先用一组证据过停止门、再用另一组未声明证据完成。
- `completion_gate` 仍会独立检查 `completion_summary` 的可见长度、断言语言、receipt scope/signature、criterion 语义匹配、mutation 后 freshness、decision/counterexample requirement 和 adversarial audit violations。

---

### 3.18 `export_handoff_packet`

**生命周期：`stable-candidate`**
**用途：** 输出 mission 的完整交接包，包括目标、状态、预算、receipts、授权、风险、未知项、子 agent 状态等。

#### 源码签名

```python
export_handoff_packet(session_id: str, task_id: str) -> str
```

#### 参数

| 参数 | 类型 | 默认值 |
|---|---|---:|
| `session_id` | `str` | 必填 |
| `task_id` | `str` | 必填 |

#### 返回字段

当前 payload 包含：

| 字段 | 说明 |
|---|---|
| `schema_version` | handoff packet schema version；当前为 `1.0` |
| `mission` | mission 基础状态、目标、criteria、scope/red lines、notes、mission epoch；不重复预算计数 |
| `budget_status` | `_budget_snapshot()` 输出 |
| `latest_receipts` | 最近 5 条 mission-scope receipts |
| `decision_records` | 当前 mission 的决策记录 |
| `counterexample_checks` | 当前 mission 的反例检查 |
| `latest_turn_gate` | 最近 turn gate approval/rejection 与 freshness |
| `latest_completion_gate` | 最近 completion gate approval/rejection 与 freshness |
| `latest_user_authorization` | 最近用户授权状态 |
| `adversarial_audit_status` | 对抗审计状态 |
| `criterion_coverage` | completion gate notes 中的 criterion receipt map |
| `known_risks` | 完成时记录的已知风险 |
| `unverified_items` | 完成时记录的未验证项 |
| `recommended_next_action` | budget guidance |

预算字段只在 `budget_status` 中出现，例如 `slice_budget`、`slice_count`、`retry_budget`、`slices_remaining`、`retries_remaining` 和 `wrap_up_guidance`。`mission` 对象只保留 identity、goal、status、criteria、scope、red lines、notes 和 `mission_start_receipt_seq`，避免 handoff 消费方在两个位置合并同一预算语义。

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "fix-release-packaging"
}
```

#### 应用范围

- 对话压缩前。
- 任务交接给另一个 agent。
- 人类审计或 PR summary。

---

### 3.19 `mission_status`

**生命周期：`stable-candidate`**
**用途：** 查询一个 task 或 session 下 mission 状态。

#### 源码签名

```python
mission_status(session_id: str, task_id: str = "") -> str
```

#### 参数

| 参数 | 类型 | 默认值 |
|---|---|---:|
| `session_id` | `str` | 必填 |
| `task_id` | `str` | `""` |

#### 返回

正常命中单个 mission 时返回文本摘要，包含 mission status、session/task、goal、slice/retry usage、last receipt seq、decision/counterexample count、completion criteria、red lines、budget pressure、latest gates、latest user authorization 等。

找不到指定 mission 时返回可解析 JSON：

```json
{
  "error": "No mission found for this session/task."
}
```

同一 session 存在多个 active missions 且未传入 `task_id` 时返回可解析 JSON，要求调用方显式指定 task：

```json
{
  "error": "Multiple active missions; specify task_id.",
  "candidate_missions": []
}
```

#### 示例

```json
{
  "session_id": "claude-2026-05-14-a",
  "task_id": "fix-release-packaging"
}
```

#### 应用范围

- 开始新 slice 前确认状态。
- host session start hook。
- dashboard 查询。

---

## 4. Host Hook / Adapter API

### 4.1 Claude Code hooks

**生命周期：`stable-candidate`，但依赖宿主实际 hook 支持**
**入口：** `scripts/claude_hooks.py`
**配置生成：** `scripts/generate_host_config.py --host claude-code ...`

#### 主要 hook event

| Event | 作用 | Enforcement 强度 |
|---|---|---|
| `SessionStart` | 初始化/读取 runtime 状态 | 中 |
| `PreToolUse` | 工具调用前拦截 secret/risky action | 高，取决于 hook 生效 |
| `PostToolUse` | 工具调用后记录 receipt | 高，取决于 hook 生效 |
| `SubagentStart` | 记录 subagent span | 中；需要明确 `agent_runway` contract |
| `SubagentStop` | 记录 subagent stop/handoff | 中；无 contract 时只能做 visibility evidence |
| `Stop` | 停止前调用 turn/completion gate | 高，Claude Code 路径最强 |

#### 风险

- 如果 hook 没安装或宿主版本变更，enforcement 会退化。
- Shell secret detection 是保守匹配，不是完整 shell interpreter。
- Agent-Runway 不能声称阻止所有可能的数据外泄方式。

### 4.2 OpenCode plugin bridge

**生命周期：`beta`**
**入口：** `.opencode/plugins/agent-runway.js` + `scripts/opencode_plugin_bridge.py`
**启用：** 需要 `ILH_OPENCODE_BRIDGE=1` 与真实 OpenCode plugin 目录。

#### 行为

- `tool.execute.before`：把 `input.args` 转发给 bridge。
- bridge 返回 `deny`：plugin 抛错阻断。
- bridge 返回 `ask`：当前采用 fail-closed，而不是交互式 permission UI。
- `tool.execute.after`：记录执行后信息；shell-like 工具会把 OpenCode response 或 metadata 中的 `exit` / `exitCode` / `exit_code` 归一化为 receipt 的 `exit_code`，否则 completion evidence 会退化为不可证明成功。退出码只接受整数或整数字符串；`bool` 与非数字字符串会被视为 unknown，而不是被误记为成功或失败。

#### 生命周期说明

OpenCode native MCP 是核心路径，plugin bridge 是增强路径。不要声称它与 Claude Code Stop hook 完全等价。

#### 当前已知边界

- 没有 repo-evidenced user-message/prompt-submit hook，因此不能声称 OpenCode 自动预注入 `prompt_intake_gate`。
- 若 bridge 未启用或没有落在 OpenCode 实际 plugin 搜索目录，bash/read/apply_patch 等 host tool 不会自动产生 Agent-Runway receipt。

### 4.3 Pi CLI extension

**生命周期：`experimental`**
**入口：** 生成的 extension template / `tool_call` handler。

#### 语义

- 适合展示 Agent-Runway 作为 extension 的接入方式。
- 当前不应宣传为完整 MCP/Stop enforcement parity。

### 4.4 Codex / Cursor / VSCode MCP advisory configs

**生命周期：`beta` for config generation；enforcement 为 advisory**

#### 语义

- 可以连接 MCP runtime。
- 没有等价 Claude Code Stop hook 时，停止阻断通常不能强制。
- README 必须明确能力边界。

---

## 5. Script / Release API

### 5.1 `scripts/quick_validate.py`

**生命周期：`internal-maintenance`**
**用途：** 检查 skill/package 结构基础合法性。

示例：

```bash
python scripts/quick_validate.py .
```

建议：作为所有 release gate 的第一道 mandatory gate。

### 5.2 `scripts/smoke_test.py`

**生命周期：`internal-maintenance`**
**用途：** 运行一条典型 mission → receipt → decision/counterexample → turn gate → completion gate → handoff 流程。

示例：

```bash
python scripts/smoke_test.py
```

### 5.3 `archive/release-tests/package_skill_check.py`

**生命周期：`internal-maintenance`**
**用途：** package validation，包括内部打包、解包验证、可选官方 packager 验证、forbidden members 检查。

示例：

```bash
python archive/release-tests/package_skill_check.py .
```

当前状态：已修复 2026-05-14 报告中的 clean staging/root 风险。当前脚本会先用 `release_files` 规则生成内部 clean package、解包并验证，然后在官方 `package_skill.py` 可用时对 **extracted clean root** 运行官方 packager，而不是直接对开发工作树打包。

关键返回字段：

| 字段 | 说明 |
|---|---|
| `quick_validate_before_package` | 源树结构检查结果 |
| `internal_package` | 内部 clean package 摘要和 forbidden members |
| `quick_validate_after_internal_package` | 解包后的 clean root 结构检查 |
| `opencode_bridge_import_after_internal_package` | 解包后的 clean root 若包含 OpenCode bridge，则在无外部 `PYTHONPATH` 下执行 bridge import smoke；验证 `scripts/opencode_plugin_bridge.py` 能找到 `mcp/agent_runway_runtime` |
| `official_package_script` | 官方 package script 路径；不存在时为 null |
| `official_package_skill` | 官方 package 输出摘要；官方脚本不可用时显式标记 unavailable |
| `official_package_validated` | 官方脚本可用且输出 clean zip 时为 true |
| `passed` | 总体是否通过 |

注意：官方 `package_skill.py` 在本机可能不可用；此时脚本仍会使用自包含 clean package validation，并在 JSON 中明确 `available: false`，不能谎称官方工具已验证。
`opencode_bridge_import_after_internal_package` 只验证 clean package 的 Python import/path 可用性；它不表示 OpenCode 已从真实 plugin 目录发现 shim，也不表示 host-assisted bridge 已在当前宿主会话启用。

### 5.4 `archive/release-tests/release_gate.py`

**生命周期：`internal-maintenance`**
**用途：** 聚合 release gates。

当前 gate 包含 quick validate、package validation、unit tests、smoke test、consistency lint、claim parity、project learning lint、ledger guard、self audit、benchmark、adversarial audit、mutation、subagent lint、release static checks 等维护项。

建议：

- 不要只报告 N/N passed，还应列出与 `archive/release-tests/release-gates.md` 的映射关系。
- 支持 timeout scale、JSON 输出、失败 artifact 保留。
- release gate 直接执行的子脚本必须自行设置 import path，不应依赖外部 `PYTHONPATH`。

### 5.5 `scripts/project_learning_lint.py`

**生命周期：`beta`**
**用途：** lint `.agent-runway/project-learning-ledger.jsonl`，确保项目记忆不会越权成 evidence/authorization。

示例：

```bash
python scripts/project_learning_lint.py .agent-runway/project-learning-ledger.jsonl --json
```

缺失默认 ledger 时：

- 默认：返回错误，适合强 lint 场景。
- `--allow-missing`：返回 warning + passed，适合 release gate 中“项目可无 ledger”的场景。

### 5.6 `scripts/project_learning_query.py`

**生命周期：`beta`**
**用途：** 查询项目级坑位、runbook、preference、invariant。

示例：

```bash
python scripts/project_learning_query.py --task packaging --limit 5 --json
```

当前状态：缺失 ledger 是允许的 advisory 状态，返回空结果 + warning，退出码为 0；malformed JSON 仍返回 errors，退出码为 2。这个边界由 `mcp/tests/test_project_learning_query_edges.py` 覆盖。

### 5.7 `scripts/dynamic_context.py`

**生命周期：`experimental`**
**用途：** 在 compact、跨 turn、跨 host 恢复时保存显式、本地、可 lint 的动态上下文快照。默认路径是 `.agent-runway/dynamic-context.jsonl`，该目录应被项目 `.gitignore` 忽略。

示例：

```bash
python scripts/dynamic_context.py append --session-id opencode --task-id todo-csv-rigorous-acceptance-and-execution --kind next_action --summary "Next local slice" --content "Continue item 19 analysis before any upload."
python scripts/dynamic_context.py lint --json
python scripts/dynamic_context.py query --session-id opencode --task-id todo-csv-rigorous-acceptance-and-execution --max-output-bytes 100000 --json
```

关键约束：

- 每条记录必须包含 `mission_id`、`session_id`、`task_id`；`mission_id` 必须等于 `session_id/task_id`。
- 单条 `content` 上限是 `100000` UTF-8 bytes。
- query 的默认输出预算是 `100000` bytes，并按 mission 过滤。
- `can_support_completion` 必须为 `false`；`requires_fresh_verification` 必须为 `true`。
- 它只解决“上下文可恢复”问题，不是 receipt、completion evidence、authorization、Project Learning active memory，也不是静默 fallback。
- 当前只提供文件 CLI；不要新增 MCP 写入工具来自动污染项目上下文。

### 5.8 `scripts/context_recovery.py`

**生命周期：`experimental`**
**用途：** 在 compact、跨 session continuation 或上下文丢失后，按固定顺序恢复候选 mission：先查当前项目 SQLite，再查显式 dynamic context JSONL，仍不足时要求用户澄清。

示例：

```bash
python scripts/context_recovery.py --cwd /path/to/project --session-id opencode-new-session --json
```

恢复顺序：

1. 当前项目 `.agent-runway/state.db` 中与 `session_id/task_id` 或当前 `cwd` 唯一匹配的 active mission。
2. 当前项目 `.agent-runway/dynamic-context.jsonl` 中最新 valid mission-scoped record。
3. 仅当项目实际存在 `agent-runway/dynamic-context.jsonl` 时，把它作为 compatibility candidate 检查。
4. 若以上来源不足或歧义，返回 `clarification_required`，不伪造 mission。

关键约束：

- dynamic context 恢复结果是 advisory candidate，必须随后用 `mission_status`、`export_handoff_packet`、文件状态或用户确认重新验证。
- 该脚本不写 runtime state，不授予 authorization，不产生 completion evidence。

---

## 6. Dynamic Context JSONL Schema

**生命周期：`experimental`**
**Canonical path：** `.agent-runway/dynamic-context.jsonl`

### 6.1 设计原则

- Dynamic context is explicit local context, not hidden memory.
- Dynamic context is not evidence.
- Dynamic context is not authorization.
- Dynamic context must be mission-scoped.
- Dynamic context must be bounded to avoid context-window flooding.

### 6.2 `dynamic_context` 字段

必需字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | `str` | `1.0` |
| `type` | `str` | `dynamic_context` |
| `mission_id` | `str` | 必须等于 `session_id/task_id` |
| `session_id` | `str` | runtime session namespace |
| `task_id` | `str` | mission task namespace |
| `kind` | `str` | `note` / `finding` / `next_action` / `decision` / `risk` |
| `summary` | `str` | 简短摘要 |
| `content` | `str` | 上下文正文，最多 `100000` UTF-8 bytes |
| `created_at` | `str` | UTC 秒级时间戳 |
| `can_support_completion` | `bool` | 必须为 `false` |
| `requires_fresh_verification` | `bool` | 必须为 `true` |

### 6.3 示例

```json
{
  "schema_version": "1.0",
  "type": "dynamic_context",
  "mission_id": "opencode/todo-csv-rigorous-acceptance-and-execution",
  "session_id": "opencode",
  "task_id": "todo-csv-rigorous-acceptance-and-execution",
  "kind": "next_action",
  "summary": "Continue local context retention audit",
  "content": "Audit existing handoff, mission_status, prompt_intake, and project learning boundaries before deciding whether more implementation is needed.",
  "created_at": "2026-05-15T00:00:00Z",
  "can_support_completion": false,
  "requires_fresh_verification": true
}
```

---

## 7. Project Learning Ledger Schema

**生命周期：`beta`**
**Canonical path：** `.agent-runway/project-learning-ledger.jsonl`

### 7.1 设计原则

- Memory is not evidence.
- Preference is not authorization.
- Project learning is advisory and scoped.
- Active learning must require fresh verification.
- No secrets.
- No unscoped global claims.
- Project ledger JSON/JSONL 文件是项目本地数据，不应打包进 Agent-Runway skill release。

### 7.2 当前主记录字段

当前 lint 脚本要求主记录至少包含：

| 字段 | 类型 | 用途 |
|---|---|---|
| `schema_version` | `str` | 当前要求 `1.0` |
| `type` | `str` | `pitfall` / `runbook` / `preference` / `invariant` |
| `id` | `str` | 稳定 ID，不能重复 |
| `project_id` | `str` | 项目标识 |
| `status` | `str` | `draft` / `candidate` / `active` / `mitigated` / `obsolete` / `disputed` |
| `summary` | `str` | 简短描述 |
| `applies_to` | `dict` | hosts、paths、platforms、tasks、commands、languages、scope 等作用范围 |
| `source_refs` | `list[dict]` | 来源引用 |
| `created_at` | `str` | UTC 秒级时间戳 |
| `can_support_completion` | `bool` | 必须 false |
| `requires_fresh_verification` | `bool` | 必须 true |

可选但常用字段：

| 字段 | 用途 |
|---|---|
| `last_verified_at` | 最近验证时间 |
| `last_confirmed_at` | 最近确认时间 |
| `expires_at` | 过期时间 |
| `invalid_if` | 何时失效 |
| `reopen_if` | 何时重开判断 |
| `severity` / `priority` | low/medium/high/critical |
| `steps` | runbook 步骤 |

### 7.3 `memory_update` 字段

`memory_update` 是追加式状态变更，必需字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | `str` | `1.0` |
| `type` | `str` | `memory_update` |
| `id` | `str` | 更新记录 ID |
| `target_id` | `str` | 被更新主记录 ID，必须存在 |
| `action` | `str` | `mark_obsolete` / `mark_disputed` / `mark_mitigated` / `refresh_verified` |
| `reason` | `str` | 原因 |
| `source_refs` | `list[dict]` | 来源 |
| `created_at` | `str` | UTC 秒级时间戳 |

### 7.4 示例

```json
{
  "schema_version": "1.0",
  "type": "pitfall",
  "id": "pitfall-release-packaging-archive-cache",
  "project_id": "agent-runway",
  "status": "active",
  "summary": "Official package output can include release-forbidden archive/cache files if packaging is run from dirty working tree.",
  "applies_to": {"paths": ["archive/release-tests"], "tasks": ["release packaging"]},
  "source_refs": [{"kind": "file", "path": "archive/release-tests/package_skill_check.py", "summary": "clean-root package validation"}],
  "created_at": "2026-05-14T00:00:00Z",
  "last_verified_at": "2026-05-15T00:00:00Z",
  "invalid_if": ["package_skill_check.py stops using extracted clean root for official packager"],
  "severity": "high",
  "can_support_completion": false,
  "requires_fresh_verification": true
}
```

---

## 8. Future API Proposals

以下不是当前实现，不能写入 README 当前能力，只能作为 roadmap。

### 8.1 `project_learning_query_mcp`

**生命周期：`future-proposal`**
**用途：** 让 agent 通过 MCP 只读查询项目学习记录。

#### 参数建议

| 参数 | 类型 | 默认值 |
|---|---|---:|
| `session_id` | `str` | 必填 |
| `task_id` | `str` | `""` |
| `query` | `str` | 必填 |
| `types` | `list[str]` | `[]` |
| `limit` | `int` | `5` |
| `scope_paths` | `list[str]` | `[]` |

#### 关键约束

- 返回结果必须带 advisory warning。
- 不得作为 completion evidence。
- 不得自动注入授权。

### 8.2 `record_project_learning_candidate`

**生命周期：`future-proposal`**
**用途：** 提交项目学习候选，而不是直接写 active memory。

#### 参数建议

| 参数 | 类型 | 默认值 |
|---|---|---:|
| `session_id` | `str` | 必填 |
| `task_id` | `str` | 必填 |
| `record_type` | `str` | 必填 |
| `summary` | `str` | 必填 |
| `scope` | `dict` | 必填 |
| `evidence_receipt_ids` | `list[str]` | 必填 |
| `proposed_status` | `str` | `candidate` |

#### 关键约束

- 只能写 candidate。
- active 需要 lint + human/review gate。
- candidate 不能自动影响 completion gate。

### 8.3 `host_capability_status`

**生命周期：`future-proposal`**
**用途：** 返回当前 host 的实际 enforcement 能力。

#### 参数建议

| 参数 | 类型 | 默认值 |
|---|---|---:|
| `session_id` | `str` | 必填 |
| `host` | `str` | 必填 |
| `cwd` | `str` | `.` |

#### 返回建议

```json
{
  "host": "opencode",
  "mcp_available": true,
  "pre_tool_hook": "optional-plugin-bridge",
  "post_tool_receipts": "available-if-bridge-enabled",
  "stop_enforcement": "advisory",
  "known_gaps": ["No Claude Code Stop parity"],
  "recommended_mode": "mcp+optional-bridge"
}
```

### 8.4 `ci_evidence_import`

**生命周期：`future-proposal`**
**用途：** 将 CI run、PR check、test report 导入为外部 evidence receipt。

关键约束：

- 必须标识 external source、URL、commit SHA、timestamp。
- 必须防止把过期 commit 的 CI 结果用于新 mission。
- 建议支持 GitHub Actions、GitLab CI、Buildkite。

### 8.5 `policy_pack_validate`

**生命周期：`future-proposal`**
**用途：** 验证团队 policy pack 的 schema、host coverage、risk profile。

适用场景：Team/Enterprise。

### 8.6 `export_release_report`

**生命周期：`future-proposal`**
**用途：** 输出机器可读 release report，用于 PR、audit、dashboard。

建议格式：JSON + Markdown。

### 8.7 `evidence_graph_query`

**生命周期：`future-proposal`**
**用途：** 查询 mission、receipts、criteria、subagent handoffs、decision records 的关系图。

风险：过早做图数据库会增加复杂度。建议先从 SQLite query + JSON export 开始。

### 8.8 `mission_template_apply`

**生命周期：`future-proposal`**
**用途：** 应用预定义 mission 模板，如 release、security audit、README claim audit、migration。

价值：降低 `mission_lock` 参数复杂度。

---

## 9. API 设计红线

1. **不要把 Project Learning 变成 evidence。** Project learning 可以 seed hypotheses，但不能 satisfy evidence。
2. **不要把 preference 变成 authorization。** 偏好只能影响默认工作方式，不能授权 push/deploy/delete。
3. **不要把 receipt 说成 semantic correctness。** Receipt 证明执行事实，语义正确仍需 criterion mapping 和 fresh verification。
4. **不要把 advisory MCP mode 说成 hard stop enforcement。** 没有 host Stop hook 时，停止阻断仍是 advisory。
5. **不要让 future API 出现在当前能力表里。** Future proposal 不能被当成当前实现。
6. **不要过早扩展 HTTP/SaaS API。** 先把本地 API 生命周期、schema versioning、host truthfulness 稳定。
7. **不要让 API 返回“approved”但同时隐藏未验证项。** known risks 和 unverified items 必须显式暴露。
8. **不要为了通过工具而伪造 receipt。** 如果 host 没有自动 receipt capture，应修 host bridge 或记录弱化证据，而不是制造假 receipt。
9. **不要把 dynamic context 说成证据或授权。** Dynamic context 只用于恢复工作上下文；completion 仍需要 fresh receipts，外部副作用仍需要 fresh user authorization。

---

## 10. 建议的 v0.40 API 冻结清单

建议 v0.40 冻结以下核心 MCP API：

- `mission_lock`
- `mission_resume`
- `list_recent_receipts`
- `budget_status`
- `record_user_authorization`
- `authorization_status`
- `verify_receipt_integrity`
- `record_stuck_attempt`
- `record_decision_record`
- `record_counterexample_check`
- `turn_end_gate`
- `completion_gate`
- `export_handoff_packet`
- `mission_status`

以下保持 beta：

- `prompt_intake_gate`
- `register_subagent_start`
- `record_subagent_handoff`
- `register_subagent_stop`
- `subagent_status`
- Project Learning query/lint schema
- Dynamic Context JSONL CLI/schema

冻结前必须完成：

1. 为每个冻结 tool 提供 schema version。
2. 为每个冻结 tool 增加 compatibility tests。
3. 把 README Components table 反向生成或至少校验到 `API.md`。
4. 区分 runtime public API 与 release-only internal-maintenance API。

---

## 11. 当前 API 文档化结论

Agent-Runway 当前 API 已经覆盖任务监督主链路，但还缺少三个企业化前必须完成的 API 工程工作：

1. **Schema versioning**：mission、receipt、handoff、dynamic context、project learning record 都应有 schema version。
2. **Machine-readable OpenAPI-like spec**：即使不是 HTTP API，也应有 MCP tool schema JSON。
3. **Compatibility tests**：v0.40 后新增字段必须可选，删除/重命名必须走 deprecation。

只有完成这些，Agent-Runway 才能从“强工程化开源项目”升级为“可供团队依赖的平台组件”。

---

## 12. 本文件校验方法

### 12.1 校验 MCP tool inventory

```bash
python -c "import ast, pathlib; tree=ast.parse(pathlib.Path('mcp/server.py').read_text(encoding='utf-8')); print('\n'.join(node.name for node in tree.body if isinstance(node, ast.FunctionDef) and any(getattr(d, 'id', '') == '_runtime_tool' for d in node.decorator_list)))"
```

期望输出 19 个工具，与本文件第 0 节一致。

### 12.2 校验 release package boundary

```bash
python archive/release-tests/package_skill_check.py .
```

期望：内部 clean package 无 forbidden members；官方 packager 不存在时明确 unavailable，不能伪称已官方验证。

### 12.3 校验 Project Learning query 边界

```bash
python scripts/project_learning_query.py --json
python -B -m pytest mcp/tests/test_project_learning*.py -q
```

期望：缺失 ledger 是 warning + 空结果 + rc 0；malformed JSON 仍为 error + rc 2。

### 12.4 校验 Dynamic Context 边界

```bash
python -B -m pytest mcp/tests/test_dynamic_context.py -q
```

期望：记录包含 `mission_id/session_id/task_id`，缺失身份 lint 失败，单条 content 超过 `100000` bytes 失败，query 按 mission 过滤并遵守输出预算。

### 12.5 校验 release script direct execution

```bash
python archive/release-tests/adversarial_audit_suite.py .
python -m unittest discover -s archive/release-tests -p "test_release_scripts.py"
```

期望：release-only suite 不依赖外部 `PYTHONPATH`。
