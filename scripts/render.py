#!/usr/bin/env python3
"""Render a markdown resume or letter into an ATS-safe DOCX, and optionally PDF.

Everything this module refuses to do is deliberate. No tables, no text boxes,
no columns, no headers or footers, no icon fonts, no images. Each of those is a
known way to have your resume parsed into garbage or dropped entirely, and each
one is something a design-forward template will happily give you.

DOCX is the primary output. It is the format most ATS platforms parse most
reliably, and several extract it more faithfully than PDF.

Markdown subset supported:
    # Name                -> document title block
    ## Section            -> section heading
    ### Role | Company | Location | Dates   -> role line, pipe separated
    - bullet              -> bullet
    **bold** and *italic* -> inline formatting
    plain line            -> paragraph
    ---                   -> ignored

Usage:
    python scripts/render.py resume.md -o out/resume.docx
    python scripts/render.py resume.md -o out/resume.docx --pdf
    python scripts/render.py letter.md -o out/letter.docx --style letter
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, Inches, RGBColor
except ImportError:
    print("python-docx is required. Run: pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1)

# Fonts that exist on essentially every machine and every parser. A resume set
# in a font the reader lacks gets substituted, and substitution can break the
# one-page layout you carefully tuned.
SAFE_FONTS = {"resume": "Calibri", "letter": "Calibri"}

INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")


def _style_document(doc, style: str) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = SAFE_FONTS[style]
    normal.font.size = Pt(10.5 if style == "resume" else 11)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.line_spacing = 1.0

    for section in doc.sections:
        section.top_margin = Inches(0.5 if style == "resume" else 1.0)
        section.bottom_margin = Inches(0.5 if style == "resume" else 1.0)
        section.left_margin = Inches(0.7 if style == "resume" else 1.0)
        section.right_margin = Inches(0.7 if style == "resume" else 1.0)


def _add_runs(para, text: str, base_bold: bool = False) -> None:
    """Write text into a paragraph, honoring **bold** and *italic*."""
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            r = para.add_run(part[2:-2]); r.bold = True
        elif part.startswith("*") and part.endswith("*"):
            r = para.add_run(part[1:-1]); r.italic = True
        else:
            r = para.add_run(part)
        if base_bold:
            r.bold = True


def _heading(doc, text: str, style: str):
    """Section heading rendered with direct formatting, not a Word style.

    Word's built-in Heading styles carry outline levels and theme colors that
    some parsers mishandle. Plain bold uppercase on a Normal paragraph is
    boring, universally understood, and cannot be misread.
    """
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(9)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text.upper())
    r.bold = True
    r.font.size = Pt(11)
    r.font.color.rgb = RGBColor(0, 0, 0)

    # A bottom rule, drawn as a border on the paragraph rather than as a table
    # or a row of underscores. Parsers ignore borders; underscores become text.
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    pPr = p._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "000000")
    borders.append(bottom)
    pPr.append(borders)
    return p


def _role_line(doc, raw: str) -> None:
    """### Title | Company | Location | Dates

    Rendered as two lines: bold title and company, then a lighter detail line.
    Deliberately NOT a right-aligned tab stop or a two-cell table, both of
    which are the usual way this is done and both of which confuse parsers.
    """
    parts = [p.strip() for p in raw.split("|")]
    p1 = doc.add_paragraph()
    p1.paragraph_format.space_before = Pt(6)
    head = ", ".join(x for x in parts[:2] if x)
    _add_runs(p1, head, base_bold=True)

    tail = "  |  ".join(x for x in parts[2:] if x)
    if tail:
        p2 = doc.add_paragraph()
        p2.paragraph_format.space_after = Pt(2)
        r = p2.add_run(tail)
        r.italic = True
        r.font.size = Pt(10)


def _bullet(doc, text: str) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.left_indent = Inches(0.22)
    _add_runs(p, text)


def markdown_to_docx(md: str, out: Path, style: str = "resume") -> Path:
    doc = docx.Document()
    _style_document(doc, style)

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped or stripped == "---":
            if not stripped:
                # Preserve intentional blank lines in letters, where paragraph
                # separation is meaningful. Resumes are dense; skip them there.
                if style == "letter":
                    doc.add_paragraph()
            i += 1
            continue

        if stripped.startswith("### "):
            _role_line(doc, stripped[4:])
        elif stripped.startswith("## "):
            _heading(doc, stripped[3:], style)
        elif stripped.startswith("# "):
            # Name block. Largest text on the page, centered, nothing else.
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(stripped[2:])
            r.bold = True
            r.font.size = Pt(18)
            # A contact line immediately after the name gets centered too.
            if i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].startswith("#"):
                cp = doc.add_paragraph()
                cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                cp.paragraph_format.space_after = Pt(4)
                cr = cp.add_run(lines[i + 1].strip())
                cr.font.size = Pt(10)
                i += 1
        elif stripped.startswith(("- ", "* ")):
            _bullet(doc, stripped[2:])
        else:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(4 if style == "letter" else 1)
            _add_runs(p, stripped)

        i += 1

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out


def docx_to_pdf(docx_path: Path) -> Path | None:
    """Convert via LibreOffice if available.

    No silent fallback to a lower-fidelity path. If the conversion cannot be
    done properly, the caller is told to export from Word, because a mangled
    PDF is worse than no PDF.
    """
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        mac_soffice = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        soffice = str(mac_soffice) if mac_soffice.exists() else None
    if not soffice:
        return None

    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", str(docx_path.parent), str(docx_path)],
            check=True, capture_output=True, timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    pdf = docx_path.with_suffix(".pdf")
    return pdf if pdf.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Markdown to ATS-safe DOCX.")
    ap.add_argument("input", help="markdown file")
    ap.add_argument("-o", "--output", help="output .docx path")
    ap.add_argument("--style", choices=["resume", "letter"], default="resume")
    ap.add_argument("--pdf", action="store_true", help="also produce a PDF")
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    if not src.exists():
        print(f"no such file: {src}", file=sys.stderr)
        return 2

    out = Path(args.output).expanduser() if args.output else src.with_suffix(".docx")
    md = src.read_text(encoding="utf-8")

    # Refuse to render text that violates the style rules. Catching an em dash
    # here, before it reaches a recruiter, is the whole point.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from style_check import check_text
    violations = [v for v in check_text(md) if v.kind == "char"]
    if violations:
        print("refusing to render, banned characters present:", file=sys.stderr)
        for v in violations[:10]:
            print(f"  line {v.line}: {v.found!r}  {v.message}", file=sys.stderr)
        print("\nRun: python scripts/style_check.py " + str(src), file=sys.stderr)
        return 1

    docx_path = markdown_to_docx(md, out, args.style)
    print(f"wrote {docx_path}")

    if args.pdf:
        pdf = docx_to_pdf(docx_path)
        if pdf:
            print(f"wrote {pdf}")
        else:
            print("\nPDF conversion unavailable (LibreOffice not found).")
            print("Open the DOCX and export as PDF, or: brew install --cask libreoffice")
            print("Note: most ATS platforms parse the DOCX more reliably anyway.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
