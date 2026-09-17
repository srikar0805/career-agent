#!/usr/bin/env python3
"""NVIDIA agent: one cover letter per prepared application, under 200 words, checked against the resume.

Srikar asked for cover letters for the prepared resumes on 2026-09-17, right after asking to keep
Opus out of the bulk work. So the letter is drafted by the NVIDIA writer role against
skills/coverletter/SKILL.md, and everything checkable is checked here rather than by a reader:

  the hook rests on a sentence that is actually in the posting, quoted back for him to verify
  every number in the letter appears on his resume or in the posting
  every technology named as his appears on his resume (their stack may be named as theirs)
  no banned opener (I am writing, excited, passionate, came across), no thanking, no groveling
  120 to 200 words, 3 or 4 paragraphs, no em dashes, no EV ids

Output per application:
  data/artifacts/<slug>/cover-letter-<id>.md     the text
  data/artifacts/<slug>/cover-letter-<id>.pdf    same letterhead as the resume, built with tectonic
and the PDF is logged as the cover_letter artifact, so prefill marks the form field FILLED and
autofill.py uploads it. Nothing is ever submitted.

    agent_cover.py --app 243
    agent_cover.py --ready --limit 20        prepared postings with no letter yet, queue order
    agent_cover.py --app 243 --dry-run       print it, write nothing
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from agent_fit import clean_posting, resume_for      # noqa: E402
from agent_verdict import posting_text, row, slug    # noqa: E402

DB = ROOT / "data" / "pipeline.db"
SKILL = (ROOT / "skills" / "coverletter" / "SKILL.md").read_text()
BANNED = re.compile(r"\bI am writing\b|\bI'm writing\b|\bexcit|\bthrill|\bpassionat|came across|\bas a recent graduate\b|"
                    r"thank you for|look forward to hearing|\bdream (job|role|company)\b|perfect fit|honou?red|"
                    r"I would love the opportunity|humbly|production[- ]grade|enterprise[- ]scale|"
                    r"world[- ]class|cutting[- ]edge|synerg", re.I)
GREETING = "Dear Hiring Team,"


def undash(s: str) -> str:
    """Dashes are punctuation, not a reasoning error: fix them instead of failing the draft."""
    return re.sub(r"\s*[—–]\s*", ", ", s)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w%+#./ -]", " ", s.lower())).strip()


def rules() -> str:
    start = SKILL.find("## Step 2")
    end = SKILL.find("## Step 5")
    return SKILL[start:end] + "\n" + SKILL[SKILL.find("## Rules"):]


def tex_escape(s: str) -> str:
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")):
        s = s.replace(a, b)
    return s


def letterhead(app_id: int) -> dict:
    """Contact details come from the resume this letter travels with, never from this file."""
    con = sqlite3.connect(DB)
    p = con.execute("SELECT path FROM artifacts WHERE application_id=? AND kind='resume_tex' ORDER BY id DESC LIMIT 1",
                    (app_id,)).fetchone()
    con.close()
    tex_path = Path(p[0]) if p and Path(p[0]).is_absolute() else (ROOT / p[0]) if p else None
    if not tex_path or not tex_path.exists():
        tex_path = ROOT / "latex" / "resume" / "Srikar_Resume_DigitalOcean" / "main.tex"
    tex = tex_path.read_text()
    cls = (tex_path.parent / "resume.cls")
    cls_text = cls.read_text() if cls.exists() else ""
    get = lambda k, d="": (re.search(rf"{k}=([^,\n]+)", tex) or [None, d])[1].strip()
    links = re.findall(r"href\{(https://(?:www\.)?(?:linkedin|github)[^}]*)\}", cls_text)
    return {"name": get("name", "Sai Srikar Reddy Kolli"), "phone": get("phone"), "email": get("email"),
            "links": links[:2]}


SYSTEM = ("You write one cover letter for one posting, following these instructions exactly. "
          "The candidate is Sai Srikar Reddy Kolli, M.S. Computer and Information Sciences, University of Missouri, "
          "graduating May 2027.\n\n" + rules() + """

HARD RULES for this run, checked automatically:
- 3 or 4 paragraphs, 120 to 200 words in total. No greeting and no sign-off: they are added for you.
- The hook (first sentence) must rest on something the POSTING actually says, and you must return that
  posting sentence verbatim in "hook_source". No fact about the company from anywhere else. Write the
  hook in YOUR OWN words: never copy a phrase of ten or more words from the posting into the letter.
- Every number you use must appear in the RESUME text or the posting. Never invent or round one.
- A technology may be described as HIS only if it is on the resume. Their stack may be named as theirs
  ("your Node.js services"), never as his experience.
- Never say he is excited, passionate or thrilled, never thank them, never ask politely for consideration.
- He lives in Columbia, Missouri and is open to relocating anywhere in the US. Never write that he is
  based in, living in or already in the employer's city; "relocating to" or "will be in" is the truth.
- No em dashes or en dashes. No evidence ids. Contractions are fine.
Reply with ONE JSON object: {"paragraphs": ["...", "..."], "hook_source": "the posting sentence the hook rests on"}""")


def check(paras: list[str], hook_source: str, resume_text: str, posting: str, company: str) -> list[str]:
    from skills_basis import LEXICON
    problems = []
    body = " ".join(paras)
    words = len(re.findall(r"[A-Za-z0-9'%+-]+", body))
    if not 3 <= len(paras) <= 4:
        problems.append(f"{len(paras)} paragraphs; the letter needs 3 or 4")
    if not 120 <= words <= 200:
        problems.append(f"{words} words; the letter must be 120 to 200")
    if BANNED.search(body):
        problems.append(f"banned phrase: {BANNED.search(body).group(0)}")
    if re.search("[—–]", body):
        problems.append("contains em or en dashes")
    if re.search(r"EV-\d", body):
        problems.append("names an evidence id")
    rt, pt = norm(resume_text), norm(posting)
    # Ultra's first Greenboard draft opened with a sentence copied out of the posting (2026-09-17).
    # Quoting their words back is not a hook; the letter has to say something in his own.
    pw, bw = pt.split(), norm(body).split()
    runs = {" ".join(pw[i:i + 10]) for i in range(max(0, len(pw) - 9))}
    lifted = next((" ".join(bw[i:i + 10]) for i in range(max(0, len(bw) - 9)) if " ".join(bw[i:i + 10]) in runs), "")
    if lifted:
        problems.append(f"copies the posting word for word: \"{lifted[:70]}\"; say it in your own words")
    if norm(hook_source)[:60] not in pt:
        problems.append("hook_source is not a sentence from the posting")
    if norm(company).split()[0] not in norm(body):
        problems.append(f"the letter never names {company}")
    for n in set(re.findall(r"(?<![\w.])\d[\d,.]*\s*(?:%|x|\+)?", body)):
        n = n.strip()
        if norm(n) and norm(n) not in rt and norm(n) not in pt:
            problems.append(f"the number {n} is on neither the resume nor the posting")
    # Ultra wrote "am already NYC-based" for Greenboard (2026-09-17). He lives in Columbia, Missouri
    # and is open to relocating anywhere; claiming residence in the employer's city is a lie a
    # recruiter can check on the first call, so a place may only appear as somewhere he will move to.
    home = ""
    ident = ROOT / "profile" / "identity.yaml"
    if ident.exists():
        m = re.search(r"^location:\s*\"?([^\"#\n]+)", ident.read_text(), re.M)
        home = norm(m.group(1)) if m else ""
    for m in re.finditer(r"(?:based in|live in|living in|located in|i am in|am already|already based|"
                         r"currently in|resident of)\s+([A-Z][\w .&-]{1,30})|\b([A-Z][\w.]{1,20})-based\b", body):
        place = norm(m.group(1) or m.group(2) or "")
        if place and place not in home and not re.search(r"\bmissouri\b|\bcolumbia\b", place):
            problems.append(f"says he is based in {place}; he lives in {home or 'Columbia, Missouri'} and is open to "
                            f"relocating, so write it as relocating there, never as already living there")
    for key, (display, pattern, _) in LEXICON.items():
        for sent in re.split(r"(?<=[.!?])\s+", body):
            if re.search(pattern, sent, re.I) and not re.search(pattern, resume_text, re.I):
                if not re.search(r"\byour?\b|\byours\b|\bthe team\b", sent, re.I):
                    problems.append(f"{display} is not on his resume, and the sentence claims it as his")
                break
    return sorted(set(problems))


def build_pdf(md_path: Path, paras: list[str], r: dict, head: dict) -> Path | None:
    body = "\n\n".join(tex_escape(p) for p in paras)
    links = "".join(f" $\\vert$ \\href{{{u}}}{{{'LinkedIn' if 'linkedin' in u else 'GitHub'}}}" for u in head["links"])
    tex = f"""\\documentclass[11pt]{{article}}
\\usepackage[margin=1in]{{geometry}}
\\usepackage[T1]{{fontenc}}
\\usepackage{{lmodern}}
\\usepackage[colorlinks=true,urlcolor=black,linkcolor=black]{{hyperref}}
\\usepackage{{parskip}}
\\pagestyle{{empty}}
\\begin{{document}}
{{\\Large\\bfseries {tex_escape(head['name'])}}}\\\\[2pt]
{{\\small {tex_escape(head['phone'])} $\\vert$ \\href{{mailto:{head['email']}}}{{{tex_escape(head['email'])}}}{links}}}

\\vspace{{1.2em}}
{date.today():%B %d, %Y}

\\vspace{{0.8em}}
Hiring Team\\\\
{tex_escape(r['company'])}

\\vspace{{0.8em}}
{GREETING}

{body}

\\vspace{{0.6em}}
Sincerely,\\\\
{tex_escape(head['name'])}
\\end{{document}}
"""
    tex_path = md_path.with_suffix(".tex")
    tex_path.write_text(tex)
    out = subprocess.run(["tectonic", "--keep-logs", "--chatter", "minimal", tex_path.name],
                         cwd=tex_path.parent, capture_output=True, text=True, timeout=300)
    pdf = tex_path.with_suffix(".pdf")
    if out.returncode != 0 or not pdf.exists():
        print("  pdf failed:", (out.stderr or out.stdout)[-300:])
        return None
    pages = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    if "Pages:          1" not in pages.replace("Pages:", "Pages:         ")[:400] and "Pages:" in pages:
        n = re.search(r"Pages:\s+(\d+)", pages)
        if n and int(n.group(1)) != 1:
            print(f"  pdf is {n.group(1)} pages, not 1")
            return None
    return pdf


def run(app_id: int, dry: bool = False) -> int:
    from nim import NimError, chat
    r = row(app_id)
    resume = resume_for(app_id)
    if not resume:
        print(f"#{app_id} {r['company']}: no resume, no letter")
        return 1
    resume_text = subprocess.run(["pdftotext", "-layout", str(resume), "-"], capture_output=True, text=True).stdout
    posting = clean_posting(posting_text(r))
    if len(posting) < 400:
        print(f"#{app_id} {r['company']}: posting unreadable, no letter")
        return 1
    prompt = (f"POSTING: {r['company']} / {r['role']} ({r.get('location') or 'location unstated'})\n{posting[:9000]}\n\n"
              f"HIS RESUME FOR THIS POSTING (the only source of facts about him):\n{resume_text[:7000]}")
    feedback, best = "", None
    for attempt in range(1, 6):
        try:
            res = chat("writer", SYSTEM, prompt + feedback, want_json=True, max_tokens=4000, temperature=0.4,
                       purpose=f"cover letter #{app_id}")
        except NimError as e:
            print(f"#{app_id} {r['company']}: FAILED {e}")
            return 1
        d = res.get("json") if isinstance(res.get("json"), dict) else {}
        paras = [undash(str(p).strip()) for p in (d.get("paragraphs") or []) if str(p).strip()]
        hook = str(d.get("hook_source") or "")
        if not paras:
            feedback = "\n\nYour last answer had no paragraphs. Answer with the JSON object."
            continue
        problems = check(paras, hook, resume_text, posting, r["company"])
        if best is None or len(problems) < len(best[1]):
            best = (paras, problems, hook, res["model"])
        if not problems:
            break
        feedback = ("\n\nYOUR LAST DRAFT:\n" + "\n\n".join(paras)
                    + "\n\nIT WAS REJECTED FOR:\n- " + "\n- ".join(problems[:8])
                    + "\nKeep everything that was right and fix only these. Answer with the JSON object.")
        print(f"  #{app_id} attempt {attempt} [{res['model'].split('/')[-1]}]: {len(problems)} problem(s): {problems[0]}", flush=True)
    paras, problems, hook, model = best
    if dry:
        print("\n".join(paras), "\n\nhook source:", hook, "\nproblems:", problems)
        return 0
    if problems:
        print(f"#{app_id} {r['company']}: no clean draft after 5 tries; nothing written. {problems}")
        return 1
    d = ROOT / "data" / "artifacts" / slug(r["company"], r["role"])
    d.mkdir(parents=True, exist_ok=True)
    md = d / f"cover-letter-{app_id}.md"
    md.write_text(f"<!-- cover letter by {model} via scripts/agent_cover.py; resume {resume.name} -->\n"
                  f"> **Hook rests on this line of the posting:** {hook}\n\n"
                  f"{GREETING}\n\n" + "\n\n".join(paras) + f"\n\nSincerely,\nSai Srikar Reddy Kolli\n")
    pdf = build_pdf(md, paras, r, letterhead(app_id))
    if not pdf:
        print(f"#{app_id} {r['company']}: text written, PDF failed: {md.relative_to(ROOT)}")
        return 1
    subprocess.run([sys.executable, str(HERE / "pipeline.py"), "artifact", str(app_id), "--kind", "cover_letter",
                    "--path", str(pdf.relative_to(ROOT))], capture_output=True, text=True)
    words = len(re.findall(r"[A-Za-z0-9'%+-]+", " ".join(paras)))
    print(f"#{app_id} {r['company']}: {words} words, checks passed [{model.split('/')[-1]}]  {pdf.relative_to(ROOT)}")
    return 0


def ready_ids(limit: int | None) -> list[int]:
    con = sqlite3.connect(DB)
    open_ids = {i for (i,) in con.execute("SELECT id FROM applications WHERE status='discovered'")}
    have = {i for (i,) in con.execute("SELECT DISTINCT application_id FROM artifacts WHERE kind='cover_letter'")}
    con.close()
    state = {}
    for f in sorted(glob.glob(str(ROOT / "data" / "logs" / "batch-*.json"))):
        state.update(json.loads(Path(f).read_text()))
    ids = [int(k) for k, x in state.items() if x.get("state") == "READY" and int(k) in open_ids and int(k) not in have]
    return sorted(ids, reverse=True)[:limit or None]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--ready", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    ids = [int(i) for i in a.app.split(",")] if a.app else []
    if a.ready:
        ids += ready_ids(a.limit)
    if not ids:
        ap.error("give --app or --ready")
    print(f"cover letters for {len(ids)} application(s)")
    failed = 0
    for i in dict.fromkeys(ids):
        try:
            failed += run(i, a.dry_run) != 0
        except Exception as e:
            print(f"#{i}: FAILED {type(e).__name__}: {e}"[:200])
            failed += 1
    return 1 if failed and len(ids) == 1 else 0


if __name__ == "__main__":
    sys.exit(main())
