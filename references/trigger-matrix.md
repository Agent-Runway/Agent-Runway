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

## Negative triggers

Do not invoke the full control plane when:

1. the work is a tiny low-risk single action
2. there is no meaningful verification burden
3. mission overhead would exceed the value of the task
4. the task is purely conversational and does not benefit from receipts or gates
5. the user explicitly asks for a lightweight answer instead of execution discipline

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
