#!/usr/bin/env python3
"""Export the pipeline to CSV.

Two modes, because they answer different questions:

    --all       every row, whatever its status. This is the working tracker:
                open it, set the status column, hand it back.
    (default)   only rows that have actually been applied to.

The default is deliberately strict. A "jobs I applied to" file that quietly
includes discovered-but-never-submitted rows is worse than no file, because it
is the document you would use to decide who to follow up with.

Each row carries the tailored resume built for it, matched by company, so the
CSV also answers "which PDF did I send them".

Usage:
    python scripts/export_csv.py --all -o ~/Desktop/job_tracker.csv
    python scripts/export_csv.py -o ~/Desktop/applied.csv
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "pipeline.db"
RESUMES = Path.home() / "Desktop" / "Resumes." / "final"

# Company name to the resume actually built for it. Keyed on a lowercase
# substring of the company, since the pipeline stores display names.
RESUME_MAP = {
    "blackrock": "SaiSrikarKolli_BlackRock_2027_Analyst.pdf",
    "google": "SaiSrikarKolli_Google_DataEngineer.pdf",
    "deepgram": "SaiSrikarKolli_Deepgram_Intern.pdf",
    "appian": "SaiSrikarKolli_Appian_Intern.pdf",
    "chicago trading": "SaiSrikarKolli_CTC_Associate_Engineer.pdf",
    "quora": "SaiSrikarKolli_MLPlatform.pdf",
    "max tech": "SaiSrikarKolli_FullStack.pdf",
    "caseguard": "SaiSrikarKolli_Backend.pdf",
    "instalily": "SaiSrikarKolli_InstaLILY.pdf",
    "aven": "SaiSrikarKolli_DataScientist.pdf",
    "new york technology": "SaiSrikarKolli_AIEngineer_NYTM.pdf",
    "marlabs": "SaiSrikarKolli_Marlabs.pdf",
    "anthropic": "SaiSrikarKolli_Anthropic_Fellows.pdf",
    "nexthop": "SaiSrikarKolli_Nexthop_NewGrad.pdf",
    "flow engineering": "SaiSrikarKolli_Flow_EarlyCareer.pdf",
    "missouri consolidated": "SaiSrikarKolli_MCHCP_AppDeveloper.pdf",
}

FIELDS = ["id", "status", "applied_at", "company", "role", "location",
          "comp_min", "comp_max", "sponsors", "fit_score", "resume_sent",
          "url", "discovered_at", "notes"]


def resume_for(company: str) -> str:
    c = (company or "").lower()
    # Charta posted two distinct roles, so the role decides which resume.
    for key, fn in RESUME_MAP.items():
        if key in c:
            return fn if (RESUMES / fn).exists() else f"{fn} (MISSING)"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--all", action="store_true",
                    help="every row, not just applied ones")
    a = ap.parse_args()

    if not DB.exists():
        sys.exit(f"no pipeline database at {DB}")
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    q = "SELECT * FROM applications"
    if not a.all:
        q += " WHERE status IN ('applied','screening','interviewing','offer','rejected')"
    q += " ORDER BY id"
    rows = list(con.execute(q))

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            d = {k: (r[k] if k in r.keys() else "") for k in FIELDS}
            d["resume_sent"] = resume_for(r["company"])
            # Charta has two roles sharing one company name.
            if "charta" in (r["company"] or "").lower():
                d["resume_sent"] = ("SaiSrikarKolli_Charta_ForwardDeployed.pdf"
                                    if "forward" in (r["role"] or "").lower()
                                    else "SaiSrikarKolli_Charta_NewGrad.pdf")
            w.writerow(d)

    label = "all rows" if a.all else "applied rows only"
    print(f"{a.out}: {len(rows)} {label}")
    if not rows and not a.all:
        print("  Nothing is marked applied yet. Re-run with --all for the tracker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
