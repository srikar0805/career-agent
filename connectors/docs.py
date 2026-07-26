#!/usr/bin/env python3
"""Scan career and research documents on this machine.

Scope is deliberately narrow. Two categories only:

  career    Resumes, cover letters, past applications, statements of purpose.
            Past applications are the most underrated source here: they show
            what you have already claimed about yourself, in your own words,
            and which framings you were willing to defend.

  research  Papers, coursework, research projects. Feeds the grad school and
            research outreach side.

Everything financial, legal, or immigration related is refused outright. Those
folders contain identity documents that have no business being read by an
agent, and nothing in them would improve a resume.

Usage:
    python connectors/docs.py
    python connectors/docs.py --root ~/Documents --json
    python connectors/docs.py --list-only          # show what would be read
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from ingest import read, SUPPORTED  # noqa: E402

OUT = REPO / "data" / "raw" / "documents.json"

# Directory names to read, by category. Matched case-insensitively against any
# path component, so nested layouts still work.
CAREER_DIRS = {
    "personal", "cover letter", "cover letters", "applied forms", "sops", "sop",
    "college submission list", "applications", "resume", "resumes", "cv",
}

RESEARCH_DIRS = {
    "research papers", "research", "dong xu project", "jianfeng research",
    "ml courseera", "neaural network courseera", "neural network courseera",
    "ml coursera", "qiskit", "matlab", "course", "coursework", "papers",
    "publications", "thesis",
}

# Dependency and build output. A course project with a checked-in node_modules
# contributes several thousand third-party READMEs, none of which are evidence
# of anything the user did.
JUNK_DIRS = {
    "node_modules", ".git", ".venv", "venv", "env", "__pycache__", "dist",
    "build", "out", ".next", ".nuxt", "target", "vendor", "site-packages",
    ".pytest_cache", ".mypy_cache", "coverage", ".gradle", "pods", ".idea",
    ".vscode", "bower_components", "jspm_packages", ".terraform", "bin", "obj",
}

# Never read. Not "read and then filter", never opened at all.
FORBIDDEN_DIRS = {
    "us tax forms", "tax", "taxes", "loan files", "loans", "lease docs", "lease",
    "passport", "ds160", "ds-160", "i20", "i-20", "visa", "immigration",
    "fee receipts", "receipts", "bank", "banking", "insurance", "medical",
    "health", "ssn", "credit", "payslips", "salary slips",
}

FORBIDDEN_NAME_PATTERNS = re.compile(
    r"(passport|visa|ds.?160|i.?20|ssn|social.?security|tax|w-?2|1040|bank|"
    r"statement|invoice|receipt|insurance|medical|prescription|license|"
    r"aadhaar|pan.?card|driving)",
    re.I,
)

# Classify a document by its own name once we know it is in scope.
DOC_KINDS = [
    (re.compile(r"resume|cv\b", re.I), "resume"),
    (re.compile(r"cover.?letter", re.I), "cover_letter"),
    (re.compile(r"\bsop\b|statement.?of.?purpose|personal.?statement", re.I), "sop"),
    (re.compile(r"recommendation|\blor\b|reference", re.I), "recommendation"),
    (re.compile(r"transcript|marksheet|grade", re.I), "transcript"),
    (re.compile(r"certificate|certification|bootcamp", re.I), "certificate"),
    (re.compile(r"paper|thesis|report|publication|abstract", re.I), "paper"),
    (re.compile(r"application|form", re.I), "application"),
]


def classify(path: Path) -> str:
    for pattern, kind in DOC_KINDS:
        if pattern.search(path.name):
            return kind
    return "other"


def category_of(path: Path, root: Path) -> str | None:
    """career, research, or None if out of scope."""
    try:
        parts = [p.lower() for p in path.relative_to(root).parts]
    except ValueError:
        parts = [p.lower() for p in path.parts]

    if any(p in FORBIDDEN_DIRS for p in parts):
        return None
    if any(p in JUNK_DIRS for p in parts):
        return None
    if FORBIDDEN_NAME_PATTERNS.search(path.name):
        return None
    if any(p in CAREER_DIRS for p in parts):
        return "career"
    if any(p in RESEARCH_DIRS for p in parts):
        return "research"
    return None


def discover(root: Path) -> list[tuple[Path, str, str]]:
    """Return (path, category, kind) for everything in scope."""
    found: list[tuple[Path, str, str]] = []
    if not root.exists():
        return found

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in SUPPORTED:
            continue
        if p.name.startswith((".", "~$")):
            continue
        cat = category_of(p, root)
        if cat:
            found.append((p, cat, classify(p)))
    return found


def extract_claims(text: str) -> list[str]:
    """Pull sentences that make a quantified claim.

    Not an evidence extractor, just a filter. build_evidence.py does the real
    work with an LLM. This narrows tens of thousands of words down to the
    handful of lines that actually assert something measurable, which keeps
    the downstream context small and the signal high.
    """
    claims = []
    # A number that is not a year, a page number, or a bare list index.
    numeric = re.compile(
        r"(\d+(?:\.\d+)?\s*%|"                    # percentages
        r"\$\s?\d[\d,.]*\s*[kmb]?|"               # money
        r"\b\d+(?:\.\d+)?\s*[xX]\b|"              # multipliers
        r"\b\d{2,}\s*(?:ms|s|sec|min|hours?|days?|weeks?|months?)\b|"
        r"\b\d{3,}\b)"                            # any number 100+
    )
    for raw in re.split(r"(?<=[.!?])\s+|\n", text):
        s = raw.strip()
        if not (25 <= len(s) <= 320):
            continue
        if not numeric.search(s):
            continue
        # Skip lines that are mostly dates or contact details.
        if re.fullmatch(r"[\d\s\-/.,()+]+", s):
            continue
        if re.search(r"[\w.+-]+@[\w-]+\.\w+", s):
            continue
        claims.append(re.sub(r"\s+", " ", s))
    return claims[:60]


def build(root: Path, list_only: bool = False) -> dict:
    targets = discover(root)
    print(f"{len(targets)} documents in scope under {root}", file=sys.stderr)

    by_cat: dict[str, int] = {}
    for _, cat, _ in targets:
        by_cat[cat] = by_cat.get(cat, 0) + 1
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:<10}{n}", file=sys.stderr)

    if list_only:
        return {
            "root": str(root),
            "documents": [
                {"path": str(p), "category": c, "kind": k} for p, c, k in targets
            ],
        }

    docs = []
    for i, (p, cat, kind) in enumerate(targets, 1):
        print(f"\r  reading {i}/{len(targets)}", end="", file=sys.stderr)
        d = read(p)
        if d.error or not d.text.strip():
            continue
        docs.append({
            "path": str(p),
            "name": p.name,
            "category": cat,
            "kind": kind,
            "words": d.words,
            "warnings": d.warnings,
            # Full text for resumes, SoPs, and cover letters, since those are
            # short and every line matters. Everything else gets truncated;
            # a 40 page paper contributes its abstract, not its appendices.
            "text": d.text if kind in ("resume", "cover_letter", "sop") else d.text[:6000],
            "truncated": kind not in ("resume", "cover_letter", "sop") and len(d.text) > 6000,
            "quantified_claims": extract_claims(d.text),
        })
    print(file=sys.stderr)

    # Resumes are the spine of the evidence bank, newest first.
    docs.sort(key=lambda d: (d["kind"] != "resume", d["name"]))

    return {
        "root": str(root),
        "document_count": len(docs),
        "by_category": by_cat,
        "excluded_dirs": sorted(FORBIDDEN_DIRS),
        "documents": docs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan career and research documents.")
    ap.add_argument("--root", default=str(Path.home() / "Documents"))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--list-only", action="store_true",
                    help="show what would be read, read nothing")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    if not root.exists():
        print(f"no such directory: {root}", file=sys.stderr)
        return 2

    data = build(root, args.list_only)

    if args.list_only:
        print(f"\n{'CATEGORY':<10}{'KIND':<16}PATH")
        print("-" * 100)
        for d in data["documents"]:
            print(f"{d['category']:<10}{d['kind']:<16}{d['path']}")
        print(f"\n{len(data['documents'])} documents. Nothing was read.")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nwrote {out}  ({data['document_count']} documents)", file=sys.stderr)

    claims = sum(len(d["quantified_claims"]) for d in data["documents"])
    print(f"  {claims} quantified claims found across all documents")

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"\n{'KIND':<16}{'WORDS':<8}{'CLAIMS':<8}NAME")
        print("-" * 92)
        for d in data["documents"][:30]:
            print(f"{d['kind']:<16}{d['words']:<8}{len(d['quantified_claims']):<8}{d['name'][:50]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
