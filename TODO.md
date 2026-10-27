# TODO

State: v0.3 (experiment bench) is implemented and verified on real harnesses. The release (version bump, tag, push) is a separate step.

## v0.3 summary
- [DONE] Spike: isolation recipe per harness (docs/v0.3-isolation-spike.md)
- [DONE] 5 tools (plan, start, status, result, history) plus `init` and `eval-judge`; spec-only config
- [DONE] Contestants, clean/real baselines, overlays, repeats, setup, objectives
- [DONE] Blind rubric per run plus both-order final; scorecard, history, HTML report
- [DONE] Gates including `agent_timeout` and `agent_failed`
- [DONE] README, docs/design.md, CHANGELOG, refreshed skill
- [DONE] Fixes from real-harness runs: build artifacts in patches, inherited `$PWD` (opencode), timed-out agent could win, invisible agent stderr, judge ran inside the user's repo

## Verification results (2026-10-27)
- [DONE] stdio MCP smoke via uvx, claude real vs codex clean: passed
  - [NOTE] Both fixed the bug. claude: 188k tokens, $0.32. codex: 77k tokens, no cost reported. `~/.codex` untouched.
- [DONE] opencode real and clean (openrouter/openai/gpt-5-mini): passed after the PWD fix
- [NOTE] eval-judge baselines
  - codex: accuracy 0.875, flip 0.0, label-A 0.5
  - claude: accuracy 0.875, flip 0.0, label-A 0.5. Only miss: 06_near_identical
  - opencode gpt-5-mini: accuracy 0.75, flip 0.125, label-A 0.438
- [NOTE] CLAUDE.md-overlay A/B, real baseline, repeats=3: the mechanics worked, but the global ~/.claude/CLAUDE.md (TDD, TODO.md) masked the difference. All 6 runs wrote TODO.md and tests. This is why the docs recommend `clean` for controlled A/Bs.
- [NOTE] A probe found no ~/AGENTS.md ancestor leak into clean codex or opencode.
- [BLOCKED] Clean-claude verification needs `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`)
- [NOTE] A tmux server started before an env var was set doesn't pass it to its sessions. Run arenas from a shell that has the provider keys.

## Features
- [DEFERRED] Task suites (multi-task scorecards)
- [DEFERRED] Authenticated smoke-call preflight (preflight is static in v0.3)
- [DEFERRED] Dollar cost for codex (it reports tokens only)
- [DEFERRED] MCP background tasks: needs fastmcp tasks extra, async tools and client support
- [DEFERRED] LayerFS backend. Revisit if it ships native macOS or a Python binding. Extract a backend protocol only then.
- [TODO] Investigate the 06_near_identical miss in claude's eval-judge run, and whether the prompt should push harder toward "tie" for cosmetic-only differences

## Technical debt (from the final review)
- [DEBT] No cleanup or prune of `refs/arena/*`, `.agents-arena/arenas/*` or empty worktree-root dirs
- [DEBT] An arena with no jobs that died mid-run stays "running"
- [DEBT] Dead code: `proc.kill_owned`, `git.delete_refs`, `git.worktree_prune`, `git.is_dirty`, `jobs.running`
- [DEBT] `Spec.ship` is unused (arena_plan still asks a "ship" question)
- [DEBT] `LEGACY_HINT` and `GITIGNORE` text in store.py is v0.1/v0.2-era (mentions `config.toml`)
- [DEBT] Other invalid git ref names are still allowed (names ending in `.` or `.lock`)
- [DEBT] Baseline setup uses the real env while per-run setup uses the clean env
- [DEBT] eval-judge skips judge preflight
- [DEBT] Ctrl-C during `start --wait` leaves the arena running
- [DEBT] Agents can still create branches or stashes in the shared .git

## Tests
- [TEST] Harness-level fakes for opencode `session export`
- [TEST] Stale arena without jobs (see the debt item above)
- [TEST] Judge cwd outside the repo (`tmp_path` can't prove it)
- [TEST] Integration tests against real claude/codex/opencode (marker `integration`)
- [TEST] `cp --reflink` path on Linux, covered only once CI runs on ubuntu

## Notes
- [NOTE] Unsupported: Windows, network filesystems / iCloud dirs (flock), git submodules, Git LFS.
- [NOTE] Rejected for a single-user tool: Bradley-Terry CIs (always overlap at small n), Swiss/knockout, full MCTS, an LLM trajectory monitor (diff tripwires suffice), a CLI framework dependency, a command blocklist.
- [NOTE] Edits to existing test files are `info`, not `needs_human`: test-first work legitimately edits tests.
- [NOTE] eval-judge results are saved under `~/.cache/agents-arena/evals/`, not in the repo.
