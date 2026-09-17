#!/usr/bin/env python3
"""Recruiter finder: the right recruiter at each company, from LinkedIn. Never messages anyone.

Srikar, 2026-09-16: "one agent finding the recruiters from LinkedIn, finding the correct
recruiters", handled by a model like Qwen. Qwen is not reachable with his keys that day
(NVIDIA retired every Qwen model, 410 Gone; Ollama answers 402 for qwen3.5 on his plan), so
the role runs on gpt-oss:120b on Ollama, with nemotron-3-super behind it. Gemini is left out
on purpose: this role handles other people's profiles, and Google's free tier may train on
prompts. Switching to Qwen later is one line in data/nim_roster.json ("recruiter").

Per company, one LinkedIn people search (the account asked to verify a new device twice on
2026-09-12, so the whole run is capped), then the model ranks what came back:
  prefer    university, campus and early-career recruiters; technical recruiters and
            talent acquisition partners for engineering and data; US-based
  avoid     agency or staffing recruiters, people not currently at the company, sales
            and executive titles (a founder or engineering manager only at a small startup)
Checked, not trusted: every name and profile link the model returns must appear in the
LinkedIn result text, so no person can be invented. Picks go into the pipeline as cold
contacts with the reason, and show on the desk. Nothing is sent, requested or followed.

Which companies: applications sent in the last 21 days with no contact at the company
first, then the highest fit scores among prepared postings.

    agent_recruiters.py                  up to 3 companies, dry run
    agent_recruiters.py --commit         save the picks as contacts
    agent_recruiters.py --company C3.ai  one named company
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
DB = ROOT / "data" / "pipeline.db"
MAX_COMPANIES = 3

SYSTEM = """You pick the right recruiters for a new-grad candidate to contact at ONE company, \
from LinkedIn people-search results. The candidate: M.S. Computer and Information Sciences, \
graduating May 2027, applying to software, data and machine learning roles, on an F-1 visa.

Rank only people in the results. Prefer, in order: university, campus or early-career recruiters; \
technical recruiters or talent acquisition partners who hire engineering or data roles; other \
in-house recruiters at the company. Prefer people based in the United States.
Exclude: anyone not currently working at this company, agency or staffing-firm recruiters, sales, \
marketing or executive titles (at a startup under about 50 people a founder or engineering manager \
is acceptable), and duplicates.

Reply with ONE JSON object:
{"picks": [{"name": "exact name as shown", "headline": "exact headline or title as shown",
  "profile_url": "exact LinkedIn URL or username as shown", "location": "as shown or null",
  "relevance": integer 0 to 100, "why": "one sentence restating only what the result shows (title, team, location); no guesses about what they hire for; no em dashes"}]}
Return at most 3 picks, best first. Return {"picks": []} if nobody fits."""


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def targets(limit: int) -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    have = {norm(c) for (c,) in con.execute("SELECT DISTINCT company FROM contacts")}
    since = (date.today() - timedelta(days=21)).isoformat()
    out, seen = [], set()
    for r in con.execute("SELECT id, company, role FROM applications WHERE status IN ('applied','screening') "
                         "AND applied_at >= ? ORDER BY applied_at DESC", (since,)):
        k = norm(r["company"])
        if k and k not in have and k not in seen:
            out.append({**dict(r), "why_target": "applied recently, nobody identified yet"})
            seen.add(k)
    scores = []
    for f in glob.glob(str(ROOT / "data" / "artifacts" / "*" / "verdict-*.json")):
        try:
            v = json.loads(Path(f).read_text())
            if v.get("verdict") != "skip" and v.get("fit_score") is not None:
                scores.append(v)
        except Exception:
            pass
    open_ids = {i for (i,) in con.execute("SELECT id FROM applications WHERE status='discovered'")}
    for v in sorted(scores, key=lambda v: -v["fit_score"]):
        k = norm(v["company"])
        if v["app_id"] in open_ids and k not in have and k not in seen:
            out.append({"id": v["app_id"], "company": v["company"], "role": v["role"],
                        "why_target": f"fit score {v['fit_score']}, nobody identified yet"})
            seen.add(k)
    con.close()
    return out[:limit]


def result_text(r) -> str:
    if getattr(r, "structured_content", None):
        return json.dumps(r.structured_content)
    return "\n".join(getattr(p, "text", "") for p in (r.content or []))


async def search(companies: list[dict]) -> dict[str, str]:
    from mcp import Client, StdioServerParameters
    out = {}
    async with Client(StdioServerParameters(command="uvx", args=["mcp-server-linkedin@latest"])) as c:
        for t in companies:
            r = await c.call_tool("search_people", {"keywords": f"recruiter {t['company']}", "location": "United States"})
            out[t["company"]] = result_text(r)[:9000]
        try:
            await c.call_tool("close_session", {})
        except Exception:
            pass
    return out


def rank(company: dict, raw: str) -> tuple[list[dict], list[str]]:
    from nim import NimError, chat
    try:
        res = chat("recruiter", SYSTEM, f"COMPANY: {company['company']} (role he applied to or is applying to: {company['role']})\n\n"
                   f"LINKEDIN RESULTS:\n{raw}", want_json=True, max_tokens=3000, purpose=f"recruiters {company['company']}")
    except NimError as e:
        return [], [f"model unavailable: {str(e)[:120]}"]
    picks = (res["json"] or {}).get("picks") if isinstance(res["json"], dict) else []
    kept, dropped = [], []
    raw_l = raw.lower()
    for p in picks or []:
        name, url = str(p.get("name") or "").strip(), str(p.get("profile_url") or "").strip()
        # LinkedIn gives full URLs, bare "linkedin.com/in/x" or relative "/in/x" (C3.ai, 2026-09-16)
        slug = re.sub(r"^((https?://)?(www\.)?linkedin\.com)?/?in/", "", url, flags=re.I).strip("/").split("?")[0]
        if not name or name.lower() not in raw_l:
            dropped.append(f"{name or '?'}: name not in the LinkedIn results")
            continue
        if not slug or slug.lower() not in raw_l:
            dropped.append(f"{name}: profile link not in the LinkedIn results")
            continue
        if int(p.get("relevance") or 0) < 55:
            dropped.append(f"{name}: relevance {p.get('relevance')}")
            continue
        kept.append({"name": name, "headline": str(p.get("headline") or "")[:160], "linkedin": f"https://www.linkedin.com/in/{slug}/",
                     "location": p.get("location"), "relevance": int(p.get("relevance") or 0),
                     "why": re.sub(r"\s*[—–]\s*", ", ", str(p.get("why") or ""))[:220], "model": res["model"]})
    return kept[:2], dropped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--company")
    ap.add_argument("--limit", type=int, default=MAX_COMPANIES)
    a = ap.parse_args()
    limit = min(a.limit, MAX_COMPANIES)                      # the cap is the point
    if a.company:
        con = sqlite3.connect(DB)
        r = con.execute("SELECT id, company, role FROM applications WHERE lower(company)=lower(?) ORDER BY id DESC LIMIT 1",
                        (a.company,)).fetchone()
        con.close()
        todo = [{"id": r[0], "company": r[1], "role": r[2], "why_target": "named"}] if r else []
    else:
        todo = targets(limit)
    if not todo:
        print("recruiters: no company needs one")
        return 0
    print("recruiters: searching", ", ".join(t["company"] for t in todo))
    raws = asyncio.run(asyncio.wait_for(search(todo), 420))
    report = []
    for t in todo:
        kept, dropped = rank(t, raws.get(t["company"], ""))
        report.append({**t, "picks": kept, "dropped": dropped, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        print(f"  {t['company']} ({t['why_target']}): {len(kept)} pick(s)")
        for p in kept:
            print(f"    {p['relevance']:3}  {p['name']}, {p['headline'][:70]}  {p['linkedin']}\n         {p['why']}")
        for d in dropped:
            print(f"    dropped  {d}")
        if a.commit:
            for p in kept:
                subprocess.run([sys.executable, str(HERE / "pipeline.py"), "contact", "--name", p["name"], "--title", p["headline"],
                                "--company", t["company"], "--linkedin", p["linkedin"], "--relationship", "cold",
                                "--notes", f"Found by agent_recruiters.py {date.today()} ({p['model'].split('/')[-1]}) for #{t['id']} "
                                           f"{t['role']}: {p['why']} Not contacted."], capture_output=True, text=True)
    out = ROOT / "data" / "logs" / f"recruiters-{date.today()}.json"
    prev = json.loads(out.read_text()) if out.exists() else []
    out.write_text(json.dumps(prev + report, indent=1) + "\n")
    print(f"report: {out.relative_to(ROOT)}{'' if a.commit else '  (dry run, no contacts saved)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
