#!/usr/bin/env python3
"""NVIDIA agent: the fit analysis, Kimi K3 first and Nemotron Ultra when Kimi fails.

Srikar asked on 2026-09-16 for fit analysis to run on Kimi K3 instead of Claude. Kimi
then failed the automated checks on its first two analyses (C3.ai, Greenboard), and his
answer was "first try with Kimi if it fails then fallback to ultra". So each analysis
is attempted in this order, stopping at the first one that passes every check:
  moonshotai/kimi-k3                      NVIDIA
  nvidia/nemotron-3-ultra-550b-a55b       NVIDIA (the only model that passed the verdict bake-off)
  ollama/nemotron-3-ultra                 Ollama Cloud, only when NVIDIA's Ultra errors
When nothing passes, the attempt with the fewest failed checks is kept, and the header
of the file says so. DeepSeek V4 Pro was also asked for; NVIDIA returns 410 Gone.

The skill stays the single source of what a fit analysis is: this sends the skill's
analysis rules, the resume as a recruiter sees it (pdftotext of the PDF), the posting
with its application form stripped, the ats_check numbers, his candidate facts and the
live pipeline counts, and asks for the skill's output structure.

Checked, not trusted:
  every section the skill requires is present, the Ten-Second Read included
  paper fit and realistic are both stated, and realistic does not exceed paper
  the weighted sub-scores reproduce the paper fit within 2 points
  interview probabilities never rise from one stage to the next (they compound)
  exactly one of the four recommendations, and not APPLY WITH RESUME TAILORING
    when the resume was built for this posting
  every quoted line under Strengths Alignment is on the resume or in the posting
    (nothing invented), and every strength quotes the resume at least once
Dashes are replaced rather than failed; they are punctuation, not a reasoning error.

Srikar also asked to "look at each fit analysis for each job I apply": the desk shows
every analysis beside its application, from fit_analysis.md and fit_analysis.json.

    agent_fit.py --app 291                          resume from the pipeline
    agent_fit.py --app 291,324 --resume path.pdf    a specific PDF (one app only)
    agent_fit.py --applied                          active applications with no analysis yet
    agent_fit.py --ready                            today's READY postings with no analysis yet
    agent_fit.py --applied --force                  redo them even when one exists
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from agent_verdict import posting_text, row, slug     # noqa: E402
from nim import NimError, chat                          # noqa: E402
from nim_profile import card                            # noqa: E402

DB = ROOT / "data" / "pipeline.db"
SKILL = (ROOT / "skills" / "fit-analysis" / "SKILL.md").read_text()
SECTIONS = ["Overall Fit Score", "The Ten-Second Read", "ATS Score", "Strengths Alignment", "Critical Gaps",
            "Competitive Position", "Interview Probability", "Biggest Resume Improvements", "Top 5 Missing Keywords",
            "Resume Bullet Suggestions", "Final Recommendation", "Brutal Reality Check"]
VERDICTS = ["APPLY IMMEDIATELY", "APPLY WITH RESUME TAILORING", "UPSKILL FIRST", "LOOK ELSEWHERE"]
FORM_MARKERS = ["Apply for this job", "indicates a required field", "Accepted file types",
                "Equal Employment Opportunity", "Privacy Policy"]
KIMI = "moonshotai/kimi-k3"
ULTRA = ["nvidia/nemotron-3-ultra-550b-a55b", "ollama/nemotron-3-ultra"]

# The checks, stated up front: Kimi broke the stage and arithmetic rules on its first two runs
CHECKLIST = """
BEFORE YOU ANSWER, verify these; the analysis is rejected automatically if any fails:
1. Interview Probability rows are CUMULATIVE from the start of the process, so each number is
   less than or equal to the one above it (e.g. 40, 22, 12, 6, 2), never per-stage conditionals.
2. State "ATS Match: N/100", "Technical Match: N/100", "Experience Match: N/100" and
   "Hiring Competitiveness: N/100", and 0.3*ATS + 0.3*Technical + 0.2*Experience + 0.2*Competitiveness
   must equal the stated Paper fit within 2 points. Do the multiplication before writing Paper fit.
3. Under Strengths Alignment, every quotation in double quotes is copied character for character
   from the resume text or the posting text. No paraphrase inside quotes, no ellipses joining lines.
   Each strength quotes at least one resume line.
4. The Final Recommendation section names exactly one of the four recommendations.
5. No em dashes or en dashes anywhere."""


def skill_rules() -> str:
    """The analysis stance, criteria, output structure and rules; not the bootstrap commands."""
    start = SKILL.find("## The analysis")
    return SKILL[start:] if start > 0 else SKILL


def clean_posting(text: str) -> str:
    cut = [i for i in (text.find(m) for m in FORM_MARKERS) if i > 400]
    return text[:min(cut)] if cut else text


def run_py(*args: str) -> str:
    return subprocess.run([sys.executable, str(HERE / args[0]), *args[1:]], capture_output=True, text=True, cwd=ROOT).stdout


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w%+#/ ]", " ", s.lower().replace("ﬁ", "fi").replace("ﬂ", "fl"))).strip()


def undash(md: str) -> str:
    md = re.sub(r"(\d)\s*[–—]\s*(\d)", r"\1 to \2", md)
    md = re.sub(r"\s*—\s*", ", ", md)
    return re.sub(r"\s*–\s*", ", ", md)


def quoted_in(q: str, text: str) -> bool:
    """A quote counts as present when every fragment between ellipses is in the text."""
    parts = [norm(p) for p in re.split(r"\.\.\.|…|\[\.\.\.\]", q)]
    parts = [p for p in parts if len(p) >= 12]
    return bool(parts) and all(p[:70] in text for p in parts)


def subscore(md: str, name: str) -> int | None:
    """The 0 to 100 score on a line naming the criterion, never its weight: Ultra wrote
    "ATS Match (30%): 55/100" on 2026-09-16 and the first number read as the score."""
    for line in re.findall(rf"^.*{name}.*$", md, re.M | re.I):
        tail = line[line.lower().find(name.lower()) + len(name):]
        m = re.search(r"(\d{1,3})\s*/\s*100", tail)
        if m:
            return int(m.group(1))
        tail = re.sub(r"\(\s*(?:weight\s*)?\d{1,2}\s*%\s*\)|\|\s*\d{1,2}\s*%\s*(?=\|)|[x×*]\s*0?\.\d+|=\s*\d+(?:\.\d+)?", " ", tail, flags=re.I)
        m = re.search(r"(?<![\d.])(\d{1,3})(?![\d.])", tail)
        if m and int(m.group(1)) <= 100:
            return int(m.group(1))
    return None


def recommendation(section: str) -> list[str]:
    """The recommendation the section leads with. The explanation may name the others
    ("TAILORING is not available"), which is not a second recommendation (Capco, 2026-09-16)."""
    up = section.upper()
    bold = list(dict.fromkeys(v for v in VERDICTS for b in re.findall(r"\*\*(.+?)\*\*", up) if v in b))
    if len(bold) == 1:
        return bold
    for line in (l for l in up.splitlines() if l.strip()):
        hits = [v for v in VERDICTS if v in line]
        if hits:
            return hits
    return []


def check(md: str, resume_text: str, built_for_posting: bool, posting: str = "") -> tuple[list[str], dict]:
    problems, facts = [], {}
    for s in SECTIONS:
        if not re.search(rf"^#+\s*{re.escape(s)}", md, re.M | re.I):
            problems.append(f"missing section: {s}")
    paper = re.search(r"paper\s+fit\s*:?\s*\**\s*(\d{1,3})\s*%", md, re.I)
    real = re.search(r"realistic\s*:?\s*\**\s*(\d{1,3})\s*%", md, re.I)
    facts["paper"] = int(paper.group(1)) if paper else None
    facts["realistic"] = int(real.group(1)) if real else None
    if facts["paper"] is None or facts["realistic"] is None:
        problems.append("paper fit and realistic scores are not both stated")
    elif facts["realistic"] > facts["paper"] and not re.search(r"referral in hand", md, re.I):
        problems.append(f"realistic {facts['realistic']}% exceeds paper {facts['paper']}% with no referral")
    subs = []
    for name, w in (("ATS Match", .3), ("Technical Match", .3), ("Experience Match", .2), ("Hiring Competitiveness", .2)):
        subs.append((w, v) if (v := subscore(md, name)) is not None else None)
    if all(subs) and facts["paper"] is not None:
        weighted = sum(w * v for w, v in subs)
        facts["weighted"] = round(weighted, 1)
        facts["subscores"] = [v for _, v in subs]
        if abs(weighted - facts["paper"]) > 2:
            problems.append(f"weighted sub-scores give {weighted:.1f}, not the stated paper fit {facts['paper']}")
    probs = re.search(r"#+\s*Interview Probability(.*?)(?=\n#+\s)", md, re.S | re.I)
    if probs:
        # the stage table, not the prose under it: "The largest drop is the first one: 35%" read as a stage (C3.ai)
        block = re.search(r"```[^\n]*\n(.*?)```", probs.group(1), re.S)
        stages = re.findall(r"^\s*([A-Za-z][A-Za-z /-]{2,40}?):\s*(\d{1,3}(?:\.\d+)?)\s*%",
                            block.group(1) if block else probs.group(1), re.M)
        facts["stages"] = [[n.strip(), float(v)] for n, v in stages]
        vals = [float(v) for _, v in stages]
        if any(b > a for a, b in zip(vals, vals[1:])):
            problems.append(f"interview probabilities rise between stages: {vals}")
    rec = re.search(r"#+\s*Final Recommendation(.*?)(?=\n#+\s|\Z)", md, re.S | re.I)
    found = recommendation(rec.group(1)) if rec else []
    if len(found) != 1:
        problems.append(f"final recommendation must be exactly one of the four, found {found or 'none'}")
    facts["recommendation"] = found[0] if len(found) == 1 else None
    if built_for_posting and facts["recommendation"] == "APPLY WITH RESUME TAILORING":
        problems.append("APPLY WITH RESUME TAILORING on a resume already built for this posting (the skill forbids it)")
    strengths = re.search(r"#+\s*Strengths Alignment(.*?)(?=\n#+\s)", md, re.S | re.I)
    rt, pt = norm(resume_text), norm(posting)
    if strengths:
        # pair every quote first, then drop short ones, or a short quote shifts the pairing
        quotes = [q for q in re.findall(r"[\"“]([^\"”\n]*)[\"”]", strengths.group(1)) if len(q) >= 20]
        facts["quotes"] = len(quotes)
        invented = [q for q in quotes if not quoted_in(q, rt) and not quoted_in(q, pt)]
        if invented:
            problems.append(f"{len(invented)} of {len(quotes)} quoted strength lines are on neither the resume nor the "
                            f"posting, e.g. \"{invented[0][:80]}\"")
        items = [b for b in re.split(r"\n\s*(?:[-*]|\d+\.)\s+", "\n" + strengths.group(1)) if b.strip()]
        bare = [b for b in items if not any(quoted_in(q, rt) for q in re.findall(r"[\"“]([^\"”\n]*)[\"”]", b))]
        if items and len(bare) > len(items) // 3:
            problems.append(f"{len(bare)} of {len(items)} strengths quote no resume line, e.g. \"{bare[0].strip()[:70]}\"")
    if re.search("[—–]", md):
        problems.append("contains em or en dashes")
    return problems, facts


def resume_for(app_id: int) -> Path | None:
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT path FROM artifacts WHERE application_id=? AND kind='resume' ORDER BY id DESC", (app_id,)).fetchall()
    con.close()
    for (p,) in rows:
        path = Path(p) if Path(p).is_absolute() else ROOT / p
        if path.suffix.lower() == ".pdf" and path.exists():
            return path
    return None


def attempt(model: str, system: str, prompt: str, app_id: int) -> dict:
    try:
        res = chat("fit", system, prompt, max_tokens=16000, temperature=0.3, purpose=f"fit analysis #{app_id}", model=model)
    except NimError as e:
        return {"model": model, "error": str(e)[:200]}
    if res.get("truncated"):
        return {"model": model, "error": "ran out of tokens before finishing"}
    if len(res["text"].strip()) < 800:
        return {"model": model, "error": f"answer too short ({len(res['text'].strip())} chars)"}
    return {"model": model, "md": undash(res["text"].strip()), "ms": res["ms"]}


def run(app_id: int, resume: Path | None) -> int:
    r = row(app_id)
    resume = resume or resume_for(app_id)
    if not resume or not resume.exists():
        print(f"#{app_id} {r['company']}: no resume PDF to analyze")
        return 1
    resume_text = subprocess.run(["pdftotext", "-layout", str(resume), "-"], capture_output=True, text=True).stdout
    jd = clean_posting(posting_text(r))
    if len(jd) < 400:
        print(f"#{app_id} {r['company']}: posting text unreadable, no analysis")
        return 1
    ats = subprocess.run([sys.executable, str(HERE / "ats_check.py"), "--resume", str(resume), "--jd-text", jd,
                          "--company", r["company"], "--json"], capture_output=True, text=True).stdout
    facts_card = "\n".join(l for l in card().splitlines() if not l.startswith("- EV-"))
    stats, due = run_py("pipeline.py", "stats"), run_py("pipeline.py", "due")
    built_for = slug(r["company"], r["role"]).split("-")[0] in resume.name.lower().replace("_", "-") or \
        r["company"].lower().replace(" ", "").replace(".", "")[:5] in resume.name.lower()

    system = ("You are the fit-analysis agent for one candidate. Follow these instructions exactly, including the "
              "output structure and every rule. Write in Markdown with each output section as a '### ' heading using "
              "the exact section names. No em dashes or en dashes anywhere.\n\n" + skill_rules() + "\n" + CHECKLIST)
    prompt = (f"POSTING: {r['company']} / {r['role']} ({r.get('location') or 'location unstated'})\n{jd[:12000]}\n\n"
              f"RESUME AS THE RECRUITER SEES IT ({resume.name}; the ONLY source of truth for scoring):\n{resume_text[:9000]}\n\n"
              f"ATS_CHECK OUTPUT (application form already stripped from the posting):\n{ats[:3000]}\n\n"
              f"CANDIDATE FACTS (for the ledger and multipliers, never as credit in scoring):\n{facts_card}\n\n"
              f"LIVE PIPELINE (for the Brutal Reality Check):\n{stats[:2500]}\n{due[:1500]}\n\n"
              f"This resume {'WAS' if built_for else 'was NOT'} built for this posting.")

    tried, best = [], None
    for model in [KIMI] + ULTRA:
        if model == ULTRA[1] and tried and tried[-1]["model"] == ULTRA[0] and "md" in tried[-1]:
            break                                   # Ultra answered and failed checks; the same model on Ollama adds nothing
        a = attempt(model, system, prompt, app_id)
        if "md" in a:
            a["problems"], a["facts"] = check(a["md"], resume_text, built_for, jd)
            if best is None or len(a["problems"]) < len(best["problems"]):
                best = a
        tried.append(a)
        short = model.split("/")[-1]
        print(f"  #{app_id} {short}: " + (f"error, {a['error']}" if "error" in a else
                                          f"{len(a['problems'])} failed check(s), {a['ms'] // 1000}s"), flush=True)
        if "md" in a and not a["problems"]:
            break
    if best is None:
        print(f"#{app_id} {r['company']}: FAILED, no model produced an analysis")
        return 1

    problems, facts, md = best["problems"], best["facts"], best["md"]
    history = []
    for a in tried:
        short = a["model"].split("/")[-1]
        history.append(f"{short} errored ({a['error']})" if "error" in a else
                       f"{short} {'passed' if not a['problems'] else 'failed: ' + '; '.join(a['problems'])}")
    header = [f"<!-- fit analysis by {best['model']} via scripts/agent_fit.py; resume {resume} -->",
              f"> **Written by:** {best['model'].split('/')[-1]}  ",
              "> **Automated checks:** " + ("all passed." if not problems else "; ".join(problems)) + "  ",
              "> **Attempts:** " + " | ".join(history), ""]
    out = ROOT / "data" / "artifacts" / slug(r["company"], r["role"]) / "fit_analysis.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(header) + md + "\n")
    (out.parent / "fit_analysis.json").write_text(json.dumps({
        "app_id": app_id, "company": r["company"], "role": r["role"], "model": best["model"],
        "passed": not problems, "problems": problems, "attempts": history, "resume": str(resume),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **facts}, indent=1) + "\n")
    tries_dir = out.parent / "fit_attempts"                # every model's answer, for auditing the checks
    tries_dir.mkdir(exist_ok=True)
    for a in tried:
        if "md" in a:
            (tries_dir / f"{app_id}-{a['model'].replace('/', '_')}.md").write_text(
                "> checks: " + ("all passed" if not a["problems"] else "; ".join(a["problems"])) + "\n\n" + a["md"] + "\n")
    rel = str(out.relative_to(ROOT))
    con = sqlite3.connect(DB)                        # one row per analysis file, not one per rerun
    con.execute("DELETE FROM artifacts WHERE application_id=? AND kind='fit_analysis' AND path=?", (app_id, rel))
    con.commit()
    con.close()
    args = ["pipeline.py", "artifact", str(app_id), "--kind", "fit_analysis", "--path", rel]
    if facts.get("paper") is not None:
        args += ["--score", str(facts["paper"])]
    run_py(*args)
    print(f"#{app_id} {r['company']}: paper {facts.get('paper')}%, realistic {facts.get('realistic')}%, "
          f"{facts.get('recommendation')}  [{best['model'].split('/')[-1]}]")
    print("  checks: " + ("all passed" if not problems else "; ".join(problems)))
    print(f"  written: {rel}")
    return 0


def has_good_analysis(app_id: int) -> bool:
    """An analysis a person or Claude wrote, or an agent one that passed its checks."""
    con = sqlite3.connect(DB)
    paths = [p for (p,) in con.execute("SELECT path FROM artifacts WHERE application_id=? AND kind='fit_analysis'", (app_id,))]
    con.close()
    for p in paths:
        f = Path(p) if Path(p).is_absolute() else ROOT / p
        if f.suffix == ".md" and f.exists():
            head = f.read_text()[:1500]
            if "Automated checks:" not in head or "Automated checks:** all passed" in head:
                return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--resume", type=Path)
    ap.add_argument("--applied", action="store_true")
    ap.add_argument("--ready", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    ids: list[int] = [int(i) for i in a.app.split(",")] if a.app else []
    con = sqlite3.connect(DB)
    if a.applied:
        ids += [i for (i,) in con.execute("SELECT id FROM applications WHERE status IN ('applied','screening','interview') "
                                          "ORDER BY applied_at DESC")]
    con.close()
    if a.ready:
        state = ROOT / "data" / "logs" / f"batch-{date.today()}.json"
        if state.exists():
            ids += [int(k) for k, x in json.loads(state.read_text()).items() if x.get("state") == "READY"][::-1]
    if not ids:
        ap.error("give --app, --applied or --ready")
    ids = list(dict.fromkeys(ids))
    if not a.app and not a.force:
        ids = [i for i in ids if not has_good_analysis(i)]
    if a.resume and len(ids) != 1:
        ap.error("--resume goes with exactly one app")
    print(f"fit analysis for {len(ids)} application(s)")
    failed = 0
    for i in ids:
        try:
            failed += run(i, a.resume) != 0
        except Exception as e:                       # one bad posting does not stop the batch
            print(f"#{i}: FAILED {type(e).__name__}: {e}"[:240])
            failed += 1
    return 1 if failed and len(ids) == 1 else 0


if __name__ == "__main__":
    sys.exit(main())
