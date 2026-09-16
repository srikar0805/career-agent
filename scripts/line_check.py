#!/usr/bin/env python3
"""Flag bullet lines that end well short of the text column.

page_check.py measures VERTICAL fill: does the content reach the bottom margin.
This measures HORIZONTAL fill: does each bullet actually use the width it was
given. The two fail independently. A resume can sit at 99% of the page and
still read as empty, because what the eye registers as whitespace is not the
inch at the bottom, it is a dozen bullets whose last wrapped line carries three
words and then stops.

Srikar's rule, 2026-08-18: "I dont want any line of the point to be less than
60% complete". So the final wrapped line of every bullet must reach at least
60% of the column width. A bullet that fits on one line is exempt, since it
never wrapped and there is no runt to fix.

The column width is measured from the document itself, from the widest line on
the page, so this works at any margin setting and on any template.

Fix a failure by adding or cutting words in that bullet until the last line
either fills past 60% or disappears into the line above. Loosening \\itemsep
does nothing here; this is a wrapping problem, not a spacing one.

Usage:
    python scripts/line_check.py resume.pdf
    python scripts/line_check.py resume.pdf --json
    python scripts/line_check.py resume.pdf --min 0.5      # looser than default
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

DEFAULT_MIN_FILL = 0.60

# Bullet glyphs the template may emit. A line starting with one of these opens
# a new bullet; anything indented below it is a continuation of the same one.
BULLETS = ("•", "●", "▪", "-", "–")


def _load(path: Path):
    try:
        import pdfplumber
    except ImportError:
        sys.exit("pdfplumber is not installed. Run: pip install pdfplumber")
    return pdfplumber.open(str(path))


def _lines(chars: list[dict], quantize: float = 2.0) -> list[dict]:
    """Group characters into visual lines with their x extents."""
    rows: dict[float, list[dict]] = {}
    for c in chars:
        key = round(c["top"] / quantize) * quantize
        rows.setdefault(key, []).append(c)
    out = []
    for top in sorted(rows):
        cs = sorted(rows[top], key=lambda c: c["x0"])
        text = "".join(c["text"] for c in cs).strip()
        if not text:
            continue
        out.append({
            "top": top,
            "x0": min(c["x0"] for c in cs),
            "x1": max(c["x1"] for c in cs),
            "text": text,
        })
    return out


def analyze(path: Path, min_fill: float = DEFAULT_MIN_FILL) -> dict:
    pdf = _load(path)
    findings, worst = [], []
    with pdf:
        for pno, page in enumerate(pdf.pages, 1):
            lines = _lines(page.chars)
            if not lines:
                continue
            # The text column is the widest span anything on the page reaches.
            left = min(l["x0"] for l in lines)
            right = max(l["x1"] for l in lines)
            width = right - left
            if width <= 0:
                continue

            # Walk bullets. A bullet starts at a bullet glyph and runs until the
            # next bullet glyph or a line that starts at or left of the bullet's
            # own indent, which means a new heading or entry rather than a wrap.
            groups: list[list[dict]] = []
            cur: list[dict] = []
            indent = None
            for l in lines:
                starts_bullet = l["text"][:1] in BULLETS
                if starts_bullet:
                    if cur:
                        groups.append(cur)
                    cur, indent = [l], l["x0"]
                elif cur and indent is not None and l["x0"] > indent + 1:
                    cur.append(l)
                else:
                    if cur:
                        groups.append(cur)
                    cur, indent = [], None
            if cur:
                groups.append(cur)

            for g in groups:
                if len(g) < 2:
                    continue          # never wrapped, so no runt line exists
                last = g[-1]
                fill = (last["x1"] - left) / width
                worst.append(fill)
                if fill < min_fill:
                    findings.append({
                        "page": pno,
                        "fill": round(fill, 3),
                        "lines": len(g),
                        "text": last["text"][:70],
                        "opens": g[0]["text"][:52],
                    })
    return {
        "file": path.name,
        "min_fill": min_fill,
        "wrapped_bullets": len(worst),
        "tightest": round(min(worst), 3) if worst else None,
        "mean": round(statistics.mean(worst), 3) if worst else None,
        "findings": sorted(findings, key=lambda f: f["fill"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--min", type=float, default=DEFAULT_MIN_FILL)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    r = analyze(a.pdf, a.min)
    if a.json:
        print(json.dumps(r, indent=2))
        return 1 if r["findings"] else 0

    pct = lambda v: f"{v * 100:.0f}%"
    print(f"{r['file']}: {r['wrapped_bullets']} wrapped bullets, "
          f"tightest last line {pct(r['tightest']) if r['tightest'] else 'n/a'}, "
          f"mean {pct(r['mean']) if r['mean'] else 'n/a'}")
    if not r["findings"]:
        print(f"  every wrapped bullet ends past {pct(a.min)}")
        return 0
    for f in r["findings"]:
        print(f"  WARN  last line {pct(f['fill'])} of column  ({f['lines']} lines)")
        print(f"        bullet opens: {f['opens']}...")
        print(f"        runt line:    {f['text']}")
    print(f"\nAdd or cut words in each until the last line passes {pct(a.min)}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
