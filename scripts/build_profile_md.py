#!/usr/bin/env python3
"""Consolidate every source into one human-readable PROFILE.md.

The data was always stored. It was just stored across evidence.yaml,
identity.yaml, skills.yaml, github.json, documents.json and a SQLite file,
which is fine for the tooling and useless for a person who wants to read their
own record.

This is a generator, not a document. Re-run it after any connector refresh or
evidence edit and the file rebuilds from source, so it cannot drift out of
sync the way a hand-written summary would.

Usage:
    python scripts/build_profile_md.py
    python scripts/build_profile_md.py --out ~/Desktop/PROFILE.md
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML required. pip install -r requirements.txt")

REPO = Path(__file__).resolve().parent.parent
PROFILE = REPO / "profile"
RAW = REPO / "data" / "raw"
OUT = PROFILE / "PROFILE.md"


def load_yaml(name):
    p = PROFILE / name
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None


def load_json(name):
    p = RAW / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def read_md(name, demote: int = 0) -> str:
    """Read a profile markdown file, optionally pushing its headings deeper.

    narrative.md and voice.md are written as standalone documents with their
    own "##" sections. Embedded here they would sit at the same level as the
    top-level sections of this file and break the outline, so their headings
    are demoted to nest correctly.
    """
    p = PROFILE / name
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8").strip()
    if not demote:
        return text
    out, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence and line.startswith("#"):
            line = "#" * demote + line
        out.append(line)
    return "\n".join(out)


def months(days):
    return f"{days / 30.4:.0f} months" if days else None


def fmt_metric(m) -> str:
    if not isinstance(m, dict):
        return str(m)
    v, u = m.get("value"), m.get("unit", "")
    s = f"{v} {u}".strip()
    if m.get("dimension"):
        s += f" ({m['dimension']})"
    if m.get("baseline") is not None:
        s += f", baseline {m['baseline']}"
    return s


def build() -> str:
    ident = load_yaml("identity.yaml") or {}
    evidence = load_yaml("evidence.yaml") or []
    skills = load_yaml("skills.yaml") or []
    gh = load_json("github.json") or {}
    docs = load_json("documents.json") or {}
    li = load_json("linkedin.json")

    L: list[str] = []
    add = L.append

    # ------------------------------------------------------------ header
    add(f"# {ident.get('name', 'Profile')}")
    add("")
    add(f"*Generated {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')} by "
        f"`scripts/build_profile_md.py`. Do not edit by hand; edit the sources and "
        f"regenerate, or your changes will be overwritten.*")
    add("")
    add("This is the complete record: identity, work history, every project with its "
        "real numbers, every skill and what backs it, and every source the record was "
        "built from. It is gitignored along with the rest of `profile/`.")
    add("")
    add("---")
    add("")

    # ------------------------------------------------------------ contact
    add("## Contact and identity")
    add("")
    for label, key in [("Email", "email"), ("Phone", "phone"), ("Location", "location"),
                       ("GitHub", "github"), ("LinkedIn", "linkedin"),
                       ("Portfolio", "portfolio")]:
        if ident.get(key):
            add(f"- **{label}:** {ident[key]}")
    add("")

    add("### Work authorization")
    add("")
    add(f"- **Citizenship:** {ident.get('citizenship', 'unknown')}")
    add(f"- **Visa status:** {ident.get('visa_status', 'unknown')}")
    add(f"- **Authorization:** {ident.get('work_authorization', 'unknown')}")
    add(f"- **STEM OPT eligible:** {ident.get('stem_opt_eligible')}")
    add(f"- **Needs sponsorship:** {ident.get('needs_sponsorship')}")
    add(f"- **Security clearance eligible:** {ident.get('security_clearance_eligible')}")
    add("")
    add("STEM designation means 12 months of OPT plus a 24-month extension: **three "
        "years of US work authorization with no employer sponsorship paperwork.** "
        "State it that way on every form that gives you a text field. A bare "
        "\"requires sponsorship\" is technically true and gets filtered.")
    add("")

    add("### Education")
    add("")
    for e in ident.get("education", []):
        line = f"**{e.get('degree')}**, {e.get('school')}"
        span = f"{e.get('start','?')} to {e.get('expected_graduation') or e.get('end','?')}"
        add(f"- {line}  \n  {span}" + (f", GPA {e['gpa']}" if e.get("gpa") else ""))
    add("")

    add("### Targeting")
    add("")
    add(f"- **Roles:** {', '.join(ident.get('target_roles', []) or ['not set'])}")
    add(f"- **Locations:** {', '.join(ident.get('target_locations', []) or ['not set'])}")
    add(f"- **Timeline:** {ident.get('timeline', 'not set')}")
    rt = ident.get("role_type")
    add(f"- **Role type:** {', '.join(rt) if isinstance(rt, list) else rt or 'not set'}")
    add("")
    if ident.get("cpt_full_time_interest"):
        add("> **CPT warning.** Twelve months or more of full-time CPT eliminates OPT "
            "eligibility entirely, which would cost the whole three-year runway above. "
            "Part-time CPT does not. Verify with the Mizzou International Center DSO "
            "before accepting any full-time CPT offer.")
        add("")
    add("---")
    add("")

    # ------------------------------------------------------------ experience
    add("## Work history")
    add("")
    def role_key(r: str) -> str:
        """Collapse spellings of the same role.

        evidence.yaml records the lab role both as "... Precision and Automated
        Agriculture Lab, University of Missouri" and as "... PAAL, University
        of Missouri". Same job, two strings, and grouping on the raw value
        splits one role into two sections.
        """
        k = r.lower().replace("precision and automated agriculture lab", "paal")
        k = k.replace("university of missouri", "univ. of missouri")
        return " ".join(k.split())

    roles: dict[str, list] = {}
    labels: dict[str, str] = {}
    for a in evidence:
        r = a.get("role")
        if not r:
            continue
        k = role_key(r)
        roles.setdefault(k, []).append(a)
        # Keep the longest spelling as the display label; it is the most complete.
        if len(r) > len(labels.get(k, "")):
            labels[k] = r

    def role_start(items):
        return min((i.get("period") or "9999") for i in items)

    for key, items in sorted(roles.items(), key=lambda kv: role_start(kv[1]), reverse=True):
        period = items[0].get("period", "")
        add(f"### {labels[key]}")
        add(f"*{period}*")
        add("")
        for a in items:
            bits = [f"**{a['id']}** {a.get('action','')}"]
            if a.get("metric"):
                bits.append(f"  - Metric: {fmt_metric(a['metric'])}")
            if a.get("scope"):
                bits.append(f"  - Scope: {a['scope']}")
            if a.get("tech"):
                bits.append(f"  - Tech: {', '.join(a['tech'])}")
            bits.append(f"  - Confidence: `{a.get('confidence','?')}`  |  "
                        f"Sources: {', '.join(a.get('sources', []) or ['none'])}")
            add("- " + "\n".join(bits))
        add("")

    add("---")
    add("")

    # ------------------------------------------------------------ projects
    add("## Projects, from the evidence bank")
    add("")
    for a in evidence:
        if not a.get("project"):
            continue
        add(f"### {a['project']}")
        if a.get("period"):
            add(f"*{a['period']}*")
        add("")
        add(a.get("action", ""))
        add("")
        if a.get("metric"):
            add(f"- **Metric:** {fmt_metric(a['metric'])}")
        if a.get("scope"):
            add(f"- **Scope:** {a['scope']}")
        if a.get("tech"):
            add(f"- **Tech:** {', '.join(a['tech'])}")
        add(f"- **Confidence:** `{a.get('confidence','?')}`")
        add(f"- **Sources:** {', '.join(a.get('sources', []) or ['none'])}")
        if a.get("star"):
            s = a["star"]
            add("")
            add("<details><summary>STAR story, for interviews</summary>")
            add("")
            for k in ("situation", "task", "action", "result"):
                if s.get(k):
                    add(f"- **{k.title()}:** {s[k]}")
            add("")
            add("</details>")
        add("")

    add("---")
    add("")

    # ------------------------------------------------------------ github
    if gh:
        add(f"## GitHub: every repository")
        add("")
        add(f"User `{gh.get('user')}`. {gh.get('repo_count', 0)} repositories, "
            f"collected {gh.get('collected_at','')[:10]}. Ranked by substance: commits "
            f"you authored, stars, tests, and CI.")
        add("")

        for r in gh.get("repos", []):
            loc = r.get("local") or {}
            if loc.get("likely_not_mine"):
                continue
            c = r.get("commits") or {}
            langs = r.get("languages") or {}

            add(f"### {r['name']}")
            if r.get("description"):
                add(f"*{r['description']}*")
            add("")
            facts = []
            if c.get("count"):
                facts.append(f"**{c['count']} commits** by you")
            if c.get("span_days"):
                facts.append(f"sustained {months(c['span_days'])}")
            if c.get("first"):
                facts.append(f"{c['first'][:10]} to {(c.get('last') or '')[:10]}")
            if r.get("stargazerCount"):
                facts.append(f"{r['stargazerCount']} stars")
            if loc.get("source_files"):
                facts.append(f"{loc['source_files']} source files")
            if loc.get("has_tests"):
                facts.append("has tests")
            if loc.get("has_ci"):
                facts.append("has CI")
            if r.get("isPrivate"):
                facts.append("private")
            if facts:
                add("- " + " · ".join(facts))
            if langs:
                total = sum(langs.values()) or 1
                top = sorted(langs.items(), key=lambda kv: -kv[1])[:6]
                add("- **Languages:** " + ", ".join(f"{k} {100*v/total:.0f}%" for k, v in top))
            if loc.get("dependencies"):
                add("- **Dependencies:** " + ", ".join(loc["dependencies"][:20]))
            if r.get("url"):
                add(f"- {r['url']}")
            add("")

            readme = (r.get("readme") or "").strip()
            if readme:
                head = "\n".join(
                    ("  " + ln if ln.lstrip().startswith("#") else ln)
                    for ln in readme.splitlines()[:30]
                )[:1600]
                add("<details><summary>README</summary>")
                add("")
                add("```")
                add(head)
                add("```")
                add("")
                add("</details>")
                add("")

            msgs = c.get("messages") or []
            if msgs:
                seen, uniq = set(), []
                for m in msgs:
                    k = m.lower()[:40]
                    if k not in seen:
                        seen.add(k); uniq.append(m)
                add("<details><summary>Representative commits</summary>")
                add("")
                for m in uniq[:20]:
                    add(f"- {m}")
                add("")
                add("</details>")
                add("")

        # not-yours section, explicitly labelled
        skipped = [r for r in gh.get("repos", [])
                   if (r.get("local") or {}).get("likely_not_mine")]
        local_only = gh.get("local_only") or {}
        flagged = {k: v for k, v in local_only.items() if v.get("likely_not_mine")}
        if skipped or flagged:
            add("### Repositories on disk that are NOT your work")
            add("")
            add("Cloned or forked from someone else. Recorded so nobody mistakes their "
                "commit history for yours.")
            add("")
            for r in skipped:
                loc = r["local"]
                add(f"- **{r['name']}**: {loc.get('my_commits')} of "
                    f"{loc.get('total_commits')} commits are yours. "
                    f"Top author: {loc.get('top_author')}")
            for name, v in flagged.items():
                add(f"- **{name}**: {v.get('my_commits')} of {v.get('total_commits')} "
                    f"commits are yours. Top author: {v.get('top_author')}")
            add("")

        prs = gh.get("external_prs") or []
        if prs:
            add("### Pull requests to other people's repositories")
            add("")
            add("The strongest evidence in this whole file. Someone else reviewed and "
                "merged your code.")
            add("")
            for pr in prs:
                add(f"- **{pr['repo']}** — {pr['title']} "
                    f"`[{pr.get('state')}]` {pr.get('created_at','')[:10]}  \n  {pr.get('url','')}")
            add("")

    add("---")
    add("")

    # ------------------------------------------------------------ linkedin
    add("## LinkedIn")
    add("")
    if li:
        p = li.get("profile") or {}
        if p.get("headline"):
            add(f"**Current headline:** {p['headline']}")
            add("")
        for pos in li.get("positions", []):
            add(f"- **{pos.get('title')}** at {pos.get('company')} "
                f"({pos.get('started')} to {pos.get('finished')})")
        add("")
        endorsed = [s for s in li.get("skills", []) if s.get("endorsements")]
        if endorsed:
            add("**Most endorsed skills:** " +
                ", ".join(f"{s['name']} ({s['endorsements']})" for s in endorsed[:15]))
            add("")
        byco = li.get("connections_by_company") or {}
        if byco:
            add(f"**Warm intro graph:** {len(li.get('connections', []))} connections "
                f"across {len(byco)} companies.")
            add("")
    else:
        add("**Not imported.** This is the biggest gap in the record.")
        add("")
        add("Get it at LinkedIn, Settings, Data Privacy, Get a copy of your data. "
            "Request the full archive, wait about ten minutes for the email, and drop "
            "the ZIP into `data/raw/`. Then:")
        add("")
        add("```bash")
        add("python connectors/linkedin.py && python scripts/build_profile_md.py")
        add("```")
        add("")
        add("It adds two things nothing else can: which skills other people endorsed, "
            "and your connection graph, which turns cold outreach into warm "
            "introductions at companies where you already know somebody.")
        add("")

    add("---")
    add("")

    # ------------------------------------------------------------ skills
    add("## Skills, and what backs each one")
    add("")
    backed = [s for s in skills if isinstance(s, dict) and s.get("level") != "unbacked"]
    unbacked = [s for s in skills if isinstance(s, dict) and s.get("level") == "unbacked"]

    by_level: dict[str, list] = {}
    for s in backed:
        by_level.setdefault(s.get("level", "unknown"), []).append(s)
    for level in ("expert", "advanced", "working", "foundational", "unknown"):
        group = by_level.get(level)
        if not group:
            continue
        add(f"### {level.title()}")
        add("")
        for s in sorted(group, key=lambda x: x["name"]):
            ev = ", ".join(s.get("evidence", []) or [])
            note = f" — {s['note']}" if s.get("note") else ""
            add(f"- **{s['name']}** — backed by {ev or 'nothing'}{note}")
        add("")

    if unbacked:
        add("### Claimed on a resume but backed by nothing")
        add("")
        add("**Do not put these on a resume.** No evidence atom supports any of them, "
            "and one question in a technical screen makes the whole document suspect.")
        add("")
        add(", ".join(s["name"] for s in unbacked))
        add("")

    add("---")
    add("")

    # ------------------------------------------------------------ narrative
    nar = read_md("narrative.md", demote=1)
    if nar:
        add("## Positioning and narrative")
        add("")
        add(nar.split("\n", 1)[1].strip() if nar.startswith("#") else nar)
        add("")
        add("---")
        add("")

    voice = read_md("voice.md", demote=1)
    if voice:
        add("## Voice")
        add("")
        add(voice.split("\n", 1)[1].strip() if voice.startswith("#") else voice)
        add("")
        add("---")
        add("")

    # ------------------------------------------------------------ gaps
    add("## What is missing, and what it would take")
    add("")
    no_metric = [a for a in evidence if not a.get("metric")]
    no_star = [a for a in evidence if not a.get("star")]
    add(f"- **{len(evidence)} evidence atoms.** "
        f"{len(evidence) - len(no_metric)} carry a metric "
        f"({100*(len(evidence)-len(no_metric))//max(len(evidence),1)}%). "
        f"{len(evidence) - len(no_star)} carry a STAR story, which is what "
        f"`/interview-prep` builds answers from.")
    if no_metric:
        add("")
        add("**Atoms with no number.** Each is a weak resume bullet until you supply one:")
        add("")
        for a in no_metric:
            add(f"- `{a['id']}` {a.get('action','')[:110]}")
    add("")
    if not li:
        add("- **LinkedIn export not imported.** See above.")
    add("")

    # ------------------------------------------------------------ sources
    add("---")
    add("")
    add("## Where this came from")
    add("")
    add("| Source | Contents |")
    add("|---|---|")
    add(f"| `profile/evidence.yaml` | {len(evidence)} atoms, the spine of every document |")
    add(f"| `profile/identity.yaml` | contact, work authorization, targeting, hard filters |")
    add(f"| `profile/skills.yaml` | {len(backed)} backed skills, {len(unbacked)} unbacked |")
    add(f"| `data/raw/github.json` | {gh.get('repo_count', 0)} repos, "
        f"{len(gh.get('external_prs', []))} external PRs |")
    add(f"| `data/raw/documents.json` | {docs.get('document_count', 0)} documents scanned |")
    add(f"| `data/raw/linkedin.json` | {'imported' if li else 'NOT IMPORTED'} |")
    add("")
    add("Rebuild this file after any change:")
    add("")
    add("```bash")
    add("python scripts/build_profile_md.py")
    add("```")
    add("")
    add("`profile/` and `data/` are gitignored. Nothing here reaches GitHub.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a consolidated PROFILE.md.")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    text = build()
    p = Path(args.out).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

    words = len(text.split())
    print(f"wrote {p}")
    print(f"  {words} words, {len(text.splitlines())} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
