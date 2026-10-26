# TODO

Goal: ship Agents Arena v0.2, a revamp driven by the research-backed plan
(`~/.claude/plans/lets-revamp-the-project-optimized-pillow.md`): fix the
confirmed bugs, rebuild on a small typed core, and make selection trustworthy.
The checkpoint and branching features come after that.

## Phase A0: Tooling
- [TODO] MIT LICENSE, seeded TODO.md, README install via uv/uvx
- [TODO] python>=3.11, pin fastmcp, declare pydantic, dev group (pytest, ruff, basedpyright)
- [TODO] ruff fixes + format
- [TODO] CI on macOS + Linux

## Phase A1: Bug fixes (failing test first)
- [BUG] Untracked files dropped from variant diff
- [BUG] include_current_diff never carries uncommitted changes into worktrees
- [BUG] Cleanup leaks branches and worktree dirs; partial open has no rollback
- [BUG] promote --mode branch switches the user's checkout
- [BUG] opencode runner/judge pass nonexistent `--dir`
- [BUG] Missing executable / timeout in checks raises instead of being recorded
- [BUG] score()/scoreboard() write the winner; current-arena follows last save; read-only calls create state
- [BUG] Secret path patterns over-match (`docs/secrets-handling.md`)
- [BUG] Non-UTF-8 diff crashes diff_against
- [BUG] No locking; fixed `.json.tmp` name collides between writers

## Phase A2: Refactor
- [REFACTOR] Single subprocess helper
- [REFACTOR] Pydantic state, per-arena dir, flock store
- [REFACTOR] Split arena.py into flat typed modules
- [REFACTOR] Remove dead policy keys, blocklist, auto-discovery, MCP prompts
- [REFACTOR] Temp-index snapshot commits under refs/arena/

## Phase A3: New surface
- [TODO] 13 -> 7 MCP tools, OPS registry, argparse parity test
- [TODO] `agents-arena init`, drop install.py / project_scaffold / references / evals
- [TODO] Legacy state detection with cleanup instructions
- [TODO] README + skill rewrite

## Phase B: Evidence-based judging
- [TODO] Background jobs in MCP server; parallel variants
- [TODO] Baseline checks; gate on regressions only
- [TODO] Dedupe; protected paths; reward-hacking tripwires
- [TODO] Blind A/B, both orders, isolated judge, strict schema
- [TODO] claude runner; same-family judge warning
- [TODO] Copeland + deterministic tie-break; remove Elo
- [TODO] Report, ledger, v0.2.0 release

## Phase C: Checkpoints + bounded search (opt-in)
- [TODO] Numbered checkpoints, arena_fork with APFS clone fallback
- [TODO] Explore-then-fork (SWE-Replay)
- [TODO] Distinguishing-test tie-break (S*)
- [TODO] Depth-capped refinement round (DARS)
- [TODO] Agentic read-only final judge
- [DEFERRED] Experimental agent-session forks (verify codex/opencode resume semantics first)
- [DEFERRED] Shared generated tests for voting (CodeMonkeys)
- [DEFERRED] Bradley-Terry strategy priors once ledger has >= 30 arenas

## Deferred / Decisions
- [DEFERRED] LayerFS backend. Revisit if it ships native macOS or a Python binding, or if >8 variants on Linux CI are needed. Extract a WorkspaceBackend Protocol only then.
- [NOTE] Rejected for a single-user tool: Bradley-Terry CIs (always overlap at n<=5), Swiss/knockout (pointless at n<=5), full MCTS (needs value fn), LLM trajectory monitor (diff tripwires suffice), CLI framework dependency.

## Notes
- [NOTE] Unsupported: Windows, network filesystems / iCloud dirs (flock), git submodules, Git LFS.
