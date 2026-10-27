# Agents Arena

An experiment bench for coding agents. You describe a task and a set of contestants. Each contestant runs the task several times, each run in its own git worktree. The arena checks every run against the base commit, judges the survivors blind, and returns a scorecard.

It is a local MCP server and CLI. It works with Claude Code, Codex and OpenCode.

## What it is for

1. **Comparing harnesses.** Claude Code vs Codex vs OpenCode on the same task and the same checks.
2. **A/B testing a skill or an instruction edit.** Same harness and model, one contestant per version of the `SKILL.md` or `CLAUDE.md`.
3. **Comparing speed, tokens and cost.** Metric objectives skip the judge and rank by the median of the runs.
4. **Finding the most elegant solution.** Give each contestant a different concrete strategy, and let a rubric judge pick.

## Contestants

A contestant is **harness + model + baseline + overlays + strategy**.

| Field | Meaning |
|---|---|
| `harness` | `claude`, `codex`, `opencode`, or `command` (your own argv) |
| `model` | Passed to the harness. Empty means the harness default. opencode always needs an explicit model |
| `baseline` | `clean` or `real` (below) |
| `overlays` | Files copied in before the run: `repo:<path>` into the worktree, `home:<path>` into the clean home |
| `strategy` | Optional text added to the brief, for example "write the test first" |

### Baselines

- **`real`** (default) uses your actual home, untouched. Your skills, plugins, MCP servers and global instructions all load. The arena never writes into it, but the harness still records its usual session history there. Only `repo:` overlays are allowed.
- **`clean`** gives the run a fresh `HOME`, so only built-in behavior and the overlays you add are present. Use it for controlled A/Bs. Auth differs per harness:
  - claude: the macOS keychain login doesn't carry over. Set `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) or `ANTHROPIC_API_KEY`.
  - codex: `auth.json` is copied into the clean home.
  - opencode: stored logins live in a database that isn't copied. Only providers keyed by environment variables work (for example `OPENROUTER_API_KEY`), and you must set `model`, for example `openrouter/openai/gpt-5-mini`.

Which baseline to use matters. In one of our tests, a `CLAUDE.md` A/B on `real` showed no difference, because the global `~/.claude/CLAUDE.md` (TDD, TODO.md) shaped every run. If you A/B instructions, use `clean`. Preflight checks the auth requirements above and fails before any run starts.

## Install

```bash
# MCP server for Claude Code
claude mcp add agents-arena -- uvx --from git+https://github.com/MatteoSava/agents-arena-mcp@v0.3.0 agents-arena-mcp

# CLI
uv tool install git+https://github.com/MatteoSava/agents-arena-mcp@v0.3.0
cd your-repo && agents-arena init --skills claude,codex
```

`init` writes the workflow skill for each agent you name (`claude`, `codex`, `opencode`). The same guide is served as the MCP resource `arena://guide`.

Run arenas from a shell that has your provider keys. A tmux server started before a variable was set does not pass it to new sessions.

## The flow

| MCP tool | CLI | What it does |
|---|---|---|
| `arena_plan(request, mode)` | `agents-arena plan "..." [--mode autopilot]` | Drafts a spec. `interview` returns questions to ask you; `autopilot` returns a filled draft. Runs nothing |
| `arena_start(spec, wait)` | `agents-arena start spec.toml` | Validates, runs preflight, then runs every contestant x repeat, judges and scores. `wait=false` runs in the background |
| `arena_status(arena_id)` | `agents-arena status` | Each run's state, exit status and eligibility, plus job progress |
| `arena_result(arena_id, html, promote)` | `agents-arena result --html --promote branch` | The scorecard. `html` writes a self-contained report. `promote` ships the winner: `patch`, `branch` (no checkout change) or `apply` (only if it applies cleanly) |
| `arena_history(contestant, task_contains, limit)` | `agents-arena history` | Past results, newest first, for trends across edits |

The CLI always waits (a background run would die with the process). Use the MCP server for background runs.

An example conversation:

```text
You:    A/B my new retry-handling skill against the old one on this repo.
Agent:  arena_plan(request, mode="interview") -> asks: which checks? which harness? how many repeats?
You:    pytest, claude, 3 repeats, judge with codex.
Agent:  shows the spec, you approve, arena_start(spec) -> polls arena_status
Agent:  arena_result(html=true) -> "skill-v2 won the final in both orders", 3/3 eligible vs 2/3
You:    Promote it.
Agent:  arena_result(promote="branch") -> branch arena/<id>-skill-v2
```

## A spec

Specs can be JSON (the MCP call) or TOML (the CLI). Unknown keys are rejected, check names and contestant names must be unique, and 1 to 6 contestants are allowed.

```toml
task = "Make retries respect the Retry-After header"
objective = "quality"          # quality | elegance | speed | tokens | cost | any rubric text
repeats = 3
setup = "uv sync"              # runs on the base commit and in each run's worktree before the agent

[[checks]]
name = "tests"
cmd = "uv run pytest -q"

[[contestants]]
name = "skill-v1"
harness = "claude"
baseline = "clean"

[[contestants.overlays]]
from = "~/skills/retry-v1/SKILL.md"
to = "repo:.claude/skills/retry/SKILL.md"

[[contestants]]
name = "skill-v2"
harness = "claude"
baseline = "clean"

[[contestants.overlays]]
from = "~/skills/retry-v2/SKILL.md"
to = "repo:.claude/skills/retry/SKILL.md"

[judge]
harness = "codex"              # prefer a different family than the contestants
```

Other fields: `base_ref` (default `HEAD`), `max_parallel` (4), `run_timeout_sec` (1800), `check_timeout_sec` (600), `judge.timeout_sec` (600). Overlays are never counted as the contestant's code: the diff is measured from the base commit plus the overlays (and `setup` output).

## Objectives and judging

- **Judged** (`quality`, `elegance`, or any other text, which becomes a custom rubric): each eligible run gets a blind rubric score from 0 to 10. Then each contestant's best run meets every other contestant's best run in a final, judged in both orders (A/B and B/A). A run wins a pair only if it wins in both orders. A split or a tie counts as no signal.
- **Metric** (`speed`, `tokens`, `cost`): no judge. The contestant with the lowest median wins. Cost is shown only for harnesses that report it. codex reports tokens but no dollars.

The judge sees anonymized diffs and the check evidence. It runs in a temporary directory outside your repo.

The scorecard has one row per contestant: runs, **eligible** (share of runs that produced a non-empty change and tripped no disqualifying gate), median score, tokens, time, cost and diff lines, plus flags for gates that fired. With one repeat the "medians" are single values, so use 3 to 5 repeats for comparisons you want to trust.

### Gates

Computed on each run's patch and checks, before judging. Checks run once on the base commit, so a run is held only for regressions it introduced.

| Severity | Gates |
|---|---|
| Disqualify (not eligible) | `empty` (no changes), `agent_timeout`, `test_deleted`, `protected_path` (CI files, `.agents-arena/`), `check_regression` |
| Needs human (shown, still eligible) | `agent_failed` (non-zero exit), `agent_config_edited`, `secret_path`, `test_config_changed`, `skip_marker_added`, `trivial_assert_added` |
| Info | `existing_test_edited`, `check_failing_on_base_too` |

## eval-judge

```bash
agents-arena eval-judge --judge codex
agents-arena eval-judge --judge claude --model sonnet
```

Runs 8 seeded pairs with known answers through the real final-judging path: a correct fix vs a no-op, a test-deleting cheat, a skip-marker cheat, a hard-coded special case, an API break, verbose vs minimal, and a near-identical pair. It reports accuracy, order-flip rate, tie rate, and how often the judge picks the label "A". Results are saved under `~/.cache/agents-arena/evals/`.

Baselines measured on 2026-10-27:

| Judge | Accuracy | Order-flip rate | Picked label A |
|---|---:|---:|---:|
| codex 0.164.0 | 0.875 | 0.0 | 0.5 |
| claude 2.1.291 | 0.875 | 0.0 | 0.5 |
| opencode, openrouter/openai/gpt-5-mini | 0.75 | 0.125 | 0.438 |

claude's only miss was `06_near_identical`. Preflight for the judge is skipped in this command.

## Trust model

Contestants and checks run agent-written code on your machine with your privileges, the same as running `make test` on an untrusted branch. Worktrees isolate files, not processes. A `real` contestant also has access to your usual config and credentials. Check and setup commands come only from the spec. Supported platforms are macOS and Linux. Windows, network filesystems, git submodules and Git LFS are not supported.

## Verified versions

claude 2.1.291, codex-cli 0.164.0, opencode 2.1.4. Other versions may work; the CLI flags and output formats are what could break.

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check . && uv run basedpyright
```

## More

- [docs/design.md](docs/design.md): architecture, data layout, selection logic.
- [docs/v0.3-isolation-spike.md](docs/v0.3-isolation-spike.md): how each harness is isolated, and what the spike found.

MIT license.
