# Changelog

## 0.2.0 (2026-10-27)

A rebuild driven by a review of the v0.1 code and of the literature on test-time selection and LLM judges.
See `docs/design.md` for the design and the reasoning behind it.

### Breaking

- The MCP surface changed. Old tool → new tool:

  | v0.1 | v0.2 |
  |---|---|
  | `arena_open`, `arena_variant_brief` | `arena_open` (returns briefs), `arena_status(variant=...)` |
  | `arena_status` | `arena_status` (adds checkpoints, gates, jobs) |
  | `arena_run_variant_agent` | `arena_run` (all or selected variants, parallel, background) |
  | `arena_record_variant`, `arena_run_checks` | `arena_check` |
  | `arena_pairwise_judge`, `arena_judge_all_pairs`, `arena_score`, `arena_scoreboard` | `arena_judge` |
  | `arena_promote_winner`, `arena_export_pr_bundle` | `arena_promote` |
  | `arena_cleanup` | `arena_close` |
  | (new) | `arena_fork`, `arena_refine` |

- `.agents-arena/policy.json` is replaced by `config.toml`. State moves to `.agents-arena/arenas/<id>/`.
  v0.1 state is detected and refused, with cleanup instructions; there is no migration.
- Elo, scoring profiles, the heuristic judge and the command blocklist are removed.
- Requires Python 3.11 or later.

### Fixed

- Untracked and non-UTF-8 files were missing from variant diffs.
- `include_current_diff` never carried uncommitted work into variants. It is now `carry_uncommitted`.
- Cleanup leaked branches and worktree directories, and a failed open left partial state behind.
- `promote --mode branch` switched your checkout.
- The opencode runner and judge passed a flag that doesn't exist (`--dir`).
- A missing check tool or a check timeout crashed instead of being recorded.
- Read-only calls wrote state, and the "current arena" pointer moved on unrelated saves.
- Secret-path patterns flagged ordinary files such as `docs/secrets-handling.md`.
- Concurrent updates could be lost.
- The codex judge ran inside your repo with your user config and plugins.

### Added

- Blind A/B judging in both orders, a strict verdict schema and isolated judge runs.
- Copeland decision with a deterministic tie-break.
- Baseline checks on the base commit; gates for deleted tests, protected paths, skip markers and
  trivial asserts.
- Parallel runs, background jobs, and MCP progress notifications.
- Claude runner and judge; runners are config-defined argv templates.
- `agents-arena init` and `agents-arena eval-judge` (8 seeded judge cases).
- Opt-in: checkpoints and `arena_fork`, explore-then-fork, `arena_refine`, distinguishing-test
  tie-break, and an agentic final-round judge.
