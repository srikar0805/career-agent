#!/usr/bin/env python3
"""Sweep every applicant-tracking board the pipeline has ever seen, not just a hand list.

WHY THIS EXISTS. On 2026-09-16 Srikar asked for the pipeline to work like Tsenta,
which watches 50,000+ career pages across 19 applicant-tracking systems. Ours
swept 54 hand-verified boards (30 Greenhouse, 22 Ashby, 2 Lever) and had no
Workday, SmartRecruiters or Oracle discovery at all, even though those are where
most Fortune 500 employers post.

The fix is not another hand list. Every posting URL that reaches the pipeline
names its board: `ntst.wd1.myworkdayjobs.com/Careers`, `jobs.lever.co/cologix`,
`hdjq.fa.us2.oraclecloud.com/.../sites/CX_1`. Harvesting those on 2026-09-16
found 121 boards the sweeper had never looked at, which took coverage from 54 to
roughly 160, and the registry grows on its own as new URLs arrive every day.

SUBMISSION IS NOT PART OF THIS. Srikar chose staged submission on 2026-09-16:
the pipeline finds, screens and prepares, and he presses submit. Nothing here
applies to anything.

    discover_ats.py harvest              add boards named in pipeline URLs, verify each
    discover_ats.py sweep                dry run: what would qualify
    discover_ats.py sweep --commit       add qualified postings as 'discovered'
    discover_ats.py list                 registry summary

Endpoints, all measured 2026-09-16 rather than assumed:

    greenhouse       GET  boards-api.greenhouse.io/v1/boards/{tok}/jobs
    lever            GET  api.lever.co/v0/postings/{tok}?mode=json
    ashby            GET  api.ashbyhq.com/posting-api/job-board/{tok}   (token is case-sensitive)
    workday          POST {tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
                     GET  .../wday/cxs/{tenant}/{site}{externalPath}     (detail: description, country, timeType)
    smartrecruiters  GET  api.smartrecruiters.com/v1/companies/{co}/postings?country=us
    oracle           GET  {host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
                          ?expand=requisitionList   (WITHOUT expand the list key is absent)
    icims            no public JSON API. Harvested for visibility, never swept.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from discover import SENIOR_MARKERS                                      # noqa: E402
from discover_data import BOARDS, DATA_TITLE, NON_US_CITY, NOT_HIS, fetch_board  # noqa: E402
from screen_job import NON_US_LOCATION, NOT_FULL_TIME, fetch_jd, screen  # noqa: E402

REGISTRY = ROOT / "data" / "boards.json"
SEEN = ROOT / "data" / "ats_seen.json"     # postings already screened and dropped
DB = ROOT / "data" / "pipeline.db"
UA = {"User-Agent": "Mozilla/5.0 (career-agent ats sweep)",
      "Accept": "application/json", "Content-Type": "application/json"}

# Software titles, listed explicitly. A bare "engineer" would pull in mechanical,
# electrical, field-service and sales engineers by the hundred.
SWE_TITLE = re.compile(
    r"\b(software\s+(engineer|developer|development\s+engineer)|application\s+developer"
    r"|programmer\s+analyst|full[\s-]?stack|back[\s-]?end\s+(engineer|developer)"
    r"|associate\s+(software\s+)?engineer|developer\s+(i|1)\b"
    r"|machine\s+learning|\bml\s+engineer|ai\s+engineer|applied\s+(ai|ml|scientist)"
    r"|forward\s+deployed|site\s+reliability|cloud\s+engineer|devops\s+engineer"
    r"|platform\s+engineer)\b", re.I)

# "New Grad", "Early Career" and "Engineer I" are LEVELS, not job families. On the
# second dry run they let Electrical Engineer, Additive Engineer and a Power &
# Water Project Engineer through. Level now only raises a candidate's rank.
OTHER_ENGINEERING = re.compile(
    r"\b(electrical|mechanical|additive|manufacturing|civil|chemical|structural"
    r"|hardware|mechatronic|aerospace|process|project|field|facilities|hvac|rf|analog"
    r"|materials|packaging|test\s+technician|quality\s+(control|inspector))\b", re.I)

# Entry-level signal. A generic "Software Engineer" at Plaid, Ramp or Brex with no
# level is usually mid-level, and his software applications score 5 to 10%
# realistic, so without a level word only DATA titles are kept. --include-unleveled
# turns this off.
LEVEL = re.compile(r"new\s+grad|20(26|27)|early\s+career|graduate|entry|associate|junior"
                   r"|rotational|college\s+grad|university|\b(i|1)\b", re.I)

NON_US_TITLE = re.compile(
    r"\((uk|u\.k\.|emea|apac|latam|canada|india|europe|eu|germany|france|ireland|australia)\)"
    r"|\b(united\s+kingdom|milton\s+keynes|belfast|glasgow|leeds|birmingham,\s*uk)\b", re.I)
# Country names, because city lists never end: the third dry run let Capco through
# at "Malaysia - Kuala Lumpur" and "Czech Republic - Brno". F-1 status authorises
# work in the United States only.
NON_US_COUNTRY = re.compile(
    r"\b(canada|mexico|brazil|argentina|chile|colombia|peru|costa\s+rica|united\s+kingdom|england"
    r"|scotland|ireland|france|germany|netherlands|belgium|switzerland|austria|spain|portugal"
    r"|italy|poland|czech(ia|\s+republic)?|slovakia|hungary|romania|bulgaria|serbia|croatia"
    r"|greece|turkey|ukraine|sweden|norway|denmark|finland|estonia|latvia|lithuania|israel"
    r"|uae|united\s+arab\s+emirates|saudi\s+arabia|qatar|egypt|south\s+africa|nigeria|kenya"
    r"|india|pakistan|sri\s+lanka|bangladesh|malaysia|singapore|indonesia|philippines|vietnam"
    r"|thailand|china|hong\s+kong|taiwan|japan|korea|australia|new\s+zealand)\b", re.I)
# A graduation window in the title. He graduates May 2027 and can start June 2027.
# The first committed sweep let three through: Applied Intuition "New Grad
# (December 2026)" and "(December 2027)", Notion "New Grad (Dec 2026)". A December
# 2026 cohort starts while he is still enrolled; a December 2027 cohort starts
# after his OPT start window (60 days after the program ends) has closed.
GRAD_WINDOW = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?"
    r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|spring|summer|fall|autumn|winter)\s*,?\s*'?(?:20)?(2[4-9])\b", re.I)
GRAD_WINDOW_OK = {("may", "27"), ("june", "27"), ("jun", "27"), ("spring", "27"), ("summer", "27")}
BARE_WRONG_YEAR = re.compile(r"(grad\w*|class\s+of|cohort)\D{0,12}20(2[4-6]|2[89])\b"
                             r"|\b20(2[4-6]|2[89])\D{0,12}(new\s+grad|grad\w*|cohort)", re.I)


def grad_window_ok(title: str) -> bool:
    for mon, yr in GRAD_WINDOW.findall(title):
        if (mon.lower(), yr) not in GRAD_WINDOW_OK:
            return False
    return not BARE_WRONG_YEAR.search(title)


LANGUAGE_ROLE = re.compile(
    r"\b(portuguese|spanish|french|german|japanese|korean|mandarin|italian|dutch|arabic)\b"
    r"|\bspeaking\b|bilingual", re.I)

# Search words for boards that make us ask rather than list everything.
KEYWORDS = ["software", "data", "analyst", "machine learning", "graduate"]

URL_PATTERNS = [
    ("greenhouse", re.compile(r"(?:job-boards|boards)\.greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([\w.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)", re.I)),
    ("workday", re.compile(r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", re.I)),
    ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com/([\w-]+)", re.I)),
    ("oracle", re.compile(r"https?://([\w-]+\.fa\.[\w-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z]{2}/sites/([\w-]+)", re.I)),
    ("icims", re.compile(r"https?://([\w-]+)\.icims\.com", re.I)),
]
NOT_BOARDS = {"embed", "jobs", "v1", "boards", "api", "careers", "job_app"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(url: str, body: dict | None = None, timeout: int = 30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ---------------------------------------------------------------- registry

def board_id(b: dict) -> str:
    if b["ats"] == "workday":
        return f"workday:{b['tenant']}.{b['dc']}/{b['site']}"
    if b["ats"] == "oracle":
        return f"oracle:{b['host']}/{b['site']}"
    return f"{b['ats']}:{b['token']}"


def load_registry() -> dict[str, dict]:
    if REGISTRY.exists():
        return {board_id(b): b for b in json.loads(REGISTRY.read_text())}
    return {}


def save_registry(reg: dict[str, dict]) -> None:
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(reg.values(), key=board_id), indent=1) + "\n")
    tmp.replace(REGISTRY)


def parse_board(url: str) -> dict | None:
    for ats, pat in URL_PATTERNS:
        m = pat.search(url or "")
        if not m:
            continue
        g = m.groups()
        if ats == "workday":
            return {"ats": ats, "tenant": g[0].lower(), "dc": g[1].lower(), "site": g[2]}
        if ats == "oracle":
            return {"ats": ats, "host": g[0].lower(), "site": g[1]}
        tok = g[0] if ats == "ashby" else g[0].lower()   # Ashby tokens are case-sensitive
        if tok.lower() in NOT_BOARDS:
            return None
        return {"ats": ats, "token": tok}
    return None


def verify(b: dict) -> tuple[bool, str]:
    """A board that does not resolve produces a silent empty sweep forever. Probe first."""
    try:
        a = b["ats"]
        if a == "greenhouse":
            d = _json(f"https://boards-api.greenhouse.io/v1/boards/{b['token']}/jobs")
            return "jobs" in d, f"{len(d.get('jobs', []))} jobs"
        if a == "lever":
            d = _json(f"https://api.lever.co/v0/postings/{b['token']}?mode=json")
            return isinstance(d, list), f"{len(d)} jobs"
        if a == "ashby":
            d = _json(f"https://api.ashbyhq.com/posting-api/job-board/{b['token']}")
            return "jobs" in d, f"{len(d.get('jobs', []))} jobs"
        if a == "workday":
            d = _json(f"https://{b['tenant']}.{b['dc']}.myworkdayjobs.com/wday/cxs/{b['tenant']}/{b['site']}/jobs",
                      {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
            return "total" in d, f"{d.get('total')} jobs"
        if a == "smartrecruiters":
            d = _json(f"https://api.smartrecruiters.com/v1/companies/{b['token']}/postings?limit=1")
            return "totalFound" in d, f"{d.get('totalFound')} jobs"
        if a == "oracle":
            d = _json(oracle_list_url(b, "", 1))
            it = (d.get("items") or [{}])[0]
            return "requisitionList" in it, f"{it.get('TotalJobsCount')} jobs"
        return False, "no public API"
    except Exception as e:
        return False, f"{type(e).__name__}"


def harvest(reg: dict[str, dict], workers: int = 10) -> None:
    for ats, tok in BOARDS:                     # the 54 hand-verified boards seed it
        b = {"ats": ats, "token": tok}
        reg.setdefault(board_id(b), {**b, "source": "seed", "verified": True, "verified_at": now()})

    con = sqlite3.connect(DB)
    urls = [u for (u,) in con.execute("SELECT url FROM applications WHERE url IS NOT NULL")]
    con.close()
    new = []
    for u in urls:
        b = parse_board(u)
        if b and board_id(b) not in reg:
            reg[board_id(b)] = {**b, "source": "harvest", "verified": None,
                                "harvested_from": u[:160], "harvested_at": now()}
            new.append(board_id(b))
    print(f"harvest: {len(urls)} pipeline URLs, {len(new)} new board(s)")

    todo = [k for k, b in reg.items() if b.get("verified") is None]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, (ok, why) in zip(todo, ex.map(lambda k: verify(reg[k]), todo)):
            reg[k].update(verified=ok, verified_at=now(), verify_note=why)
            print(f"  {'ok  ' if ok else 'FAIL'} {k:58} {why}")
    save_registry(reg)


# ---------------------------------------------------------------- listing

def oracle_list_url(b: dict, keyword: str, limit: int) -> str:
    finder = f'findReqs;siteNumber={b["site"]},limit={limit},sortBy=POSTING_DATES_DESC'
    if keyword:
        finder += f',keyword="{keyword}"'
    return (f"https://{b['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true&expand=requisitionList&finder=" + urllib.parse.quote(finder, safe=";=,"))


def list_board(b: dict) -> list[dict]:
    a, rows = b["ats"], []
    try:
        if a in ("greenhouse", "lever", "ashby"):
            for r in fetch_board((a, b["token"])):
                rows.append({**r, "ats": a, "board": board_id(b)})
        elif a == "workday":
            base = f"https://{b['tenant']}.{b['dc']}.myworkdayjobs.com"
            seen = set()
            for kw in KEYWORDS:
                d = _json(f"{base}/wday/cxs/{b['tenant']}/{b['site']}/jobs",
                          {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": kw})
                for j in d.get("jobPostings", []):
                    p = j.get("externalPath", "")
                    if p in seen:
                        continue
                    seen.add(p)
                    rows.append({"ats": a, "board": board_id(b), "company": b["tenant"],
                                 "title": j.get("title", ""), "location": j.get("locationsText", ""),
                                 "url": f"{base}/{b['site']}{p}", "ref": p})
        elif a == "smartrecruiters":
            d = _json(f"https://api.smartrecruiters.com/v1/companies/{b['token']}/postings?country=us&limit=100")
            for j in d.get("content", []):
                loc = j.get("location") or {}
                rows.append({"ats": a, "board": board_id(b),
                             "company": (j.get("company") or {}).get("name") or b["token"],
                             "title": j.get("name", ""), "location": loc.get("fullLocation", ""),
                             "url": f"https://jobs.smartrecruiters.com/{b['token']}/{j.get('id')}",
                             "ref": j.get("id"),
                             "employment": (j.get("typeOfEmployment") or {}).get("label", "")})
        elif a == "oracle":
            seen = set()
            for kw in KEYWORDS:
                d = _json(oracle_list_url(b, kw, 50))
                for j in ((d.get("items") or [{}])[0].get("requisitionList") or []):
                    if j["Id"] in seen or (j.get("PrimaryLocationCountry") or "US") != "US":
                        continue
                    seen.add(j["Id"])
                    rows.append({"ats": a, "board": board_id(b), "company": b["host"].split(".")[0],
                                 "title": j.get("Title", ""), "location": j.get("PrimaryLocation", ""),
                                 "url": f"https://{b['host']}/hcmUI/CandidateExperience/en/sites/{b['site']}/job/{j['Id']}",
                                 "ref": j["Id"]})
    except Exception as e:
        print(f"  {board_id(b)}: {type(e).__name__}", file=sys.stderr)
    return rows


def title_ok(r: dict) -> tuple[bool, str]:
    t = r.get("title") or ""
    if not (DATA_TITLE.search(t) or SWE_TITLE.search(t)):
        return False, "not his job family"
    if NOT_HIS.search(t):
        return False, "wrong function"
    if OTHER_ENGINEERING.search(t):
        return False, "other engineering discipline"
    # "Full Stack Engineer (UK)" at Milton Keynes passed the first dry run: the
    # country was only in the title and the town is in no city list.
    loc_text = r.get("location") or ""
    if (NON_US_TITLE.search(t) or NON_US_TITLE.search(loc_text)
            or (NON_US_COUNTRY.search(loc_text) and not re.search(r"\b(us|usa|united\s+states)\b", loc_text, re.I))):
        return False, "outside the US"
    if LANGUAGE_ROLE.search(t):
        return False, "requires another language"
    if not grad_window_ok(t):
        return False, "graduation window is not May 2027"
    tl = f" {t.lower()} "
    for m in SENIOR_MARKERS:
        if m in tl:
            return False, f"seniority: {m.strip()}"
    if NOT_FULL_TIME.search(t) or re.search(r"part[\s-]?time|contract|temporary", r.get("employment", ""), re.I):
        return False, "not full-time"
    loc = r.get("location") or ""
    if loc and (NON_US_LOCATION.search(loc) or NON_US_CITY.search(loc)):
        return False, "outside the US"
    return True, ""


# ---------------------------------------------------------------- employer names

def _title_of(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=20) as r:
        m = re.search(r"<title[^>]*>([^<]+)</title>", r.read(200_000).decode("utf-8", "replace"), re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def employer_name(reg: dict[str, dict], bid: str, fallback: str) -> str:
    """The employer's real name for a board, cached on the registry entry.

    The first committed sweep (2026-09-16) stored 22 of 26 rows under their board
    token: "applied" for Applied Intuition, "idmeuniversityrecruiting" for ID.me,
    "c3iot" for C3.ai. That breaks the desk, the (company, title) dedupe against
    rows he entered by hand, and prefill.py's "have you applied here before".
    Order: a name he already used in the pipeline for this board, then the
    employer's own board name or page title, then the token.
    """
    b = reg[bid]
    if b.get("name"):
        return b["name"]
    name = ""
    con = sqlite3.connect(DB)
    for u, c, src in con.execute("SELECT url, company, source FROM applications WHERE url IS NOT NULL"):
        pb = parse_board(u)
        if (pb and board_id(pb) == bid and not (src or "").startswith("ats:")
                and _norm(c) != _norm(b.get("token") or b.get("tenant") or "")):   # older sweeps stored tokens too
            name = c
            break
    con.close()
    try:
        if not name and b["ats"] == "greenhouse":
            name = _json(f"https://boards-api.greenhouse.io/v1/boards/{b['token']}").get("name", "")
        elif not name and b["ats"] == "ashby":
            name = _title_of(f"https://jobs.ashbyhq.com/{b['token']}")
        elif not name and b["ats"] == "lever":
            name = _title_of(f"https://jobs.lever.co/{b['token']}")
    except Exception:
        name = ""
    name = re.sub(r"^(jobs|careers)\s+at\s+|\s+(jobs|careers|job\s+board)$"
                  r"|\s+(university|campus|early\s+career)s?(\s+recruiting)?$", "", name.strip(), flags=re.I)
    if not name or name.lower() in ("jobs", "careers", "ashby", "lever"):
        return fallback
    b["name"] = name
    return name


# ---------------------------------------------------------------- reading

def read_posting(r: dict, reg: dict[str, dict]) -> tuple[str, str]:
    """Return (text, drop_reason). Uses each ATS's detail endpoint where fetch_jd has none."""
    b = reg[r["board"]]
    try:
        if r["ats"] == "workday":
            d = _json(f"https://{b['tenant']}.{b['dc']}.myworkdayjobs.com/wday/cxs/{b['tenant']}/{b['site']}{r['ref']}")
            info = d.get("jobPostingInfo", {})
            country = (info.get("country") or {}).get("descriptor", "")
            if country and "united states" not in country.lower():
                return "", f"outside the US: {country}"
            if info.get("timeType") and "full" not in info["timeType"].lower():
                return "", f"not full-time: {info['timeType']}"
            org = (d.get("hiringOrganization") or {}).get("name")
            if org:
                r["company"] = re.sub(r"^\d+\s+", "", org)
            return re.sub(r"<[^>]+>", " ", info.get("jobDescription", "")), ""
        if r["ats"] == "smartrecruiters":
            d = _json(f"https://api.smartrecruiters.com/v1/companies/{b['token']}/postings/{r['ref']}")
            secs = (d.get("jobAd") or {}).get("sections") or {}
            return re.sub(r"<[^>]+>", " ", " ".join((v or {}).get("text", "") for v in secs.values())), ""
        if r["ats"] == "oracle":
            fd = f'ById;Id="{r["ref"]}",siteNumber={b["site"]}'
            d = _json(f"https://{b['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
                      f"?expand=all&onlyData=true&finder=" + urllib.parse.quote(fd, safe=";=,"))
            x = (d.get("items") or [{}])[0]
            return re.sub(r"<[^>]+>", " ", (x.get("ExternalDescriptionStr") or "") + " " +
                          (x.get("ExternalQualificationsStr") or "")), ""
        return fetch_jd(r["url"]), ""
    except Exception as e:
        return f"__FETCH_FAILED__ {e}", ""


def posting_key(url: str) -> str:
    """Identify a posting by its ATS id, never by its raw URL.

    The same Sierra posting is stored in the pipeline as
    `.../149f368c-.../application?embed=true` and listed by the board as
    `.../149f368c-...`. Comparing URLs let it back in as a duplicate on the
    first dry run, and AiPrise #216 the same way.
    """
    u = url or ""
    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", u, re.I)
    if m:                                             # ashby, lever
        return m.group(0).lower()
    for pat in (r"greenhouse\.io/[^?#]*/jobs/(\d+)", r"[?&]gh_jid=(\d+)",
                r"myworkdayjobs\.com/.*?_(R?-?\d[\w-]*)(?:[/?#]|$)",
                r"smartrecruiters\.com/[\w-]+/(\d+)", r"/sites/[\w-]+/job/(\d+)",
                r"icims\.com/jobs/(\d+)"):
        m = re.search(pat, u, re.I)
        if m:
            return m.group(1).lower()
    return u.split("?")[0].rstrip("/").lower()


# Affirmative evidence ONLY. Notes are full of negative mentions ("no citizenship
# or clearance language in the posting") that must never block a board.
EMPLOYER_SAID_NO = re.compile(
    r"unable\s+to\s+(offer|provide)\s+(visa\s+)?sponsorship"
    r"|will\s+not\s+(provide\s+|offer\s+)?(visa\s+)?sponsor"
    r"|not\s+eligible\s+for\s+f-?1"
    r"|exit\s+3,\s+BLOCKER"
    r"|requires?\s+work\s+authoriz\w*\s+without\s+(visa\s+)?sponsorship"   # row #60, National Software Management
    r"|u\.?\s?s\.?\s+citizens?\s+only"
    r"|gates?\s+on\s+u\.?\s?s\.?\s+person", re.I)


def _norm(x: str) -> str:
    return re.sub(r"\W", "", (x or "").lower())


def pipeline_keys():
    """Posting ids, (company, title) and (board, title) pairs, plus boards to skip.

    A board is blocked when a pipeline row on it carries AFFIRMATIVE evidence the
    employer will not hire him: Emerson said it will not sponsor (row #248, Oracle
    board hdjq), CHAOS Industries gates its form on U.S. Person status (row #276).
    On the second dry run both came straight back as qualified, because the sweep
    knew nothing the pipeline had already learned. Keyed by BOARD, not company
    name, because the board says `hdjq` and the pipeline says `Emerson`.
    """
    con = sqlite3.connect(DB)
    keys, pairs, blocked = set(), set(), {}
    evidence = {}
    for aid, summ in con.execute("SELECT application_id, summary FROM interactions"):
        evidence[aid] = evidence.get(aid, "") + " " + (summ or "")
    for aid, u, c, t, notes in con.execute("SELECT id, url, company, role, notes FROM applications"):
        b = parse_board(u or "")
        if u:
            keys.add(posting_key(u))
        pairs.add((_norm(c), _norm(t)))
        if b:
            pairs.add((board_id(b), _norm(t)))
            m = EMPLOYER_SAID_NO.search(f"{notes or ''} {evidence.get(aid, '')}")
            if m:
                blocked.setdefault(board_id(b), f"#{aid} {c}: {m.group(0)}")
    con.close()
    return keys, pairs, blocked


def sweep(reg: dict[str, dict], commit: bool, limit: int, workers: int,
          include_unleveled: bool = False) -> int:
    boards = [b for b in reg.values() if b.get("verified") and b["ats"] != "icims"]
    counts = {}
    for b in boards:
        counts[b["ats"]] = counts.get(b["ats"], 0) + 1
    mix = ", ".join(f"{a} {n}" for a, n in sorted(counts.items()))
    print(f"sweeping {len(boards)} verified boards ({mix})", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        per_board = list(ex.map(list_board, boards))
    stamp = now()
    for b, rows in zip(boards, per_board):
        reg[board_id(b)].update(last_swept=stamp, last_listed=len(rows))
    rows = [r for batch in per_board for r in batch]
    print(f"  {len(rows)} postings listed", file=sys.stderr)

    urls, pairs, blocked = pipeline_keys()
    if blocked:
        print(f"  {len(blocked)} board(s) blocked on the pipeline's own evidence:", file=sys.stderr)
        for k, why in sorted(blocked.items()):
            print(f"    {k:52} {why[:70]}", file=sys.stderr)
    seen = json.loads(SEEN.read_text()) if SEEN.exists() else {}
    cand, drops = [], {}
    for r in rows:
        ok, why = title_ok(r)
        key = posting_key(r["url"])
        if ok and not include_unleveled and not LEVEL.search(r["title"]) and not DATA_TITLE.search(r["title"]):
            ok, why = False, "generic software title, no entry-level signal"
        if ok and r["board"] in blocked:
            ok, why = False, "employer already said no"
        if ok and (key in urls or (_norm(r["company"]), _norm(r["title"])) in pairs
                   or (r["board"], _norm(r["title"])) in pairs):
            ok, why = False, "already in the pipeline"
        if ok and key in seen:
            ok, why = False, "screened and dropped before"
        if not ok:
            drops[why] = drops.get(why, 0) + 1
            continue
        cand.append(r)
    print(f"  {len(cand)} new and in his job families", file=sys.stderr)
    for k, v in sorted(drops.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    dropped {v:5}  {k}", file=sys.stderr)

    # On the first dry run the read budget went to the first 40 candidates in
    # board order: all 21 qualifiers were Ashby, Sierra alone took 13, and no
    # Workday, SmartRecruiters or Oracle posting was ever read. So rank each
    # board's candidates, then take one from every board per round.
    def score(r: dict) -> int:
        t = r["title"]
        s = 0
        if LEVEL.search(t):
            s += 5
        if DATA_TITLE.search(t):
            s += 3                    # his data fit scores run about twenty points higher
        return s
    by_board: dict[str, list[dict]] = {}
    for r in sorted(cand, key=score, reverse=True):
        by_board.setdefault(r["board"], []).append(r)
    ordered, rnd = [], 0
    while len(ordered) < limit and any(len(v) > rnd for v in by_board.values()):
        tier = sorted((v[rnd] for v in by_board.values() if len(v) > rnd), key=score, reverse=True)
        ordered += tier[: limit - len(ordered)]
        rnd += 1
        if rnd >= 3:                   # at most three reads per board per run
            break

    qualified = []
    for r in ordered:
        text, drop = read_posting(r, reg)
        key = posting_key(r["url"])
        if drop:
            seen[key] = {"at": stamp, "why": drop}
            continue
        v = screen(text, r["company"])
        if v["verdict"] == "PASS":
            qualified.append((r, v, text))
        elif v["verdict"] != "UNKNOWN":           # an unreadable posting is retried next run
            seen[key] = {"at": stamp, "why": (v["blockers"] or ["dropped"])[0][:120]}
    SEEN.write_text(json.dumps(seen, indent=1) + "\n")
    for b in boards:
        reg[board_id(b)]["last_qualified"] = sum(1 for r, _, _ in qualified if r["board"] == board_id(b))
    save_registry(reg)

    print(f"\nQUALIFIED {len(qualified)}")
    for r, v, _ in qualified:
        f = f"   flags: {'; '.join(v['flags'])[:90]}" if v.get("flags") else ""
        print(f"  [{r['ats']:15}] {r['company'][:20]:22}{r['title'][:48]:50}{(r['location'] or '')[:24]}")
        print(f"      {r['url']}{f}")
    if not commit:
        print("\ndry run. add --commit to put these in the pipeline as 'discovered'.")
        return 0
    added = 0
    for r, v, text in qualified:
        if r["ats"] in ("greenhouse", "lever", "ashby", "oracle"):
            r["company"] = employer_name(reg, r["board"], r["company"])
        p = subprocess.run([sys.executable, str(HERE / "pipeline.py"), "add",
                            "--company", r["company"], "--role", r["title"], "--url", r["url"],
                            "--source", f"ats:{r['ats']}", "--location", (r["location"] or "")[:120],
                            "--jd", text[:60000],
                            "--notes", f"Found by discover_ats.py sweep {stamp[:10]} on board {r['board']}."
                                       + (f" Screen flags: {'; '.join(v['flags'])[:300]}" if v.get("flags") else "")],
                           capture_output=True, text=True)
        added += "DUPLICATE" not in p.stdout
    save_registry(reg)   # employer names resolved above are cached for the next run
    print(f"\ncommitted {added} of {len(qualified)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["harvest", "sweep", "list"])
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int, default=40, help="max postings read in full per run")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--include-unleveled", action="store_true",
                    help="also read generic software titles that carry no entry-level signal")
    a = ap.parse_args()
    reg = load_registry()
    if a.cmd == "harvest":
        harvest(reg, a.workers)
    elif a.cmd == "sweep":
        if not reg:
            harvest(reg, a.workers)
        return sweep(reg, a.commit, a.limit, a.workers, a.include_unleveled)
    else:
        from collections import Counter
        c = Counter((b["ats"], b.get("verified")) for b in reg.values())
        for (ats, ok), n in sorted(c.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
            print(f"  {ats:16} verified={str(ok):5}  {n}")
        print(f"  total {len(reg)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
