# Design (v0.3)

Agents Arena v0.3 is an experiment bench: a spec describes a task and up to six contestants, the engine runs each contestant `repeats` times in isolation, and a scorecard says which one won on the stated objective. This document records how it is built and why.

## Architecture

```
arena_plan -> plan.py            (detect checks/setup/harnesses, draft a spec)
arena_start -> pipeline.create   (validate, preflight, write arena.json + refs)
            -> jobs.in_background / foreground
               pipeline.execute: baseline -> run_one x (contestants x repeats) -> finish
                                 finish: judge.score_runs -> judge.run_finals -> scorecard.build
arena_status / arena_result / arena_history read the store
```

| Module | Role |
|---|---|
| `models.py` | Pydantic types. Spec side: `Spec`, `Contestant`, `Overlay`, `Check`, `JudgeSpec`. Runtime side: `Arena`, `Run`, `Snapshot`, `Gate`, `Metrics`, `Score`, `Match`, `Scorecard`, `Job`. `Spec` forbids unknown keys |
| `harness.py` | One adapter per harness (claude, codex, opencode, command): agent argv, judge argv, preflight, clean-environment recipe, metrics parsing |
| `workspace.py` | Per-run worktree and clean home, overlays, snapshots, cleanup |
| `checks.py` | Check execution, the base-commit baseline, deterministic gates |
| `pipeline.py` | Preflight, arena creation, the per-run flow, `execute`/`finish`, `promote` |
| `judge.py` | Blind rubric scoring per run and both-order finals; JSON extraction; `best_run`, `pair_winner` |
| `scorecard.py` | Per-contestant medians, winner rules, markdown and HTML, history record |
| `plan.py` | `arena_plan`: detects checks and setup, installed harnesses, builds questions or a draft |
| `arena.py` | The five operations. Each is an MCP tool and a CLI subcommand |
| `server.py`, `cli.py` | FastMCP registration plus the `arena://guide` resource; argparse CLI with the same parameter names, plus `init` and `eval-judge` |
| `evals.py` | `eval-judge`: seeded pairs run as real arenas, then judged directly |
| `store.py` | Persistence: flock-guarded JSON, atomic writes, append-only logs, history |
| `proc.py` | The one subprocess helper: timeouts, process groups, owner tracking, log capture |
| `git.py` | Git plumbing: snapshot commits, refs, worktrees, patches, branches |
| `jobs.py` | Background jobs with progress and MCP progress notifications |
| `scaffold.py` | `init`: writes `GUIDE.md` as a skill per agent |

State changes are read-modify-write under an `flock` on `arena.lock` (`Store.mutate`). The lock is re-entrant per thread and never held while an agent runs.

## Data layout

```
<repo>/.agents-arena/                 self-ignoring (its .gitignore is "*")
  current                             id of the most recently started arena
  history.jsonl                       one record per finished arena (arena_history reads this)
  arenas/<id>/
    arena.json  arena.lock  events.jsonl
    spec.json                         the validated spec
    jobs/<job>.json
    runs/<run>/                       prompt.md, patch.diff, stdout.log, stderr.log
    judge/<rubric-run | final-order>/ prompt.md, schema.json, output.json, logs
    result.json  report.md            written when the arena finishes
    report.html                       on arena_result(html=true)
    winner.diff                       on arena_result(promote=...)

refs/arena/<id>/base                  the base commit
refs/arena/<id>/<run>-base            base + the run's overlays/setup output (only when it has any)
refs/arena/<id>/<run>                 the run's snapshot commit

~/.cache/agents-arena/worktrees/<repo>-<hash>/<id>/<run>/{repo,home}
```

Run ids are `<contestant>-<repeat>`. Worktrees are detached checkouts, so no branches are left behind. If the cache is on a different volume than the repo, they go in a sibling `.agents-arena-worktrees/` directory instead, so clones and hardlinks stay cheap. `home` exists only for `clean` contestants and is deleted with the worktree, since it may hold a copied auth file. The arena's worktree directory, and the per-repo directory above it, are removed once they are empty.

The snapshot commit is built through a temporary index, so the agent's own index is untouched. The refs keep the commits reachable after the worktree is gone. A run's diff is measured from its own base: the arena base, or the overlay commit when overlays or `setup` changed the tree. That keeps overlays and setup output out of the contestant's patch.

## Isolation

The recipe comes from [the v0.3 spike](v0.3-isolation-spike.md), which tested claude 2.1.291, codex-cli 0.164.0 and opencode 2.1.4.

- `real`: the user's actual home, never copied or modified. Copies lose keychain and database auth.
- `clean`: a fresh `HOME` plus each harness's own variables (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `XDG_*` for opencode, `--standalone`). Redirecting only the harness variable still leaked user skills, so `HOME` is always redirected. Package caches (`UV_CACHE_DIR`, `XDG_CACHE_HOME`, npm) stay on the real paths.
- Children get `PWD` set to their real working directory. Without it opencode resolved its project from the launcher's `$PWD`.
- Judge calls run in a temporary directory outside the repo.
- `setup` and checks run in the user's environment, in the baseline and in every run, so a check can only differ because of the contestant's change. Only the agent gets the clean home.
- Agents share the repo's `.git`, so they can create branches, tags or stashes. These can't be blocked cheaply. Refs that appear under `refs/heads`, `refs/tags` or `refs/stash` during the runs are listed in the scorecard notes (`Arena.new_refs`).
- Every arena run, foreground or background, has a job record holding its pid. `arena_status` marks an arena failed when its job's process is gone. Ctrl-C calls `proc.cancel(arena_id)`, which kills the arena's agent and judge process groups and refuses new ones. They run in their own sessions, so the terminal's SIGINT doesn't reach them.

The spike also records where auth does not survive isolation, and that metrics come from different places per harness (claude's result JSON, codex's `turn.completed`, opencode's `session export`).

## Selection

1. **Eligibility.** A run is eligible if it finished, produced a non-empty change, and tripped no `disqualify` gate. The gates are `empty`, `agent_timeout`, `test_deleted`, `protected_path`, and `check_regression` (a check that passed, or did not exist, on the base commit fails on the run). `needs_human` gates (`agent_failed`, `agent_config_edited`, `secret_path`, `test_config_changed`, `skip_marker_added`, `trivial_assert_added`) and `info` gates are reported but do not exclude. Checks run once on the base commit, so only regressions count. Statistics cover eligible runs only.
2. **Rubric.** For judged objectives, every eligible run gets a blind score from 0 to 10 against the objective's rubric (`quality` and `elegance` have built-in rubrics; other text is used as the rubric). The judge sees the task, the patch and the check evidence, with no contestant names.
3. **Final.** Each contestant's best run (highest score, then fewest failing checks, then fewest changed lines) meets each other contestant's best run, judged in both orders. A run wins a pair only if it wins in every order. A split or a tie is no signal, and an unusable judge output counts as a tie.
4. **Winner by objective.**
   - Judged: most pair wins, then highest median score, then highest eligible rate. A tie on all three is reported as a tie ("your call"), with no winner. With one contestant there is no final and the winner is the only eligible contestant.
   - `speed`, `tokens`, `cost`: lowest median of that metric among eligible contestants, ties broken by eligible rate. If no one reported the metric, there is no winner.
   - No eligible run anywhere: no winner, and the verdict says so.
5. **Winner run.** The run that `promote` ships is the contestant's best run (judged) or its best run on the metric (metric objectives).

A tie is a valid result. The scorecard states how the winner was decided, and notes list per-run errors.

## What was kept or cut from v0.2

Kept: the typed Pydantic core and flat modules, snapshot commits under `refs/arena/`, detached worktrees, the `flock` store, the single subprocess helper, baseline checks and regression-only gating, the reward-hacking tripwires, blind judging in both orders with a strict schema and an isolated judge, `eval-judge`, `init`, and MCP tools being plain functions with a CLI parity test.

Cut:
- **The 9 tools** (open, run, check, judge, close, fork, refine, promote, status). A run is now a pipeline, so five tools cover plan, start, status, result and history.
- **`config.toml`.** Everything is in the spec, so a run is reproducible from `spec.json`.
- **Variants.** Replaced by contestants with a harness, model, baseline and overlays, because the interesting experiments vary those, not only a strategy string.
- **Pairwise Copeland over every survivor.** Replaced by per-run rubric scores plus a final over each contestant's best run. With repeats, comparing every pair of runs costs too many judge calls.
- **Checkpoints, fork, refine, explore-then-fork, distinguishing-test tie-break, agentic final judge.** They served the single-task variant search, not controlled comparison, and added most of the v0.2 surface. They can return if a use case needs them.
- **The manual runner and the ledger.** The scorecard history replaces the ledger.
- **v0.2 arena state.** It can't be read.

## Deferred and rejected

- **LayerFS.** No Python binding, needs Node and a Rust build, runs in Docker on macOS (so host `codex` and `pytest` can't use its mounts), no git interop, and its store isn't crash-durable. Git refs and detached worktrees already give durable, git-native workspaces. Revisit if it ships native macOS support or a Python binding.
- **MCP background tasks.** In fastmcp they need an extra, async tools, and client support. Background threads plus `arena_status` polling work with every client. `wait=true` sends progress notifications.
- **Elo, Bradley-Terry, Swiss, knockout, MCTS.** Elo depends on match order, and Bradley-Terry intervals always overlap at this size. Both-order finals over 6 or fewer best runs are cheap and make position bias visible as a tie.
- **A regex blocklist for check commands.** It was trivially bypassed and gave no real protection. Isolation is the trust model's job, and v0.3 states plainly that it runs agent-written code on your machine.
