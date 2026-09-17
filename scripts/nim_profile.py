#!/usr/bin/env python3
"""The profile card an NVIDIA agent is allowed to see. Built, never hand-written.

Srikar agreed on 2026-09-16 that NVIDIA-hosted agents may read his postings,
resume facts and mail. This card is the resume-facts part, and it is built from
profile/ every time so it can never drift from the evidence bank.

What is IN: education, positions with titles exactly as profile/titles.yaml
states them, work authorization, availability, targets, skills with levels, and
every evidence atom that is not `unverifiable`, with its id, action, metric and
tech. That is what a recruiter could learn from his resume and LinkedIn.

What is OUT: phone, email, student id, advisor, street address, every `note`
field (they hold private reasoning, background-check wording and incident
history), unverifiable atoms, and anything about repositories with security
problems beyond their evidence ids.

    nim_profile.py            print the card
    nim_profile.py --stats    size only
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def resume_sourced_ids() -> set[str]:
    """Atoms carrying the "METRIC IS RESUME-SOURCED" warning.

    The warning is a YAML comment (audit 2026-09-11), so yaml.safe_load drops it and
    a card built from parsed data showed those figures as verified. On 2026-09-16
    an NVIDIA-written application answer quoted EV-002's "0.94" against the wrong
    project for exactly that reason. The comment sits inside the atom it warns about.
    """
    ids, cur = set(), None
    for line in (ROOT / "profile" / "evidence.yaml").read_text().splitlines():
        m = re.match(r"^-\s+id:\s*(EV-\w+)", line)
        if m:
            cur = m.group(1)
        elif "METRIC IS RESUME-SOURCED" in line and cur:
            ids.add(cur)
    return ids


def card() -> str:
    idn = yaml.safe_load((ROOT / "profile" / "identity.yaml").read_text())
    titles = yaml.safe_load((ROOT / "profile" / "titles.yaml").read_text())["positions"]
    skills = yaml.safe_load((ROOT / "profile" / "skills.yaml").read_text())
    atoms = yaml.safe_load((ROOT / "profile" / "evidence.yaml").read_text())

    L = ["CANDIDATE PROFILE (facts only; nothing outside this card may be claimed)", ""]
    L.append("EDUCATION")
    for e in idn.get("education", []):
        end = e.get("expected_graduation") and f"expected {e['expected_graduation']}" or e.get("end", "")
        L.append(f"- {e['degree']}, {e['school']}, {e.get('start', '')} to {end}, GPA {e.get('gpa')}")
    L += ["", "POSITIONS (titles are exact; never rename them)"]
    for p in titles:
        L.append(f"- {p['title']} | {p['company']} | {p['period']}")
    L += ["", "WORK AUTHORIZATION AND AVAILABILITY",
          f"- Citizenship {idn.get('citizenship')}; {idn.get('work_authorization')}",
          f"- Needs sponsorship eventually: {'yes' if idn.get('needs_sponsorship') else 'no'}. OPT then the 24-month "
          f"STEM OPT extension cover about 36 months with no petition; H-1B needed after that.",
          "- Graduates May 2027. Full-time start June 2027. Part-time now, up to 20 hours a week on CPT.",
          "- No security clearance; not a U.S. citizen or permanent resident, so citizenship or clearance gates exclude him.",
          f"- Relocation: {'anywhere in the US' if idn.get('open_to_relocate') else 'no'}; remote: {'yes' if idn.get('open_to_remote') else 'no'}",
          f"- Targets: {', '.join(idn.get('target_roles') or [])}",
          "", "SKILLS (level, then supporting evidence ids)"]
    for s in skills:
        L.append(f"- {s['name']} ({s.get('level', '?')}): {', '.join(s.get('evidence') or [])}")
    L += ["", "EVIDENCE ATOMS (id | role | period | what he did | metric | tech)"]
    usable = {a["id"] for a in atoms if a.get("confidence") != "unverifiable"}
    # rebuild the skills lines with usable ids only: listing EV-001 under a skill while
    # withholding the atom made every model that cited it look like it invented an id
    skill_start = L.index("SKILLS (level, then supporting evidence ids)") + 1
    L[skill_start:skill_start + len(skills)] = [
        f"- {s['name']} ({s.get('level', '?')}): {', '.join(i for i in (s.get('evidence') or []) if i in usable) or 'no usable evidence'}"
        for s in skills]
    unquotable = resume_sourced_ids()
    for a in atoms:
        if a.get("confidence") == "unverifiable":
            continue
        m = a.get("metric") or {}
        metric = f"{m.get('value')} {m.get('unit', '')} {m.get('dimension', '')}".strip() if m else ""
        hedge = " (approximate)" if a.get("confidence") == "approximate" else ""
        action = a.get("action") or ""
        if a["id"] in unquotable:               # the work is real, the figures are not quotable
            action = re.sub(r"(?<![\w.])\d+(?:[.,]\d+)*(?![\w])", "[figure withheld]", action)
            metric, hedge = "no quotable figure", ""
        L.append(f"- {a['id']} | {a.get('role')} | {a.get('period')} | {action} | "
                 f"{metric}{hedge} | {', '.join(a.get('tech') or [])}")
    return "\n".join(L)


def evidence_ids() -> set[str]:
    atoms = yaml.safe_load((ROOT / "profile" / "evidence.yaml").read_text())
    return {a["id"] for a in atoms if a.get("confidence") != "unverifiable"}


if __name__ == "__main__":
    c = card()
    if "--stats" in sys.argv:
        print(f"{len(c):,} chars, about {len(c) // 4:,} tokens, {len(evidence_ids())} usable atoms")
    else:
        print(c)
