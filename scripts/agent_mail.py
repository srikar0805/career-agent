#!/usr/bin/env python3
"""Mail agent: read Gmail over IMAP (read-only), triage job mail on NVIDIA, update the pipeline.

Srikar chose on 2026-09-16 to move mail triage off Claude onto NVIDIA, with an
app password over IMAP. Until then the Stage 2 Claude session read mail through
the claude.ai Gmail connector.

Read-only in three ways: every folder is opened with EXAMINE (readonly=True),
bodies are fetched with BODY.PEEK so nothing is marked read, and there is no
SMTP code in this file. The app password could send mail; this program cannot.

What leaves the machine: only mail that a local filter already judged
job-related (an ATS or job-site sender domain, a company in the pipeline, or an
application-shaped subject), with email addresses and phone numbers removed and
the body cut to 2,000 characters. Everything else is never read past its headers.

What it changes, and the evidence each change needs:
  rejection            move to rejected: the model says rejection AND the text carries a
                       rejection phrase AND exactly one open application matches
  interview/assessment move applied to screening, add a task: model AND exactly one match
  application received log it, and confirm an 'applied' row that had no confirmation
  anything else        reported only
Every message acted on is logged with its Message-ID, so no mail is processed twice.

Store the app password once (Google Account > Security > App passwords):
    security add-generic-password -a "$USER" -s gmail-app-password -w

    agent_mail.py                  dry run: classify and report, change nothing
    agent_mail.py --commit         also update the pipeline
    agent_mail.py --days 7         look back further (default: since the last run, else 3 days)
"""
from __future__ import annotations

import argparse
import email
import email.header
import email.utils
import imaplib
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

DB = ROOT / "data" / "pipeline.db"
STATE = ROOT / "data" / "mail_state.json"
FOLDERS = ["INBOX", "[Gmail]/Spam"]

JOB_DOMAINS = re.compile(
    r"greenhouse|lever\.co|ashbyhq|myworkday|workday\.com|icims|smartrecruiters|successfactors|oraclecloud|taleo"
    r"|jobvite|joinhandshake|handshake|linkedin|dice\.com|indeed|hackerrank|codesignal|hirevue|bamboohr|rippling"
    r"|workable|paylocity|ultipro|ukg|avature|eightfold|phenom|gem\.com|goodtime|modernhire|karat", re.I)
JOB_SUBJECT = re.compile(
    r"application|applying|candidacy|interview|assessment|coding (challenge|test)|next steps|your (interest|profile)"
    r"|offer|position|opportunity|recruit|hiring|thank you for (applying|your interest)|role at|update on", re.I)
REJECTION_PHRASE = re.compile(
    r"not (be )?moving forward|decided (not )?to (move|proceed|pursue) (forward )?with other|other candidates"
    r"|will not be (moving|proceeding)|unable to (offer|move forward)|regret to inform|no longer under consideration"
    r"|position has been filled|not selected|decided to pursue other|unfortunately,? (we|after)", re.I)

SYSTEM = """You triage one email for a job seeker. Reply with ONE JSON object only:
{"category": "rejection" | "interview_request" | "assessment" | "application_received" | "recruiter_outreach" | "offer" | "job_alert" | "other",
 "company": "employer the email is about, or null",
 "role": "job title the email is about, or null",
 "action_needed": "what he must do, or null",
 "deadline": "YYYY-MM-DD if the email states one, else null",
 "summary": "one sentence, at most 200 characters, no em dashes"}"""


def app_password() -> str:
    try:
        return subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "gmail-app-password", "-w"],
                              capture_output=True, text=True, timeout=10).stdout.strip().replace(" ", "")
    except Exception:
        return ""


def decode(s) -> str:
    try:
        return str(email.header.make_header(email.header.decode_header(s or "")))
    except Exception:
        return str(s or "")


def body_text(msg: email.message.Message) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    plain, htmlish = [], []
    for p in parts:
        if p.get_content_maintype() != "text" or p.get("Content-Disposition", "").startswith("attachment"):
            continue
        try:
            t = p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        (plain if p.get_content_subtype() == "plain" else htmlish).append(t)
    text = "\n".join(plain) or re.sub(r"<[^>]+>", " ", "\n".join(htmlish))
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(">"))   # drop quoted replies
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def redact(s: str) -> str:
    s = re.sub(r"[\w.+-]+@([\w-]+\.[\w.-]+)", r"<email at \1>", s)
    s = re.sub(r"(\+?\d[\d\s().-]{8,}\d)", "<phone>", s)
    s = re.sub(r"(https?://[^\s?]+)\?\S*", r"\1", s)              # tracking and token query strings
    return s


def pipeline_companies() -> list[tuple[int, str, str, str]]:
    con = sqlite3.connect(DB)
    rows = list(con.execute("SELECT id, company, role, status FROM applications"))
    con.close()
    return rows


def norm(x: str) -> str:
    return re.sub(r"\W", "", (x or "").lower())


def job_related(sender: str, subject: str, rows) -> bool:
    if JOB_DOMAINS.search(sender) or JOB_SUBJECT.search(subject):
        return True
    blob = norm(sender + subject)
    return any(len(norm(c)) > 3 and norm(c) in blob for _, c, _, _ in rows)


def match(company: str, role: str, rows, statuses: tuple[str, ...]) -> list[tuple[int, str, str, str]]:
    nc = norm(company)
    if len(nc) < 3:
        return []
    same = [r for r in rows if r[3] in statuses and (norm(r[1]) == nc or (len(nc) > 4 and (nc in norm(r[1]) or norm(r[1]) in nc)))]
    if len(same) <= 1 or not role:
        return same
    words = set(re.findall(r"[a-z]{3,}", role.lower()))
    scored = sorted(same, key=lambda r: -len(words & set(re.findall(r"[a-z]{3,}", r[2].lower()))))
    best = len(words & set(re.findall(r"[a-z]{3,}", scored[0][2].lower())))
    top = [r for r in scored if len(words & set(re.findall(r"[a-z]{3,}", r[2].lower()))) == best]
    return top if best > 0 else same


def already_logged(message_id: str) -> bool:
    con = sqlite3.connect(DB)
    n = con.execute("SELECT count(*) FROM interactions WHERE summary LIKE ?", (f"%[mail {message_id[:24]}]%",)).fetchone()[0]
    con.close()
    return n > 0


def fetch(days: int | None) -> list[dict]:
    pw = app_password()
    if not pw:
        raise SystemExit('no Gmail app password: security add-generic-password -a "$USER" -s gmail-app-password -w')
    addr = yaml.safe_load((ROOT / "profile" / "identity.yaml").read_text())["email"]
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    since = (date.today() - timedelta(days=days)) if days else \
        (date.fromisoformat(st["last_run"][:10]) - timedelta(days=1) if st.get("last_run") else date.today() - timedelta(days=3))
    out = []
    M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        M.login(addr, pw)
        for folder in FOLDERS:
            typ, _ = M.select(f'"{folder}"', readonly=True)          # EXAMINE: flags cannot change
            if typ != "OK":
                continue
            typ, data = M.search(None, "SINCE", since.strftime("%d-%b-%Y"))
            for num in (data[0].split() if typ == "OK" else []):
                typ, parts = M.fetch(num, "(BODY.PEEK[])")          # PEEK: not marked read
                if typ != "OK" or not parts or not isinstance(parts[0], tuple):
                    continue
                msg = email.message_from_bytes(parts[0][1])
                out.append({"folder": folder, "message_id": (msg.get("Message-ID") or f"{folder}-{num.decode()}").strip("<>"),
                            "from": decode(msg.get("From")), "subject": decode(msg.get("Subject")),
                            "date": decode(msg.get("Date")), "msg": msg})
    finally:
        try:
            M.logout()
        except Exception:
            pass
    STATE.write_text(json.dumps({"last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "since": since.isoformat()}, indent=1) + "\n")
    return out


def triage(mails: list[dict], commit: bool) -> list[dict]:
    from nim import NimError, chat
    rows = pipeline_companies()
    report = []
    for m in mails:
        if already_logged(m["message_id"]) or not job_related(m["from"], m["subject"], rows):
            continue
        text = body_text(m["msg"]) if "msg" in m else m.get("body", "")
        sender_domain = (re.search(r"@([\w.-]+)", m["from"]) or [None, ""])[1]
        payload = redact(f"From: {re.sub(r'<[^>]*>', '', m['from']).strip()} ({sender_domain})\n"
                         f"Subject: {m['subject']}\nDate: {m['date']}\n\n{text[:2000]}")
        try:
            c = chat("triage", SYSTEM, payload, want_json=True, max_tokens=1200, purpose="mail triage")["json"]
        except NimError as e:
            report.append({**{k: m[k] for k in ("from", "subject", "folder")}, "error": str(e)[:120]})
            continue
        c = c if isinstance(c, dict) else {}
        cat = c.get("category", "other")
        rec = {"folder": m["folder"], "from_domain": sender_domain, "subject": m["subject"][:120], "category": cat,
               "company": c.get("company"), "role": c.get("role"), "summary": str(c.get("summary") or "")[:200],
               "deadline": c.get("deadline"), "action": None}
        tag = f"[mail {m['message_id'][:24]}]"
        if cat == "rejection":
            hits = match(c.get("company") or "", c.get("role") or "", rows, ("applied", "screening"))
            confirmed = bool(REJECTION_PHRASE.search(text))
            if len(hits) == 1 and confirmed:
                rec["action"] = f"#{hits[0][0]} applied -> rejected"
                if commit:
                    subprocess.run([sys.executable, str(HERE / "pipeline.py"), "move", str(hits[0][0]), "rejected"], capture_output=True)
                    subprocess.run([sys.executable, str(HERE / "pipeline.py"), "log", str(hits[0][0]), "--kind", "rejection",
                                    "--direction", "in", "--channel", "email", "--summary", f"{rec['summary']} {tag}"], capture_output=True)
            else:
                rec["action"] = f"not moved: {len(hits)} matching application(s), rejection phrase {'present' if confirmed else 'absent'}"
        elif cat in ("interview_request", "assessment", "offer"):
            hits = match(c.get("company") or "", c.get("role") or "", rows, ("applied", "screening", "discovered"))
            if len(hits) == 1:
                rec["action"] = f"#{hits[0][0]} logged, task added" + (", applied -> screening" if hits[0][3] == "applied" else "")
                if commit:
                    if hits[0][3] == "applied":
                        subprocess.run([sys.executable, str(HERE / "pipeline.py"), "move", str(hits[0][0]), "screening"], capture_output=True)
                    subprocess.run([sys.executable, str(HERE / "pipeline.py"), "log", str(hits[0][0]), "--kind", "email",
                                    "--direction", "in", "--channel", "email", "--summary", f"{cat}: {rec['summary']} {tag}"], capture_output=True)
                    due = c.get("deadline") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c.get("deadline") or "")) else \
                        (date.today() + timedelta(days=1)).isoformat()
                    subprocess.run([sys.executable, str(HERE / "pipeline.py"), "task", str(hits[0][0]), "--kind", "follow_up",
                                    "--description", f"respond: {c.get('action_needed') or cat}"[:200], "--due", due], capture_output=True)
            else:
                rec["action"] = f"NEEDS YOU: {len(hits)} matching application(s), not linked automatically"
        elif cat == "application_received":
            hits = match(c.get("company") or "", c.get("role") or "", rows, ("applied",))
            if len(hits) == 1:
                rec["action"] = f"#{hits[0][0]} confirmation logged"
                if commit:
                    subprocess.run([sys.executable, str(HERE / "pipeline.py"), "log", str(hits[0][0]), "--kind", "application",
                                    "--direction", "in", "--channel", "email", "--summary", f"confirmation received {tag}"], capture_output=True)
        report.append(rec)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--days", type=int)
    a = ap.parse_args()
    mails = fetch(a.days)
    report = triage(mails, a.commit)
    out = ROOT / "data" / "logs" / f"mail-{date.today()}.json"
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(f"mail: {len(mails)} message(s) read, {len(report)} job-related")
    for r in report:
        if r.get("error"):
            print(f"  ERROR    {r['subject'][:60]}: {r['error']}")
        else:
            print(f"  {r['category']:20} {str(r.get('company'))[:20]:22} {r['summary'][:70]}" + (f"  -> {r['action']}" if r.get("action") else ""))
    print(f"report: {out.relative_to(ROOT)}{'' if a.commit else '  (dry run, pipeline unchanged)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
