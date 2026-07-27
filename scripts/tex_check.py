#!/usr/bin/env python3
"""Compile a LaTeX resume and measure whether an ATS can actually read it.

The point of this script is empirical verification. There is a lot of folklore
about making LaTeX resumes "ATS friendly", most of it untested. This compiles
the real document and inspects the real text layer, so a proposed fix either
measurably changes the extraction or it does not.

What it reports, in order of how badly each one hurts:

  space glyphs      Does the PDF contain literal space characters? LaTeX
                    normally renders inter-word gaps as positioning rather than
                    spaces, so a naive parser reads one continuous string.
  unicode mapping   Do glyphs map back to Unicode, or do they extract as
                    (cid:NNN)? Usually fixed by \\input{glyphtounicode} plus
                    \\pdfgentounicode=1, which this script can verify.
  column layout     Does the text sit in one column as a parser reads it?
  keyword coverage  Against a real posting, if one is supplied.

Usage:
    python scripts/tex_check.py resume.tex
    python scripts/tex_check.py resume.tex --jd posting.txt
    python scripts/tex_check.py resume.tex --compare old.pdf
    python scripts/tex_check.py --pdf-only existing.pdf
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from ingest import read, _has_gutter  # noqa: E402
from ats_check import run as ats_run  # noqa: E402


def find_engine() -> tuple[str, list[str]] | None:
    """Prefer tectonic: self-contained, fetches packages on demand, no TeX Live."""
    if shutil.which("tectonic"):
        return "tectonic", ["tectonic", "--keep-logs", "--print"]
    if shutil.which("latexmk"):
        return "latexmk", ["latexmk", "-pdf", "-interaction=nonstopmode"]
    for e in ("lualatex", "xelatex", "pdflatex"):
        if shutil.which(e):
            return e, [e, "-interaction=nonstopmode"]
    return None


def compile_tex(tex: Path, outdir: Path) -> tuple[Path | None, str]:
    engine = find_engine()
    if not engine:
        return None, ("No LaTeX engine found. Install one:\n"
                      "  brew install tectonic        (recommended, self-contained)\n"
                      "  brew install --cask mactex   (full, several GB)")

    name, cmd = engine
    outdir = outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    # Run from the .tex file's own directory so a sibling resume.cls resolves,
    # but pass an absolute path, since a relative one is interpreted against
    # that same directory and would not be found.
    tex = tex.resolve()

    if name == "tectonic":
        full = [*cmd, "--outdir", str(outdir), str(tex)]
    elif name == "latexmk":
        full = [*cmd, f"-outdir={outdir}", str(tex)]
    else:
        full = [*cmd, "-output-directory", str(outdir), str(tex)]

    try:
        proc = subprocess.run(full, capture_output=True, text=True, timeout=300,
                              cwd=str(tex.parent))
    except subprocess.TimeoutExpired:
        return None, f"{name} timed out after 300s"

    pdf = outdir / (tex.stem + ".pdf")
    if not pdf.exists():
        log = (proc.stderr or "") + (proc.stdout or "")
        errors = [l for l in log.splitlines()
                  if l.startswith("!") or "error" in l.lower()][:15]
        return None, f"{name} did not produce a PDF.\n" + "\n".join(errors)

    return pdf, f"compiled with {name}"


def probe(pdf: Path) -> dict:
    """Measure the text layer the way an ATS parser would see it."""
    try:
        import pdfplumber
    except ImportError:
        raise SystemExit("pdfplumber required. pip install -r requirements.txt")

    with pdfplumber.open(pdf) as doc:
        pages = len(doc.pages)
        chars = [c for p in doc.pages for c in p.chars]
        spaces = sum(1 for c in chars if c["text"] == " ")
        right = 0
        words_total = 0
        gutter = False
        for p in doc.pages:
            ws = p.extract_words() or []
            words_total += len(ws)
            right += sum(1 for w in ws if w["x0"] > p.width / 2)
            gutter = gutter or _has_gutter(p)

    d = read(pdf)
    cids = d.text.count("(cid:")

    return {
        "pages": pages,
        "chars": len(chars),
        "space_chars": spaces,
        "space_ratio": (spaces / len(chars)) if chars else 0.0,
        "right_ratio": (right / words_total) if words_total else 0.0,
        "gutter": gutter,
        "cid_count": cids,
        "words": d.words,
        "text": d.text,
        "warnings": d.warnings,
    }


def verdict_line(label: str, ok: bool, detail: str) -> str:
    return f"  [{'PASS' if ok else 'FAIL'}] {label:<20}{detail}"


def report(p: dict, title: str) -> None:
    print(f"\n{title}")
    print(f"  {p['pages']} page(s), {p['words']} words, {p['chars']} glyphs\n")

    print(verdict_line(
        "space glyphs", p["space_ratio"] >= 0.05,
        f"{p['space_chars']} literal spaces ({100*p['space_ratio']:.1f}% of glyphs). "
        + ("healthy" if p["space_ratio"] >= 0.05
           else "a simple parser will read this as one continuous string")))

    print(verdict_line(
        "unicode mapping", p["cid_count"] == 0,
        "all glyphs map to Unicode" if p["cid_count"] == 0
        else f"{p['cid_count']} unmapped (cid:NNN) glyphs, add \\input{{glyphtounicode}} "
             f"and \\pdfgentounicode=1"))

    print(verdict_line(
        "single column", not p["gutter"],
        ("no vertical gutter; "
         f"the {100*p['right_ratio']:.0f}% of words past the midpoint are "
         "right-aligned dates, which parse fine")
        if not p["gutter"] else
        "a persistent vertical gutter splits the text, so a parser will "
        "interleave the two sides into nonsense"))

    print(verdict_line(
        "page count", p["pages"] <= 1,
        f"{p['pages']} page(s)" + ("" if p["pages"] <= 1 else ", trim to 1")))


def main() -> int:
    ap = argparse.ArgumentParser(description="Compile LaTeX and measure ATS readability.")
    ap.add_argument("source", nargs="?", help="path to the .tex file")
    ap.add_argument("--pdf-only", help="skip compilation, probe an existing PDF")
    ap.add_argument("--jd", help="job posting to score keyword coverage against")
    ap.add_argument("--company", help="employer name, excluded from keyword scoring")
    ap.add_argument("--compare", help="a second PDF to diff the metrics against")
    ap.add_argument("--outdir", help="where to write the compiled PDF")
    ap.add_argument("--show-text", action="store_true",
                    help="print the extracted text, which is what an ATS receives")
    args = ap.parse_args()

    if args.pdf_only:
        pdf = Path(args.pdf_only).expanduser()
        if not pdf.exists():
            print(f"no such file: {pdf}", file=sys.stderr)
            return 2
        note = "existing PDF, not compiled"
    else:
        if not args.source:
            print("give a .tex file, or use --pdf-only", file=sys.stderr)
            return 2
        tex = Path(args.source).expanduser()
        if not tex.exists():
            print(f"no such file: {tex}", file=sys.stderr)
            return 2
        outdir = Path(args.outdir).expanduser() if args.outdir else Path(tempfile.mkdtemp())
        pdf, note = compile_tex(tex, outdir)
        if not pdf:
            print(note, file=sys.stderr)
            return 1

    print(f"{note}\n{pdf}")
    p = probe(pdf)
    report(p, "ATS READABILITY")

    if args.compare:
        other = Path(args.compare).expanduser()
        if other.exists():
            q = probe(other)
            report(q, f"BASELINE: {other.name}")
            print("\nDELTA")
            for key, label, pct in (("space_ratio", "space glyphs", True),
                                    ("right_ratio", "past midpoint", True),
                                    ("cid_count", "unmapped glyphs", False),
                                    ("words", "words", False)):
                a, b = p[key], q[key]
                if pct:
                    print(f"  {label:<18}{100*b:>7.1f}%  ->  {100*a:>6.1f}%")
                else:
                    print(f"  {label:<18}{b:>8}  ->  {a:>7}")

    if args.jd:
        jd = Path(args.jd).expanduser()
        if jd.exists():
            res = ats_run(p["text"], read(jd).text, p["warnings"], args.company)
            print(f"\nKEYWORD COVERAGE vs {jd.name}")
            print(f"  {res['coverage_percent']}%  "
                  f"({res['keywords_found']} present, {res['keywords_missing']} missing)")
            if res["missing"]:
                print("  top missing: " +
                      ", ".join(m["term"] for m in res["missing"][:8]))

    if args.show_text:
        print("\nWHAT AN ATS RECEIVES\n" + "-" * 70)
        print(p["text"])

    fatal = p["space_ratio"] < 0.05 or p["cid_count"] > 0 or p["gutter"]
    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main())
