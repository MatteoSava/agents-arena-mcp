# Agents Arena: how to use it

Agents Arena runs **experiments** on coding agents. Contestants are full recipes:
**harness** (claude / codex / opencode) + **model** + **baseline** (`clean` | `real`) + **overlays** (any file, any target) + **strategy**.
Each contestant runs `repeats` times, each run in its own git worktree. The arena checks every run against the base commit and judges it blind, then returns a **scorecard** for the arena's **objective**.

## Flow
1. **`arena_plan(request, mode)`**:
   - `interview`: ask the user the returned questions, one at a time, and update `draft_spec`.
   - `autopilot`: adapt `draft_spec` to the request and explain each choice in one line.
   Show the final spec to the user before starting.
2. **`arena_start(spec, wait=false)`**: preflight runs first and fails fast. Then poll **`arena_status`** until `status` is `done`.
3. **`arena_result(html=true)`** returns the scorecard. Add `promote="branch"` to ship the winner without touching the user's checkout.
4. **`arena_history(contestant=...)`** shows trends across arenas.

## Writing good specs
- **Spec files** (CLI): TOML uses `[[contestants]]` tables, or pass the same structure as JSON. Unknown keys are rejected, so typos fail loudly.
- **Vary one thing.** For a skill A/B, keep the harness, model and baseline the same, and give each contestant a different overlay.
- **Overlays:** `{"from": "<any path>", "to": "repo:<path>"}` puts a file or directory into the run's checkout. `home:<path>` targets the clean harness home and requires `baseline="clean"`. Overlays are never counted as the contestant's code.
- **Setup:** `setup` is a shell command (e.g. `npm ci`) run once on the base commit and in every run's checkout before the agent starts. Its output is never counted as the contestant's code.
- **Baseline:**
  - `real` uses the user's actual setup. The arena never writes overlays into it, but the harness still records its usual session history there.
  - `clean` starts from an empty harness home with auth only. Clean claude needs `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`) or `ANTHROPIC_API_KEY`. Clean opencode only sees providers keyed by environment variables, and every opencode contestant needs an explicit `model`.
- **Objective:**
  - `quality` and `elegance` are judged: a blind rubric score per run, then a final in both orders.
  - `speed`, `tokens` and `cost` are metrics only, with no judge.
  - Any other text becomes a custom rubric.
- **Repeats:** 3–5 for comparisons you want to trust.
- **Judge:** prefer a different model family than the contestants.
- **Strategies:** for "most elegant solution", write 2–4 genuinely different, concrete approaches.

## Rules
- Report the verdict honestly. A tie is a valid result.
- Contestants and checks run agent-written code on this machine, the same as running tests on an untrusted branch.
- `promote="apply"` only touches the user's tree if the winner's diff applies cleanly. Otherwise use `promote="branch"`.
