# Stuck Escalation

## Purpose

Persistence must be bounded. Escalation is valid only after the search space has been explored in materially different ways.

## What counts as materially different

These usually count as different strategies:

- reading code paths vs. reproducing with a failing command
- changing the hypothesis and testing a different subsystem
- switching from static inspection to a bounded runtime experiment
- replacing one verification method with a meaningfully stronger one

These usually do not count:

- re-running the same command with no new evidence
- restating the same theory in new words
- repeating the same edit with cosmetic variation

## Escalation package

Before using `stuck_escalation`, provide:

- the distinct strategy fingerprints already attempted
- the receipts for each failed strategy
- a concrete explanation of why more local retries would just repeat the same search space
- the narrowest blocker statement you can defend

## Reporting rule

When escalating, say what was tried, what failed, what was learned, and what exact missing input or authority would unlock progress.
