# TODO

Goal: ship Agents Arena v0.2, following the research-backed revamp plan: fix the confirmed bugs,
rebuild on a small typed core, make selection trustworthy, and add bounded checkpoint/branching search.

## Phase A0: Tooling
- [DONE] MIT LICENSE, seeded TODO.md, README install via uv/uvx
- [DONE] python>=3.11, pin fastmcp, declare pydantic, dev group (pytest, ruff, basedpyright)
- [DONE] ruff fixes + format
- [DONE] CI on macOS + Linux (workflow added; first run happens on push)

## Phase A1: Bug fixes (failing test first)
- [DONE] Untracked files dropped from variant diff
- [DONE] include_current_diff never carried uncommitted changes into worktrees
- [DONE] Cleanup leaked branches and worktree dirs; partial open had no rollback
- [DONE] promote --mode branch switched the user's checkout
- [DONE] opencode runner/judge passed nonexistent `--dir`
- [DONE] Missing executable / timeout in checks raised instead of being recorded
- [DONE] score()/scoreboard() wrote the winner; current-arena followed last save; reads created state
- [DONE] Secret path patterns over-matched (`docs/secrets-handling.md`)
- [DONE] Non-UTF-8 diff crashed diff_against
- [DONE] No locking; fixed `.json.tmp` name collided between writers
- [DONE] Found during the rewrite: slugify turned `minimal_patch` into `minimal-patch`, losing its strategy text
- [DONE] Found during the rewrite: racy-git miss of same-second, same-size edits (temp index must keep its mtime)

## Phase A2/A3: Typed core + new surface
- [DONE] Single subprocess helper, Pydantic state, per-arena dir, flock store, flat modules
- [DONE] Temp-index snapshot commits under refs/arena/
- [DONE] 13 -> 7 core MCP tools (+ fork, refine), CLI/MCP parity test
- [DONE] `agents-arena init`; removed install.py / project_scaffold / references / old evals
- [DONE] Legacy state detection with cleanup instructions
- [DONE] README, docs/design.md, skill, CHANGELOG
- [DEBT] arena.py is ~350 LOC, above the <250 target. Remaining bulk is annotated parameter docs; splitting further would only shuffle code

## Phase B: Evidence-based judging
- [DONE] Background jobs in MCP server; parallel variants
- [DONE] Baseline checks; gate on regressions only
- [DONE] Dedupe; protected paths; reward-hacking tripwires
- [DONE] Blind A/B, both orders, isolated judge, strict schema
- [DONE] claude runner and judge; same-family judge warning
- [DONE] Copeland + deterministic tie-break; Elo removed
- [DONE] Report, ledger
- [DONE] Judge prompt as editable template (data/judge.md.tmpl, config override); brief template override
- [DONE] Judge eval harness (`agents-arena eval-judge`, 8 bundled cases)
- [DONE] MCP progress notifications (ctx.report_progress) for wait=True runs/judging
- [DONE] Manual verification with claude: real 2-variant arena (claude runner + claude judge) ran open->run->check->judge; both variants passed vs baseline; judge returned schema-valid ties in both orders (patches differed only by a test name); same-family warning shown
- [NOTE] eval-judge baseline 2026-10-27, claude (default model): accuracy 0.875, order-flip 0.0, tie 0.0, label-A 0.5, ~14s/call. Only miss: 06_near_identical (preferred `square(x)` over `square(value)` in both orders)
- [TODO] Investigate 06_near_identical miss (now that reasons are saved) and decide whether the prompt should push harder toward "tie" for cosmetic-only differences
- [DONE] Release: 0.2.0 bumped, branch pushed, PR opened, tag v0.2.0 pushed
- [DEFERRED] MCP background tasks (task=True): needs fastmcp[tasks]/pydocket + async tools + client support

## Phase C: Checkpoints + bounded search (opt-in)
- [DONE] Numbered checkpoints, arena_fork with copy-on-write clone of ignored dirs
- [DONE] Explore-then-fork (SWE-Replay)
- [DONE] Distinguishing-test tie-break (S*)
- [DONE] Depth-capped refinement round (DARS)
- [DONE] Agentic read-only final judge
- [DEFERRED] Experimental agent-session forks (verify codex/opencode resume semantics first)
- [DEFERRED] Shared generated tests for voting (CodeMonkeys)
- [DEFERRED] Bradley-Terry strategy priors once ledger has >= 30 arenas

## Tests
- [TEST] Integration tests against real codex/opencode/claude (marker `integration`, AGENTS_ARENA_IT=1)
- [TEST] `cp --reflink=auto` fork path on Linux (covered only once CI runs on ubuntu)

## Deferred / Decisions
- [DEFERRED] LayerFS backend. Revisit if it ships native macOS or a Python binding, or if >8 variants on Linux CI are needed. Extract a WorkspaceBackend Protocol only then.
- [NOTE] Rejected for a single-user tool: Bradley-Terry CIs (always overlap at n<=5), Swiss/knockout (pointless at n<=5), full MCTS (needs value fn), LLM trajectory monitor (diff tripwires suffice), CLI framework dependency.
- [NOTE] Edits to existing test files are `info`, not `needs_human`: test-first work legitimately edits tests. Skip markers, trivial asserts and test-config edits remain `needs_human`.

## Notes
- [NOTE] Unsupported: Windows, network filesystems / iCloud dirs (flock), git submodules, Git LFS.
- [NOTE] `--ignore-user-config` (codex judge) keeps auth but drops provider/model config; override the judge argv if needed.
- [BLOCKED] Real codex verification: local codex-cli 0.133.0 fails to decode the server's model list, and its built-in default models are rejected for ChatGPT accounts. Update codex or set `[judge] model` / runner model, then rerun the manual arena + eval-judge with codex.
- [NOTE] Even with `--ignore-user-config`, codex 0.133 still started user MCP servers (rmcp errors seen). Judge isolation from MCP servers is not guaranteed for codex; claude judge uses `--setting-sources "" --tools ""`.
