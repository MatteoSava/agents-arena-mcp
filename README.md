# Shadow PR Arena MCP

Shadow PR Arena is a local FastMCP server and CLI for comparing multiple agentic coding variants in isolated Git worktrees.

It is designed for Claude Code, Codex, and OpenCode workflows where the first patch is not necessarily the best patch.

## What it does

```text
task
  -> arena_open()
  -> isolated variant worktrees
  -> agent/manual implementation runs
  -> diff + check + telemetry ledger
  -> pairwise judge tournament
  -> Elo scoreboard
  -> winner patch / PR bundle
```

## Core ideas

- **Variants, not one-shot patches**: compare minimal patch, test-first, clean boundary, policy object, adapter boundary, or custom strategies.
- **Pairwise judging**: judge all variant pairs and update Elo ratings.
- **Hard gates first**: failing checks or critical risks cannot beat a safe passing variant.
- **Run telemetry**: record runner, model, latency, token usage when available, stdout/stderr, JSONL events, prompt hash, diff stats, checks, and artifacts.
- **Safe promotion**: default winner promotion exports a patch. It does not apply to the base branch unless explicitly requested.
- **Client ready**: includes scaffold for Claude Code, Codex, OpenCode, `.agents/skills`, and optional hooks.

## Install the Python package

```bash
cd agents-arena-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Install scaffold into a repo

```bash
python install.py --target /path/to/repo --append-agents --append-claude
```

This creates:

```text
.shadow-pr-arena/
.claude/skills/shadow-pr-arena/SKILL.md
.codex/config.shadow-pr-arena.example.toml
.opencode/skills/shadow-pr-arena/SKILL.md
.agents/skills/shadow-pr-arena/SKILL.md
AGENTS.shadow-pr-arena.md
CLAUDE.shadow-pr-arena.md
```

## CLI example

```bash
cd /path/to/repo
shadow-pr-arena open "Refactor billing retries without changing behavior" \
  --variant minimal_patch \
  --variant test_first \
  --variant policy_object \
  --variant adapter_boundary
```

Get implementation briefs:

```bash
shadow-pr-arena brief <arena-id> minimal_patch
shadow-pr-arena brief <arena-id> policy_object
```

After implementing in each worktree:

```bash
shadow-pr-arena record <arena-id> minimal_patch
shadow-pr-arena checks <arena-id> minimal_patch --command "python -m pytest -q"
```

Run pairwise tournament and render scoreboard:

```bash
shadow-pr-arena judge-all <arena-id> --judge-runner heuristic
shadow-pr-arena scoreboard <arena-id>
```

Export winner patch:

```bash
shadow-pr-arena promote <arena-id> --mode patch
```

## Agent runners

### Manual runner

The default `manual` runner writes prompts and run metadata, then waits for you or an interactive coding agent to implement the variant.

```bash
shadow-pr-arena run-agent <arena-id> test_first --runner manual
```

### Codex runner

If the Codex CLI is installed:

```bash
shadow-pr-arena run-agent <arena-id> test_first --runner codex --model gpt-5.5
```

The runner captures stdout, stderr, JSONL events where available, token usage when present, wall time, model, prompt hash, and final output path.

### OpenCode runner

If OpenCode is installed:

```bash
shadow-pr-arena run-agent <arena-id> clean_boundary --runner opencode --model anthropic/claude-sonnet-4-5
```

## Pairwise judge runners

```bash
shadow-pr-arena judge <arena-id> minimal_patch policy_object --judge-runner heuristic
shadow-pr-arena judge-all <arena-id> --judge-runner codex --judge-model gpt-5.5
shadow-pr-arena judge-all <arena-id> --judge-runner opencode
```

`heuristic` is deterministic and useful for local testing. `codex` and `opencode` are external judge adapters that run read-only comparison prompts and record judge telemetry.

## MCP server

Run:

```bash
agents-arena-mcp
```

Or:

```bash
python -m agents_arena_mcp.server
```

### Claude Code project config example

The scaffold includes `.claude/settings.shadow-pr-arena.example.json`. You can also add:

```bash
claude mcp add --transport stdio --scope project shadow-pr-arena -- \
  python -m agents_arena_mcp.server
```

### Codex config example

Copy or merge `.codex/config.shadow-pr-arena.example.toml` into your Codex config.

### OpenCode config example

Copy or merge `opencode.json.shadow-pr-arena.example` into your OpenCode configuration.

## Files written in the target repo

```text
.shadow-pr-arena/
├── policy.json
├── state/
│   ├── current-arena.json
│   ├── arenas.jsonl
│   ├── pairwise-results.jsonl
│   └── runs.jsonl
├── runs/
│   └── <run-id>/
│       ├── metadata.json
│       ├── prompt.md
│       ├── stdout.log
│       ├── stderr.log
│       ├── events.jsonl
│       └── final.md
├── patches/
│   ├── <arena-id>-<variant>.patch
│   └── <arena-id>-winner-<variant>.patch
└── reports/
    ├── <arena-id>-scoreboard.md
    └── <arena-id>-pr-summary.md
```

Worktrees live outside the repo by default:

```text
../.shadow-pr-arena-worktrees/<repo-name>/<arena-id>/<variant>/
```

## Safety defaults

- Refuses dirty repo by default unless `include_current_diff=true`.
- Uses Git worktrees for isolation.
- Blocks destructive commands in check execution.
- Does not auto-apply winner patches.
- Uses read-only judge prompts for external judges.
- Treats critical secret-like file paths as hard-gate failures.

## Typical workflows

### Arena-driven refactor

```text
1. open arena with 4 strategies
2. run agent/manual implementation per worktree
3. record variants
4. run tests/checks
5. judge all pairs
6. inspect Elo scoreboard
7. export winner patch
```

### Bug that keeps returning

```text
1. variants: minimal_patch, test_first, robust_boundary
2. test_first must add regression evidence
3. pairwise judge penalizes untested fixes
4. scoreboard explains why the winner is less likely to regress
```

### Dependency migration

```text
1. variants: compatibility_layer, direct_migration, module_by_module
2. score by checks, blast radius, rollback ease, and maintainability
3. export PR bundle with rejected alternatives
```
