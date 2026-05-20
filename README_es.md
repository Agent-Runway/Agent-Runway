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

Haz que la IA avance hacia objetivos, no que desgaste tu confianza.

`Agent-Runway` está pensado para desarrolladores atrapados escribiendo "continue" una y otra vez mientras las herramientas de programación con IA se quedan a medias. Hay un nombre para ese rol: Continue Engineer. Sustituye el "ya terminé" autoreportado por una misión, un receipt ledger, presupuestos y gates: un mecanismo de auditoría que rechaza abandonar tareas a mitad de camino y fingir trabajo. Se distribuye como un archivo de skill, escala mediante un runtime MCP para seguimiento estructurado del estado y, cuando el hook `Stop` de Claude Code está configurado y activo, puede bloquear físicamente que el agente se detenga sin aprobación.

## 💪 Qué puede hacer

Lee esta sección primero como un resumen de capacidades; la tabla de cinco problemas justo después explica por qué existe cada parte.

| Capacidad | En la práctica |
|---|---|
| 🔒 Mission locking | Objetivo, criterios, alcance, presupuestos y mapa de evidencia -> sin éxito vago |
| ✍️ Signed receipts | Firmados con HMAC por instalación -> inspeccionables, no retóricos |
| 🚪 Completion gate | Cada criterio se asigna a receipts -> sin "done" sin sustento |
| 💰 Budget discipline | Slice/retry/time + `wrap_up_guidance` al agotarse -> sin teatro de reintentos infinitos |
| 🛡️ Stale-evidence guard | Tras editar archivos, hay que volver a verificar -> evita lavar evidencia vieja con "edité y luego leí" |
| 🚫 Assertion-language gate | Patrones multilingües rechazan lenguaje ambiguo en los resúmenes de `turn_end_gate` / `completion_gate` |
| 🔬 Counterexample | `record_counterexample_check` -> hipótesis + refutaciones + riesgo remanente |
| 📝 Decision records | `record_decision_record` -> decisión + alternativas rechazadas + disparadores de reapertura |
| 🔐 Authorization | Las acciones irreversibles requieren aprobación del usuario registrada y con vigencia; los comandos ya autorizados no se vuelven a preguntar |
| 🔄 Failure escalation | `record_stuck_attempt` -> solo cuentan estrategias materialmente distintas; escalado tras agotar retry budget |
| 📦 Handoff packet | Paquete JSON completo entre cualquier host -> continuidad sin memoria oculta |
| ⛔ Stop enforcement | Bloqueo físico solo con el hook `Stop` de Claude Code configurado; MCP/OpenCode/Pi/Codex/Cursor no tienen paridad de Stop hook |
| ⚠️ Risk-event interception | Los hooks de Claude pueden preguntar/denegar shell commands riesgosos y lecturas de rutas protegidas; el bridge de OpenCode puede fallar cerrado si está habilitado; Pi CLI es extension-only |
| ⚖️ Value Gate | Solo continuar cuando el impacto es alto, verificable y de baja expansión |
| 🧠 Project Learning Ledger | JSONL local del proyecto bajo `.agent-runway` para pitfalls, runbooks, preferencias e invariants; solo advisory, nunca evidencia ni autorización |
| 🧪 Adversarial Audit Gate | Falsificación acotada para claims de finalización de alto riesgo; nunca prueba ausencia de bugs |

## 🎯 Los cinco problemas que resuelve

Los agentes fallan de formas predecibles y concentradas. Estos son los cinco problemas que importan y cómo los resuelve este proyecto.

| Problema | Qué ocurre | Cómo se corrige |
|---|---|---|
| Se detiene demasiado pronto | Hace una cosa, se congela y espera "continue" | Action frontier rule: seguir mientras el siguiente paso siga alineado con la misión, sea reversible y verificable |
| Se equivoca con confianza | Dice "fixed" o "should pass" sin pruebas | La finalización requiere un gate con mapeo criterio-a-receipt |
| Sigue puliendo sin parar | Edita, audita y expande el alcance mucho después de terminar el trabajo real | Value Gate: solo continuar cuando el impacto es alto y hay lagunas de evidencia |
| Pierde contexto | El estado deriva entre turnos | Los handoff packets transportan misión, evidencia, presupuesto, decisiones y riesgos |
| Se sale de su autoridad | Despliega, hace push o llamadas externas sin aprobación duradera | Los registros de autorización se revisan por vigencia antes de acciones irreversibles; los comandos ya autorizados no se vuelven a preguntar, y lo que quede fuera del alcance autorizado sigue requiriendo aprobación |

El problema de fondo: los agentes son naturalmente buenos haciendo que los resultados suenen correctos, pero nadie los supervisa.

## ⚙️ Cómo funciona

```text
mission_lock -> bounded slice -> receipt -> turn_end_gate -> repeat -> completion_gate -> handoff
```

Cada etapa produce un artefacto concreto de runtime:

| Etapa | Trabajo | Artefacto |
|---|---|---|
| Lock mission | Definir objetivo, criterios, alcance, presupuestos, líneas rojas y plan de evidencia | Registro de misión |
| Execute slice | Una unidad de trabajo concreta, reversible y alineada con la misión | Actividad de herramienta |
| Capture receipt | Registrar qué ocurrió: comando, exit code, hash, diff | Signed receipt |
| Turn gate | Comprobar legalidad de la parada y frescura de receipts antes de terminar | Aprobación o rechazo |
| Completion gate | Verificar que cada criterio tenga receipts de respaldo | Decisión criterio-a-receipt |
| Handoff | Empaquetar misión, evidencia, presupuesto y riesgo para el siguiente turno | Handoff packet |

Esto no es un prompt que "pide evidencia". Es estado estructurado: mission object, receipt ledger, rastreador de presupuestos, approval tokens y authorization records. El agente lo lee y los gates lo hacen cumplir. Cuando una misión se refresca, los receipts antiguos quedan invalidados y no pueden reutilizarse para la nueva decisión de finalización. Los cinco tools de gate (turn gate, completion gate, stuck attempt, decision record y counterexample) aplican esta regla de forma uniforme.

Los registros de governance respaldados por receipts también necesitan receipt_ids reales y capturados. En Codex, Cursor o cualquier ruta MCP solo de instrucciones sin captura automática de tool receipts, una lista vacía `receipt_ids` señala una limitación de capacidad, no un registro válido; expón la evidencia local directa por separado o corrige el host bridge, en vez de inventar IDs.

## ⚙️ Runtime modes

| Capacidad | 📄 Archivos del skill | 📄 Skill + ⚙️ MCP | 📄 Skill + ⚙️ MCP + 🧩 Host Assist | 📄 Skill + ⚙️ MCP + 🔒 Hooks |
|---|---|---|---|---|
| **Qué se ejecuta** | Archivos del skill | Skill + MCP | Skill + MCP + assist | Skill + MCP + hooks |
| **Mission lock** | Reglas | ✅ | ✅ | ✅ |
| **Receipt ledger** | ◽ | ✅ | ✅ | ✅ |
| **Budget discipline** | Reglas | ✅ | ✅ | ✅ |
| **Gate decisions** | Advisory | ✅ | ✅ | ✅ |
| **Authorization records** | ◽ | ✅ | ✅ | ✅ |
| **Risk-event interception** | ◽ | ◽ | 🟡 host-specific | ✅ |
| **Stop enforcement** | ◽ | ◽ | ◽ | ✅ |
| **Hosts compatibles** | Cualquier Host | Codex, Cursor, VSCode | OpenCode, Pi CLI | Claude Code |

Muestra el modo más fuerte actualmente declarado para cada host; `🟡 host-specific` significa que esa intercepción extra depende del host.

OpenCode usa configuración MCP nativa por defecto. Este repositorio incluye la implementación real del bridge en `.opencode/plugins/agent-runway.js`, pero OpenCode no auto-descubre plugins desde directorios de skill. Solo auto-carga plugins locales desde `.opencode/plugins/` del proyecto, `~/.config/opencode/plugins/` del usuario o, en Windows, `%USERPROFILE%\.config\opencode\plugins\`. Si quieres que los tool events de OpenCode se reenvíen automáticamente al receipt ledger, coloca un `shim` o `symlink` en uno de esos directorios de plugins de OpenCode para que re-exporte el plugin del skill y luego establece `ILH_OPENCODE_BRIDGE=1`. Esto mejora la captura de receipts, incluida la propagación del exit code de shell cuando OpenCode informa `exit`, `exitCode` o `exit_code`, aunque sigue sin paridad con el Stop hook de Claude.

El soporte de Pi CLI es intencionalmente más estrecho. `python scripts/generate_host_config.py --host pi-cli --agent-runway-dir <agent-runway-dir>` emite solo una nota extension-only, no una configuración MCP nativa. La ruta de intercepción verificada usa una extensión de Pi con `pi.on("tool_call", ...)` que devuelve `{ block: true, reason: "..." }`; consulta `scripts/fixtures/pi_block_extension.js`.

## 🔍 Cómo deciden los gates

Los gates trabajan en dos capas: primero verifican si la evidencia realmente respalda la afirmación; después deciden si el siguiente paso sigue mereciendo la pena.

### Profundidad de verificación

Los gates no se limitan a mirar por encima: detectan el discurso vacío en varios niveles.

- **Coincidencia semántica.** El completion gate analiza el lenguaje de cada criterio. Si el criterio dice "tests pass" o "build succeeds", exige execution receipts: un receipt de Read no basta. Si menciona "edit" o "patch", exige mutation receipts. El gate rechaza criterios cuya intención no coincide con el tipo de evidencia aportado.
- **Evidencia posterior a la mutación.** Después de la última edición de archivos, si no existe un verification receipt en o después de ese número de secuencia para un criterio, el completion gate lo rechaza. No se puede afirmar que "tests pass" con receipts anteriores al último cambio.
- **Rechazo de lenguaje asertivo en resúmenes.** `turn_end_gate` revisa `work_summary` y `completion_gate` revisa `completion_summary` con patrones multilingües para frases como "should work", "probably" o "I believe".
- Un stop tras un slice verificado no debe esconder en supuestos, riesgos o elementos no verificados una siguiente campaña de alto valor, una nueva fuente alpha o un rediseño de plantilla que siga siendo trabajo local pendiente. Nómbralo como trabajo real restante y continúa, o usa un stop suave legal cuando falte autoridad o información.
- **Control de alineación con el objetivo.** Cada tres slices aprobados se dispara un aviso `goal_alignment_check_due`: ¿sigues avanzando hacia lo que dice la misión?
- **Avisos de observación solamente.** Si un turno solo aporta receipts de Read/Glob/Grep sin ejecución, el turn gate avisa: leer no es progreso.

### Value Gate

Antes de dar el siguiente paso, comprueba si todavía vale la pena darlo.

| Comprobación | Pregunta | Umbral |
|---|---|---|
| Impacto | ¿Afecta a corrección, seguridad, release, instalación o confianza? | Alto |
| Brecha de evidencia | ¿La afirmación es más fuerte que la prueba? | Sí |
| Bloqueo | ¿Omitirlo deja un bloqueo real? | Sí |
| Tamaño | ¿Cambio acotado? | Pequeño |
| Expansión | ¿Amplía la superficie de runtime/API? | No |
| Verificación | ¿Hay test o auditoría claros? | Sí |
| Parada | ¿Está claro cuándo detenerse? | Sí |

Sigue solo cuando el impacto sea alto, exista una brecha de evidencia o un bloqueo real, la verificación sea clara, la expansión sea baja y la parada esté definida. De lo contrario, converge. Cinco categorías para converger: preferencias de redacción o tono, expansión de superficie sin un problema de alto riesgo correspondiente, optimizaciones que no mejoran seguridad/instalabilidad/verificabilidad, más cambios locales cuando los gates ya pasan sin defectos nuevos, y trabajo cuyo valor y verificación no pueden expresarse con precisión.

## 🔧 Gestión de fallos y escalado

Cuando te atasques, los reintentos deben ser materialmente distintos. `record_stuck_attempt` solo cuenta estrategias que cambian de enfoque de verdad: repetir el mismo camino no cuenta. Cuando se agota el retry budget, se activa `stuck_escalation`: hay que escalar con evidencia de que las opciones locales se agotaron, no con un simple "sigue fallando".

## 🛠️ Herramientas MCP

| Tool | Propósito |
|---|---|
| `mission_lock` | Bloquear o refrescar la misión |
| `mission_status` | Ver misión, frescura del gate y aprobaciones |
| `budget_status` | Slices, reintentos y tiempo restante |
| `list_recent_receipts` | Listar receipts capturados |
| `verify_receipt_integrity` | Verificar firmas de receipts |
| `record_stuck_attempt` | Registrar una estrategia fallida materialmente distinta |
| `record_decision_record` | Registrar una decisión reversible y relevante |
| `record_counterexample_check` | Registrar una comprobación de refutación y su riesgo |
| `record_user_authorization` | Registrar aprobación para acciones irreversibles |
| `authorization_status` | Comprobar vigencia de autorizaciones |
| `turn_end_gate` | Aprobar o rechazar el fin del turno |
| `completion_gate` | Aprobar o rechazar la finalización mediante mapeo a receipts |
| `export_handoff_packet` | Exportar un paquete de continuidad |

## 📦 Instalación

### Deja que la IA te ayude a instalarlo

Si estás dentro de una herramienta de IA, puedes enviarle esto directamente:

```text
Ayúdame a instalar Agent-Runway:

1. Requisito previo: Python 3.11+
2. Clona Agent-Runway en el directorio de skills que carga este CLI/host: git clone https://github.com/Agent-Runway/Agent-Runway <cli-skills-dir>/agent-runway
3. Instala dependencias: pip install mcp
4. Genera la configuración: python scripts/generate_host_config.py --agent-runway-dir <agent-runway-dir>
   Si mi host no es Claude Code, añade solo --host opencode, --host codex, --host cursor o --host pi-cli.
5. Fusiona el JSON de salida en el destino de configuración correcto para mi host actual:
   - Claude Code -> el .claude/settings.json que usa realmente mi workspace de Claude Code o configuración del host
   - OpenCode -> el archivo de configuración de OpenCode que realmente uso, por ejemplo ~/.config/opencode/opencode.json, ~/.config/opencode/config.json, %USERPROFILE%\.config\opencode\opencode.json o %USERPROFILE%\.config\opencode\config.json
   - Codex/Cursor -> la sección env de configuración del servidor MCP de ese host
   - Pi CLI -> nota extension-only; no se emite configuración MCP nativa
6. Si el host es OpenCode y quiero captura automática de tool-event receipts, crea ~/.config/opencode/plugins/agent-runway.js (o %USERPROFILE%\.config\opencode\plugins\agent-runway.js) con: export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
7. Si el skill está instalado en otra ubicación, ajusta esa ruta de re-export al lugar real del skill. Usa un shim o symlink; no copies sin más el raw plugin file a menos que también conserves su ruta relativa hacia scripts/opencode_plugin_bridge.py
8. Establece ILH_OPENCODE_BRIDGE=1 en la configuración generada de OpenCode o en el entorno del host y reinicia OpenCode
9. Verifica: python scripts/quick_validate.py <agent-runway-dir>
```

### Instalación manual

**Requisitos previos:** Python 3.11+. Clona Agent-Runway en el directorio de skills que carga tu CLI o host de IA: `git clone https://github.com/Agent-Runway/Agent-Runway <cli-skills-dir>/agent-runway`. Ese directorio clonado es `<agent-runway-dir>` y contiene `SKILL.md`, `scripts/` y `mcp/`; no es el directorio del archivo de configuración del host.

```bash
pip install mcp
```

### Pasos de configuración

Instalar significa añadir el JSON de configuración al archivo de configuración de tu herramienta de IA.

#### 1. Generar la configuración

Ejecuta el comando predeterminado desde `<agent-runway-dir>` para generar el JSON de configuración. Sin `--host`, genera configuración para Claude Code.

```bash
python scripts/generate_host_config.py --agent-runway-dir <agent-runway-dir>
```

Para OpenCode, Codex, Cursor o Pi CLI, usa el mismo comando y añade `--host opencode`, `--host codex`, `--host cursor` o `--host pi-cli` antes de `--agent-runway-dir`.

La salida de Pi CLI es una nota de capacidad extension-only, no un instalador MCP nativo.

#### 2. Copiar la configuración al archivo correspondiente

**Claude Code:** copia el JSON de salida y fusiónalo en el `.claude/settings.json` que usa realmente tu workspace de Claude Code o configuración del host.

**OpenCode:** copia el JSON de salida y fusiónalo en tu archivo de configuración de OpenCode, como `~/.config/opencode/opencode.json`, `~/.config/opencode/config.json`, `%USERPROFILE%\.config\opencode\opencode.json`, `%USERPROFILE%\.config\opencode\config.json` u otra ruta de configuración de OpenCode que realmente uses.

#### 2a. Opcional: habilitar el OpenCode plugin bridge

OpenCode no auto-descubre el bridge interno del skill. Solo auto-carga plugins desde `.opencode/plugins/` del proyecto, `~/.config/opencode/plugins/` del usuario o, en Windows, `%USERPROFILE%\.config\opencode\plugins\`.

Crea un shim en un directorio real de plugins de OpenCode, por ejemplo `~/.config/opencode/plugins/agent-runway.js` o `%USERPROFILE%\.config\opencode\plugins\agent-runway.js`:

```js
export { default } from "../skills/agent-runway/.opencode/plugins/agent-runway.js"
```

Si tu skill está instalado en otra ubicación, cambia la ruta de re-export a la ubicación real del skill. Prefiere un shim o symlink. No copies sin más el raw plugin file a menos que también conserves su ruta relativa hacia `scripts/opencode_plugin_bridge.py`.

Después, establece `ILH_OPENCODE_BRIDGE=1` en tu configuración de OpenCode. El bridge trata los valores explícitos como autoritativos en este orden: entorno del proceso host, luego contenido de configuración de OpenCode y luego archivos de configuración descubiertos como `opencode.json` o `.opencode/opencode.json`. Mantener `ILH_OPENCODE_BRIDGE="1"` dentro de `mcp.agent-runway.environment` en la configuración generada es, por tanto, una ruta válida de activación una vez que exista el shim, y un `"0"` explícito mantiene el bridge desactivado. Déjalo en `"0"` cuando el estado MCP nativo y el registro manual de receipts sean suficientes.

**Codex:** copia la sección `env` de la salida y añádela a las variables de entorno de la configuración del servidor MCP de Codex.

**Cursor:** copia la sección `env` de la salida y añádela a las variables de entorno de la configuración del servidor MCP de Cursor.

#### 3. Verificar la instalación

```bash
python scripts/quick_validate.py <agent-runway-dir>
python -B -m pytest mcp/tests -q
python scripts/smoke_test.py
```

Para reproducir evidencia de bloqueo a nivel de host cuando Claude Code, OpenCode, Node y npm estén disponibles:

```bash
python scripts/host_blocking_experiments.py
```

### Detalles de configuración

**Ubicaciones predeterminadas de archivos de runtime:**
- Base de datos: `.agent-runway/state.db` dentro del directorio del proyecto activo; no uses el directorio de instalación de la skill como base de datos predeterminada compartida entre proyectos
- Secret key: Linux/macOS `~/.config/agent-runway/secret.key`, Windows `%USERPROFILE%\.config\agent-runway\secret.key`
- Anular con variables de entorno: `ILH_DB_PATH` / `ILH_SECRET_PATH`

**Notas para Windows:**
- Usa rutas absolutas para `--agent-runway-dir`; en PowerShell la forma probada es `"$(Get-Location)"` cuando estás dentro del directorio del skill Agent-Runway
- Deja `ILH_DB_PATH` sin definir para el uso normal local al proyecto. Defínelo solo cuando quieras una ruta de estado específica para ese proyecto; el runtime crea `.agent-runway` automáticamente
- Si personalizas `ILH_SECRET_PATH`, colócalo fuera del repositorio y evita sincronizarlo. El runtime intenta endurecer los ACL de Windows con `icacls`; si eso falla, emite una advertencia explícita en lugar de fingir que la key ya está protegida

## 📂 Archivos del proyecto

```text
.
├── SKILL.md                         # constitución
├── README*.md                       # documentación multilingüe
├── mcp/
│   ├── server.py                    # runtime
│   ├── agent_runway_runtime/
│   │   └── store.py                 # state & receipt ledger
│   └── tests/                       # tests de runtime y adaptadores
├── scripts/
│   ├── generate_host_config.py      # configuración de host
│   ├── quick_validate.py            # comprobación de estructura
│   ├── smoke_test.py                # smoke test de runtime
│   ├── project_learning_lint.py     # lint del Project Learning Ledger
│   ├── project_learning_query.py    # consulta advisory acotada del ledger
│   ├── dynamic_context.py           # JSONL de contexto acotado por misión
│   ├── adversarial_audit_lint.py    # lint de registros de auditoría
│   └── host_blocking_experiments.py # experimentos reproducibles de bloqueo de host
├── .opencode/
│   └── plugins/                     # bridge opcional de OpenCode
└── references/                      # arquitectura, host, budget, receipt, parity y project learning
```

## ⚠️ Límites

- Sin un hook `Stop` configurado en Claude Code, Stop enforcement sigue siendo advisory
- Un receipt prueba que una herramienta se ejecutó, no la corrección semántica del resultado
- El acceso a secret o DB degrada la confianza en los receipts
- Con hooks configurados de Claude Code, las lecturas de secret-key se deniegan en distintas variantes de ruta
- Con hooks configurados de Claude Code, los shell commands peligrosos disparan confirmación antes de ejecutarse
- Con hooks configurados de Claude Code, cualquier receipt nuevo después de una aprobación de gate deja obsoleta esa aprobación, así que `Stop` exige una decisión de gate nueva
- OpenCode `ask` es fail-closed, no un diálogo nativo de confirmación
- El soporte de Pi CLI es extension-only: se probó bloqueo `tool_call`, no paridad MCP nativa ni hook Stop
- Codex y Cursor son rutas MCP en este repositorio; este repo no afirma captura automática de receipts de shell/read/edit para ellos sin un host bridge adicional verificado
- Project Learning Ledger es local al proyecto bajo el `.agent-runway/` ignorado del proyecto activo: memory no es evidence y preference no es authorization
- Dynamic Context es local al proyecto en `.agent-runway/dynamic-context.jsonl`, está acotado por misión, limita cada registro a 100k bytes y no es evidence ni authorization

## 📄 Licencia

MIT.
