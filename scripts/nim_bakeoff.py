#!/usr/bin/env python3
"""Pick the NVIDIA model for each role by measurement, not by name.

The roster in nim.py was a guess. On 2026-09-16 the first ping showed why a guess
is not enough: the model chosen for the fast roles (nemotron-3.5-lightning)
reasons on every call and took 25 to 50 seconds to say one word, and every model
got a simple extraction 5/5, so easy tests do not separate them. This runs the
real verdict task on postings whose right answer the pipeline already recorded.

LABELS come from decisions already made and logged, with the sentence that made
them: AEG, REI Systems, Callan, CHAOS and OneImaging were withdrawn on a posting
sentence; Notion and Applied Intuition on the graduation window; Greenboard,
Commure, Selector, ID.me and Zip were judged worth applying to. Garner, Klaviyo
and Emerson are ambiguous by design and scored only on whether the sponsorship
line is raised at all, as a blocker or a risk.

    nim_bakeoff.py verdict                      every candidate model
    nim_bakeoff.py verdict --models a,b         a subset
    nim_bakeoff.py verdict --write-roster       also save the winner to data/nim_roster.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import nim                                                     # noqa: E402
from agent_verdict import SYSTEM, build_prompt, posting_text, row, salvage, validate   # noqa: E402

CACHE = ROOT / "data" / "nim_bakeoff"
# Each label was checked against the fetched posting text on 2026-09-16, not only
# against the pipeline note: #304 turned out to accept "by Summer 2027" (clean, it
# had been withdrawn in error) and Emerson #248's posting carries no sentence to
# judge, so it is not scored.
BLOCKED = {241: "no visa sponsorship", 258: "clearance", 259: "any employer, no sponsorship",
           276: "US Citizen or Permanent Resident", 254: "University of Florida students only",
           287: "graduating December 2026", 310: "graduate by Dec 2026, start Jan/Feb 2027"}
CLEAN = {243: "Greenboard 2027 grads", 252: "Commure early career 2027", 253: "Selector 0 to 3 years",
         234: "ID.me DS new grad", 136: "Zip new grad 2027 start", 304: "December 2026 or by Summer 2027"}
AMBIGUOUS = {256: "unable to sponsor an employment visa", 261: "not eligible for immigration sponsorship"}
DEFAULT_MODELS = ["nvidia/nemotron-3-super-120b-a12b", "z-ai/glm-5.3-flash", "openai/gpt-oss-20b",
                  "nvidia/nemotron-3-ultra-550b-a55b", "z-ai/glm-5.3"]


def postings() -> dict[int, str]:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    for i in list(BLOCKED) + list(CLEAN) + list(AMBIGUOUS):
        f = CACHE / f"jd-{i}.txt"
        if not f.exists():
            f.write_text(posting_text(row(i)))
        out[i] = f.read_text()
    return out


def verdict_bakeoff(models: list[str], write_roster: bool) -> int:
    texts = postings()
    usable = {i: t for i, t in texts.items() if len(t) >= 400}
    skipped = sorted(set(texts) - set(usable))
    if skipped:
        print(f"no readable posting (dead or unfetchable), skipped: {skipped}")
    results = {}
    for m in models:
        rec = {"blocked_caught": 0, "blocked_n": 0, "clean_passed": 0, "clean_n": 0, "ambiguous_raised": 0,
               "ambiguous_n": 0, "bad_json": 0, "invented_ids": 0, "ms": [], "rows": {}}
        for i, text in usable.items():
            raw = CACHE / "raw" / f"{m.split('/')[-1]}-{i}.json"
            raw.parent.mkdir(parents=True, exist_ok=True)
            try:
                res = nim.chat("analyst", SYSTEM, build_prompt(row(i), text), want_json=True, max_tokens=8000,
                               purpose=f"bakeoff verdict #{i}", model=m)
                raw.write_text(json.dumps({"model": m, "app": i, "ms": res["ms"], "text": res["text"]}, indent=1))
                parsed = res["json"] if isinstance(res["json"], dict) else {}
                if "verdict" not in parsed:
                    parsed = salvage(res["text"])
                v, problems = validate(parsed)
                rec["ms"].append(res["ms"])
                rec["invented_ids"] += sum(1 for p in problems if p.startswith("invented"))
            except nim.NimError as e:
                raw.write_text(json.dumps({"model": m, "app": i, "error": str(e)}, indent=1))
                rec["bad_json"] += 1
                rec["rows"][i] = f"FAILED {str(e)[:80]}"
                if i in BLOCKED:
                    rec["blocked_n"] += 1
                elif i in CLEAN:
                    rec["clean_n"] += 1
                else:
                    rec["ambiguous_n"] += 1
                continue
            flagged = bool(v["blockers"]) or v["verdict"] == "skip"
            raised = flagged or any(re.search(r"sponsor|authoriz", x, re.I) for x in v["risks"])
            if i in BLOCKED:
                rec["blocked_n"] += 1
                rec["blocked_caught"] += flagged
            elif i in CLEAN:
                rec["clean_n"] += 1
                rec["clean_passed"] += not flagged
            else:
                rec["ambiguous_n"] += 1
                rec["ambiguous_raised"] += raised
            rec["rows"][i] = f"{v['verdict']} {v['fit_score']} blockers={len(v['blockers'])} :: {v['one_line'][:90]}"
        n = rec["blocked_n"] + rec["clean_n"]
        rec["accuracy"] = round((rec["blocked_caught"] + rec["clean_passed"]) / n, 3) if n else 0
        ms = sorted(rec["ms"])
        rec["median_ms"] = ms[len(ms) // 2] if ms else None
        results[m] = rec
        print(f"{m:42} acc {rec['accuracy']:.2f}  blockers {rec['blocked_caught']}/{rec['blocked_n']}  "
              f"clean {rec['clean_passed']}/{rec['clean_n']}  ambiguous raised {rec['ambiguous_raised']}/{rec['ambiguous_n']}  "
              f"bad {rec['bad_json']}  invented ids {rec['invented_ids']}  median {rec['median_ms']}ms", flush=True)

    stamp = time.strftime("%Y-%m-%d")
    for m, rec in results.items():                 # one file per model, so parallel runs never overwrite each other
        (CACHE / f"verdict-{stamp}-{m.split('/')[-1]}.json").write_text(json.dumps(rec, indent=1) + "\n")
    # accuracy first, then fewer failures and invented ids, then speed
    ranked = sorted(results, key=lambda m: (-results[m]["accuracy"], results[m]["bad_json"],
                                            results[m]["invented_ids"], results[m]["median_ms"] or 1e9))
    print("\nranking:", " > ".join(x.split("/")[-1] for x in ranked))
    if write_roster and ranked:
        path = nim.ROSTER_OVERRIDE
        roster = json.loads(path.read_text()) if path.exists() else {}
        roster["analyst"] = ranked[:3]
        path.write_text(json.dumps(roster, indent=1) + "\n")
        print(f"analyst roster written: {roster['analyst']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task", choices=["verdict"])
    ap.add_argument("--models")
    ap.add_argument("--write-roster", action="store_true")
    a = ap.parse_args()
    models = a.models.split(",") if a.models else DEFAULT_MODELS
    return verdict_bakeoff(models, a.write_roster)


if __name__ == "__main__":
    sys.exit(main())
