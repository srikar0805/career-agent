#!/usr/bin/env python3
"""Merge raw sources into an evidence packet, and validate the evidence bank.

Division of labor, on purpose:

  This script       Mechanical work. Merge the three raw sources, deduplicate,
                    rank by signal, and compress into a packet small enough to
                    reason over. Then, separately, validate the resulting
                    evidence.yaml against the schema and find the gaps.

  The LLM           Semantic work, during /career-setup. Read the packet and
                    write evidence atoms. Deciding that "5,837 commits over 14
                    months on a browser extension with CI and tests" is worth
                    a resume bullet, and what that bullet should say, is
                    judgment. Python cannot do it and should not pretend to.

Commands:
    pack       merge raw sources into data/raw/evidence_packet.md
    validate   check profile/evidence.yaml, report gaps
    gaps       list only the atoms missing a metric, for the intake interview
    stats      summarize the bank

Usage:
    python connectors/build_evidence.py pack
    python connectors/build_evidence.py validate
    python connectors/build_evidence.py gaps
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML is required. Run: pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1)

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "raw"
PROFILE = REPO / "profile"
EVIDENCE = PROFILE / "evidence.yaml"
PACKET = RAW / "evidence_packet.md"

REQUIRED_FIELDS = {"id", "action", "sources", "confidence"}
# asserted-by-srikar: his own word on something no document or repo shows (EV-043, and
# EV-020's locally measured figures, 2026-09-16). Usable, but the figures are never restated by an agent.
VALID_CONFIDENCE = {"verified", "approximate", "unverifiable", "asserted-by-srikar"}

# Documents whose full text is worth carrying into the packet. Everything else
# contributes only its quantified claims.
FULL_TEXT_KINDS = {"resume", "cover_letter", "sop"}


def load(name: str) -> dict | None:
    p = RAW / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"warning: {name} is not valid JSON ({e})", file=sys.stderr)
        return None


# ------------------------------------------------------------------- pack

def _repo_section(r: dict) -> str:
    c = r.get("commits") or {}
    loc = r.get("local") or {}
    langs = r.get("languages") or {}

    lines = [f"### {r['name']}"]
    if r.get("description"):
        lines.append(f"description: {r['description']}")

    facts = []
    if c.get("count"):
        facts.append(f"{c['count']} commits by you")
    if c.get("span_days"):
        months = c["span_days"] / 30.4
        facts.append(f"sustained over {months:.0f} months ({c.get('first','')[:10]} to {c.get('last','')[:10]})")
    if r.get("stargazerCount"):
        facts.append(f"{r['stargazerCount']} stars")
    if r.get("forkCount"):
        facts.append(f"{r['forkCount']} forks")
    if loc.get("source_files"):
        facts.append(f"{loc['source_files']} source files")
    if loc.get("contributor_count", 0) > 1:
        facts.append(f"{loc['contributor_count']} contributors")
    if loc.get("has_tests"):
        facts.append("has a test suite")
    if loc.get("has_ci"):
        facts.append("has CI")
    if r.get("isPrivate"):
        facts.append("private repo")
    if facts:
        lines.append("facts: " + "; ".join(facts))

    if langs:
        total = sum(langs.values()) or 1
        top = sorted(langs.items(), key=lambda kv: -kv[1])[:6]
        lines.append("languages: " + ", ".join(f"{k} {100*v/total:.0f}%" for k, v in top))

    if loc.get("dependencies"):
        lines.append("dependencies: " + ", ".join(loc["dependencies"][:25]))
    if r.get("topics"):
        lines.append("topics: " + ", ".join(t for t in r["topics"] if t))

    readme = (r.get("readme") or "").strip()
    if readme:
        # The README's opening is the project's own pitch. Later sections are
        # install instructions, which are not evidence of anything.
        head = "\n".join(readme.splitlines()[:40])[:1800]
        lines.append(f"readme excerpt:\n{head}")

    msgs = c.get("messages") or []
    if msgs:
        # Commit subjects, deduplicated. These describe what was built, written
        # at the time it was built, which beats a retrospective summary.
        seen, uniq = set(), []
        for m in msgs:
            k = re.sub(r"[^a-z ]", "", m.lower())[:40]
            if k and k not in seen:
                seen.add(k)
                uniq.append(m)
        lines.append("representative commits: " + " | ".join(uniq[:25]))

    return "\n".join(lines)


def pack() -> str:
    gh = load("github.json")
    li = load("linkedin.json")
    dc = load("documents.json")

    if not any([gh, li, dc]):
        raise SystemExit(
            "No raw sources found. Run the connectors first:\n"
            "  python connectors/github.py\n"
            "  python connectors/docs.py\n"
            "  python connectors/linkedin.py   (needs the export in data/raw/)"
        )

    out: list[str] = [
        "# Evidence packet",
        "",
        f"Assembled {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')}.",
        "",
        "Raw material for building the evidence bank. Every fact below traces to a",
        "real source. Nothing here is inferred, summarized, or embellished.",
        "",
        "Source availability:",
    ]
    out.append(f"- GitHub:    {'yes, ' + str(gh.get('repo_count', 0)) + ' repos' if gh else 'NOT COLLECTED'}")
    out.append(f"- LinkedIn:  {'yes' if li else 'NOT COLLECTED (export not present)'}")
    out.append(f"- Documents: {'yes, ' + str(dc.get('document_count', 0)) + ' files' if dc else 'NOT COLLECTED'}")
    out.append("")

    # ---------------------------------------------------------- LinkedIn
    if li:
        out += ["", "## LinkedIn", ""]
        p = li.get("profile") or {}
        if p.get("headline"):
            out.append(f"current headline: {p['headline']}")
        if p.get("summary"):
            out.append(f"current about section:\n{p['summary'][:1500]}")
        out.append("")

        if li.get("positions"):
            out.append("### Positions")
            for pos in li["positions"]:
                out.append(f"- {pos.get('title')} at {pos.get('company')} "
                           f"({pos.get('started')} to {pos.get('finished')}), {pos.get('location') or ''}")
                if pos.get("description"):
                    out.append(f"  described as: {pos['description'][:900]}")
            out.append("")

        if li.get("education"):
            out.append("### Education")
            for e in li["education"]:
                out.append(f"- {e.get('degree') or ''} at {e.get('school')} "
                           f"({e.get('started')} to {e.get('finished')})")
            out.append("")

        endorsed = [s for s in li.get("skills", []) if s.get("endorsements")]
        if endorsed:
            out.append("### Skills other people endorsed")
            out.append("Independent confirmation of strengths. Weight these above self-assessment.")
            for s in endorsed[:25]:
                out.append(f"- {s['name']}: {s['endorsements']} endorsements")
            out.append("")

        if li.get("recommendations"):
            out.append("### Recommendations received")
            out.append("Third-party descriptions of the work. The strongest raw material available,")
            out.append("because the framing is already externally validated.")
            for r in li["recommendations"][:8]:
                out.append(f"- from {r.get('from')} ({r.get('job_title') or ''} at {r.get('company') or ''}):")
                out.append(f"  \"{(r.get('text') or '')[:800]}\"")
            out.append("")

        byco = li.get("connections_by_company") or {}
        if byco:
            out.append("### Warm intro graph")
            out.append(f"{len(li.get('connections', []))} connections across {len(byco)} companies.")
            out.append("Top companies where a first-degree connection already exists:")
            for _, people in list(byco.items())[:30]:
                out.append(f"- {people[0]['company']}: {len(people)} "
                           f"(e.g. {people[0]['name']}, {people[0].get('position') or 'role unknown'})")
            out.append("")

    # ---------------------------------------------------------- GitHub
    if gh:
        out += ["", "## GitHub", "",
                f"User {gh.get('user')}. Ranked by substance, not recency.", ""]
        for r in (gh.get("repos") or [])[:20]:
            out.append(_repo_section(r))
            out.append("")

        if gh.get("external_prs"):
            out.append("### Pull requests to other people's repositories")
            out.append("External contributions. Strongest third-party signal in the whole packet:")
            out.append("someone else's maintainer reviewed and accepted this code.")
            for pr in gh["external_prs"][:25]:
                out.append(f"- {pr['repo']}: {pr['title']} [{pr.get('state')}] {pr.get('created_at','')[:10]}")
            out.append("")

        if gh.get("local_only"):
            out.append("### Local repositories with no matching GitHub remote")
            out.append("Possibly private, possibly under another account. Ask before using.")
            for name, v in list(gh["local_only"].items())[:15]:
                out.append(f"- {name}: {v.get('local_commits')} commits, "
                           f"{v.get('source_files')} files, stack {','.join(v.get('stack') or []) or 'unknown'}")
            out.append("")

    # ---------------------------------------------------------- Documents
    if dc:
        docs = dc.get("documents") or []
        out += ["", "## Documents", ""]

        full = [d for d in docs if d["kind"] in FULL_TEXT_KINDS]
        if full:
            out.append("### Resumes, cover letters, and statements of purpose")
            out.append("These are prior self-descriptions. They show what has already been claimed,")
            out.append("in the user's own words. Treat conflicting versions as something to resolve")
            out.append("with the user, not something to silently pick between.")
            out.append("")
            for d in full[:14]:
                out.append(f"#### {d['name']}  [{d['kind']}, {d['words']} words]")
                out.append(d["text"][:4000])
                out.append("")

        claims: list[tuple[str, str]] = []
        for d in docs:
            if d["kind"] in FULL_TEXT_KINDS:
                continue
            for c in d.get("quantified_claims", []):
                claims.append((d["name"], c))

        if claims:
            # Deduplicate. The same sentence recurs across resume revisions and
            # near-identical assignment reports.
            seen, uniq = set(), []
            for name, c in claims:
                k = re.sub(r"[^a-z0-9]", "", c.lower())[:70]
                if k and k not in seen:
                    seen.add(k)
                    uniq.append((name, c))
            out.append("### Quantified claims found in other documents")
            out.append(f"{len(uniq)} distinct claims containing a number. Each needs verification")
            out.append("before it becomes an evidence atom. Many are course grades or citations,")
            out.append("not achievements. Filter accordingly.")
            out.append("")
            for name, c in uniq[:180]:
                out.append(f"- [{name}] {c}")
            out.append("")

    out += [
        "",
        "## How to turn this into evidence atoms",
        "",
        "1. One atom per distinct accomplishment. Not one per repo, not one per job.",
        "2. Every atom needs a `sources` list. An atom with no source is a hallucination.",
        "3. An atom with no `metric` is incomplete. Flag it rather than inventing a number.",
        "   The user supplies the real number once during intake, and it is reused forever.",
        "4. Set `confidence: verified` only for facts a source states directly. A commit",
        "   count is verified. 'Improved performance' with no measurement is unverifiable.",
        "5. Prefer the same accomplishment appearing in multiple sources. Cross-source",
        "   agreement is the strongest signal in this packet.",
        "6. Coursework and assignments are usually not evidence. A course project with",
        "   real scope, real users, or real engineering depth is. Most are not.",
    ]

    return "\n".join(out)


# --------------------------------------------------------------- validate

def load_evidence() -> list[dict]:
    if not EVIDENCE.exists():
        raise SystemExit(f"no evidence bank at {EVIDENCE}. Run /career-setup first.")
    data = yaml.safe_load(EVIDENCE.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise SystemExit("evidence.yaml must be a list of atoms at the top level.")
    return data


def validate() -> int:
    atoms = load_evidence()
    errors: list[str] = []
    warnings: list[str] = []

    ids = [a.get("id") for a in atoms]
    dupes = [i for i, n in Counter(ids).items() if n > 1 and i]
    for d in dupes:
        errors.append(f"duplicate id {d}")

    for i, a in enumerate(atoms):
        label = a.get("id") or f"atom #{i} (no id)"

        missing = REQUIRED_FIELDS - set(a.keys())
        if missing:
            errors.append(f"{label}: missing required field(s) {', '.join(sorted(missing))}")

        if a.get("id") and not re.fullmatch(r"EV-\d{3,}", str(a["id"])):
            errors.append(f"{label}: id must look like EV-001")

        conf = a.get("confidence")
        if conf and conf not in VALID_CONFIDENCE:
            errors.append(f"{label}: confidence '{conf}' must be one of {sorted(VALID_CONFIDENCE)}")

        src = a.get("sources")
        if not src:
            errors.append(f"{label}: no sources. Every atom must trace to something real.")
        elif not isinstance(src, list):
            errors.append(f"{label}: sources must be a list")

        m = a.get("metric")
        if not m:
            warnings.append(f"{label}: no metric. Cannot become a strong resume bullet as written.")
        elif isinstance(m, dict):
            if "value" not in m:
                errors.append(f"{label}: metric has no value")
            if "unit" not in m:
                warnings.append(f"{label}: metric has no unit")

        action = (a.get("action") or "").strip()
        if action and len(action) < 15:
            warnings.append(f"{label}: action is too short to be meaningful")

        if a.get("confidence") == "verified" and not a.get("metric"):
            warnings.append(f"{label}: marked verified but has no metric to verify")

        star = a.get("star")
        if star and isinstance(star, dict):
            for k in ("situation", "task", "action", "result"):
                if not (star.get(k) or "").strip():
                    warnings.append(f"{label}: STAR is missing '{k}', so it cannot be used in /interview-prep")

    print(f"evidence bank: {len(atoms)} atoms\n")

    if errors:
        print(f"{len(errors)} ERROR(S), these block generation:")
        for e in errors:
            print(f"  {e}")
        print()
    if warnings:
        print(f"{len(warnings)} warning(s):")
        for w in warnings[:40]:
            print(f"  {w}")
        if len(warnings) > 40:
            print(f"  ... and {len(warnings) - 40} more")
        print()
    if not errors and not warnings:
        print("clean.")

    return 1 if errors else 0


def gaps() -> int:
    """Atoms that need a number from the user. Drives the intake interview."""
    atoms = load_evidence()
    needy = [a for a in atoms if not a.get("metric")]

    if not needy:
        print("Every atom has a metric. Nothing to ask about.")
        return 0

    print(f"{len(needy)} of {len(atoms)} atoms have no metric.\n")
    print("Each of these becomes a weak resume bullet until a number exists.")
    print("Ask for the number once. It is then reused in every future document.\n")

    for a in needy:
        print(f"{a.get('id')}  {a.get('role') or a.get('project') or ''}")
        print(f"  claim:  {a.get('action')}")
        if a.get("scope"):
            print(f"  scope:  {a['scope']}")
        print(f"  source: {', '.join(a.get('sources') or [])}")
        print(f"  ask:    {_suggest_question(a)}")
        print()
    return 0


def _suggest_question(a: dict) -> str:
    """Turn an unmeasured claim into the specific question worth asking."""
    action = (a.get("action") or "").lower()
    pairs = [
        (r"\b(migrat|port|mov)\w*", "How many services, tables, or users moved, and over what period?"),
        (r"\b(optimi|speed|fast|latenc|perf)\w*", "What was the before and after number? Latency, throughput, or cost."),
        (r"\b(build|built|creat|develop|implement)\w*", "Who used it, how many of them, and what did it replace?"),
        (r"\b(automat|script)\w*", "How much manual time did this remove per week?"),
        (r"\b(fix|debug|resolv)\w*", "How often was it failing before, and after?"),
        (r"\b(lead|led|manag|mentor)\w*", "How many people, for how long?"),
        (r"\b(test|coverag)\w*", "What did coverage or defect rate go from and to?"),
        (r"\b(scale|scaling|throughput)\w*", "What volume did it handle before and after?"),
        (r"\b(cost|spend|budget)\w*", "How much money per month, and what was the reduction?"),
    ]
    for pattern, q in pairs:
        if re.search(pattern, action):
            return q
    return "What changed because of this, and by how much? A number, a percentage, or a count."


def stats() -> int:
    atoms = load_evidence()
    if not atoms:
        print("evidence bank is empty")
        return 0

    with_metric = sum(1 for a in atoms if a.get("metric"))
    with_star = sum(1 for a in atoms if a.get("star"))
    conf = Counter(a.get("confidence") for a in atoms)
    tech = Counter(t for a in atoms for t in (a.get("tech") or []))
    skills = Counter(s for a in atoms for s in (a.get("skills") or []))
    src_kinds = Counter(
        (s.split(":")[0] if ":" in s else "document")
        for a in atoms for s in (a.get("sources") or [])
    )

    print(f"atoms            {len(atoms)}")
    print(f"with a metric    {with_metric}  ({100*with_metric/len(atoms):.0f}%)")
    print(f"with STAR        {with_star}  ({100*with_star/len(atoms):.0f}%)   usable in /interview-prep")
    print(f"\nconfidence")
    for k, n in conf.most_common():
        print(f"  {str(k):<16}{n}")
    print(f"\nsources")
    for k, n in src_kinds.most_common():
        print(f"  {k:<16}{n}")
    print(f"\ntop technologies")
    for k, n in tech.most_common(15):
        print(f"  {k:<24}{n}")
    if skills:
        print(f"\ntop skills")
        for k, n in skills.most_common(12):
            print(f"  {k:<24}{n}")

    if with_metric < len(atoms):
        print(f"\n{len(atoms)-with_metric} atoms need a number. Run: "
              f"python connectors/build_evidence.py gaps")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Build and validate the evidence bank.")
    ap.add_argument("command", choices=["pack", "validate", "gaps", "stats"])
    ap.add_argument("--out", default=str(PACKET))
    args = ap.parse_args()

    if args.command == "pack":
        text = pack()
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        words = len(text.split())
        print(f"wrote {out}")
        print(f"  {words} words, roughly {words * 4 // 3} tokens")
        if words > 60000:
            print("  This is large. /career-setup should read it in sections.")
        return 0

    return {"validate": validate, "gaps": gaps, "stats": stats}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
