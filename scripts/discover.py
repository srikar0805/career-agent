#!/usr/bin/env python3
"""Find open roles from public applicant tracking system APIs.

Greenhouse, Lever, and Ashby all publish every company's open roles as public
JSON, because that is how the company's own careers page renders. Reading those
endpoints is not scraping; it is the documented way to consume a job board.

This deliberately does not touch LinkedIn. LinkedIn job scraping violates their
terms and risks the account the user needs most, and the same roles are almost
always posted on the company's own ATS anyway.

Usage:
    python scripts/discover.py --query "machine learning" --limit 40
    python scripts/discover.py --query "ml engineer" --location remote
    python scripts/discover.py --companies stripe,anthropic --query engineer
    python scripts/discover.py --list-companies
    python scripts/discover.py --query ml --json
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests is required. Run: pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1)

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parent.parent
WATCHLIST = REPO / "profile" / "companies.yaml"
IDENTITY = REPO / "profile" / "identity.yaml"

TIMEOUT = 12
UA = {"User-Agent": "career-agent/1.0 (personal job search)"}

# Board tokens, which are the company's slug on that ATS. Seeded with companies
# that commonly hire for engineering and ML roles. The user's own watchlist in
# profile/companies.yaml is merged on top and takes precedence.
DEFAULT_BOARDS = {
    "greenhouse": [
        # Tech product companies
        "stripe", "databricks", "figma", "airbnb", "dropbox", "robinhood",
        "instacart", "doordash", "coinbase", "brex", "ramp", "plaid",
        "cloudflare", "digitalocean", "hashicorp", "gitlab", "elastic",
        "affirm", "flexport", "samsara", "benchling", "scaleai", "discord",
        "reddit", "grammarly", "asana", "duolingo", "wealthfront", "chime",
        "gusto", "rippling", "carta", "twilio", "airtable", "amplitude",
        "mixpanel", "segment", "fivetran", "dbtlabs", "starburst", "sigma",
        "hex", "atlan", "monteCarlo", "greatexpectations",
        # Health, insurance and life sciences. Heavy Power BI and SQL demand,
        # large analytics orgs, and routine OPT hiring.
        "oscarhealth", "devoted", "included", "cedar", "komodohealth",
        "flatiron", "tempus", "veeva", "olive", "healthgorilla", "zocdoc",
        "hingehealth", "carbonhealth", "spring", "lyra",
        # Finance, fintech and insurance
        "betterment", "marqeta", "modernTreasury", "unit", "mercury",
        "lemonade", "root", "hippo", "policygenius", "ethos",
        # Retail, logistics, industrial, energy
        "instacart", "gopuff", "wayfair", "chewy", "faire", "convoy",
        "projectcanary", "arcadia",
        # Data, analytics and BI vendors. Hire people who know their own tools.
        "sisense", "thoughtspot", "domo", "alteryx", "matillion",
    ],
    "lever": [
        "netflix", "spotify", "shopify", "quora", "mistral", "leetcode",
        "matchgroup", "cruise", "nubank", "sardine", "attentive",
        "klaviyo", "everlywell", "included", "kandji", "aledade",
        "clarifyhealth", "collectivehealth", "wellthy", "zipline",
    ],
    "ashby": [
        "openai", "ramp", "linear", "vercel", "replit", "runway", "cursor",
        "modal", "together", "deepgram", "clerk", "sourcegraph", "warp",
        "anthropic", "perplexity", "harvey", "sierra", "decagon", "baseten",
        "prefect", "dagster", "hightouch", "census", "secoda", "omni",
        "motherduck", "neon", "supabase", "turso", "resend", "knock",
    ],
}

# Sectors worth adding by hand in profile/companies.yaml, because their boards
# are not on a public ATS API and cannot be enumerated automatically:
#
#   Microsoft partners      The single best fit for a Fabric/Power BI profile.
#                           Avanade, Slalom, Hitachi Solutions, Neudesic,
#                           Quisitive, Catapult, BlueGranite, Data Bear.
#                           Many hire OPT candidates and none need clearance.
#   Big 4 and consulting    Deloitte, EY, PwC, KPMG, Accenture, Infosys, TCS,
#                           Cognizant, LTIMindtree, Capgemini. High volume,
#                           structured new-grad pipelines, sponsor routinely.
#   Universities            Mizzou itself, plus other Big 12 schools. Research
#                           and IT analyst roles, on-campus, CPT friendly.
#   Regional health systems MU Health Care, BJC, SSM, Mercy, Cerner/Oracle
#                           Health. Kansas City and St. Louis have real
#                           analytics demand and less competition than the
#                           coasts.


@dataclass
class Job:
    company: str
    role: str
    url: str
    source: str
    location: str = ""
    remote: str = ""
    department: str = ""
    posted_at: str = ""
    jd_text: str = ""
    score: float = 0.0
    matched: list[str] = field(default_factory=list)


def _get(url: str, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT, **kw)
        if r.status_code == 200:
            return r.json()
    except (requests.RequestException, ValueError):
        pass
    return None


def _strip_html(s: str) -> str:
    """HTML to plain text.

    Entities are unescaped BEFORE tags are stripped, not after. Greenhouse
    returns content that is HTML-escaped, so the markup arrives as `&lt;div&gt;`
    and a tag-strip pass sees no tags at all. Unescaping afterwards then turns
    that into literal "<div>" text, and every `div` and `span` ends up in the
    keyword extractor as if it were a job requirement.
    """
    s = html.unescape(s or "")
    # Some feeds are double-escaped. One more pass is cheap and idempotent.
    if "&lt;" in s or "&amp;" in s:
        s = html.unescape(s)

    s = re.sub(r"<(br|/p|/li|/div|/h\d)\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "- ", s, flags=re.I)
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)

    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


# --------------------------------------------------------------- providers

def from_greenhouse(token: str) -> list[Job]:
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    if not data or "jobs" not in data:
        return []
    out = []
    for j in data["jobs"]:
        out.append(Job(
            company=token,
            role=j.get("title", ""),
            url=j.get("absolute_url", ""),
            source="greenhouse",
            location=(j.get("location") or {}).get("name", ""),
            department=", ".join(d.get("name", "") for d in (j.get("departments") or [])),
            posted_at=(j.get("updated_at") or "")[:10],
            jd_text=_strip_html(j.get("content", "")),
        ))
    return out


def from_lever(token: str) -> list[Job]:
    data = _get(f"https://api.lever.co/v0/postings/{token}?mode=json")
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        cats = j.get("categories") or {}
        body = _strip_html(j.get("description", ""))
        for lst in (j.get("lists") or []):
            body += "\n\n" + _strip_html(lst.get("text", "")) + "\n" + _strip_html(lst.get("content", ""))
        out.append(Job(
            company=token,
            role=j.get("text", ""),
            url=j.get("hostedUrl", ""),
            source="lever",
            location=cats.get("location", "") or "",
            department=cats.get("team", "") or "",
            remote=cats.get("commitment", "") or "",
            posted_at=time.strftime("%Y-%m-%d", time.gmtime((j.get("createdAt") or 0) / 1000))
            if j.get("createdAt") else "",
            jd_text=body.strip(),
        ))
    return out


def from_ashby(token: str) -> list[Job]:
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    if not data or "jobs" not in data:
        return []
    out = []
    for j in data["jobs"]:
        out.append(Job(
            company=token,
            role=j.get("title", ""),
            url=j.get("jobUrl", "") or j.get("applyUrl", ""),
            source="ashby",
            location=j.get("location", "") or "",
            department=j.get("department", "") or j.get("team", "") or "",
            remote="remote" if j.get("isRemote") else "",
            posted_at=(j.get("publishedAt") or "")[:10],
            jd_text=_strip_html(j.get("descriptionPlain") or j.get("descriptionHtml") or ""),
        ))
    return out


def from_remoteok(query: str) -> list[Job]:
    data = _get("https://remoteok.com/api")
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        out.append(Job(
            company=j.get("company", ""),
            role=j.get("position", ""),
            url=j.get("url", ""),
            source="remoteok",
            location=j.get("location", "") or "remote",
            remote="remote",
            posted_at=(j.get("date") or "")[:10],
            jd_text=_strip_html(j.get("description", "")),
        ))
    return out


# ----------------------------------------------------------------- ranking

def load_watchlist() -> dict[str, list[str]]:
    boards = {k: list(v) for k, v in DEFAULT_BOARDS.items()}
    if yaml and WATCHLIST.exists():
        try:
            user = yaml.safe_load(WATCHLIST.read_text(encoding="utf-8")) or {}
            for provider, tokens in (user.get("boards") or {}).items():
                if provider in boards:
                    # User entries first, so they are fetched before any cap.
                    boards[provider] = list(dict.fromkeys(list(tokens) + boards[provider]))
                else:
                    boards[provider] = list(tokens)
        except yaml.YAMLError as e:
            print(f"warning: could not read {WATCHLIST}: {e}", file=sys.stderr)
    return boards


def load_identity() -> dict:
    if yaml and IDENTITY.exists():
        try:
            return yaml.safe_load(IDENTITY.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return {}
    return {}


def score(job: Job, terms: list[str], location: str | None) -> None:
    """Rank by how well the title and body match. Title matches dominate.

    A term in the job title means the role is about that thing. The same term
    buried in the benefits section means nothing, so body matches are worth a
    small fraction.
    """
    title = job.role.lower()
    body = job.jd_text.lower()
    matched = []
    total = 0.0

    for t in terms:
        t = t.lower().strip()
        if not t:
            continue
        if t in title:
            total += 10.0
            matched.append(t)
        elif t in body:
            total += 1.0
            matched.append(t)

    if location:
        loc = location.lower()
        blob = f"{job.location} {job.remote}".lower()
        if loc == "remote":
            if "remote" in blob or "anywhere" in blob:
                total += 6.0
            elif blob.strip():
                total -= 4.0
        elif loc in blob:
            total += 6.0

    # Freshness. A role posted this week is materially more likely to still be
    # open and unflooded than one from three months ago.
    if job.posted_at:
        try:
            age = (time.time() - time.mktime(time.strptime(job.posted_at, "%Y-%m-%d"))) / 86400
            if age < 7:
                total += 4.0
            elif age < 21:
                total += 2.0
            elif age > 90:
                total -= 3.0
        except ValueError:
            pass

    job.score = round(total, 1)
    job.matched = sorted(set(matched))


def filter_by_identity(jobs: list[Job], ident: dict) -> tuple[list[Job], list[str]]:
    """Drop roles the user cannot actually take, and say why."""
    notes: list[str] = []
    if not ident:
        return jobs, notes

    kept = []
    needs_sponsorship = bool(ident.get("needs_sponsorship"))
    dropped_citizenship = 0
    extra = [str(s).lower() for s in ident.get("exclude_if_posting_mentions", [])]

    for j in jobs:
        # Collapse ALL whitespace before matching. Job descriptions wrap, and a
        # disqualifier split across a line break is invisible to both a literal
        # search and a regex. "without the\n  need for visa support" is the same
        # requirement as the unwrapped form and must be caught identically.
        blob = " ".join(j.jd_text.lower().split())
        if needs_sponsorship and any(e in blob for e in extra if e):
            dropped_citizenship += 1
            continue

        if needs_sponsorship and re.search(
            # Citizenship and clearance
            r"(u\.?s\.? citizen(ship)? (is )?required|must be a u\.?s\.? citizen|"
            r"security clearance|ability to obtain a .{0,20}clearance|"
            # Employer states it will not sponsor
            r"not (able|be able) to sponsor|no sponsorship|unable to sponsor|"
            r"do(es)? not (provide |offer )?sponsor|will not sponsor|"
            # Requirement placed on the candidate. This phrasing is more common
            # than the negative form and reads as boilerplate, which is exactly
            # why it gets missed.
            r"without (the need for |requiring )?(visa support|sponsorship|"
            r"employer sponsorship|visa sponsorship)|"
            r"(work|employment) authorization without sponsorship|"
            r"not require sponsorship|no visa support)", blob
        ):
            dropped_citizenship += 1
            continue
        kept.append(j)

    if dropped_citizenship:
        notes.append(
            f"{dropped_citizenship} role(s) dropped: the posting states citizenship, "
            f"clearance, or no sponsorship, and profile/identity.yaml says sponsorship is needed."
        )
    return kept, notes


def collect(terms: list[str], location: str | None, companies: list[str] | None,
            limit: int, workers: int = 12) -> tuple[list[Job], list[str]]:
    boards = load_watchlist()
    tasks: list[tuple[str, str]] = []

    if companies:
        # Try every provider for each named company, since we do not know which
        # ATS they use and guessing wrong just returns nothing.
        for c in companies:
            for provider in ("greenhouse", "lever", "ashby"):
                tasks.append((provider, c.strip().lower()))
    else:
        for provider, tokens in boards.items():
            for t in tokens:
                tasks.append((provider, t))

    fetchers = {"greenhouse": from_greenhouse, "lever": from_lever, "ashby": from_ashby}
    jobs: list[Job] = []
    reached = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for provider, token in tasks:
            fn = fetchers.get(provider)
            if fn:
                futures[pool.submit(fn, token)] = (provider, token)

        for i, fut in enumerate(as_completed(futures), 1):
            provider, token = futures[fut]
            try:
                got = fut.result()
            except Exception:
                got = []
            if got:
                reached += 1
                jobs.extend(got)
            print(f"\r  fetched {i}/{len(futures)} boards, {len(jobs)} postings",
                  end="", file=sys.stderr)
    print(file=sys.stderr)

    if not companies:
        ro = from_remoteok(" ".join(terms))
        if ro:
            jobs.extend(ro)
            print(f"  remoteok: {len(ro)} postings", file=sys.stderr)

    notes = [f"{reached} of {len(futures)} company boards responded"]

    for j in jobs:
        score(j, terms, location)

    jobs = [j for j in jobs if j.score > 0]

    # Deduplicate. The same role appears on a company board and an aggregator.
    seen, unique = set(), []
    for j in sorted(jobs, key=lambda x: -x.score):
        key = (j.company.lower().strip(), re.sub(r"[^a-z0-9]", "", j.role.lower()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(j)

    unique, id_notes = filter_by_identity(unique, load_identity())
    notes += id_notes

    return unique[:limit], notes


def main() -> int:
    ap = argparse.ArgumentParser(description="Find open roles from public ATS APIs.")
    ap.add_argument("--query", help="space separated terms, e.g. 'machine learning engineer'")
    ap.add_argument("--location", help="'remote' or a city")
    ap.add_argument("--companies", help="comma separated board tokens to target directly")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--list-companies", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="also write results to this JSON path")
    args = ap.parse_args()

    if args.list_companies:
        boards = load_watchlist()
        for provider, tokens in boards.items():
            print(f"\n{provider} ({len(tokens)})")
            for t in tokens:
                print(f"  {t}")
        print(f"\nAdd your own in {WATCHLIST}:\n\nboards:\n  greenhouse:\n    - yourcompany\n")
        return 0

    if not args.query:
        print("--query is required. Example: --query 'machine learning engineer'", file=sys.stderr)
        return 2

    terms = [t for t in re.split(r"[\s,]+", args.query) if t]
    companies = args.companies.split(",") if args.companies else None

    jobs, notes = collect(terms, args.location, companies, args.limit)
    jobs = [j for j in jobs if j.score >= args.min_score]

    payload = {"query": args.query, "location": args.location,
               "count": len(jobs), "notes": notes,
               "jobs": [asdict(j) for j in jobs]}

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {p}", file=sys.stderr)

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    for n in notes:
        print(f"note: {n}", file=sys.stderr)

    if not jobs:
        print("\nNothing matched. Try broader terms, or add companies to "
              f"{WATCHLIST} and re-run.")
        return 0

    print(f"\n{len(jobs)} roles\n")
    print(f"{'SCORE':<7}{'COMPANY':<20}{'ROLE':<44}{'LOCATION':<24}SRC")
    print("-" * 112)
    for j in jobs:
        print(f"{j.score:<7.1f}{j.company[:19]:<20}{j.role[:43]:<44}"
              f"{(j.location or '-')[:23]:<24}{j.source}")

    print("\nTop matches with links:")
    for j in jobs[:8]:
        print(f"\n  {j.company} / {j.role}")
        print(f"    {j.url}")
        if j.matched:
            print(f"    matched: {', '.join(j.matched)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
