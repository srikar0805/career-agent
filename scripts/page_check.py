#!/usr/bin/env python3
"""Measure how completely a resume fills its page.

A resume that stops two inches above the bottom margin reads as thin, whatever
the content says. A resume that spills six lines onto a second page reads as
careless. Both are invisible while you are editing the source and obvious the
moment someone opens the PDF, which is why this is a check and not a habit.

Three defects, all measured against the document's own geometry rather than a
fixed number, so it works on any margin setting:

  1. Short page.   The last line sits well above where the bottom margin is.
     Inferred from the top margin, since resume templates are symmetric.
  2. Orphan page.  More than one page, with the final page nearly empty. The
     classic 1.1-page resume that should have been squeezed to one.
  3. Internal gap. The page ends at the bottom but has a hole in the middle,
     which fills the page without looking full.

Usage:
    python scripts/page_check.py resume.pdf
    python scripts/page_check.py resume.pdf --json
    python scripts/page_check.py resume.pdf --slack 0.25   # tighter than default
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

PT_PER_INCH = 72.0

# How far above the inferred bottom margin the last line may sit before the
# page counts as underfilled. A third of an inch is roughly two blank lines at
# resume body size, which is the point where a reader starts to notice.
DEFAULT_SLACK_IN = 0.33

# A final page holding less than this fraction of a full page of text is an
# orphan, not a real second page.
ORPHAN_FILL = 0.30

# An internal gap this many times the median line spacing is a hole rather
# than section breathing room.
GAP_RATIO = 3.0


def _load(path: Path):
    try:
        import pdfplumber
    except ImportError:
        sys.exit("pdfplumber is not installed. Run: pip install pdfplumber")
    return pdfplumber.open(str(path))


def _line_tops(chars: list[dict], quantize: float = 2.0) -> list[float]:
    """Collapse characters into distinct text baselines.

    Characters on one visual line vary by a point or two, so exact tops would
    report every line as several. Rounding to a 2pt grid merges them.
    """
    tops = {round(c["top"] / quantize) * quantize for c in chars}
    return sorted(tops)


def analyze(path: Path, slack_in: float = DEFAULT_SLACK_IN) -> dict:
    slack = slack_in * PT_PER_INCH
    findings: list[str] = []

    with _load(path) as pdf:
        pages = pdf.pages
        n_pages = len(pages)
        if not n_pages:
            return {"ok": False, "findings": ["the PDF has no pages"], "pages": 0}

        per_page = []
        for page in pages:
            chars = [c for c in page.chars if c.get("text", "").strip()]
            if not chars:
                per_page.append(None)
                continue
            top = min(c["top"] for c in chars)
            bottom = max(c["bottom"] for c in chars)
            per_page.append({
                "height": page.height,
                "top": top,
                "bottom": bottom,
                "tops": _line_tops(chars),
            })

        real = [p for p in per_page if p]
        if not real:
            return {"ok": False, "findings": ["no extractable text"], "pages": n_pages}

        last = real[-1]
        height = last["height"]

        # Resume templates set equal top and bottom margins, so the top margin
        # of the first page is the best available estimate of where the bottom
        # margin sits. Using the first page matters: the last page's top margin
        # is where its content starts, which on a continuation page is the
        # same thing, but on a one-page resume it is the header.
        top_margin = real[0]["top"]
        bottom_margin_y = height - top_margin
        unused = bottom_margin_y - last["bottom"]
        # Fraction of the writable column that carries text.
        writable = bottom_margin_y - top_margin
        fill = (last["bottom"] - top_margin) / writable if writable > 0 else 0.0

        if n_pages > 1 and fill < ORPHAN_FILL:
            findings.append(
                f"page {n_pages} is an orphan, {fill:.0%} full. "
                f"Cut or tighten until it fits on {n_pages - 1}, "
                f"or add enough to fill it."
            )
        elif unused > slack:
            findings.append(
                f"the last line stops {unused / PT_PER_INCH:.2f} inch above the "
                f"bottom margin. Page is {fill:.0%} full. Add content or open up "
                f"spacing until it reaches the last line."
            )

        # Internal holes. Checked on every page, since a gap on page one is
        # just as visible as one at the end.
        for i, p in enumerate(real, start=1):
            tops = p["tops"]
            if len(tops) < 6:
                continue
            gaps = [b - a for a, b in zip(tops, tops[1:])]
            median = statistics.median(gaps)
            if median <= 0:
                continue
            worst = max(gaps)
            if worst > median * GAP_RATIO:
                where = tops[gaps.index(worst)]
                findings.append(
                    f"page {i} has a {worst / PT_PER_INCH:.2f} inch vertical gap "
                    f"at y={where / PT_PER_INCH:.2f} inch, {worst / median:.1f}x the "
                    f"normal line spacing. That reads as a hole, not a section break."
                )

    return {
        "ok": not findings,
        "pages": n_pages,
        "fill": round(fill, 4),
        "unused_inches": round(unused / PT_PER_INCH, 3),
        "top_margin_inches": round(top_margin / PT_PER_INCH, 3),
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--slack", type=float, default=DEFAULT_SLACK_IN,
                    help="inches of unused space tolerated above the bottom "
                         f"margin (default {DEFAULT_SLACK_IN})")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.pdf.exists():
        sys.exit(f"no such file: {args.pdf}")

    result = analyze(args.pdf, args.slack)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{args.pdf.name}: {result['pages']} page(s), "
              f"{result.get('fill', 0):.0%} full, "
              f"{result.get('unused_inches', 0):.2f} inch unused at the bottom")
        for f in result["findings"]:
            print(f"  WARN  {f}")
        if result["ok"]:
            print("  fills the page")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
