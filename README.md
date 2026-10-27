<div align="center">

# ⚔️ Agents Arena

**Stop accepting the first patch. Make coding agents compete, then pick the winner on evidence.**

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)
[![MCP](https://img.shields.io/badge/protocol-MCP-purple.svg)](https://modelcontextprotocol.io)

</div>

Agents Arena is a local MCP server and CLI. It runs several strategies for one task, each in an isolated
git worktree, and gates every attempt on checks against the base commit. It judges the survivors **blind
and in both orders**, then either promotes a winner or tells you honestly that a human has to decide.
It works with Claude Code, Codex and OpenCode, or with edits you make yourself.

```
 "fix the retry bug"
        │
  ┌─────┼──────────┐
  ▼     ▼          ▼
minimal test     clean        ← parallel, one detached worktree each
patch   first    boundary
  │     │          │
  └─────┴────┬─────┘
             ▼
   checks vs. base-commit baseline     ← only regressions count
   gates: deleted tests, CI edits, skip markers, secrets
   dedupe identical patches
             ▼
   blind A/B judging, both orders      ← a split verdict is a tie
             ▼
   Copeland decision → winner | needs_human | no_viable
```

## Why it works this way

Generating candidates is cheap; picking the right one is the hard part. The design follows the research:

- **Position bias is real.** Swapping the order of two answers flipped LLM-judge verdicts in 66 of 80
  cases ([2305.17926](https://arxiv.org/abs/2305.17926)). Every pair is judged A·B and B·A, and a
  disagreement counts as a tie.
- **Judges favor themselves** ([2404.13076](https://arxiv.org/abs/2404.13076)). Variants are anonymized,
  and you can use a judge from a different model family than the generator.
- **Agents cheat on tests, and stronger ones cheat more** ([ImpossibleBench](https://arxiv.org/abs/2510.20270)).
  Deleting tests disqualifies a variant. Skip markers and trivial asserts go to a human.
- **Passing tests aren't proof** ([2503.15223](https://arxiv.org/abs/2503.15223)). Checks run once on the
  base commit, so a variant fails only for regressions it introduced.
- **Branching from checkpoints is cheaper than starting over** ([SWE-Replay](https://arxiv.org/abs/2601.22129)).
  `arena_open(explore=true)` + `arena_fork` lets every strategy start from one shared exploration.

More detail is in [docs/design.md](docs/design.md).

## Install

```bash
# MCP server for Claude Code
claude mcp add agents-arena -- uvx --from git+https://github.com/MatteoSava/agents-arena-mcp@v0.2.0 agents-arena-mcp

# CLI
uv tool install git+https://github.com/MatteoSava/agents-arena-mcp@v0.2.0
cd your-repo && agents-arena init --skills claude,codex,opencode
```

`init` writes `.agents-arena/config.toml` (commit it), a self-ignoring `.gitignore`, and the workflow
skill for each agent you name.

## Configure

Edit `.agents-arena/config.toml`:

```toml
default_variants = ["minimal_patch", "test_first", "clean_boundary"]
default_runner = "claude"          # or codex / opencode / manual
setup = "uv sync"                  # run in each new worktree
checks = [{ name = "tests", cmd = "uv run pytest -q" }, { name = "lint", cmd = "uv run ruff check ." }]

[judge]
runner = "codex"                   # use a different model family than default_runner
model = ""
```

Runners and judges are argv templates (`[runners.*]`, `[judges.*]`), so a CLI flag change only needs a
config edit, not a release. Judges run in an empty directory with your user config ignored, and must
return JSON that matches a strict schema.

## Use

| MCP tool | CLI | What it does |
|---|---|---|
| `arena_open` | `agents-arena open "task" --variant a --variant b` | One worktree per strategy; returns briefs |
| `arena_status` | `agents-arena status` | States, checkpoints, checks, gates, decision, jobs |
| `arena_run` | `agents-arena run --runner claude` | Runs agents in parallel (`wait=false` starts a background job) |
| `arena_check` | `agents-arena check` | Takes a checkpoint, runs checks vs. the baseline, applies gates |
| `arena_judge` | `agents-arena judge` | Judges every pair blind in both orders, decides, writes `report.md` |
| `arena_promote` | `agents-arena promote --mode branch` | `patch` / `branch` (your checkout is untouched) / `apply` |
| `arena_close` | `agents-arena close` | Stops processes, removes worktrees and `refs/arena/<id>/` |
| `arena_fork` | `agents-arena fork explore` | Forks variants from `variant@checkpoint` |
| `arena_refine` | `agents-arena refine` | Forks the unresolved top two with the judge's critique (depth-capped) |

The report is also available as the MCP resource `arena://{arena_id}/report`.

A typical session:

```text
arena_open(task="Make retries respect Retry-After", variants=["minimal_patch", "test_first"])
arena_run(runner="claude", wait=false)      → poll arena_status until the job is done
arena_check()
arena_judge(wait=false)                     → decision: winner test_first
arena_promote(mode="branch")                → branch arena/<id>-test_first
arena_close()
```

## Tune the judge

```bash
agents-arena eval-judge --judge codex
agents-arena eval-judge --judge claude --model sonnet
```

This command runs 8 seeded pairs with known answers through the real judging path. They include a
correct fix vs. a no-op, a test-deleting cheat, a skip-marker cheat, a hard-coded special case, an API
break, verbose vs. minimal, and a near-identical pair. It reports **accuracy**, **order-flip rate**,
**tie rate**, and how often the judge picks the label "A". Results are saved in `.agents-arena/evals/`,
so you can compare prompt or model changes. The prompt itself is a template you can override with
`[judge] template = "path"`.

## Opt-in extras

These options go in the `[judge]` section of the config:

- `distinguish = true`: when a pair splits, the judge proposes a command where the two variants should
  differ. It runs in both checkouts and the pair is judged again with the outputs ([S*](https://arxiv.org/abs/2502.14382)).
- `agentic_final = "claude-agentic"`: a tool-using judge reviews the unresolved top two read-only,
  directly in their checkouts ([Agent-as-a-Judge](https://arxiv.org/abs/2410.10934)).
- `max_refine_depth`: caps how many `arena_refine` rounds can run.

## Trust model

Checks run agent-written code on your machine with your privileges, the same as running `make test` on
an untrusted branch. Isolation comes only from the agent runner's sandbox. `config.toml` is always read
from the main repo, never from a variant. Supported platforms are macOS and Linux. Windows, network
filesystems, git submodules and Git LFS are not supported.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run basedpyright
```

## License

MIT
