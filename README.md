<div align="center">

# ⚔️ Agents Arena

**Stop accepting the first patch. Make your AI agents compete for the best one.**

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![MCP](https://img.shields.io/badge/protocol-MCP-purple.svg)](https://modelcontextprotocol.io)

</div>

---

Agents Arena is a local MCP server and CLI that pits multiple coding strategies against each other in isolated Git worktrees, judges them head-to-head, and picks a winner with an Elo scoreboard. It works with Claude Code, Codex, OpenCode, or plain manual editing.

```
  "Refactor billing retries"
           │
     ┌─────┼─────────┬────────────┐
     ▼     ▼         ▼            ▼
 minimal  test    policy      adapter
  patch   first   object     boundary
     │     │         │            │
     └─────┴────┬────┴────────────┘
                ▼
       pairwise judging
         Elo ratings
                ▼
        🏆 winner patch
```

## Why?

LLM-generated code varies wildly between runs. The same prompt can produce a minimal one-liner, a well-tested refactor, or a sprawling rewrite. Instead of hoping the first attempt is the best, Agents Arena lets you:

1. **Spin up isolated worktrees** — one per strategy, zero interference
2. **Run agents or code manually** — Codex, OpenCode, Claude Code, or your own hands
3. **Judge pairs automatically** — heuristic scoring or LLM-as-judge
4. **Pick the winner with evidence** — Elo ratings, test results, blast radius, risk flags

No cloud services. No API keys required. Everything stays local.

---

## Quick start

### Install

```bash
git clone https://github.com/MatteoSava/agents-arena-mcp.git
cd agents-arena-mcp
pip install -e .
```

### Open an arena

```bash
cd /path/to/your/repo

agents-arena open "Refactor billing retries without changing behavior" \
  --variant minimal_patch \
  --variant test_first \
  --variant policy_object
```

### Implement → record → check → judge → win

```bash
# See what each variant should do
agents-arena brief <arena-id> test_first

# After coding in each worktree…
agents-arena record <arena-id> minimal_patch
agents-arena checks <arena-id> minimal_patch --command "pytest -q"

# Run the tournament
agents-arena judge-all <arena-id>
agents-arena scoreboard <arena-id>

# Ship the winner
agents-arena promote <arena-id> --mode patch
```

### Preview before you run

Use `--dry-run` with any command to see what would happen without executing it:

```bash
agents-arena --dry-run open "fix auth bug" --variant test_first
```

```json
{
  "dry_run": true,
  "command": "open",
  "engine_method": "open",
  "args": { "task": "fix auth bug", "base_ref": "HEAD", "variants": ["test_first"] },
  "description": "Would create a new arena with task 'fix auth bug' using base ref HEAD.",
  "side_effects": [
    "Creates git worktrees for each variant",
    "Writes arena metadata to .agents-arena/state/"
  ]
}
```

---

## How it works

### 1. Variants, not one-shot patches

Each variant gets its own Git worktree and a strategy brief. Built-in strategies include:

| Strategy | Approach |
|---|---|
| `minimal_patch` | Smallest safe change, no API surface changes |
| `test_first` | Write regression tests first, then minimal code to pass |
| `clean_boundary` | Improve local boundary/adapter shape, reduce coupling |
| `policy_object` | Model business rules as explicit policy objects |
| `adapter_boundary` | Push integration details behind an adapter |
| `performance_oriented` | Optimize with measurement, correctness first |
| `maintainability_refactor` | Favor long-term readability and small helpers |

Or pass any custom variant name — the strategy is yours to define.

### 2. Pairwise Elo judging

Every pair of variants is compared head-to-head. Ratings update after each match, producing a ranked scoreboard with win/loss/draw records, confidence scores, and explanations.

### 3. Hard gates

Failing tests or critical risk flags (secrets, dangerous commands) are hard gates — a risky variant cannot beat a safe one regardless of code elegance.

### 4. Full telemetry

Every run records: runner, model, wall time, token usage, stdout/stderr, JSONL events, prompt hash, diff stats, check results, and judge reasoning.

---

## Agent runners

Agents Arena can delegate implementation to external coding agents or let you code manually.

| Runner | Command | What it does |
|---|---|---|
| **manual** (default) | `agents-arena run-agent <id> <variant>` | Writes a prompt + metadata; you implement |
| **codex** | `--runner codex --model gpt-5.5` | Runs Codex CLI, captures full telemetry |
| **opencode** | `--runner opencode --model anthropic/claude-sonnet-4-5` | Runs OpenCode, captures full telemetry |

## Judge runners

| Runner | Description |
|---|---|
| **heuristic** (default) | Deterministic scoring based on checks, blast radius, risk flags |
| **codex** | LLM-as-judge via Codex CLI with read-only comparison prompt |
| **opencode** | LLM-as-judge via OpenCode with read-only comparison prompt |

```bash
# Judge a single pair
agents-arena judge <arena-id> minimal_patch policy_object

# Judge all pairs with an LLM judge
agents-arena judge-all <arena-id> --judge-runner codex --judge-model gpt-5.5
```

---

## MCP server

Agents Arena exposes all functionality as MCP tools, making it available to any MCP-compatible client.

```bash
# Start the server
agents-arena-mcp
```

### Claude Code

```bash
claude mcp add --transport stdio --scope project agents-arena -- \
  python -m agents_arena_mcp.server
```

### Codex / OpenCode

Scaffold files are included — see [Installing into a repo](#installing-into-a-repo).

### Available MCP tools

`arena_open` · `arena_status` · `arena_variant_brief` · `arena_run_variant_agent` · `arena_record_variant` · `arena_run_checks` · `arena_pairwise_judge` · `arena_judge_all_pairs` · `arena_score` · `arena_scoreboard` · `arena_promote_winner` · `arena_export_pr_bundle` · `arena_cleanup`

---

## Installing into a repo

The install script scaffolds configuration files for multiple agent platforms:

```bash
python install.py --target /path/to/repo --append-agents --append-claude
```

This creates:

```
.agents-arena/          ← arena state, patches, reports
.claude/skills/         ← Claude Code skill
.codex/                 ← Codex config example
.opencode/skills/       ← OpenCode skill
.agents/skills/         ← Generic agents skill
AGENTS.agents-arena.md  ← Agent instructions
CLAUDE.agents-arena.md  ← Claude instructions
```

---

## Project layout

```
.agents-arena/
├── policy.json                         ← safety policy + defaults
├── state/
│   ├── current-arena.json              ← active arena pointer
│   ├── arenas.jsonl                    ← event log
│   ├── pairwise-results.jsonl          ← judge outcomes
│   └── runs.jsonl                      ← agent run records
├── runs/<run-id>/
│   ├── metadata.json, prompt.md        ← run inputs
│   ├── stdout.log, stderr.log          ← captured output
│   └── events.jsonl, final.md          ← telemetry + result
├── patches/
│   ├── <arena>-<variant>.patch         ← variant diffs
│   └── <arena>-winner-<variant>.patch  ← promoted winner
└── reports/
    ├── <arena>-scoreboard.md           ← Elo scoreboard
    └── <arena>-pr-summary.md           ← PR-ready summary
```

Worktrees live outside the repo to avoid pollution:

```
../.agents-arena-worktrees/<repo>/<arena-id>/<variant>/
```

---

## Safety

Agents Arena is designed to be safe by default:

- 🔒 **Dirty repo protection** — refuses to open an arena on uncommitted changes unless you opt in
- 🌳 **Git worktree isolation** — variants can't interfere with each other or your working tree
- 🚫 **Command blocklist** — destructive commands are blocked during check execution
- 📦 **Patch-only promotion** — winner exports as a `.patch` file; nothing is applied unless you say so
- 🔍 **Read-only judging** — external judges receive diffs only, never write access
- 🚨 **Secret detection** — files matching secret-like patterns trigger hard-gate failures

---

## Example workflows

### Refactoring with confidence

> *"Four strategies compete. The one with passing tests, minimal blast radius, and clean boundaries wins."*

```bash
agents-arena open "Extract payment logic into a service" \
  --variant minimal_patch --variant test_first \
  --variant clean_boundary --variant policy_object
# implement → record → check → judge-all → promote
```

### Squashing a recurring bug

> *"The test-first variant catches the regression. The minimal patch doesn't. Elo reflects that."*

```bash
agents-arena open "Fix race condition in order processing" \
  --variant minimal_patch --variant test_first --variant robust_boundary
```

### Dependency migration

> *"Three migration strategies, scored by blast radius, rollback ease, and test coverage."*

```bash
agents-arena open "Migrate from requests to httpx" \
  --variant compatibility_layer --variant direct_migration --variant module_by_module
```

---

## CLI reference

| Command | Description |
|---|---|
| `agents-arena open <task>` | Create a new arena with variant worktrees |
| `agents-arena status` | Show current arena status |
| `agents-arena brief <arena> <variant>` | Show variant implementation brief |
| `agents-arena run-agent <arena> <variant>` | Run an agent in a variant worktree |
| `agents-arena record <arena> <variant>` | Snapshot the variant diff and metadata |
| `agents-arena checks <arena> <variant>` | Run test/lint commands for a variant |
| `agents-arena judge <arena> <a> <b>` | Judge one pair of variants |
| `agents-arena judge-all <arena>` | Run full pairwise tournament |
| `agents-arena score <arena>` | Compute final scores and pick a winner |
| `agents-arena scoreboard <arena>` | Render the Elo scoreboard |
| `agents-arena promote <arena>` | Export/apply/branch the winner |
| `agents-arena export-pr-bundle <arena>` | Generate PR-ready artifacts |
| `agents-arena cleanup <arena>` | Remove arena worktrees |

Global flags: `--repo <path>` · `--dry-run` · `--version`

---

## Development

```bash
pip install -e '.[dev]'
pytest
```

---

## License

MIT
