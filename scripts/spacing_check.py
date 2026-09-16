#!/usr/bin/env python3
"""Spacing consistency gate.

A resume looks unprofessional the moment one section breathes differently from
another. That defect is invisible in the .tex and obvious on the page, so this
checks the source for divergent knobs and the PDF for the rhythm they produce.

    python scripts/spacing_check.py <main.tex> [resume.pdf]

Source checks
  1. every \\itemsep in the document carries the same value
  2. no itemize opens with a \\vspace, which is always a per-section hack
  3. all five section headers in resume.cls use the same rule spacing

PDF check
  4. the gap between bullets is the same everywhere it occurs
"""
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

DATE = re.compile(r"(19|20)\d\d\s*$|present\s*$", re.I)


def fail(msg):
    print(f"  FAIL  {msg}")
    return 1


def check_source(tex: Path) -> int:
    s = tex.read_text(encoding="utf-8", errors="ignore")
    bad = 0

    vals = re.findall(r"\\itemsep\s*(-?[\d.]+\s*[a-z]{2})", s)
    uniq = sorted({v.replace(" ", "") for v in vals})
    if not vals:
        print(f"  note  no \\itemsep found in {tex.name}")
    elif len(uniq) > 1:
        bad |= fail(f"{len(vals)} \\itemsep values but {len(uniq)} distinct: {', '.join(uniq)}")
        print("        one value for the whole document. Tune that one value to fill the page.")
    else:
        print(f"  [OK]  {len(vals)} lists, all \\itemsep {uniq[0]}")

    hack = re.findall(r"\\begin\{itemize\}\s*\n\s*\\vspace\{([^}]+)\}", s)
    if hack:
        bad |= fail(f"{len(hack)} itemize block(s) open with \\vspace ({', '.join(sorted(set(hack)))})")
        print("        that tightens one section against the others. Remove it.")
    else:
        print("  [OK]  no itemize opens with a \\vspace")

    cls = tex.parent / "resume.cls"
    if cls.exists():
        c = cls.read_text(encoding="utf-8", errors="ignore")
        rule = re.findall(r"\\textbf\{\\MakeUppercase\{[^}]*\}\}[^\n]*\n\s*\\vspace\{([^}]+)\}\s*\n\s*\\hrule\s*\n(\s*\\vspace\{([^}]+)\})?", c)
        above = {r[0] for r in rule}
        below = {r[2] if r[2] else "MISSING" for r in rule}
        if len(above) > 1 or len(below) > 1:
            bad |= fail(f"section headers disagree: above the rule {sorted(above)}, below {sorted(below)}")
        elif rule:
            print(f"  [OK]  {len(rule)} section headers, all {above.pop()} above the rule, {below.pop()} below")
    return bad


def check_pdf(pdf: Path) -> int:
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as t:
        out = t.name
    if subprocess.run(["pdftotext", "-bbox-layout", str(pdf), out],
                      capture_output=True).returncode:
        print("  note  pdftotext unavailable, skipped the rendered check")
        return 0
    x = Path(out).read_text(encoding="utf-8", errors="ignore")

    lines = []
    for m in re.finditer(r'<line xMin="[\d.]+" yMin="([\d.]+)" xMax="[\d.]+" yMax="([\d.]+)">(.*?)</line>', x, re.S):
        txt = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        if txt:
            lines.append((float(m.group(1)), float(m.group(2)), txt))
    lines.sort()

    twin = {y for y, n in Counter(round(l[0], 1) for l in lines).items() if n > 1}
    wrap, between = [], []
    for i in range(1, len(lines)):
        gap = round(lines[i][0] - lines[i - 1][1], 1)
        prev, cur = lines[i - 1][2], lines[i][2]
        if gap < 0:
            continue                                   # right-aligned twin of the same line
        if cur.startswith("\u2022"):
            if (not prev.isupper() and not DATE.search(prev)
                    and round(lines[i - 1][0], 1) not in twin):
                between.append(gap)
        elif not cur.isupper() and not prev.isupper():
            wrap.append(gap)

    if not between:
        print("  note  no multi-bullet block found, nothing to compare")
        return 0

    w = Counter(wrap).most_common(1)[0][0] if wrap else None
    spread = max(between) - min(between)
    print(f"  within a wrapped bullet : {w}pt")
    print(f"  between bullets         : {min(between)}pt to {max(between)}pt")

    if spread > 0.6:
        print(f"  FAIL  between-bullet gap varies by {spread:.1f}pt across the document")
        print("        sections are spaced differently. Find the odd \\vspace or \\itemsep.")
        return 1
    if w is not None and min(between) < w:
        print("  FAIL  bullets sit closer together than the lines inside one bullet")
        print("        a new bullet must read as a new bullet. Open the gap.")
        return 1
    print("  [OK]  one bullet rhythm throughout")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    tex = Path(sys.argv[1])
    print(f"{tex.name}")
    bad = check_source(tex)
    if len(sys.argv) > 2:
        bad |= check_pdf(Path(sys.argv[2]))
    return bad


if __name__ == "__main__":
    sys.exit(main())
