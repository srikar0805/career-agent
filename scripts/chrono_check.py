#!/usr/bin/env python3
"""Verify a resume's experience section is in reverse-chronological order.

This exists because the failure is easy to introduce and nearly invisible to
the person who introduced it. Adding one role to the middle of a list, or
reordering by relevance and forgetting to re-sort, produces a document that a
recruiter reads as carelessness before they read anything else. Dates are the
one part of a resume that gets checked arithmetically.

Also flags overlapping full-time roles, which read as either an error or an
undisclosed second job, and gaps over six months, which invite a question
worth preparing for.

Usage:
    python scripts/chrono_check.py resume.pdf
    python scripts/chrono_check.py latex/resume/*/main.tex
    python scripts/chrono_check.py resume.pdf --json

Exit codes:
    0  ordered correctly
    1  out of order or overlapping
    2  bad invocation
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest import read  # noqa: E402

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}

# "Feb 2026 - Present", "May 2024 - Jun 2025", "Feb 24 - Apr 24"
RANGE = re.compile(
    r"([A-Z][a-z]{2})\.?\s*(\d{2,4})\s*(?:-|to|until)\s*"
    r"(Present|Current|(?:[A-Z][a-z]{2})\.?\s*\d{2,4})",
    re.I,
)


def parse_point(month: str, year: str) -> tuple[int, int]:
    y = int(year)
    if y < 100:                      # "24" means 2024, not 24 AD
        y += 2000
    return (y, MONTHS.get(month[:3].lower(), 1))


def parse_ranges(text: str) -> list[dict]:
    out = []
    for m in RANGE.finditer(text):
        start = parse_point(m.group(1), m.group(2))
        end_raw = m.group(3)
        if end_raw.lower() in ("present", "current"):
            end = (9999, 12)
            end_label = "Present"
        else:
            em = re.match(r"([A-Z][a-z]{2})\.?\s*(\d{2,4})", end_raw, re.I)
            end = parse_point(em.group(1), em.group(2)) if em else (9999, 12)
            end_label = end_raw
        out.append({
            "start": start, "end": end,
            "label": f"{m.group(1)} {m.group(2)} to {end_label}",
            "pos": m.start(),
        })
    return out


def months_between(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


# Headings that begin a block of roles. A resume may legitimately split
# experience into several such blocks, for example PROFESSIONAL EXPERIENCE
# above RESEARCH ENGINEERING. Each block is ordered internally; the blocks
# themselves are ordered by relevance, not by date, and comparing across them
# produces a false positive on a perfectly correct document.
EXPERIENCE_HEADINGS = (
    "PROFESSIONAL EXPERIENCE", "RESEARCH ENGINEERING", "RESEARCH EXPERIENCE",
    "WORK EXPERIENCE", "RELEVANT EXPERIENCE", "ENGINEERING EXPERIENCE",
    "INDUSTRY EXPERIENCE", "EXPERIENCE", "EMPLOYMENT", "INTERNSHIPS",
)

# Headings that end the experience region entirely.
STOP_HEADINGS = (
    "SELECTED PROJECTS", "ACADEMIC PROJECTS", "PROJECTS", "TECHNICAL SKILLS",
    "SKILLS", "EDUCATION", "CERTIFICATIONS", "PUBLICATIONS", "AWARDS",
)


def strip_tex_comments(text: str) -> str:
    """Remove LaTeX comment lines.

    A .tex file often carries a header comment explaining its own structure,
    and that prose mentions the section names. Matching headings inside it
    splits the document at positions that do not exist in the output.
    """
    out = []
    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("%"):
            continue
        # Strip trailing comments, honouring the \% escape.
        i, esc = 0, False
        while i < len(line):
            if line[i] == "\\":
                esc = not esc
            elif line[i] == "%" and not esc:
                line = line[:i]
                break
            else:
                esc = False
            i += 1
        out.append(line)
    return "\n".join(out)


def experience_blocks(text: str) -> list[str]:
    """Split the experience region into independently-ordered blocks."""
    upper = text.upper()

    stop = len(text)
    for h in STOP_HEADINGS:
        i = upper.find(h)
        if i > 0:
            stop = min(stop, i)

    region = text[:stop]
    region_upper = region.upper()

    # Match longest headings first, then discard any match that falls inside
    # one already claimed. Without this, "EXPERIENCE" matches inside
    # "PROFESSIONAL EXPERIENCE" and splits a single heading in two.
    claimed: list[tuple[int, int]] = []
    for h in sorted(EXPERIENCE_HEADINGS, key=len, reverse=True):
        i = region_upper.find(h)
        while i >= 0:
            if not any(a <= i < b for a, b in claimed):
                claimed.append((i, i + len(h)))
            i = region_upper.find(h, i + 1)

    starts = sorted(a for a, _ in claimed)
    if not starts:
        return [region]

    blocks = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(region)
        blocks.append(region[s:e])
    return blocks


def check(text: str) -> dict:
    problems, warnings = [], []
    ranges: list[dict] = []

    # Validate ordering WITHIN each block, never across blocks.
    for block in experience_blocks(text):
        block_ranges = parse_ranges(block)
        ranges.extend(block_ranges)
        for i in range(len(block_ranges) - 1):
            a, b = block_ranges[i], block_ranges[i + 1]
            if a["start"] < b["start"]:
                problems.append(
                    f"out of order: '{a['label']}' is listed above '{b['label']}' "
                    f"but started earlier"
                )

    # Overlap and gap analysis on the chronologically sorted view.
    ordered = sorted(ranges, key=lambda r: r["start"])
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        if a["end"] != (9999, 12) and b["start"] < a["end"]:
            overlap = months_between(b["start"], a["end"])
            if overlap >= 2:
                problems.append(
                    f"overlap of {overlap} months: '{a['label']}' and "
                    f"'{b['label']}' run concurrently"
                )
        elif a["end"] != (9999, 12):
            gap = months_between(a["end"], b["start"])
            if gap > 6:
                warnings.append(
                    f"gap of {gap} months between '{a['label']}' and '{b['label']}'. "
                    f"Not a defect, but expect to be asked about it."
                )

    return {
        "roles_found": len(ranges),
        "ranges": [r["label"] for r in ranges],
        "ordered": not problems,
        "problems": problems,
        "warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Check reverse-chronological order.")
    ap.add_argument("paths", nargs="+", help="resume PDF, DOCX, or .tex files")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results, failed = {}, False
    for raw in args.paths:
        p = Path(raw).expanduser()
        if not p.exists():
            print(f"no such file: {p}", file=sys.stderr)
            return 2
        if p.suffix == ".tex":
            text = strip_tex_comments(p.read_text(encoding="utf-8", errors="replace"))
        else:
            text = read(p).text
        r = check(text)
        results[str(p)] = r
        if r["problems"]:
            failed = True

    if args.json:
        print(json.dumps(results, indent=2))
        return 1 if failed else 0

    for path, r in results.items():
        name = Path(path).parent.name if Path(path).name == "main.tex" else Path(path).name
        status = "OK" if r["ordered"] else "OUT OF ORDER"
        print(f"\n{name}  [{status}]  {r['roles_found']} date ranges")
        for lbl in r["ranges"]:
            print(f"    {lbl}")
        for prob in r["problems"]:
            print(f"  PROBLEM  {prob}")
        for w in r["warnings"]:
            print(f"  note     {w}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
