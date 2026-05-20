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

<p align="center"><img src="agent-runway-cn.png" alt="Agent-Runway" width="900" /></p>

让 AI 朝目标推进，而不是透支你的信任。

`Agent-Runway` 是一套 AI 任务监督系统，面向那些在 AI 编码工具中反复输入"继续"的开发者——这类角色有个名字：Continue Engineer。它用任务定义、证据账本、预算约束和门控裁决取代 AI 的自我报告"做完了"，这是一套拒绝中途退出和虚假努力的审计机制。以 Skill 文件形式分发，通过 MCP 运行时进行结构化状态追踪，在 Claude Code 中还能实际拦截 Agent 未经批准的停止。

## 💪 能做什么

先看这一段能力概览；后面的“五个问题”表格再解释这些能力分别在解决什么。

| 能力 | 实际效果 |
|---|---|
| 🔒 任务锁定 | 目标、标准、范围、预算、证据计划 -> 成功标准必须明确，不能含糊过关 |
| ✍️ 签名证据 | 每个安装实例独立密钥散列签名 -> 可检查，不能靠说 |
| 🚪 完成门控 | 每条标准对应证据 -> 无法空喊完成 |
| 💰 预算纪律 | 切片/重试/时间 + 耗尽时 `wrap_up_guidance` -> 杜绝无限重试 |
| 🛡️ 旧证据守卫 | 文件编辑后必须重新验证 -> 防止"先改代码再用读文件洗白旧证据" |
| 🚫 空话拦截 | 15 个正则模式拒绝空话，例如"应该没问题""大概""我相信""似乎""看起来对"等 |
| 🔬 反例证伪 | `record_counterexample_check` -> 假设 + 反证尝试 + 残余风险 |
| 📝 决策追溯 | `record_decision_record` -> 选择 + 被拒替代 + 重新打开条件 |
| 🔐 授权边界 | 不可逆动作需记录、会校验是否存在仍然有效的用户审批 |
| 🔄 失败升级 | `record_stuck_attempt` -> 要求换思路才计数，耗尽规划次数预算后才可升级 |
| 📦 交接包 | 跨任意 Host 的全量 JSON 包 -> 连续性不靠隐藏记忆 |
| ⛔ 停止拦截 | Claude Code 中实际拦截停止（Stop hook）；Codex/OpenCode/Pi CLI 中为建议性质 |
| ⚠️ 危险命令拦截 | 10 类 + 秘密路径拒绝（跨平台变体匹配） |
| ⚖️ 价值门控 | 只有高影响、可验证、低扩张时才继续 |
| 🧠 项目经验记录（Project Learning Ledger） | 用可审查 JSONL 记录项目坑点、运行手册、偏好和长期约束；只提供建议，不是证据或授权 |
| 🧪 对抗审计门 | 对高风险完成声明进行有边界的证伪尝试；不构成 bug 不存在的证明 |

## 🎯 解决的五个问题

AI Agent 的失败模式很集中，主要是这五种：

| 问题 | 表现 | 解法 |
|---|---|---|
| 过早停止 | 做一步就等"继续" | 动作边界规则：下一步合法、可逆、可验证就不准停 |
| 空喊完成 | "修好了""应该过了"，全靠嘴 | 完成必须过门控，每条标准要有证据 |
| 伪勤奋 | 真正的工作完成后还继续润色、审计、扩展范围 | 价值门控：高影响、有证据缺口才继续 |
| 断上下文 | 跨轮丢失状态、决策、风险 | 交接包保留任务、证据、预算、决策、风险 |
| 越权操作 | 部署、推送、外部调用没经过授权 | 不可逆动作前记录授权，执行前校验时效 |

根源：AI 擅长美化结果，没人监督就会糊弄。

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

这不是提示词，是结构化状态：任务对象、证据账本、预算追踪、审批令牌、授权记录。Agent 读取，门控执行。任务刷新后旧证据自动失效，不能用来证明新任务完成。五个审核工具（轮次门控、完成门控、卡住记录、决策记录、反例检查）都强制执行这条规则。

## ⚙️ 运行模式

| 能力 | 📄 Skill 文件层 | 📄 Skill + ⚙️ MCP | 📄 Skill + ⚙️ MCP + 🧩 Host Assist | 📄 Skill + ⚙️ MCP + 🔒 Hooks |
|---|---|---|---|---|
| **运行内容** | Skill 文件 | Skill + MCP | Skill + MCP + 辅助 | Skill + MCP + Hooks |
| **任务锁定** | 规则 | ✅ | ✅ | ✅ |
| **证据账本** | ◽ | ✅ | ✅ | ✅ |
| **预算纪律** | 规则 | ✅ | ✅ | ✅ |
| **门控决策** | 建议 | ✅ | ✅ | ✅ |
| **授权记录** | ◽ | ✅ | ✅ | ✅ |
| **危险命令拦截** | ◽ | ◽ | 🟡 host-specific | ✅ |
| **拦截 Agent 提前停工** | ◽ | ◽ | ◽ | ✅ |
| **支持 Host** | Any Host | Codex、Cursor、VSCode | OpenCode、Pi CLI | Claude Code |

这里只写当前声明的最强模式；`🟡 host-specific` 表示这类额外拦截能力取决于具体 Host。

OpenCode 默认使用原生 MCP 配置。仓库里确实带着真正的桥接实现 `.opencode/plugins/agent-runway.js`，但 OpenCode 不会自动发现技能目录里的插件；它只会从项目 `.opencode/plugins/`、用户 `~/.config/opencode/plugins/`，或 Windows `%USERPROFILE%\.config\opencode\plugins\` 这类真实插件目录自动加载本地插件。如果你希望 OpenCode 的工具事件自动转发到证据账本，就要先在这些 OpenCode 插件目录里放一个 shim 或 symlink 去 re-export skill 插件，再设置 `ILH_OPENCODE_BRIDGE=1`。这样能改善证据捕获。

Pi CLI 支持范围更窄。`python scripts/generate_host_config.py --host pi-cli --project-dir <项目根目录>` 只输出 extension-only 说明，不输出原生 MCP 配置。拦截方式：编写 Pi 扩展脚本，通过 `pi.on("tool_call", ...)` 注册回调返回 `{ block: true, reason: "..." }` 来阻断危险工具调用，可参考 `scripts/fixtures/pi_block_extension.js`。已验证 `@mariozechner/pi-coding-agent@0.73.1` 的 `tool_call` handler 可阻断真实 `bash` 调用。

## 🔍 门控如何决策

门控分两层：先验证证据是否真的支撑当前声明，再判断下一步值不值得继续做。

### 验证深度

门控不是看一眼就放行，而是从多个角度卡住糊弄：

- **语义匹配。** 完成门控会分析每条标准的措辞。标准提到"测试""构建""代码检查"，就要求执行型证据（不能只给文件读取）。提到"编辑""写入""补丁"就要求变更型证据。拿读取类证据证明"测试通过"会被拒绝。
- **变更后证据。** 最后一次文件编辑后，如果没有在该序号或之后的验证证据覆盖同一标准，完成门控拒绝。防止拿改动前的旧证据充数。
- **空话拦截。** 总结里出现"应该没问题""大概""我感觉""看起来对""我相信""似乎修好了"，门控直接驳回——只认动作，不认感觉。
- **目标对齐提醒。** 每通过三次切片验证，系统自动提醒"请重新检查是否还在朝原目标推进"，防止不知不觉跑偏。
- **无效动作警告。** 如果本轮只提供了读取/搜索类证据而没有执行类证据，轮次门控会警告——只读不执行不构成推进。

### 价值门控

执行下一步前，先判断值不值得做。

| 检验项 | 问题 | 门槛 |
|---|---|---|
| 影响 | 影响正确性、安全、发布、安装、信任？ | 高 |
| 证据缺口 | 当前声明强于证据？ | 是 |
| 阻塞性 | 不做会留阻塞？ | 是 |
| 改动规模 | 有边界的小改动？ | 小 |
| 扩散风险 | 扩大运行时或接口面？ | 否 |
| 验证路径 | 有明确测试或审计？ | 是 |
| 停止条件 | 做完能明确停？ | 是 |

只有同时满足：影响高、存在证据缺口或真实阻塞、验证路径明确、扩展面小、停止条件清晰——才继续。否则收敛。以下五类应当收敛：措辞偏好与语气微调；没有对应高风险问题的接口扩展；仅改善评分但对安全性/安装/可验证性无实质帮助的优化；所有门控已通过且无新缺陷时继续做本地改动；无法说清收益和验证路径的工作。价值门控是规则不是工具——运行时已经管住了预算、证据、时效、授权和标准映射。另设对抗审计门用于高风险任务：由有边界的对抗角色以可执行反例尝试证伪完成声明，条件触发、非全局税，记忆不是证据，偏好不是授权。

## 🔧 失败处理和升级

任务受阻时，不能简单重试。`record_stuck_attempt` 只对实质不同的重试策略计数——用相同方式反复尝试不会被记录。重试预算耗尽后，触发卡住升级：需附带证据证明本地可尝试手段已穷尽。

## 🛠️ MCP 工具

| 工具 | 作用 |
|---|---|
| `mission_lock` | 锁定或刷新任务 |
| `mission_status` | 查看任务、门控时效、审批 |
| `budget_status` | 切片、重试、剩余时间 |
| `list_recent_receipts` | 列出证据 |
| `verify_receipt_integrity` | 验证证据签名 |
| `record_stuck_attempt` | 记录实质不同的失败策略 |
| `record_decision_record` | 记录重要可逆决策 |
| `record_counterexample_check` | 记录反证检查与风险 |
| `record_user_authorization` | 记录不可逆动作审批 |
| `authorization_status` | 检查授权时效 |
| `turn_end_gate` | 通过或拒绝本轮结束 |
| `completion_gate` | 通过证据映射审批完成 |
| `export_handoff_packet` | 导出交接包 |

## 📦 安装

### 让 AI 帮你安装

如果你正在使用 AI 工具，可以直接把下面这段话发给你当前的 AI 助手：

```text
帮我安装 Agent-Runway：

1. 前提：Python 3.11+
2. 克隆仓库：git clone https://github.com/Agent-Runway/Agent-Runway
3. 安装依赖：pip install mcp
4. 生成配置：python scripts/generate_host_config.py --host <当前 Host> --project-dir <仓库路径>
5. 把输出的 JSON 合并到当前 Host 真正使用的配置目标里：
   - Claude Code -> <仓库路径>/.claude/settings.json
   - OpenCode -> 你实际使用的 OpenCode 配置文件，例如 ~/.config/opencode/opencode.json、~/.config/opencode/config.json、%USERPROFILE%\.config\opencode\opencode.json、%USERPROFILE%\.config\opencode\config.json
   - Codex/Cursor -> 该 Host MCP 服务器配置里的 env 部分
   - Pi CLI -> extension-only 说明；不会生成原生 MCP 配置
6. 如果当前 Host 是 OpenCode，且我希望自动捕获工具事件证据，就创建 ~/.config/opencode/plugins/agent-runway.js（或 %USERPROFILE%\.config\opencode\plugins\agent-runway.js），内容是：export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
7. 如果你的 skill 安装在别处，就把这个 re-export 路径改成实际 skill 路径。优先用 shim 或 symlink；不要直接复制原始插件文件，除非你同时保留它到 scripts/opencode_plugin_bridge.py 的相对路径
8. 然后在生成的 OpenCode 配置或 Host 进程环境里把 ILH_OPENCODE_BRIDGE=1，并重启 OpenCode
9. 验证：python scripts/quick_validate.py <仓库路径>
```

### 手动安装

**前提：** Python 3.11+，从 GitHub 克隆仓库：`https://github.com/Agent-Runway/Agent-Runway`

```bash
pip install mcp
```

### 配置步骤

安装就是把配置 JSON 添加到你的 AI 工具配置文件里。

#### 1. 生成配置

运行命令生成配置 JSON（替换 `<项目根目录>` 为实际路径）：

**Claude Code：**
```bash
python scripts/generate_host_config.py --project-dir <项目根目录>
```

**OpenCode：**
```bash
python scripts/generate_host_config.py --host opencode --project-dir <项目根目录>
```

**Codex / Cursor：**
```bash
python scripts/generate_host_config.py --host <codex|cursor> --project-dir <项目根目录>
```

**Pi CLI：**
```bash
python scripts/generate_host_config.py --host pi-cli --project-dir <项目根目录>
```

Pi CLI 输出只是 extension-only 能力说明，不是原生 MCP 安装器。

#### 2. 复制配置到对应文件

**Claude Code：** 复制输出的 JSON，合并到项目根目录的 `.claude/settings.json`

**OpenCode：** 复制输出的 JSON，合并到你实际使用的 OpenCode 配置文件，例如 `~/.config/opencode/opencode.json`、`~/.config/opencode/config.json`、`%USERPROFILE%\.config\opencode\opencode.json`、`%USERPROFILE%\.config\opencode\config.json`，或其它 OpenCode 配置路径

#### 2a. 可选：启用 OpenCode 插件桥接

OpenCode 不会自动发现 skill 目录里的桥接文件。它只会从项目 `.opencode/plugins/`、用户 `~/.config/opencode/plugins/`，或 Windows `%USERPROFILE%\.config\opencode\plugins\` 自动加载插件。

先在真实的 OpenCode 插件目录里创建一个 shim，例如 `~/.config/opencode/plugins/agent-runway.js` 或 `%USERPROFILE%\.config\opencode\plugins\agent-runway.js`：

```js
export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
```

如果你的 skill 装在别处，就把这个 re-export 路径改成真实 skill 路径。优先用 shim 或 symlink。不要直接复制原始插件文件，除非你同时保留它到 `scripts/opencode_plugin_bridge.py` 的相对路径。

然后在 OpenCode 配置中设置 `ILH_OPENCODE_BRIDGE=1`。桥接按以下优先级确定该值：Host 进程环境变量 > OpenCode 配置内容 > 配置文件中发现的值。因此在生成配置的 `mcp.agent-runway.environment` 中保留 `ILH_OPENCODE_BRIDGE="1"` 是有效的启用方式（前提是 shim 已就位），显式设为 `"0"` 则保持桥接关闭。启用后，桥接还会将 `ILH_DB_PATH` 和 `ILH_SECRET_PATH` 传入 Python bridge 进程，并禁用 Python 字节码写入以避免项目本地状态/缓存漂移。仅需原生 MCP 和手动记录时保持 `"0"`。

**Codex：** 复制输出的 `env` 部分，添加到 Codex MCP 服务器配置的环境变量

**Cursor：** 复制输出的 `env` 部分，添加到 Cursor MCP 服务器配置的环境变量

#### 3. 验证安装

```bash
python scripts/quick_validate.py <项目根目录>
python -m unittest discover -s mcp/tests -p "test_*.py"
python scripts/smoke_test.py
```

如果本机有 Claude Code、OpenCode、Node 和 npm，可以复现 Host 级阻断证据：

```bash
python scripts/host_blocking_experiments.py
```

### 配置说明

**默认运行时文件位置：**
- 数据库：`.agent-runway/state.db`（项目根目录下）
- 密钥：Linux/macOS `~/.config/agent-runway/secret.key`，Windows `%USERPROFILE%\.config\agent-runway\secret.key`
- 覆盖方式：环境变量 `ILH_DB_PATH` / `ILH_SECRET_PATH`

**Windows 注意事项：**
- `--project-dir` 使用绝对路径；PowerShell 中已验证的写法是 `"$(Get-Location)"`
- `ILH_DB_PATH` 放在有写权限的项目目录下；运行时会自动创建 `.agent-runway`
- 如果自定义 `ILH_SECRET_PATH`，把它放在仓库外并避免同步。运行时会尝试用 `icacls` 收紧 Windows ACL；如果失败，会输出明确警告，不会假装密钥已被锁定

## 📂 项目文件

```text
.
├── SKILL.md                         # 项目准则
├── README*.md                       # 多语言文档
├── mcp/
│   ├── server.py                    # 运行时
│   ├── agent_runway_runtime/
│   │   └── store.py                 # 状态与证据账本
│   └── tests/                       # 测试
├── scripts/
│   ├── generate_host_config.py      # Host 配置
│   ├── quick_validate.py            # 结构校验
│   ├── package_skill_check.py       # 打包校验
│   ├── release_gate.py              # 十六道发布门
│   ├── release_static_checks.py     # 静态检查
│   ├── project_learning_lint.py     # 项目经验记录校验
│   ├── project_learning_query.py    # 受限的建议性账本查询
│   └── host_blocking_experiments.py # 可复现 Host 阻断实验
├── .opencode/
│   └── plugins/                     # 可选 OpenCode 插件桥接
└── references/                      # 架构、Host、预算、证据、一致性、发布、项目经验记录
```

## ⚠️ 边界

- 无 hooks 时，停止强制执行仅为建议性质
- 证据只证明执行行为发生过，不单独证明语义正确性
- 访问密钥或数据库会降低证据可信度
- 启用 Host Hooks 后，跨路径变体的密钥读取会被拒绝
- 启用 Host Hooks 后，危险命令会在执行前触发确认
- 启用 Host Hooks 后，门控批准后的任何新证据会使该批准过时，Stop 需要重新通过门控裁决
- OpenCode 的 ask 机制是 fail-closed（默认拒绝），不是原生的确认对话框
- Pi CLI 支持仅限扩展层：已验证 tool_call 阻断能力，但不具备原生 MCP 或 Stop hook 同等级别
- Codex、Cursor 在当前仓库为 MCP 接入路径
- 项目经验记录只提供建议性上下文：记忆不是证据，偏好不是授权

## ✍️ 署名

- 发布者：babutree
- 协作者：Codex

## 🙏 致谢

感谢真诚、友善、团结、专业的 Linux.do 社区。<a href="https://linux.do" target="_blank" rel="noopener noreferrer"><img src="https://camo.githubusercontent.com/36a8066e13b53b968451a780de4cd6a432adeb175522afe7a080562e4f4e2534/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f4c696e7578446f2d636f6d6d756e6974792d316636666562" alt="LinuxDo" /></a>

## 📄 许可

MIT。
