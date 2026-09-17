#!/usr/bin/env python3
"""NVIDIA agent: is this posting worth Srikar's time? One JSON verdict per row.

Replaces the per-posting reading Stage 2 did on Claude (2 to 4.5M cached tokens a
run, most of it postings). Runs in Stage 1, in Python, before Claude starts, so
Claude reads a verdict line instead of a job description.

    agent_verdict.py --app 291            one row
    agent_verdict.py --new                every 'discovered' row from today with no verdict yet
    agent_verdict.py --app 291 --dry-run  build the prompt, send nothing

Output: data/artifacts/<slug>/verdict-<id>.json, and one pipeline note per new
verdict. The model's answer is checked, not trusted: evidence ids it cites must
exist in the bank (invented ids are dropped and counted), the score is clamped,
and em dashes are removed.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, time as dtime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from nim import NimError, chat                  # noqa: E402
from nim_profile import card, evidence_ids      # noqa: E402

DB = ROOT / "data" / "pipeline.db"

SYSTEM = """You screen job postings for one candidate. You are strict and honest: \
most postings are not worth applying to, and a generous verdict wastes his week.

Rules:
- Use ONLY the candidate profile. Never assume a skill or experience it does not state.
- Cite evidence ONLY by the EV ids that appear in the profile.
- Hard blockers: U.S. citizenship or permanent residency required, security clearance, \
an explicit statement that the employer will never sponsor or will not support OPT, \
a graduation window that excludes May 2027, a full-time start date before June 2027 that the posting \
STATES (a date, "immediate start", "ASAP"), \
a years-of-experience floor above 2, work located outside the United States, \
eligibility restricted to students of a named school other than the University of Missouri.
- The TITLE can be narrower than the body. Judge the graduation window from the body \
when both state one ("December 2026 or by Summer 2027" includes May 2027).
- "Not eligible for sponsorship" alone is a blocker only if it rules out OPT; if the \
wording is ambiguous, list it under risks, not blockers.
- A full-time role that states no start date is NOT a blocker and NOT an "immediate hire". Do not infer \
urgency. Mention timing under risks only when the posting gives a reason to (2026-09-16: Gemini skipped four \
postings as "immediate-hire" when none of them said so).
- No em dashes anywhere in your output.

Reply with ONE JSON object and nothing else:
{
  "verdict": "apply" | "maybe" | "skip",
  "fit_score": integer 0 to 100,
  "one_line": "at most 220 characters: the single reason this is or is not worth his time",
  "blockers": ["quoted or paraphrased posting sentence that disqualifies him"],
  "risks": ["concern that is not absolute"],
  "must_haves": [{"requirement": "...", "status": "met" | "partial" | "missing", "evidence": ["EV-..."]}],
  "missing_keywords": ["posting keyword absent from his profile"],
  "best_evidence": ["EV-... most relevant to this posting, strongest first"]
}"""


def slug(company: str, role: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{company}-{role}".lower()).strip("-")[:60]


def row(app_id: int) -> dict:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    con.close()
    if not r:
        raise SystemExit(f"no pipeline row #{app_id}")
    return dict(r)


def out_path(r: dict) -> Path:
    return ROOT / "data" / "artifacts" / slug(r["company"], r["role"]) / f"verdict-{r['id']}.json"


def posting_text(r: dict) -> str:
    """Stored text, else fetched live. Simplify rows never store the posting, and
    on 2026-09-16 most rows with a recorded verdict had no jd_text at all."""
    jd = (r.get("jd_text") or "").strip()
    if len(jd) < 400 and r.get("url"):
        try:
            from screen_job import fetch_jd
            fetched = fetch_jd(r["url"]) or ""
            if len(fetched) > len(jd) and not fetched.startswith("__"):
                jd = fetched
        except Exception:
            pass
    return re.sub(r"\s+", " ", jd).strip()[:14000]


def build_prompt(r: dict, jd: str | None = None) -> str:
    jd = posting_text(r) if jd is None else jd
    return (f"{card()}\n\nPOSTING #{r['id']}\nCompany: {r['company']}\nRole: {r['role']}\n"
            f"Location: {r.get('location') or 'unstated'}\nURL: {r.get('url') or ''}\n\n{jd or '(no posting text stored)'}")


def salvage(text: str) -> dict:
    """Top-level fields from a JSON answer that stopped part way. The schema puts
    verdict, score, one_line, blockers and risks first for exactly this reason."""
    out = {}
    m = re.search(r'"verdict"\s*:\s*"(apply|maybe|skip)"', text)
    if m:
        out["verdict"] = m.group(1)
    m = re.search(r'"fit_score"\s*:\s*(\d{1,3})', text)
    if m:
        out["fit_score"] = int(m.group(1))
    m = re.search(r'"one_line"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        out["one_line"] = json.loads(f'"{m.group(1)}"')
    for key in ("blockers", "risks", "missing_keywords", "best_evidence"):
        m = re.search(rf'"{key}"\s*:\s*(\[(?:[^\[\]"]|"(?:[^"\\]|\\.)*")*\])', text)
        if m:
            try:
                out[key] = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return out


def validate(v: dict) -> tuple[dict, list[str]]:
    problems, known = [], evidence_ids()

    def clean_ids(ids):
        good = [i for i in (ids or []) if isinstance(i, str) and i in known]
        bad = [i for i in (ids or []) if i not in good]
        if bad:
            problems.append(f"invented evidence ids dropped: {bad}")
        return good

    def nodash(s):
        return re.sub(r"\s*[—–]\s*", ", ", s) if isinstance(s, str) else s

    out = {
        "verdict": v.get("verdict") if v.get("verdict") in ("apply", "maybe", "skip") else "maybe",
        "fit_score": max(0, min(100, int(v.get("fit_score") or 0))) if str(v.get("fit_score", "")).strip().lstrip("-").isdigit() else None,
        "one_line": nodash(str(v.get("one_line") or ""))[:220],
        "blockers": [nodash(str(b)) for b in (v.get("blockers") or [])][:6],
        "risks": [nodash(str(b)) for b in (v.get("risks") or [])][:6],
        "must_haves": [], "missing_keywords": [str(k) for k in (v.get("missing_keywords") or [])][:25],
        "best_evidence": clean_ids(v.get("best_evidence"))[:6],
    }
    if v.get("verdict") not in ("apply", "maybe", "skip"):
        problems.append(f"verdict {v.get('verdict')!r} replaced with 'maybe'")
    for m in (v.get("must_haves") or [])[:15]:
        if isinstance(m, dict):
            out["must_haves"].append({"requirement": nodash(str(m.get("requirement", "")))[:160],
                                      "status": m.get("status") if m.get("status") in ("met", "partial", "missing") else "missing",
                                      "evidence": clean_ids(m.get("evidence"))})
    if out["blockers"] and out["verdict"] == "apply":
        problems.append("verdict 'apply' with blockers downgraded to 'maybe'")
        out["verdict"] = "maybe"
    return out, problems


def run(app_id: int, dry: bool = False, log: bool = True) -> dict | None:
    r = row(app_id)
    prompt = build_prompt(r)
    if dry:
        print(f"#{app_id} {r['company']} / {r['role']}: prompt {len(SYSTEM) + len(prompt):,} chars, nothing sent")
        return None
    # 8000, not 2500: nemotron-3-ultra spends most of its budget on hidden reasoning,
    # and at 3000 two bake-off answers stopped inside must_haves (2026-09-16).
    res = chat("analyst", SYSTEM, prompt, want_json=True, max_tokens=8000, purpose=f"verdict #{app_id}")
    parsed = res["json"] if isinstance(res["json"], dict) else {}
    salvaged = False
    if "verdict" not in parsed or res.get("truncated"):   # cut off: the parser found an inner object
        parsed, salvaged = salvage(res["text"]), True
    v, problems = validate(parsed)
    if salvaged:
        problems.append("answer was cut off; top fields recovered, must_haves lost")
    v.update(app_id=app_id, company=r["company"], role=r["role"], model=res["model"],
             built=datetime.now(timezone.utc).isoformat(timespec="seconds"), validation=problems)
    p = out_path(r)
    is_new = not p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, indent=1) + "\n")
    if log and is_new:
        subprocess.run([sys.executable, str(HERE / "pipeline.py"), "log", str(app_id), "--kind", "note",
                        "--summary", f"NVIDIA verdict ({res['model'].split('/')[-1]}): {v['verdict']} "
                                     f"{v['fit_score']}. {v['one_line']}"[:480]],
                       capture_output=True, text=True)
    return v


def todays_rows() -> list[int]:
    since = datetime.combine(date.today(), dtime()).astimezone(timezone.utc).isoformat()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    ids = [x["id"] for x in con.execute("SELECT * FROM applications WHERE status='discovered' AND discovered_at>=? "
                                        "ORDER BY id", (since,)) if not out_path(dict(x)).exists()]
    con.close()
    return ids


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", type=int, action="append")
    ap.add_argument("--new", action="store_true")
    ap.add_argument("--open", action="store_true", help="every discovered row with no verdict yet, newest first")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--limit", type=int, default=20,
                    help="most rows per run with --new; the rest wait for tomorrow (ultra ran ~70s each)")
    a = ap.parse_args()
    ids = (a.app or []) + (todays_rows()[:a.limit] if a.new else [])
    if a.open:
        con = sqlite3.connect(DB)
        con.row_factory = sqlite3.Row
        ids += [x["id"] for x in con.execute("SELECT * FROM applications WHERE status='discovered' ORDER BY id DESC")
                if not out_path(dict(x)).exists()][:a.limit]
        con.close()
    if not ids:
        print("agent_verdict: nothing to do")
        return 0
    failed = 0
    for i in ids:
        try:
            v = run(i, dry=a.dry_run, log=not a.no_log)
            if v:
                warn = f"  [{'; '.join(v['validation'])}]" if v["validation"] else ""
                print(f"#{i:<4} {v['verdict']:5} {str(v['fit_score']):>3}  {v['company'][:18]:18} {v['one_line'][:110]}{warn}")
        except NimError as e:
            failed += 1
            print(f"#{i:<4} FAILED {e}")
            if "no NVIDIA key" in str(e) or "rejected" in str(e):
                break
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
