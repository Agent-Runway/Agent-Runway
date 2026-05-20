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

AI を、信頼を浪費する存在ではなく、目標へ進み続ける存在にする。

`Agent-Runway` は、AI コーディングツールが作業途中で止まり、開発者が何度も "continue" を打つはめになる状況に向けた仕組みです。こうした役割には名前があります。Continue Engineer です。このプロジェクトは、自己申告の "I'm done" を、mission、receipt ledger、budget、gate に置き換えます。つまり、途中放棄や見せかけの努力を拒否する監査メカニズムです。skill ファイルとして配布され、構造化された state 追跡のために MCP runtime と連携し、Claude Code では承認なしの停止を物理的にブロックできます。

## 💪 できること

まずはこのセクションを機能の要約として読んでください。直後の「5つの問題」表は、それぞれの要素がなぜ必要なのかを説明します。

| 機能 | 実際の効果 |
|---|---|
| 🔒 Mission locking | 目標、基準、スコープ、budget、evidence map を固定 -> あいまいな成功を防ぐ |
| ✍️ Signed receipts | インストール単位の HMAC 署名付き -> レトリックではなく検証可能 |
| 🚪 Completion gate | すべての基準を receipts に対応付け -> 根拠のない "done" を防ぐ |
| 💰 Budget discipline | slice/retry/time + 枯渇時の `wrap_up_guidance` -> 無限 retry を防ぐ |
| 🛡️ Stale-evidence guard | ファイル編集後は再検証が必須 -> "edit then read" による古い evidence の洗浄を防ぐ |
| 🚫 Assertion blocking | 15 個の regex で "should work" / "probably" / "I believe" を拒否 |
| 🔬 Counterexample | `record_counterexample_check` -> 仮説 + 反証確認 + 残余リスク |
| 📝 Decision records | `record_decision_record` -> 選択 + 却下した代替案 + 再オープン条件 |
| 🔐 Authorization | 不可逆な操作には、記録され、なお有効なユーザー承認が必要 |
| 🔄 Failure escalation | `record_stuck_attempt` -> 本質的に異なる戦略だけをカウントし、retry budget 枯渇後に escalation |
| 📦 Handoff packet | どの Host でも使える完全な JSON パケット -> 隠れた記憶に依存しない継続性 |
| ⛔ Stop enforcement | Claude Code では Stop hook による物理ブロック、Codex/OpenCode/Pi CLI では advisory |
| ⚠️ Dangerous command interception | 10 分類 + 複数プラットフォームのパス変種を含む secret path 拒否 |
| ⚖️ Value Gate | 高 impact・検証可能・低 expansion の場合だけ続行 |
| 🧠 Project Learning Ledger | プロジェクト固有の pitfalls、runbooks、preferences、invariants を記録するレビュー可能な JSONL。advisory のみで、evidence や authorization にはならない |
| 🧪 Adversarial Audit Gate | 高リスク completion claims に対する bounded falsification。bug が存在しない証明ではない |

## 🎯 解決する5つの問題

agent の失敗パターンは、予測できる少数の型に集中しています。重要なのは次の 5 つで、このプロジェクトはそれぞれに対処します。

| 問題 | 何が起きるか | どう直すか |
|---|---|---|
| 早く止まりすぎる | 一つやって止まり、"continue" を待つ | Action frontier rule: 次の一手が mission に沿い、可逆で、検証可能なら続行する |
| 自信満々で間違う | 根拠なしに "fixed" や "should pass" と言う | 完了には、criterion-to-receipt mapping を持つ gate が必要 |
| いつまでも磨き続ける | 実作業が終わった後も edit、audit、scope 拡大を続ける | Value Gate: impact が高く evidence gap があるときだけ続行 |
| 文脈を失う | turn をまたぐと state がずれる | handoff packet が mission、evidence、budget、decision、risk を引き継ぐ |
| 権限を越える | durable な承認なしに deploy、push、外部呼び出しをする | 不可逆操作の前に authorization record がまだ有効か確認する |

根本の問題は、agent が結果をもっともらしく見せるのは得意でも、それを監督する仕組みがないことです。

## ⚙️ 仕組み

```text
mission_lock -> bounded slice -> receipt -> turn_end_gate -> repeat -> completion_gate -> handoff
```

各段階は具体的な runtime artifact を生みます。

| 段階 | 役割 | 生成物 |
|---|---|---|
| Lock mission | 目標、基準、scope、budget、red line、evidence plan を定義 | mission record |
| Execute slice | 可逆で mission に沿った具体的な作業単位を実行 | tool activity |
| Capture receipt | 何が起きたかを記録: command、exit code、hash、diff | signed receipt |
| Turn gate | turn を終える前に stop の合法性と receipt の有効性を確認 | 承認または拒否 |
| Completion gate | すべての基準に receipts が対応しているか確認 | criterion-to-receipt decision |
| Handoff | 次の turn に備えて mission、evidence、budget、risk を束ねる | handoff packet |

これは evidence を「求めるだけ」の prompt ではありません。mission object、receipt ledger、budget tracker、approval token、authorization record からなる構造化 state です。agent がそれを読み、gate がそれを強制します。mission が更新されると、古い receipts は無効化され、新しい completion decision に再利用できません。5 つの gate tool（turn gate、completion gate、stuck attempt、decision record、counterexample）はこのルールを一貫して適用します。

## ⚙️ Runtime modes

| 機能 | 📄 Skill ファイル層 | 📄 Skill + ⚙️ MCP | 📄 Skill + ⚙️ MCP + 🧩 Host Assist | 📄 Skill + ⚙️ MCP + 🔒 Hooks |
|---|---|---|---|---|
| **動くもの** | Skill ファイル | Skill + MCP | Skill + MCP + 補助 | Skill + MCP + Hooks |
| **Mission lock** | ルール | ✅ | ✅ | ✅ |
| **Receipt ledger** | ◽ | ✅ | ✅ | ✅ |
| **Budget discipline** | ルール | ✅ | ✅ | ✅ |
| **Gate decisions** | Advisory | ✅ | ✅ | ✅ |
| **Authorization records** | ◽ | ✅ | ✅ | ✅ |
| **Dangerous command interception** | ◽ | ◽ | 🟡 host-specific | ✅ |
| **Stop enforcement** | ◽ | ◽ | ◽ | ✅ |
| **対応 Host** | Any Host | Codex, Cursor, VSCode | OpenCode, Pi CLI | Claude Code |

現在各 Host について主張している最強モードだけを示します。`🟡 host-specific` は、その追加インターセプトが Host 依存であることを意味します。

OpenCode はデフォルトで native MCP configuration を使います。このリポジトリには `.opencode/plugins/agent-runway.js` として実際の bridge 実装が含まれていますが、OpenCode は skill directory 内の plugin を自動検出しません。ローカル plugin を自動ロードするのは、project の `.opencode/plugins/`、ユーザーの `~/.config/opencode/plugins/`、または Windows の `%USERPROFILE%\.config\opencode\plugins\` だけです。OpenCode の tool events を自動で receipt ledger に転送したい場合は、これらの OpenCode plugin 配置先のどれかに `shim` または `symlink` を置き、skill plugin を再エクスポートさせたうえで `ILH_OPENCODE_BRIDGE=1` を設定してください。これにより receipt capture は改善されます。

Pi CLI support は意図的に狭い範囲です。`python scripts/generate_host_config.py --host pi-cli --project-dir <project-root>` は extension-only note を出すだけで、native MCP configuration は出力しません。検証済みの interception path は、`pi.on("tool_call", ...)` で `{ block: true, reason: "..." }` を返す Pi extension です。`scripts/fixtures/pi_block_extension.js` を参照してください。

## 🔍 gate はどう判断するか

gate には 2 層あります。まず evidence が本当にその主張を支えているかを確認し、その後で次の一手に進む価値がまだあるかを判断します。

### 検証の深さ

gate は単にざっと見るだけではありません。言い逃れやごまかしを複数のレベルで捕まえます。

- **意味の一致。** completion gate は各 criterion の文言を解析します。"Tests pass" や "build succeeds" なら execution receipts が必要で、Read receipt では足りません。"Edit" や "patch" なら mutation receipts が必要です。criterion の意図と evidence type が一致しない場合、gate はそれを拒否します。
- **変更後の evidence。** 最後のファイル編集以降、その criterion を支える verification receipt がその sequence 以上で存在しなければ、completion gate は拒否します。最後の変更前の receipts で "tests pass" と主張することはできません。
- **断定表現の拒否。** work summary や completion summary に "should work", "probably", "I believe", "seems to", "appears to", "looks correct", "I'm confident", "it works" が含まれていると、自動的に gate に拒否されます。具体的な行動の言葉が必要です。
- **目標整合チェック。** approved な slice が 3 回通るたびに `goal_alignment_check_due` が出ます。今も mission の方向に進んでいるかを確認するためです。
- **観察だけの warning。** Read/Glob/Grep receipts だけで execution がない turn には、turn gate が「読むだけでは進捗ではない」と警告します。

### Value Gate

次の一手に進む前に、その一手にまだ価値があるかを確認してください。

| チェック | 問い | 基準 |
|---|---|---|
| Impact | 正しさ、安全性、release、installation、trust に影響するか | 高い |
| Evidence gap | 今の主張は証拠より強いか | はい |
| Blocker | スキップすると本当に blocker が残るか | はい |
| Size | 変更は bounded か | 小さい |
| Expansion | runtime/API surface を広げるか | いいえ |
| Verification | 明確な test または audit があるか | はい |
| Stop | どこで止めるかが明確か | はい |

impact が高く、evidence gap か real blocker があり、verification が明確で、expansion が低く、stop が明示されている場合だけ続けてください。そうでなければ収束させてください。以下の 5 種類は収束させるべき作業です：表現やトーンの好み、高リスク問題のない surface 拡張、安全性・installability・verifiability を改善しない最適化、gate が通って新 defect もない状態での local change、価値・verification path・stop condition を正確に説明できない作業。

## 🔧 失敗処理と escalation

行き詰まったとき、retry は本質的に異なるものでなければなりません。`record_stuck_attempt` は、アプローチが本当に変わった場合だけカウントします。同じ道の繰り返しはカウントされません。retry budget が尽きたら `stuck_escalation` を発動し、ローカルな選択肢が尽きたことを evidence 付きで示してエスカレーションします。単に "まだ失敗する" だけでは不十分です。

## 🛠️ MCP tools

| Tool | 役割 |
|---|---|
| `mission_lock` | mission を lock または refresh する |
| `mission_status` | mission、gate の有効性、approval を見る |
| `budget_status` | slices、retry、残り時間を見る |
| `list_recent_receipts` | recent receipts を一覧する |
| `verify_receipt_integrity` | receipt の署名を検証する |
| `record_stuck_attempt` | 本質的に異なる failure strategy を記録する |
| `record_decision_record` | 重要な可逆 decision を記録する |
| `record_counterexample_check` | 反証チェックとその risk を記録する |
| `record_user_authorization` | 不可逆な action への承認を記録する |
| `authorization_status` | authorization がまだ有効か確認する |
| `turn_end_gate` | turn の終了を承認または拒否する |
| `completion_gate` | receipt mapping によって完了を承認または拒否する |
| `export_handoff_packet` | continuity 用 packet を export する |

## 📦 インストール

### AI にインストールを手伝ってもらう

AI ツール内にいるなら、そのまま次の文を送れます。

```text
Agent-Runway のインストールを手伝ってください:

1. 前提条件: Python 3.11+
2. リポジトリを clone: git clone https://github.com/Agent-Runway/Agent-Runway
3. 依存をインストール: pip install mcp
4. 設定を生成: python scripts/generate_host_config.py --host <current-host> --project-dir <repo-path>
5. 出力された JSON を、現在の host に合った正しい設定先へ merge:
   - Claude Code -> <repo-path>/.claude/settings.json
   - OpenCode -> 実際に使っている OpenCode 設定ファイル。例: ~/.config/opencode/opencode.json, ~/.config/opencode/config.json, %USERPROFILE%\.config\opencode\opencode.json, %USERPROFILE%\.config\opencode\config.json
   - Codex/Cursor -> その host の MCP server 設定にある env セクション
   - Pi CLI -> extension-only note。native MCP configuration は出力されません
6. host が OpenCode で、tool-event receipt を自動 capture したい場合は、~/.config/opencode/plugins/agent-runway.js（または %USERPROFILE%\.config\opencode\plugins\agent-runway.js）を作成し、`export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"` を記述する
7. skill が別の場所にあるなら、この再エクスポート先を実際の skill path に合わせて調整する。shim または symlink を使う。raw plugin file をむやみにコピーしないこと。コピーするなら scripts/opencode_plugin_bridge.py への相対パスも維持すること
8. 生成した OpenCode 設定または host environment に ILH_OPENCODE_BRIDGE=1 を設定し、OpenCode を再起動する
9. 検証: python scripts/quick_validate.py <repo-path>
```

### 手動インストール

**前提条件:** Python 3.11+、GitHub から clone: `https://github.com/Agent-Runway/Agent-Runway`

```bash
pip install mcp
```

### 設定手順

インストールとは、設定 JSON を AI ツールの設定ファイルに追加することです。

#### 1. 設定を生成する

次のコマンドで設定 JSON を生成します（`<project-root>` は実際のパスに置き換えてください）。

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

Pi CLI の出力は extension-only capability note であり、native MCP installer ではありません。

#### 2. 設定を対応するファイルへコピーする

**Claude Code:** 出力された JSON をプロジェクトルートの `.claude/settings.json` に merge します。

**OpenCode:** 出力された JSON を、実際に使っている OpenCode 設定ファイルへ merge します。例: `~/.config/opencode/opencode.json`、`~/.config/opencode/config.json`、`%USERPROFILE%\.config\opencode\opencode.json`、`%USERPROFILE%\.config\opencode\config.json` など。

#### 2a. 任意: OpenCode plugin bridge を有効化する

OpenCode は skill 内部の bridge ファイルを自動検出しません。自動ロード対象は、project の `.opencode/plugins/`、ユーザーの `~/.config/opencode/plugins/`、または Windows の `%USERPROFILE%\.config\opencode\plugins\` のみです。

実際の OpenCode plugin 配置先に shim を作成してください。例: `~/.config/opencode/plugins/agent-runway.js` または `%USERPROFILE%\.config\opencode\plugins\agent-runway.js`。

```js
export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
```

skill が別の場所にインストールされている場合は、この再エクスポート先を実際の skill path に変更してください。shim または symlink を推奨します。raw plugin file をそのままコピーするのは避けてください。コピーするなら `scripts/opencode_plugin_bridge.py` への相対パスも保持する必要があります。

その後、OpenCode 設定に `ILH_OPENCODE_BRIDGE=1` を設定します。bridge は、host process environment、OpenCode config content、`opencode.json` や `.opencode/opencode.json` といった検出済みの設定ファイルの順で、明示された値を優先して採用します。生成された設定の `mcp.agent-runway.environment` に `ILH_OPENCODE_BRIDGE="1"` を残すことは、shim が存在する前提では有効な有効化経路です。明示的に `"0"` を書けば bridge は無効のままです。native MCP state と手動 receipt 記録で十分なら `"0"` のままにしてください。

**Codex:** 出力の `env` セクションを、Codex の MCP server 設定の環境変数に追加します。

**Cursor:** 出力の `env` セクションを、Cursor の MCP server 設定の環境変数に追加します。

#### 3. インストールを検証する

```bash
python scripts/quick_validate.py <project-root>
python -m unittest discover -s mcp/tests -p "test_*.py"
python scripts/smoke_test.py
```

Claude Code、OpenCode、Node、npm が利用できる場合、host-level blocking evidence を再現できます。

```bash
python scripts/host_blocking_experiments.py
```

### 設定の詳細

**runtime ファイルの既定位置:**
- データベース: `.agent-runway/state.db`（project root 配下）
- Secret key: Linux/macOS `~/.config/agent-runway/secret.key`、Windows `%USERPROFILE%\.config\agent-runway\secret.key`
- 上書きする環境変数: `ILH_DB_PATH` / `ILH_SECRET_PATH`

**Windows メモ:**
- `--project-dir` には絶対パスを使ってください。PowerShell では `"$(Get-Location)"` が検証済みです
- `ILH_DB_PATH` は書き込み可能な project directory 配下に置いてください。runtime が `.agent-runway` を自動作成します
- `ILH_SECRET_PATH` をカスタマイズする場合は repository の外に置き、同期しないでください。runtime は `icacls` で Windows ACL を強化しようとします。失敗した場合でも、黙って成功したふりはせず、明示的な warning を出します

## 📂 プロジェクトファイル

```text
.
├── SKILL.md                         # 行動憲章
├── README*.md                       # 多言語ドキュメント
├── mcp/
│   ├── server.py                    # runtime
│   ├── agent_runway_runtime/
│   │   └── store.py                 # state & receipt ledger
│   └── tests/                       # テスト
├── scripts/
│   ├── generate_host_config.py      # host 設定
│   ├── quick_validate.py            # 構造チェック
│   ├── package_skill_check.py       # パッケージ検証
│   ├── release_gate.py              # 16-gate harness
│   ├── release_static_checks.py     # 静的チェック
│   ├── project_learning_lint.py     # Project Learning Ledger lint
│   ├── project_learning_query.py    # 制限付き advisory ledger query
│   └── host_blocking_experiments.py # 再現可能な host blocking 実験
├── .opencode/
│   └── plugins/                     # OpenCode 用の任意 bridge
└── references/                      # architecture, host, budget, receipt, parity, release, project learning
```

## ⚠️ 制限

- hooks がない場合、Stop enforcement は advisory のままです
- receipt が証明するのは tool が実行されたことだけであり、タスク全体の意味的な正しさではありません
- secret や DB へアクセスできると、receipt の信頼性は下がります
- Host Hooks がある場合、secret-key の読み取りはパス変種をまたいで拒否されます
- Host Hooks がある場合、危険な shell command は実行前に確認を要求します
- Host Hooks がある場合、gate 承認後に新しい receipt が追加されると、その承認は古くなり、`Stop` には新しい gate decision が必要になります
- OpenCode `ask` は fail-closed であり、ネイティブの確認ダイアログではありません
- Pi CLI support は extension-only です。検証済みなのは `tool_call` blocking であり、native MCP や Stop hook parity ではありません
- Codex、Cursor はこのリポジトリでは MCP パスです
- Project Learning Ledger は advisory context のみです。memory は evidence ではなく、preference は authorization ではありません

## ✍️ クレジット

- Publisher: babutree
- Collaborator: Codex

## 🙏 謝辞

誠実で、親切で、結束が強く、プロフェッショナルな Linux.do コミュニティに感謝します。<a href="https://linux.do" target="_blank" rel="noopener noreferrer"><img src="https://camo.githubusercontent.com/36a8066e13b53b968451a780de4cd6a432adeb175522afe7a080562e4f4e2534/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f4c696e7578446f2d636f6d6d756e6974792d316636666665622f68747470733a2f2f6c696e75782e646f" alt="LinuxDo" /></a>

## 📄 ライセンス

MIT.
