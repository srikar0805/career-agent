#!/usr/bin/env python3
"""Job boards agent: Dice (and LinkedIn, capped) from Python, so Claude never reads a board.

Until 2026-09-16 the daily Stage 2 Claude session searched Dice and LinkedIn
itself, reading every result into its context. Srikar asked for those searches to
move to their own agent with the reading done on NVIDIA. This calls the SAME
servers Claude used (mcp.dice.com over HTTP, the local LinkedIn server over
stdio) with the MCP Python client, filters deterministically, and uses the
NVIDIA scout model only on the few postings that survive, to catch what fields
do not say: staffing agencies posing as employers, contract roles, experience
floors.

Filters, in order, each one cheaper than the next:
  Dice employerType must be Direct Hire and employmentType full-time
  discover_ats.title_ok: job family, seniority, US location, language roles
  the entry-level gate for generic software titles (same rule as the ATS sweep)
  already in the pipeline, or screened and dropped before
  screen_job.screen on the full description (sponsorship, citizenship, clearance)
  NVIDIA scout: staffing or contract, years required, graduation window

LinkedIn stays at the caps set on 2026-09-13 after the account asked twice to
verify a new device: two job searches a day, one page each, weekday rotation.
Results are LEADS, written to data/logs/linkedin-leads-<date>.json, never added
to the pipeline directly (Easy Apply is the weakest channel he has).

    agent_boards.py                      dry run: Dice only, prints what would be added
    agent_boards.py --commit             add Dice survivors as 'discovered'
    agent_boards.py --commit --linkedin  also run today's two capped LinkedIn searches
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from discover_ats import DATA_TITLE, LEVEL, _norm, pipeline_keys, posting_key, title_ok   # noqa: E402
from screen_job import screen                                                               # noqa: E402

SEEN = ROOT / "data" / "boards_seen.json"
DICE_URL = "https://mcp.dice.com/mcp"
FAMILIES = ["data analyst", "data engineer", "data scientist", "business intelligence analyst",
            "machine learning engineer", "software engineer new grad", "entry level software engineer"]
LINKEDIN_ROTATION = [("data analyst", "data engineer"), ("software engineer", "machine learning engineer"),
                     ("data scientist", "business intelligence analyst"), ("data engineer", "software engineer"),
                     ("machine learning engineer", "data analyst")]

SCOUT_SYSTEM = """Extract facts from a job posting. Reply with ONE JSON object only:
{"staffing_or_contract": true if the poster is a staffing agency, recruiter or consultancy placing someone \
at a client, or the role is contract, contract-to-hire, C2C or W2 through a third party; otherwise false,
 "real_employer": "company the person would actually work for",
 "years_required": minimum years of professional experience required as an integer, or null,
 "graduation_window": "the graduation dates the posting requires, verbatim", or null,
 "sponsorship_statement": "the posting's sentence about visas or sponsorship, verbatim", or null}"""


def detag(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def clean_url(u: str) -> str:
    return (u or "").split("?")[0]


async def dice_search(families: list[str], sponsor_pass: bool) -> tuple[list[dict], dict[str, str]]:
    from mcp import Client
    found, details = {}, {}
    async with Client(DICE_URL) as c:
        for fam in families:
            args = {"keyword": fam, "jobs_per_page": 20, "posted_date": "THREE", "employment_types": ["FULLTIME"]}
            if sponsor_pass:
                args["willing_to_sponsor"] = True
            r = await c.call_tool("search_jobs", args)
            if r.is_error:
                print(f"  dice {fam!r}: {str(r.content[0].text)[:100]}", file=sys.stderr)
                continue
            d = r.structured_content or json.loads(r.content[0].text)
            for j in d.get("data", []):
                found.setdefault(j["guid"], {**j, "_family": fam, "_sponsor_pass": sponsor_pass})
        return list(found.values()), details


async def dice_details(guids: list[str]) -> dict[str, str]:
    from mcp import Client
    out = {}
    async with Client(DICE_URL) as c:
        for g in guids:
            r = await c.call_tool("get_job_details", {"job_id": g})
            if not r.is_error:
                d = r.structured_content or json.loads(r.content[0].text)
                out[g] = detag(d.get("description", "")) + " Skills: " + ", ".join(
                    s if isinstance(s, str) else str(s.get("name", s)) for s in (d.get("skills") or []))
    return out


async def dice_companies(guids: list[str]) -> dict[str, str]:
    from mcp import Client
    out = {}
    async with Client(DICE_URL) as c:
        for g in guids:
            r = await c.call_tool("get_company", {"job_id": g})
            if not r.is_error:
                d = r.structured_content or json.loads(r.content[0].text)
                out[g] = (d.get("desc") or "").strip()
    return out


async def linkedin_leads() -> list[dict]:
    from mcp import Client, StdioServerParameters
    pair = LINKEDIN_ROTATION[date.today().weekday() % len(LINKEDIN_ROTATION)]
    leads = []
    params = StdioServerParameters(command="uvx", args=["mcp-server-linkedin@latest"])
    async with Client(params) as c:
        for kw in pair:                                   # exactly two searches: the cap
            r = await c.call_tool("search_jobs", {"keywords": kw, "location": "United States", "max_pages": 1,
                                                  "job_type": "full_time", "experience_level": "entry,associate",
                                                  "date_posted": "past_week", "sort_by": "date"})
            text = r.content[0].text if r.content else ""
            try:
                data = r.structured_content or json.loads(text)
            except Exception:
                data = {"raw": text[:4000]}
            leads.append({"keywords": kw, "result": data})
        try:
            await c.call_tool("close_session", {})
        except Exception:
            pass
    return leads


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--linkedin", action="store_true")
    ap.add_argument("--no-scout", action="store_true", help="skip the NVIDIA scout pass")
    a = ap.parse_args()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # sponsor pass over every family; the unfiltered pass rotates three families a day
    rot = date.today().toordinal() % len(FAMILIES)
    unfiltered = (FAMILIES + FAMILIES)[rot:rot + 3]
    rows_s, _ = asyncio.run(dice_search(FAMILIES, True))
    rows_u, _ = asyncio.run(dice_search(unfiltered, False))
    rows = {r["guid"]: r for r in rows_u + rows_s}.values()          # sponsor-pass copy wins
    print(f"dice: {len(rows_s)} from the sponsor pass, {len(rows_u)} unfiltered ({', '.join(unfiltered)})")

    urls, pairs, _ = pipeline_keys()
    seen = json.loads(SEEN.read_text()) if SEEN.exists() else {}
    drops, cand = {}, []
    for j in rows:
        url = clean_url(j.get("detailsPageUrl"))
        r = {"title": j.get("title", ""), "location": (j.get("jobLocation") or {}).get("displayName", ""),
             "company": j.get("companyName") or "", "employment": j.get("employmentType") or ""}
        why = ""
        if (j.get("employerType") or "") != "Direct Hire":
            why = f"employer type {j.get('employerType')}"
        elif "full" not in r["employment"].lower():
            why = "not full-time"
        else:
            ok, why = title_ok(r)
            why = "" if ok else why
            if not why and not LEVEL.search(r["title"]) and not DATA_TITLE.search(r["title"]):
                why = "generic software title, no entry-level signal"
        if not why and (posting_key(url) in urls or (_norm(r["company"]), _norm(r["title"])) in pairs):
            why = "already in the pipeline"
        if not why and j["guid"] in seen:
            why = "screened and dropped before"
        if why:
            drops[why] = drops.get(why, 0) + 1
            continue
        cand.append((j, r, url))
    print(f"  {len(cand)} survive the field filters")
    for k, v in sorted(drops.items(), key=lambda kv: -kv[1])[:6]:
        print(f"    dropped {v:4}  {k}")

    texts = asyncio.run(dice_details([j["guid"] for j, _, _ in cand])) if cand else {}
    companies = asyncio.run(dice_companies([j["guid"] for j, _, _ in cand])) if cand else {}
    keep = []
    for j, r, url in cand:
        text = texts.get(j["guid"], "")
        # An employer Dice knows nothing about, posting nowhere in particular, is the
        # profile of a firm that recruits OPT students rather than employs them.
        # Nexorant LLC on 2026-09-16: no company description, no location, and a
        # description generic enough that the scout found nothing to object to.
        if not companies.get(j["guid"]) and not r["location"]:
            seen[j["guid"]] = {"at": stamp, "why": "employer unverifiable on Dice: no company profile, no location"}
            drops["employer unverifiable"] = drops.get("employer unverifiable", 0) + 1
            continue
        if companies.get(j["guid"]):
            text = f"About the company: {companies[j['guid']][:1500]}\n\n{text}"
        v = screen(text, r["company"]) if len(text) > 300 else {"verdict": "UNKNOWN", "blockers": [], "flags": []}
        if v["verdict"] == "DROP":
            seen[j["guid"]] = {"at": stamp, "why": (v["blockers"] or ["screen"])[0][:120]}
            continue
        if v["verdict"] != "PASS":
            continue
        keep.append((j, r, url, text, v))

    if keep and not a.no_scout:
        from nim import NimError, chat
        scouted = []
        for j, r, url, text, v in keep:
            try:
                s = chat("scout", SCOUT_SYSTEM, f"{r['company']} / {r['title']}\n\n{text[:8000]}", want_json=True,
                         max_tokens=1500, purpose=f"boards scout dice {j['guid'][:8]}")["json"]
            except NimError as e:
                print(f"  scout unavailable ({str(e)[:80]}); keeping the deterministic result")
                scouted.append((j, r, url, text, v, {}))
                continue
            yrs = s.get("years_required") if isinstance(s, dict) else None
            if isinstance(s, dict) and (s.get("staffing_or_contract") is True or (isinstance(yrs, int) and yrs > 2)):
                seen[j["guid"]] = {"at": stamp, "why": f"scout: staffing/contract={s.get('staffing_or_contract')} years={yrs}"}
                continue
            scouted.append((j, r, url, text, v, s if isinstance(s, dict) else {}))
        keep = scouted
    else:
        keep = [(*k, {}) for k in keep]

    SEEN.write_text(json.dumps(seen, indent=1) + "\n")
    print(f"\nQUALIFIED {len(keep)}")
    added = 0
    for j, r, url, text, v, s in keep:
        note = (f"Found by agent_boards.py {stamp[:10]} on Dice ({'sponsor pass' if j['_sponsor_pass'] else 'unfiltered'}, "
                f"search '{j['_family']}'). Dice says willingToSponsor={j.get('willingToSponsor')}, salary {j.get('salary') or 'unstated'}."
                + (f" Scout: {json.dumps(s)[:300]}" if s else "")
                + (f" Screen flags: {'; '.join(v['flags'])[:200]}" if v.get("flags") else ""))
        print(f"  {r['company'][:24]:26}{r['title'][:50]:52}{r['location'][:26]}\n      {url}")
        if a.commit:
            p = subprocess.run([sys.executable, str(HERE / "pipeline.py"), "add", "--company", r["company"],
                                "--role", r["title"], "--url", url, "--source", "dice", "--location", r["location"][:120],
                                "--jd", text[:60000], "--notes", note], capture_output=True, text=True)
            added += "DUPLICATE" not in (p.stdout + p.stderr)
    if a.commit:
        print(f"committed {added} of {len(keep)}")

    if a.linkedin:
        try:
            leads = asyncio.run(asyncio.wait_for(linkedin_leads(), 300))
            out = ROOT / "data" / "logs" / f"linkedin-leads-{date.today()}.json"
            out.write_text(json.dumps(leads, indent=1) + "\n")
            print(f"linkedin: 2 capped searches, leads in {out.relative_to(ROOT)}")
        except Exception as e:
            print(f"linkedin: skipped ({type(e).__name__}: {str(e)[:120]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
