#!/usr/bin/env python3
"""Enforce templates/style-rules.md against generated text.

The banned-phrase list is parsed out of style-rules.md itself so there is one
source of truth. Edit the markdown, not this file, to change what is banned.

Usage:
    python scripts/style_check.py draft.md
    python scripts/style_check.py draft.md --max-words 200
    cat draft.md | python scripts/style_check.py -
    python scripts/style_check.py draft.md --json

Exit codes:
    0  clean
    1  violations found
    2  bad invocation
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RULES = REPO / "templates" / "style-rules.md"

# Characters that must never appear. Mapped to the suggested replacement.
BANNED_CHARS: dict[str, str] = {
    "—": 'em dash. Use a comma, colon, parentheses, or two sentences.',
    "–": 'en dash. Use "to" for ranges, a hyphen elsewhere.',
    "…": "ellipsis character. Use three periods or rewrite.",
    "‘": "curly quote. Use a straight apostrophe.",
    "’": "curly quote. Use a straight apostrophe.",
    "“": "curly quote. Use a straight double quote.",
    "”": "curly quote. Use a straight double quote.",
    "•": "fancy bullet. Use a hyphen.",
    "▪": "fancy bullet. Use a hyphen.",
    "◦": "fancy bullet. Use a hyphen.",
    "→": "arrow. Use a word.",
    "⇒": "arrow. Use a word.",
    "✓": "checkmark. Use a word.",
    "✔": "checkmark. Use a word.",
    "★": "star glyph. Use a word.",
    " ": "non-breaking space. Some ATS parsers mangle it. Use a normal space.",
}

# Words that are legitimate inside a code block or a URL and should not be flagged.
SKIP_LINE_PATTERNS = [
    re.compile(r"^\s*```"),
    re.compile(r"^\s*(https?://|www\.)"),
]


@dataclass
class Violation:
    line: int
    col: int
    kind: str          # "char" | "phrase" | "length" | "adverb"
    found: str
    message: str
    context: str

    def render(self) -> str:
        return f"  {self.line}:{self.col}  {self.kind:7s} {self.found!r}\n      {self.message}\n      > {self.context}"


def is_emoji(ch: str) -> bool:
    if ch in ("‍", "️"):
        return True
    cp = ord(ch)
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x1F1E6 <= cp <= 0x1F1FF
    )


def load_banned_phrases(rules_path: Path = RULES) -> list[str]:
    """Pull every bullet item under '## HARD BAN: phrases' out of style-rules.md."""
    if not rules_path.exists():
        raise SystemExit(f"style rules not found at {rules_path}")

    phrases: list[str] = []
    in_section = False
    for raw in rules_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            in_section = line.strip() == "## HARD BAN: phrases"
            continue
        if not in_section:
            continue
        if line.startswith("- "):
            item = line[2:].strip()
            # Drop the parenthetical carve-outs: "leverage (as a verb; ...)"
            item = re.sub(r"\s*\(.*?\)\s*$", "", item).strip()
            # A bullet may list variants: "delve, delving"
            for variant in item.split(","):
                variant = variant.strip().lower()
                if variant and len(variant) > 2:
                    phrases.append(variant)
    return sorted(set(phrases), key=len, reverse=True)


def build_phrase_regex(phrases: list[str]) -> re.Pattern:
    alts = []
    for p in phrases:
        words = p.split()
        parts = [re.escape(w) for w in words]
        body = r"\s+".join(parts)
        # Single words get inflection tolerance so "leverage" also catches
        # "leveraged" and "utilize" catches "utilized". Multi-word phrases are
        # matched literally, since inflecting them produces false positives.
        if len(words) == 1:
            body += r"(?:s|d|ed|ing)?"
        alts.append(body)
    return re.compile(r"(?<![\w-])(" + "|".join(alts) + r")(?![\w-])", re.IGNORECASE)


# A file that declares this is defining the rules rather than obeying them.
# style-rules.md, this checker, and the normalizer in ats_check.py all have to
# contain the banned characters as literals. Without this marker, auditing the
# repo against its own rules reports its own tooling as violations, which is
# confusing enough that people stop running the audit.
EXEMPT_MARKER = "style-check: allow-banned-literals"


def check_text(text: str, max_words: int | None = None, min_words: int | None = None) -> list[Violation]:
    if EXEMPT_MARKER in text:
        return []

    violations: list[Violation] = []
    phrase_re = build_phrase_regex(load_banned_phrases())
    lines = text.splitlines()
    in_fence = False

    for i, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if any(p.match(line) for p in SKIP_LINE_PATTERNS):
            continue

        ctx = line.strip()[:100]

        for j, ch in enumerate(line, start=1):
            if ch in BANNED_CHARS:
                violations.append(Violation(i, j, "char", ch, BANNED_CHARS[ch], ctx))
            elif is_emoji(ch):
                violations.append(
                    Violation(i, j, "char", ch, "emoji. Never in a professional document.", ctx)
                )
            elif ord(ch) > 0x2000 and unicodedata.category(ch) in ("Pd", "Pi", "Pf"):
                violations.append(
                    Violation(i, j, "char", ch, "non-ASCII punctuation. Use the ASCII equivalent.", ctx)
                )

        for m in phrase_re.finditer(line):
            violations.append(
                Violation(
                    i,
                    m.start() + 1,
                    "phrase",
                    m.group(0),
                    "banned phrase. See templates/style-rules.md.",
                    ctx,
                )
            )

    words = len(re.findall(r"\b[\w'-]+\b", text))
    if max_words is not None and words > max_words:
        violations.append(
            Violation(0, 0, "length", f"{words} words",
                      f"over the {max_words} word cap by {words - max_words}.", "")
        )
    if min_words is not None and words < min_words:
        violations.append(
            Violation(0, 0, "length", f"{words} words",
                      f"under the {min_words} word floor by {min_words - words}.", "")
        )

    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description="Enforce style-rules.md on a draft.")
    ap.add_argument("path", help="file to check, or - for stdin")
    ap.add_argument("--max-words", type=int, default=None, help="fail if the draft exceeds this")
    ap.add_argument("--min-words", type=int, default=None, help="fail if the draft is under this")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if args.path == "-":
        text = sys.stdin.read()
        label = "<stdin>"
    else:
        p = Path(args.path)
        if not p.exists():
            print(f"no such file: {p}", file=sys.stderr)
            return 2
        text = p.read_text(encoding="utf-8")
        label = str(p)

    violations = check_text(text, args.max_words, args.min_words)
    words = len(re.findall(r"\b[\w'-]+\b", text))

    if args.json:
        print(json.dumps({
            "file": label,
            "words": words,
            "clean": not violations,
            "violations": [asdict(v) for v in violations],
        }, indent=2))
        return 1 if violations else 0

    if not violations:
        print(f"STYLE OK  {label}  ({words} words)")
        return 0

    print(f"STYLE FAIL  {label}  ({words} words, {len(violations)} violations)\n")
    for v in violations:
        print(v.render())
    print(f"\nFix all {len(violations)} before shipping. Rules: templates/style-rules.md")
    return 1


if __name__ == "__main__":
    sys.exit(main())
