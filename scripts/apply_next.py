#!/usr/bin/env python3
"""One job at a time: the next prepared application, its fit analysis, the form filled, then you.

Srikar, 2026-09-16: "once one resume is done lets apply for that job". Instead of preparing
everything and applying in bulk later, this walks the prepared queue one posting at a time:
  1. picks the next job (order below)
  2. makes sure it has a fit analysis (Kimi, then Ultra) and shows the verdict
  3. drafts the written answers when the form has open questions and none are drafted yet
  4. Greenhouse: opens Chrome with the form filled (autofill.py), which stops before Submit
     anything else: opens the posting in your browser and the packet to paste from
  5. asks what happened: submitted, skip for now, or not applying
Nothing here submits. "applied" is recorded only when you answer that you pressed Submit.

Order: the analysis says APPLY IMMEDIATELY (highest realistic first), then APPLY WITH RESUME
TAILORING, then jobs with no analysis yet (newest first; the analysis runs before the form
opens), then UPSKILL FIRST and LOOK ELSEWHERE last, because he asked to apply to every
company. Anything to check first (a technology to confirm, a required question left blank)
is printed before the form opens.

    apply_next.py              the loop, in your terminal
    apply_next.py --list       the next 15 in order, nothing opened
    apply_next.py --app 300    start with this one
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
DB = ROOT / "data" / "pipeline.db"
PY = sys.executable
SKIPS = ROOT / "data" / "logs" / "apply-next-skips.json"
RANK = {"APPLY IMMEDIATELY": 0, "APPLY WITH RESUME TAILORING": 1, None: 2, "UPSKILL FIRST": 3, "LOOK ELSEWHERE": 4}


def batch_state() -> dict[int, tuple[dict, str]]:
    out = {}
    for f in sorted(glob.glob(str(ROOT / "data" / "logs" / "batch-*.json"))):
        for k, v in json.loads(Path(f).read_text()).items():
            out[int(k)] = (v, f)
    return out


def analysis(app_id: int) -> dict | None:
    from agent_fit import has_good_analysis
    from build_desk import analysis_of
    con = sqlite3.connect(DB)
    paths = con.execute("SELECT path, score FROM artifacts WHERE application_id=? AND kind='fit_analysis' ORDER BY id",
                        (app_id,)).fetchall()
    con.close()
    if not paths or not has_good_analysis(app_id):
        return None
    x = analysis_of(app_id, paths)
    if x:
        p = next((Path(q) if Path(q).is_absolute() else ROOT / q for q, _ in reversed(paths) if q.endswith(".md")), None)
        x["path"] = p
        # the bullets were rewritten on 2026-09-17: an analysis older than the resume scores a page he will not send
        from agent_fit import resume_for
        pdf = resume_for(app_id)
        x["stale"] = bool(p and p.exists() and pdf and pdf.stat().st_mtime > p.stat().st_mtime)
    return x


def queue(first: int | None = None) -> list[dict]:
    con = sqlite3.connect(DB)
    open_ids = {i for (i,) in con.execute("SELECT id FROM applications WHERE status='discovered'")}
    con.close()
    skips = json.loads(SKIPS.read_text()) if SKIPS.exists() else {}
    jobs = []
    for app_id, (b, f) in batch_state().items():
        if b.get("state") != "READY" or app_id not in open_ids:
            continue
        a = analysis(app_id)
        rec = a["rec"] if a else None
        jobs.append({**b, "id": app_id, "state_file": f, "analysis": a, "rec": rec,
                     "skipped": str(app_id) in skips})
    jobs.sort(key=lambda j: (j["id"] != first, j["skipped"], RANK.get(j["rec"], 2),
                             -((j["analysis"] or {}).get("realistic") or 0), -j["id"]))
    return jobs


def show(j: dict) -> None:
    a = j["analysis"] or {}
    print("\n" + "=" * 78)
    print(f"#{j['id']}  {j['company']}  /  {j['role']}")
    print(f"platform {j.get('ats')}   resume {Path(j.get('resume') or '').name}")
    print(f"posting  {j.get('url')}")
    if a:
        print(f"fit      paper {a.get('paper')}%   realistic {a.get('realistic')}%   {a.get('rec')}   "
              f"(by {a.get('model')}{', checks passed' if a.get('passed') else ''})")
        md = a["path"].read_text() if a.get("path") else ""
        m = re.search(r"#+\s*The Ten-Second Read\s*\n(.*?)(?=\n#+\s)", md, re.S | re.I)
        if m:
            import html
            print("\n" + html.unescape(re.sub(r"\n{3,}", "\n\n", m.group(1).strip()))[:900])
        if a.get("path"):
            print(f"\nfull analysis: {a['path'].relative_to(ROOT)}")
    checks = []
    if j.get("skills_confirm"):
        checks.append("confirm you have used: " + ", ".join(j["skills_confirm"]))
    if j.get("required_blank"):
        checks.append(f"{j['required_blank']} required question(s) the packet could not answer; the form marks them red")
    for c in checks:
        print(f"CHECK    {c}")


def ensure_answers(j: dict) -> None:
    if not j.get("open_questions") or j.get("answered"):
        return
    print(f"drafting {j['open_questions']} written answer(s) on NVIDIA first...", flush=True)
    from agent_answers import run as answers_run
    ok = answers_run(j["id"], dry=False) == 0
    f = Path(j["state_file"])
    state = json.loads(f.read_text())
    state[str(j["id"])]["answered"] = ok
    f.write_text(json.dumps(state, indent=1) + "\n")
    print("  written answers " + ("added to the packet" if ok else "failed; the form leaves those questions to you"))


def pipeline(*args: str) -> None:
    subprocess.run([PY, str(HERE / "pipeline.py"), *args], capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--app", type=int)
    a = ap.parse_args()

    if a.list:
        for j in queue(a.app)[:15]:
            x = j["analysis"] or {}
            fit = f"{x.get('paper')}% / {x.get('realistic')}%" if x else "analysis pending"
            print(f"#{j['id']:<4} {j['company'][:24]:26}{(j['rec'] or '').title()[:26]:28}{fit:18}{j.get('ats')}"
                  + ("  (skipped earlier)" if j["skipped"] else ""))
        return 0

    first, done_now = a.app, set()
    while True:
        jobs = [j for j in queue(first) if j["id"] not in done_now]
        if not jobs:
            print("nothing left in the prepared queue")
            return 0
        j = jobs[0]
        first = None
        done_now.add(j["id"])
        if not j["analysis"] or j["analysis"].get("stale"):
            why = "the resume changed since its analysis, rescoring" if j["analysis"] else "writing the fit analysis first"
            print(f"\n#{j['id']} {j['company']}: {why} (Kimi, then Ultra; a few minutes)...", flush=True)
            subprocess.run([PY, str(HERE / "agent_fit.py"), "--app", str(j["id"])])
            j["analysis"] = analysis(j["id"])
        show(j)
        go = input("\nopen this application? [enter] yes   [s] skip for now   [n] not applying   [q] quit: ").strip().lower()
        if go == "q":
            return 0
        if go in ("s", "n"):
            record(j, go)
            continue
        ensure_answers(j)
        if j.get("ats") == "greenhouse":
            print("opening Chrome with the form filled. Review it, answer anything red, press Submit, close the window.")
            subprocess.run([PY, str(HERE / "autofill.py"), "--app", str(j["id"])])
        else:
            print("opening the posting and the packet. Paste from the packet, attach the resume, press Submit.")
            subprocess.run(["open", j.get("url") or ""])
            if j.get("packet"):
                subprocess.run(["open", "-e", str(ROOT / j["packet"])])
            subprocess.run(["open", "-R", j.get("resume") or ""])
        ans = ""
        while ans not in ("y", "s", "n", "q"):         # a bare Enter is not an answer (InterSystems, 2026-09-17)
            ans = input("\ndid you press Submit? [y] submitted   [s] skip for now   [n] not applying   [q] quit: ").strip().lower()
        if ans == "q":
            return 0
        record(j, ans)


def record(j: dict, ans: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con = sqlite3.connect(DB)
    status = (con.execute("SELECT status FROM applications WHERE id=?", (j["id"],)).fetchone() or ["?"])[0]
    con.close()
    if status != "discovered":                   # he told Claude "applied to X" in chat while this waited
        print(f"{j['company']} is already recorded as {status}; moving on")
        return
    if ans == "y":
        pipeline("move", str(j["id"]), "applied")
        pipeline("log", str(j["id"]), "--kind", "note", "--summary",
                 f"Submitted by Srikar via apply_next.py ({j.get('ats')}; resume {Path(j.get('resume') or '').name}).")
        print(f"recorded: applied to {j['company']}")
    elif ans == "n":
        why = input("why not (one line, optional): ").strip()
        pipeline("move", str(j["id"]), "withdrawn")
        pipeline("log", str(j["id"]), "--kind", "note", "--summary", f"Srikar decided not to apply. {why}".strip())
        print(f"recorded: not applying to {j['company']}")
    else:
        skips = json.loads(SKIPS.read_text()) if SKIPS.exists() else {}
        skips[str(j["id"])] = now
        SKIPS.write_text(json.dumps(skips, indent=1) + "\n")
        print(f"skipped {j['company']} for now; it goes to the back of the queue")


if __name__ == "__main__":
    sys.exit(main())
