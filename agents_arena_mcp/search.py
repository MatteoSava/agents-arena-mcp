"""Phase C, opt-in: fork variants from checkpoints and run bounded refinement rounds."""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import Field

from agents_arena_mcp import workspace
from agents_arena_mcp.arena import ArenaId, context, selected, slugify, summary
from agents_arena_mcp.errors import ArenaError
from agents_arena_mcp.models import Variant


def arena_fork(
    source: Annotated[str, Field(description="Variant to fork from, e.g. `explore`.")],
    arena_id: ArenaId = None,
    names: Annotated[
        list[str] | None,
        Field(description="New variant names (strategies). Defaults to the arena's pending strategies."),
    ] = None,
    checkpoint: Annotated[int | None, Field(description="Checkpoint number; defaults to the latest.")] = None,
) -> dict[str, Any]:
    """Fork new variants from source@checkpoint. Ignored dirs (venvs, node_modules) are cloned copy-on-write."""
    store, config = context()
    arena = store.load(arena_id)
    src = selected(arena, [source])[0]
    new = [slugify(n) for n in (names or arena.pending_strategies)]
    if not new:
        raise ArenaError("No names given and no pending strategies to fork.")
    clash = sorted(set(new) & set(arena.variants))
    if clash:
        raise ArenaError(f"Variant(s) already exist: {', '.join(clash)}")
    created = []
    for name in new:
        path, parent = workspace.fork(arena, src, checkpoint, name, config.setup, config.run_timeout_sec)
        variant = Variant(name=name, strategy=config.strategy_text(name), workspace=str(path), parent=parent)
        with store.mutate(arena.id) as a:
            a.variants[name] = variant
            a.pending_strategies = [p for p in a.pending_strategies if p != name]
        created.append(name)
    store.event(arena.id, "fork", source=source, checkpoint=checkpoint, created=created)
    return summary(store.load(arena.id))


def arena_refine(
    arena_id: ArenaId = None,
    variants: Annotated[
        list[str] | None, Field(description="Variants to refine; defaults to the top two of an unresolved decision.")
    ] = None,
) -> dict[str, Any]:
    """Fork the contenders into `<name>-r<depth>` with the judge's critique in their brief. Depth is capped."""
    store, config = context()
    arena = store.load(arena_id)
    d = arena.decision
    if variants is None:
        if d is None or d.status == "winner" or len(d.ranking) < 2:
            raise ArenaError("Nothing to refine: judge first, and refine only unresolved decisions (or pass variants).")
        variants = d.ranking[:2]
    created = []
    for v in selected(arena, variants):
        depth = v.depth + 1
        if depth > config.judge.max_refine_depth:
            raise ArenaError(
                f"{v.name} is already at refine depth {v.depth} (max_refine_depth={config.judge.max_refine_depth})."
            )
        stem = re.sub(r"-r\d+$", "", v.name)
        name = f"{stem}-r{depth}"
        path, parent = workspace.fork(arena, v, None, name, config.setup, config.run_timeout_sec)
        critique = [
            f"- {r}"
            for m in arena.matches.values()
            if v.name in (m.first, m.second)
            for r in m.verdict.reasons + m.verdict.risks
        ]
        extra = "\n## Reviewer critique of your previous attempt\n\n" + "\n".join(dict.fromkeys(critique)) + "\n"
        brief_path = store.arena_dir(arena.id) / "variants" / name / "extra-brief.md"
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief_path.write_text(extra, encoding="utf-8")
        refined = Variant(name=name, strategy=v.strategy, workspace=str(path), parent=parent, depth=depth)
        with store.mutate(arena.id) as a:
            a.variants[name] = refined
        created.append(name)
    store.event(arena.id, "refine", created=created)
    out = summary(store.load(arena.id))
    out["next"] = f"arena_run(variants={created}) then arena_check and arena_judge"
    return out


SEARCH_OPS = (arena_fork, arena_refine)
