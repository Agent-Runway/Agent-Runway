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

Sorge dafür, dass KI auf Ziele zusteuert, statt dein Vertrauen aufzubrauchen.

`Agent-Runway` richtet sich an Entwickler, die festhängen und immer wieder "continue" tippen, während KI-Coding-Tools mitten in der Aufgabe stocken. Für diese Rolle gibt es einen Namen: Continue Engineer. Das Projekt ersetzt ein selbst gemeldetes "I'm done" durch eine Mission, ein receipt ledger, Budgets und gates – einen Audit-Mechanismus, der vorzeitiges Aufhören und vorgetäuschte Arbeit zurückweist. Es wird als Skill-Datei ausgeliefert, skaliert über ein MCP-Runtime für strukturiertes State-Tracking und kann, wenn der Claude-Code-`Stop`-Hook konfiguriert und aktiv ist, den Agenten physisch daran hindern, ohne Freigabe zu stoppen.

## 💪 Was es leisten kann

Lies diesen Abschnitt zuerst als Fähigkeitsüberblick; die Tabelle mit den fünf Problemen direkt danach erklärt, warum jeder Teil existiert.

| Fähigkeit | In der Praxis |
|---|---|
| 🔒 Mission locking | Ziel, Kriterien, Umfang, Budgets und Evidence-Map -> kein vager Erfolg |
| ✍️ Signed receipts | Pro Installation HMAC-signiert -> prüfbar statt rhetorisch |
| 🚪 Completion gate | Jedes Kriterium wird auf receipts abgebildet -> kein unbelegtes "done" |
| 💰 Budget discipline | Slice/retry/time + `wrap_up_guidance` bei Erschöpfung -> kein endloses Retry-Theater |
| 🛡️ Stale-evidence guard | Nach Dateiänderungen muss neu verifiziert werden -> verhindert das Waschen alter Evidenz durch "edit then read" |
| 🚫 Assertion-language gate | Mehrsprachige Muster weisen vage Formulierungen in `turn_end_gate`- / `completion_gate`-Zusammenfassungen zurück |
| 🔬 Counterexample | `record_counterexample_check` -> Hypothese + Gegenprüfungen + verbleibendes Risiko |
| 📝 Decision records | `record_decision_record` -> Entscheidung + verworfene Alternativen + Reopen-Trigger |
| 🔐 Authorization | Irreversible Aktionen erfordern eine aufgezeichnete, frische Benutzerfreigabe; bereits freigegebene Commands werden nicht erneut abgefragt |
| 🔄 Failure escalation | `record_stuck_attempt` -> nur materiell unterschiedliche Strategien zählen; Eskalation nach erschöpftem Retry-Budget |
| 📦 Handoff packet | Vollständiges JSON-Paket über jeden Host hinweg -> Kontinuität ohne verstecktes Gedächtnis |
| ⛔ Stop enforcement | Physisches Blocking nur mit konfiguriertem Claude-Code-`Stop`-Hook; MCP/OpenCode/Pi/Codex/Cursor haben keine Stop-Hook-Parität |
| ⚠️ Risk-event interception | Claude-Hooks können riskante Shell-Commands und geschützte Pfadzugriffe fragen/ablehnen; die OpenCode-Bridge kann aktiviert fail-closed reagieren; Pi CLI ist extension-only |
| ⚖️ Value Gate | Nur weitergehen, wenn der Schritt hohen Impact, Verifizierbarkeit und geringe Expansion hat |
| 🧠 Project Learning Ledger | Projektlokales `.agent-runway`-JSONL für Projekt-Pitfalls, Runbooks, Präferenzen und Invariants; nur advisory, niemals Beweis oder Autorisierung |
| 🧪 Adversarial Audit Gate | Begrenzte Falsifikation für High-Risk-Completion-Claims; niemals Beweis, dass keine Bugs existieren |

## 🎯 Die fünf Probleme, die es löst

Agenten scheitern auf wenige, vorhersehbare Arten. Hier sind die fünf relevanten Probleme – und wie dieses Projekt mit ihnen umgeht.

| Problem | Was passiert | Wie es behoben wird |
|---|---|---|
| Stoppt zu früh | Erledigt eine Sache, friert ein und wartet auf "continue" | Action frontier rule: weitermachen, solange der nächste Schritt missionskonform, reversibel und verifizierbar ist |
| Liegt selbstbewusst falsch | Sagt "fixed" oder "should pass" ohne Beleg | Abschluss erfordert ein gate mit Kriterium-zu-receipt-Mapping |
| Poliert endlos weiter | Edits, Audits und Scope-Erweiterungen lange nach dem eigentlichen Abschluss | Value Gate: nur weitergehen, wenn hoher Impact und Evidenzlücke vorhanden sind |
| Verliert Kontext | State driftet zwischen Turns | Handoff packets transportieren Mission, Evidenz, Budget, Entscheidungen und Risiken weiter |
| Überschreitet Autorität | Deploys, Pushes oder externe Aufrufe ohne belastbare Freigabe | Authorization records werden vor irreversiblen Aktionen auf Frische geprüft; bereits freigegebene Commands werden nicht erneut abgefragt, außerhalb dieses Scopes ist weiterhin Freigabe nötig |

Das Grundproblem: Agenten sind von Natur aus gut darin, Ergebnisse plausibel klingen zu lassen – aber niemand beaufsichtigt sie.

## ⚙️ Wie es funktioniert

```text
mission_lock -> bounded slice -> receipt -> turn_end_gate -> repeat -> completion_gate -> handoff
```

Jede Stufe erzeugt ein konkretes Runtime-Artefakt:

| Stufe | Aufgabe | Artefakt |
|---|---|---|
| Lock mission | Ziel, Kriterien, Scope, Budgets, rote Linien und Evidence-Plan definieren | Missionsdatensatz |
| Execute slice | Eine konkrete, reversible und missionskonforme Arbeitseinheit ausführen | Tool-Aktivität |
| Capture receipt | Festhalten, was passiert ist: Befehl, Exit-Code, Hash, Diff | Signed receipt |
| Turn gate | Vor Turn-Ende Stop-Legalität und Receipt-Frische prüfen | Freigabe oder Ablehnung |
| Completion gate | Prüfen, ob jedes Kriterium durch receipts gestützt wird | Kriterium-zu-receipt-Entscheidung |
| Handoff | Mission, Evidenz, Budget und Risiko für den nächsten Turn bündeln | Handoff packet |

Das ist kein Prompt, der einfach nur "nach Belegen fragt". Es ist strukturierter State: mission object, receipt ledger, Budget-Tracking, approval tokens und authorization records. Der Agent liest ihn, und die gates erzwingen ihn. Wenn eine Mission aktualisiert wird, werden alte receipts invalidiert und dürfen nicht mehr für die neue Completion-Entscheidung verwendet werden. Alle fünf Gate-Tools (turn gate, completion gate, stuck attempt, decision record und counterexample) erzwingen diese Regel einheitlich.

Receipt-gestützte Governance-Records brauchen außerdem reale, erfasste receipt_ids. In Codex, Cursor oder jedem reinen MCP-Pfad ohne automatische Tool-Receipt-Erfassung ist eine leere `receipt_ids`-Liste ein Hinweis auf eine Capability-Lücke, kein gültiger Record; lege direkte lokale Evidenz separat offen oder behebe den Host-Bridge-Pfad, statt IDs zu erfinden.

## ⚙️ Runtime modes

| Fähigkeit | 📄 Skill-Dateien | 📄 Skill + ⚙️ MCP | 📄 Skill + ⚙️ MCP + 🧩 Host Assist | 📄 Skill + ⚙️ MCP + 🔒 Hooks |
|---|---|---|---|---|
| **Was läuft** | Skill-Dateien | Skill + MCP | Skill + MCP + Assist | Skill + MCP + Hooks |
| **Mission lock** | Regeln | ✅ | ✅ | ✅ |
| **Receipt ledger** | ◽ | ✅ | ✅ | ✅ |
| **Budget discipline** | Regeln | ✅ | ✅ | ✅ |
| **Gate decisions** | Advisory | ✅ | ✅ | ✅ |
| **Authorization records** | ◽ | ✅ | ✅ | ✅ |
| **Risk-event interception** | ◽ | ◽ | 🟡 host-specific | ✅ |
| **Stop enforcement** | ◽ | ◽ | ◽ | ✅ |
| **Unterstützte Hosts** | Jeder Host | Codex, Cursor, VSCode | OpenCode, Pi CLI | Claude Code |

Zeigt den aktuell pro Host beanspruchten stärksten Modus; `🟡 host-specific` bedeutet, dass die zusätzliche Interception vom konkreten Host abhängt.

OpenCode verwendet standardmäßig native MCP-Konfiguration. Dieses Repo enthält die echte Bridge-Implementierung unter `.opencode/plugins/agent-runway.js`, aber OpenCode entdeckt Plugins aus Skill-Verzeichnissen nicht automatisch. Es lädt lokale Plugins nur aus dem projektweiten `.opencode/plugins/`, aus `~/.config/opencode/plugins/` des Benutzers oder unter Windows aus `%USERPROFILE%\.config\opencode\plugins\`. Wenn du möchtest, dass OpenCode-Tool-Events automatisch in das receipt ledger weitergeleitet werden, platziere ein `shim` oder `symlink` in einem dieser OpenCode-Plugin-Verzeichnisse, sodass es das Skill-Plugin re-exportiert, und setze dann `ILH_OPENCODE_BRIDGE=1`. Das verbessert die Receipt-Erfassung, einschließlich der Weitergabe des Shell-Exit-Codes, wenn OpenCode `exit`, `exitCode` oder `exit_code` meldet, bleibt aber ohne Claude-artige Stop-hook-Parität.

Pi CLI-Unterstützung ist bewusst enger. `python scripts/generate_host_config.py --host pi-cli --agent-runway-dir <agent-runway-dir>` gibt nur einen extension-only Hinweis aus, keine native MCP-Konfiguration. Der geprüfte Interception-Pfad ist eine Pi-Erweiterung mit `pi.on("tool_call", ...)`, die `{ block: true, reason: "..." }` zurückgibt; siehe `scripts/fixtures/pi_block_extension.js`.

## 🔍 Wie die gates entscheiden

Die gates arbeiten auf zwei Ebenen: Zuerst prüfen sie, ob die Evidenz die Behauptung tatsächlich trägt, danach entscheiden sie, ob der nächste Schritt überhaupt noch lohnend ist.

### Verifikationstiefe

Die gates schauen nicht nur oberflächlich hin – sie erkennen Schönfärberei auf mehreren Ebenen.

- **Semantisches Matching.** Das completion gate analysiert die Formulierung jedes Kriteriums. "Tests pass" oder "build succeeds" verlangen execution receipts – ein Read-receipt reicht nicht. "Edit" oder "patch" verlangen mutation receipts. Das gate weist Kriterien zurück, deren Absicht nicht zum gelieferten Evidenztyp passt.
- **Evidenz nach Mutation.** Nach der letzten Dateiänderung wird ein Kriterium vom completion gate zurückgewiesen, wenn es keinen verification receipt auf oder nach dieser Sequenznummer gibt. Man darf also nicht behaupten, "tests pass", wenn die receipts vor der letzten Änderung liegen.
- **Ablehnung von Behauptungssprache in Zusammenfassungen.** `turn_end_gate` prüft `work_summary` und `completion_gate` prüft `completion_summary` mit 15 Regex-Mustern für Formulierungen wie "should work", "probably" oder "I believe".
- Ein verifizierter Slice-Stop darf keine noch offene nächste High-Value-Kampagne, neue Alpha-Quelle oder Template-Redesign in Annahmen, Risiken oder unüberprüften Punkten verstecken. Benenne das als echte Restarbeit und arbeite weiter, oder nutze einen legalen weichen Stopp, wenn Autorität oder Information tatsächlich fehlt.
- **Zielausrichtungs-Checkpoint.** Alle drei genehmigten slices löst das System einen `goal_alignment_check_due`-Hinweis aus: Bewegst du dich noch in Richtung der Mission?
- **Warnungen bei reiner Beobachtung.** Wenn ein Turn nur Read/Glob/Grep-receipts ohne Ausführung enthält, warnt das turn gate: Lesen ist kein Fortschritt.

### Value Gate

Bevor du den nächsten Schritt gehst, prüfe, ob er es noch wert ist.

| Prüfung | Frage | Schwelle |
|---|---|---|
| Impact | Betrifft es Korrektheit, Sicherheit, Release, Installation oder Vertrauen? | Hoch |
| Evidenzlücke | Ist die Behauptung stärker als der Beleg? | Ja |
| Blocker | Lässt Auslassen einen echten Blocker stehen? | Ja |
| Größe | Ist die Änderung begrenzt? | Klein |
| Expansion | Vergrößert sie die Runtime-/API-Oberfläche? | Nein |
| Verifikation | Gibt es einen klaren Test oder Audit? | Ja |
| Stop | Ist klar, wann man aufhören muss? | Ja |

Fahre nur fort, wenn der Impact hoch ist, eine Evidenzlücke oder ein echter Blocker besteht, die Verifikation klar ist, die Expansion gering ist und ein explizites Stop-Kriterium vorliegt. Andernfalls konvergiere. Fünf Kategorien zur Konvergenz: Formulierungspräferenzen, Oberflächenexpansion ohne Hochrisikoproblem, Optimierung ohne Sicherheits-/Installierbarkeits-/Verifizierbarkeitsgewinn, lokale Änderungen nach bestandenen Gates ohne neuen Defekt, und Arbeit ohne präzise benennbaren Wert oder Verifikationspfad.

## 🔧 Fehlerbehandlung und Eskalation

Wenn du feststeckst, müssen retries materiell unterschiedlich sein. `record_stuck_attempt` zählt nur Strategien, die den Ansatz wirklich ändern – denselben Weg zu wiederholen zählt nicht. Sobald das Retry-Budget erschöpft ist, wird `stuck_escalation` ausgelöst: Eskalation mit Evidenz dafür, dass lokale Optionen verbraucht sind, nicht bloß mit "es scheitert immer noch".

## 🛠️ MCP-Tools

| Tool | Zweck |
|---|---|
| `mission_lock` | Mission sperren oder aktualisieren |
| `mission_status` | Mission, Gate-Frische und Freigaben anzeigen |
| `budget_status` | Slices, retries und verbleibende Zeit |
| `list_recent_receipts` | Erfasste receipts auflisten |
| `verify_receipt_integrity` | Receipt-Signaturen prüfen |
| `record_stuck_attempt` | Eine materiell andere Fehlstrategie festhalten |
| `record_decision_record` | Eine wichtige reversible Entscheidung festhalten |
| `record_counterexample_check` | Eine Gegenprüfung und ihr Risiko festhalten |
| `record_user_authorization` | Freigabe für irreversible Aktionen festhalten |
| `authorization_status` | Frische der Autorisierung prüfen |
| `turn_end_gate` | Turn-Ende genehmigen oder ablehnen |
| `completion_gate` | Abschluss per receipt-Mapping genehmigen oder ablehnen |
| `export_handoff_packet` | Kontinuitätspaket exportieren |

## 📦 Installation

### Lass die KI bei der Installation helfen

Wenn du in einem KI-Tool arbeitest, kannst du ihm Folgendes direkt schicken:

```text
Hilf mir bei der Installation von Agent-Runway:

1. Voraussetzung: Python 3.11+
2. Agent-Runway in das von diesem CLI/Host geladene Skills-Verzeichnis klonen: git clone https://github.com/Agent-Runway/Agent-Runway <cli-skills-dir>/agent-runway
3. Abhängigkeiten installieren: pip install mcp
4. Konfiguration erzeugen: python scripts/generate_host_config.py --agent-runway-dir <agent-runway-dir>
   Wenn mein Host nicht Claude Code ist, füge nur --host opencode, --host codex, --host cursor oder --host pi-cli hinzu.
5. Das erzeugte JSON in das richtige Konfigurationsziel für meinen aktuellen Host einfügen:
   - Claude Code -> die .claude/settings.json, die mein Claude-Code-Workspace oder meine Host-Konfiguration tatsächlich verwendet
   - OpenCode -> die OpenCode-Konfigurationsdatei, die ich tatsächlich verwende, z. B. ~/.config/opencode/opencode.json, ~/.config/opencode/config.json, %USERPROFILE%\.config\opencode\opencode.json oder %USERPROFILE%\.config\opencode\config.json
   - Codex/Cursor -> den env-Abschnitt der MCP-Server-Konfiguration dieses Hosts
   - Pi CLI -> extension-only Hinweis; es wird keine native MCP-Konfiguration erzeugt
6. Wenn der Host OpenCode ist und ich automatische Tool-Event-Receipt-Erfassung möchte, erstelle ~/.config/opencode/plugins/agent-runway.js (oder %USERPROFILE%\.config\opencode\plugins\agent-runway.js) mit: export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
7. Wenn das Skill woanders installiert ist, passe diesen Re-Export-Pfad auf den tatsächlichen Skill-Speicherort an. Verwende ein shim oder symlink; kopiere die raw plugin file nicht blind, außer du erhältst auch ihren relativen Pfad zu scripts/opencode_plugin_bridge.py
8. Setze ILH_OPENCODE_BRIDGE=1 in der generierten OpenCode-Konfiguration oder der Host-Umgebung und starte OpenCode neu
9. Verifizieren: python scripts/quick_validate.py <agent-runway-dir>
```

### Manuelle Installation

**Voraussetzungen:** Python 3.11+. Klone Agent-Runway in das Skills-Verzeichnis, das dein CLI oder KI-Host lädt: `git clone https://github.com/Agent-Runway/Agent-Runway <cli-skills-dir>/agent-runway`. Dieses geklonte Verzeichnis ist `<agent-runway-dir>` und enthält `SKILL.md`, `scripts/` und `mcp/`; es ist nicht das Host-Konfigurationsverzeichnis.

```bash
pip install mcp
```

### Konfigurationsschritte

Installation bedeutet, das Konfigurations-JSON in die Konfigurationsdatei deines KI-Tools einzufügen.

#### 1. Konfiguration erzeugen

Führe den Standardbefehl aus `<agent-runway-dir>` aus, um das Konfigurations-JSON zu erzeugen. Ohne `--host` wird Claude Code konfiguriert.

```bash
python scripts/generate_host_config.py --agent-runway-dir <agent-runway-dir>
```

Für OpenCode, Codex, Cursor oder Pi CLI verwende denselben Befehl und füge vor `--agent-runway-dir` `--host opencode`, `--host codex`, `--host cursor` oder `--host pi-cli` hinzu.

Pi CLI-Ausgabe ist ein extension-only Capability-Hinweis, kein nativer MCP-Installer.

#### 2. Konfiguration in die richtige Datei kopieren

**Claude Code:** Kopiere das ausgegebene JSON und merge es in die `.claude/settings.json`, die dein Claude-Code-Workspace oder deine Host-Konfiguration tatsächlich verwendet.

**OpenCode:** Kopiere das ausgegebene JSON und merge es in deine OpenCode-Konfigurationsdatei, z. B. `~/.config/opencode/opencode.json`, `~/.config/opencode/config.json`, `%USERPROFILE%\.config\opencode\opencode.json`, `%USERPROFILE%\.config\opencode\config.json` oder einen anderen OpenCode-Konfigurationspfad, den du tatsächlich nutzt.

#### 2a. Optional: die OpenCode plugin bridge aktivieren

OpenCode entdeckt die skill-interne Bridge-Datei nicht automatisch. Es lädt Plugins nur aus dem projektweiten `.opencode/plugins/`, aus `~/.config/opencode/plugins/` des Benutzers oder unter Windows aus `%USERPROFILE%\.config\opencode\plugins\`.

Erstelle ein shim in einem echten OpenCode-Plugin-Verzeichnis, zum Beispiel `~/.config/opencode/plugins/agent-runway.js` oder `%USERPROFILE%\.config\opencode\plugins\agent-runway.js`:

```js
export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
```

Wenn dein Skill woanders installiert ist, ändere den Re-Export-Pfad auf den tatsächlichen Skill-Speicherort. Bevorzuge ein shim oder symlink. Kopiere die raw plugin file nicht blind, außer du erhältst auch ihren relativen Pfad zu `scripts/opencode_plugin_bridge.py`.

Setze anschließend `ILH_OPENCODE_BRIDGE=1` in deiner OpenCode-Konfiguration. Die Bridge behandelt explizite Werte in dieser Reihenfolge als autoritativ: Host-Prozess-Umgebung, dann OpenCode-Konfigurationsinhalt und schließlich gefundene Konfigurationsdateien wie `opencode.json` oder `.opencode/opencode.json`. `ILH_OPENCODE_BRIDGE="1"` unter `mcp.agent-runway.environment` in der generierten Konfiguration ist damit ein gültiger Aktivierungspfad, sobald das shim existiert, und ein explizites `"0"` hält die Bridge deaktiviert. Belasse es bei `"0"`, wenn nativer MCP-State und manuelle Receipt-Erfassung ausreichen.

**Codex:** Kopiere den `env`-Abschnitt aus der Ausgabe in die Umgebungsvariablen der Codex-MCP-Server-Konfiguration.

**Cursor:** Kopiere den `env`-Abschnitt aus der Ausgabe in die Umgebungsvariablen der Cursor-MCP-Server-Konfiguration.

#### 3. Installation verifizieren

```bash
python scripts/quick_validate.py <agent-runway-dir>
python -B -m pytest mcp/tests -q
python scripts/smoke_test.py
```

Wenn Claude Code, OpenCode, Node und npm lokal verfügbar sind, kann Host-Blocking-Evidenz reproduziert werden:

```bash
python scripts/host_blocking_experiments.py
```

### Konfigurationsdetails

**Standardpfade für Runtime-Dateien:**
- Datenbank: `.agent-runway/state.db` unter dem aktiven Projektverzeichnis; nutze nicht das Skill-Installationsverzeichnis als gemeinsame Standarddatenbank für mehrere Projekte
- Secret key: Linux/macOS `~/.config/agent-runway/secret.key`, Windows `%USERPROFILE%\.config\agent-runway\secret.key`
- Überschreiben über Umgebungsvariablen: `ILH_DB_PATH` / `ILH_SECRET_PATH`

**Hinweise für Windows:**
- Verwende absolute Pfade für `--agent-runway-dir`; in PowerShell ist `"$(Get-Location)"` die getestete Form, wenn du dich im Agent-Runway-Skill-Verzeichnis befindest
- Lasse `ILH_DB_PATH` für normale projektlokale Nutzung ungesetzt. Setze es nur, wenn du bewusst eine bestimmte State-Datei für dieses Projekt verwenden willst; die Runtime erstellt `.agent-runway` automatisch
- Wenn `ILH_SECRET_PATH` angepasst wird, speichere ihn außerhalb des Repositories und synchronisiere ihn nicht mit. Die Runtime versucht, Windows-ACLs mit `icacls` zu verschärfen; wenn das fehlschlägt, wird eine explizite Warnung ausgegeben, statt still zu behaupten, die key sei gesichert

## 📂 Projektdateien

```text
.
├── SKILL.md                         # Verfassung
├── README*.md                       # mehrsprachige Dokumentation
├── mcp/
│   ├── server.py                    # Runtime
│   ├── agent_runway_runtime/
│   │   └── store.py                 # State & receipt ledger
│   └── tests/                       # Runtime- und Adapter-Tests
├── scripts/
│   ├── generate_host_config.py      # Host-Konfiguration
│   ├── quick_validate.py            # Strukturprüfung
│   ├── smoke_test.py                # Runtime-Smoke-Test
│   ├── project_learning_lint.py     # Project-Learning-Ledger-Lint
│   ├── project_learning_query.py    # begrenzte advisory Ledger-Abfrage
│   ├── dynamic_context.py           # begrenzter missionsbezogener Kontext-JSONL
│   ├── adversarial_audit_lint.py    # Audit-Record-Lint
│   └── host_blocking_experiments.py # reproduzierbare Host-Blocking-Experimente
├── .opencode/
│   └── plugins/                     # optionale OpenCode-Bridge
└── references/                      # Architektur, Host, Budget, receipt, parity und project learning
```

## ⚠️ Grenzen

- Ohne konfigurierten Claude-Code-`Stop`-Hook bleibt Stop enforcement advisory
- Ein receipt beweist, dass ein Tool gelaufen ist, nicht dass das Ergebnis semantisch korrekt ist
- Secret- oder DB-Zugriff verschlechtert das Vertrauen in receipts
- Mit konfigurierten Claude-Code-Hooks werden Secret-Key-Lesezugriffe über Pfadvarianten hinweg verweigert
- Mit konfigurierten Claude-Code-Hooks lösen gefährliche Shell-Commands vor der Ausführung eine Bestätigung aus
- Mit konfigurierten Claude-Code-Hooks macht jeder neue receipt nach einer gate-Freigabe diese Freigabe veraltet, sodass `Stop` eine frische gate-Entscheidung verlangt
- OpenCode `ask` ist fail-closed und kein nativer Bestätigungsdialog
- Pi CLI-Unterstützung ist extension-only: getestet ist `tool_call`-Blocking, nicht native MCP- oder Stop-Hook-Parität
- Codex und Cursor sind in diesem Repo MCP-Pfade; dieses Repo behauptet ohne zusätzlichen verifizierten Host-Bridge-Pfad keine automatische Shell-/Read-/Edit-Receipt-Erfassung für sie
- Project Learning Ledger bleibt projektlokal unter dem ignorierten `.agent-runway/` des aktiven Projekts: memory ist keine evidence und preference keine authorization
- Dynamic Context bleibt projektlokal in `.agent-runway/dynamic-context.jsonl`, ist missionsbezogen, pro Record auf 100k Bytes begrenzt und ist weder evidence noch authorization

## 📄 Lizenz

MIT.
