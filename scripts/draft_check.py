#!/usr/bin/env python3
"""Count every draft body in an outreach drafts file.

Connection notes are capped at 300 characters (LinkedIn Premium since
2026-09-02) and cold messages at 80 words. Each `### ` heading is followed by
its body as a single paragraph, then an `Evidence:` paragraph, so the first
paragraph after the heading is the body. Flags em dashes, which are banned.

    python scripts/draft_check.py data/artifacts/outreach-2026-09-10/drafts.md
"""
import re
import sys

EM_DASH = "—"


def main(path):
    text = open(path, encoding="utf-8").read()
    blocks = re.split(r"\n### ", text)[1:]
    bad = 0
    for block in blocks:
        head, _, rest = block.partition("\n")
        paras = [p.strip() for p in rest.split("\n\n") if p.strip()]
        body = paras[0] if paras else ""
        words = len(body.split())
        chars = len(body)
        flags = []
        if EM_DASH in body:
            flags.append("EM DASH")
        if "note" in head.lower() and chars > 300:
            flags.append("OVER 300")
        if "acceptance" in head.lower() and words > 80:
            flags.append("OVER 80 WORDS")
        if flags:
            bad += 1
        print(f"{head[:58]:58s} chars={chars:4d} words={words:3d} {' '.join(flags)}")
    print(f"{len(blocks)} drafts, {bad} over cap")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "drafts.md"))
