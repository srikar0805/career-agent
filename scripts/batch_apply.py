#!/usr/bin/env python3
"""Prepare every open posting for submission: screen, form check, fast resume, packet. Never submits.

Srikar, 2026-09-16: "open the pipeline and start applying to every company", newest
postings first, fast builds for most and a full Opus build for the ten best. This is the
fast lane. It stops short of the submit button like everything else here: the output is
data/logs/READY-<date>.md, one line per posting with the resume, the packet and the exact
way to submit (the form filler for Greenhouse, the packet for the rest).

Per posting, cheapest check first:
  1. posting text readable            otherwise listed as MANUAL
  2. screen_job.screen                a posting sentence that rules him out: SKIPPED, with the sentence
  3. prefill form check               a form BLOCKER: SKIPPED; a cohort WARNING: YOUR CALL (not built)
  4. resume                           an existing tailored resume is kept; otherwise fast_resume.py
  5. packet                           rebuilt with the resume attached
Written answers (NVIDIA) run in a later pass, --answers, because they take minutes each.

    batch_apply.py --limit 10            the ten newest open postings
    batch_apply.py                       every open posting
    batch_apply.py --ids 318,326         specific rows
    batch_apply.py --answers             add written answers to packets already built today
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
DB = ROOT / "data" / "pipeline.db"
STATE = ROOT / "data" / "logs" / f"batch-{date.today()}.json"
READY = ROOT / "data" / "logs" / f"READY-{date.today()}.md"


def ats_of(url: str) -> str:
    for name, pat in (("greenhouse", r"greenhouse|gh_jid"), ("ashby", r"ashbyhq"), ("lever", r"lever\.co"),
                      ("workday", r"myworkdayjobs"), ("icims", r"icims"), ("smartrecruiters", r"smartrecruiters"),
                      ("successfactors", r"successfactors"), ("oracle", r"oraclecloud")):
        if re.search(pat, url or ""):
            return name
    return "other"


def artifact(app_id: int, kind: str) -> str:
    con = sqlite3.connect(DB)
    x = con.execute("SELECT path FROM artifacts WHERE application_id=? AND kind=? ORDER BY id DESC LIMIT 1", (app_id, kind)).fetchone()
    con.close()
    return x[0] if x else ""


def prepare(app_id: int) -> dict:
    from agent_verdict import posting_text, row
    from fast_resume import build
    from prefill import write_packet
    from screen_job import screen
    r = row(app_id)
    out = {"id": app_id, "company": r["company"], "role": r["role"], "url": r.get("url"), "ats": ats_of(r.get("url") or "")}
    posting = posting_text(r)
    if len(posting) < 400:
        return {**out, "state": "MANUAL", "why": "the posting text could not be read; open the link"}
    s = screen(posting, r["company"])
    # a required technology he lacks is a gap, not a bar (Srikar, 2026-09-16: apply to every company);
    # sponsorship, citizenship, clearance and experience floors still stop it
    hard = [b for b in s["blockers"] if "no repository behind it" not in b]
    if s["verdict"] == "DROP" and hard:
        return {**out, "state": "SKIPPED", "why": "; ".join(hard)[:220]}
    _, _, info = write_packet(app_id)
    if info["blockers"]:
        return {**out, "state": "SKIPPED", "why": "form: " + "; ".join(info["blockers"])[:200]}
    if info["warnings"]:
        return {**out, "state": "YOUR CALL", "why": "form question you cannot honestly pass: " + "; ".join(info["warnings"])[:200]}
    pdf = artifact(app_id, "resume")
    built = None
    if not (pdf and Path(pdf).exists()):
        b = build(app_id)
        if not b.get("ok"):
            return {**out, "state": "BUILD FAILED", "why": b.get("why", "")[:220]}
        pdf, built = b["pdf"], b
    path, _, info = write_packet(app_id)
    out.update(state="READY", resume=pdf, packet=str(path.relative_to(ROOT)), form=info["verdict"],
               open_questions=info["counts"].get("OPEN", 0), required_blank=info["open_required"])
    if built:
        out.update(base=built["base"], skills_added=built.get("skills_added"), skills_confirm=built.get("skills_confirm"))
        subprocess.run([sys.executable, str(HERE / "pipeline.py"), "log", str(app_id), "--kind", "note", "--summary",
                        f"Fast resume and packet ready {date.today()} (base {built['base']}, bullets unchanged). "
                        f"Skills added: {', '.join(built.get('skills_added') or []) or 'none'}. Not submitted."], capture_output=True)
    return out


def write_ready(results: list[dict]) -> None:
    ready = [x for x in results if x["state"] == "READY"]
    L = [f"# Ready to submit, {date.today()}", "",
         "Nothing here was submitted. For each one: open it, review, press Submit yourself, then tell Claude "
         "\"applied to <company>\" so the pipeline records it.", "",
         f"**{len(ready)} ready**, {sum(x['state'] == 'YOUR CALL' for x in results)} your call, "
         f"{sum(x['state'] == 'SKIPPED' for x in results)} skipped, {sum(x['state'] == 'MANUAL' for x in results)} manual, "
         f"{sum(x['state'] == 'BUILD FAILED' for x in results)} failed.", ""]
    L += ["## Ready", ""]
    for x in ready:
        how = (f"`.venv/bin/python scripts/autofill.py --app {x['id']}`" if x["ats"] == "greenhouse"
               else f"open {x['url']} and paste from `{x['packet']}`")
        extra = []
        if x.get("open_questions"):
            extra.append(f"{x['open_questions']} written answer(s) to add")
        if x.get("skills_confirm"):
            extra.append("confirm first: " + ", ".join(x["skills_confirm"]))
        L.append(f"- **#{x['id']} {x['company']}** / {x['role']} ({x['ats']})  \n  {how}  \n  resume `{Path(x['resume']).name}`"
                 + (f"; {'; '.join(extra)}" if extra else ""))
    for state in ("YOUR CALL", "MANUAL", "BUILD FAILED", "SKIPPED"):
        rows = [x for x in results if x["state"] == state]
        if rows:
            L += ["", f"## {state.title()}", ""]
            L += [f"- #{x['id']} {x['company']} / {x['role']}: {x.get('why', '')}" for x in rows]
    READY.write_text("\n".join(L) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids")
    ap.add_argument("--answers", action="store_true")
    a = ap.parse_args()
    done = json.loads(STATE.read_text()) if STATE.exists() else {}

    if a.answers:
        from agent_answers import run as answers_run
        for k, x in done.items():
            if x.get("state") == "READY" and x.get("open_questions") and not x.get("answered"):
                ok = answers_run(int(k), dry=False) == 0
                x["answered"] = ok
                STATE.write_text(json.dumps(done, indent=1) + "\n")
        write_ready(list(done.values()))
        return 0

    con = sqlite3.connect(DB)
    if a.ids:
        ids = [int(i) for i in a.ids.split(",")]
    else:
        ids = [i for (i,) in con.execute("SELECT id FROM applications WHERE status='discovered' ORDER BY id DESC")]
    con.close()
    ids = [i for i in ids if str(i) not in done][: a.limit or None]
    print(f"preparing {len(ids)} posting(s), newest first")
    for i in ids:
        t0 = time.time()
        try:
            x = prepare(i)
        except SystemExit as e:
            x = {"id": i, "state": "BUILD FAILED", "why": str(e)[:200], "company": "?", "role": "?"}
        except Exception as e:
            x = {"id": i, "state": "BUILD FAILED", "why": f"{type(e).__name__}: {e}"[:200], "company": "?", "role": "?"}
        done[str(i)] = x
        STATE.write_text(json.dumps(done, indent=1) + "\n")
        write_ready(list(done.values()))
        print(f"  #{i:<4} {x['state']:12} {round(time.time() - t0):3}s  {x.get('company', '')[:22]:24} {x.get('why', x.get('resume', ''))[:90]}", flush=True)
    print(f"ready list: {READY.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
