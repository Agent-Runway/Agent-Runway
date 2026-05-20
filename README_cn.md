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

<p align="center"><img src="agent-runway-cn.png" alt="Agent-Runway" width="900" /></p>

让 AI 朝目标推进，而不是透支你的信任。

`Agent-Runway` 面向那些在 AI 编码工具里反复敲"继续"的开发者——Continue Engineer。它用任务定义、证据账本、预算约束和门控裁决，替代 AI 那句自我报告的"我做完了"——一套拒绝中途放弃和虚假努力的审计机制。以 Skill 文件分发，通过 MCP 运行时进行结构化状态追踪；只有 Claude Code 的 `Stop` hook 配置并生效后，才能物理阻断 Agent 未经门控批准就停工。

## 💪 能做什么

先看能力概览；紧接的“五个问题”表格会说明每项能力各自解决什么。

| 能力 | 实际效果 |
|---|---|
| 🔒 任务锁定 | 目标、标准、范围、预算、证据计划 -> 成功标准必须明确，不能含糊过关 |
| ✍️ 签名证据 | 每个安装实例独立密钥散列签名 -> 可检查，不能靠说 |
| 🚪 完成门控 | fresh approved `turn_end_gate` + 每条标准对应其覆盖过的证据 -> 无法空喊完成 |
| 💰 预算纪律 | 切片/重试/时间 + 耗尽时 `wrap_up_guidance` -> 杜绝无限重试 |
| 🛡️ 旧证据守卫 | 文件编辑后须重新验证 -> 防止"先改代码再用只读洗白旧证据" |
| 🚫 空话拒绝 | `turn_end_gate` / `completion_gate` 的总结中，多语言正则拒绝含糊措辞，如"应该没问题""大概没问题""我觉得这次能过""看起来对了"等 |
| 🔬 反例证伪 | `record_counterexample_check` -> 假设 + 反证尝试 + 结果 + 残余风险 |
| 📝 决策追溯 | `record_decision_record` -> 选择 + 被否决方案 + 重开条件 |
| 🔐 授权边界 | 不可逆动作需记录并校验用户审批是否仍有效；已授权的命令不重复询问 |
| 🔄 失败升级 | `record_stuck_attempt` -> 只统计换思路的尝试；重试预算耗尽后方可升级 |
| 📦 交接包 | 跨任意 Host 的全量 JSON 包 -> 连续性不靠隐藏记忆 |
| ⛔ 停止强制执行 | 仅配置了 Claude Code `Stop` hook 时可物理阻断停工；MCP-only、OpenCode、Pi CLI、Codex、Cursor 路径均无同级 Stop hook |
| ⚠️ 风险事件拦截 | Claude hooks 可询问或拒绝高风险 shell 命令和受保护路径读取；OpenCode bridge 启用后 fail-closed 拒绝；Pi CLI 仅限扩展级 `tool_call` 阻断 |
| ⚖️ 价值门控 | 只有高影响、可验证、低扩张时才继续 |
| 🧠 项目经验记录（Project Learning Ledger） | 用项目本地 `.agent-runway` JSONL 记踩过的坑、操作手册、偏好和不变量；仅供参考，不充当证据或授权 |
| 🧪 对抗审计门 | 对高风险完成声明做有界证伪；不能证明"bug 不存在" |

## 🎯 解决的五个问题

AI Agent 失败模式很集中，主要是这五种：

| 问题 | 表现 | 解法 |
|---|---|---|
| 过早停止 | 做一步就等"继续" | 动作边界规则：下一步合法、可逆、可验证就不准停 |
| 空喊完成 | "修好了""应该过了"，没有证据 | 完成必须过门控，每条标准须对应证据 |
| 伪勤奋 | 真正的工作完成后还在润色、审计、扩展范围 | 价值门控：仅高影响且存在证据缺口时才继续 |
| 断上下文 | 跨轮丢失状态、决策、风险 | 交接包携带任务、证据、预算、决策、风险 |
| 越权操作 | 部署、推送、外部调用没经授权 | 不可逆动作前须记录授权，执行前校验时效；已授权的不重复询问，超出范围的仍需授权 |

根源问题：Agent 天然擅长把结果说得像模像样，但没有人监督。

## ⚙️ 怎么工作

```
锁定任务 → 执行切片 → 留下证据 → 轮次门控 → 循环 → 完成门控 → 交接
```

每一步产生具体的运行时产物：

| 步骤 | 职责 | 产物 |
|---|---|---|
| 锁定任务 | 写入目标、标准、范围边界、预算、红线、证据计划 | 任务记录 |
| 执行切片 | 完成一个具体、可逆、与任务对齐的工作单元 | 工具活动 |
| 留下证据 | 记录实际结果：命令、退出码、哈希值、差异 | 签名证据 |
| 轮次门控 | 检查停止合法性和证据时效 | 通过或拒绝 |
| 完成门控 | 验证每条标准都有证据支撑 | 标准-证据对照判定 |
| 交接 | 打包任务、证据、预算、风险给下一轮 | 交接包 |

这不是一段要求提供证据的提示词，而是一套结构化状态——任务对象、证据账本、预算追踪器、审批令牌、授权记录——Agent 读取，门控强制执行。任务刷新后旧证据自动失效，不能用于新的完成判定。五个门控工具（轮次门控、完成门控、卡住记录、决策记录、反例检查）统一执行此规则。

## ⚙️ 运行模式

| 能力 | 📄 Skill 文件层 | 📄 Skill + ⚙️ MCP | 📄 Skill + ⚙️ MCP + 🧩 Host Assist | 📄 Skill + ⚙️ MCP + 🔒 Hooks |
|---|---|---|---|---|
| **运行内容** | Skill 文件 | Skill + MCP | Skill + MCP + 辅助 | Skill + MCP + Hooks |
| **任务锁定** | 规则 | ✅ | ✅ | ✅ |
| **证据账本** | ◽ | ✅ | ✅ | ✅ |
| **预算纪律** | 规则 | ✅ | ✅ | ✅ |
| **门控决策** | 建议 | ✅ | ✅ | ✅ |
| **授权记录** | ◽ | ✅ | ✅ | ✅ |
| **风险事件拦截** | ◽ | ◽ | 🟡 host-specific | ✅ |
| **停止强制执行** | ◽ | ◽ | ◽ | ✅ |
| **支持 Host** | Any Host | Codex、Cursor、VSCode | OpenCode、Pi CLI | Claude Code |

上表仅列出当前各 Host 声明的最强模式；`🟡 host-specific` 表示额外拦截能力取决于 Host。

OpenCode 默认走原生 MCP 配置。仓库内含桥接实现 `.opencode/plugins/agent-runway.js`，但 OpenCode 不会自动发现 skill 目录里的插件；它只从项目 `.opencode/plugins/`、用户 `~/.config/opencode/plugins/` 或 Windows `%USERPROFILE%\.config\opencode\plugins\` 自动加载本地插件。想让 OpenCode 工具事件自动转发到证据账本，就在上述插件目录放一个 shim 或 symlink re-export skill 插件，再设 `ILH_OPENCODE_BRIDGE=1`，即可改善证据捕获。

Pi CLI 支持范围更窄。`python scripts/generate_host_config.py --host pi-cli --agent-runway-dir <agent-runway-dir>` 只输出 extension-only 说明，不输出原生 MCP 配置。拦截方式：写一个 Pi 扩展脚本，通过 `pi.on("tool_call", ...)` 注册回调并返回 `{ block: true, reason: "..." }` 阻断危险工具调用；参见 `scripts/fixtures/pi_block_extension.js` 模板。已在 `@mariozechner/pi-coding-agent@0.73.1` 上验证 `tool_call` handler 可阻断真实 `bash` 调用。

## 🔍 门控如何决策

门控分两层：先验证证据是否支撑当前声明，再判断下一步是否值得继续。

### 验证深度

门控不是看一眼就放行，而是多角度卡住糊弄：

- **语义匹配。** 完成门控分析每条标准的措辞——"测试通过""构建成功"要求执行型证据（只读不算），"编辑""写入""打补丁"要求变更型证据。拿只读类证据证明"测试通过"会被拒绝。
- **轮次门控绑定。** 完成前必须有 fresh approved `turn_end_gate`；完成时每条证据都必须被最新轮次门控覆盖，防止 Agent 跳过停止合法性或在完成时换用未审查证据。
- **变更后证据。** 最后一次文件编辑后，若没有在该序号或之后的验证证据覆盖同一标准，完成门控拒绝。防止拿改动前的旧证据充数。
- **空话拒绝。** `turn_end_gate` 检查 `work_summary`，`completion_gate` 检查 `completion_summary`；出现含糊措辞——如"应该没问题""大概没问题""我觉得这次能过""看起来对了"——门控即拒绝。
- **目标对齐提醒。** 每通过三次切片验证，系统提醒检查当前方向是否仍与任务目标一致，防止不知不觉跑偏。
- **纯观察警告。** 若本轮只有 Read/Glob/Grep 等观察类证据而无执行类证据，轮次门控会警告——只读不算推进。

### 价值门控

执行下一步前，先判断值不值得做。

| 检验项 | 问题 | 门槛 |
|---|---|---|
| 影响 | 影响正确性、安全、发布、安装、信任？ | 高 |
| 证据缺口 | 当前声明强于证据？ | 是 |
| 阻塞性 | 不做会留阻塞？ | 是 |
| 改动规模 | 有边界的小改动？ | 小 |
| 扩散风险 | 会扩大运行时或 API 接口面？ | 否 |
| 验证路径 | 有明确测试或审计？ | 是 |
| 停止条件 | 做完能明确停？ | 是 |

只有同时满足——影响高、存在证据缺口或真实阻塞、验证路径明确、扩展面小、停止条件清晰——才继续。否则收敛。以下五类应收敛：措辞偏好与语气微调；没有对应高风险问题的接口扩展；仅改善评分但对安全性/安装/可验证性无实质帮助的优化；门控已通过且无新缺陷时还做本地改动；无法说清收益和验证路径的工作。价值门控是规则不是工具——运行时已经管住了预算、证据、时效、授权和标准映射。另设对抗审计门用于高风险任务：由受限对抗角色以可执行反例证伪完成声明，条件触发、非全局征收。

记忆不是证据，偏好不是授权。

## 🔧 失败处理和升级

任务受阻时不能简单重试。`record_stuck_attempt` 只统计实质不同的重试策略——用相同方式反复尝试不计入。重试预算耗尽后触发卡住升级：须附带证据证明本地可尝试手段已穷尽。

## 🛠️ MCP 工具

| 工具 | 作用 |
|---|---|
| `mission_lock` | 锁定或刷新任务 |
| `mission_resume` | 恢复活跃任务并刷新 Host 会话绑定 |
| `mission_status` | 查看任务、门控时效、审批 |
| `budget_status` | 切片、重试、剩余时间 |
| `list_recent_receipts` | 列出证据 |
| `verify_receipt_integrity` | 验证证据签名 |
| `record_stuck_attempt` | 记录实质不同的失败策略 |
| `record_decision_record` | 记录有后果的可逆决策 |
| `record_counterexample_check` | 记录反证检查、观察结果与风险 |
| `record_user_authorization` | 记录不可逆动作的用户审批 |
| `authorization_status` | 检查授权时效 |
| `turn_end_gate` | 通过或拒绝本轮结束 |
| `completion_gate` | 证据映射审批完成或拒绝 |
| `export_handoff_packet` | 导出交接包 |

## 📦 安装

### 让 AI 帮你安装

如果你正在使用 AI 工具，可以直接把下面这段话发给你当前的 AI 助手：

```text
帮我安装 Agent-Runway：

1. 前提：Python 3.11+
2. 把 Agent-Runway 克隆到当前 CLI/Host 会加载的 skills 目录：git clone https://github.com/Agent-Runway/Agent-Runway <cli-skills-dir>/agent-runway
3. 安装依赖：pip install mcp
4. 生成配置：python scripts/generate_host_config.py --agent-runway-dir <agent-runway-dir>
   如果当前 Host 不是 Claude Code，只需加 --host opencode、--host codex、--host cursor 或 --host pi-cli。
5. 把输出的 JSON 合并到当前 Host 真正使用的配置目标里：
   - Claude Code -> 当前 Claude Code workspace 或 Host 配置实际使用的 .claude/settings.json
   - OpenCode -> 你实际使用的 OpenCode 配置文件，例如 ~/.config/opencode/opencode.json、~/.config/opencode/config.json、%USERPROFILE%\.config\opencode\opencode.json、%USERPROFILE%\.config\opencode\config.json
   - Codex/Cursor -> 该 Host MCP 服务器配置里的 env 部分
   - Pi CLI -> extension-only 说明；不会生成原生 MCP 配置
6. 如果当前 Host 是 OpenCode，且我希望自动捕获工具事件证据，就创建 ~/.config/opencode/plugins/agent-runway.js（或 %USERPROFILE%\.config\opencode\plugins\agent-runway.js），内容是：export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
7. 如果你的 skill 安装在别处，就把这个 re-export 路径改成实际 skill 路径。优先用 shim 或 symlink；不要直接复制原始插件文件，除非你同时保留它到 scripts/opencode_plugin_bridge.py 的相对路径
8. 然后在生成的 OpenCode 配置或 Host 进程环境里把 ILH_OPENCODE_BRIDGE=1，并重启 OpenCode
9. 验证：python scripts/quick_validate.py <agent-runway-dir>
```

### 手动安装

**前提：** Python 3.11+。把 Agent-Runway 克隆到当前 CLI 或 AI Host 会加载的 skills 目录：`git clone https://github.com/Agent-Runway/Agent-Runway <cli-skills-dir>/agent-runway`。这个克隆出来的目录就是 `<agent-runway-dir>`，内含 `SKILL.md`、`scripts/` 和 `mcp/`；不是 Host 配置文件目录。

```bash
pip install mcp
```

### 配置步骤

安装就是把配置 JSON 添进 AI 工具配置文件。

#### 1. 生成配置

在 `<agent-runway-dir>` 里运行默认命令生成配置 JSON。不指定 `--host` 则生成 Claude Code 配置。

```bash
python scripts/generate_host_config.py --agent-runway-dir <agent-runway-dir>
```

OpenCode、Codex、Cursor 或 Pi CLI 用同一命令，在 `--agent-runway-dir` 前加 `--host opencode`、`--host codex`、`--host cursor` 或 `--host pi-cli`。

Pi CLI 输出只是 extension-only 能力说明，不是原生 MCP 安装器。

#### 2. 复制配置到对应文件

**Claude Code：** 复制输出的 JSON，合并到 Claude Code workspace 或 Host 配置实际用的 `.claude/settings.json`

**OpenCode：** 复制输出的 JSON，合并到你实际用的 OpenCode 配置文件，如 `~/.config/opencode/opencode.json`、`~/.config/opencode/config.json`、`%USERPROFILE%\.config\opencode\opencode.json`、`%USERPROFILE%\.config\opencode\config.json`，或其它 OpenCode 配置路径

#### 2a. 可选：启用 OpenCode 插件桥接

OpenCode 不会自动发现 skill 目录里的桥接文件。它只从项目 `.opencode/plugins/`、用户 `~/.config/opencode/plugins/` 或 Windows `%USERPROFILE%\.config\opencode\plugins\` 自动加载插件。

在真实 OpenCode 插件目录里创建一个 shim，如 `~/.config/opencode/plugins/agent-runway.js` 或 `%USERPROFILE%\.config\opencode\plugins\agent-runway.js`：

```js
export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
```

skill 装在别处就把 re-export 路径改成实际 skill 路径。优先用 shim 或 symlink。不要直接复制原始插件文件，除非同时保留它到 `scripts/opencode_plugin_bridge.py` 的相对路径。

然后在 OpenCode 配置中设 `ILH_OPENCODE_BRIDGE=1`。桥接按此优先级取值：Host 进程环境变量 > OpenCode 配置内容 > 配置文件发现的值。因此生成配置的 `mcp.agent-runway.environment` 中保留 `ILH_OPENCODE_BRIDGE="1"` 就是有效启用方式（shim 已就位为前提），显式设 `"0"` 保持关闭。除非你有意为当前项目指定状态文件，否则 `ILH_DB_PATH` 不设；桥接默认用事件项目目录下的 `.agent-runway/state.db`。桥接仍会传递 `ILH_SECRET_PATH` 等已配置环境值，并禁用 Python 字节码写入以避免项目本地状态/缓存漂移。仅需原生 MCP 和手动记录时保持 bridge 为 `"0"`。

**Codex：** 复制输出的 `env` 部分，添加到 Codex MCP 服务器配置的环境变量

**Cursor：** 复制输出的 `env` 部分，添加到 Cursor MCP 服务器配置的环境变量

#### 3. 验证安装

```bash
python scripts/quick_validate.py <agent-runway-dir>
python -B -m pytest mcp/tests -q
python scripts/smoke_test.py
```

如果本机有 Claude Code、OpenCode、Node 和 npm，可以复现 Host 级阻断行为：

```bash
python scripts/host_blocking_experiments.py
```

### 配置说明

**默认运行时文件位置：**
- 数据库：活动项目目录下的 `.agent-runway/state.db`。不要把 skill 安装目录当多个项目共享的默认数据库。
- 密钥：Linux/macOS `~/.config/agent-runway/secret.key`，Windows `%USERPROFILE%\.config\agent-runway\secret.key`
- 覆盖方式：环境变量 `ILH_DB_PATH` / `ILH_SECRET_PATH`

**Windows 注意事项：**
- `--agent-runway-dir` 须用绝对路径；在 Agent-Runway skill 目录内，PowerShell 已验证的写法是 `"$(Get-Location)"`
- 常规项目本地使用时 `ILH_DB_PATH` 不设。只有明确要为某个项目指定状态文件时才设它；运行时会自动创建 `.agent-runway`
- 自定义 `ILH_SECRET_PATH` 时放在仓库外并避免同步。运行时会尝试用 `icacls` 收紧 Windows ACL；若失败则输出明确警告，不会假装密钥已锁好

## 📂 项目文件

```text
.
├── SKILL.md                         # 项目准则
├── README*.md                       # 多语言文档
├── mcp/
│   ├── server.py                    # 运行时
│   ├── agent_runway_runtime/
│   │   └── store.py                 # 状态与证据账本
│   └── tests/                       # 运行时与适配器测试
├── scripts/
│   ├── generate_host_config.py      # Host 配置
│   ├── quick_validate.py            # 结构校验
│   ├── smoke_test.py                # 运行时冒烟测试
│   ├── project_learning_lint.py     # 项目经验记录校验
│   ├── project_learning_query.py    # 有限查询项目经验；仅供参考，不作证据或授权
│   ├── context_recovery.py          # SQLite 优先的断点恢复
│   ├── dynamic_context.py           # 按 mission 限界的上下文 JSONL
│   ├── adversarial_audit_lint.py    # 审计记录校验
│   └── host_blocking_experiments.py # 可复现的 Host 阻断实验
├── .opencode/
│   └── plugins/                     # 可选 OpenCode 插件桥接
└── references/                      # 架构、Host、预算、证据、一致性、项目经验
```

## ⚠️ 边界

- 没配 Claude Code `Stop` hook 时，停止强制执行仅为建议
- 证据只证明执行行为发生过，不单独证明语义正确
- 访问密钥或数据库会降低证据可信度
- 启用 Claude Code hooks 后，跨路径变体的密钥读取会被拒绝
- 启用 Claude Code hooks 后，危险命令会在执行前触发确认
- 启用 Claude Code hooks 后，门控批准后产生的任何新证据会使该批准失效，Stop 须重新过门控
- 启用可选 OpenCode bridge 后，`ask` 决策 fail-closed 拒绝工具事件；这不是原生确认对话框或 Stop hook
- Pi CLI 仅限扩展层：已验证 tool_call 阻断，不具备原生 MCP 或 Stop hook 对等能力
- Codex 和 Cursor 在本仓库中走 MCP 接入路径
- 项目经验记录仅限当前项目：数据放在该项目被忽略的 `.agent-runway/` 下；记忆不是证据，偏好不是授权
- 动态上下文仅限当前项目：`.agent-runway/dynamic-context.jsonl` 须保持被忽略、按 mission 限界、单条不超过 100k bytes，且不充当证据或授权

## 📄 许可

MIT。
