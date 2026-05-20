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

Sorge dafür, dass KI auf Ziele zusteuert, statt dein Vertrauen aufzubrauchen.

`Agent-Runway` richtet sich an Entwickler, die festhängen und immer wieder "continue" tippen, während KI-Coding-Tools mitten in der Aufgabe stocken. Für diese Rolle gibt es einen Namen: Continue Engineer. Das Projekt ersetzt ein selbst gemeldetes "I'm done" durch eine Mission, ein receipt ledger, Budgets und gates – einen Audit-Mechanismus, der vorzeitiges Aufhören und vorgetäuschte Arbeit zurückweist. Es wird als Skill-Datei ausgeliefert, skaliert über ein MCP-Runtime für strukturiertes State-Tracking und kann in Claude Code den Agenten physisch daran hindern, ohne Freigabe zu stoppen.

## 💪 Was es leisten kann

Lies diesen Abschnitt zuerst als Fähigkeitsüberblick; die Tabelle mit den fünf Problemen direkt danach erklärt, warum jeder Teil existiert.

| Fähigkeit | In der Praxis |
|---|---|
| 🔒 Mission locking | Ziel, Kriterien, Umfang, Budgets und Evidence-Map -> kein vager Erfolg |
| ✍️ Signed receipts | Pro Installation HMAC-signiert -> prüfbar statt rhetorisch |
| 🚪 Completion gate | Jedes Kriterium wird auf receipts abgebildet -> kein unbelegtes "done" |
| 💰 Budget discipline | Slice/retry/time + `wrap_up_guidance` bei Erschöpfung -> kein endloses Retry-Theater |
| 🛡️ Stale-evidence guard | Nach Dateiänderungen muss neu verifiziert werden -> verhindert das Waschen alter Evidenz durch "edit then read" |
| 🚫 Assertion blocking | 15 Regex-Muster lehnen "should work" / "probably" / "I believe" ab |
| 🔬 Counterexample | `record_counterexample_check` -> Hypothese + Gegenprüfungen + verbleibendes Risiko |
| 📝 Decision records | `record_decision_record` -> Entscheidung + verworfene Alternativen + Reopen-Trigger |
| 🔐 Authorization | Irreversible Aktionen erfordern eine aufgezeichnete, frische Benutzerfreigabe |
| 🔄 Failure escalation | `record_stuck_attempt` -> nur materiell unterschiedliche Strategien zählen; Eskalation nach erschöpftem Retry-Budget |
| 📦 Handoff packet | Vollständiges JSON-Paket über jeden Host hinweg -> Kontinuität ohne verstecktes Gedächtnis |
| ⛔ Stop enforcement | Physisches Stop-Blocking in Claude Code (Stop-Hook); in Codex/OpenCode/Pi CLI advisory |
| ⚠️ Dangerous command interception | 10 Kategorien + Secret-Path-Sperre mit plattformübergreifender Varianten-Erkennung |
| ⚖️ Value Gate | Nur weitergehen, wenn der Schritt hohen Impact, Verifizierbarkeit und geringe Expansion hat |
| 🧠 Project Learning Ledger | Prüfbares JSONL für Projekt-Pitfalls, Runbooks, Präferenzen und Invariants; nur advisory, niemals Beweis oder Autorisierung |
| 🧪 Adversarial Audit Gate | Begrenzte Falsifikation für High-Risk-Completion-Claims; niemals Beweis, dass keine Bugs existieren |

## 🎯 Die fünf Probleme, die es löst

Agenten scheitern auf wenige, vorhersehbare Arten. Hier sind die fünf relevanten Probleme – und wie dieses Projekt mit ihnen umgeht.

| Problem | Was passiert | Wie es behoben wird |
|---|---|---|
| Stoppt zu früh | Erledigt eine Sache, friert ein und wartet auf "continue" | Action frontier rule: weitermachen, solange der nächste Schritt missionskonform, reversibel und verifizierbar ist |
| Liegt selbstbewusst falsch | Sagt "fixed" oder "should pass" ohne Beleg | Abschluss erfordert ein gate mit Kriterium-zu-receipt-Mapping |
| Poliert endlos weiter | Edits, Audits und Scope-Erweiterungen lange nach dem eigentlichen Abschluss | Value Gate: nur weitergehen, wenn hoher Impact und Evidenzlücke vorhanden sind |
| Verliert Kontext | State driftet zwischen Turns | Handoff packets transportieren Mission, Evidenz, Budget, Entscheidungen und Risiken weiter |
| Überschreitet Autorität | Deploys, Pushes oder externe Aufrufe ohne belastbare Freigabe | Authorization records werden vor irreversiblen Aktionen auf Frische geprüft |

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

## ⚙️ Runtime modes

| Fähigkeit | 📄 Skill-Dateien | 📄 Skill + ⚙️ MCP | 📄 Skill + ⚙️ MCP + 🧩 Host Assist | 📄 Skill + ⚙️ MCP + 🔒 Hooks |
|---|---|---|---|---|
| **Was läuft** | Skill-Dateien | Skill + MCP | Skill + MCP + Assist | Skill + MCP + Hooks |
| **Mission lock** | Regeln | ✅ | ✅ | ✅ |
| **Receipt ledger** | ◽ | ✅ | ✅ | ✅ |
| **Budget discipline** | Regeln | ✅ | ✅ | ✅ |
| **Gate decisions** | Advisory | ✅ | ✅ | ✅ |
| **Authorization records** | ◽ | ✅ | ✅ | ✅ |
| **Dangerous command interception** | ◽ | ◽ | 🟡 host-specific | ✅ |
| **Stop enforcement** | ◽ | ◽ | ◽ | ✅ |
| **Unterstützte Hosts** | Jeder Host | Codex, Cursor, VSCode | OpenCode, Pi CLI | Claude Code |

Zeigt den aktuell pro Host beanspruchten stärksten Modus; `🟡 host-specific` bedeutet, dass die zusätzliche Interception vom konkreten Host abhängt.

OpenCode verwendet standardmäßig native MCP-Konfiguration. Dieses Repo enthält die echte Bridge-Implementierung unter `.opencode/plugins/agent-runway.js`, aber OpenCode entdeckt Plugins aus Skill-Verzeichnissen nicht automatisch. Es lädt lokale Plugins nur aus dem projektweiten `.opencode/plugins/`, aus `~/.config/opencode/plugins/` des Benutzers oder unter Windows aus `%USERPROFILE%\.config\opencode\plugins\`. Wenn du möchtest, dass OpenCode-Tool-Events automatisch in das receipt ledger weitergeleitet werden, platziere ein `shim` oder `symlink` in einem dieser OpenCode-Plugin-Verzeichnisse, sodass es das Skill-Plugin re-exportiert, und setze dann `ILH_OPENCODE_BRIDGE=1`. Das verbessert die Receipt-Erfassung.

Pi CLI-Unterstützung ist bewusst enger. `python scripts/generate_host_config.py --host pi-cli --project-dir <project-root>` gibt nur einen extension-only Hinweis aus, keine native MCP-Konfiguration. Der geprüfte Interception-Pfad ist eine Pi-Erweiterung mit `pi.on("tool_call", ...)`, die `{ block: true, reason: "..." }` zurückgibt; siehe `scripts/fixtures/pi_block_extension.js`.

## 🔍 Wie die gates entscheiden

Die gates arbeiten auf zwei Ebenen: Zuerst prüfen sie, ob die Evidenz die Behauptung tatsächlich trägt, danach entscheiden sie, ob der nächste Schritt überhaupt noch lohnend ist.

### Verifikationstiefe

Die gates schauen nicht nur oberflächlich hin – sie erkennen Schönfärberei auf mehreren Ebenen.

- **Semantisches Matching.** Das completion gate analysiert die Formulierung jedes Kriteriums. "Tests pass" oder "build succeeds" verlangen execution receipts – ein Read-receipt reicht nicht. "Edit" oder "patch" verlangen mutation receipts. Das gate weist Kriterien zurück, deren Absicht nicht zum gelieferten Evidenztyp passt.
- **Evidenz nach Mutation.** Nach der letzten Dateiänderung wird ein Kriterium vom completion gate zurückgewiesen, wenn es keinen verification receipt auf oder nach dieser Sequenznummer gibt. Man darf also nicht behaupten, "tests pass", wenn die receipts vor der letzten Änderung liegen.
- **Ablehnung von Behauptungssprache.** Arbeits- und Abschlusszusammenfassungen mit "should work", "probably", "I believe", "seems to", "appears to", "looks correct", "I'm confident" oder "it works" führen automatisch zur Ablehnung durch das gate. Es ist konkrete Aktionssprache erforderlich.
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
2. Repository klonen: git clone https://github.com/Agent-Runway/Agent-Runway
3. Abhängigkeiten installieren: pip install mcp
4. Konfiguration erzeugen: python scripts/generate_host_config.py --host <aktueller-host> --project-dir <repo-pfad>
5. Das erzeugte JSON in das richtige Konfigurationsziel für meinen aktuellen Host einfügen:
   - Claude Code -> <repo-pfad>/.claude/settings.json
   - OpenCode -> die OpenCode-Konfigurationsdatei, die ich tatsächlich verwende, z. B. ~/.config/opencode/opencode.json, ~/.config/opencode/config.json, %USERPROFILE%\.config\opencode\opencode.json oder %USERPROFILE%\.config\opencode\config.json
   - Codex/Cursor -> den env-Abschnitt der MCP-Server-Konfiguration dieses Hosts
   - Pi CLI -> extension-only Hinweis; es wird keine native MCP-Konfiguration erzeugt
6. Wenn der Host OpenCode ist und ich automatische Tool-Event-Receipt-Erfassung möchte, erstelle ~/.config/opencode/plugins/agent-runway.js (oder %USERPROFILE%\.config\opencode\plugins\agent-runway.js) mit: export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
7. Wenn das Skill woanders installiert ist, passe diesen Re-Export-Pfad auf den tatsächlichen Skill-Speicherort an. Verwende ein shim oder symlink; kopiere die raw plugin file nicht blind, außer du erhältst auch ihren relativen Pfad zu scripts/opencode_plugin_bridge.py
8. Setze ILH_OPENCODE_BRIDGE=1 in der generierten OpenCode-Konfiguration oder der Host-Umgebung und starte OpenCode neu
9. Verifizieren: python scripts/quick_validate.py <repo-pfad>
```

### Manuelle Installation

**Voraussetzungen:** Python 3.11+, aus GitHub klonen: `https://github.com/Agent-Runway/Agent-Runway`

```bash
pip install mcp
```

### Konfigurationsschritte

Installation bedeutet, das Konfigurations-JSON in die Konfigurationsdatei deines KI-Tools einzufügen.

#### 1. Konfiguration erzeugen

Führe den Befehl aus, um das Konfigurations-JSON zu erzeugen (ersetze `<project-root>` durch den echten Pfad):

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

Pi CLI-Ausgabe ist ein extension-only Capability-Hinweis, kein nativer MCP-Installer.

#### 2. Konfiguration in die richtige Datei kopieren

**Claude Code:** Kopiere das ausgegebene JSON und merge es in `.claude/settings.json` im Projektwurzelverzeichnis.

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
python scripts/quick_validate.py <project-root>
python -m unittest discover -s mcp/tests -p "test_*.py"
python scripts/smoke_test.py
```

Wenn Claude Code, OpenCode, Node und npm lokal verfügbar sind, kann Host-Blocking-Evidenz reproduziert werden:

```bash
python scripts/host_blocking_experiments.py
```

### Konfigurationsdetails

**Standardpfade für Runtime-Dateien:**
- Datenbank: `.agent-runway/state.db` (unter dem Projektwurzelverzeichnis)
- Secret key: Linux/macOS `~/.config/agent-runway/secret.key`, Windows `%USERPROFILE%\.config\agent-runway\secret.key`
- Überschreiben über Umgebungsvariablen: `ILH_DB_PATH` / `ILH_SECRET_PATH`

**Hinweise für Windows:**
- Verwende absolute Pfade für `--project-dir`; in PowerShell ist `"$(Get-Location)"` die getestete Form
- Halte `ILH_DB_PATH` in einem beschreibbaren Projektverzeichnis; die Runtime erstellt `.agent-runway` automatisch
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
│   └── tests/                       # Tests
├── scripts/
│   ├── generate_host_config.py      # Host-Konfiguration
│   ├── quick_validate.py            # Strukturprüfung
│   ├── package_skill_check.py       # Paketprüfung
│   ├── release_gate.py              # 16-Gate-Harness
│   ├── release_static_checks.py     # statische Prüfungen
│   ├── project_learning_lint.py     # Project-Learning-Ledger-Lint
│   ├── project_learning_query.py    # begrenzte advisory Ledger-Abfrage
│   └── host_blocking_experiments.py # reproduzierbare Host-Blocking-Experimente
├── .opencode/
│   └── plugins/                     # optionale OpenCode-Bridge
└── references/                      # Architektur, Host, Budget, receipt, parity, release und project learning
```

## ⚠️ Grenzen

- Ohne hooks bleibt Stop enforcement advisory
- Ein receipt beweist, dass ein Tool gelaufen ist, nicht dass das Ergebnis semantisch korrekt ist
- Secret- oder DB-Zugriff verschlechtert das Vertrauen in receipts
- Mit Host Hooks werden Secret-Key-Lesezugriffe über Pfadvarianten hinweg verweigert
- Mit Host Hooks lösen gefährliche Shell-Commands vor der Ausführung eine Bestätigung aus
- Mit Host Hooks macht jeder neue receipt nach einer gate-Freigabe diese Freigabe veraltet, sodass `Stop` eine frische gate-Entscheidung verlangt
- OpenCode `ask` ist fail-closed und kein nativer Bestätigungsdialog
- Pi CLI-Unterstützung ist extension-only: getestet ist `tool_call`-Blocking, nicht native MCP- oder Stop-Hook-Parität
- Codex und Cursor sind in diesem Repo MCP-Pfade
- Project Learning Ledger ist nur advisory: memory ist keine evidence und preference keine authorization

## ✍️ Credits

- Publisher: babutree
- Collaborator: Codex

## 🙏 Danksagung

Danke an die aufrichtige, freundliche, geeinte und professionelle Linux.do-Community.<a href="https://linux.do" target="_blank" rel="noopener noreferrer"><img src="https://camo.githubusercontent.com/36a8066e13b53b968451a780de4cd6a432adeb175522afe7a080562e4f4e2534/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f4c696e7578446f2d636f6d6d756e6974792d316636666665622f68747470733a2f2f6c696e75782e646f" alt="LinuxDo" /></a>

## 📄 Lizenz

MIT.
