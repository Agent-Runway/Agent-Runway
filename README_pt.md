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

Faça a IA avançar em direção a objetivos, e não consumir a sua confiança.

`Agent-Runway` foi feito para desenvolvedores presos digitando "continue" repetidamente enquanto ferramentas de código com IA travam no meio da tarefa. Existe um nome para esse papel: Continue Engineer. Ele substitui o "I'm done" autorrelatado por uma missão, um receipt ledger, budgets e gates — um mecanismo de auditoria que rejeita desistência no meio da tarefa e esforço fingido. É distribuído como um arquivo de skill, escala por meio de um runtime MCP para rastreamento estruturado de state e, no Claude Code, pode bloquear fisicamente o agente para que ele não pare sem aprovação.

## 💪 O que ele pode fazer

Leia esta seção primeiro como um resumo das capacidades; a tabela dos cinco problemas logo abaixo explica por que cada parte existe.

| Capacidade | Na prática |
|---|---|
| 🔒 Mission locking | Objetivo, critérios, escopo, budgets e evidence map -> sem sucesso vago |
| ✍️ Signed receipts | Assinados por HMAC por instalação -> inspecionáveis, não retóricos |
| 🚪 Completion gate | Cada critério é mapeado para receipts -> sem "done" sem sustentação |
| 💰 Budget discipline | Slice/retry/time + `wrap_up_guidance` ao esgotar -> sem teatro de retry infinito |
| 🛡️ Stale-evidence guard | Depois de editar arquivos, é preciso verificar de novo -> impede lavar evidence antiga com "edit then read" |
| 🚫 Assertion blocking | 9 padrões regex rejeitam "should work" / "probably" / "I believe" |
| 🔬 Counterexample | `record_counterexample_check` -> hipótese + verificações de refutação + risco remanescente |
| 📝 Decision records | `record_decision_record` -> decisão + alternativas rejeitadas + gatilhos de reabertura |
| 🔐 Authorization | Ações irreversíveis exigem aprovação do usuário registrada e ainda válida |
| 🔄 Failure escalation | `record_stuck_attempt` -> só contam estratégias materialmente diferentes; escalonamento após esgotar o retry budget |
| 📦 Handoff packet | Pacote JSON completo entre qualquer host -> continuidade sem memória oculta |
| ⛔ Stop enforcement | Bloqueio físico de Stop no Claude Code (hook Stop); em Codex/OpenCode é advisory |
| ⚠️ Dangerous command interception | 10 categorias + negação de `secret path` com variações multiplataforma |
| ⚖️ Value Gate | Só continuar quando houver alto impacto, verificabilidade e baixa expansão |
| 🧠 Project Learning Ledger | JSONL revisável para pitfalls, runbooks, preferências e invariants do projeto; apenas advisory, nunca evidence nem authorization |

## 🎯 Os cinco problemas que isso resolve

Os agentes falham em um conjunto pequeno de maneiras previsíveis. Estes são os cinco problemas que importam e como este projeto trata cada um deles.

| Problema | O que acontece | Como é corrigido |
|---|---|---|
| Para cedo demais | Faz uma coisa, congela e espera por "continue" | Action frontier rule: continuar enquanto o próximo passo ainda estiver alinhado à missão, for reversível e verificável |
| Erra com confiança | Diz "fixed" ou "should pass" sem prova | A conclusão exige um gate com mapeamento de critério para receipt |
| Continua polindo | Faz edits, audits e expande o escopo muito depois de o trabalho real acabar | Value Gate: só continuar quando o impacto for alto e existir lacuna de evidence |
| Perde contexto | O state deriva entre turns | Handoff packets carregam missão, evidence, budget, decisões e riscos adiante |
| Passa dos limites de autoridade | Faz deploy, push ou chamadas externas sem aprovação durável | Authorization records são verificados quanto ao frescor antes de ações irreversíveis |

O problema raiz: agentes são naturalmente bons em fazer resultados soarem corretos, mas ninguém os supervisiona.

## ⚙️ Como funciona

```text
mission_lock -> bounded slice -> receipt -> turn_end_gate -> repeat -> completion_gate -> handoff
```

Cada etapa produz um artefato concreto de runtime:

| Etapa | Trabalho | Artefato |
|---|---|---|
| Lock mission | Definir objetivo, critérios, escopo, budgets, red lines e plano de evidence | Registro de missão |
| Execute slice | Executar uma unidade de trabalho concreta, reversível e alinhada à missão | Atividade de ferramenta |
| Capture receipt | Registrar o que aconteceu: comando, exit code, hash, diff | Signed receipt |
| Turn gate | Verificar legalidade da parada e frescor dos receipts antes de encerrar | Aprovação ou rejeição |
| Completion gate | Verificar que cada critério tenha receipts de suporte | Decisão critério-para-receipt |
| Handoff | Empacotar missão, evidence, budget e risco para o próximo turn | Handoff packet |

Isto não é um prompt que apenas "pede evidence". É state estruturado — mission object, receipt ledger, rastreador de budget, approval tokens e authorization records. O agente lê esse state, e os gates o fazem valer. Quando uma missão é atualizada, os receipts antigos são invalidados e não podem ser reutilizados na nova decisão de conclusão. Os cinco gate tools (turn gate, completion gate, stuck attempt, decision record e counterexample) aplicam essa regra de forma uniforme.

## ⚙️ Runtime modes

| Capacidade | 📄 Arquivos do skill | 📄 Skill + ⚙️ MCP | 📄 Skill + ⚙️ MCP + 🧩 Host Assist | 📄 Skill + ⚙️ MCP + 🔒 Hooks |
|---|---|---|---|---|
| **O que roda** | Arquivos do skill | Skill + MCP | Skill + MCP + assist | Skill + MCP + hooks |
| **Mission lock** | Regras | ✅ | ✅ | ✅ |
| **Receipt ledger** | ◽ | ✅ | ✅ | ✅ |
| **Budget discipline** | Regras | ✅ | ✅ | ✅ |
| **Gate decisions** | Advisory | ✅ | ✅ | ✅ |
| **Authorization records** | ◽ | ✅ | ✅ | ✅ |
| **Dangerous command interception** | ◽ | ◽ | 🟡 host-specific | ✅ |
| **Stop enforcement** | ◽ | ◽ | ◽ | ✅ |
| **Hosts suportados** | Qualquer Host | Codex, Cursor, VSCode | OpenCode, Pi CLI | Claude Code |

Mostra apenas o modo mais forte atualmente declarado para cada host; `🟡 host-specific` significa que essa intercepção extra depende do host.

O OpenCode usa configuração MCP nativa por padrão. Este repositório inclui a implementação real do bridge em `.opencode/plugins/agent-runway.js`, mas o OpenCode não faz auto-discovery de plugins a partir de diretórios de skill. Ele só faz auto-load de plugins locais a partir de `.opencode/plugins/` do projeto, `~/.config/opencode/plugins/` do usuário ou, no Windows, `%USERPROFILE%\.config\opencode\plugins\`. Se você quiser que os tool events do OpenCode sejam encaminhados automaticamente para o receipt ledger, coloque um `shim` ou `symlink` em um desses diretórios de plugin do OpenCode para re-exportar o plugin do skill, e então defina `ILH_OPENCODE_BRIDGE=1`. Isso melhora a captura de receipts.

## 🔍 Como os gates decidem

Os gates trabalham em duas camadas: primeiro verificam se a evidence realmente sustenta a afirmação; depois decidem se o próximo passo ainda vale a pena.

### Profundidade de verificação

Os gates não apenas conferem superficialmente — eles pegam o discurso vazio em múltiplos níveis.

- **Correspondência semântica.** O completion gate analisa o texto de cada critério. "Tests pass" ou "build succeeds" exigem execution receipts — um Read receipt não basta. "Edit" ou "patch" exigem mutation receipts. O gate rejeita critérios cuja intenção não corresponde ao tipo de evidence fornecida.
- **Evidence pós-mutação.** Depois da última edição de arquivo, se não existir um verification receipt naquele número de sequência ou depois dele para um critério, o completion gate o rejeita. Não é permitido afirmar "tests pass" usando receipts anteriores à última mudança.
- **Rejeição de linguagem assertiva.** Resumos de trabalho e de conclusão contendo "should work", "probably", "I believe", "seems to", "appears to", "looks correct", "I'm confident" ou "it works" disparam rejeição automática do gate. É exigida linguagem de ação concreta.
- **Checkpoint de alinhamento de objetivo.** A cada três slices aprovados, o sistema emite um aviso `goal_alignment_check_due`: você ainda está indo na direção que a missão define?
- **Avisos de observação apenas.** Se um turn trouxer apenas receipts de Read/Glob/Grep sem execução, o turn gate avisa: ler não é progresso.

### Value Gate

Antes de dar o próximo passo, verifique se ele ainda vale a pena.

| Verificação | Pergunta | Limiar |
|---|---|---|
| Impacto | Afeta correção, segurança, release, instalação ou confiança? | Alto |
| Lacuna de evidence | A afirmação é mais forte que a prova? | Sim |
| Blocker | Pular isso deixa um blocker real? | Sim |
| Tamanho | É uma mudança bounded? | Pequena |
| Expansão | Aumenta a superfície de runtime/API? | Não |
| Verificação | Existe teste ou audit claro? | Sim |
| Parada | Está claro quando parar? | Sim |

Só continue quando o impacto for alto, houver uma lacuna de evidence ou blocker real, a verificação for clara, a expansão for baixa e a parada for explícita. Caso contrário, convirja. Cinco categorias para convergir: preferências de redação, expansão de superfície sem problema de alto risco, otimização sem ganho em segurança/installability/verifiability, mudanças locais após gates passarem sem novo defeito, e trabalho cujo valor e verificação não podem ser declarados com precisão.

## 🔧 Tratamento de falhas e escalonamento

Quando você travar, os retries precisam ser materialmente diferentes. `record_stuck_attempt` só conta estratégias que realmente mudam a abordagem — repetir o mesmo caminho não conta. Quando o retry budget se esgota, `stuck_escalation` é acionado: o escalonamento deve trazer evidence de que as opções locais acabaram, e não apenas "ainda falha".

## 🛠️ Ferramentas MCP

| Tool | Propósito |
|---|---|
| `mission_lock` | Travar ou atualizar a missão |
| `mission_status` | Ver missão, frescor dos gates e aprovações |
| `budget_status` | Slices, retries e tempo restante |
| `list_recent_receipts` | Listar receipts capturados |
| `verify_receipt_integrity` | Verificar assinaturas dos receipts |
| `record_stuck_attempt` | Registrar uma estratégia de falha materialmente diferente |
| `record_decision_record` | Registrar uma decisão reversível relevante |
| `record_counterexample_check` | Registrar uma checagem de refutação e seu risco |
| `record_user_authorization` | Registrar aprovação para ações irreversíveis |
| `authorization_status` | Verificar a validade atual da authorization |
| `turn_end_gate` | Aprovar ou rejeitar o fim do turn |
| `completion_gate` | Aprovar ou rejeitar a conclusão via mapping para receipts |
| `export_handoff_packet` | Exportar um pacote de continuidade |

## 📦 Instalação

### Deixe a IA ajudar na instalação

Se você estiver dentro de uma ferramenta de IA, pode enviar isto diretamente para ela:

```text
Ajude-me a instalar o Agent-Runway:

1. Pré-requisito: Python 3.11+
2. Clone o repositório: git clone https://github.com/Agent-Runway/Agent-Runway
3. Instale as dependências: pip install mcp
4. Gere a configuração: python scripts/generate_host_config.py --host <host-atual> --project-dir <caminho-do-repo>
5. Mescle o JSON gerado no alvo de configuração correto para o meu host atual:
   - Claude Code -> <caminho-do-repo>/.claude/settings.json
   - OpenCode -> o arquivo de configuração do OpenCode que eu realmente uso, por exemplo ~/.config/opencode/opencode.json, ~/.config/opencode/config.json, %USERPROFILE%\.config\opencode\opencode.json ou %USERPROFILE%\.config\opencode\config.json
   - Codex/Cursor -> a seção env da configuração do servidor MCP desse host
6. Se o host for OpenCode e eu quiser captura automática de tool-event receipts, crie ~/.config/opencode/plugins/agent-runway.js (ou %USERPROFILE%\.config\opencode\plugins\agent-runway.js) com: export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
7. Se o skill estiver instalado em outro lugar, ajuste esse caminho de re-export para o local real do skill. Use um shim ou symlink; não copie cegamente o raw plugin file, a menos que você também preserve o caminho relativo até scripts/opencode_plugin_bridge.py
8. Defina ILH_OPENCODE_BRIDGE=1 na configuração gerada do OpenCode ou no ambiente do host e reinicie o OpenCode
9. Verifique: python scripts/quick_validate.py <caminho-do-repo>
```

### Instalação manual

**Pré-requisitos:** Python 3.11+, clone do GitHub: `https://github.com/Agent-Runway/Agent-Runway`

```bash
pip install mcp
```

### Etapas de configuração

Instalar significa adicionar o JSON de configuração ao arquivo de configuração da sua ferramenta de IA.

#### 1. Gerar a configuração

Execute o comando para gerar o JSON de configuração (substitua `<project-root>` pelo caminho real):

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

#### 2. Copiar a configuração para o arquivo correspondente

**Claude Code:** copie o JSON de saída e faça merge em `.claude/settings.json` na raiz do projeto.

**OpenCode:** copie o JSON de saída e faça merge no seu arquivo de configuração do OpenCode, como `~/.config/opencode/opencode.json`, `~/.config/opencode/config.json`, `%USERPROFILE%\.config\opencode\opencode.json`, `%USERPROFILE%\.config\opencode\config.json`, ou outro caminho de configuração do OpenCode que você realmente use.

#### 2a. Opcional: habilitar o OpenCode plugin bridge

O OpenCode não faz auto-discovery do arquivo bridge interno do skill. Ele só faz auto-load de plugins a partir de `.opencode/plugins/` do projeto, `~/.config/opencode/plugins/` do usuário ou, no Windows, `%USERPROFILE%\.config\opencode\plugins\`.

Crie um shim em um diretório real de plugins do OpenCode, por exemplo `~/.config/opencode/plugins/agent-runway.js` ou `%USERPROFILE%\.config\opencode\plugins\agent-runway.js`:

```js
export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
```

Se o seu skill estiver instalado em outro local, altere o caminho de re-export para o local real do skill. Prefira um shim ou symlink. Não copie cegamente o raw plugin file, a menos que você também preserve o caminho relativo até `scripts/opencode_plugin_bridge.py`.

Depois, defina `ILH_OPENCODE_BRIDGE=1` na sua configuração do OpenCode. O bridge trata valores explícitos como autoritativos nesta ordem: ambiente do processo host, depois conteúdo de configuração do OpenCode e depois arquivos de configuração descobertos, como `opencode.json` ou `.opencode/opencode.json`. Manter `ILH_OPENCODE_BRIDGE="1"` dentro de `mcp.agent-runway.environment` na configuração gerada é, portanto, um caminho válido de ativação quando o shim já existe, e um `"0"` explícito mantém o bridge desativado. Deixe `"0"` quando o state MCP nativo e o registro manual de receipts forem suficientes.

**Codex:** copie a seção `env` da saída e adicione-a às variáveis de ambiente da configuração do servidor MCP do Codex.

**Cursor:** copie a seção `env` da saída e adicione-a às variáveis de ambiente da configuração do servidor MCP do Cursor.

#### 3. Verificar a instalação

```bash
python scripts/quick_validate.py <project-root>
python -m unittest discover -s mcp/tests -p "test_*.py"
python scripts/smoke_test.py
```

### Detalhes de configuração

**Localizações padrão dos arquivos de runtime:**
- Banco de dados: `.agent-runway/state.db` (na raiz do projeto)
- Secret key: Linux/macOS `~/.config/agent-runway/secret.key`, Windows `%USERPROFILE%\.config\agent-runway\secret.key`
- Sobrescreva com variáveis de ambiente: `ILH_DB_PATH` / `ILH_SECRET_PATH`

**Notas para Windows:**
- Passe caminhos absolutos em `--project-dir`; em PowerShell, a forma testada é `"$(Get-Location)"`
- Mantenha `ILH_DB_PATH` dentro de um diretório de projeto gravável; o runtime cria `.agent-runway` automaticamente
- Se `ILH_SECRET_PATH` for customizado, coloque-o fora do repositório e evite sincronizá-lo. O runtime tenta endurecer os ACLs do Windows com `icacls`; se isso falhar, ele emite um aviso explícito em vez de fingir silenciosamente que a key foi protegida

## 📂 Arquivos do projeto

```text
.
├── SKILL.md                         # constituição
├── README*.md                       # documentação multilíngue
├── mcp/
│   ├── server.py                    # runtime
│   ├── agent_runway_runtime/
│   │   └── store.py                 # state & receipt ledger
│   └── tests/                       # testes
├── scripts/
│   ├── generate_host_config.py      # configuração de host
│   ├── quick_validate.py            # verificação de estrutura
│   ├── package_skill_check.py       # verificação de pacote
│   ├── release_gate.py              # harness de 16 gates
│   ├── release_static_checks.py     # verificações estáticas
│   ├── project_learning_lint.py     # lint do Project Learning Ledger
│   └── project_learning_query.py    # consulta advisory limitada do ledger
├── .opencode/
│   └── plugins/                     # bridge opcional do OpenCode
└── references/                      # arquitetura, host, budget, receipt, parity, release e project learning
```

## ⚠️ Limites

- Sem hooks, Stop enforcement continua sendo advisory
- Um receipt prova que uma ferramenta foi executada, não que o resultado é semanticamente correto
- Acesso a secret ou DB degrada a confiança nos receipts
- Com Host Hooks, leituras de secret-key são negadas em diferentes variantes de caminho
- Com Host Hooks, shell commands perigosos exigem confirmação antes da execução
- Com Host Hooks, qualquer novo receipt após uma aprovação de gate torna essa aprovação stale, então `Stop` exige uma nova decisão de gate
- OpenCode `ask` é fail-closed, não uma caixa de diálogo nativa de confirmação
- Codex e Cursor são caminhos MCP neste repositório
- Project Learning Ledger é apenas advisory: memory não é evidence e preference não é authorization

## ✍️ Créditos

- Publisher: babutree
- Collaborator: Codex

## 🙏 Agradecimentos

Obrigado à comunidade Linux.do, sincera, amigável, unida e profissional.<a href="https://linux.do" target="_blank" rel="noopener noreferrer"><img src="https://camo.githubusercontent.com/36a8066e13b53b968451a780de4cd6a432adeb175522afe7a080562e4f4e2534/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f4c696e7578446f2d636f6d6d756e6974792d316636666665622f68747470733a2f2f6c696e75782e646f" alt="LinuxDo" /></a>

## 📄 Licença

MIT.
