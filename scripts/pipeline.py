#!/usr/bin/env python3
"""Pipeline CRM. The memory layer for every skill in this repo.

Skills read from this so they never repeat themselves: /follow-up knows what
was already sent, /cold-message-manager knows whether you already contacted
someone at that company, /career knows what is going stale.

Usage:
    pipeline.py add --company Stripe --role "ML Engineer" [--url ...] [--track job]
    pipeline.py move <id> applied
    pipeline.py list [--status applied] [--track job] [--company Stripe] [--json]
    pipeline.py show <id>
    pipeline.py log <id> --kind cold_message --direction out --summary "..." [--body-file f.md]
    pipeline.py contact --name "Jane Roe" --company Stripe [--relationship connection]
    pipeline.py task <id> --kind follow_up --description "..." --due 2026-08-05
    pipeline.py due [--days 0]
    pipeline.py stale [--days 10]
    pipeline.py artifact <id> --kind resume --path ... [--score 84] [--verdict INTERVIEW]
    pipeline.py stats [--track job]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, init, now, STAGES, TERMINAL, ALL_STATUSES, TRACKS  # noqa: E402


def _conn() -> sqlite3.Connection:
    return init()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).days


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------- commands

def cmd_add(a) -> int:
    if a.track not in TRACKS:
        print(f"track must be one of {TRACKS}", file=sys.stderr)
        return 2
    conn = _conn()
    ts = now()
    try:
        cur = conn.execute(
            """INSERT INTO applications
               (track, company, role, url, source, location, remote, status,
                sponsors, jd_text, notes, discovered_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (a.track, a.company, a.role, a.url, a.source, a.location, a.remote,
             a.status, a.sponsors, a.jd, a.notes, ts, ts),
        )
        conn.commit()
        print(f"#{cur.lastrowid}  {a.company} / {a.role}  [{a.status}]")
        return 0
    except sqlite3.IntegrityError:
        existing = conn.execute(
            "SELECT id, status FROM applications WHERE company=? AND role=? AND (url IS ? OR url=?)",
            (a.company, a.role, a.url, a.url),
        ).fetchone()
        if existing:
            print(f"already tracked as #{existing['id']} [{existing['status']}]")
            return 0
        raise


def cmd_move(a) -> int:
    if a.status not in ALL_STATUSES:
        print(f"status must be one of {ALL_STATUSES}", file=sys.stderr)
        return 2
    conn = _conn()
    row = conn.execute("SELECT * FROM applications WHERE id=?", (a.id,)).fetchone()
    if not row:
        print(f"no application #{a.id}", file=sys.stderr)
        return 2

    fields = {"status": a.status, "updated_at": now()}
    if a.status == "applied" and not row["applied_at"]:
        fields["applied_at"] = now()
    if a.status in TERMINAL:
        fields["closed_at"] = now()

    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE applications SET {sets} WHERE id=?", (*fields.values(), a.id))
    conn.execute(
        """INSERT INTO interactions
           (application_id, kind, direction, summary, occurred_at, created_at)
           VALUES (?,?,?,?,?,?)""",
        (a.id, "status_change", "in" if a.status in TERMINAL else "out",
         f"{row['status']} -> {a.status}", now(), now()),
    )
    conn.commit()
    print(f"#{a.id}  {row['company']} / {row['role']}:  {row['status']} -> {a.status}")
    return 0


def cmd_list(a) -> int:
    conn = _conn()
    where, params = [], []
    if a.status:
        where.append("status=?"); params.append(a.status)
    if a.track:
        where.append("track=?"); params.append(a.track)
    if a.company:
        where.append("company LIKE ?"); params.append(f"%{a.company}%")
    if a.open:
        where.append(f"status NOT IN ({','.join('?' * len(TERMINAL))})"); params += TERMINAL

    sql = "SELECT * FROM applications"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE status " + " ".join(
        f"WHEN '{s}' THEN {i}" for i, s in enumerate(ALL_STATUSES)
    ) + " END DESC, updated_at DESC"

    rows = _rows(conn.execute(sql, params))
    if a.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("nothing matches")
        return 0

    print(f"{'ID':<5}{'STATUS':<14}{'FIT':<5}{'AGE':<6}{'COMPANY':<24}ROLE")
    print("-" * 96)
    for r in rows:
        age = _days_since(r["updated_at"])
        print(f"{r['id']:<5}{r['status']:<14}"
              f"{(str(r['fit_score']) if r['fit_score'] is not None else '-'):<5}"
              f"{(f'{age}d' if age is not None else '-'):<6}"
              f"{r['company'][:23]:<24}{r['role'][:44]}")
    print(f"\n{len(rows)} shown")
    return 0


def cmd_show(a) -> int:
    conn = _conn()
    app = conn.execute("SELECT * FROM applications WHERE id=?", (a.id,)).fetchone()
    if not app:
        print(f"no application #{a.id}", file=sys.stderr)
        return 2
    app = dict(app)

    ints = _rows(conn.execute(
        "SELECT * FROM interactions WHERE application_id=? ORDER BY occurred_at", (a.id,)))
    arts = _rows(conn.execute(
        "SELECT * FROM artifacts WHERE application_id=? ORDER BY created_at", (a.id,)))
    tsks = _rows(conn.execute(
        "SELECT * FROM tasks WHERE application_id=? AND status='open' ORDER BY due_date", (a.id,)))

    if a.json:
        print(json.dumps({"application": app, "interactions": ints,
                          "artifacts": arts, "open_tasks": tsks}, indent=2))
        return 0

    print(f"#{app['id']}  {app['company']} / {app['role']}")
    print(f"  status    {app['status']}   fit {app['fit_score'] or '-'}   track {app['track']}")
    print(f"  location  {app['location'] or '-'}  ({app['remote'] or '-'})")
    print(f"  source    {app['source'] or '-'}")
    if app["url"]:
        print(f"  url       {app['url']}")
    if app["sponsors"] is not None:
        print(f"  sponsors  {'yes' if app['sponsors'] else 'NO'}")
    print(f"  applied   {app['applied_at'] or 'not yet'}")
    if app["notes"]:
        print(f"  notes     {app['notes']}")

    if ints:
        print("\n  history")
        for i in ints:
            d = "->" if i["direction"] == "out" else "<-"
            print(f"    {i['occurred_at'][:10]}  {d} {i['kind']:<15} {i['summary']}")
    if arts:
        print("\n  artifacts")
        for x in arts:
            sc = f" score {x['score']}" if x["score"] is not None else ""
            vd = f" [{x['verdict']}]" if x["verdict"] else ""
            print(f"    {x['kind']:<15}{x['path']}{sc}{vd}")
    if tsks:
        print("\n  open tasks")
        for t in tsks:
            print(f"    due {t['due_date'] or '-'}  {t['kind']:<12}{t['description']}")
    return 0


def cmd_log(a) -> int:
    conn = _conn()
    body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else a.body
    conn.execute(
        """INSERT INTO interactions
           (application_id, contact_id, kind, direction, channel, summary, body,
            occurred_at, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (a.id, a.contact, a.kind, a.direction, a.channel, a.summary, body,
         a.at or now(), now()),
    )
    conn.execute("UPDATE applications SET updated_at=? WHERE id=?", (now(), a.id))
    conn.commit()
    print(f"logged {a.kind} on #{a.id}")
    return 0


def cmd_contact(a) -> int:
    conn = _conn()
    try:
        cur = conn.execute(
            """INSERT INTO contacts
               (name, title, company, email, linkedin_url, relationship, connected_on, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (a.name, a.title, a.company, a.email, a.linkedin, a.relationship,
             a.connected_on, a.notes, now()),
        )
        conn.commit()
        print(f"contact #{cur.lastrowid}  {a.name} ({a.company or '?'})  [{a.relationship}]")
    except sqlite3.IntegrityError:
        row = conn.execute("SELECT id FROM contacts WHERE name=? AND company IS ?",
                           (a.name, a.company)).fetchone()
        print(f"already known as contact #{row['id'] if row else '?'}")
    return 0


def cmd_task(a) -> int:
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO tasks (application_id, contact_id, kind, description, due_date, created_at)
           VALUES (?,?,?,?,?,?)""",
        (a.id, a.contact, a.kind, a.description, a.due, now()),
    )
    conn.commit()
    print(f"task #{cur.lastrowid} due {a.due or 'unscheduled'}: {a.description}")
    return 0


def cmd_done(a) -> int:
    conn = _conn()
    conn.execute("UPDATE tasks SET status='done', completed_at=? WHERE id=?", (now(), a.task_id))
    conn.commit()
    print(f"task #{a.task_id} done")
    return 0


def cmd_due(a) -> int:
    conn = _conn()
    cutoff = (datetime.now(timezone.utc).date() + timedelta(days=a.days)).isoformat()
    rows = _rows(conn.execute(
        """SELECT t.*, a.company, a.role, c.name AS contact_name
           FROM tasks t
           LEFT JOIN applications a ON a.id = t.application_id
           LEFT JOIN contacts c ON c.id = t.contact_id
           WHERE t.status='open' AND t.due_date IS NOT NULL AND t.due_date <= ?
           ORDER BY t.due_date""", (cutoff,)))
    if a.json:
        print(json.dumps(rows, indent=2)); return 0
    if not rows:
        print(f"nothing due through {cutoff}")
        return 0
    print(f"due through {cutoff}\n")
    for t in rows:
        overdue = t["due_date"] < _today()
        mark = "OVERDUE" if overdue else "       "
        who = t["company"] or t["contact_name"] or "-"
        print(f"  {mark} {t['due_date']}  #{t['id']:<4}{t['kind']:<12}{who[:20]:<22}{t['description']}")
    return 0


def cmd_stale(a) -> int:
    """Applications sitting in a non-terminal stage with no movement.

    This is the single most useful query in the whole system. Job searches die
    in silence, not in rejection.
    """
    conn = _conn()
    rows = _rows(conn.execute(
        f"""SELECT * FROM applications
            WHERE status NOT IN ({','.join('?' * len(TERMINAL))})
              AND status != 'discovered'
            ORDER BY updated_at""", TERMINAL))
    stale = [(r, _days_since(r["updated_at"])) for r in rows]
    stale = [(r, d) for r, d in stale if d is not None and d >= a.days]

    if a.json:
        print(json.dumps([{**r, "days_quiet": d} for r, d in stale], indent=2)); return 0
    if not stale:
        print(f"nothing quiet for {a.days}+ days")
        return 0
    print(f"quiet for {a.days}+ days\n")
    for r, d in stale:
        print(f"  {d:>3}d  #{r['id']:<4}{r['status']:<14}{r['company'][:22]:<24}{r['role'][:40]}")
    print("\nRun /follow-up on these.")
    return 0


def cmd_artifact(a) -> int:
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO artifacts (application_id, kind, path, score, verdict, evidence_ids, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (a.id, a.kind, a.path, a.score, a.verdict, a.evidence, now()),
    )
    # Only a document score belongs in applications.fit_score. A /fit-analysis
    # result is a different measurement on a different scale, and writing it
    # here silently overwrote the resume-judge score for the same application.
    if a.score is not None and a.kind not in ("fit_analysis",):
        conn.execute("UPDATE applications SET fit_score=?, updated_at=? WHERE id=?",
                     (a.score, now(), a.id))
    conn.commit()
    print(f"artifact #{cur.lastrowid} {a.kind} -> #{a.id}")
    return 0


def cmd_stats(a) -> int:
    conn = _conn()
    params = [a.track] if a.track else []
    clause = "WHERE track=?" if a.track else ""

    counts = {r["status"]: r["n"] for r in conn.execute(
        f"SELECT status, COUNT(*) n FROM applications {clause} GROUP BY status", params)}
    total = sum(counts.values())

    if a.json:
        print(json.dumps({"total": total, "by_status": counts}, indent=2)); return 0

    if total == 0:
        print("pipeline is empty. Run /job-hunt to fill it.")
        return 0

    label = f" [{a.track}]" if a.track else ""
    print(f"pipeline{label}: {total} total\n")

    for s in ALL_STATUSES:
        n = counts.get(s, 0)
        if n:
            bar = "#" * min(n, 40)
            print(f"  {s:<14}{n:>4}  {bar}")

    # Funnel conversion. Everything at or past a stage counts as having reached it,
    # so a rejected candidate who interviewed still counts toward 'interviewing'.
    print("\nconversion")
    reached = {}
    for i, s in enumerate(STAGES):
        rows = conn.execute(
            f"""SELECT COUNT(*) n FROM applications
                WHERE {'track=? AND ' if a.track else ''}
                (status IN ({','.join('?' * (len(STAGES) - i))})
                 OR (status IN ({','.join('?' * len(TERMINAL))})
                     AND id IN (SELECT application_id FROM interactions
                                WHERE summary LIKE '%-> {s}%')))""",
            params + STAGES[i:] + TERMINAL).fetchone()
        reached[s] = rows["n"]

    prev = None
    for s in STAGES:
        n = reached[s]
        rate = f"{100 * n / prev:.0f}%" if prev else "   "
        print(f"  {s:<14}{n:>4}  {rate:>5}")
        prev = n if n else None

    offers = counts.get("offer", 0) + counts.get("accepted", 0)
    applied = reached.get("applied", 0)
    if applied:
        print(f"\n  applied -> offer: {100 * offers / applied:.1f}%  ({offers}/{applied})")

    open_tasks = conn.execute(
        "SELECT COUNT(*) n FROM tasks WHERE status='open' AND due_date <= ?", (_today(),)
    ).fetchone()["n"]
    if open_tasks:
        print(f"\n  {open_tasks} task(s) due today or overdue. Run: pipeline.py due")
    return 0


def cmd_contacts_at(a) -> int:
    """Who do I already know here? Drives warm intro before cold outreach."""
    conn = _conn()
    rows = _rows(conn.execute(
        "SELECT * FROM contacts WHERE company LIKE ? ORDER BY relationship, name",
        (f"%{a.company}%",)))
    if a.json:
        print(json.dumps(rows, indent=2)); return 0
    if not rows:
        print(f"no known contacts at {a.company}. Cold outreach it is.")
        return 0
    print(f"contacts at {a.company}\n")
    for c in rows:
        print(f"  {c['relationship']:<12}{c['name'][:26]:<28}{c['title'] or '-'}")
    return 0


# ---------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="career-agent pipeline CRM")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add", help="track a new application")
    s.add_argument("--company", required=True)
    s.add_argument("--role", required=True)
    s.add_argument("--url"); s.add_argument("--source"); s.add_argument("--location")
    s.add_argument("--remote", choices=["onsite", "hybrid", "remote"])
    s.add_argument("--track", default="job", choices=TRACKS)
    s.add_argument("--status", default="discovered", choices=ALL_STATUSES)
    s.add_argument("--sponsors", type=int, choices=[0, 1])
    s.add_argument("--jd", help="full posting text")
    s.add_argument("--notes")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("move", help="change status")
    s.add_argument("id", type=int); s.add_argument("status")
    s.set_defaults(fn=cmd_move)

    s = sub.add_parser("list")
    s.add_argument("--status"); s.add_argument("--track"); s.add_argument("--company")
    s.add_argument("--open", action="store_true", help="exclude closed")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("show"); s.add_argument("id", type=int)
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_show)

    s = sub.add_parser("log", help="record an interaction")
    s.add_argument("id", type=int)
    s.add_argument("--kind", required=True); s.add_argument("--direction", default="out",
                                                            choices=["out", "in"])
    s.add_argument("--summary", required=True); s.add_argument("--body")
    s.add_argument("--body-file"); s.add_argument("--channel"); s.add_argument("--contact", type=int)
    s.add_argument("--at"); s.set_defaults(fn=cmd_log)

    s = sub.add_parser("contact")
    s.add_argument("--name", required=True); s.add_argument("--title"); s.add_argument("--company")
    s.add_argument("--email"); s.add_argument("--linkedin"); s.add_argument("--connected-on")
    s.add_argument("--relationship", default="cold",
                   choices=["cold", "connection", "colleague", "referrer"])
    s.add_argument("--notes"); s.set_defaults(fn=cmd_contact)

    s = sub.add_parser("task"); s.add_argument("id", type=int, nargs="?")
    s.add_argument("--kind", required=True); s.add_argument("--description", required=True)
    s.add_argument("--due"); s.add_argument("--contact", type=int); s.set_defaults(fn=cmd_task)

    s = sub.add_parser("done"); s.add_argument("task_id", type=int); s.set_defaults(fn=cmd_done)

    s = sub.add_parser("due"); s.add_argument("--days", type=int, default=0)
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_due)

    s = sub.add_parser("stale"); s.add_argument("--days", type=int, default=10)
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_stale)

    s = sub.add_parser("artifact"); s.add_argument("id", type=int)
    s.add_argument("--kind", required=True); s.add_argument("--path", required=True)
    s.add_argument("--score", type=int); s.add_argument("--verdict")
    s.add_argument("--evidence", help="comma separated EV-* ids"); s.set_defaults(fn=cmd_artifact)

    s = sub.add_parser("stats"); s.add_argument("--track", choices=TRACKS)
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("who"); s.add_argument("company")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_contacts_at)

    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    sys.exit(args.fn(args))
