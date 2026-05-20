# Scoring Model

The scoreboard combines hard gates, deterministic metrics, pairwise judge results, and Elo ratings.

## Hard gates

Hard gates override Elo. A variant should not win when it:

- fails checks while another variant passes;
- touches critical secret-like paths;
- has compile/runtime evidence failure;
- changes behavior not requested by the task.

## Elo

Each pairwise match updates ratings from 1500 by default. Winner receives score 1.0, loser 0.0, draw 0.5. Confidence controls K-factor multiplier.

## Deterministic metrics

- checks pass/fail;
- test file changes;
- docs changes;
- files changed;
- lines added/removed;
- sensitive path risk flags.
