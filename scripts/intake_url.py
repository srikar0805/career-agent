#!/usr/bin/env python3
"""Turn one job link into a pipeline row, ready for apply_flow.py.

Srikar, 2026-09-17: "Creating the resumes in bulk is creating chaos around so lets update the
pipeline here. We have the dashboard right so there I will find the link to the job description
and provide you with the link, you create the complete perfect resume and also the cover letter
for it and also provide the answers to the questions". So the pipeline no longer prepares
everything in advance: a link arrives, and this is the front door.

It fetches the posting, works out the employer and the title, screens it, and either reuses the
row the pipeline already has for that URL or adds one. Nothing is submitted and no resume is
built here; apply_flow.py does the rest.

    intake_url.py https://job-boards.greenhouse.io/acme/jobs/123
    intake_url.py <url> --json            machine readable, for apply_flow
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
DB = ROOT / "data" / "pipeline.db"

SYSTEM = """You read one job posting and name the employer, the job title and the location, copying
them out of the text. Copy the values, never the instructions.
Example answer for a posting by Acme about a backend role in Austin:
{"company": "Acme", "role": "Backend Engineer II", "location": "Austin, TX"}
Reply with ONE JSON object holding company, role and location. Every value must appear in the
posting text; use null for a location the posting does not state."""


def slug_of(url: str) -> str:
    """The employer slug an ATS puts in the URL, as a fallback name and for matching rows."""
    m = (re.search(r"job-boards\.greenhouse\.io/(?:embed/job_app\?for=)?([\w.-]+)", url)
         or re.search(r"boards\.greenhouse\.io/([\w.-]+)", url)
         or re.search(r"jobs\.ashbyhq\.com/([\w.-]+)", url)
         or re.search(r"jobs\.lever\.co/([\w.-]+)", url)
         or re.search(r"([\w.-]+)\.my\.salesforce-sites\.com", url)
         or re.search(r"//(?:www\.)?([\w-]+)\.", url))
    return (m.group(1) if m else "").replace("-", " ").strip()


def existing_row(url: str) -> int | None:
    from agent_verdict import row                      # noqa: F401  (kept for symmetry with callers)
    key = re.sub(r"[?#].*$", "", url).rstrip("/")
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    hit = None
    for r in con.execute("SELECT id, url, status FROM applications WHERE url IS NOT NULL ORDER BY id DESC"):
        u = re.sub(r"[?#].*$", "", r["url"] or "").rstrip("/")
        if u and (u == key or (len(u) > 25 and (u in key or key in u))):
            hit = r["id"]
            break
    con.close()
    return hit


def identify(jd: str, url: str, known: dict | None = None) -> dict:
    """What this posting is. A value the posting does not contain is a guess and is dropped:
    the first run on 2026-09-17 echoed the schema back ("the job title exactly as posted")."""
    from nim import NimError, chat
    known = known or {}
    out = {"company": known.get("company") or "", "role": known.get("role") or "", "location": known.get("location")}
    try:
        res = chat("scout", SYSTEM, jd[:6000], want_json=True, max_tokens=500, purpose="intake")
        d = res.get("json") if isinstance(res.get("json"), dict) else {}
    except NimError:
        d = {}
    low = jd.lower()
    for k in ("company", "role", "location"):
        v = re.sub(r"\s+", " ", str(d.get(k) or "")).strip()
        if v and v.lower() in low and len(v) < 120 and not re.search(r"\bas posted\b|\bexactly as\b|\bor null\b", v, re.I):
            out[k] = v
    if not out["company"]:
        out["company"] = slug_of(url).title() or "Unknown employer"
    if not out["role"]:
        m = re.match(r"\s*([A-Z][^\n|]{4,70})", jd)       # the posting usually opens with its own title
        out["role"] = (m.group(1).strip() if m else "") or "Unknown role"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    from screen_job import fetch_jd, screen

    jd = fetch_jd(a.url)
    if len(jd) < 400:
        print(json.dumps({"ok": False, "why": "the posting text could not be read from that link"})
              if a.json else "could not read that posting; paste the description text instead")
        return 1
    found = existing_row(a.url)
    known = {}
    if found:
        from agent_verdict import row
        r0 = row(found)
        known = {"company": r0["company"], "role": r0["role"], "location": r0.get("location")}
    what = identify(jd, a.url, known)
    s = screen(jd, what["company"])
    if found:
        subprocess.run([sys.executable, str(HERE / "pipeline.py"), "show", str(found)], capture_output=True)
        app_id = found
        con = sqlite3.connect(DB)                      # refresh the stored posting text
        con.execute("UPDATE applications SET jd_text=?, updated_at=datetime('now') WHERE id=?", (jd, app_id))
        con.commit()
        con.close()
    else:
        out = subprocess.run([sys.executable, str(HERE / "pipeline.py"), "add", "--company", what["company"],
                              "--role", what["role"] or "Unknown role", "--url", a.url, "--jd", jd]
                             + (["--location", what["location"]] if what["location"] else []),
                             capture_output=True, text=True).stdout
        m = re.search(r"#(\d+)", out)
        app_id = int(m.group(1)) if m else None
    result = {"ok": app_id is not None, "app_id": app_id, **what, "verdict": s["verdict"],
              "blockers": s["blockers"], "flags": s.get("flags") or [], "existing": bool(found)}
    if a.json:
        print(json.dumps(result, indent=1))
    else:
        print(f"#{app_id} {what['company']} / {what['role']} ({what['location'] or 'location unstated'})"
              f"{'  [already in the pipeline]' if found else '  [added]'}")
        print(f"screen: {s['verdict']}" + (f"; blockers: {'; '.join(s['blockers'])}" if s["blockers"] else ""))
        print(f"next: .venv/bin/python scripts/apply_flow.py --app {app_id}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
