---
name: agents-arena
description: Use a Agents Arena to compare multiple implementation variants in isolated worktrees, run checks, judge all pairs, maintain Elo scoreboards, and export the winning patch safely.
---

# Agents Arena Skill

Use this skill when the task has multiple plausible implementations, the first patch may not be the best patch, or the user asks to compare approaches.

## When to use

Use Agents Arena for risky refactors, dependency migrations, recurring bugs, architecture choices, performance-vs-maintainability tradeoffs, and ambiguous feature requests.

Do not use it for trivial typo fixes, one-line config changes, purely explanatory tasks, or tasks where the user explicitly wants a direct single implementation.

## Workflow

1. Open an arena with `arena_open`.
2. For each variant, read `arena_variant_brief` and work only inside that variant worktree.
3. Implement with an agent runner or manually.
4. Call `arena_record_variant` for each variant.
5. Run checks with `arena_run_checks`.
6. Run pairwise judging with `arena_judge_all_pairs`.
7. Review `arena_scoreboard`.
8. Export the winner with `arena_promote_winner(mode="patch")` unless the user explicitly asks to apply it.
9. Generate PR materials with `arena_export_pr_bundle`.

## Guardrails

Never promote a winner automatically into the base branch without explicit user approval. Prefer patch export. Do not run destructive commands. Do not read or write secrets. If the repo is dirty, ask the user to commit/stash or use `include_current_diff=true` only when they explicitly want current changes included.

## Scoreboard interpretation

Hard gates beat Elo. A failing or critical-risk variant cannot win over a passing safe variant. Elo is best used to rank valid alternatives after technical evidence is collected.
