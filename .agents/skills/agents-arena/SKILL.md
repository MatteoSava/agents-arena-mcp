---
name: agents-arena-workflow
description: >
  Full Agents Arena MCP workflow for competing variant implementations.
  Use when the user asks to "use arena", "arena compare", "compete variants",
  or wants to evaluate multiple implementation approaches for a code change.
argument-hint: "[task description]"
---

# Agents Arena MCP Workflow

Use this skill whenever the user asks you to use the Arena MCP to implement, compare, and judge competing code variants. This is the canonical step-by-step workflow.

## Overview

The arena creates isolated git worktrees for each variant, lets you implement differently in each, runs checks, judges pairs with an LLM, scores, and promotes the winner.

## Step-by-step Workflow

### 1. Open the Arena

```
arena_open(task="<task description>", include_current_diff=true)
```

- If the working tree is dirty, pass `include_current_diff=true`.
- Note the `arena_id` — you need it for all subsequent steps.
- By default 4 variants are created: `minimal_patch`, `test_first`, `clean_boundary`, `maintainability_refactor`.
- You can pass `variants=["name1", "name2", ...]` to use custom names.

### 2. Implement Each Variant (sequential, not parallel)

For **each** variant, in order:

```
arena_run_variant_agent(arena_id=<id>, variant=<name>, runner="manual")
```

Then manually edit files in the variant's worktree path (returned in the response). Each variant has its own isolated worktree — make changes there, not in the main repo.

**Important:** Do NOT use sub-agents or parallel task runners. Implement each variant yourself, one at a time, using the `edit` tool on files in the variant worktree path.

After implementing, record the variant:

```
arena_record_variant(arena_id=<id>, variant=<name>, notes="<brief description>")
```

### 3. Run Checks

For each variant:

```
arena_run_checks(arena_id=<id>, variant=<name>, commands=["python -m pytest tests/ -v"])
```

Use whatever test/lint commands are appropriate for the project.

### 4. Judge All Pairs

Use the codex judge runner for LLM-based evaluation:

```
arena_pairwise_judge(arena_id=<id>, variant_a=<a>, variant_b=<b>, judge_runner="codex", timeout_sec=600)
```

**Do NOT use `arena_judge_all_pairs` with codex** — it times out due to MCP transport limits. Instead, call `arena_pairwise_judge` for each pair individually.

For N variants there are N*(N-1)/2 pairs. Run them one at a time.

If codex is unavailable, `judge_runner="heuristic"` works but only compares diff sizes and check results (all similar variants draw).

Available judge runners: `"heuristic"`, `"codex"`, `"opencode"`.

### 5. Score

```
arena_score(arena_id=<id>)
```

Returns Elo ratings, deterministic scores, and the winner.

### 6. Scoreboard

```
arena_scoreboard(arena_id=<id>)
```

Returns a markdown table with rankings.

### 7. Promote Winner

```
arena_promote_winner(arena_id=<id>, variant=<winner_name>, mode="patch")
```

Modes: `"patch"` (safe export), `"apply"` (apply to main), `"branch"` (create branch).

### 8. Cleanup (optional)

```
arena_cleanup(arena_id=<id>)
```

Removes worktrees, keeps patches and reports by default.

## Known Issues & Workarounds

### MCP transport timeout
Long-running MCP tool calls (codex judge, judge_all_pairs) can hit the MCP client timeout (~60s). Workaround: call `arena_pairwise_judge` one pair at a time — each codex call takes ~50s.

### Codex judge output parsing
Codex plugins (e.g. python-quality-gate) can overwrite `result.json` with non-judgment content. The fix in `judges/pairwise.py` prefers extracting the judgment from JSONL stdout (first `agent_message` with a `"winner"` field) over `result.json`.

### Multi-JSON parse
When the extracted text has multiple JSON objects, `parse_judge_json` uses `json.JSONDecoder.raw_decode()` to extract just the first valid object.

## Variant Strategy Guide

| Variant | Strategy |
|---|---|
| `minimal_patch` | Smallest safe change. No refactoring. Targeted tests only. |
| `test_first` | Write tests first, then implement. TDD approach. |
| `clean_boundary` | Improve local boundaries/adapters. Reduce coupling. |
| `maintainability_refactor` | Extract helpers for readability. Avoid broad rewrites. |

## Example Session

```
User: "use arena to add a --dry-run flag to the CLI"

1. arena_open(task="Add --dry-run flag to CLI", include_current_diff=true)
2. For each variant:
   - arena_run_variant_agent(arena_id=<id>, variant=<name>, runner="manual")
   - Edit files in variant worktree
   - arena_record_variant(arena_id=<id>, variant=<name>, notes="...")
3. For each variant:
   - arena_run_checks(arena_id=<id>, variant=<name>, commands=["pytest tests/ -v"])
4. For each pair (6 pairs for 4 variants):
   - arena_pairwise_judge(arena_id=<id>, variant_a=<a>, variant_b=<b>, judge_runner="codex")
5. arena_score(arena_id=<id>)
6. arena_scoreboard(arena_id=<id>)
7. arena_promote_winner(arena_id=<id>, variant=<winner>, mode="patch")
8. arena_cleanup(arena_id=<id>)
```
