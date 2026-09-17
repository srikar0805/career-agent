#!/usr/bin/env python3
"""A tailored resume in about a minute, without Claude: adapt the closest verified variant.

Srikar, 2026-09-16: apply to every open posting in the pipeline, with a full Opus build
only for the ten best and a fast build for the rest. A full Opus build took about an hour
that day and his plan limit stopped two of them, so 144 postings cannot all get one.

What stays exactly as verified: every experience, project and education bullet. The base
is one of the variants built since the 2026-09-07 rules that passes all six PDF gates
(data/fast_resume_bases.json), and every bullet in it already went through the fact-checker.
What changes for the posting:
  the tagline role        the posting's own title, trimmed of team names and req ids
  the tagline technology  the technologies the posting names, in its order, that he has used
  the relocation phrase   the posting's city, or "open to relocation"
  the skills section      scripts/skills_basis.py (every posting technology he has used)
LaTeX comment lines from the base are dropped: they describe the base's posting, not this one.

    fast_resume.py --app 318              build, gate, copy to Resumes/final, log the artifacts
    fast_resume.py --app 318 --dry-run    choose the base and show the new tagline only
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from agent_verdict import posting_text, row        # noqa: E402
from skills_basis import LEXICON, apply as skills_apply, posting_terms, records, resume_plain   # noqa: E402

FINAL = Path.home() / "Developer" / "Resumes" / "final"
BASES = ROOT / "data" / "fast_resume_bases.json"

FAMILIES = [   # (family, title pattern, preferred bases in order)
    ("quant", r"quant|trading|portfolio|trader", ["Srikar_Resume_SIG", "Srikar_Resume_Point72", "Srikar_Resume_Acadian"]),
    ("sre", r"reliability|devops|infrastructure|cloud engineer|platform engineer|systems engineer|site ops",
     ["Srikar_Resume_Equifax", "Srikar_Resume_C3AI_Platform_FullStack"]),
    ("ml", r"machine learning|\bml\b|\bai\b|artificial intelligence|computer vision|deep learning|applied scientist|"
           r"research engineer|ai scientist|llm|nlp|forward deployed", ["Srikar_Resume_Deeter", "Srikar_Resume_StudyFetch", "Srikar_Resume_BCG"]),
    ("data_scientist", r"data scien|statistic|decision scien|analytics scien", ["Srikar_Resume_Mulligan", "Srikar_Resume_Mulligan_FS"]),
    ("data_engineer", r"data engineer|etl|data platform|analytics engineer|data developer",
     ["Srikar_Resume_Mulligan_FS", "Srikar_Resume_Emerson", "Srikar_Resume_Equifax"]),
    ("analyst", r"analyst|business intelligence|\bbi\b|reporting|insights|operations research",
     ["Srikar_Resume_Emerson", "Srikar_Resume_Hoffman", "Srikar_Resume_Zoox"]),
    ("web", r"web|front[- ]?end|ui\b|full[- ]?stack", ["Srikar_Resume_C3AI_Platform_FullStack", "Srikar_Resume_RedBud"]),
    ("swe", r".", ["Srikar_Resume_DigitalOcean", "Srikar_Resume_Emerson_SWE", "Srikar_Resume_C3AI_Platform_FullStack"]),
]


def token(s: str, n: int = 24) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", s.title())[:n] or "Role"


def clean_title(title: str) -> str:
    """The posting's role without cohort, season, team, location or req-id noise."""
    t = re.sub(r"^\s*(summer|spring|fall|winter)?\s*20\d\d\s*[-\u2013:]?\s*", "", title, flags=re.I)   # "Summer 2027- SDE"
    t = re.sub(r"\((?:[^)]*(?:20\d\d|grad|remote|hybrid|onsite|req|rq|job|\d{4,})[^)]*)\)", "", t, flags=re.I)
    t = t.replace(" / ", " & ")
    t = re.split(r"\s+[-\u2013\u2014|:]\s+|\s*,\s+|\s*\(", t)[0]
    t = re.sub(r"\b(new grad(uate)?|early career|university grad(uate)?|college grad|campus|20\d\d)\b", "", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip(" -,&")
    return (t or title)[:48].strip()


def latex_escape(s: str) -> str:
    return s.replace("\\", "").replace("&", r"\&").replace("%", r"\%").replace("#", r"\#").replace("$", r"\$")


def choose_base(title: str, posting: str) -> tuple[str, str]:
    available = set(json.loads(BASES.read_text())) if BASES.exists() else set()
    recent_cut = time.time() - 3 * 3600                  # skip a variant another build may still be writing
    named = posting_terms(posting)
    for family, pat, prefs in FAMILIES:
        if not re.search(pat, title, re.I):
            continue
        usable = [b for b in prefs if b in available and (ROOT / "latex" / "resume" / b / "main.tex").exists()
                  and (ROOT / "latex" / "resume" / b / "main.tex").stat().st_mtime < recent_cut]
        if not usable:
            continue

        def overlap(b):
            plain = resume_plain((ROOT / "latex" / "resume" / b / "main.tex").read_text())
            return sum(1 for k in named if re.search(LEXICON[k][1], plain, 0 if k in ("r", "c") else re.I))
        return family, max(usable, key=lambda b: (overlap(b), -prefs.index(b)))
    raise SystemExit("no usable base variant")


def rewrite_header(tex: str, role_title: str, techs: list[str], city: str) -> str:
    tex = "\n".join(l for l in tex.splitlines() if not re.match(r"\s*%", l)) + "\n"
    center = re.search(r"\\begin\{center\}(.*?)\\end\{center\}", tex, re.S)
    if not center:
        return tex
    head = center.group(1)
    m = re.search(r"(\s*)\\textbf\{[^}]*\}(\s*\\,\s*\$\\vert\$\s*\\,\s*)(.*?)(\s*\\\\)", head, re.S)
    if m:
        # Keep the tagline about as long as the base's: a short centred tagline reads to
        # line_check as a runt line (SingleStore, 2026-09-16). Posting technologies first,
        # then the base's own, which were fact-checked with it.
        base_techs = [re.sub(r"~", " ", t) for t in re.findall(r"\\textbf\{([^}]*)\}", m.group(3))]
        merged = []
        for t in techs + base_techs:
            if t.lower() not in {x.lower() for x in merged}:
                merged.append(t)
        merged = merged[:7] if techs else base_techs
        tech_tex = ", ".join(f"\\textbf{{{latex_escape(t).replace(' ', '~')}}}" for t in merged) if techs else m.group(3)
        head = head[:m.start()] + f"{m.group(1)}\\textbf{{{latex_escape(role_title)}}}{m.group(2)}{tech_tex}{m.group(4)}" + head[m.end():]
    # the second line's last segment says where he is going: "Open to Seattle{,} WA",
    # "\textbf{Graduating May 2027{,} relocating to Redwood City}" and so on
    lines = head.rstrip().split("\n")
    last = lines[-1]
    parts = re.split(r"(\s*\\,\s*\$\\vert\$\s*\\,\s*)", last)
    seg = parts[-1]
    if re.search(r"open to|relocat|graduating", seg, re.I):
        where = f"relocating to {latex_escape(city)}" if city else "open to relocation"
        if seg.strip().startswith("\\textbf{"):
            parts[-1] = f"\\textbf{{Graduating May 2027{{,}} {where}}}"
        else:
            parts[-1] = f"Open to {latex_escape(city)}" if city else "Open to relocation"
        lines[-1] = "".join(parts)
    head = "\n".join(lines) + "\n"
    return tex[:center.start(1)] + head + tex[center.end(1):]


def build(app_id: int, dry: bool = False, base: str | None = None) -> dict:
    """base: rebuild from this variant instead of choosing one. The bullet rewrite of 2026-09-17
    rebuilt each prepared resume from the base it was first built on, and choose_base skips any
    variant edited in the last 3 hours, which every freshly rewritten base is."""
    from agent_keywords import compile_tex, gates
    r = row(app_id)
    posting = posting_text(r)
    if len(posting) < 400:
        return {"ok": False, "why": "no readable posting text"}
    if base:
        family = next((f for f, pat, prefs in FAMILIES if base in prefs and re.search(pat, r["role"], re.I)),
                      next((f for f, pat, prefs in FAMILIES if base in prefs), "swe"))
    else:
        family, base = choose_base(r["role"], posting)
    base_tex = (ROOT / "latex" / "resume" / base / "main.tex").read_text()
    used, _ = records()
    named = posting_terms(posting)
    order = sorted(named, key=lambda k: (re.search(LEXICON[k][1], posting, 0 if k in ("r", "c") else re.I).start()))
    base_plain = resume_plain(base_tex)
    techs = [named[k] for k in order if k in used or re.search(LEXICON[k][1], base_plain, 0 if k in ("r", "c") else re.I)][:7]
    loc = (r.get("location") or "").strip()
    city = "" if (not loc or re.search(r"remote|multiple|various|united states|\bUS\b|anywhere", loc, re.I)) else \
        re.split(r"\s*[,;/|]\s*|\s+-\s+", loc)[0].strip().strip(",")
    role_title = clean_title(r["role"])
    info = {"app_id": app_id, "family": family, "base": base, "role_title": role_title, "techs": techs, "city": city or None}
    if dry:
        return {"ok": True, **info}

    d = ROOT / "latex" / "resume" / f"Srikar_Resume_{token(r['company'], 18)}_{token(role_title, 22)}_fast"
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(ROOT / "latex" / "resume" / base, d, ignore=shutil.ignore_patterns("main.pdf", "*.pre-*", "*.log", "*.aux"))
    tex_path = d / "main.tex"
    header_ok = False
    generic = {"quant": "Quantitative Developer", "sre": "Site Reliability Engineer", "ml": "Machine Learning Engineer",
               "data_scientist": "Data Scientist", "data_engineer": "Data Engineer", "analyst": "Data Analyst",
               "web": "Software Engineer", "swe": "Software Engineer"}[family]
    attempts = [(role_title, t, city) for t in (techs, techs[:4], techs[:2], [])] + [(role_title, [], "")] \
        + [(generic, [], "")]         # InterSystems and Keysight: a long title wrapped and pushed the page to two
    for title_used, tech_list, where in attempts:
        tex_path.write_text(rewrite_header(base_tex, title_used, tech_list, where))
        g = gates(tex_path, d / "main.pdf") if compile_tex(tex_path) else None
        if g and all(g.values()):
            header_ok, info["techs"], info["role_title"] = True, tech_list, title_used
            break
    if not header_ok:
        return {"ok": False, "why": f"tagline rewrite broke a PDF gate: {g}", **info}
    sk = skills_apply(app_id, tex_path, dry=False)
    info.update(skills_added=sk["applied"], skills_confirm=[c["name"] for c in sk["confirm"]])
    # the relocation city must be this posting's (or none): read it from the rendered PDF, not the source
    pdf_text = subprocess.run(["pdftotext", str(d / "main.pdf"), "-"], capture_output=True, text=True).stdout
    leftovers = [w.strip() for w in re.findall(r"(?:relocating to|Open to) ([A-Z][A-Za-z .]+)", pdf_text)
                 if w.strip() not in (city, "relocation") and not (city and w.strip().startswith(city))]
    if leftovers:
        return {"ok": False, "why": f"base-specific text survived: {leftovers}", **info}
    FINAL.mkdir(parents=True, exist_ok=True)
    pdf = FINAL / f"SaiSrikarKolli_{token(r['company'], 18)}_{token(role_title, 22)}.pdf"
    shutil.copy2(d / "main.pdf", pdf)
    (d / "BUILD.md").write_text(
        f"# Fast build for #{app_id} {r['company']} / {r['role']}\n\nBase variant: {base} (family {family}); every bullet is "
        f"unchanged from it and was fact-checked when it was built.\nTagline: {role_title} | {', '.join(info['techs'])}\n"
        f"Skills added: {', '.join(sk['applied']) or 'none'}\nConfirm before adding (no record of use): "
        f"{', '.join(info['skills_confirm']) or 'none'}\n")
    for kind, path in (("resume", str(pdf)), ("resume_tex", str(tex_path.relative_to(ROOT)))):
        subprocess.run([sys.executable, str(HERE / "pipeline.py"), "artifact", str(app_id), "--kind", kind, "--path", path],
                       capture_output=True, text=True)
    return {"ok": True, "pdf": str(pdf), "tex": str(tex_path), **info}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    out = build(a.app, a.dry_run)
    print(json.dumps(out, indent=1))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
