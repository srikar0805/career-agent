#!/usr/bin/env python3
"""Daily watcher over the SimplifyJobs New-Grad-Positions feed.

Pulls the structured listing feed, keeps only rows that clear Srikar's
eligibility filters, drops anything already in the pipeline, and writes the
survivors into the pipeline as `discovered` so the morning queue is real work
rather than a scroll.

WHAT THIS DOES NOT DO, deliberately:
  It does not submit anything. It does not message anyone. It stages work and
  stops. Every downstream step (resume, answers, outreach) is generated for
  review and waits for a human to press send. See docs in the run report.

Filters, in order, each one cheap before the expensive ones:
  1. active and visible
  2. posted within --days (default 3), so a daily run never re-reads history
  3. degree includes Bachelor's or Master's
  4. sponsorship is not a hard block (citizenship-required rows are dropped)
  5. title is entry level, using discover.py's seniority markers
  6. title matches his domains, using discover.py's word-boundary patterns
  7. not already in pipeline.db by URL

Usage:
    python scripts/watch_simplify.py                 # report only
    python scripts/watch_simplify.py --commit        # write to the pipeline
    python scripts/watch_simplify.py --days 7 --commit
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover import SENIOR_MARKERS, term_pattern  # noqa: E402
from screen_job import fetch_jd, screen, NON_US_LOCATION, NOT_FULL_TIME  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "pipeline.db"
FEED = ("https://raw.githubusercontent.com/SimplifyJobs/"
        "New-Grad-Positions/dev/.github/scripts/listings.json")

# Title terms worth surfacing, from profile/skills.yaml and what he has
# actually applied to. Matched with discover.py's word-boundary patterns so
# "intern" never matches "Internals".
DOMAINS = [
    "software engineer", "software developer", "backend", "back end",
    "full stack", "fullstack", "machine learning", "ml engineer",
    "ai engineer", "data engineer", "data scientist", "platform engineer",
    "infrastructure engineer", "applied scientist", "research engineer",
    "forward deployed", "programmer analyst", "systems engineer",
    "analyst", "developer",
]

# Sponsorship values that end the conversation. "Other" is the overwhelming
# default in this feed and means unstated, not refused, so it is kept.
BLOCKING_SPONSORSHIP = {"U.S. Citizenship is Required"}


def fetch(url: str = FEED) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "career-agent"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def eligible(rec: dict, cutoff: float, pats: list) -> tuple[bool, str]:
    if not rec.get("active") or not rec.get("is_visible"):
        return False, "inactive"
    if (rec.get("date_posted") or 0) < cutoff:
        return False, "older than window"
    degs = " ".join(rec.get("degrees") or []).lower()
    if degs and not any(d in degs for d in ("bachelor", "master")):
        return False, f"degree: {degs}"
    if rec.get("sponsorship") in BLOCKING_SPONSORSHIP:
        return False, "citizenship required"
    title = (rec.get("title") or "").lower()
    for m in SENIOR_MARKERS:
        if m in title:
            return False, f"seniority: {m}"
    if not any(p.search(title) for p in pats):
        return False, "domain mismatch"
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--no-screen", action="store_true",
                    help="skip reading the postings (title filters only)")
    a = ap.parse_args()

    cutoff = datetime.now(timezone.utc).timestamp() - a.days * 86400
    pats = [term_pattern(t) for t in DOMAINS]
    recs = fetch()

    con = sqlite3.connect(DB)
    seen = {r[0] for r in con.execute("SELECT url FROM applications WHERE url IS NOT NULL")}

    hits, reasons = [], {}
    for r in recs:
        ok, why = eligible(r, cutoff, pats)
        if not ok:
            reasons[why] = reasons.get(why, 0) + 1
            continue
        if (r.get("url") or "") in seen:
            reasons["already tracked"] = reasons.get("already tracked", 0) + 1
            continue
        hits.append(r)

    hits.sort(key=lambda r: r.get("date_posted") or 0, reverse=True)
    hits = hits[: a.limit]

    # STAGE 2. Title filters are cheap and wrong on their own: they cannot see a
    # citizenship requirement, a 5-year floor, or a required language he has no
    # repository for. So read each surviving posting and screen it against
    # profile/identity.yaml. Only PASS reaches the queue; UNKNOWN is reported
    # separately because an unread posting is not a clean one.
    passed, dropped, unknown = [], [], []
    if not a.no_screen:
        print(f"reading {len(hits)} postings...\n")
        for r in hits:
            # Location is knowable from the feed and costs no fetch. Synack's
            # "Remote in UK" reached the queue on 2026-09-02 because nothing
            # checked it: he holds F-1 status in the United States and cannot
            # take a role that needs another country's authorization.
            # Full-time only. Read off the title, so it costs no fetch.
            if NOT_FULL_TIME.search(r.get("title", "")):
                r["_screen"] = {"verdict": "DROP", "flags": [], "jd_chars": 0,
                                "blockers": ["not full-time: internship, co-op or "
                                             "part-time in the title"]}
                dropped.append(r)
                continue

            loc_s = ", ".join(r.get("locations") or [])
            if NON_US_LOCATION.search(loc_s):
                r["_screen"] = {"verdict": "DROP", "flags": [], "jd_chars": 0,
                                "blockers": [f"located outside the US: {loc_s[:40]}"]}
                dropped.append(r)
                continue
            v = screen(fetch_jd(r.get("url") or ""), r.get("company_name", ""))
            r["_screen"] = v
            (passed if v["verdict"] == "PASS"
             else unknown if v["verdict"] == "UNKNOWN" else dropped).append(r)
    else:
        passed = hits

    for r in passed:
        loc = ", ".join(r.get("locations") or [])[:34]
        d = datetime.fromtimestamp(r.get("date_posted") or 0, timezone.utc).date()
        print(f"  {d}  {r['company_name'][:24]:<26}{r['title'][:42]:<44}{loc}")
        for f in (r.get("_screen") or {}).get("flags", []):
            print(f"          flag: {f[:104]}")
        if a.commit:
            con.execute(
                "INSERT INTO applications (track,company,role,url,source,location,"
                "status,sponsors,discovered_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("job", r["company_name"], r["title"], r["url"], "simplify",
                 loc, "discovered", r.get("sponsorship"),
                 datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat()))
    if a.commit:
        con.commit()

    print(f"\nfeed {len(recs)} records, {a.days}d window")
    for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:6]:
        print(f"    title-filtered {v:>6}  {k}")
    print(f"    read in full   {len(hits):>6}")
    print(f"    QUALIFIED      {len(passed):>6}   <- these are in the list above")
    print(f"    dropped on JD  {len(dropped):>6}")
    print(f"    unreadable     {len(unknown):>6}")

    if dropped:
        print("\ndropped, with the stated minimum he does not meet:")
        for r in dropped:
            b = (r["_screen"]["blockers"] or ["?"])[0]
            print(f"  {r['company_name'][:22]:<24}{r['title'][:36]:<38}{b[:56]}")
    if unknown:
        print("\nunreadable postings, check these by hand:")
        for r in unknown:
            print(f"  {r['company_name'][:22]:<24}{r['title'][:40]:<42}{r['url'][:44]}")
    if a.commit:
        print(f"\ncommitted {len(passed)} qualified to the pipeline as 'discovered'")
    else:
        print("\ndry run. re-run with --commit to write the qualified ones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
