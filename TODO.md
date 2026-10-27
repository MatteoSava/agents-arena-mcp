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
- [DONE] Live MCP test inside a Claude Code session against the released v0.3.0 (uvx from the tag): plan, start, status, result(html), promote, history
  - [NOTE] claude real vs codex clean, repeats=2, planted `a - b` bug: all 4 runs made the same 1-line fix and scored 10. Both final orders said tie, so promote refused. claude 169k tokens, $0.30, 17s. codex 76k tokens, 19s

## Features
- [TODO] arena_plan: detect `pytest` when a `tests/` dir exists without pyproject.toml (it found no checks in a plain-script repo)
- [TODO] arena_plan interview: carry repeats and per-contestant baseline from the request text into draft_spec ("2 runs each", "Codex (clean)" were ignored)
- [DEFERRED] Task suites (multi-task scorecards)
- [DEFERRED] Authenticated smoke-call preflight (preflight is static in v0.3)
- [DEFERRED] Dollar cost for codex (it reports tokens only)
- [DEFERRED] MCP background tasks: needs fastmcp tasks extra, async tools and client support
- [DEFERRED] LayerFS backend. Revisit if it ships native macOS or a Python binding. Extract a backend protocol only then.
- [TODO] Investigate the 06_near_identical miss in claude's eval-judge run, and whether the prompt should push harder toward "tie" for cosmetic-only differences

## Technical debt (from the final review)
- [DONE] Empty worktree-root dirs are removed when an arena finishes
- [DEFERRED] A `prune` command for old `refs/arena/*` and `.agents-arena/arenas/*`. It's a feature, and the refs are what `promote` ships from, so deleting them needs an explicit user action
- [DONE] Foreground runs are tracked as jobs, so a dead process marks the arena failed
- [DONE] Dead code removed. `kill_owned` became `proc.cancel`, used on Ctrl-C
- [DONE] Removed `Spec.ship` and the plan question
- [DONE] `.agents-arena/.gitignore` un-ignored itself and a removed `config.toml` (`!.gitignore`, `!config.toml`). Now `*`, and old files are upgraded
- [DONE] `LEGACY_HINT` text is version-neutral
- [DONE] Removed the stale `.claude/mcp.json`
- [DONE] Repo `.mcp.json` ran `python -m agents_arena_mcp.server`, which exited at once (no `__main__` guard). Fixed, with a stdio regression test
- [DONE] Removed stray `calc.py` committed by accident in 55d4a85 (shipped in v0.3.0)
- [DONE] Names ending in `.` or `.lock` are rejected
- [DONE] Setup and checks always run in the user's env; only the agent is isolated
- [DONE] eval-judge runs judge preflight first
- [DONE] Ctrl-C kills agents and judges, marks the arena failed, and the CLI exits 130 (verified with a real Ctrl-C in tmux)
- [DONE] SIGTERM and the client quitting (stdin closed) cancel live arenas, mark them failed and remove worktrees. The server and CLI exit 143. Verified with a real server over stdio: EOF and SIGTERM both left no agent, no worktree, and a failed arena
- [NOTE] SIGKILL can't be handled. The worktrees stay, and `arena_status` reports the arena failed because its job's pid is gone
- [DONE] Refs that agents create in the shared .git are listed in the scorecard notes
- [DEFERRED] Blocking agent-created refs outright needs a separate clone per run (slower, more disk)

## Tests
- [TEST] Harness-level fakes for opencode `session export`
- [TEST] `test_position_biased_judge_is_caught` flaked once on macOS / py3.13 CI (flip rate 0.875: one case didn't flip). It didn't reproduce in 14 local runs (py3.11 and 3.13), 3 CI reruns, or a 120-add concurrent `git worktree` stress test. The assertion now names the case and its run error, so look there if it recurs
- [DONE] An autouse fixture points XDG_CACHE_HOME at tmp_path. The 43 empty dirs came from eval-judge runs, now cleaned at the source
- [DONE] Foreground start is tracked as a job (test added)
- [TEST] Judge cwd outside the repo (`tmp_path` can't prove it)
- [TEST] Integration tests against real claude/codex/opencode (marker `integration`)
- [TEST] `cp --reflink` path on Linux, covered only once CI runs on ubuntu

## Notes
- [NOTE] Unsupported: Windows, network filesystems / iCloud dirs (flock), git submodules, Git LFS.
- [NOTE] Rejected for a single-user tool: Bradley-Terry CIs (always overlap at small n), Swiss/knockout, full MCTS, an LLM trajectory monitor (diff tripwires suffice), a CLI framework dependency, a command blocklist.
- [NOTE] Edits to existing test files are `info`, not `needs_human`: test-first work legitimately edits tests.
- [NOTE] eval-judge results are saved under `~/.cache/agents-arena/evals/`, not in the repo.
