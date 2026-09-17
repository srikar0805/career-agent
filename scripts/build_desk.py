#!/usr/bin/env python3
"""Build the Application Desk page from the pipeline. The whole page, every run.

Redesigned 2026-09-16 at Srikar's request, in the visual language of Tsenta's dashboard
(pill states, a match-% card row, a dark pipeline board, a sidebar with live counts),
under the desk's own name. Until then this script only swapped two <tbody> blocks inside
a hand-edited page, so anything not in those tables went stale between edits.

Sources, all read-only:
  data/pipeline.db                      applications, artifacts, tasks, contacts
  data/logs/batch-*.json                prepared applications (fast resumes and packets)
  data/artifacts/*/verdict-<id>.json    fit scores
  data/artifacts/*/fit_analysis.md      the full fit analysis per application, readable in a side panel
                                        (Srikar, 2026-09-16: "look at each fit analysis for each job I apply")
  data/nim_roster.json, nim-usage.jsonl the agent roster and this month's calls
  data/desk_notes.md                    a few bullet lines Stage 2 may write, instead of hand-editing the HTML

    build_desk.py [out.html]      default data/desk.html

desk_publish_state.py hashes the <div class="n"> counters and the <tbody> blocks, so both
stay in this markup on purpose.
"""
from __future__ import annotations

import glob
import html
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "pipeline.db"
DESK = REPO / "data" / "desk.html"

PLATFORM = [("Greenhouse", r"greenhouse|gh_jid"), ("Ashby", r"ashbyhq"), ("Lever", r"lever\.co"),
            ("Workday", r"myworkdayjobs"), ("iCIMS", r"icims"), ("SmartRecruiters", r"smartrecruiters"),
            ("SuccessFactors", r"successfactors"), ("Oracle", r"oraclecloud"), ("Handshake", r"joinhandshake"),
            ("Indeed", r"indeed\.com"), ("Dice", r"dice\.com")]


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def platform(url: str) -> str:
    for name, pat in PLATFORM:
        if re.search(pat, url or "", re.I):
            return name
    return "Company site"


def days_ago(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        d = date.fromisoformat(ts[:10])
    except ValueError:
        return ""
    n = (date.today() - d).days
    return "today" if n <= 0 else "yesterday" if n == 1 else f"{n}d ago"


def load() -> dict:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    apps = [dict(r) for r in con.execute("SELECT * FROM applications WHERE status != 'withdrawn' ORDER BY id DESC")]
    arts = defaultdict(dict)
    fit_paths = defaultdict(list)
    for r in con.execute("SELECT application_id, kind, path, score FROM artifacts ORDER BY id"):
        arts[r["application_id"]][r["kind"]] = r["path"]
        if r["kind"] == "fit_analysis":
            fit_paths[r["application_id"]].append((r["path"], r["score"]))
    today = date.today().isoformat()
    due = defaultdict(list)
    for r in con.execute("SELECT application_id, description FROM tasks WHERE status='open' "
                         "AND kind IN ('follow_up','followup') AND due_date <= ?", (today,)):
        due[r["application_id"]].append(r["description"])
    contacts = [dict(r) for r in con.execute("SELECT * FROM contacts ORDER BY id DESC")]
    con.close()

    batch = {}
    for f in sorted(glob.glob(str(REPO / "data" / "logs" / "batch-*.json"))):
        batch.update({int(k): v for k, v in json.loads(Path(f).read_text()).items()})
    verdicts = {}
    for f in glob.glob(str(REPO / "data" / "artifacts" / "*" / "verdict-*.json")):
        try:
            v = json.loads(Path(f).read_text())
            verdicts[int(v["app_id"])] = v
        except Exception:
            pass
    rfile = REPO / "data" / "nim_roster.json"
    roster = json.loads(rfile.read_text()) if rfile.exists() else {}
    usage = Counter()
    ufile = REPO / "data" / "logs" / "nim-usage.jsonl"
    if ufile.exists():
        month = today[:7]
        for line in ufile.read_text().splitlines()[-6000:]:
            try:
                u = json.loads(line)
            except Exception:
                continue
            if u.get("at", "")[:7] == month and u.get("outcome") == "ok":
                usage[re.split(r" #| dice", u.get("purpose", ""))[0]] += 1
    nfile = REPO / "data" / "desk_notes.md"
    runs = sorted(glob.glob(str(REPO / "data" / "logs" / "daily-*.log")))
    analyses = {}
    for app_id, paths in fit_paths.items():
        x = analysis_of(app_id, paths)
        if x:
            analyses[app_id] = x
    return {"apps": apps, "arts": arts, "due": due, "contacts": contacts, "batch": batch, "verdicts": verdicts,
            "analyses": analyses,
            "roster": roster, "usage": usage, "notes": nfile.read_text() if nfile.exists() else "",
            "last_run": Path(runs[-1]).stem.replace("daily-", "") if runs else "not yet"}


RECS = {"APPLY IMMEDIATELY": ("Apply now", "p-good"), "APPLY WITH RESUME TAILORING": ("Tailor first", "p-warn"),
        "UPSKILL FIRST": ("Upskill first", "p-warn"), "LOOK ELSEWHERE": ("Look elsewhere", "p-crit")}


def md_html(text: str) -> str:
    """Markdown to HTML with raw HTML escaped. The early analyses are preformatted text, not Markdown."""
    if len(re.findall(r"^#{2,4}\s", text, re.M)) < 3:
        return f'<pre class="plain">{esc(text.strip())}</pre>'
    try:
        import mistune
        return mistune.create_markdown(escape=True, plugins=["table", "strikethrough"])(text)
    except Exception:
        return f'<pre class="plain">{esc(text.strip())}</pre>'


def analysis_of(app_id: int, paths: list[tuple[str, int | None]]) -> dict | None:
    """The newest readable fit analysis for one application, with its scores and who wrote it."""
    for p, logged_score in reversed(paths):
        f = Path(p) if Path(p).is_absolute() else REPO / p
        if f.suffix != ".md" or not f.exists():
            continue
        text = f.read_text(errors="replace")
        meta = {}
        j = f.with_name("fit_analysis.json")
        if j.exists():
            try:
                meta = json.loads(j.read_text())
            except Exception:
                meta = {}
            if meta.get("app_id") != app_id:
                meta = {}
        by = re.search(r"<!-- fit analysis by (\S+)", text)
        checks = re.search(r"^> \*\*Automated checks:\*\* (.*?)\s*$", text, re.M)
        tries = re.search(r"^> \*\*Attempts:\*\* (.*?)\s*$", text, re.M)
        body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        body = "\n".join(l for l in body.splitlines() if not re.match(r"> \*\*(Written by|Automated checks|Attempts):", l)).strip()
        paper = meta.get("paper")
        if paper is None:
            m = (re.search(r"paper\s+fit\s*:?\s*\**\s*(\d{1,3})\s*%", body, re.I) or re.search(r"OVERALL FIT\s*:?\s*\**\s*(\d{1,3})\s*%", body, re.I)
                 or re.search(r"Overall Fit Score[^\d\n]{0,40}\n?[^\d\n]{0,40}?(\d{1,3})\s*%", body, re.I))
            paper = int(m.group(1)) if m else logged_score
        real = meta.get("realistic")
        if real is None:
            m = re.search(r"realistic\s*:?\s*\**\s*(\d{1,3})\s*%", body, re.I)
            real = int(m.group(1)) if m else None
        rec = meta.get("recommendation")
        if not rec:
            tail = body[body.upper().rfind("RECOMMENDATION"):] if "RECOMMENDATION" in body.upper() else body
            found = [(tail.upper().find(v), v) for v in RECS if v in tail.upper()]
            rec = min(found)[1] if found else None
        model = meta.get("model") or (by.group(1) if by else "")
        if checks:
            passed = checks.group(1).startswith("all passed")
            problems = [] if passed else meta.get("problems") or [s.strip() for s in checks.group(1).split(";") if s.strip()]
        else:
            passed, problems = None, []
        return {"paper": paper, "realistic": real, "rec": rec, "model": model.split("/")[-1] if model else "Claude",
                "passed": passed, "problems": problems, "attempts": meta.get("attempts") or
                ([s.strip() for s in tries.group(1).split("|")] if tries else []),
                "at": (meta.get("at") or "")[:10], "html": md_html(body)}
    return None


def state_of(a: dict, D: dict) -> tuple[str, str]:
    """(tab key, pill label) for one application."""
    s, b = a["status"], D["batch"].get(a["id"], {})
    if s == "applied":
        return ("applied", "Follow up") if D["due"].get(a["id"]) else ("applied", "Applied")
    if s == "screening":
        return "process", "In process"
    if s == "rejected":
        return "closed", "Rejected"
    bs = b.get("state")
    if bs == "READY":
        return ("needs", "Ready, check") if (b.get("skills_confirm") or b.get("required_blank")) else ("ready", "Ready")
    if bs in ("YOUR CALL", "MANUAL", "BUILD FAILED"):
        return "needs", {"YOUR CALL": "Your call", "MANUAL": "Open manually", "BUILD FAILED": "Build failed"}[bs]
    if bs == "SKIPPED":
        return "closed", "Skipped"
    return "queued", "Queued"


PILL = {"Ready": "p-good", "Applied": "p-ink", "In process": "p-good", "Follow up": "p-warn", "Ready, check": "p-warn",
        "Your call": "p-warn", "Open manually": "p-warn", "Build failed": "p-crit", "Rejected": "p-mute",
        "Skipped": "p-mute", "Queued": "p-mute"}


def build() -> str:
    D = load()
    rows = []
    for a in D["apps"]:
        tab, pill = state_of(a, D)
        v = D["verdicts"].get(a["id"], {})
        b = D["batch"].get(a["id"], {})
        tex = D["arts"][a["id"]].get("resume_tex", "")
        resume = D["arts"][a["id"]].get("resume")
        rtype = "" if not resume else ("Fast" if tex.endswith("_fast/main.tex") else "Tailored")
        if b.get("state") in ("YOUR CALL", "MANUAL", "BUILD FAILED", "SKIPPED"):
            why = b.get("why", "")
        elif b.get("skills_confirm"):
            why = "confirm first: " + ", ".join(b["skills_confirm"])
        elif D["due"].get(a["id"]):
            why = D["due"][a["id"]][0]
        else:
            why = v.get("one_line", "")
        rows.append({**a, "tab": tab, "pill": pill, "fit": v.get("fit_score"), "vword": v.get("verdict"),
                     "plat": platform(a.get("url")), "rtype": rtype, "why": why or "",
                     "when": days_ago(a.get("applied_at") or a.get("discovered_at"))})
    tabs = Counter(r["tab"] for r in rows)
    applied_ever = sum(1 for r in rows if r["tab"] in ("applied", "process") or (r["tab"] == "closed" and r["pill"] == "Rejected"))
    due_n = sum(len(v) for v in D["due"].values())
    ready_n = tabs["ready"] + tabs["needs"]
    open_rows = [r for r in rows if r["tab"] in ("ready", "needs", "queued")]
    top = sorted([r for r in open_rows if r["fit"] is not None and r["vword"] != "skip"], key=lambda r: -r["fit"])[:4]

    kpis = [("Ready to submit", ready_n, "prepared, waiting for you", "good"),
            ("Applications sent", applied_ever, "since July", ""),
            ("In process", tabs["process"], "a recruiter replied", "good" if tabs["process"] else ""),
            ("Follow-ups due", due_n, "today or overdue", "warn" if due_n else ""),
            ("Closed", tabs["closed"], "rejected or skipped", "")]
    kpi_html = "".join(f'<div class="kpi {t}"><div class="n">{n}</div><div class="k">{esc(k)}</div><div class="s">{esc(s)}</div></div>'
                       for k, n, s, t in kpis)

    def fitpill(r):
        return f'<span class="fit">{r["fit"]}%</span>' if r["fit"] is not None else '<span class="fit none">no score</span>'

    top_html = "".join(
        f'<article class="match"><div class="mhead">{fitpill(r)}<span class="chip">{esc(r["plat"])}</span></div>'
        f'<div class="mco">{esc(r["company"])}</div><div class="mrole">{esc(r["role"])}</div>'
        f'<div class="mwhy">{esc(r["why"][:150])}</div>'
        f'<div class="mfoot"><span class="loc">{esc((r.get("location") or "")[:34])}</span>'
        f'<a class="btn" href="{esc(r.get("url"))}" target="_blank" rel="noopener">Open posting</a></div></article>'
        for r in top) or '<p class="empty">Fit scores appear here once the verdict agent has scored the open postings.</p>'

    A = D["analyses"]

    def fa_button(r, label="Read"):
        x = A.get(r["id"])
        if not x:
            return '<span class="dim">&ndash;</span>'
        score = f'{x["paper"]}%' if x["paper"] is not None else "open"
        rec = RECS.get(x["rec"] or "", ("", ""))[0]
        return (f'<button type="button" class="fa-btn" data-fa="{r["id"]}" aria-haspopup="dialog" '
                f'aria-label="Read the fit analysis for {esc(r["company"])}"><span class="fa-score">{esc(score)}</span>'
                f'<span>{esc(label)}</span></button>' + (f'<div class="why">{esc(rec)}</div>' if rec else ""))

    def action(r):
        if r["tab"] in ("ready", "needs") and r["plat"] == "Greenhouse" and r["rtype"]:
            cmd = f".venv/bin/python scripts/autofill.py --app {r['id']}"
            return (f'<button class="copy" type="button" data-cmd="{esc(cmd)}" '
                    f'aria-label="Copy the form filler command for {esc(r["company"])}">Copy fill command</button>')
        if not r.get("url"):
            return ""
        label = "View" if r["tab"] in ("applied", "process", "closed") else "Apply"
        return f'<a class="link" href="{esc(r["url"])}" target="_blank" rel="noopener">{label}</a>'

    table_rows = "".join(
        f'<tr data-tab="{r["tab"]}" data-q="{esc((r["company"] + " " + r["role"] + " " + r["plat"]).lower())}">'
        f'<td class="mono dim">#{r["id"]}</td>'
        f'<td><div class="co">{esc(r["company"])}</div><div class="role">{esc(r["role"])}</div></td>'
        f'<td>{fitpill(r)}</td><td>{fa_button(r)}</td><td><span class="chip">{esc(r["plat"])}</span></td>'
        f'<td class="dim">{esc(r["rtype"]) or "&ndash;"}</td>'
        f'<td><span class="pill {PILL.get(r["pill"], "p-mute")}">{esc(r["pill"])}</span>'
        + (f'<div class="why">{esc(r["why"][:120])}</div>' if r["why"] and r["tab"] in ("needs", "applied", "closed") else "")
        + f'</td><td class="dim nowrap">{esc(r["when"])}</td><td class="act">{action(r)}</td></tr>'
        for r in rows)

    tab_defs = [("all", "All", len(rows)), ("ready", "Ready", tabs["ready"]), ("needs", "Needs you", tabs["needs"]),
                ("applied", "Applied", tabs["applied"]), ("process", "In process", tabs["process"]),
                ("closed", "Closed", tabs["closed"]), ("queued", "Queued", tabs["queued"])]
    tabs_html = "".join(f'<button type="button" role="tab" class="tab{" on" if k == "all" else ""}" data-tab="{k}" id="tab-{k}" '
                        f'aria-selected="{"true" if k == "all" else "false"}">{esc(label)}<span class="cnt">{n}</span></button>'
                        for k, label, n in tab_defs if n or k == "all")

    def lane(title, keys, sub):
        members = [r for r in rows if r["tab"] in keys]
        cards = "".join(f'<li><span class="lco">{esc(r["company"])}</span><span class="lwhen">{esc(r["when"])}</span>'
                        f'<span class="lrole">{esc(r["role"])}</span></li>' for r in members[:4])
        return (f'<section class="lane"><header><span class="ltitle">{esc(title)}</span><span class="lnum">{len(members)}</span></header>'
                f'<p class="lsub">{esc(sub)}</p><ul>{cards}</ul></section>')
    board = (lane("Ready", ("ready", "needs"), "resume and packet built") + lane("Applied", ("applied",), "you pressed submit")
             + lane("In process", ("process",), "a human replied") + lane("Closed", ("closed",), "rejected or skipped"))

    def meter(label, n):
        w = 0 if n is None else max(2, min(100, n))
        return (f'<div class="meter"><span class="mlabel">{label}</span><span class="mtrack"><span style="width:{w}%"></span></span>'
                f'<span class="mval">{"&ndash;" if n is None else f"{n}%"}</span></div>')

    def checks_chip(x):
        if x["passed"] is None:
            return f'<span class="chip">by {esc(x["model"])}</span>'
        return (f'<span class="chip">{esc(x["model"])}, checks passed</span>' if x["passed"]
                else f'<span class="chip warnchip">{esc(x["model"])}, {len(x["problems"])} check(s) failed</span>')

    sent = [r for r in rows if r["tab"] in ("applied", "process") and r["id"] in A]
    sent.sort(key=lambda r: r.get("applied_at") or "", reverse=True)
    fa_cards = "".join(
        f'<article class="fa-card"><div class="mhead"><span class="pill {RECS.get(A[r["id"]]["rec"] or "", ("", "p-mute"))[1]}">'
        f'{esc(RECS.get(A[r["id"]]["rec"] or "", ("No recommendation", ""))[0])}</span><span class="dim small">{esc(r["when"])}</span></div>'
        f'<div class="mco">{esc(r["company"])}</div><div class="mrole">{esc(r["role"])}</div>'
        + meter("Paper fit", A[r["id"]]["paper"]) + meter("Realistic", A[r["id"]]["realistic"])
        + f'<div class="mfoot">{checks_chip(A[r["id"]])}{fa_button(r, "Read analysis").split("<div")[0]}</div></article>'
        for r in sent[:8]) or '<p class="empty">Analyses for the jobs you applied to appear here as the fit agent writes them.</p>'
    missing_sent = sum(1 for r in rows if r["tab"] in ("applied", "process") and r["id"] not in A)

    templates = "".join(
        f'<template class="fa-src" id="fa-{i}" data-co="{esc(next((r["company"] for r in rows if r["id"] == i), ""))}" '
        f'data-role="{esc(next((r["role"] for r in rows if r["id"] == i), ""))}">'
        f'<div class="fa-meta">'
        + (f'<span class="pill {RECS[x["rec"]][1]}">{esc(RECS[x["rec"]][0])}</span>' if x["rec"] in RECS else "")
        + f'<span class="fa-num"><b>{"&ndash;" if x["paper"] is None else str(x["paper"]) + "%"}</b> paper fit</span>'
        f'<span class="fa-num"><b>{"&ndash;" if x["realistic"] is None else str(x["realistic"]) + "%"}</b> realistic</span>'
        + checks_chip(x) + (f'<span class="dim small">{esc(x["at"])}</span>' if x["at"] else "") + '</div>'
        + (f'<details class="fa-checks"><summary>What the checks found</summary><ul>'
           + "".join(f"<li>{esc(p)}</li>" for p in x["problems"]) + "</ul>"
           + (f'<p class="dim small">Attempts: {esc(" | ".join(x["attempts"]))}</p>' if x["attempts"] else "") + "</details>"
           if x["problems"] else
           (f'<p class="fa-tries dim small">Attempts: {esc(" | ".join(x["attempts"]))}</p>' if len(x["attempts"]) > 1 else ""))
        + f'<div class="fa-md">{x["html"]}</div></template>'
        for i, x in A.items() if any(r["id"] == i for r in rows))

    plat_counts = Counter(r["plat"] for r in open_rows)
    maxp = max(plat_counts.values()) if plat_counts else 1
    how = {"Greenhouse": "form fills itself", "Ashby": "packet to paste", "Lever": "packet to paste"}
    plat_html = "".join(
        f'<div class="prow"><span class="pname">{esc(p)}</span>'
        f'<span class="pbar"><span style="width:{max(4, round(100 * n / maxp))}%"></span></span><span class="pnum">{n}</span>'
        f'<span class="pnote">{how.get(p, "account needed" if p in ("Workday", "iCIMS", "SuccessFactors", "Oracle") else "open the link")}</span></div>'
        for p, n in plat_counts.most_common())

    by_co = defaultdict(list)
    for c in D["contacts"]:
        by_co[c.get("company") or "Unknown"].append(c)
    rec_html = "".join(
        f'<div class="rco"><div class="rname">{esc(co)}</div><ul>' + "".join(
            f'<li><a href="{esc(c.get("linkedin_url"))}" target="_blank" rel="noopener">{esc(c["name"])}</a>'
            f'<span class="pill {"p-good" if c.get("relationship") in ("connection", "referrer", "colleague") else "p-mute"}">'
            f'{esc(c.get("relationship") or "cold")}</span><span class="rtitle">{esc(c.get("title"))}</span></li>'
            for c in cs[:3]) + '</ul></div>'
        for co, cs in list(by_co.items())[:16])

    R = D["roster"]

    def model(role):
        m = R.get(role) or []
        if not m:
            return '<span class="dim">not set</span>'
        return esc(m[0].split("/")[-1]) + (f'<div class="dim small">then {esc(m[1].split("/")[-1])}</div>' if len(m) > 1 else "")

    def calls(key):
        n = D["usage"].get(key, 0)
        return f"{n} this month" if n else "on demand"
    agents = [
        ("Discovery", "Simplify feed, 54 data boards, 160+ ATS boards", "Python, no model", "daily"),
        ("Job boards", "Dice, and LinkedIn at 2 searches a day", model("scout"), "daily"),
        ("Posting verdicts", "fit score, blockers, missing keywords", model("analyst"), calls("verdict")),
        ("Resumes", "fast build from verified variants; full build for the top ten", "Python, then Claude Opus", "per posting"),
        ("Skills section", "every posting technology you have used", "Python, no model", "every build"),
        ("Bullet keywords", "evidence-backed edits, every PDF check rerun", model("writer"), calls("keywords")),
        ("Fit analysis", "the fit-analysis skill; Kimi first, Ultra when Kimi fails the checks", model("fit"), calls("fit analysis")),
        ("Packets", "every form answer, open-ended answers drafted", model("writer"), "every build"),
        ("Form filler", "fills Greenhouse, stops before Submit", "Playwright, no model", "you run it"),
        ("Mail triage", "rejections and interview requests logged", model("triage"), "daily"),
        ("Recruiter finder", "the right recruiter at each company", model("recruiter"), calls("recruiters")),
    ]
    agents_html = "".join(f'<tr><td class="aname">{esc(n)}</td><td class="dim">{esc(w)}</td><td>{m}</td>'
                          f'<td class="dim nowrap">{esc(c)}</td></tr>' for n, w, m, c in agents)

    notes_html = ""
    items = [l.lstrip("-* ").strip() for l in D["notes"].splitlines() if l.strip().startswith(("-", "*"))][:8]
    if items:
        notes_html = ('<section class="card notes" id="notes"><h2>Notes from the daily run</h2><ul>'
                      + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul></section>")

    hour = datetime.now().hour
    greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    nav = [("overview", "Overview", ""), ("matches", "Top matches", len(top)), ("analyses", "Fit analyses", len(A)),
           ("applications", "Applications", len(rows)),
           ("pipeline", "Pipeline", ""), ("platforms", "Platforms", len(plat_counts)),
           ("recruiters", "Recruiters", len(D["contacts"])), ("agents", "Agents", len(agents))]
    nav_html = "".join(f'<a href="#{k}" class="nav-i"><span>{esc(l)}</span>'
                       + (f'<span class="ncount">{n}</span>' if n != "" else "") + "</a>" for k, l, n in nav)

    page = TEMPLATE
    for key, val in {"NAV": nav_html, "GREET": greet, "STAMP": esc(datetime.now().strftime("%a %d %b %Y, %H:%M")),
                     "LASTRUN": esc(D["last_run"]), "READY": str(ready_n), "APPLIED": str(applied_ever), "KPIS": kpi_html,
                     "TOP": top_html, "TABS": tabs_html, "ROWS": table_rows, "BOARD": board, "PLATFORMS": plat_html,
                     "RECRUITERS": rec_html or '<p class="empty">No contacts yet.</p>', "AGENTS": agents_html,
                     "NOTES": notes_html, "FACARDS": fa_cards, "TEMPLATES": templates,
                     "FASUB": esc(f"the jobs you applied to, newest first; {len(A)} analyses in all, every one opens from its row"
                                  + (f"; {missing_sent} applied job(s) still without one" if missing_sent else ""))}.items():
        page = page.replace("{{" + key + "}}", val)
    return page


TEMPLATE = r"""<title>Application Desk</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Urbanist:wght@300;400;500;600&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --canvas:#F6F8F6; --surface:#FFFFFF; --ink:#14201A; --body:#34423B; --muted:#5E6D65; --line:#E1E7E2; --line-soft:#EDF1EE;
  --forest:#15362B; --forest-ink:#F4EFE3; --forest-sub:rgba(244,239,227,.64); --forest-line:rgba(244,239,227,.14); --forest-card:rgba(244,239,227,.07);
  --accent:#15362B; --accent-ink:#FFFFFF; --hover:#F1F5F2;
  --mint:#E7F5EE; --mint-ink:#1D6B45; --amber:#FDF1CC; --amber-ink:#7A5410; --rose:#FBE9E4; --rose-ink:#9C3A24;
  --chip:#EEF2EF; --chip-ink:#3D4B44; --focus:#2F7D57;
  --display:"Urbanist","Century Gothic","Avenir Next","Helvetica Neue",Arial,sans-serif;
  --ui:"DM Sans","Helvetica Neue",Arial,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --canvas:#0C1310; --surface:#131C18; --ink:#E6EEE9; --body:#C3CEC8; --muted:#92A198; --line:#243129; --line-soft:#1A2520;
    --forest:#0F2A21; --forest-ink:#F1ECDF; --forest-sub:rgba(241,236,223,.62); --forest-line:rgba(241,236,223,.12); --forest-card:rgba(241,236,223,.06);
    --accent:#7ED3A5; --accent-ink:#0C1310; --hover:#18221E;
    --mint:#16302A; --mint-ink:#8FDDB2; --amber:#3A2E12; --amber-ink:#EBC377; --rose:#3A1E18; --rose-ink:#F0A08C;
    --chip:#1B2621; --chip-ink:#B9C6BF; --focus:#7ED3A5;
  }
}
:root[data-theme="dark"]{
  --canvas:#0C1310; --surface:#131C18; --ink:#E6EEE9; --body:#C3CEC8; --muted:#92A198; --line:#243129; --line-soft:#1A2520;
  --forest:#0F2A21; --forest-ink:#F1ECDF; --forest-sub:rgba(241,236,223,.62); --forest-line:rgba(241,236,223,.12); --forest-card:rgba(241,236,223,.06);
  --accent:#7ED3A5; --accent-ink:#0C1310; --hover:#18221E;
  --mint:#16302A; --mint-ink:#8FDDB2; --amber:#3A2E12; --amber-ink:#EBC377; --rose:#3A1E18; --rose-ink:#F0A08C;
  --chip:#1B2621; --chip-ink:#B9C6BF; --focus:#7ED3A5;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
@media (prefers-reduced-motion: reduce){html{scroll-behavior:auto}}
body{margin:0;background:var(--canvas);color:var(--body);font:14px/1.5 var(--ui);-webkit-font-smoothing:antialiased}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:6px}
.shell{display:grid;grid-template-columns:236px minmax(0,1fr)}
.side{position:sticky;top:0;height:100vh;border-right:1px solid var(--line);background:var(--surface);padding:22px 14px;display:flex;flex-direction:column;gap:22px}
.brand{display:flex;align-items:center;gap:10px;padding:0 8px}
.mark{width:32px;height:32px;border-radius:10px;background:var(--forest);color:var(--forest-ink);display:grid;place-items:center;font:600 13px/1 var(--display);letter-spacing:.03em;flex:none}
.bname{font:600 15px/1.15 var(--display);color:var(--ink)}
.bsub{font-size:11.5px;color:var(--muted)}
.navlist{display:flex;flex-direction:column;gap:2px}
.nav-i{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;border-radius:9px;text-decoration:none;color:var(--body);font-size:13.5px}
.nav-i:hover{background:var(--hover);color:var(--ink)}
.ncount{font:500 11px/1 var(--ui);font-variant-numeric:tabular-nums;background:var(--chip);color:var(--chip-ink);padding:4px 8px;border-radius:999px}
.sidefoot{margin-top:auto;padding:12px 10px 0;border-top:1px solid var(--line-soft);font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:6px}
.live{display:inline-flex;align-items:center;gap:7px;color:var(--mint-ink);font-weight:500}
.live::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.main{padding-inline:clamp(16px,3vw,40px);padding-block:30px 72px;display:flex;flex-direction:column;gap:30px;max-width:1200px;width:100%;min-width:0}
.head{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:16px}
h1{margin:0;font:300 clamp(28px,3.4vw,42px)/1.08 var(--display);letter-spacing:-.022em;color:var(--ink);text-wrap:balance}
.lede{margin:8px 0 0;color:var(--muted);font-size:14.5px;max-width:64ch}
.lede b{color:var(--ink);font-weight:600}
.stamp{font:400 12px/1.4 var(--mono);color:var(--muted)}
h2{margin:0;font:500 19px/1.2 var(--display);color:var(--ink);text-wrap:balance}
.sechead{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:6px 12px;margin-bottom:14px}
.secsub{font-size:12.5px;color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.kpi{padding:16px 18px;border-left:1px solid var(--line-soft)}
.kpi:first-child{border-left:0}
.kpi .n{font:300 36px/1 var(--display);color:var(--ink);font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.kpi .k{margin-top:10px;font-weight:600;font-size:12.5px;color:var(--ink)}
.kpi .s{font-size:12px;color:var(--muted)}
.kpi.good .n{color:var(--mint-ink)}
.kpi.warn .n{color:var(--amber-ink)}
.matches{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.match{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:5px}
.mhead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px}
.fit{font:600 12px/1 var(--ui);font-variant-numeric:tabular-nums;background:var(--amber);color:var(--amber-ink);padding:5px 9px;border-radius:999px;white-space:nowrap;display:inline-block}
.fit.none{background:transparent;color:var(--muted);font-weight:500;border:1px dashed var(--line)}
.chip{font:500 11px/1 var(--ui);background:var(--chip);color:var(--chip-ink);padding:5px 9px;border-radius:999px;white-space:nowrap;display:inline-block}
.mco{font:600 15.5px/1.25 var(--display);color:var(--ink)}
.mrole{font-size:13px;color:var(--body)}
.mwhy{font-size:12.5px;color:var(--muted);flex:1}
.mfoot{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:8px}
.loc{font-size:11.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.btn{font:500 12px/1 var(--ui);background:var(--accent);color:var(--accent-ink);text-decoration:none;padding:8px 12px;border-radius:999px;white-space:nowrap}
.btn:hover{filter:brightness(1.12)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;min-width:0}
.work{padding:18px 0 4px}
.work>.sechead{padding-inline:18px}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;padding:0 18px 14px;border-bottom:1px solid var(--line-soft)}
.tabs{display:flex;flex-wrap:wrap;gap:6px}
.tab{font:500 12.5px/1 var(--ui);border:1px solid var(--line);background:var(--surface);color:var(--body);padding:7px 11px;border-radius:999px;cursor:pointer;display:inline-flex;gap:7px;align-items:center}
.tab:hover{background:var(--hover)}
.tab .cnt{font-variant-numeric:tabular-nums;color:var(--muted)}
.tab.on{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.tab.on .cnt{color:inherit;opacity:.78}
.search{font:13px var(--ui);color:var(--ink);background:var(--canvas);border:1px solid var(--line);border-radius:999px;padding:8px 14px;width:250px;max-width:100%}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.tablewrap{overflow-x:auto}
table{width:100%;border-collapse:collapse}
#t-apps{min-width:960px}
th{font:600 10.5px/1 var(--ui);letter-spacing:.08em;text-transform:uppercase;color:var(--muted);text-align:left;padding:12px}
td{padding:11px 12px;border-top:1px solid var(--line-soft);vertical-align:top}
tbody tr:hover td{background:var(--hover)}
.co{font-weight:600;color:var(--ink)}
.role{font-size:12.5px;color:var(--muted);max-width:360px}
.why{margin-top:6px;font-size:11.5px;color:var(--muted);max-width:300px}
.mono{font-family:var(--mono);font-size:12px}
.dim{color:var(--muted)}
.small{font-size:11.5px}
.nowrap{white-space:nowrap}
.pill{font:500 11.5px/1 var(--ui);padding:5px 10px;border-radius:999px;border:1px solid transparent;white-space:nowrap;display:inline-block}
.p-good{background:var(--mint);color:var(--mint-ink)}
.p-warn{background:var(--amber);color:var(--amber-ink)}
.p-crit{background:var(--rose);color:var(--rose-ink)}
.p-ink{background:var(--chip);color:var(--ink);border-color:var(--line)}
.p-mute{background:transparent;color:var(--muted);border-color:var(--line)}
.act{text-align:right;white-space:nowrap}
.link{font:500 12.5px var(--ui);color:var(--ink);text-decoration:none;border-bottom:1px solid var(--line)}
.link:hover{border-color:var(--ink)}
.copy{font:500 12px/1 var(--ui);background:var(--accent);color:var(--accent-ink);border:0;border-radius:999px;padding:8px 12px;cursor:pointer}
.copy.done{background:var(--mint);color:var(--mint-ink)}
.empty{color:var(--muted);font-size:13px;margin:0}
tr.hidden{display:none}
.foot-note{margin:0;padding:12px 18px 14px;font-size:12px;color:var(--muted)}
.foot-note code{font-family:var(--mono);font-size:11.5px;color:var(--ink)}
.board{background:var(--forest);color:var(--forest-ink);border-radius:16px;padding:20px;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}
.lane header{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid var(--forest-line);padding-bottom:10px}
.ltitle{font:700 10.5px/1 var(--ui);letter-spacing:.1em;text-transform:uppercase;color:var(--forest-sub)}
.lnum{font:300 32px/1 var(--display);font-variant-numeric:tabular-nums;color:var(--forest-ink)}
.lsub{margin:8px 0 10px;font-size:12px;color:var(--forest-sub)}
.lane ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.lane li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 8px;padding:9px 11px;border-radius:10px;background:var(--forest-card)}
.lco{font-weight:600;font-size:13px;color:var(--forest-ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lwhen{font-size:11px;color:var(--forest-sub);white-space:nowrap}
.lrole{grid-column:1 / 3;font-size:11.5px;color:var(--forest-sub);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.twocol{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:14px;align-items:start}
.plat,.recs{padding:18px}
.prow{display:grid;grid-template-columns:120px minmax(0,1fr) 36px;gap:3px 12px;align-items:center;padding:6px 0}
.pname{font-weight:500;color:var(--ink);font-size:13px}
.pbar{height:8px;border-radius:999px;background:var(--line-soft);overflow:hidden}
.pbar span{display:block;height:100%;border-radius:999px;background:var(--accent)}
.pnum{font-variant-numeric:tabular-nums;text-align:right;color:var(--ink);font-weight:600}
.pnote{grid-column:2 / 4;font-size:11.5px;color:var(--muted)}
.recgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 24px}
.rname{font:600 13.5px/1.2 var(--display);color:var(--ink);margin-bottom:7px}
.rco ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:7px}
.rco li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:1px 8px;font-size:12.5px;align-items:center}
.rco a{color:var(--ink);text-decoration:none;border-bottom:1px solid var(--line);justify-self:start}
.rtitle{grid-column:1 / 3;color:var(--muted);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.agents{padding:18px 0 6px}
.agents>.sechead{padding-inline:18px}
.agents table{min-width:660px}
.aname{font-weight:600;color:var(--ink);white-space:nowrap}
.notes{padding:18px}
.notes ul{margin:12px 0 0;padding-left:18px;display:flex;flex-direction:column;gap:6px;max-width:80ch}
.warnchip{background:var(--amber);color:var(--amber-ink)}
.fa-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.fa-card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:5px}
.fa-card .mrole{flex:1;margin-bottom:6px}
.fa-card .mfoot{flex-wrap:wrap}
.meter{display:grid;grid-template-columns:62px minmax(0,1fr) 36px;align-items:center;gap:8px;font-size:11.5px}
.mlabel{color:var(--muted)}
.mtrack{height:6px;border-radius:999px;background:var(--line-soft);overflow:hidden}
.mtrack span{display:block;height:100%;border-radius:999px;background:var(--accent)}
.mval{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink);font-weight:600}
.fa-btn{font:500 12px/1 var(--ui);display:inline-flex;align-items:center;gap:7px;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:4px 10px 4px 4px;cursor:pointer;white-space:nowrap}
.fa-btn:hover{background:var(--hover);border-color:var(--muted)}
.fa-score{font-variant-numeric:tabular-nums;font-weight:600;background:var(--chip);color:var(--ink);padding:4px 7px;border-radius:999px}
dialog.fa{margin:0 0 0 auto;padding:0;border:0;width:min(780px,100vw);max-width:100vw;height:100%;max-height:100%;background:var(--surface);color:var(--body);box-shadow:-24px 0 60px rgba(8,16,12,.22);overflow-y:auto;overscroll-behavior:contain}
dialog.fa::backdrop{background:rgba(10,18,14,.46)}
.fa-top{position:sticky;top:0;z-index:1;background:var(--surface);border-bottom:1px solid var(--line);padding:18px 22px 14px;display:flex;flex-direction:column;gap:12px}
.fa-titlerow{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}
.fa-co{font:500 22px/1.15 var(--display);color:var(--ink);letter-spacing:-.01em}
.fa-role{font-size:13px;color:var(--muted);margin-top:3px}
.fa-x{font:500 12.5px/1 var(--ui);background:var(--chip);color:var(--ink);border:0;border-radius:999px;padding:9px 14px;cursor:pointer;flex:none}
.fa-x:hover{background:var(--hover)}
.fa-meta{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px}
.fa-num{font-size:12.5px;color:var(--muted)}
.fa-num b{font:600 15px/1 var(--display);color:var(--ink);font-variant-numeric:tabular-nums;margin-right:3px}
.fa-checks{font-size:12.5px;background:var(--amber);color:var(--amber-ink);border-radius:10px;padding:8px 12px}
.fa-checks summary{cursor:pointer;font-weight:600}
.fa-checks ul{margin:8px 0 4px;padding-left:18px;display:flex;flex-direction:column;gap:4px}
.fa-checks p{margin:6px 0 0;color:inherit;opacity:.85}
.fa-tries{margin:0}
.fa-body{padding:4px 22px 48px}
.fa-md{max-width:74ch;color:var(--body);font-size:14px;line-height:1.6}
.fa-md h1,.fa-md h2,.fa-md h3,.fa-md h4{font:600 16px/1.3 var(--display);color:var(--ink);margin:28px 0 8px;text-wrap:balance}
.fa-md h1{font-size:19px}
.fa-md p{margin:0 0 10px}
.fa-md ul,.fa-md ol{margin:0 0 12px;padding-left:20px;display:flex;flex-direction:column;gap:5px}
.fa-md strong{color:var(--ink)}
.fa-md code{font-family:var(--mono);font-size:12.5px;background:var(--chip);color:var(--ink);padding:1px 5px;border-radius:5px}
.fa-md pre,.fa-body pre.plain{background:var(--canvas);border:1px solid var(--line-soft);border-radius:10px;padding:12px 14px;overflow-x:auto;font:12.5px/1.55 var(--mono);color:var(--ink);white-space:pre}
.fa-md pre code{background:transparent;padding:0}
.fa-md table{display:block;overflow-x:auto;border-collapse:collapse;margin:0 0 14px;font-size:13px;width:auto}
.fa-md th,.fa-md td{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
.fa-md th{text-transform:none;letter-spacing:0;font-size:12px;color:var(--ink);background:var(--canvas)}
.fa-md blockquote{margin:0 0 12px;padding:4px 14px;border-left:3px solid var(--line);color:var(--muted)}
@media (max-width:1080px){.matches,.fa-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.board{grid-template-columns:repeat(2,minmax(0,1fr))}.twocol{grid-template-columns:minmax(0,1fr)}}
@media (max-width:820px){
  .shell{grid-template-columns:minmax(0,1fr)}
  .side{z-index:5;height:auto;flex-direction:row;align-items:center;padding:10px 16px;gap:14px;border-right:0;border-bottom:1px solid var(--line);overflow-x:auto}
  .bsub,.sidefoot{display:none}
  .navlist{flex-direction:row;gap:4px}
  .nav-i{white-space:nowrap;padding:7px 10px}
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .kpi{border-left:0;border-top:1px solid var(--line-soft)}
  .kpi:nth-child(even){border-left:1px solid var(--line-soft)}
  .kpi:nth-child(-n+2){border-top:0}
  .recgrid{grid-template-columns:minmax(0,1fr)}
}
@media (max-width:520px){.matches,.board,.fa-grid{grid-template-columns:minmax(0,1fr)}.search{width:100%}.fa-top,.fa-body{padding-inline:16px}}
</style>
<div class="shell">
  <aside class="side">
    <div class="brand"><div class="mark" aria-hidden="true">AD</div><div><div class="bname">Application Desk</div><div class="bsub">Sai Srikar Reddy Kolli</div></div></div>
    <nav class="navlist" aria-label="Sections">{{NAV}}</nav>
    <div class="sidefoot"><span class="live">Daily run {{LASTRUN}}</span><span>Nothing here submits an application. You press Submit.</span></div>
  </aside>
  <main class="main">
    <header class="head" id="overview">
      <div>
        <h1>{{GREET}}, Srikar</h1>
        <p class="lede"><b>{{READY}} applications</b> are prepared and waiting for you, and <b>{{APPLIED}}</b> have gone out. Rows with a copy button fill their own form.</p>
      </div>
      <div class="stamp">Built {{STAMP}}</div>
    </header>
    <section class="kpis" aria-label="Summary">{{KPIS}}</section>
    <section id="matches">
      <div class="sechead"><h2>Top matches</h2><span class="secsub">highest fit scores among prepared postings</span></div>
      <div class="matches">{{TOP}}</div>
    </section>
    <section id="analyses">
      <div class="sechead"><h2>Fit analyses</h2><span class="secsub">{{FASUB}}</span></div>
      <div class="fa-grid">{{FACARDS}}</div>
    </section>
    <section class="card work" id="applications">
      <div class="sechead"><h2>Applications</h2><span class="secsub">every posting still in the pipeline</span></div>
      <div class="toolbar">
        <div class="tabs" role="tablist" aria-label="Filter applications">{{TABS}}</div>
        <label for="q" class="vh">Search applications</label>
        <input id="q" class="search" type="search" placeholder="Search company, role or platform" autocomplete="off">
      </div>
      <div class="tablewrap"><table id="t-apps">
        <thead><tr><th>#</th><th>Position</th><th>Fit</th><th>Analysis</th><th>Platform</th><th>Resume</th><th>Status</th><th>Updated</th><th><span class="vh">Action</span></th></tr></thead>
        <tbody>{{ROWS}}</tbody>
      </table></div>
      <p class="foot-note">Copy a fill command and run it in <code>~/Developer/career-agent</code>. Chrome opens the form filled in; you review it and press Submit.</p>
    </section>
    <section id="pipeline" class="board" aria-label="Pipeline">{{BOARD}}</section>
    <div class="twocol">
      <section class="card plat" id="platforms">
        <div class="sechead"><h2>Platforms</h2><span class="secsub">open postings by application system</span></div>
        {{PLATFORMS}}
      </section>
      <section class="card recs" id="recruiters">
        <div class="sechead"><h2>Recruiters and contacts</h2><span class="secsub">found for you, never messaged automatically</span></div>
        <div class="recgrid">{{RECRUITERS}}</div>
      </section>
    </div>
    <section class="card agents" id="agents">
      <div class="sechead"><h2>Agents</h2><span class="secsub">who does each job, and the model behind it</span></div>
      <div class="tablewrap"><table><thead><tr><th>Task</th><th>What it does</th><th>Model</th><th>Runs</th></tr></thead><tbody>{{AGENTS}}</tbody></table></div>
    </section>
    {{NOTES}}
  </main>
</div>
<dialog class="fa" id="fa" aria-labelledby="fa-co">
  <div class="fa-top">
    <div class="fa-titlerow">
      <div><div class="fa-co" id="fa-co"></div><div class="fa-role" id="fa-role"></div></div>
      <button type="button" class="fa-x" id="fa-x">Close</button>
    </div>
    <div id="fa-meta"></div>
  </div>
  <div class="fa-body" id="fa-body"></div>
</dialog>
{{TEMPLATES}}
<script>
(() => {
  const rows = [...document.querySelectorAll('#t-apps tbody tr')];
  const tabs = [...document.querySelectorAll('.tab')];
  const q = document.getElementById('q');
  let tab = 'all';
  const apply = () => {
    const term = (q.value || '').trim().toLowerCase();
    rows.forEach(r => r.classList.toggle('hidden', !((tab === 'all' || r.dataset.tab === tab) && (!term || r.dataset.q.includes(term)))));
  };
  tabs.forEach(t => t.addEventListener('click', () => {
    tab = t.dataset.tab;
    tabs.forEach(x => { x.classList.toggle('on', x === t); x.setAttribute('aria-selected', x === t ? 'true' : 'false'); });
    apply();
  }));
  q.addEventListener('input', apply);
  document.querySelectorAll('.copy').forEach(b => b.addEventListener('click', async () => {
    const cmd = b.dataset.cmd;
    try { await navigator.clipboard.writeText(cmd); b.textContent = 'Copied'; }
    catch (e) { window.prompt('Copy this command:', cmd); b.textContent = 'Shown'; }
    b.classList.add('done');
    setTimeout(() => { b.textContent = 'Copy fill command'; b.classList.remove('done'); }, 2200);
  }));
  const dlg = document.getElementById('fa');
  const body = document.getElementById('fa-body');
  const meta = document.getElementById('fa-meta');
  let opener = null;
  const openFa = (id, btn) => {
    const src = document.getElementById('fa-' + id);
    if (!src || !dlg.showModal) return;
    opener = btn;
    document.getElementById('fa-co').textContent = src.dataset.co;
    document.getElementById('fa-role').textContent = src.dataset.role;
    const frag = src.content.cloneNode(true);
    const md = frag.querySelector('.fa-md');
    meta.replaceChildren(frag);
    body.replaceChildren(md);
    dlg.showModal();
    dlg.scrollTop = 0;
  };
  document.addEventListener('click', e => {
    const b = e.target.closest('.fa-btn');
    if (b) openFa(b.dataset.fa, b);
  });
  document.getElementById('fa-x').addEventListener('click', () => dlg.close());
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener('close', () => { if (opener) opener.focus(); });
})();
</script>
"""


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DESK
    page = build()
    out.write_text(page)
    print(f"desk rebuilt: {out} ({len(re.findall(r'<tr data-tab=', page))} applications, {len(page) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
