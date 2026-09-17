#!/usr/bin/env python3
"""One job, one agent per step, each in its own small context. Never submits.

Srikar's flow, as he described it on 2026-09-16:

    NVIDIA brings the job data  ->  Claude builds the resume  ->  NVIDIA does the fit
    analysis and adds the missing keywords  ->  Claude does the fit analysis  ->
    the application is filled in
    (changed the same day at his direction: the fit analysis runs on Kimi K3 too)

    step       agent                                   context
    verdict    agent_verdict.py (NVIDIA analyst)       posting + profile card
    form       prefill.py (no model)                   the real application form
    resume     claude --print --model opus             fresh session, one skill
    skills     skills_basis.py (no model)              every posting technology he has used
    keywords   agent_keywords.py (NVIDIA writer)       tex lines + posting + gaps
    fit        agent_fit.py (NVIDIA Kimi K3)           resume text + posting + skill rules
    packet     prefill.py (no model)                   answers for every question

WHY FRESH SESSIONS. Measured 2026-09-16: Srikar's Opus usage was one interactive
session re-reading 400K to 800K tokens of history on every turn, because every
resume and fit analysis ran inside it. Here each Claude step starts empty, reads
one skill and one row, and exits.

STOPS, on purpose, before the expensive step: a verdict with blockers, a form
BLOCKER, or a form WARNING (a cohort question whose honest answer filters him
out). --force continues past a WARNING or verdict blocker, never past a BLOCKER.

    apply_flow.py --app 243                 run every step not yet done
    apply_flow.py --app 243 --from keywords re-run from a step
    apply_flow.py --app 243 --only fit      one step
    apply_flow.py --app 243 --plan          say what would run, run nothing

State: data/artifacts/<slug>/flow-<id>.json. Claude usage per step is appended
to data/logs/flow-usage.jsonl, so the saving can be measured, not assumed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from agent_verdict import out_path as verdict_file, row, slug   # noqa: E402

CLAUDE = os.environ.get("CLAUDE_BIN", str(Path.home() / ".local" / "bin" / "claude"))
RESUMES = Path.home() / "Developer" / "Resumes"
DB = ROOT / "data" / "pipeline.db"
STEPS = ["verdict", "form", "resume", "skills", "keywords", "fit", "packet"]
PY = str(ROOT / ".venv" / "bin" / "python")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state_path(r: dict) -> Path:
    return ROOT / "data" / "artifacts" / slug(r["company"], r["role"]) / f"flow-{r['id']}.json"


def artifact(app_id: int, kind: str) -> str:
    con = sqlite3.connect(DB)
    x = con.execute("SELECT path FROM artifacts WHERE application_id=? AND kind=? ORDER BY id DESC LIMIT 1",
                    (app_id, kind)).fetchone()
    con.close()
    return x[0] if x else ""


def claude(prompt: str, model: str, tools: list[str], step: str, app_id: int, timeout: int) -> dict:
    """A fresh headless Claude session on the Max plan. Never an API key."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}   # a key bills a card, not the plan
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    cmd = [CLAUDE, "--print", "--model", model, "--output-format", "json", "--permission-mode", "acceptEdits",
           "--add-dir", str(ROOT), "--add-dir", str(RESUMES), "--allowedTools", *tools]
    t0 = time.time()
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=ROOT, env=env, timeout=timeout)
    try:
        out = json.loads(p.stdout)
    except Exception:
        out = {"result": p.stdout[-2000:], "is_error": True}
    entry = {"at": now(), "app_id": app_id, "step": step, "model": model, "exit": p.returncode,
             "seconds": round(time.time() - t0), "usage": out.get("usage"), "num_turns": out.get("num_turns"),
             "model_usage": out.get("modelUsage")}
    log = ROOT / "data" / "logs" / "flow-usage.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    out["exit"] = p.returncode
    if p.returncode != 0 and p.stderr:
        out["stderr"] = p.stderr[-1500:]
    return out


# ---------------------------------------------------------------- steps

def step_verdict(r: dict, st: dict, force: bool) -> tuple[bool, str]:
    from agent_verdict import posting_text, run as verdict_run
    try:
        v = json.loads(verdict_file(r).read_text()) if verdict_file(r).exists() else verdict_run(r["id"])
    except Exception as e:
        # NVIDIA unavailable (Greenboard #243, 2026-09-16: two timeouts on the only model that
        # passed the bake-off). The verdict is a guard before the Opus build, so fall back to the
        # deterministic screener rather than either stopping the flow or skipping the guard.
        from screen_job import screen
        text = posting_text(r)
        s = screen(text, r["company"]) if len(text) > 300 else {"verdict": "UNKNOWN", "blockers": [], "flags": []}
        st["verdict"] = {"verdict": "screen_job " + s["verdict"], "blockers": s["blockers"], "model": None,
                         "note": f"NVIDIA verdict unavailable: {str(e)[:160]}"}
        if s["verdict"] == "DROP" and not force:
            return False, "NVIDIA unavailable; the rule screener found blockers: " + "; ".join(s["blockers"])[:300]
        return True, f"NVIDIA unavailable ({str(e)[:80]}); rule screener says {s['verdict']}" + \
            (f", flags: {'; '.join(s['flags'])[:120]}" if s.get("flags") else "")
    st["verdict"] = {k: v.get(k) for k in ("verdict", "fit_score", "one_line", "blockers", "risks", "model")}
    if v.get("blockers") and not force:
        return False, "the verdict found blockers: " + "; ".join(v["blockers"])[:300] + " (--force to continue)"
    return True, f"{v.get('verdict')} {v.get('fit_score')}: {v.get('one_line')}"


def step_form(r: dict, st: dict, force: bool) -> tuple[bool, str]:
    from prefill import write_packet
    path, _, info = write_packet(r["id"])
    st["form"] = {"verdict": info["verdict"], "warnings": info["warnings"], "blockers": info["blockers"], "packet": str(path)}
    if info["blockers"]:
        return False, "form BLOCKER, not buildable: " + "; ".join(info["blockers"])[:300]
    if info["warnings"] and not force:
        return False, "form WARNING: " + "; ".join(info["warnings"])[:300] + " (--force to continue)"
    return True, f"form {info['verdict']}"


def step_resume(r: dict, st: dict, force: bool) -> tuple[bool, str]:
    started = time.time()
    prompt = f"""Build a tailored resume for pipeline row #{r['id']} ({r['company']} / {r['role']}).

Follow skills/resume-rewrite/SKILL.md in full for `--app {r['id']}`, including the review loop and every
gate on the compiled PDF. Its reviewers run as subagents; dispatch them rather than reviewing inline.
Put the LaTeX source in latex/resume/Srikar_Resume_<Company>_<Short role>/main.tex, copy the finished PDF to
{RESUMES}/final/SaiSrikarKolli_<Company>_<Role>.pdf, then record both:
  ./.venv/bin/python scripts/pipeline.py artifact {r['id']} --kind resume --path <pdf>
  ./.venv/bin/python scripts/pipeline.py artifact {r['id']} --kind resume_tex --path <main.tex>
The NVIDIA verdict for this row, for context: {json.dumps(st.get('verdict', {}))[:800]}
Do not apply, submit, message or email anything. End with one line: the PDF path and every gate result."""
    tools = ["Read", "Write", "Edit", "Glob", "Grep", "Agent", "Task",
             "Bash(./.venv/bin/python:*)", f"Bash({PY}:*)", "Bash(tectonic:*)", "Bash(pdftotext:*)",
             "Bash(cp:*)", "Bash(mkdir:*)", "Bash(ls:*)", "Bash(sqlite3:*)", "WebFetch"]
    out = claude(prompt, "opus", tools, "resume", r["id"], timeout=3600)
    tex = artifact(r["id"], "resume_tex")
    pdf = artifact(r["id"], "resume")
    if not tex:                       # the session forgot to log it: take the newest source written during it
        # filtered by company: two flows can build at once (C3.ai and Greenboard did on 2026-09-16),
        # and the newest source overall may belong to the other one
        token = re.sub(r"[^a-z0-9]", "", r["company"].lower())[:6]
        fresh = [p for p in (ROOT / "latex" / "resume").glob("*/main.tex") if p.stat().st_mtime >= started
                 and token in re.sub(r"[^a-z0-9]", "", p.parent.name.lower())]
        tex = str(max(fresh, key=lambda p: p.stat().st_mtime)) if fresh else ""
    st["resume"] = {"tex": tex, "pdf": pdf, "claude_exit": out.get("exit"), "result": str(out.get("result"))[-600:]}
    if out.get("exit") != 0 or not tex or not pdf:
        return False, f"resume step did not finish (exit {out.get('exit')}, tex {bool(tex)}, pdf {bool(pdf)})"
    return True, f"resume built: {pdf}"


def step_skills(r: dict, st: dict, force: bool) -> tuple[bool, str]:
    """Srikar, 2026-09-16: every technology the posting names goes on the Skills line if he
    has used it, bullet or no bullet. Technologies with no record are listed, not written."""
    from skills_basis import apply as skills_apply
    tex = Path((st.get("resume") or {}).get("tex") or artifact(r["id"], "resume_tex") or "/nonexistent")
    pdf = (st.get("resume") or {}).get("pdf") or artifact(r["id"], "resume")
    if not tex.exists():
        return False, "no LaTeX source recorded for this row"
    rep = skills_apply(r["id"], tex, dry=False)
    st["skills"] = {"applied": rep["applied"], "dropped_for_space": rep["dropped_for_space"], "confirm": rep["confirm"]}
    if rep["applied"] and pdf:
        shutil.copy2(tex.parent / "main.pdf", pdf)
    confirm = ", ".join(c["name"] for c in rep["confirm"]) or "none"
    return True, f"added {', '.join(rep['applied']) or 'nothing'}; CONFIRM before adding (no record): {confirm}"


def step_keywords(r: dict, st: dict, force: bool) -> tuple[bool, str]:
    from agent_keywords import run as kw_run
    tex = Path((st.get("resume") or {}).get("tex") or artifact(r["id"], "resume_tex") or "/nonexistent")
    pdf = (st.get("resume") or {}).get("pdf") or artifact(r["id"], "resume")
    if not tex.exists():              # resumed with --from keywords after the resume session ended on its own
        token = re.sub(r"[^a-z0-9]", "", r["company"].lower())[:6]
        cands = [p for p in (ROOT / "latex" / "resume").glob("*/main.tex")
                 if token and token in re.sub(r"[^a-z0-9]", "", p.parent.name.lower())]
        if cands:
            tex = max(cands, key=lambda p: p.stat().st_mtime)
    if not tex.exists():
        return False, "no LaTeX source recorded for this row"
    rep = kw_run(r["id"], tex, apply=True, max_edits=6)
    st["keywords"] = {k: rep.get(k) for k in ("coverage_before", "coverage_after", "addable", "real_gaps", "model", "gates")}
    st["keywords"]["applied"] = [{"line": e["line"], "keywords": e.get("keywords")} for e in rep.get("applied", [])]
    st["keywords"]["rejected"] = [e.get("why") for e in rep.get("rejected", [])]
    if rep.get("applied") and rep.get("gates") and all(rep["gates"].values()) and pdf:
        shutil.copy2(pdf, str(pdf).replace(".pdf", ".pre-keywords.pdf"))
        shutil.copy2(tex.parent / "main.pdf", pdf)
        return True, f"{len(rep['applied'])} keyword edit(s) applied, coverage {rep['coverage_before']}% -> {rep['coverage_after']}%"
    return True, f"no keyword edit landed ({rep.get('note') or rep.get('error') or 'none passed every check'})"


def step_fit(r: dict, st: dict, force: bool) -> tuple[bool, str]:
    """Kimi K3 on NVIDIA (scripts/agent_fit.py), Srikar's choice on 2026-09-16.
    Claude Opus is the fallback only if every NVIDIA and Gemini model for the role fails. Opus, not
    Sonnet: Srikar's rule from 2026-09-16 is that Claude work uses Opus only."""
    pdf = (st.get("resume") or {}).get("pdf") or artifact(r["id"], "resume")
    if not pdf:
        return False, "no resume to analyze"
    from agent_fit import run as fit_run
    if fit_run(r["id"], Path(pdf)) == 0:
        st["fit"] = {"agent": "agent_fit.py", "path": artifact(r["id"], "fit_analysis")}
        return True, f"fit analysis written: {st['fit']['path']}"
    print("  fit: NVIDIA and Gemini failed, falling back to a Claude Opus session")
    kw = st.get("keywords") or {}
    prompt = f"""Run skills/fit-analysis/SKILL.md for pipeline row #{r['id']} with `--app {r['id']} --resume {pdf}`.
Write it to data/artifacts/{slug(r['company'], r['role'])}/fit-analysis.md and log it with
  ./.venv/bin/python scripts/pipeline.py artifact {r['id']} --kind fit_analysis --path <that file> --score <overall fit>
Context from the NVIDIA keyword pass (keywords the evidence supports were already worked in; these are the real gaps):
{json.dumps({'real_gaps': kw.get('real_gaps'), 'coverage_after': kw.get('coverage_after')})[:1200]}
Do not edit the resume. End with one line: overall fit, recommendation."""
    tools = ["Read", "Write", "Glob", "Grep", "Bash(./.venv/bin/python:*)", f"Bash({PY}:*)", "Bash(pdftotext:*)", "WebFetch"]
    out = claude(prompt, "opus", tools, "fit", r["id"], timeout=1800)
    st["fit"] = {"claude_exit": out.get("exit"), "path": artifact(r["id"], "fit_analysis"), "result": str(out.get("result"))[-600:]}
    return out.get("exit") == 0, str(out.get("result"))[-200:]


def step_packet(r: dict, st: dict, force: bool) -> tuple[bool, str]:
    from agent_answers import run as answers_run
    from prefill import write_packet
    path, _, info = write_packet(r["id"])          # rebuilt now that the resume exists
    if info["counts"].get("OPEN"):
        answers_run(r["id"], dry=False)            # NVIDIA writer appends "## Written answers"
    st["packet"] = {"path": str(path), "counts": info["counts"], "open_required": info["open_required"]}
    return True, f"packet {path.relative_to(ROOT)}: {info['counts']}"


RUNNERS = {"verdict": step_verdict, "form": step_form, "resume": step_resume, "skills": step_skills,
           "keywords": step_keywords, "fit": step_fit, "packet": step_packet}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", type=int, required=True)
    ap.add_argument("--from", dest="start", choices=STEPS)
    ap.add_argument("--only", choices=STEPS)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--plan", action="store_true")
    a = ap.parse_args()

    r = row(a.app)
    sp = state_path(r)
    st = json.loads(sp.read_text()) if sp.exists() else {"app_id": a.app, "done": []}
    steps = [a.only] if a.only else STEPS[STEPS.index(a.start):] if a.start else [s for s in STEPS if s not in st["done"]]
    print(f"#{a.app} {r['company']} / {r['role']}: {' -> '.join(steps) or 'nothing left'}")
    if a.plan:
        return 0
    for s in steps:
        t0 = time.time()
        try:
            ok, msg = RUNNERS[s](r, st, a.force)
        except Exception as e:
            ok, msg = False, f"{type(e).__name__}: {e}"
        print(f"  {s:9} {'ok  ' if ok else 'STOP'} {round(time.time() - t0):4}s  {msg}")
        if ok and s not in st["done"]:
            st["done"].append(s)
        st["updated"] = now()
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(st, indent=1) + "\n")
        if not ok:
            return 1
    print("  staged. Nothing was submitted: open the packet, review, and press submit yourself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
