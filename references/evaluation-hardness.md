# Evaluation Hardness

A benchmark that only proves the golden path is not hard enough.

## Required pressure

Use at least one of these:

- mutation tests that degrade the skill and should fail
- negative tasks where the correct behavior is not to invoke or not to claim completion
- parity checks that compare prose promises with actual tools and scripts
- red-team cases that exploit technically true but semantically weak evidence

## Anti-overfit rule

If the skill can achieve a perfect self-score while obvious mutants still pass, the evaluation is too weak and the release should stop.
