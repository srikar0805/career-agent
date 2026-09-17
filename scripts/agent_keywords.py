#!/usr/bin/env python3
"""NVIDIA agent: work the posting's missing keywords into a built resume, safely.

Srikar's flow (2026-09-16): Claude builds the resume, then an NVIDIA agent does
the fit analysis and updates the resume for the missing keywords, then Claude
runs the final fit analysis. This is the middle step.

It is the riskiest thing an outside model does in this repo, because a resume is
a factual document that has already survived a fact check. So the model only
PROPOSES line edits, and code decides what lands:

  1. Keyword gaps come from ats_check.py, not from the model.
  2. A gap is addable only if the evidence bank already supports it. The rest are
     reported as real gaps and never written in.
  3. Every proposed edit must: target an existing \\item or skills line; introduce
     no number that was not already on that line; add only addable keywords; add
     no other technology the evidence bank does not mention; keep braces balanced;
     use no em or en dashes; grow the line by at most 80 characters; add no
     scale or ownership claim; put nothing on a skills line that no bullet on the
     page demonstrates; and never add a term the resume's trace.md records as
     deliberately left out (C3.ai, 2026-09-16: Java, reverted by hand).
  4. Accepted edits are compiled with tectonic and all six PDF gates run. If the
     set fails, edits are applied one at a time and only those that keep every
     gate green are kept.

    agent_keywords.py --app 247 --tex latex/resume/Srikar_Resume_Equifax/main.tex            propose only
    agent_keywords.py --app 247 --tex .../main.tex --apply                                     edit, compile, gate

With --apply the original is kept beside it as main.pre-keywords.tex. Nothing is
copied to ~/Developer/Resumes/final; shipping stays a separate, deliberate step.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from agent_verdict import out_path as verdict_path, posting_text, row, slug   # noqa: E402
from nim import NimError, chat                                                # noqa: E402

# What counts as support. Not the raw file: notes and sources mention technologies
# he does NOT have, and skills.yaml lists "kubernetes" as coursework-asserted with
# no evidence at all, which a first draft of this check accepted on 2026-09-16.
_ATOMS = [a for a in yaml.safe_load((ROOT / "profile" / "evidence.yaml").read_text())
          if a.get("confidence") != "unverifiable"]
EVIDENCE = json.dumps([{k: a.get(k) for k in ("action", "tech", "skills", "star", "scope")} for a in _ATOMS]).lower()
SKILL_NAMES = {s["name"].lower() for s in yaml.safe_load((ROOT / "profile" / "skills.yaml").read_text())
               if s.get("evidence") and "asserted" not in str(s.get("level", "")) and "unbacked" not in str(s.get("level", ""))}
PY = sys.executable

SYSTEM = r"""You edit resume bullets written in LaTeX to include keywords a job posting uses. \
You never invent experience. You only rephrase a line so a keyword the candidate's evidence \
already supports appears where that work is described.

Hard rules:
- Edit only the numbered lines given. Return the FULL new line, starting with \item when the original does.
- Add only keywords from the ADDABLE list, and only to a line describing work that supports that keyword.
- Do not add, remove or change any number.
- Keep the LaTeX valid: same commands as the original (\textbf{...}, ~, \%, \&), balanced braces.
- Keep the line about the same length: at most 80 characters longer.
- No em dashes or en dashes.
- If a keyword fits no line honestly, leave it out. Fewer honest edits beat more.

Reply with ONE JSON object:
{"edits": [{"line": <line number>, "new": "<full new line>", "keywords": ["<addable keyword used>"]}]}"""


def gates(tex: Path, pdf: Path) -> dict[str, bool]:
    checks = {"page": ["page_check.py", pdf], "line": ["line_check.py", pdf], "spacing": ["spacing_check.py", tex, pdf],
              "chrono": ["chrono_check.py", pdf], "title": ["title_check.py", pdf], "tex": ["tex_check.py", tex]}
    return {k: subprocess.run([PY, str(HERE / v[0]), *map(str, v[1:])], capture_output=True).returncode == 0
            for k, v in checks.items()}


def compile_tex(tex: Path) -> bool:
    r = subprocess.run(["tectonic", "--keep-logs", "--chatter", "minimal", tex.name], cwd=tex.parent,
                       capture_output=True, text=True, timeout=300)
    return r.returncode == 0 and (tex.parent / "main.pdf").exists()


def ats(pdf: Path, jd: str, company: str) -> dict:
    r = subprocess.run([PY, str(HERE / "ats_check.py"), "--resume", str(pdf), "--jd-text", jd,
                        "--company", company, "--json"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"coverage_percent": None, "present": [], "missing": []}


def _t(s: str) -> str:
    return re.sub(r"[-_\s]+", " ", s.lower()).strip()


# Technology names only. On 2026-09-16 the first live run treated ats_check's generic
# "missing" words (documentation, optimization, enterprise) as supported because they
# occur somewhere in his evidence prose, and wrote "for documentation" and "at
# enterprise scale" onto real bullets. A keyword worth adding is a named technology
# he has evidence for, not an English word the posting happens to use.
TECH_TERMS = {_t(s) for s in SKILL_NAMES} | {_t(t) for a in _ATOMS for t in (a.get("tech") or []) if isinstance(t, str)}

# Words that change what a bullet CLAIMS about scale, ownership or seniority.
CLAIM_WORDS = re.compile(r"\b(enterprise|production|large[- ]scale|at scale|scalable|global|fortune|millions?|"
                         r"thousands|mission[- ]critical|senior|led|lead|leading|managed|owned|spearheaded|"
                         r"architected|distributed|real[- ]time|high[- ]traffic|industry[- ]leading)\b", re.I)


def supported(keyword: str) -> bool:
    """A technology he has evidence for (used for any word an edit introduces)."""
    k = keyword.lower().strip()
    return _t(k) in TECH_TERMS or k in SKILL_NAMES or \
        re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", EVIDENCE) is not None


def addable_term(keyword: str) -> bool:
    """Worth writing in: a named technology with evidence, never a generic word."""
    return _t(keyword) in TECH_TERMS


NUM = re.compile(r"\d+(?:[.,]\d+)*")
try:
    DICTIONARY = {w.strip().lower() for w in open("/usr/share/dict/words", encoding="utf-8", errors="ignore")}
except OSError:
    DICTIONARY = set()      # no dictionary: every new non-evidence word is rejected, which is the safe side


def english(t: str) -> bool:
    """In the macOS word list, allowing for the inflections it omits ("checks", "reconciled")."""
    stems = {t, t[:-1] if t.endswith("s") else t, t[:-2] if t.endswith("es") else t,
             t[:-3] if t.endswith("ies") else t, (t[:-3] + "y") if t.endswith("ies") else t,
             t[:-2] if t.endswith("ed") else t, t[:-1] if t.endswith("ed") else t,
             t[:-3] if t.endswith("ing") else t, (t[:-3] + "e") if t.endswith("ing") else t,
             t[:-2] if t.endswith("ly") else t}
    return any(s in DICTIONARY for s in stems if len(s) >= 2)


def plain(s: str) -> str:
    return _t(re.sub(r"\\[a-zA-Z]+|[{}\\]", " ", s.replace("~", " ")))


def held_off(keyword: str, trace: str) -> bool:
    """True when the resume's own trace records a deliberate decision to leave this term out.
    C3.ai, 2026-09-16: the trace said Java was barred from the skills line because no bullet
    demonstrates it and its only evidence (EV-036) sits in a repo with hardcoded credentials.
    This agent added Java anyway; the decision was reverted and this check added."""
    k = re.escape(keyword.lower())
    return any(re.search(rf"(?<![a-z]){k}(?![a-z])", l.lower()) and
               re.search(r"held off|holds? off|bars?\b|barred|off the page|not on the page|left out|excluded|gap|miss", l.lower())
               for l in trace.splitlines())


def check_edit(e: dict, lines: list[str], editable: set[int], addable: set[str],
               trace: str = "") -> str:
    """Empty string when the edit is acceptable, otherwise the reason it is not."""
    n = e.get("line")
    if not isinstance(n, int) or n not in editable:
        return f"line {n} is not an editable bullet or skills line"
    old, new = lines[n - 1].rstrip("\n"), str(e.get("new") or "").rstrip("\n")
    if not new.strip() or new.strip() == old.strip():
        return "no change"
    if old.lstrip().startswith(r"\item") and not new.lstrip().startswith(r"\item"):
        return "dropped the \\item"
    if sorted(NUM.findall(new)) != sorted(NUM.findall(old)):
        return f"numbers changed: {NUM.findall(old)} -> {NUM.findall(new)}"
    if new.count("{") != new.count("}"):
        return "unbalanced braces"
    if re.search("[—–]", new) or "---" in new or " -- " in new:
        return "em or en dash"
    if len(new) > len(old) + 80:
        return f"grew {len(new) - len(old)} characters"
    kws_declared = [k for k in (e.get("keywords") or []) if isinstance(k, str)]
    for k in kws_declared:
        if held_off(k, trace):
            return f"the resume's trace records '{k}' as deliberately left out"
    if re.match(r"\s*skills\s*=", old):
        # the skill's rule: a skills line lists only what a bullet on the page demonstrates
        bullets = " ".join(plain(l) for l in lines if re.match(r"\s*\\item(\s|\[)", l))
        shown_nowhere = [k for k in kws_declared if not re.search(rf"(?<![a-z0-9]){re.escape(_t(k))}(?![a-z0-9])", bullets)]
        if shown_nowhere:
            return f"skills line may only list what a bullet shows; no bullet shows {shown_nowhere}"
    added_claims = {m.group(0).lower() for m in CLAIM_WORDS.finditer(new)} - {m.group(0).lower() for m in CLAIM_WORDS.finditer(old)}
    if added_claims:
        return f"adds a scale or ownership claim: {sorted(added_claims)}"
    kws = [k for k in (e.get("keywords") or []) if isinstance(k, str)]
    bad = [k for k in kws if k.lower() not in addable]
    if bad:
        return f"keywords not addable: {bad}"
    # LaTeX spells "Power BI" as "Power~BI" and may bold it; compare the plain text
    plain_new = _t(re.sub(r"\\[a-zA-Z]+|[{}\\]", " ", new.replace("~", " ")))
    missing = [k for k in kws if _t(k) not in plain_new]
    if missing:
        return f"declared keywords not in the line: {missing}"
    # Any word the edit introduces must be ordinary English or backed by evidence.
    # A capitalised word ("Terraform") or a non-dictionary word ("kubectl") that
    # is neither on the old line nor supported is a claim, and claims need evidence.
    def words(s: str) -> list[str]:
        return re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]*[A-Za-z0-9+#]|[A-Za-z]", re.sub(r"\\[a-zA-Z]+|[{}~\\]", " ", s))
    old_words = {w.lower() for w in words(old)}
    new_words = words(new)
    for idx, tok in enumerate(new_words):
        t = tok.lower()
        if t in old_words or t in addable or len(t) < 3 or supported(t):
            continue
        if (tok[0].isupper() and idx > 0) or tok[1:] != tok[1:].lower() or not english(t):
            return f"introduced '{tok}', which neither the line nor the evidence bank supports"
    return ""


def editable_lines(lines: list[str]) -> set[int]:
    """Bullet lines only (\\item followed by text, never \\itemsep). The skills line belongs to
    scripts/skills_basis.py since 2026-09-16, which adds every posting technology he has used."""
    out = set()
    for i, l in enumerate(lines, 1):
        if re.match(r"\\item(\s|\[)", l.strip()):
            out.add(i)
    return out


def run(app_id: int, tex: Path, apply: bool, max_edits: int) -> dict:
    r = row(app_id)
    jd = posting_text(r)
    if len(jd) < 400:
        raise SystemExit(f"#{app_id}: no readable posting text")
    pdf = tex.parent / "main.pdf"
    if not pdf.exists() and not compile_tex(tex):
        raise SystemExit(f"{tex}: does not compile")
    before = ats(pdf, jd, r["company"])
    # ats_check reports {"term", "weight"}; heaviest first so the model sees what matters
    gaps = [g["term"] if isinstance(g, dict) else str(g)
            for g in sorted(before.get("missing") or [], key=lambda g: -(g.get("weight", 0) if isinstance(g, dict) else 0))]
    addable = sorted({g for g in gaps if addable_term(g)})
    unsupported = [g for g in gaps if g not in addable]
    report = {"app_id": app_id, "tex": str(tex), "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "coverage_before": before.get("coverage_percent"), "missing": gaps, "addable": addable,
              "real_gaps": unsupported, "proposed": [], "accepted": [], "rejected": [], "applied": [],
              "gates": None, "coverage_after": None, "model": None}
    if not addable:
        report["note"] = "no missing keyword is supported by the evidence bank; nothing to add honestly"
        return report

    lines = tex.read_text().splitlines(keepends=True)
    editable = editable_lines(lines)
    numbered = "\n".join(f"{i}: {lines[i - 1].rstrip()}" for i in sorted(editable))
    verdict = verdict_path(r)
    context = json.loads(verdict.read_text()).get("one_line", "") if verdict.exists() else ""
    prompt = (f"POSTING: {r['company']} / {r['role']}\n{jd[:9000]}\n\n"
              f"ADDABLE (missing from the resume, supported by his evidence): {', '.join(addable)}\n"
              f"NOT ADDABLE (real gaps, never write these in): {', '.join(unsupported) or 'none'}\n"
              f"{('Verdict: ' + context) if context else ''}\n\n"
              f"EDITABLE LINES OF main.tex (line number: content). At most {max_edits} edits.\n{numbered}")
    try:
        res = chat("writer", SYSTEM, prompt, want_json=True, max_tokens=12000, purpose=f"keywords #{app_id}")
    except NimError as e:
        report["error"] = str(e)
        return report
    report["model"] = res["model"]
    if res.get("truncated") or not isinstance(res["json"], dict) or "edits" not in res["json"]:
        report["error"] = ("the model ran out of tokens before answering" if res.get("truncated")
                           else "the model's reply had no edits list") + "; nothing was changed"
        return report
    edits = (res["json"] or {}).get("edits") if isinstance(res["json"], dict) else []
    addable_l = {a.lower() for a in addable}
    trace_file = ROOT / "data" / "artifacts" / slug(r["company"], r["role"]) / "trace.md"
    trace = trace_file.read_text() if trace_file.exists() else ""
    if not trace:                                   # the resume build may have used its own slug
        tok = re.sub(r"[^a-z0-9]", "", r["company"].lower())[:5]
        cands = [p for p in (ROOT / "data" / "artifacts").glob("*/trace.md") if tok and tok in re.sub(r"[^a-z0-9]", "", p.parent.name)]
        trace = max(cands, key=lambda p: p.stat().st_mtime).read_text() if cands else ""
    for e in (edits or [])[:max_edits]:
        why = check_edit(e, lines, editable, addable_l, trace)
        report["proposed"].append(e)
        (report["rejected"] if why else report["accepted"]).append({**e, **({"why": why} if why else {})})

    if not apply or not report["accepted"]:
        return report

    backup = tex.with_name("main.pre-keywords.tex")
    if not backup.exists():
        shutil.copy2(tex, backup)
    original = backup.read_text().splitlines(keepends=True)

    def attempt(chosen: list[dict]) -> dict[str, bool] | None:
        cur = list(original)
        for e in chosen:
            nl = "\n" if cur[e["line"] - 1].endswith("\n") else ""
            cur[e["line"] - 1] = e["new"].rstrip("\n") + nl
        tex.write_text("".join(cur))
        return gates(tex, pdf) if compile_tex(tex) else None

    g = attempt(report["accepted"])
    if g and all(g.values()):
        report["applied"] = report["accepted"]
    else:
        kept = []
        for e in report["accepted"]:                     # one at a time, keep only what stays green
            g = attempt(kept + [e])
            if g and all(g.values()):
                kept.append(e)
            else:
                report["rejected"].append({**e, "why": "a PDF gate failed: " + (
                    ", ".join(k for k, ok in (g or {}).items() if not ok) or "did not compile")})
        report["applied"] = kept
        g = attempt(kept)
    report["gates"] = g
    report["coverage_after"] = ats(pdf, jd, r["company"]).get("coverage_percent")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", type=int, required=True)
    ap.add_argument("--tex", type=Path, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-edits", type=int, default=6)
    a = ap.parse_args()
    rep = run(a.app, a.tex.resolve(), a.apply, a.max_edits)
    r = row(a.app)
    out = ROOT / "data" / "artifacts" / slug(r["company"], r["role"]) / f"keywords-{a.app}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1) + "\n")
    print(f"coverage {rep['coverage_before']}% -> {rep['coverage_after']}%   model {rep['model']}")
    print(f"missing {len(rep['missing'])}, addable {len(rep['addable'])}: {', '.join(rep['addable'])}")
    print(f"real gaps (not written in): {', '.join(rep['real_gaps'][:15])}")
    print(f"proposed {len(rep['proposed'])}, passed checks {len(rep['accepted'])}, applied {len(rep['applied'])}")
    for x in rep["rejected"]:
        print(f"  rejected line {x.get('line')}: {x['why']}")
    for x in rep["applied"]:
        print(f"  applied  line {x['line']}: +{', '.join(x.get('keywords') or [])}")
    if rep.get("gates"):
        print("gates:", "  ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in rep["gates"].items()))
    if rep.get("error"):
        print("error:", rep["error"])
    print(f"report: {out.relative_to(ROOT)}")
    return 0 if not rep.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
