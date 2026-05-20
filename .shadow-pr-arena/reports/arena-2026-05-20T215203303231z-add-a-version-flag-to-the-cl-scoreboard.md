# Shadow PR Arena Scoreboard

Arena: `arena-2026-05-20T215203303231z-add-a-version-flag-to-the-cl`
Task: Add a --version flag to the CLI that prints the package version. The version should be read from a single source of truth.
Base commit: `2770249cac67c13bd1d424620ae018aa9231a123`
Winner: **minimal_patch**

| Variant | Elo | W-L-D | Checks | Risk | Diff | Tokens | Latency | Score |
|---|---:|---:|---|---|---|---:|---:|---:|
| minimal_patch | 1535.83 | 2-0-0 | passed | normal | 2 files / +14 -0 |  |  | 103.29 |
| importlib_metadata | 1482.57 | 0-1-1 | pending | normal | 3 files / +24 -1 |  |  | 76.63 |
| dynamic_version | 1481.6 | 0-1-1 | pending | normal | 3 files / +49 -1 |  |  | 74.58 |

## Pairwise matrix

| | dynamic_version | importlib_metadata | minimal_patch |
|---|---|---|---|
| dynamic_version | — | D | L |
| importlib_metadata | D | — | L |
| minimal_patch | W | W | — |

## Pairwise reasons

- `dynamic_version` vs `importlib_metadata` → **draw** (0.55, tiny): Heuristic judge used because no external judge runner was selected or available.
- `dynamic_version` vs `minimal_patch` → **minimal_patch** (0.9, strong): One variant has stronger check evidence.; Blast radius differs by changed file count.; Heuristic judge used because no external judge runner was selected or available.
- `importlib_metadata` vs `minimal_patch` → **minimal_patch** (0.9, strong): One variant has stronger check evidence.; Blast radius differs by changed file count.; Heuristic judge used because no external judge runner was selected or available.
