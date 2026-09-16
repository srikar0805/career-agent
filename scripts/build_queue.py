#!/usr/bin/env python3
"""Write data/logs/QUEUE.md: what a human needs to act on today.

The launchd job collects data unattended but CANNOT run Claude. Verified
2026-08-20 by probing a real launchd agent: `claude --print` fails there with
"OAuth session expired and could not be refreshed", because a launchd agent
cannot refresh the token. So the daily run ends by leaving a short readable
queue instead. Open Claude whenever you like and the judgement work starts
from this file rather than from nothing.
"""
import sqlite3, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
c = sqlite3.connect(ROOT / "data" / "pipeline.db")
today = dt.date.today()
out = [f"# Waiting for you, {today}", "",
       "Collected by launchd. Claude cannot run unattended, so this is the handoff.", ""]

# discovered_at is written in UTC. The 23:32 CDT run on 2026-09-14 committed
# nine rows stamped 2026-09-15T04:32Z, and date(discovered_at)=today missed all
# nine, so QUEUE.md said "0 new postings" under a log that listed them. Compare
# against local midnight expressed in UTC instead of against the bare date.
since = dt.datetime.combine(today, dt.time()).astimezone(dt.timezone.utc).isoformat()
# Every source, not just Simplify. Until 2026-09-16 this read source='simplify',
# so no Dice, data-board or ATS-sweep find ever reached the queue: 11 Dice rows,
# 11 data-board rows and all 23 open discover_ats rows were invisible here.
new = list(c.execute(
    "SELECT id,company,role,location,url,COALESCE(NULLIF(source,''),'data boards') FROM applications "
    "WHERE discovered_at>=? AND status='discovered' ORDER BY id",
    (since,)))
out.append(f"## {len(new)} new qualified postings")

# A prefilled application packet per posting (scripts/prefill.py). Staged
# submission, chosen 2026-09-16: he reads the packet and presses submit himself.
# The one-line summary is here so a cohort WARNING or a form BLOCKER is seen
# BEFORE he picks a posting to build a resume for.
try:
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from prefill import write_packet
except Exception as e:                       # never let the queue die with it
    write_packet = None
    print(f"  prefill unavailable: {type(e).__name__}: {e}")
for r in new:
    out.append(f"- **#{r[0]}  {r[1]} - {r[2]}**  ({r[3] or ''})  _via {r[5]}_")
    if r[4]:
        out.append(f"  {r[4]}")
    if write_packet and len(new) <= 60:
        try:
            path, _, info = write_packet(r[0])
            k = info["counts"]
            out.append(f"  packet: `{path.relative_to(ROOT)}`  form {info['verdict']}, "
                       f"{k.get('FILLED', 0)} filled, {k.get('CONFIRM', 0)} to confirm, "
                       f"{info['open_required']} required still blank")
            for b in info["blockers"]:
                out.append(f"  **BLOCKER** {b[:100]}")
            for w in info["warnings"]:
                out.append(f"  **WARNING** {w[:100]}")
        except Exception as e:
            out.append(f"  packet failed: {type(e).__name__}")
if not new:
    out.append("_none today_")

out += ["", "## Needs a follow-up"]
any_fu = False
for r in c.execute("SELECT id,company,role,applied_at,status FROM applications "
                   "WHERE status IN ('applied','screening') ORDER BY applied_at"):
    if not r[3]:
        out.append(f"- #{r[0]}  {r[1]}  **unverified**, no confirmation email found")
        any_fu = True
        continue
    if r[4] == "screening":
        continue
    # applied_at is written two ways: a bare date from a manual backfill, and a
    # full ISO timestamp with an offset from pipeline.py move. date.fromisoformat
    # rejects the second, which crashed this script every day from 2026-08-30 to
    # 2026-09-07 and left QUEUE.md frozen at 29 August.
    age = (today - dt.date.fromisoformat(r[3][:10])).days
    if age >= 14:
        out.append(f"- #{r[0]}  **{age}d**  {r[1]} - {r[2][:44]}  **follow up**"); any_fu = True
    elif age >= 10:
        out.append(f"- #{r[0]}  {age}d  {r[1]} - {r[2][:44]}  due soon"); any_fu = True
if not any_fu:
    out.append("_nothing due_")

(ROOT / "data" / "logs" / "QUEUE.md").write_text("\n".join(out) + "\n")
print(f"  wrote data/logs/QUEUE.md ({len(new)} new postings)")
