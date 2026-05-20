# Trigger Matrix

Use this file when deciding whether the full control plane should be invoked.

## Positive triggers

Invoke the skill when at least one of these is true:

1. the task needs more than one execution step
2. completion can be faked unless evidence is mapped to criteria
3. a weak model habit could stop early and still sound persuasive
4. a host or tool interaction needs explicit risk boundaries
5. the user expects the model to operate as the primary executor
6. the task is important enough that benchmark or release discipline is justified
7. the user sends a short continuation phrase and there is active or recoverable execution context
8. the user omits the skill name but requests multi-step coding, debugging, verification, commit, push, release, or other work with evidence or authorization boundaries

## Prompt Intake Gate

Short prompts are not low-value prompts. A short prompt often points to runtime state, previous assistant next steps, dirty worktree state, or an active mission.

Use `prompt_intake_gate` when a prompt is short, ambiguous, or potentially high-autonomy. The tool returns `classification`, `should_activate_agent_runway`, `confidence`, `evidence_sources`, `required_first_actions`, `authority_boundary`, and a capability caveat.

The gate separates four language-monitoring domains:

- activation detection for explicit `/agent-runway` or implicit high-autonomy requests
- continuation detection for phrases such as `continue`, `go on`, `继续`, `weiter`, `continuez`, `continúa`, `continua`, `続けて`, and `계속`
- assertion laundering detection for completion summaries that substitute hedging for evidence
- authorization detection for scoped replies to a previous explicit authority question

Continuation phrases are registry signals, not decisions. The decision must use state:

- active session mission plus continuation means continue the current mission after hydrating state
- unique active workspace mission plus continuation means resume that mission and mark session rebind as needed
- multiple active workspace missions means ask which mission to continue
- multiple active missions in the same session is treated as corrupted or legacy runtime state; ask for `task_id` instead of silently choosing the latest mission
- no mission but dirty worktree or previous next step means recover context before continuing without fabricating a mission
- an explicit `task_id` that has no active mission must not fall back to a neighboring workspace mission
- no recoverable context means ask one clarification
- previous explicit authority question plus reply means record only that scoped authorization
- previous explicit authority question plus denial or limiting language such as `do not push`, `don't deploy`, `不要推送`, or `别发布` means authorization was not granted; continue only with reversible local work or ask for fresh scoped approval

The signal layer normalizes Unicode width, case, accents, punctuation, and common politeness or directive wrappers such as `please continue`, `Can you continue?`, `OK 继续`, `继续开发`, `接着处理`, `continúa por favor`, `bitte weiter`, `続けてください`, and `계속해줘`. It uses word-boundary matching and narrow reference-context filters so strings such as `contest`, `pushdown`, `push-down automata`, `release notes`, `release-candidate notes`, `发布说明`, and `推送通知` do not become fake `test`, `push`, `release`, or external-side-effect requests.

Do not treat memory, project learning, or vector search as completion evidence or authorization. Memory can be a hint only; it must not create a mission when runtime state is absent.

## Negative triggers

Do not invoke the full control plane when:

1. the work is a tiny low-risk single action
2. there is no meaningful verification burden
3. mission overhead would exceed the value of the task
4. the task is purely conversational and does not benefit from receipts or gates
5. the user explicitly asks for a lightweight answer instead of execution discipline
6. the prompt is a code question, quoted user text, or ordinary question containing a continuation word, such as `What does continue mean in Python?`
7. the prompt asks whether to perform an external side effect, such as `继续推送吗？`; this is a question requiring scoped authorization, not an authorization or execution command

## Borderline cases

For borderline work, prefer these lighter patterns before full invocation:

- one reversible action plus one verification step
- a small evidence table without full mission state
- explicit runtime honesty without the rest of the apparatus

## Trigger decision record

When invocation fit is ambiguous, answer these four questions:

1. what failure would the skill prevent here
2. what overhead would the skill add here
3. what weaker alternative would still be safe
4. what would make non-invocation obviously wrong

If the first and fourth answers are strong while the second is modest, invoke the skill.
