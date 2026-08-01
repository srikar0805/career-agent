#!/usr/bin/env python3
"""Verify that every job title on a resume matches the one actually held.

A job title is a factual claim about employment that a background check
verifies against payroll. Tailoring the surrounding bullets to a posting is
normal and expected; retitling the job is not, and the cost of being caught is
not a lost interview but a rescinded offer.

The failure is easy to make because it does not feel like lying. "Student
Assistant, Technical (AI Image Engineering)" becomes "Data Engineer (Student
Technical Assistant)" on a data resume and "Student Technical Assistant
(Systems and ML)" on a systems one, each time to help the reader, and now
there are six spellings of one job across six files and none of them is the
one on the offer letter.

Titles come from profile/titles.yaml, which is the single source of truth.

Usage:
    python scripts/title_check.py resume.pdf
    python scripts/title_check.py latex/resume/*/main.tex
    python scripts/title_check.py --list
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TITLES_FILE = REPO / "profile" / "titles.yaml"


def load_titles() -> list[dict]:
    try:
        import yaml
    except ImportError:
        sys.exit("pyyaml is not installed. Run: pip install pyyaml")
    if not TITLES_FILE.exists():
        sys.exit(f"missing {TITLES_FILE}. It is the source of truth for job titles.")
    data = yaml.safe_load(TITLES_FILE.read_text()) or {}
    return data.get("positions", [])


def extract(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                             capture_output=True, text=True)
        return out.stdout
    return path.read_text(errors="replace")


def normalize(s: str) -> str:
    """Collapse the differences that are formatting, not substance.

    LaTeX writes a literal comma inside a macro argument as {,}, and breaks
    ligatures with \\/. Neither changes what the reader sees, so neither should
    count as a title mismatch.
    """
    s = s.replace("{,}", ",").replace("\\/", "").replace("\\&", "&")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def check(path: Path, positions: list[dict]) -> list[str]:
    text = normalize(extract(path))
    problems = []

    for pos in positions:
        official = pos["title"]
        company_hint = normalize(pos.get("company", ""))
        # Only enforce a title when the document actually claims the job.
        if company_hint and company_hint.split(",")[0] not in text:
            continue
        if normalize(official) in text:
            continue
        # The job is on the page but under some other name. Find what it says.
        found = [normalize(v) for v in pos.get("seen_variants", [])
                 if normalize(v) in text]
        if found:
            problems.append(
                f'"{pos.get("company", "?")}" is titled "{found[0]}" but the '
                f'actual title is "{official}"'
            )
        else:
            problems.append(
                f'"{pos.get("company", "?")}" appears but the title '
                f'"{official}" does not. Check what it was renamed to.'
            )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--list", action="store_true", help="print the official titles and exit")
    args = ap.parse_args()

    positions = load_titles()

    if args.list:
        for p in positions:
            print(f"{p.get('company','?'):45s} {p['title']}")
        return 0

    if not args.paths:
        ap.error("give at least one resume file, or use --list")

    failed = False
    for path in args.paths:
        if not path.exists():
            print(f"{path}: no such file")
            failed = True
            continue
        problems = check(path, positions)
        if problems:
            failed = True
            print(f"{path.name}  [TITLE MISMATCH]")
            for p in problems:
                print(f"  {p}")
        else:
            print(f"{path.name}  [OK]  titles match profile/titles.yaml")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
