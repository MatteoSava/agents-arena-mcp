from agents_arena_mcp.core.elo import score_for_outcome, update_pair


def test_elo_updates_winner_up():
    new_a, new_b, da, db = update_pair(1500, 1500, 1.0, confidence=0.8, k_factor=32)
    assert new_a > 1500
    assert new_b < 1500
    assert da > 0
    assert db < 0


def test_draw_score():
    assert score_for_outcome("draw", "a", "b") == 0.5
