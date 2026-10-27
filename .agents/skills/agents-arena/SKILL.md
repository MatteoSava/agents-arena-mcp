---
name: agents-arena
description: >
  Compete several implementations of one coding task in isolated git worktrees and pick a winner on
  evidence. Use when the user says "use the arena", "compare approaches", "compete variants", or wants
  more than one attempt at a risky change.
---

# Agents Arena workflow

The `agents-arena` MCP server gives each strategy its own detached git worktree, gates every attempt
on checks against the base commit, and judges survivors blind: anonymized A/B, both orders.

## Steps

1. **Open.** `arena_open(task="...", variants=["minimal_patch", "test_first"])`.
   - Pass `carry_uncommitted=true` if the user has work in progress that variants should start from.
   - Note the returned `arena_id` and each variant's `workspace` and brief.
2. **Implement** each variant, inside its `workspace` only. There are two ways:
   - Do it yourself: edit files in each workspace. You may use parallel sub-agents, one per workspace.
   - Or delegate: `arena_run(runner="codex" | "claude" | "opencode", wait=false)`, then poll `arena_status`
     until the job is `done`.
3. **Check.** `arena_check()` snapshots every variant (a new checkpoint) and runs the configured checks.
   Checks also run once on the base commit, so only *regressions* count against a variant.
   - These disqualify a variant: deleting tests, touching CI or agent config, and new check failures.
   - These need a human: added skip or xfail markers, `assert True`, conftest edits, and secret paths.
4. **Judge.** `arena_judge(wait=false)`, then poll `arena_status`. The decision is one of:
   - `winner`: safe to promote.
   - `needs_human`: show the user `.agents-arena/arenas/<id>/report.md` and ask them to choose.
   - `no_viable`: report why, and do not promote.
5. **Promote.** `arena_promote(mode="branch")` creates `arena/<id>-<variant>` without touching the
   user's checkout. Use `mode="apply"` only when the user asks for it.
6. **Close.** `arena_close()` removes worktrees and refs. Reports are kept.

## Optional

- **Explore first:** `arena_open(explore=true)`, implement or run the `explore` variant, `arena_check()`,
  then `arena_fork(source="explore")` to branch every strategy from its checkpoint.
- **Unresolved decision:** `arena_refine()` forks the top two with the judge's critique in their brief.
  Then run, check and judge again. The number of refine rounds is capped by config.

## Rules

- Never edit the main checkout while an arena is open, and never commit inside a variant workspace.
- Do not "fix" a variant's flags (for example, deleted tests) by hand to make it win.
- Report the decision honestly. A `needs_human` result is a valid outcome.
