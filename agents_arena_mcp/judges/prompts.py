from __future__ import annotations

from typing import Any


def pairwise_judge_prompt(arena: dict[str, Any], variant_a: dict[str, Any], variant_b: dict[str, Any]) -> str:
    task = arena.get("task", "")
    va = variant_a.get("name")
    vb = variant_b.get("name")
    return f"""# Shadow PR Arena Pairwise Judge

You are judging two alternative code changes for the same task. You must not edit files. You must compare evidence and return only JSON matching the provided schema.

## Original task

{task}

## Variant A: {va}

State: {variant_a.get('state')}
Checks: {variant_a.get('checks')}
Risk flags: {variant_a.get('risk_flags')}
Diff summary: {variant_a.get('diff_summary')}
Patch excerpt:

```diff
{variant_a.get('patch_excerpt', '')}
```

## Variant B: {vb}

State: {variant_b.get('state')}
Checks: {variant_b.get('checks')}
Risk flags: {variant_b.get('risk_flags')}
Diff summary: {variant_b.get('diff_summary')}
Patch excerpt:

```diff
{variant_b.get('patch_excerpt', '')}
```

## Criteria

Prefer the variant that:
- satisfies the task and acceptance criteria;
- passes hard technical gates;
- preserves existing behavior unless the task explicitly requires change;
- adds useful regression coverage when a bug is involved;
- minimizes blast radius without hiding bad design;
- is easier to maintain and rollback;
- avoids security, secrets, IaC, migration and production risk.

Hard gates override aesthetics: if one variant fails tests or has critical risk and the other does not, prefer the safe passing variant.

Return JSON only. Use winner equal to "{va}", "{vb}", or "draw".
"""
