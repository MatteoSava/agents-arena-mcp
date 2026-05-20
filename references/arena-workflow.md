# Arena Workflow

Shadow PR Arena is meant for tasks where implementation strategy matters.

## Lifecycle

1. Open an arena.
2. Create variant worktrees from the same base commit.
3. Generate a strategy brief per variant.
4. Implement each variant manually or with a runner.
5. Record diffs and patch artifacts.
6. Run checks.
7. Judge all pairs.
8. Update Elo ratings.
9. Render scoreboard.
10. Export or apply winner.

## Recommended variant sets

Bug fix:

```text
minimal_patch
test_first
robust_boundary
```

Refactor:

```text
minimal_patch
clean_boundary
policy_object
adapter_boundary
```

Migration:

```text
compatibility_layer
direct_migration
module_by_module
```
