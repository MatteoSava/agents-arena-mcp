from __future__ import annotations


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def confidence_multiplier(confidence: float) -> float:
    if confidence < 0.66:
        return 0.75
    if confidence <= 0.85:
        return 1.0
    return 1.15


def update_pair(
    rating_a: float,
    rating_b: float,
    score_a: float,
    confidence: float = 0.75,
    k_factor: int = 32,
) -> tuple[float, float, int, int]:
    k = k_factor * confidence_multiplier(confidence)
    exp_a = expected_score(rating_a, rating_b)
    exp_b = 1 - exp_a
    new_a = rating_a + k * (score_a - exp_a)
    new_b = rating_b + k * ((1 - score_a) - exp_b)
    return new_a, new_b, round(new_a - rating_a), round(new_b - rating_b)


def score_for_outcome(winner: str, variant_a: str, variant_b: str) -> float:
    if winner == "draw":
        return 0.5
    if winner == variant_a:
        return 1.0
    if winner == variant_b:
        return 0.0
    raise ValueError(f"winner must be {variant_a!r}, {variant_b!r}, or 'draw'; got {winner!r}")
