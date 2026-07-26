#!/usr/bin/env python3
"""Import a LinkedIn data export.

LinkedIn has no API for reading your own profile, so the official archive is
the only complete, legitimate source. Get it at:

    LinkedIn > Settings > Data Privacy > Get a copy of your data
    > "Download larger data archive", request, wait ~10 minutes for the email.

Drop the ZIP (or the unzipped folder) anywhere under data/raw/ and run this.

Two things in the archive matter more than the profile text:

  Connections.csv   Your warm-intro graph. Knowing you already have a first
                    degree connection at a company changes the entire outreach
                    strategy for that company, from cold pitch to asking a
                    person you know. This is the single highest-value file.

  Endorsement_Received_Info.csv
                    Which skills other people vouched for. Independent
                    confirmation of what to lead with, as opposed to what you
                    think your strengths are.

Usage:
    python connectors/linkedin.py                    # auto-find under data/raw
    python connectors/linkedin.py path/to/export.zip
    python connectors/linkedin.py --json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "raw"
OUT = RAW / "linkedin.json"

# Filename in the archive -> key in our output. LinkedIn has renamed several of
# these over the years, so matching is done on a normalized stem, not exactly.
WANTED = {
    "profile": "profile",
    "positions": "positions",
    "education": "education",
    "skills": "skills",
    "endorsement_received_info": "endorsements",
    "projects": "projects",
    "certifications": "certifications",
    "publications": "publications",
    "honors": "honors",
    "languages": "languages",
    "connections": "connections",
    "recommendations_received": "recommendations_received",
    "recommendations_given": "recommendations_given",
    "email_addresses": "emails",
    "phone_numbers": "phones",
    "job_applications": "job_applications",
    "saved_jobs": "saved_jobs",
    "company_follows": "company_follows",
}

# Files that contain message bodies or contact details we have no reason to
# retain. Skipped outright rather than read and discarded.
SKIP = {"messages", "invitations", "ad_targeting", "ads_clicked", "searches",
        "security_challenge", "logins", "account_status_history", "rich_media",
        "member_follows", "votes", "reactions", "comments", "shares"}


def _norm(stem: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")


def _read_csv(data: bytes, source: str) -> list[dict]:
    """Parse a LinkedIn CSV.

    LinkedIn prefixes several files (Connections.csv most notably) with a
    freeform "Notes:" preamble before the real header row. csv.DictReader on
    the raw bytes silently produces garbage. Find the header by looking for the
    first line that parses into multiple non-empty, plausible column names.
    """
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()

    header_idx = 0
    for i, line in enumerate(lines[:12]):
        if not line.strip():
            continue
        try:
            cols = next(csv.reader([line]))
        except (csv.Error, StopIteration):
            continue
        named = [c for c in cols if c.strip()]
        if len(named) >= 2 and all(len(c) < 60 for c in named):
            # A preamble line is prose: one long cell, or starts with "Notes".
            if line.lower().lstrip().startswith("note"):
                continue
            header_idx = i
            break

    body = "\n".join(lines[header_idx:])
    try:
        rows = [dict(r) for r in csv.DictReader(io.StringIO(body))]
    except csv.Error as e:
        print(f"  could not parse {source}: {e}", file=sys.stderr)
        return []

    cleaned = []
    for r in rows:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items() if k}
        if any(r.values()):
            cleaned.append(r)
    return cleaned


def _iter_files(src: Path):
    """Yield (normalized_stem, bytes) from a zip or a directory."""
    if src.is_file() and src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as z:
            for info in z.infolist():
                if info.is_dir() or not info.filename.lower().endswith(".csv"):
                    continue
                stem = _norm(Path(info.filename).stem)
                yield stem, z.read(info)
    elif src.is_dir():
        for p in sorted(src.rglob("*.csv")):
            yield _norm(p.stem), p.read_bytes()


def find_export(root: Path = RAW) -> Path | None:
    """Locate a LinkedIn export under data/raw without being told where."""
    if not root.exists():
        return None

    candidates: list[tuple[int, Path]] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".zip":
            name = p.name.lower()
            score = 10 if any(k in name for k in ("linkedin", "basic", "complete")) else 1
            try:
                with zipfile.ZipFile(p) as z:
                    names = {_norm(Path(n).stem) for n in z.namelist()}
                if "positions" in names or "connections" in names:
                    score += 50
            except zipfile.BadZipFile:
                continue
            candidates.append((score, p))
        elif p.is_dir() and (p / "Positions.csv").exists():
            candidates.append((60, p))

    if not candidates:
        return None
    return max(candidates, key=lambda t: t[0])[1]


def parse_date(s: str) -> str | None:
    """LinkedIn writes dates as 'Jan 2024', 'Jan 1, 2024', or ''."""
    s = (s or "").strip()
    if not s:
        return None
    month_only = ("%b %Y", "%B %Y")
    # "%d %b %Y" is what Connections.csv uses ("15 Mar 2024"), which differs
    # from the "Jan 2024" format Positions.csv uses. Both appear in one export.
    for fmt in (*month_only, "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
                "%Y-%m-%d", "%m/%d/%Y", "%Y"):
        try:
            d = datetime.strptime(s, fmt)
            return d.strftime("%Y-%m") if fmt in month_only else d.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def build(src: Path) -> dict:
    tables: dict[str, list[dict]] = {}
    seen: list[str] = []

    for stem, data in _iter_files(src):
        seen.append(stem)
        if stem in SKIP:
            continue
        key = WANTED.get(stem)
        if key is None:
            # Tolerate LinkedIn's renames: "Positions_1.csv", "Skills (1).csv"
            base = re.sub(r"_\d+$", "", stem)
            key = WANTED.get(base)
        if key:
            rows = _read_csv(data, stem)
            if rows:
                tables.setdefault(key, []).extend(rows)

    out: dict = {
        "source": str(src),
        "imported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "files_seen": sorted(set(seen)),
        "tables_imported": sorted(tables.keys()),
    }

    # ---- profile
    prof = (tables.get("profile") or [{}])[0]
    out["profile"] = {
        "first_name": prof.get("First Name"),
        "last_name": prof.get("Last Name"),
        "headline": prof.get("Headline"),
        "summary": prof.get("Summary"),
        "industry": prof.get("Industry"),
        "location": prof.get("Geo Location") or prof.get("Location"),
        "websites": prof.get("Websites"),
    }

    # ---- positions
    positions = []
    for r in tables.get("positions", []):
        positions.append({
            "company": r.get("Company Name"),
            "title": r.get("Title"),
            "location": r.get("Location"),
            "description": r.get("Description"),
            "started": parse_date(r.get("Started On", "")),
            "finished": parse_date(r.get("Finished On", "")) or "present",
        })
    positions.sort(key=lambda p: p.get("started") or "", reverse=True)
    out["positions"] = positions

    # ---- education
    out["education"] = [{
        "school": r.get("School Name"),
        "degree": r.get("Degree Name"),
        "field": r.get("Notes") or r.get("Activities"),
        "started": parse_date(r.get("Start Date", "")),
        "finished": parse_date(r.get("End Date", "")),
    } for r in tables.get("education", [])]

    # ---- skills, weighted by endorsements
    endorse_counts: dict[str, int] = {}
    for r in tables.get("endorsements", []):
        skill = (r.get("Skill Name") or r.get("Endorsed Skill") or "").strip()
        if skill:
            endorse_counts[skill] = endorse_counts.get(skill, 0) + 1

    skills = []
    for r in tables.get("skills", []):
        name = (r.get("Name") or r.get("Skill Name") or "").strip()
        if name:
            skills.append({"name": name, "endorsements": endorse_counts.get(name, 0)})
    for name, n in endorse_counts.items():
        if not any(s["name"].lower() == name.lower() for s in skills):
            skills.append({"name": name, "endorsements": n})
    skills.sort(key=lambda s: -s["endorsements"])
    out["skills"] = skills

    # ---- projects, certifications, publications
    out["projects"] = [{
        "title": r.get("Title"),
        "description": r.get("Description"),
        "url": r.get("Url"),
        "started": parse_date(r.get("Started On", "")),
        "finished": parse_date(r.get("Finished On", "")),
    } for r in tables.get("projects", [])]

    out["certifications"] = [{
        "name": r.get("Name"),
        "authority": r.get("Authority"),
        "started": parse_date(r.get("Started On", "")),
        "url": r.get("Url"),
    } for r in tables.get("certifications", [])]

    out["publications"] = [{
        "name": r.get("Name"),
        "publisher": r.get("Publisher"),
        "date": parse_date(r.get("Published On", "")),
        "description": r.get("Description"),
    } for r in tables.get("publications", [])]

    # ---- recommendations. Other people describing your work, unprompted.
    # The best raw material for a resume that exists, because it is already
    # third-party validated language.
    out["recommendations"] = [{
        "from": f"{r.get('First Name','')} {r.get('Last Name','')}".strip(),
        "company": r.get("Company"),
        "job_title": r.get("Job Title"),
        "text": r.get("Text"),
        "date": parse_date(r.get("Creation Date", "")),
    } for r in tables.get("recommendations_received", []) if (r.get("Text") or "").strip()]

    # ---- connections, grouped into a warm-intro index by company
    conns, by_company = [], {}
    for r in tables.get("connections", []):
        name = f"{r.get('First Name','')} {r.get('Last Name','')}".strip()
        company = (r.get("Company") or "").strip()
        if not name and not company:
            continue
        c = {
            "name": name,
            "company": company,
            "position": (r.get("Position") or "").strip(),
            "connected_on": parse_date(r.get("Connected On", "")),
            "url": (r.get("URL") or "").strip(),
        }
        conns.append(c)
        if company:
            by_company.setdefault(company.lower(), []).append(c)

    out["connections"] = conns
    out["connections_by_company"] = {
        k: v for k, v in sorted(by_company.items(), key=lambda kv: -len(kv[1]))
    }

    # ---- what you already applied to through LinkedIn, so the pipeline can
    # be backfilled instead of starting empty.
    out["job_applications"] = [{
        "company": r.get("Company Name"),
        "title": r.get("Job Title"),
        "applied_at": parse_date(r.get("Application Date", "")),
        "url": r.get("Job Url"),
    } for r in tables.get("job_applications", [])]

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Import a LinkedIn data export.")
    ap.add_argument("path", nargs="?", help="export .zip or unzipped folder")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    src = Path(args.path).expanduser() if args.path else find_export()
    if not src or not src.exists():
        print(
            "No LinkedIn export found under data/raw/.\n\n"
            "To get one:\n"
            "  1. LinkedIn > Settings > Data Privacy > Get a copy of your data\n"
            "  2. Choose 'Download larger data archive', request it\n"
            "  3. LinkedIn emails a ZIP in about 10 minutes\n"
            "  4. Drop the ZIP into data/raw/ and run this again\n\n"
            "Everything else in career-agent works without it. The export adds\n"
            "your endorsement data and your warm-intro graph.",
            file=sys.stderr,
        )
        return 1

    print(f"reading {src}", file=sys.stderr)
    data = build(src)

    if not data["tables_imported"]:
        print(f"no recognizable LinkedIn CSVs in {src}", file=sys.stderr)
        print(f"files seen: {', '.join(data['files_seen'][:20])}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")

    print(f"\nwrote {out}", file=sys.stderr)
    print(f"  positions        {len(data['positions'])}")
    print(f"  education        {len(data['education'])}")
    print(f"  skills           {len(data['skills'])}")
    print(f"  projects         {len(data['projects'])}")
    print(f"  certifications   {len(data['certifications'])}")
    print(f"  recommendations  {len(data['recommendations'])}")
    print(f"  connections      {len(data['connections'])} "
          f"across {len(data['connections_by_company'])} companies")

    top = list(data["connections_by_company"].items())[:8]
    if top:
        print("\n  companies where you already know someone:")
        for company, people in top:
            print(f"    {len(people):>3}  {people[0]['company']}")

    endorsed = [s for s in data["skills"] if s["endorsements"]][:8]
    if endorsed:
        print("\n  most endorsed skills:")
        for s in endorsed:
            print(f"    {s['endorsements']:>3}  {s['name']}")

    if args.json:
        print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
