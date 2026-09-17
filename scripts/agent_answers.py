#!/usr/bin/env python3
"""NVIDIA agent: write the open-ended answers in an application packet.

prefill.py fills every factual question from the answer bank and marks free-text
questions OPEN ("Why Anthropic?", "Imagine you're building a computer vision
system..."). This writes those, in Srikar's voice, from his evidence, in one call
per packet, and appends them to the packet under "## Written answers".

Checked, not trusted:
  - every number must come from an evidence item the answer CITES (or the posting,
    the answer bank, or his education and authorization facts), so a real figure
    cannot be moved onto a different project; figures the 2026-09-11 audit marked
    resume-sourced are withheld from the card entirely;
  - evidence ids may not appear inside the answer text;
  - CHECKED means those checks passed, not that every claim is true: he reads it;
  - cited evidence ids must exist, and EV-041 (TigerVerse, authorship unconfirmed)
    is never allowed;
  - no em or en dashes; answers over the length limit are flagged.
An answer that fails a check is kept but labelled DRAFT with the reason, so he
sees exactly what to fix rather than a silently weaker answer.

    agent_answers.py --app 300              write and append
    agent_answers.py --app 300 --dry-run    list the OPEN questions, send nothing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from agent_verdict import out_path as verdict_file, posting_text, row   # noqa: E402
from nim import NimError, chat                                         # noqa: E402
from nim_profile import card, evidence_ids                             # noqa: E402
from prefill import write_packet                                       # noqa: E402

VOICE = (ROOT / "profile" / "voice.md").read_text()
ANSWERS_YAML = (ROOT / "profile" / "answers.yaml").read_text()
NEVER = {"EV-041"}          # TigerVerse: authorship unconfirmed
MAX_CHARS = 1100

SYSTEM = """You write the free-text answers on a job application for one candidate, in his voice.

His voice (from the samples provided): state the problem before the solution, short declarative \
sentences, a concrete constraint instead of an adjective, a real point of view. No flattery of the \
company, no "I am passionate", no "I believe I would be a great fit".

Rules:
- Use ONLY facts in the candidate profile. Every number you write must appear in the profile, the \
answer bank or the posting. Never invent a metric, a team size, a user count or a result.
- Put the evidence ids you drew on ONLY in the "evidence" list, never inside the answer text. Never use EV-041.
- A figure may only describe the project it belongs to. Never attach a number from one evidence item to \
the work of another. Items marked "[figure withheld]" or "no quotable figure" have no quotable numbers.
- "Why this company" answers give one specific, checkable reason taken from the posting.
- Technical scenario questions: answer from work he has actually done, naming the closest real project.
- 60 to 170 words each unless the question asks for less. No em dashes or en dashes.

Reply with ONE JSON object:
{"answers": [{"question": "<exact question>", "answer": "<text>", "evidence": ["EV-..."]}]}"""


NUM = r"(?<![\w.])\d+(?:[.,]\d+)*(?![\w])"


def check(answer: str, evidence: list[str], allowed_numbers: set[str],
          atom_lines: dict[str, str] | None = None) -> list[str]:
    """allowed_numbers: numbers from the posting, the answer bank and the non-evidence
    parts of the card. A number may otherwise appear only if an atom the answer CITES
    contains it. On 2026-09-16 a check against the whole card let "0.94 ... at 500
    inferences per day" through: both figures were real, from two other projects."""
    problems = []
    cited_numbers = set()
    for e in evidence:
        cited_numbers |= set(re.findall(NUM, (atom_lines or {}).get(e, "")))
    for n in set(re.findall(NUM, answer)):
        if n not in allowed_numbers and n not in cited_numbers:
            problems.append(f"number {n} is not in a cited evidence item, the answer bank or the posting")
    if re.search(r"\bEV-\d", answer):
        problems.append("evidence ids inside the answer text; they belong in the note, not the paste")
    bad = [e for e in evidence if e not in evidence_ids() or e in NEVER]
    if bad:
        problems.append(f"evidence ids not allowed: {bad}")
    if re.search("[—–]", answer):
        problems.append("contains an em or en dash")
    if len(answer) > MAX_CHARS:
        problems.append(f"{len(answer)} characters, over {MAX_CHARS}")
    return problems


def run(app_id: int, dry: bool) -> int:
    r = row(app_id)
    path, text, info = write_packet(app_id)
    open_q = [x for x in info["rows"] if x["status"] == "OPEN"]
    if not open_q:
        print(f"#{app_id}: no open-ended questions in the packet")
        return 0
    print(f"#{app_id} {r['company']}: {len(open_q)} open question(s)")
    for q in open_q:
        print(f"  {'(required) ' if q['required'] else ''}{q['label'][:110]}")
    if dry:
        return 0

    jd = posting_text(r)
    verdict = json.loads(verdict_file(r).read_text()) if verdict_file(r).exists() else {}
    prof = card()
    prompt = (f"VOICE SAMPLES\n{VOICE}\n\n{prof}\n\nANSWER BANK NOTES (grounding, not prose)\n"
              f"{yaml.safe_dump(yaml.safe_load(ANSWERS_YAML).get('open_ended'), sort_keys=False)}\n"
              f"POSTING: {r['company']} / {r['role']} ({r.get('location') or ''})\n{jd[:9000]}\n\n"
              f"VERDICT CONTEXT: {verdict.get('one_line', '')} best evidence {verdict.get('best_evidence', [])}\n\n"
              "QUESTIONS\n" + "\n".join(f"- {q['label']}" for q in open_q))
    try:
        res = chat("writer", SYSTEM, prompt, want_json=True, max_tokens=12000, temperature=0.4,
                   purpose=f"answers #{app_id}")
    except NimError as e:
        print(f"  FAILED {e}")
        return 1
    if res.get("truncated"):
        print("  FAILED the model ran out of tokens before finishing; packet left unchanged")
        return 1
    atom_lines = {l.split(" | ")[0][2:]: l for l in prof.splitlines() if l.startswith("- EV-")}
    non_atom = "\n".join(l for l in prof.splitlines() if not l.startswith("- EV-") and "):" not in l)
    allowed = set(re.findall(NUM, non_atom + ANSWERS_YAML + jd))
    got = (res["json"] or {}).get("answers") if isinstance(res["json"], dict) else []
    L = ["", "## Written answers", "",
         f"Drafted by {res['model']} from profile/voice.md and the evidence bank. Read each before pasting.", ""]
    for q in open_q:
        a = next((x for x in got or [] if isinstance(x, dict) and x.get("question", "").strip()[:60] == q["label"][:60]), None) \
            or next((x for x in got or [] if isinstance(x, dict) and q["label"][:40].lower() in str(x.get("question", "")).lower()), None)
        L.append(f"### {q['label']}")
        if not a or not str(a.get("answer", "")).strip():
            L += ["", "NEEDS YOU: the writer returned nothing for this question.", ""]
            print(f"  missing answer: {q['label'][:80]}")
            continue
        ans, ev = str(a["answer"]).strip(), [e for e in a.get("evidence") or [] if isinstance(e, str)]
        problems = check(ans, ev, allowed, atom_lines)
        status = "DRAFT, check: " + "; ".join(problems) if problems else "CHECKED (numbers and ids verified; read the claims yourself)"
        L += ["", ans, "", f"_{status}. Evidence: {', '.join(ev) or 'none cited'}_", ""]
        print(f"  {'DRAFT' if problems else 'CHECKED'} {len(ans):4} chars  {q['label'][:70]}" + (f"  [{'; '.join(problems)[:90]}]" if problems else ""))
    body = path.read_text().split("\n## Written answers")[0].rstrip("\n")
    path.write_text(body + "\n" + "\n".join(L) + "\n")
    print(f"  appended to {path.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    return run(a.app, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
