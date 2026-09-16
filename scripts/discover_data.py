#!/usr/bin/env python3
"""Find DATA roles that the software-engineering watcher structurally cannot see.

WHY THIS EXISTS. Discovery ran on one source: the SimplifyJobs New-Grad feed,
which is a software-engineering list. `watch_simplify.py` already allows the
words "analyst" and "developer" in a title, so the filter was never the problem.
The FEED was. A Data Analyst job at a bank, a hospital or a data-tooling company
is simply not in it.

The cost was measurable. On 2026-09-07 a fit analysis scored Srikar 76 technical
and 72 experience as a Power BI and Microsoft Fabric analyst, against 45 to 58 as
a new-grad software engineer, while 42 of 42 applications had gone to the second
category. He holds a Microsoft Fabric Analytics Engineer certification that had
never appeared on a resume until that day.

WHAT THIS DOES. Sweeps the public job-board APIs of employers verified to hire
data roles, filters on data titles, drops seniority, non-US and non-full-time on
the title alone, then screens the real posting with the same `screen_job.screen`
the software watcher uses, so nothing reaches the pipeline on a title match.

The board list was built by probing 143 candidate tokens on 2026-09-07 and
keeping the 54 that resolved. Guessing tokens produces silent empty sweeps, so
anything added here is probed first.

Usage:
    python scripts/discover_data.py                 # dry run, show what qualifies
    python scripts/discover_data.py --commit        # add qualified to the pipeline
    python scripts/discover_data.py --limit 25 --no-screen
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover import SENIOR_MARKERS                      # noqa: E402
from screen_job import fetch_jd, screen, NON_US_LOCATION, NOT_FULL_TIME  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (career-agent data discovery)"}

# Verified 2026-09-07. (ats, token). Ordered roughly by how likely the employer
# is to post a role Srikar is actually a fit for, not by board size.
BOARDS: list[tuple[str, str]] = [
    # Data platform and analytics tooling. The densest source of data titles.
    ("greenhouse", "databricks"), ("ashby", "snowflake"), ("greenhouse", "fivetran"),
    ("greenhouse", "hightouch"), ("greenhouse", "sigmacomputing"), ("ashby", "hex"),
    ("ashby", "atlan"), ("ashby", "airbyte"), ("lever", "metabase"),
    ("greenhouse", "starburst"), ("ashby", "montecarlodata"), ("ashby", "prefect"),
    ("ashby", "astronomer"), ("ashby", "sisense"), ("ashby", "sisu"),
    ("greenhouse", "amplitude"), ("greenhouse", "mixpanel"), ("ashby", "posthog"),
    # Health data. Heavy on analyst and data-engineer titles, and often remote.
    ("greenhouse", "truveta"), ("greenhouse", "komodohealth"),
    ("greenhouse", "healthverity"), ("ashby", "nuna"),
    ("greenhouse", "omadahealth"), ("greenhouse", "modernhealth"),
    # Fintech and payments. Analytics, risk and data-science reqs.
    ("greenhouse", "stripe"), ("greenhouse", "affirm"), ("greenhouse", "chime"),
    ("ashby", "plaid"), ("ashby", "ramp"), ("greenhouse", "brex"),
    ("greenhouse", "carta"), ("greenhouse", "mercury"), ("greenhouse", "robinhood"),
    ("greenhouse", "coinbase"), ("greenhouse", "gemini"), ("ashby", "circle"),
    # Remote-first and ops-heavy, where BI and analyst roles are common.
    ("greenhouse", "gitlab"), ("greenhouse", "remotecom"), ("ashby", "oyster"),
    ("greenhouse", "gusto"), ("greenhouse", "smartsheet"), ("greenhouse", "asana"),
    ("ashby", "notion"), ("ashby", "clickup"), ("greenhouse", "airtable"),
    ("ashby", "zapier"), ("ashby", "close"), ("ashby", "buffer"),
    ("ashby", "homebase"), ("ashby", "benevity"), ("lever", "torchdental"),
    ("greenhouse", "instacart"), ("greenhouse", "lyft"), ("greenhouse", "koch"),
]

# Data-role titles. Deliberately broader than the SWE watcher, because this is
# the job family the pipeline has been blind to.
DATA_TITLE = re.compile(
    r"\b("
    r"data\s+analyst|data\s+engineer|data\s+scientist|analytics\s+engineer"
    r"|business\s+intelligence|bi\s+(analyst|developer|engineer)"
    r"|business\s+analyst|reporting\s+analyst|insights\s+analyst"
    r"|analytics\s+(analyst|associate|specialist)"
    r"|decision\s+scientist|quantitative\s+analyst"
    r"|data\s+(platform|infrastructure|operations|quality)\s+engineer"
    r"|machine\s+learning\s+engineer|ml\s+engineer"
    r"|power\s?bi|tableau\s+developer"
    r")\b", re.I)

# NON_US_LOCATION in screen_job.py needs the country spelled out, so a board that
# says only "Toronto" or "Dublin" slips through. F-1 status authorises work in the
# United States and nowhere else, so these are hard drops.
NON_US_CITY = re.compile(
    r"^\s*(toronto|vancouver|montreal|ottawa|waterloo|calgary"
    r"|london|dublin|edinburgh|manchester|bristol|cambridge, uk"
    r"|warsaw|krakow|berlin|munich|amsterdam|paris|madrid|barcelona|lisbon"
    r"|bangalore|bengaluru|hyderabad|pune|gurgaon|gurugram|chennai|noida"
    r"|singapore|tokyo|sydney|melbourne|tel aviv|dubai|sao paulo|mexico city"
    r"|remote\s*[-,]?\s*(canada|uk|emea|apac|latam|europe|india))\b", re.I)

# Titles that read as data but are not his job family.
NOT_HIS = re.compile(
    r"\b(sales|marketing|people|hr|recruit\w*|finance|accounting|legal|clinical|"
    r"compliance|payroll|revenue|gtm|customer\s+success|support)\b", re.I)


def _get(url: str, timeout: int = 20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_board(entry: tuple[str, str]) -> list[dict]:
    ats, tok = entry
    out: list[dict] = []
    try:
        if ats == "greenhouse":
            for j in _get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs").get("jobs", []):
                out.append({"company": tok, "title": j.get("title", ""),
                            "location": (j.get("location") or {}).get("name", ""),
                            "url": j.get("absolute_url", "")})
        elif ats == "lever":
            for j in _get(f"https://api.lever.co/v0/postings/{tok}?mode=json"):
                cat = j.get("categories") or {}
                out.append({"company": tok, "title": j.get("text", ""),
                            "location": cat.get("location", ""),
                            "url": j.get("hostedUrl", "")})
        elif ats == "ashby":
            for j in _get(f"https://api.ashbyhq.com/posting-api/job-board/{tok}").get("jobs", []):
                out.append({"company": tok, "title": j.get("title", ""),
                            "location": j.get("location", ""),
                            "url": j.get("jobUrl", "")})
    except Exception as e:
        print(f"  {ats}/{tok}: {type(e).__name__}", file=sys.stderr)
    return out


def title_ok(r: dict) -> tuple[bool, str]:
    t = (r.get("title") or "")
    tl = t.lower()
    if not DATA_TITLE.search(t):
        return False, "not a data title"
    if NOT_HIS.search(t):
        return False, "wrong function"
    for m in SENIOR_MARKERS:
        if m in tl:
            return False, f"seniority: {m.strip()}"
    if NOT_FULL_TIME.search(t):
        return False, "not full-time"
    loc = r.get("location") or ""
    if loc and (NON_US_LOCATION.search(loc) or NON_US_CITY.search(loc)):
        return False, f"outside the US: {loc[:36]}"
    return True, ""


def known_urls() -> set[str]:
    import sqlite3
    db = ROOT / "data" / "pipeline.db"
    c = sqlite3.connect(db)
    u = {r[0] for r in c.execute("SELECT url FROM applications WHERE url IS NOT NULL")}
    c.close()
    return u


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int, default=40, help="max postings to screen in full")
    ap.add_argument("--no-screen", action="store_true", help="skip the JD read")
    ap.add_argument("--workers", type=int, default=10)
    a = ap.parse_args()

    print(f"sweeping {len(BOARDS)} verified boards ...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        rows = [r for batch in ex.map(fetch_board, BOARDS) for r in batch]
    print(f"  {len(rows)} total postings", file=sys.stderr)

    seen = known_urls()
    cand, drops = [], {}
    for r in rows:
        ok, why = title_ok(r)
        if not ok:
            drops[why] = drops.get(why, 0) + 1
            continue
        if r["url"] in seen:
            drops["already in the pipeline"] = drops.get("already in the pipeline", 0) + 1
            continue
        cand.append(r)

    print(f"  {len(cand)} data-titled and new\n", file=sys.stderr)
    for k, v in sorted(drops.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    dropped {v:5}  {k}", file=sys.stderr)
    print(file=sys.stderr)

    cand = cand[: a.limit]
    qualified = []
    for r in cand:
        if a.no_screen:
            qualified.append((r, {"verdict": "UNSCREENED", "blockers": [], "flags": []}))
            continue
        jd = fetch_jd(r["url"])
        v = screen(jd, r["company"])
        if v["verdict"] == "PASS":
            qualified.append((r, v))
        else:
            b = (v["blockers"] or ["unreadable"])[0]
            print(f"  drop  {r['company'][:18]:20}{r['title'][:44]:46}{b[:52]}", file=sys.stderr)

    print(f"\nQUALIFIED  {len(qualified)}\n")
    for r, v in qualified:
        flags = f"   flags: {'; '.join(v['flags'])[:70]}" if v.get("flags") else ""
        print(f"  {r['company'][:18]:20}{r['title'][:50]:52}{(r['location'] or '')[:26]:28}")
        print(f"    {r['url']}{flags}")

    if not a.commit:
        print("\ndry run. add --commit to put these in the pipeline as 'discovered'.")
        return 0

    added = 0
    for r, _ in qualified:
        p = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "pipeline.py"), "add",
             "--company", r["company"], "--role", r["title"], "--url", r["url"]],
            capture_output=True, text=True)
        if "DUPLICATE" not in p.stdout:
            added += 1
    print(f"\ncommitted {added} of {len(qualified)} (the rest were duplicates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
