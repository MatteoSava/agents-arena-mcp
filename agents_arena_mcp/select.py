"""Selection funnel: gates -> dedupe -> cap -> Copeland over both-order verdicts -> deterministic tie-break."""

from __future__ import annotations

from itertools import combinations

from agents_arena_mcp.checks import failing_count
from agents_arena_mcp.models import Arena, Decision, Match, Variant

TIE_BREAKS = ("fewer failing checks", "fewer flags needing review", "smaller diff")


def deterministic_key(variant: Variant) -> tuple[int, int, int]:
    needs_human = sum(1 for g in variant.gates if g.severity == "needs_human")
    lines = variant.snapshot.lines_changed if variant.snapshot else 10**9
    return (failing_count(variant), needs_human, lines)


def survivors(arena: Arena, max_survivors: int) -> tuple[list[str], list[str]]:
    """Variants worth judging, plus notes on everything that was dropped and why."""
    notes: list[str] = []
    alive: list[Variant] = []
    seen: dict[str, str] = {}
    for v in arena.variants.values():
        if v.state == "closed":
            continue
        if v.snapshot is None:
            notes.append(f"{v.name}: not checked yet")
            continue
        blocking = [g for g in v.gates if g.severity == "disqualify"]
        if blocking:
            notes.append(f"{v.name}: disqualified ({', '.join(f'{g.kind}: {g.detail}' for g in blocking)})")
            continue
        if v.snapshot.patch_hash in seen:
            notes.append(f"{v.name}: duplicate of {seen[v.snapshot.patch_hash]}")
            continue
        seen[v.snapshot.patch_hash] = v.name
        alive.append(v)
    if len(alive) > max_survivors:
        alive.sort(key=deterministic_key)
        for v in alive[max_survivors:]:
            notes.append(f"{v.name}: cut by prefilter (max_survivors={max_survivors})")
        alive = alive[:max_survivors]
    return [v.name for v in alive], notes


def pair_matches(arena: Arena, a: Variant, b: Variant) -> list[Match]:
    """Current matches for this pair (both orders). Evidence-backed rounds supersede plain ones."""
    assert a.snapshot and b.snapshot
    current = {(a.name, a.snapshot.commit), (b.name, b.snapshot.commit)}
    found = [m for m in arena.matches.values() if {(m.first, m.first_commit), (m.second, m.second_commit)} == current]
    with_evidence = [m for m in found if m.evidence]
    return with_evidence or found


def pair_winner(matches: list[Match]) -> str | None:
    """A variant takes the pair only if it won in every order; a split or tie is no signal."""
    winners = {m.winner for m in matches}
    if len(matches) >= 2 and len(winners) == 1:
        return winners.pop()
    return None


def judged_equivalent(matches: list[Match]) -> bool:
    """An explicit, usable "tie" in every order: the judge saw no meaningful difference (unlike a split)."""
    return len(matches) >= 2 and all(m.verdict.winner == "tie" and m.verdict.confidence > 0 for m in matches)


def _all_equivalent(arena: Arena, top: list[Variant]) -> bool:
    return all(judged_equivalent(pair_matches(arena, a, b)) for a, b in combinations(top, 2))


def decide(arena: Arena, names: list[str], judged: bool, notes: list[str]) -> Decision:
    rationale = list(notes)
    if not names:
        return Decision(status="no_viable", rationale=rationale + ["no variant passed the gates"])
    variants = {n: arena.variants[n] for n in names}
    scores = dict.fromkeys(names, 0)
    if judged:
        for a, b in combinations(names, 2):
            matches = pair_matches(arena, variants[a], variants[b])
            winner = pair_winner(matches)
            if winner is None:
                kind = "judged equivalent" if judged_equivalent(matches) else "split or unclear verdicts"
                rationale.append(f"{a} vs {b}: tie ({kind})")
                continue
            loser = b if winner == a else a
            scores[winner] += 1
            scores[loser] -= 1
            rationale.append(f"{a} vs {b}: {winner} won in both orders")
    top_score = max(scores.values())
    top = sorted((n for n in names if scores[n] == top_score), key=lambda n: deterministic_key(variants[n]))
    ranking = sorted(names, key=lambda n: (-scores[n], deterministic_key(variants[n])))
    decision = Decision(status="winner", ranking=ranking, scores=scores, rationale=rationale)
    if len(top) == 1 and judged:
        decision.winner = top[0]
    else:
        first, second = (top + [top[0]])[:2]
        key_a, key_b = deterministic_key(variants[first]), deterministic_key(variants[second])
        if len(top) > 1 and key_a == key_b and judged and _all_equivalent(arena, [variants[n] for n in top]):
            decision.winner, decision.tie_break = first, "judged equivalent in both orders"
            return decision
        if len(top) > 1 and key_a == key_b:
            decision.status = "needs_human"
            decision.rationale.append(f"tied between {', '.join(top)} and no deterministic tie-break separates them")
            return decision
        decision.winner = first
        if len(top) > 1:
            decision.tie_break = next(TIE_BREAKS[i] for i in range(3) if key_a[i] != key_b[i])
        elif not judged:
            decision.tie_break = "deterministic only (no LLM judge configured)"
    flagged = [g for g in variants[decision.winner].gates if g.severity == "needs_human"]
    if flagged:
        decision.status = "needs_human"
        decision.rationale.append(
            f"{decision.winner} leads but needs review: " + ", ".join(f"{g.kind} ({g.detail})" for g in flagged)
        )
    return decision
