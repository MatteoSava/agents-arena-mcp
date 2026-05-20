# Safety Model

Agents Arena is local software with filesystem access. Treat it as privileged.

## Defaults

- Worktrees are isolated.
- Dirty repos are refused by default.
- Promotion exports a patch by default.
- Destructive check commands are blocked.
- Judge prompts are read-only.
- External runner subprocesses are logged.

## Not a sandbox

This package is not a complete security sandbox. Use it with existing CLI approvals, OS sandboxing, repo-sentinel, CI, secret scanning, and careful MCP allowlists.
