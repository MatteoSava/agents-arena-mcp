"""Regenerate the README images (dark + light): uv run python docs/assets/make_assets.py

The hero is an animated SVG (CSS keyframes, no script), so GitHub plays it inside <img>.
With prefers-reduced-motion it shows the final frame. The scorecard data is from a real run.
"""

from pathlib import Path

OUT = Path(__file__).parent
SANS = "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
THEMES = {
    "dark": dict(
        bg="#0b0d12",
        panel="#12151c",
        line="#232836",
        ink="#e9ecf2",
        dim="#8a93a6",
        faint="#4a5263",
        a="#7c9cff",
        b="#ff8a5b",
        c="#37d39a",
        warn="#ff6b6b",
        glow="#7c9cff",
    ),
    "light": dict(
        bg="#fbfbf8",
        panel="#ffffff",
        line="#e4e2dc",
        ink="#111318",
        dim="#5b6070",
        faint="#a3a7b3",
        a="#2a5bd7",
        b="#d9531e",
        c="#0f9a68",
        warn="#c62f2f",
        glow="#2a5bd7",
    ),
}

LOOP_SEC = 10
FADE = (92, 98)  # % of the loop: everything fades out, then the race restarts
# name, color key, final bar fraction, result, progress keyframes (% of loop -> share of the final bar), result at %
LANES = [
    ("strategy: minimal", "a", 0.92, "✓ 9.5", [(6, 0), (26, 0.35), (46, 1)], 47),
    ("strategy: test-first", "b", 0.78, "✓ 9.0", [(6, 0), (26, 0.6), (52, 1)], 53),
    ("strategy: rewrite", "c", 0.55, "✗ regression", [(6, 0), (20, 0.8), (35, 1)], 37),
]
WINNER_AT = 64
# status line phases: (start %, end %, text)
TICKER = [
    (3, 16, "▸ preflight ✓  harnesses, auth, overlays"),
    (16, 36, "▸ 9 runs · isolated worktrees · clean homes"),
    (36, 52, "▸ gates · 1 regression caught → disqualified"),
    (52, WINNER_AT, "▸ blind rubric · final judged A·B and B·A"),
    (WINNER_AT, 100, "▸ minimal wins both orders → arena/…-minimal"),
]


def _frames(name: str, steps: list[tuple[float, str]]) -> str:
    return f"@keyframes {name} {{ " + " ".join(f"{p:g}% {{ {css} }}" for p, css in steps) + " }"


def _appear(name: str, at: float, until: float = FADE[0], end: float = FADE[1]) -> str:
    return _frames(
        name,
        [
            (0, "opacity: 0"),
            (at, "opacity: 0"),
            (at + 2, "opacity: 1"),
            (until, "opacity: 1"),
            (end, "opacity: 0"),
            (100, "opacity: 0"),
        ],
    )


def hero(t: dict) -> str:
    x0, x1, y0 = 610, 1070, 112
    rows, css = [], []
    for i, (name, key, frac, res, steps, res_at) in enumerate(LANES):
        y, col, length = y0 + i * 62, t[key], (x1 - x0) * frac
        end = x0 + length
        failed = res.startswith("✗")
        last = steps[-1][0]
        bar = [(p, f"transform: scaleX({s:g})") for p, s in steps] + [
            (FADE[1], "transform: scaleX(1)"),
            (100, "transform: scaleX(0)"),
        ]
        dot = [(p, f"transform: translateX({-(1 - s) * length:.0f}px)") for p, s in steps]
        dot += [(FADE[1], "transform: translateX(0px)"), (100, f"transform: translateX({-length:.0f}px)")]
        css += [
            _frames(f"bar{i}", [(0, "transform: scaleX(0)")] + bar),
            _frames(f"dot{i}", [(0, dot[0][1])] + dot),
            _appear(f"res{i}", res_at - 2),
            _frames(
                f"lane{i}",
                [
                    (0, "opacity: 0"),
                    (3, "opacity: 1"),
                    (FADE[0], "opacity: 1"),
                    (FADE[1], "opacity: 0"),
                    (100, "opacity: 0"),
                ],
            ),
        ]
        if failed:
            css.append(
                _frames(
                    f"fail{i}",
                    [
                        (0, f"fill: {col}"),
                        (last, f"fill: {col}"),
                        (last + 2, f"fill: {t['warn']}"),
                        (FADE[1], f"fill: {t['warn']}"),
                        (100, f"fill: {col}"),
                    ],
                )
            )
        fill_anim = f"bar{i} {LOOP_SEC}s infinite" + (f", fail{i} {LOOP_SEC}s infinite" if failed else "")
        final_fill = t["warn"] if failed else col
        dot_anim = f' style="animation: fail{i} {LOOP_SEC}s infinite"' if failed else ""
        res_col = t["warn"] if failed else t["ink"]
        rows.append(f"""
  <g style="animation: lane{i} {LOOP_SEC}s infinite">
    <text x="{x0}" y="{y - 12}" font-family="{MONO}" font-size="15" fill="{t["dim"]}">{name}</text>
    <rect x="{x0}" y="{y}" width="{x1 - x0}" height="10" rx="5" fill="{t["line"]}"/>
    <rect class="grow" x="{x0}" y="{y}" width="{length:.0f}" height="10" rx="5" fill="{final_fill}" style="animation: {fill_anim}"/>
    <g style="animation: dot{i} {LOOP_SEC}s infinite">
      <circle cx="{end:.0f}" cy="{y + 5}" r="9" fill="{final_fill}" opacity="0.25"{dot_anim}/>
      <circle cx="{end:.0f}" cy="{y + 5}" r="5" fill="{final_fill}"{dot_anim}/>
    </g>
    <text x="{x1 + 22}" y="{y + 10}" font-family="{MONO}" font-size="15" font-weight="600" fill="{res_col}" style="animation: res{i} {LOOP_SEC}s infinite">{res}</text>
  </g>""")
    css += [
        _appear("win", WINNER_AT),
        _frames("pulse", [(0, "opacity: 0.10"), (50, "opacity: 0.22"), (100, "opacity: 0.10")]),
    ]
    ticker = []
    for j, (start, stop, text) in enumerate(TICKER):
        final = j == len(TICKER) - 1
        steps = [
            (0, "opacity: 0"),
            (start, "opacity: 0"),
            (start + 1, "opacity: 1"),
            (stop - 1 if not final else FADE[0], "opacity: 1"),
            (stop if not final else FADE[1], "opacity: 0"),
            (100, "opacity: 0"),
        ]
        css.append(_frames(f"tick{j}", steps))
        ticker.append(
            f'<text x="{x0}" y="300" font-family="{MONO}" font-size="14" fill="{t["ink"] if final else t["dim"]}" '
            f'opacity="{1 if final else 0}" style="animation: tick{j} {LOOP_SEC}s infinite">{text}</text>'
        )
    style = "\n    ".join(css)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="340" viewBox="0 0 1280 340" role="img" aria-label="Agents Arena: three strategies race, one trips a regression, a blind judge picks the winner">
  <style>
    .grow {{ transform-box: fill-box; transform-origin: 0 50%; }}
    {style}
    @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} }}
  </style>
  <defs>
    <radialGradient id="g" cx="0.15" cy="0.1" r="0.9"><stop offset="0" stop-color="{t["glow"]}" stop-opacity="0.16"/><stop offset="1" stop-color="{t["glow"]}" stop-opacity="0"/></radialGradient>
    <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" fill="none" stroke="{t["line"]}" stroke-width="1" opacity="0.6"/></pattern>
  </defs>
  <rect width="1280" height="340" rx="18" fill="{t["bg"]}"/>
  <rect width="1280" height="340" rx="18" fill="url(#grid)" opacity="0.5"/>
  <rect width="1280" height="340" rx="18" fill="url(#g)"/>
  <text x="64" y="84" font-family="{MONO}" font-size="15" letter-spacing="3" fill="{t["dim"]}">AGENTS ARENA · v0.3</text>
  <text x="64" y="160" font-family="{SANS}" font-size="58" font-weight="800" letter-spacing="-1.5" fill="{t["ink"]}">Race your agents.</text>
  <text x="64" y="226" font-family="{SANS}" font-size="58" font-weight="800" letter-spacing="-1.5" fill="{t["a"]}">Ship the winner.</text>
  <text x="64" y="278" font-family="{SANS}" font-size="19" fill="{t["dim"]}">Same task, isolated worktrees, blind judging, real numbers.</text>
  <text x="64" y="312" font-family="{MONO}" font-size="13" fill="{t["faint"]}">claude · codex · opencode  —  MCP server + CLI</text>
  <g style="animation: win {LOOP_SEC}s infinite">
    <rect x="{x0 - 14}" y="{y0 - 34}" width="{1240 - x0 + 14}" height="56" rx="12" fill="{t["a"]}" style="animation: pulse 1.6s ease-in-out infinite" opacity="0.16"/>
    <text x="{x0 + 182}" y="{y0 - 12}" font-family="{MONO}" font-size="13" font-weight="700" letter-spacing="1.5" fill="{t["a"]}">★ WINNER</text>
  </g>
  <line x1="{x1}" y1="88" x2="{x1}" y2="252" stroke="{t["faint"]}" stroke-width="2" stroke-dasharray="4 6"/>
  <text x="{x1}" y="78" font-family="{MONO}" font-size="12" text-anchor="middle" fill="{t["faint"]}">checks</text>{"".join(rows)}
  {chr(10).join("  " + line for line in ticker).lstrip()}
</svg>
"""


def scorecard(t: dict) -> str:
    # Real run, 2026-10-27: claude (real baseline), CLAUDE.md overlay A/B, 3 repeats each, judged by codex.
    rows = [("rules-v1", t["a"], "3/3", 9.0, 218, 28.6, 0.255), ("rules-v2", t["b"], "3/3", 9.5, 250, 24.8, 0.258)]
    cols = [
        ("score", 10, lambda r: f"{r[3]:.1f}"),
        ("tokens", 260, lambda r: f"{r[4]}k"),
        ("time", 30, lambda r: f"{r[5]:.0f}s"),
        ("cost", 0.3, lambda r: f"${r[6]:.2f}"),
    ]
    body = []
    for i, r in enumerate(rows):
        y = 170 + i * 84
        body.append(f"""
  <circle cx="64" cy="{y - 5}" r="6" fill="{r[1]}"/>
  <text x="80" y="{y}" font-family="{MONO}" font-size="16" font-weight="600" fill="{t["ink"]}">{r[0]}</text>
  <text x="80" y="{y + 24}" font-family="{MONO}" font-size="13" fill="{t["dim"]}">eligible {r[2]}</text>""")
        for j, (_label, top, fmt) in enumerate(cols):
            x = 300 + j * 205
            val = [r[3], r[4], r[5], r[6]][j]
            w = 150 * val / top
            body.append(f"""
  <rect x="{x}" y="{y - 10}" width="150" height="8" rx="4" fill="{t["line"]}"/>
  <rect x="{x}" y="{y - 10}" width="{w:.0f}" height="8" rx="4" fill="{r[1]}"/>
  <text x="{x}" y="{y + 22}" font-family="{MONO}" font-size="15" fill="{t["ink"]}">{fmt(r)}</text>""")
    heads = "".join(
        f'<text x="{300 + j * 205}" y="128" font-family="{MONO}" font-size="12" letter-spacing="1.5" fill="{t["faint"]}">{c[0].upper()}</text>'
        for j, c in enumerate(cols)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1160" height="380" viewBox="0 0 1160 380" role="img" aria-label="Example scorecard from a real arena run">
  <rect width="1160" height="380" rx="16" fill="{t["panel"]}" stroke="{t["line"]}"/>
  <circle cx="34" cy="30" r="6" fill="{t["warn"]}" opacity="0.8"/><circle cx="54" cy="30" r="6" fill="{t["b"]}" opacity="0.8"/><circle cx="74" cy="30" r="6" fill="{t["c"]}" opacity="0.8"/>
  <text x="100" y="35" font-family="{MONO}" font-size="13" fill="{t["dim"]}">arena_result · "Add a multiply(a, b) function" · objective: quality · 3 repeats</text>
  <rect x="48" y="62" width="540" height="40" rx="10" fill="{t["bg"]}" stroke="{t["line"]}"/>
  <text x="68" y="88" font-family="{MONO}" font-size="15" fill="{t["ink"]}">▸ rules-v2 highest median quality score</text>
  {heads}{"".join(body)}
  <text x="48" y="352" font-family="{MONO}" font-size="12" fill="{t["faint"]}">real run · claude 2.1.291 contestants · codex 0.164.0 as blind judge · 2026-10-27</text>
</svg>
"""


if __name__ == "__main__":
    for name, theme in THEMES.items():
        (OUT / f"hero-{name}.svg").write_text(hero(theme), encoding="utf-8")
        (OUT / f"scorecard-{name}.svg").write_text(scorecard(theme), encoding="utf-8")
    print(sorted(p.name for p in OUT.glob("*.svg")))
