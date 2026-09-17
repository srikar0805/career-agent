#!/usr/bin/env python3
"""Build a ready-to-submit application packet for one pipeline row. Never submits.

WHY THIS EXISTS. On 2026-09-16 Srikar asked for Tsenta-style application
prefill and chose STAGED submission: the pipeline fills in every answer it can,
and he reviews and presses submit himself. `/apply` already stopped short of the
form; this is the form.

    prefill.py --app <id>              write data/artifacts/<slug>/packet.md and log it
    prefill.py --app <id> --print      also print the packet
    prefill.py --app <id> --no-log     do not record the artifact

What it does, per posting:

  Greenhouse    reads the REAL form through ?questions=true (see form_check.py)
                and answers each question in form order, choosing the matching
                option for dropdowns.
  anything else the form is not publicly readable, so the packet lists the
                standard answers every form asks, for pasting.

Every answer comes from profile/answers.yaml or pipeline.db. Four statuses:

  FILLED     ready to paste or select
  CONFIRM    a near-certain fact nobody has confirmed
  DECISION   his choice, never pre-selected: consents, pronouns, EEO, preferences
  NEEDS YOU  unknown, left blank
  OPEN       a free-text answer that must be written for this role (/apply does it)

Work authorization is answered exactly and honestly on every form. The
sponsorship question gets "Yes" even though it is the question that has closed
more applications in this pipeline than anything else, because the alternative
is a false statement on an employment application.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from form_check import classify, greenhouse_questions  # noqa: E402

DB = ROOT / "data" / "pipeline.db"
ANSWERS = yaml.safe_load((ROOT / "profile" / "answers.yaml").read_text())
# parsed, not raw: a comment in evidence.yaml quotes a posting's "on AWS" and read as experience
EVIDENCE_TEXT = json.dumps(yaml.safe_load((ROOT / "profile" / "evidence.yaml").read_text()))


# ---------------------------------------------------------------- helpers

def val(node):
    """Return (value, status, note) for a plain string or a {value, confirm, ...} node."""
    if isinstance(node, dict):
        note = node.get("note", "")
        if node.get("need"):
            return "", "NEEDS YOU", note
        if node.get("decision"):
            return node.get("value", ""), "DECISION", note
        if node.get("confirm"):
            return node.get("value", ""), "CONFIRM", note
        return node.get("value", ""), "FILLED", note
    return node, "FILLED", ""


def norm(x: str) -> str:
    return re.sub(r"\W", "", (x or "").lower())


def pick_option(options: list[str], want: str, prefer: str = "") -> str | None:
    """Choose the dropdown option that says what `want` says. None if nothing does."""
    w = (want or "").lower().strip()
    if not options or not w:     # "" startswith-matches every option; C3.ai got Carnegie Mellon that way
        return None
    if prefer:
        for o in options:
            if o.lower().startswith(w) and prefer in o.lower():
                return o
    for o in options:
        if o.lower().strip() == w:
            return o
    for o in options:
        if o.lower().startswith(w):
            return o
    for o in options:
        if w and w in o.lower():
            return o
    if w == "no":   # Robinhood and InterSystems spell No as "I have never worked at ..."
        for o in options:
            if re.search(r"\bnever\b|\bhave\s+not\b|\bhaven'?t\b|\bdo\s+not\b|\bdon'?t\b|^none\b", o, re.I):
                return o
    return None


def start_option(options: list[str]) -> str | None:
    """The option that contains June 2027: Stripe offers 'Q2 2027 (April - June)'."""
    start = 2027 * 12 + 6
    for o in options:
        q = re.search(r"\bQ([1-4])\s*'?(20\d\d)", o, re.I)
        if q:
            lo = int(q.group(2)) * 12 + (int(q.group(1)) - 1) * 3 + 1
            if lo <= start <= lo + 2:
                return o
            continue
        toks = DATE_TOK.findall(o)
        if toks:
            t, y = toks[0][0].lower(), int(toks[0][1])
            lo, hi = SEASON[t] if t in SEASON else (MONTH[t[:3]], MONTH[t[:3]])
            if y * 12 + lo <= start <= y * 12 + hi:
                return o
    return None


# ---------------------------------------------------------------- context from the pipeline

def load_row(app_id: int) -> dict:
    out = subprocess.run([sys.executable, str(HERE / "pipeline.py"), "show", str(app_id), "--json"],
                         capture_output=True, text=True).stdout
    doc = json.loads(out)
    row = dict(doc.get("application", doc))
    row["_raw"] = out   # notes may live on the row or in history; form_check reads both the same way
    return row


def artifact_path(app_id: int, kind: str) -> str:
    con = sqlite3.connect(DB)
    r = con.execute("SELECT path FROM artifacts WHERE application_id=? AND kind=? ORDER BY id DESC LIMIT 1",
                    (app_id, kind)).fetchone()
    con.close()
    return r[0] if r else ""


def prior_applications(row: dict) -> list[str]:
    """Other rows at the same employer that were actually sent. Honest 'applied before'."""
    me, co = row["id"], norm(row.get("company"))
    con = sqlite3.connect(DB)
    hits = []
    for rid, c, role, status, applied in con.execute(
            "SELECT id, company, role, status, applied_at FROM applications WHERE id != ?", (me,)):
        nc = norm(c)
        same = nc and co and (nc == co or (len(co) > 4 and co in nc) or (len(nc) > 4 and nc in co))
        if same and (applied or status in ("applied", "screening", "interviewing", "offer", "rejected")):
            hits.append(f"#{rid} {role} ({status})")
    con.close()
    return hits


def board_token(row: dict) -> str | None:
    """A Greenhouse board token already learned for this employer, if any.

    Company-hosted pages (`c3.ai/job-description/...?gh_jid=`) hide the token, and
    form_check guesses from the hostname, which is `c3` and wrong. The pipeline
    usually knows it already: written in the notes by hand ("board token is
    digitalocean98"), by discover_ats ("on board greenhouse:c3iot"), or as the
    URL of another row at the same employer.
    """
    m = re.search(r"board token is ([\w-]+)|on board greenhouse:([\w-]+)", row["_raw"], re.I)
    if m:
        return m.group(1) or m.group(2)
    con = sqlite3.connect(DB)
    urls = [u for (u,) in con.execute("SELECT url FROM applications WHERE lower(company)=lower(?) AND id != ?",
                                      (row.get("company") or "", row["id"]))]
    con.close()
    for u in urls:
        m = re.search(r"greenhouse\.io/([\w-]+)/jobs/\d+", u or "")
        if m and m.group(1) not in ("embed",):
            return m.group(1)
    return None


def salary(row: dict) -> tuple[str, str]:
    comp = ANSWERS["compensation"]
    lo, hi = row.get("comp_min"), row.get("comp_max")
    if not (lo and hi):
        m = re.search(r"\$\s?(\d{2,3}),?(\d{3})(?:\.\d+)?\s*(?:-|to|–)\s*\$?\s?(\d{2,3}),?(\d{3})",
                      row.get("jd_text") or "")
        if m:
            lo, hi = int(m[1] + m[2]), int(m[3] + m[4])
    if lo and hi and 40_000 <= int(lo) < int(hi) <= 400_000:
        return (f"Within the posted range of ${int(lo):,} to ${int(hi):,}; I am flexible on the overall package.",
                "posting states a range, so the answer stays inside it")
    loc = f"{row.get('location') or ''} {row.get('jd_text') or ''}"[:4000].lower()
    band = comp["band_high_cost"] if any(m in loc for m in comp["high_cost_metros"]) else comp["band_default"]
    return comp["wording"].format(band=band), "no posted range; band from what he has already told employers"


def how_heard(row: dict) -> str:
    table = ANSWERS["sourcing"]["how_did_you_hear"]
    return table.get(row.get("source") or "", table["default"])


# ---------------------------------------------------------------- answering one question

CONSENT_Q = re.compile(r"i\s+accept|acknowledg|agree|consent|privacy|terms|policy|text\s+message|sms"
                       r"|background\s+check|drug\s+(test|screen)|certif(y|ication)\s+that|i\s+confirm|attest"
                       r"|information\s+provided.{0,60}(true|accurate|complete)", re.I)

GPA = 3.95
GRAD = 2027 * 12 + 5          # May 2027, in months
MONTH = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
         "sep": 9, "oct": 10, "nov": 11, "dec": 12}
SEASON = {"spring": (3, 5), "summer": (6, 8), "fall": (9, 11), "autumn": (9, 11), "winter": (12, 14)}
DATE_TOK = re.compile(r"\b(jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|oct\w*|nov\w*|dec\w*"
                      r"|spring|summer|fall|autumn|winter)\s*(?:of\s+)?,?\s*'?(20\d\d)\b", re.I)


def grad_window(L: str) -> bool | None:
    """Does May 2027 satisfy the graduation date a question names? None if it names none.

    ID.me asks "Are you graduating Summer of 2027" and Celonis "Will you be
    completing your degree in June 2027 or later?". Both honest answers are No,
    and both are worth a warning, because a required cohort question filters.
    """
    if not re.search(r"graduat|degree|complet|finish", L):
        return None
    spans = []
    for tok, yr in DATE_TOK.findall(L):
        t, y = tok.lower(), int(yr)
        lo, hi = SEASON[t] if t in SEASON else (MONTH[t[:3]], MONTH[t[:3]])
        spans.append((y * 12 + lo, y * 12 + hi))
    if not spans:
        return None
    if len(spans) >= 2 and re.search(r"\bor\b", L):   # InterSystems: "Fall 2026 or Spring 2027"
        return any(lo <= GRAD <= hi for lo, hi in spans)
    if len(spans) >= 2 and re.search(r"between|\bto\b|through|\band\b", L):
        return spans[0][0] <= GRAD <= spans[-1][1]
    if re.search(r"or\s+(later|after)|\bafter\b", L):
        return GRAD >= spans[0][0]
    if re.search(r"or\s+(earlier|before|sooner)|\bbefore\b|\bby\b", L):
        return GRAD <= spans[0][1]
    return spans[0][0] <= GRAD <= spans[0][1]


def gpa_option(options: list[str]) -> str | None:
    """Pick the GPA bucket holding 3.95: Klaviyo offers '3.75 - 4', '4+', 'Below 2'."""
    for o in options:
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", o)]
        if not nums:
            continue
        if re.search(r"below|under|less", o, re.I):
            if GPA < nums[0]:
                return o
        elif "+" in o or re.search(r"above|higher|or\s+more", o, re.I):
            if GPA >= nums[0]:
                return o
        elif len(nums) >= 2 and nums[0] <= GPA <= nums[1]:
            return o
    return None
OPEN_Q = re.compile(r"^\s*(why|tell\s+us|describe|explain|imagine|what\s+(are|is|would|excites|interests|makes)"
                    r"|how\s+would|share|walk\s+us|please\s+(describe|explain|share))", re.I)


def answer(q: dict, row: dict, prev: dict | None = None) -> dict:
    label = re.sub(r"\s+", " ", (q.get("label") or "").strip())
    L = label.lower()
    fields = q.get("fields") or [{}]
    f0 = fields[0]
    ftype, fname = f0.get("type", ""), f0.get("name", "")
    options = [v.get("label", "") for v in (f0.get("values") or [])]
    wa, ed, av, ex = (ANSWERS["work_authorization"], ANSWERS["education"],
                      ANSWERS["availability"], ANSWERS["experience"])
    ct, pe = ANSWERS["contact"], ANSWERS["personal"]
    res = {"label": label, "required": bool(q.get("required")), "type": ftype,
           "options": options, "answer": "", "status": "NEEDS YOU", "note": "", "warn": False}

    def put(value, status="FILLED", note="", prefer=""):
        if options and value and status in ("FILLED", "CONFIRM"):
            chosen = pick_option(options, value, prefer)
            if chosen is None:
                res.update(answer=value, status="NEEDS YOU",
                           note=(note + " " if note else "") + f"intended '{value}', no matching option: {options}")
                return res
            value = chosen
        res.update(answer=value, status=status, note=note)
        return res

    # a follow-up to the question before it ("If you selected 'Other', please specify")
    m = re.match(r"if\s+(?:you\s+)?(?:selected|answered|chose|picked)?\s*['\"‘“]?([\w\s-]+?)['\"’”]?\s*"
                 r"(?:to\s+the\s+(?:above|previous|prior)\s+question\s*)?[,:]", L)
    if m and prev is not None:
        trigger = m.group(1).strip()
        if not (prev.get("answer") or "").lower().startswith(trigger):
            return put("", "FILLED", f"skip: only asked if the previous answer was '{trigger}'")
        if re.search(r"how\s+did\s+you\s+(hear|find|learn)", prev["label"], re.I):
            return put(how_heard(row), "CONFIRM", f"pipeline source: {row.get('source') or 'unknown'}")
        return put("", "NEEDS YOU", f"follows '{prev['label'][:60]}'")

    # standard Greenhouse fields, by name
    by_name ={"first_name": ct["legal_first_name"], "last_name": ct["last_name"],
               "email": ct["email"], "phone": ct["phone"]}
    if fname in by_name:
        return put(by_name[fname])
    if fname == "preferred_name":
        return put(*val(ct["preferred_first_name"])[:2], note="never confirmed by him")
    # Tebra asks for legal names as custom questions, not as first_name/last_name fields
    if re.search(r"^(what\s+is\s+your\s+)?(legal\s+)?first\s+name\b", L):
        return put(ct["legal_first_name"])
    if re.search(r"^(what\s+is\s+your\s+)?(legal\s+)?(last|family)\s+name\b|surname", L):
        return put(ct["last_name"])
    if re.search(r"^(what\s+is\s+your\s+)?(legal\s+)?middle\s+name\b", L):
        return put("", "CONFIRM", f"left blank: '{ct['legal_first_name']}' is entered as the legal first name")
    if re.search(r"^country(\s+of\s+residence)?\s*\??$|what\s+country\s+do\s+you\s+(live|reside)", L):
        return put(ct["country"])
    if re.search(r"^state(\s*/\s*province)?\s*\??$", L):
        return put(ct["state"])
    if fname in ("resume", "resume_text"):
        p = artifact_path(row["id"], "resume")
        if ftype == "input_file":
            return put(p, "FILLED", "upload this file") if p else put("", "NEEDS YOU", "no resume built for this row yet")
        return put("", "FILLED", "skip: upload the PDF instead of pasting text")
    if fname in ("cover_letter", "cover_letter_text"):
        p = artifact_path(row["id"], "cover_letter")
        if ftype == "input_file" and p:
            return put(p, "FILLED", "upload this file")
        return put("", "FILLED" if not res["required"] else "OPEN",
                   "optional, skip" if not res["required"] else "required: run /coverletter")

    # checked before consents: Capco's non-compete question says "agreement"
    if re.search(r"non-?compete|restrictive\s+covenant|non-?solicit", L):
        v, st, note = val(pe["non_compete"])
        if re.search(r"non-?disclosure|confidential", L):   # he answered for non-competes; an NDA is common
            return put(v, "CONFIRM", note + "; this question also names NDAs or confidentiality agreements, which most "
                       "employers have you sign: No is right only if none of them restricts where you can work")
        return put(v, st, note)
    if re.search(r"accommodat|reasonable\s+adjustment", L):
        v, st, note = val(pe.get("accommodations", {"decision": True}))
        return put(v, st, note)

    # consents are agreements: never pre-selected. Judge by the opening of the
    # label and by the options, because C3.ai's 2,500-character privacy notice
    # says "unauthorized third parties" and "resources" further down.
    head = L[:200]
    only_accept = options and all(re.search(r"accept|agree|acknowledg|consent|understand|i\s+do\b", o, re.I)
                                  or o.lower().strip() in ("yes", "no") for o in options) \
        and any(re.search(r"accept|agree|acknowledg", o, re.I) for o in options)
    if only_accept or (CONSENT_Q.search(head) and not re.search(r"sponsor|authori[sz]ed\s+to\s+work", head)):
        return put("", "DECISION", "an agreement or consent; your call")

    # work authorization, exactly and honestly
    if re.search(r"sponsor|h-?1b|visa\s+support|immigration\s+(case|support)", L):
        if "new h" in L or "h-1b" in L or "h1b" in L:
            return put(wa["requires_new_h1b"], note=wa["sponsorship_explanation"])
        return put(wa["requires_sponsorship_now_or_future"], note=wa["sponsorship_explanation"])
    if re.search(r"(authori[sz]ed|eligible)\s+to\s+work|(legal\s+)?work\s+authori[sz]ation\s+(in|for)", L):
        if "any employer" in L:
            v, s, n = val(wa["authorized_for_any_employer"])
            return put(v, s, n)
        return put(wa["authorized_to_work_us"], note=wa["authorized_explanation"])
    if re.search(r"citizen|permanent\s+resident|green\s*card", L):
        return put(wa["us_citizen_or_permanent_resident"])
    if re.search(r"visa\s+status|immigration\s+status|work\s+permit", L):
        return put(wa["visa_status"])
    if re.search(r"export\s+control", L):
        return put(wa["export_control_category"], prefer="alien")
    if re.search(r"clearance", L):
        return put(wa["security_clearance"])

    # education and dates
    yes_no = not options or {o.lower().strip() for o in options} <= {"yes", "no"}
    window = grad_window(L)
    if window is not None and yes_no:
        put("Yes" if window else "No", "FILLED",
            "" if window else "the honest answer is No: he graduates May 2027. A required cohort "
                              "question usually filters, so decide whether this is worth submitting")
        res["warn"] = not window
        return res
    if re.search(r"graduat", L) and not re.search(r"\bgpa\b", L):
        if options:
            chosen = next((o for o in options if "2027" in o and re.search(r"may|june|spring", o, re.I)), None)
            return put(chosen or ed["graduation_month_year"], "FILLED" if chosen else "NEEDS YOU")
        return put(ed["graduation_month_year"])
    if re.search(r"\bgpa\b|grade\s+point", L):
        gnote = "M.S. GPA 3.95; bachelor's " + val(ed["gpa_bachelors"])[0] + " (unverified) if they ask for it"
        th = re.search(r"(\d\.\d+)\s*(or\s+(higher|above|greater|more)|\+|and\s+above)", L)
        if th and yes_no:
            return put("Yes" if GPA >= float(th.group(1)) else "No", "FILLED", gnote)
        if options:
            return put(gpa_option(options) or ed["gpa"], "FILLED", gnote)
        return put(ed["gpa"], note=gnote)
    if "transcript" in L:
        return put("", "NEEDS YOU", "upload an unofficial transcript")

    # money and logistics
    if re.search(r"salary|compensation|pay\s+(range|expectation)|expected\s+pay|desired\s+pay", L):
        s, why = salary(row)
        return put(s, "CONFIRM", why)
    if re.search(r"relocat", L):
        return put(av["willing_to_relocate"], note=av["relocation_explanation"], prefer="relocat")
    if re.search(r"(currently\s+)?(located|living|residing|based)\s+in\s+the\s+(united\s+states|u\.?s\.?)", L):
        return put("Yes", "FILLED", f"{ct['city']}, {ct['state_code']}")
    # a location question whose options include moving: "Able to relocate to job
    # location" (InterSystems), "I am open to working in any office" (Stripe)
    if options and re.search(r"location|office|city|site", L) and not yes_no:
        flex = next((o for o in options if re.search(r"relocat", o, re.I)), None) \
            or next((o for o in options if re.search(r"open\s+to|any\s+(office|location)|flexible|no\s+preference", o, re.I)), None)
        if flex:
            return put(flex, "CONFIRM", "willing to relocate anywhere in the US; pick a city instead if you prefer one")
        return put("", "DECISION", f"a location preference: {options}")
    if re.search(r"on-?site|in\s+the\s+office|in-office|office\(s\)|work\s+from\s+the\s+office|hybrid|headquarters"
                 r"|commut|days\s+(a|per)\s+week", L):
        if options and not yes_no and not any(o.lower().startswith(("yes", "no")) for o in options):
            return put("", "DECISION", f"a location preference: {options}")
        return put(av["willing_onsite_5_days"], note="willing to relocate; not currently within commuting distance",
                   prefer="relocat")
    if re.search(r"start\s+date|when\s+can\s+you\s+start|available\s+to\s+start|earliest|notice\s+period", L):
        if options and not yes_no:
            return put(start_option(options) or av["earliest_full_time_start"], note=av["explanation"])
        return put(av["earliest_full_time_start"], note=av["explanation"])
    if re.search(r"offer\s+deadline|recruiting[-\s]process\s+deadline|competing\s+offer|other\s+offers?", L):
        con = sqlite3.connect(DB)
        offers = con.execute("SELECT count(*) FROM applications WHERE status='offer'").fetchone()[0]
        con.close()
        if not offers:
            return put("No", "CONFIRM", "no offer in the pipeline")
        return put("", "NEEDS YOU", f"{offers} offer(s) in the pipeline")

    # history with this employer, from the pipeline itself
    if re.search(r"(previously|ever|before).{0,30}appl|appl\w*.{0,40}before", L):
        prior = prior_applications(row)
        return put("Yes" if prior else "No", "FILLED",
                   ("pipeline shows: " + "; ".join(prior[:3])) if prior else "no prior application in the pipeline")
    if re.search(r"interview\w*.{0,30}before", L):
        return put(ANSWERS["prior_contact"]["interviewed_here_before"], "CONFIRM")
    if re.search(r"worked\s+for\s+(an?\s+)?[\w.]+\s+(client|customer|partner|vendor|competitor)", L):
        return put("No", "CONFIRM", "MAQ Software served client companies; check none of them is on their list")
    if re.search(r"(previously|ever|formerly).{0,25}(employed|worked)|former\s+employee|employment\s+history", L):
        return put(ANSWERS["prior_contact"]["previously_employed_here"])
    if re.search(r"government\s+official|public\s+official|politically\s+exposed", L):
        return put("", "NEEDS YOU", "he works for the University of Missouri, a PUBLIC university, and some "
                                    "definitions count staff of government-owned entities as officials. Read "
                                    "their definition before answering; if unsure, answer Yes and explain")
    if re.search(r"familial|personal.{0,25}relationships?|outside\s+business\s+activit|conflicts?\s+of\s+interest", L):
        return put("No", "CONFIRM", "no relationship or outside business activity recorded")
    if re.search(r"employee'?s?\s+(email|name)|referrer'?s?\s+(email|name)|name\s+of\s+(the\s+)?(employee|referrer)", L):
        return put("", "FILLED", "skip: no referral recorded in the pipeline")
    if re.search(r"\breferr", L):   # word boundary: "Preferred Name" matched a bare "referr"
        return put(ANSWERS["prior_contact"]["referred_by_employee"], "CONFIRM", "no referral recorded in the pipeline")
    if re.search(r"know\s+anyone|related\s+to\s+anyone|relatives?\s+(who\s+)?work|family\s+members?\s+(who\s+)?work", L):
        return put("No", "CONFIRM", "nobody recorded at this employer in the pipeline's contacts")
    if re.search(r"how\s+did\s+you\s+(hear|find|learn)|where\s+did\s+you\s+(hear|find|see)"
                 r"|\b(referral|application|candidate|job|lead)\s+source\b|^source\b", L):
        want = how_heard(row)
        chosen = pick_option(options, want)
        if not chosen and want == "Company website":
            # ID.me says "ID.me Careers page", others "Company Website" or "Careers Site"
            chosen = next((o for o in options if re.search(r"career\w*\s+(page|site)|website|job\s+board", o, re.I)), None)
        chosen = chosen or pick_option(options, "other")
        return put(chosen or want, "CONFIRM", f"pipeline source: {row.get('source') or 'unknown'}")
    if re.search(r"campus\s+(recruiting\s+)?event|career\s+fair", L):
        return put("", "DECISION", "only if you attended one of theirs")

    # personal and EEO: his choices
    if "pronoun" in L:
        return put("", "DECISION", "never stated; choose what you want shown")
    if re.search(r"military|served\s+in", L):
        return put(*val(pe["military_service"])[:2])
    if "veteran" in L:
        return put("", "DECISION", "voluntary self-identification")
    if re.search(r"\bgender\b|\bsex\b|race|ethnic|hispanic|latino|disabilit", L):
        return put("", "DECISION", "voluntary self-identification; declining is always allowed")
    if re.search(r"criminal|convict|felony", L):
        return put("", "DECISION", "never pre-filled")
    if re.search(r"18\s+years|at\s+least\s+18|over\s+18", L):
        return put(pe["over_18"])

    # experience and identity
    m = re.search(r"(more\s+than|at\s+least|over|minimum\s+(?:of\s+)?|greater\s+than)\s+(\d+)\s*\+?\s*(?:plus\s+)?years?", L) \
        or re.search(r"(\b)(\d+)\s*(?:\+|plus)\s*years?", L)                     # "3+ years of SQL" means at least 3
    if m and yes_no and re.search(r"experience", L):
        n, have = int(m.group(2)), ex["full_time_months"] / 12
        ok = have > n if (m.group(1) or "").startswith(("more", "over", "greater")) else have >= n
        generic = re.search(r"(full[-\s]?time|professional|work|industry)\s+(work\s+)?experience", L)
        if generic or not ok:
            # Capco, 2026-09-16: "at least 2 plus years of Technical Business Analyst experience?" was left
            # blank. 13 months of full-time work in total cannot contain 2 years of any one kind, so the
            # honest answer is No whatever the specialism. A Yes still needs the specialism checked.
            res["warn"] = not ok and bool(res["required"])
            return put("Yes" if ok else "No", "FILLED", f"{ex['full_time_months']} months full-time in total, excluding internships"
                       + ("; a required experience floor he does not meet usually filters" if not ok else ""))
    if re.search(r"how\s+many.{0,40}(internship|co-?op)", L):
        return put(ex["internships_completed"], "FILLED", "SP Software 2024 and HiringFIT 2023, both software")
    if re.search(r"how\s+many\s+years|years\s+of\s+.{0,40}experience", L):
        return put(ex["years_professional"], "CONFIRM",
                   ex["years_explanation"] + " If the question is about one specific skill, answer for that skill.")
    if re.search(r"(current|most\s+recent|latest|present)\s+(company|employer)", L):
        return put(ex["current_company"])
    if re.search(r"(current|most\s+recent|latest|present)\s+(job\s+)?(title|position|role)", L):
        return put(ex["current_title"])
    if re.search(r"engineer(ing)?\s+(profile\s+types?|preference)|team\s+preference|area\s+of\s+interest", L):
        return put("", "DECISION", f"your interest; the resume best supports backend and full-stack work. Options: {options}")
    if re.search(r"\b(sat|act|gre|gmat)\b.{0,20}scores?", L):
        return put("", "DECISION", "optional; leave blank unless you have a score you want to share")
    if re.search(r"which\s+of\s+the\s+following.{0,40}(experience|skills|technolog|areas)", L):
        return put("", "NEEDS YOU", "select only what the evidence bank backs; the option text is in the posting")
    if re.search(r"showcases?|link.{0,40}(built|shipped|work\s+sample)|code\s+sample|sample\s+of\s+(some\s+)?code", L):
        return put("", "NEEDS YOU", "one repo he built, opened signed out first. Never Guardian AI or SPD-React "
                                    "until their security issues are fixed")
    if "linkedin" in L:
        return put(ct["linkedin"])
    if re.search(r"github|portfolio|website|personal\s+site", L):
        return put(ct["github"] if "github" in L else ct["portfolio"],
                   note=f"GitHub {ct['github']} ; portfolio {ct['portfolio']}")
    if re.search(r"publication|google\s+scholar", L):
        return put("", "FILLED", "leave blank: no publications")
    if re.search(r"preferred\s+(first\s+)?name", L):
        return put(*val(ct["preferred_first_name"])[:2])
    if re.search(r"\b(school|university|college)\b", L):
        return put(ed["current_school"])
    if re.search(r"\bdegree\b", L):
        return put(ed["degree"])
    if re.search(r"major|field\s+of\s+study|discipline", L):
        return put(ed["field_of_study"])
    if re.search(r"(which|what)\s+state|state\s+of\s+residence|\breside\b", L):
        return put(ct["state"] if not options or pick_option(options, ct["state"]) else ct["state_code"])
    if re.search(r"\b(city|location|where\s+are\s+you\s+(located|based))\b", L):
        return put(f"{ct['city']}, {ct['state_code']}", note="willing to relocate anywhere in the US")
    # not a bare "address": CaseGuard asks "how might you address them?"
    if re.search(r"(home|street|mailing|current|postal|residential)\s+address|^address\b|address\s+line|zip|postal\s+code", L):
        return put("", "NEEDS YOU")

    # "Do you have experience with CyberArk?" is answered from the evidence bank, never from hope
    m = re.search(r"(?:do|have)\s+you\s+(?:have\s+)?(?:any\s+)?(?:hands-on\s+|prior\s+|professional\s+)?experience\s+"
                  r"(?:with|in|using|supporting|building|working\s+with|(?:programming|developing|coding)\s+(?:in|with))"
                  r"\s+([^?]+)", label, re.I)
    if m and yes_no:
        # whole named items, not words: "Privileged Access Management" matched a
        # bare "Access" and "Management" in the bank and answered Yes to CyberArk
        items = []
        for seg in re.split(r",|\s+or\s+(?:other\s+)?|\s+and\s+(?:other\s+)?|\s+such\s+as\s+|\(|\)|\be\.g\.", m.group(1)):
            seg = re.sub(r"\b(platforms?|tools?|systems?|frameworks?|technologies|solutions?|software|services?"
                         r"|environments?|like|similar|etc\.?)\b", "", seg).strip(" .")
            if seg and re.search(r"[A-Z]", seg):
                items.append(seg)
        if items:
            found = [s for s in items if re.search(rf"(?<![\w]){re.escape(s)}(?![\w])", EVIDENCE_TEXT, re.I)]
            missing = [s for s in items if s not in found]
            if found:
                return put("Yes", "CONFIRM", f"the evidence bank mentions {', '.join(found)}"
                           + (f" but not {', '.join(missing)}" if missing else "") + "; check it is real experience")
            return put("No", "CONFIRM", f"the evidence bank never mentions {', '.join(items)}")

    # everything else that asks for words is written for this role
    if ftype == "textarea" or OPEN_Q.search(L):
        return put("", "OPEN", "write for this role from profile/voice.md and the evidence bank (/apply)")
    return put("", "NEEDS YOU", "no rule matched")


# ---------------------------------------------------------------- packet

STANDARD_SET = [
    ("Are you legally authorized to work in the United States?", "input_text"),
    ("Will you now or in the future require visa sponsorship?", "input_text"),
    ("What is your current visa status?", "input_text"),
    ("Are you a U.S. citizen or permanent resident?", "input_text"),
    ("What is your expected graduation month and year?", "input_text"),
    ("Cumulative GPA", "input_text"),
    ("When can you start?", "input_text"),
    ("Are you willing to relocate?", "input_text"),
    ("What are your salary expectations?", "input_text"),
    ("How did you hear about this job?", "input_text"),
    ("Have you previously applied to this company before?", "input_text"),
    ("Current company", "input_text"),
    ("LinkedIn Profile", "input_text"),
    ("GitHub", "input_text"),
    ("How many years of experience do you have?", "input_text"),
]


def build(row: dict) -> tuple[str, dict]:
    url = row.get("url") or ""
    known = board_token(row)
    gh = greenhouse_questions(url, known) if url else None
    readable = bool(gh and gh[2] is not None)
    findings = {"hard": []}
    if readable:
        questions = gh[2]
        verdict, findings = classify(questions)
        source = f"the real Greenhouse form ({gh[0]}/{gh[1]}, {len(questions)} questions)"
    else:
        questions = [{"label": l, "required": False, "fields": [{"type": t, "name": ""}]} for l, t in STANDARD_SET]
        verdict = "MANUAL"
        source = "the standard set; this ATS does not expose its form, so open it and match these up"

    rows = []
    for q in questions:
        rows.append(answer(q, row, rows[-1] if rows else None))
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    L = []
    L.append(f"# Application packet: {row.get('company')} / {row.get('role')}")
    L.append("")
    L.append(f"Pipeline row #{row['id']} | built {date.today().isoformat()} | STAGED: you review and press submit")
    L.append(f"Apply: {url}")
    L.append(f"Form check: {verdict} | answers built from {source}")
    L.append("")
    L.append("| Status | Count |")
    L.append("|---|---|")
    for s in ("FILLED", "CONFIRM", "DECISION", "OPEN", "NEEDS YOU"):
        if counts.get(s):
            L.append(f"| {s} | {counts[s]} |")
    L.append("")

    L.append("## Before you submit")
    L.append("")
    todo = [r for r in rows if r["status"] in ("NEEDS YOU", "OPEN", "DECISION", "CONFIRM") and (r["required"] or not readable or r["status"] != "DECISION")]
    for h in findings.get("hard", []):
        L.append(f"- **BLOCKER**: {h[:110]}. A citizenship or clearance gate with no lawful non-citizen option. Do not submit.")
    if not readable:
        L.append("- The form could not be read. Open the apply page and match each question to the answers below.")
    for r in rows:
        if r["warn"]:
            L.append(f"- **WARNING**: {r['label'][:110]}. {r['note']}")
    for r in todo:
        req = " (required)" if r["required"] else ""
        L.append(f"- **{r['status']}**{req}: {r['label'][:110]}" + (f". {r['note']}" if r["note"] else ""))
    if not todo and readable:
        L.append("- Nothing. Every question has an answer.")
    L.append("")

    resume, cover = artifact_path(row["id"], "resume"), artifact_path(row["id"], "cover_letter")
    L.append("## Files")
    L.append("")
    L.append(f"- Resume: {resume or 'NOT BUILT YET, run /resume-rewrite for this row'}")
    L.append(f"- Cover letter: {cover or 'none built; add one only if the form requires it'}")
    L.append("")

    L.append("## The form, in order" if readable else "## Standard answers")
    L.append("")
    for i, r in enumerate(rows, 1):
        req = " *(required)*" if r["required"] else ""
        kind = " [dropdown]" if r["options"] else (" [file]" if r["type"] == "input_file" else "")
        L.append(f"{i}. **{r['label']}**{req}{kind}")
        if r["answer"]:
            L.append(f"   `{r['answer']}`")
        L.append(f"   {r['status']}" + (f": {r['note']}" if r["note"] else ""))
        L.append("")
    info = {"counts": counts, "verdict": verdict, "readable": readable,
            "rows": [{k: x[k] for k in ("label", "required", "type", "status", "answer")} for x in rows],
            "blockers": list(findings.get("hard", [])),
            "warnings": [r["label"] for r in rows if r["warn"]],
            # questions only: an unbuilt resume is expected at queue time, not a gap
            "open_required": sum(1 for r in rows if r["required"] and r["status"] in ("NEEDS YOU", "OPEN")
                                 and r["type"] != "input_file")}
    return "\n".join(L), info


def write_packet(app_id: int, log: bool = True) -> tuple[Path, str, dict]:
    """Build, write and (once) log the packet for one row. build_queue.py calls this."""
    row = load_row(app_id)
    text, info = build(row)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{row.get('company')}-{row.get('role')}".lower()).strip("-")[:60]
    out = ROOT / "data" / "artifacts" / slug / f"packet-{app_id}.md"   # IXL has two rows with one slug
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    rel = str(out.relative_to(ROOT))
    if log and artifact_path(app_id, "packet") != rel:   # rebuilding the same packet is not a new artifact
        subprocess.run([sys.executable, str(HERE / "pipeline.py"), "artifact", str(app_id),
                        "--kind", "packet", "--path", rel], capture_output=True, text=True)
    return out, text, info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", type=int, required=True)
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--no-log", action="store_true")
    a = ap.parse_args()

    out, text, info = write_packet(a.app, log=not a.no_log)
    print(f"packet: {out.relative_to(ROOT)}  form {info['verdict']}  "
          + "  ".join(f"{k} {v}" for k, v in info["counts"].items()))
    if a.print:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
