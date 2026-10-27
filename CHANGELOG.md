# Changelog

## 0.3.0 (2026-10-27)

Agents Arena is now an experiment bench: contestants (harness + model + baseline + overlays + strategy) run several times each, and a scorecard says which won. See `docs/design.md` and `docs/v0.3-isolation-spike.md`.

### Breaking

- The 9 MCP tools became 5. Old tool -> new tool:

  | v0.2 | v0.3 |
  |---|---|
  | `arena_open`, `arena_run`, `arena_check`, `arena_judge`, `arena_close`, `arena_fork`, `arena_refine` | `arena_plan` + `arena_start` + `arena_status` |
  | `arena_promote` | `arena_result(promote=)` |
  | `arena_status` | `arena_status` (stays) |
  | (new) | `arena_history` |

- `config.toml` is gone. Everything (checks, setup, judge, timeouts) lives in the spec.
- v0.2 arenas can't be read.

### Added

- Contestants with harness, model, baseline, overlays and strategy; `clean` and `real` baselines.
- Repeats, with per-contestant medians.
- Objectives: `quality`, `elegance`, `speed`, `tokens`, `cost`, or a custom rubric.
- A blind rubric score per run, then a both-order final between contestants' best runs.
- Scorecard (with an "eligible" column), `history.jsonl` and `arena_history`, and a self-contained HTML report.
- `agents-arena eval-judge` on the new pipeline (8 seeded pairs).
- `setup`: a shell command run on the base commit and in each run's worktree before the agent.
- Gates `agent_timeout` (disqualifies) and `agent_failed` (needs a human).
- The `arena://guide` MCP resource, and `agents-arena init --skills` installing the same guide.

### Fixed (found during v0.3 real-harness verification)

- Build artifacts were captured in patches.
- Child processes inherited the launcher's `$PWD`, which made opencode explore the wrong repo.
- A timed-out agent could still win.
- Agent stderr was invisible.
- The judge ran inside the user's repo.

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
