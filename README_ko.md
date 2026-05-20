# Agent-Runway

[![Version](https://img.shields.io/badge/version-v0.35-blue)](../../issues)
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

AI 가 신뢰를 소모하는 대신 목표를 향해 계속 전진하도록 만드세요.

`Agent-Runway` 는 AI 코딩 도구가 작업 중간에 멈추고, 개발자가 계속해서 "continue" 를 입력해야 하는 상황을 위한 시스템입니다. 이런 역할에는 이름이 있습니다. Continue Engineer 입니다. 이 프로젝트는 스스로 "I'm done" 이라고 말하는 방식을 mission, receipt ledger, budget, gate 로 대체합니다. 즉, 작업 중도 이탈과 가짜 노력을 거부하는 감사 메커니즘입니다. skill 파일로 배포되며, 구조화된 state 추적을 위해 MCP runtime 과 함께 동작하고, Claude Code 에서는 승인 없이 멈추는 것을 물리적으로 막을 수 있습니다.

## 💪 할 수 있는 일

먼저 이 섹션을 기능 요약으로 읽으세요. 바로 다음의 "다섯 가지 문제" 표는 각 요소가 왜 필요한지 설명합니다.

| 기능 | 실제 효과 |
|---|---|
| 🔒 Mission locking | 목표, 기준, 범위, budget, evidence map 을 고정 -> 모호한 성공 방지 |
| ✍️ Signed receipts | 설치 단위 HMAC 서명 -> 수사적 주장 대신 점검 가능 |
| 🚪 Completion gate | 모든 기준을 receipts 에 매핑 -> 근거 없는 "done" 방지 |
| 💰 Budget discipline | slice/retry/time + 소진 시 `wrap_up_guidance` -> 끝없는 retry 극장 방지 |
| 🛡️ Stale-evidence guard | 파일 수정 후 재검증 필수 -> "edit then read" 로 낡은 evidence 세탁 방지 |
| 🚫 Assertion blocking | 9개의 regex 패턴으로 "should work" / "probably" / "I believe" 거부 |
| 🔬 Counterexample | `record_counterexample_check` -> 가설 + 반증 점검 + 잔여 위험 |
| 📝 Decision records | `record_decision_record` -> 선택 + 기각한 대안 + 재오픈 조건 |
| 🔐 Authorization | 되돌릴 수 없는 작업에는 기록되어 있고 아직 유효한 사용자 승인이 필요 |
| 🔄 Failure escalation | `record_stuck_attempt` -> materially different 한 전략만 인정, retry budget 소진 후 escalation |
| 📦 Handoff packet | 어떤 host 에서도 통하는 전체 JSON 패킷 -> 숨은 기억 없는 연속성 |
| ⛔ Stop enforcement | Claude Code 에서는 Stop hook 기반 물리적 차단, Codex/OpenCode 에서는 advisory |
| ⚠️ Dangerous command interception | 10개 분류 + 크로스플랫폼 경로 변형까지 잡는 secret path 차단 |
| ⚖️ Value Gate | impact 가 높고 검증 가능하며 expansion 이 낮을 때만 계속 진행 |
| 🧠 Project Learning Ledger | 프로젝트의 pitfalls, runbooks, preferences, invariants 를 담는 검토 가능한 JSONL. advisory 전용이며 evidence 나 authorization 은 아님 |

## 🎯 해결하는 다섯 가지 문제

agent 는 예측 가능한 몇 가지 방식으로 실패합니다. 여기서는 그중 중요한 다섯 가지와, 이 프로젝트가 각각을 어떻게 다루는지 설명합니다.

| 문제 | 어떤 일이 일어나는가 | 어떻게 해결하는가 |
|---|---|---|
| 너무 일찍 멈춘다 | 한 가지를 하고 멈춘 뒤 "continue" 를 기다린다 | Action frontier rule: 다음 단계가 여전히 mission 에 맞고, 가역적이며, 검증 가능하면 계속 진행 |
| 확신에 차서 틀린다 | 증거 없이 "fixed" 또는 "should pass" 라고 말한다 | 완료에는 criterion-to-receipt mapping 이 있는 gate 가 필요 |
| 끝없이 다듬는다 | 실제 일이 끝난 뒤에도 edit, audit, scope 확장을 계속한다 | Value Gate: impact 가 높고 evidence gap 이 있을 때만 계속 |
| 맥락을 잃는다 | turn 사이에서 state 가 흔들린다 | handoff packet 이 mission, evidence, budget, decision, risk 를 다음 turn 으로 전달 |
| 권한을 넘는다 | 지속 가능한 승인 없이 deploy, push, 외부 호출을 수행한다 | irreversible action 전에 authorization record 가 아직 유효한지 확인 |

근본 문제는 agent 가 결과를 그럴듯하게 보이게 만드는 데는 능하지만, 그 과정을 감독하는 장치가 없다는 점입니다.

## ⚙️ 동작 방식

```text
mission_lock -> bounded slice -> receipt -> turn_end_gate -> repeat -> completion_gate -> handoff
```

각 단계는 구체적인 runtime artifact 를 생성합니다.

| 단계 | 역할 | 산출물 |
|---|---|---|
| Lock mission | 목표, 기준, 범위, budget, red line, evidence plan 정의 | mission record |
| Execute slice | mission 에 맞는 구체적이고 가역적인 작업 단위 수행 | tool activity |
| Capture receipt | 무슨 일이 있었는지 기록: command, exit code, hash, diff | signed receipt |
| Turn gate | turn 을 끝내기 전에 stop 의 합법성과 receipt 의 유효성 확인 | 승인 또는 거부 |
| Completion gate | 모든 기준이 receipts 로 뒷받침되는지 확인 | criterion-to-receipt decision |
| Handoff | 다음 turn 을 위해 mission, evidence, budget, risk 를 묶음 | handoff packet |

이것은 단순히 evidence 를 "요구하는" prompt 가 아닙니다. mission object, receipt ledger, budget tracker, approval token, authorization record 로 이루어진 구조화된 state 입니다. agent 가 이것을 읽고, gate 가 그것을 강제합니다. mission 이 갱신되면 오래된 receipts 는 무효화되며 새로운 completion decision 에 사용할 수 없습니다. 다섯 가지 gate tool(turn gate, completion gate, stuck attempt, decision record, counterexample)은 이 규칙을 일관되게 적용합니다.

## ⚙️ Runtime modes

| 기능 | 📄 Skill 파일층 | 📄 Skill + ⚙️ MCP | 📄 Skill + ⚙️ MCP + 🧩 Host Assist | 📄 Skill + ⚙️ MCP + 🔒 Hooks |
|---|---|---|---|---|
| **실행되는 것** | Skill 파일 | Skill + MCP | Skill + MCP + 보조 | Skill + MCP + Hooks |
| **Mission lock** | 규칙 | ✅ | ✅ | ✅ |
| **Receipt ledger** | ◽ | ✅ | ✅ | ✅ |
| **Budget discipline** | 규칙 | ✅ | ✅ | ✅ |
| **Gate decisions** | Advisory | ✅ | ✅ | ✅ |
| **Authorization records** | ◽ | ✅ | ✅ | ✅ |
| **Dangerous command interception** | ◽ | ◽ | 🟡 host-specific | ✅ |
| **Stop enforcement** | ◽ | ◽ | ◽ | ✅ |
| **지원 Host** | Any Host | Codex, Cursor, VSCode | OpenCode, Pi CLI | Claude Code |

현재 각 Host 에 대해 주장하는 가장 강한 모드만 보여줍니다. `🟡 host-specific` 은 그 추가 차단이 Host 에 따라 달라진다는 뜻입니다.

OpenCode 는 기본적으로 native MCP configuration 을 사용합니다. 이 저장소에는 `.opencode/plugins/agent-runway.js` 에 실제 bridge 구현이 들어 있지만, OpenCode 는 skill directory 안의 plugin 을 자동으로 찾지 않습니다. 로컬 plugin 을 자동으로 로드하는 위치는 project 의 `.opencode/plugins/`, 사용자 `~/.config/opencode/plugins/`, 그리고 Windows 의 `%USERPROFILE%\.config\opencode\plugins\` 뿐입니다. OpenCode 의 tool events 를 자동으로 receipt ledger 로 보내고 싶다면, 이들 OpenCode plugin 위치 중 하나에 `shim` 또는 `symlink` 를 두어 skill plugin 을 다시 export 하게 만든 다음 `ILH_OPENCODE_BRIDGE=1` 을 설정해야 합니다. 이렇게 하면 receipt capture 는 좋아집니다.

## 🔍 gate 는 어떻게 판단하는가

gate 는 두 층으로 작동합니다. 먼저 evidence 가 해당 claim 을 실제로 뒷받침하는지 확인하고, 그다음 다음 단계가 계속할 가치가 있는지를 판단합니다.

### 검증 깊이

gate 는 단순히 훑어보는 수준에 그치지 않고, 여러 단계에서 얼버무림을 잡아냅니다.

- **의미 일치 검증.** completion gate 는 각 criterion 의 표현을 분석합니다. "Tests pass" 또는 "build succeeds" 라면 execution receipts 가 필요하며, Read receipt 만으로는 부족합니다. "Edit" 나 "patch" 라면 mutation receipts 가 필요합니다. criterion 의 의도와 제공된 evidence type 이 맞지 않으면 gate 가 거부합니다.
- **수정 이후 evidence 요구.** 마지막 파일 수정 이후 해당 criterion 을 뒷받침하는 verification receipt 가 그 sequence 이상에서 존재하지 않으면 completion gate 는 이를 거부합니다. 마지막 변경 이전의 receipts 로 "tests pass" 를 주장할 수 없습니다.
- **단정적 표현 거부.** work summary 나 completion summary 에 "should work", "probably", "I believe", "seems to", "appears to", "looks correct", "I'm confident", "it works" 가 들어가면 gate 가 자동으로 거부합니다. 구체적인 행동 언어가 필요합니다.
- **목표 정렬 체크포인트.** 승인된 slice 가 세 번 누적될 때마다 `goal_alignment_check_due` 알림이 발생합니다. 여전히 mission 이 요구하는 방향으로 가고 있는지 확인하기 위함입니다.
- **관찰-only 경고.** Read/Glob/Grep receipts 만 있고 execution 이 없는 turn 이면, turn gate 는 읽기만으로는 진전이 아니라고 경고합니다.

### Value Gate

다음 단계를 밟기 전에, 그 단계가 여전히 가치가 있는지 판단하세요.

| 점검 항목 | 질문 | 기준 |
|---|---|---|
| Impact | 정확성, 보안, release, 설치, 신뢰에 영향을 주는가 | 높음 |
| Evidence gap | 지금의 주장이 현재 증거보다 강한가 | 예 |
| Blocker | 이걸 건너뛰면 실제 blocker 가 남는가 | 예 |
| Size | bounded change 인가 | 작음 |
| Expansion | runtime/API surface 를 넓히는가 | 아니오 |
| Verification | 명확한 test 또는 audit 이 있는가 | 예 |
| Stop | 언제 멈춰야 하는지가 분명한가 | 예 |

impact 가 높고, evidence gap 또는 real blocker 가 있으며, verification 이 명확하고, expansion 이 낮고, stop 조건이 명확할 때만 계속하세요. 그렇지 않으면 거기서 수습하고 마무리해야 합니다.

다음과 같은 다섯 가지 작업 유형은 계속하기보다 수습하고 마무리해야 합니다. 문구나 톤의 선호 조정, 이에 상응하는 고위험 문제가 없는 API/runtime/host surface 확장, 안전성·설치성·검증성을 개선하지 않고 presentation 이나 score 만 좋아지는 최적화, gate 와 targeted check 가 이미 통과했고 새로운 재현 가능한 defect 도 없는 상태에서의 추가 local change, 그리고 가치·verification path·stop condition 을 정확히 설명할 수 없는 다음 단계입니다.

Value Gate 는 tool 이 아니라 rule 입니다. v0.35 에서 이렇게 설계한 이유는 runtime 이 이미 budget, receipts, freshness, authorization, criterion mapping 을 관리하고 있기 때문입니다.

## 🔧 실패 처리와 escalation

막혔을 때 retry 는 materially different 해야 합니다. `record_stuck_attempt` 는 접근법이 실제로 바뀐 경우만 세며, 같은 길을 반복하는 것은 count 하지 않습니다. retry budget 이 소진되면 `stuck_escalation` 이 트리거됩니다. 이때는 로컬 옵션이 소진되었다는 evidence 와 함께 에스컬레이션해야지, 단순히 "아직도 실패한다" 로 끝나면 안 됩니다.

## 🛠️ MCP 도구

| Tool | 역할 |
|---|---|
| `mission_lock` | mission 을 잠그거나 갱신 |
| `mission_status` | mission, gate 유효성, approval 확인 |
| `budget_status` | slice, retry, 남은 시간 확인 |
| `list_recent_receipts` | 최근 receipts 조회 |
| `verify_receipt_integrity` | receipt 서명 검증 |
| `record_stuck_attempt` | materially different 한 실패 전략 기록 |
| `record_decision_record` | 중요한 가역적 decision 기록 |
| `record_counterexample_check` | 반증 체크와 그 risk 기록 |
| `record_user_authorization` | irreversible action 에 대한 승인 기록 |
| `authorization_status` | authorization 이 아직 유효한지 확인 |
| `turn_end_gate` | turn 종료 승인 또는 거부 |
| `completion_gate` | receipt mapping 을 통한 완료 승인 또는 거부 |
| `export_handoff_packet` | continuity packet 내보내기 |

## 📦 설치

### AI 에게 설치를 맡기기

AI 도구 안에 있다면 아래 문장을 그대로 보내도 됩니다.

```text
Agent-Runway 설치를 도와줘:

1. 전제 조건: Python 3.11+
2. 저장소 clone: git clone https://github.com/Agent-Runway/Agent-Runway
3. 의존성 설치: pip install mcp
4. 설정 생성: python scripts/generate_host_config.py --host <current-host> --project-dir <repo-path>
5. 생성된 JSON 을 현재 host 에 맞는 올바른 설정 대상에 merge:
   - Claude Code -> <repo-path>/.claude/settings.json
   - OpenCode -> 실제로 사용하는 OpenCode 설정 파일. 예: ~/.config/opencode/opencode.json, ~/.config/opencode/config.json, %USERPROFILE%\.config\opencode\opencode.json, %USERPROFILE%\.config\opencode\config.json
   - Codex/Cursor -> 해당 host 의 MCP server 설정 내 env 섹션
6. host 가 OpenCode 이고 tool-event receipt 를 자동 capture 하고 싶다면, ~/.config/opencode/plugins/agent-runway.js(또는 %USERPROFILE%\.config\opencode\plugins\agent-runway.js)를 만들고 `export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"` 를 넣습니다
7. skill 이 다른 위치에 설치되어 있다면, 이 재내보내기 경로를 실제 skill path 로 조정합니다. shim 또는 symlink 를 사용하세요. raw plugin file 을 무작정 복사하지 말고, 복사하려면 scripts/opencode_plugin_bridge.py 까지의 상대 경로도 유지해야 합니다
8. 생성된 OpenCode 설정 또는 host environment 에 ILH_OPENCODE_BRIDGE=1 을 설정한 뒤 OpenCode 를 다시 시작합니다
9. 검증: python scripts/quick_validate.py <repo-path>
```

### 수동 설치

**전제 조건:** Python 3.11+, GitHub 에서 clone: `https://github.com/Agent-Runway/Agent-Runway`

```bash
pip install mcp
```

### 설정 단계

설치란 설정 JSON 을 AI 도구의 설정 파일에 추가하는 것을 의미합니다.

#### 1. 설정 생성

설정 JSON 을 생성하는 명령을 실행하세요 (`<project-root>` 는 실제 경로로 바꾸세요).

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

#### 2. 설정을 해당 파일에 복사

**Claude Code:** 출력된 JSON 을 프로젝트 루트의 `.claude/settings.json` 에 merge 합니다.

**OpenCode:** 출력된 JSON 을 실제로 사용하는 OpenCode 설정 파일에 merge 합니다. 예: `~/.config/opencode/opencode.json`, `~/.config/opencode/config.json`, `%USERPROFILE%\.config\opencode\opencode.json`, `%USERPROFILE%\.config\opencode\config.json` 등.

#### 2a. 선택 사항: OpenCode plugin bridge 활성화

OpenCode 는 skill 내부 bridge 파일을 자동으로 찾지 않습니다. 자동 로드 대상은 project 의 `.opencode/plugins/`, 사용자 `~/.config/opencode/plugins/`, 또는 Windows 의 `%USERPROFILE%\.config\opencode\plugins\` 뿐입니다.

실제 OpenCode plugin 위치에 shim 을 만드세요. 예: `~/.config/opencode/plugins/agent-runway.js` 또는 `%USERPROFILE%\.config\opencode\plugins\agent-runway.js`.

```js
export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
```

skill 이 다른 위치에 설치되어 있다면 재내보내기 경로를 실제 skill path 로 바꾸세요. shim 또는 symlink 를 권장합니다. raw plugin file 을 그대로 복사하는 것은 피하세요. 복사하려면 `scripts/opencode_plugin_bridge.py` 까지의 상대 경로도 유지해야 합니다.

그 다음 OpenCode 설정에 `ILH_OPENCODE_BRIDGE=1` 을 설정하세요. bridge 는 host process environment, OpenCode config content, `opencode.json` 또는 `.opencode/opencode.json` 같은 발견된 설정 파일 순서로 명시된 값을 우선 적용합니다. 생성된 설정의 `mcp.agent-runway.environment` 안에 `ILH_OPENCODE_BRIDGE="1"` 을 두는 것은 shim 이 준비되어 있다는 전제에서 유효한 활성화 경로입니다. 명시적으로 `"0"` 을 쓰면 bridge 는 비활성 상태를 유지합니다. native MCP state 와 수동 receipt 기록으로 충분하다면 `"0"` 으로 두세요.

**Codex:** 출력의 `env` 섹션을 Codex MCP server 설정의 환경 변수에 추가하세요.

**Cursor:** 출력의 `env` 섹션을 Cursor MCP server 설정의 환경 변수에 추가하세요.

#### 3. 설치 검증

```bash
python scripts/quick_validate.py <project-root>
python -m unittest discover -s mcp/tests -p "test_*.py"
python scripts/smoke_test.py
```

### 설정 상세

**runtime 파일 기본 위치:**
- 데이터베이스: `.agent-runway/state.db` (project root 아래)
- Secret key: Linux/macOS `~/.config/agent-runway/secret.key`, Windows `%USERPROFILE%\.config\agent-runway\secret.key`
- 환경 변수로 override 가능: `ILH_DB_PATH` / `ILH_SECRET_PATH`

**Windows 메모:**
- `--project-dir` 에는 절대 경로를 사용하세요. PowerShell 에서 검증된 형태는 `"$(Get-Location)"` 입니다
- `ILH_DB_PATH` 는 쓰기 가능한 project directory 아래에 두세요. runtime 이 `.agent-runway` 를 자동 생성합니다
- `ILH_SECRET_PATH` 를 커스텀했다면 repository 밖에 두고 동기화하지 마세요. runtime 은 `icacls` 로 Windows ACL 을 강화하려 시도하며, 실패 시 조용히 성공한 척하지 않고 명시적인 경고를 출력합니다

## 📂 프로젝트 파일

```text
.
├── SKILL.md                         # 헌장
├── README*.md                       # 다국어 문서
├── mcp/
│   ├── server.py                    # runtime
│   ├── agent_runway_runtime/
│   │   └── store.py                 # state & receipt ledger
│   └── tests/                       # 테스트
├── scripts/
│   ├── generate_host_config.py      # host 설정
│   ├── quick_validate.py            # 구조 검증
│   ├── package_skill_check.py       # 패키지 검증
│   ├── release_gate.py              # 16-gate harness
│   ├── release_static_checks.py     # 정적 검사
│   ├── project_learning_lint.py     # Project Learning Ledger lint
│   └── project_learning_query.py    # 제한된 advisory ledger query
├── .opencode/
│   └── plugins/                     # 선택적 OpenCode bridge
└── references/                      # architecture, host, budget, receipt, parity, release, project learning
```

## ⚠️ 한계

- hooks 가 없으면 Stop enforcement 는 advisory 에 머뭅니다
- receipt 는 tool 이 실행되었다는 사실만 증명하며, 상위 수준 작업이 의미적으로 완료되었음을 단독으로 증명하지 않습니다
- secret 또는 DB 에 접근 가능하면 receipt 신뢰도가 낮아집니다
- Host Hooks 가 있으면 secret-key 읽기는 경로 변형까지 포함해 차단됩니다
- Host Hooks 가 있으면 위험한 shell command 는 실행 전에 확인을 요구합니다
- Host Hooks 가 있으면 gate 승인 이후 새로운 receipt 가 하나라도 생기면 그 승인은 오래되어 무효가 되며, `Stop` 에는 새로운 gate decision 이 필요합니다
- OpenCode `ask` 는 fail-closed 이며, 네이티브 확인 대화상자가 아닙니다
- Codex, Cursor 는 이 저장소에서 MCP 경로입니다
- Project Learning Ledger 는 advisory context 일 뿐입니다. memory 는 evidence 가 아니며 preference 는 authorization 이 아닙니다

## ✍️ 크레딧

- Publisher: babutree
- Collaborator: Codex

## 🙏 감사의 말

진정성 있고, 친절하며, 단결되어 있고, 전문적인 Linux.do 커뮤니티에 감사드립니다.<a href="https://linux.do" target="_blank" rel="noopener noreferrer"><img src="https://camo.githubusercontent.com/36a8066e13b53b968451a780de4cd6a432adeb175522afe7a080562e4f4e2534/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f4c696e7578446f2d636f6d6d756e6974792d316636666665622f68747470733a2f2f6c696e75782e646f" alt="LinuxDo" /></a>

## 📄 라이선스

MIT.
