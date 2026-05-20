# Integration Patterns

## With repo-sentinel

Repo Sentinel should remain the blocking guardrail for dangerous shell commands and sensitive paths. Shadow PR Arena focuses on variants, scoring and telemetry.

## With python-tdd

Add a `test_first` variant for bug fixes. Pairwise judges should penalize untested fixes when a regression is reproducible.

## With webqa-devtools

If frontend files change, require browser evidence. Store browser reports under `.webqa-devtools/reports/` and reference them in variant notes.

## With agentops-continuity

Record the winning decision and rejected alternatives into the AgentOps ledger.

## With repo-docs-wiki

If the winning patch changes architecture, export a docs/ADR update as part of the PR bundle.
