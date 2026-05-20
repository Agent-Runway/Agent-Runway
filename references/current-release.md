# Current Release

- packaged version: v0.36
- release status: in development for the v0.36 Adversarial Audit Gate pass, with release-discipline checks extended to cover bounded falsification governance
- generation label: generation-4
- current priority theme: release correctness, mission evidence freshness, receipt uniqueness, host bridge truthfulness, bounded project learning, and adversarial audit governance
- v0.36 focus: Adversarial Audit Gate for bounded falsification before high-risk completion claims, implemented through protocol docs, schema, lint, deterministic suite, and conditional gate integration
- retained hardening: `package_skill_validation` remains a mandatory release gate and receipt nonce protection remains part of release truthfulness
- project-learning rules: `Memory is not evidence`; `Preference is not authorization`; project learning remains advisory context only
- routing boundary: common cross-project preferences route first to CLI SQLite memory when available; project pitfalls, runbooks, invariants, and project-scoped preferences route first to the project ledger
- release-gate closure: the release gate is now a direct 16-gate harness matching `references/release-gates.md`; it reports gate count, elapsed time, timeout scale, and per-gate output
- new release gate: `project_learning_lint` runs in strict mode against `references/project-learning-ledger.jsonl`
- new v0.36 release gate: `adversarial_audit_suite` runs deterministic bounded-falsification fixtures before mutation checks
- OpenCode bridge truthfulness: the bundled bridge now requires discovery from a real OpenCode plugin directory plus `ILH_OPENCODE_BRIDGE`; once discovered, it honors host environment first and falls back to OpenCode config content/files, passes configured DB/secret paths to the Python bridge, disables bridge bytecode writes, and does not claim stronger stop-hook parity
- host experiment truthfulness: `scripts/host_blocking_experiments.py` gives reproducible local evidence for Claude Code configured hooks, Pi CLI extension `tool_call` blocking, and OpenCode bridge blocking; it is recommended validation, not a mandatory release gate, because host CLIs are environment-dependent
- Pi CLI boundary: support is extension-only through `@mariozechner/pi-coding-agent@0.73.1`; this release does not claim native MCP or Claude Code `Stop` parity for Pi CLI
- convergence close: mutation harness emits per-mutant progress, release gate enforces per-check timeouts with deterministic output capture, and project learning claims are reflected in manifest, policy, tests, and static checks
