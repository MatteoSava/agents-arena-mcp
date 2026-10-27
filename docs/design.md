# Design

This document records why Agents Arena v0.2 works the way it does and what was deliberately left out.

## Lifecycle and state

`.agents-arena/` lives in the main repo and ignores itself, except for `config.toml` and `.gitignore`:

```
.agents-arena/
  config.toml                 committed; packaged defaults fill in anything unset
  current                     id of the most recently opened arena
  ledger.jsonl                one outcome record per judged/promoted arena (for later judge calibration)
  evals/                      eval-judge results
  arenas/<id>/
    arena.json  arena.lock  events.jsonl
    variants/<name>/patch-<n>.diff  extra-brief.md
    runs/<run>/   prompt.md stdout.log stderr.log
    judge/<match>/ prompt.md A.diff B.diff schema.json output.json
    jobs/<job>.json
    report.md  winner.diff  pr-summary.md
```

- **Worktrees** are detached checkouts under `~/.cache/agents-arena/worktrees/<repo>-<hash>/<arena>/<variant>`.
  If the cache is on a different volume, they go in a sibling directory instead, so APFS clones and uv
  hardlinks keep working. Since the worktrees are detached, no branches are left behind.
- **Checkpoints.** `arena_check` commits the full working tree of each variant (tracked and untracked,
  minus ignored files) to `refs/arena/<id>/<variant>/<n>`. It builds the commit through a temporary
  index file, so the agent's own index is never touched. The temporary index is a copy that keeps the
  original's mtime; git's racy-entry check depends on it, and a fresh mtime would make same-second,
  same-size edits invisible. Every diff and patch is commit-to-commit, so it is deterministic.
- **Uncommitted work.** With `carry_uncommitted=true`, your dirty tree is snapshotted and that commit
  becomes the arena base. Your own changes are therefore never credited to a variant.
- **Concurrency.** Every state change is a read-modify-write under an `flock` on `arena.lock`. The lock
  is re-entrant per thread and is never held while an agent runs.

## Selection

1. **Gates.** Each check result is compared with the same check on the base commit.
   - These disqualify a variant: empty diff, deleted test files, protected paths, and checks that pass on
     base but fail on the variant.
   - These require a human: secret paths, test-config edits, added skip/xfail markers, and `assert True`.
   - These are reported only: edits to existing tests (legitimate for test-first work), and checks that
     already fail on base.
2. **Dedupe.** Patches with the same whitespace-normalized hash are judged once.
3. **Cap.** Survivors are capped at `max_survivors` (default 5), ranked by the deterministic key.
4. **Judge.** Every ordered pair gets its own call, with labels A and B only: no variant names, branch
   names or paths. Each call runs in an empty directory with user config ignored, and the answer must
   match a strict schema. If the output can't be used, it counts as a tie, and the reason is recorded.
5. **Decide.** A variant wins a pair only if it wins in both orders. The Copeland score is pair wins
   minus pair losses.
   - Ties at the top are broken deterministically: fewer failing checks, then fewer review flags, then
     a smaller diff. The report names the rule that decided.
   - If they are still tied, the result is `needs_human`. A winner that carries review flags is also
     `needs_human`.
   - If no variant survives the gates, the result is `no_viable`.

### Why not Elo or Bradley-Terry?

Online Elo depends on match order ([2311.17295](https://arxiv.org/abs/2311.17295)). Bradley-Terry with
bootstrap confidence intervals is order-invariant, but with 2–5 variants the intervals always overlap,
so it would end in `needs_human` every time while looking rigorous. Copeland over both-order verdicts
is easier to explain and makes position bias visible as a tie. Bradley-Terry may still be worth it as a
cross-arena prior per strategy, once the ledger holds about 30 or more arenas.

### Why not knockout, Swiss or MCTS?

Knockout and Swiss rounds don't pay off at 5 or fewer survivors: judging every pair in both orders is
only 12 calls at n=4. MCTS needs a value function. Bounded search gets most of the benefit:
explore-then-fork ([SWE-Replay](https://arxiv.org/abs/2601.22129)), a distinguishing-test tie-break
([S*](https://arxiv.org/abs/2502.14382)), one depth-capped refinement round
([DARS](https://arxiv.org/abs/2503.14269)), and an agentic final round
([Agent-as-a-Judge](https://arxiv.org/abs/2410.10934)). All of these are opt-in.

## Trust model

Check commands come only from the main repo's `config.toml` or from the calling agent, and run with
`sh -c` on the host. They execute agent-written code with your privileges, the same as running
`make test` on an untrusted branch, so isolation comes only from the runner's sandbox. The v0.1 regex
command blocklist was removed: it was trivially bypassed (`sh -c`, `python -c`) and so offered no real
protection.

## LayerFS

Evaluated and deferred. LayerFS has no Python binding and needs Node plus a Rust build. On macOS it runs
inside Docker, so the host `codex` and `pytest` can't work in its mounts. It has no git interop, and its
store is not crash-durable. Git refs, detached worktrees and copy-on-write clones already give durable,
git-native checkpoints and forks. A `WorkspaceBackend` protocol will be extracted only when a second
backend actually exists. Revisit if LayerFS ships native macOS support or a Python binding, or if runs
need more than about 8 variants on Linux CI.

## MCP

Every operation is a plain function registered with `mcp.tool(fn)`. Its `Annotated[..., Field(description)]`
parameters give clients full input schemas, and the CLI exposes exactly the same parameters, which a
test enforces. Long runs use background threads plus `arena_status` polling, which works with every
client. Calls with `wait=true` also send MCP progress notifications. MCP background tasks are deferred:
in fastmcp 3.3.1 they need the `fastmcp[tasks]` extra (pydocket) and async tools, and clients must
support the tasks protocol.
