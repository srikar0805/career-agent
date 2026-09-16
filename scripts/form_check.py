#!/usr/bin/env python3
"""Read the APPLICATION FORM's screening questions before a resume is built.

WHY THIS EXISTS. Three applications died at the form in one week, every one of
them after a posting that screened completely clean:

    Emerson  2026-09-11  posting said only "Legal authorization to work in the
                         United States". Applied. Told there is no sponsorship.
    Equifax  2026-09-11  posting had NO sponsorship, citizenship or clearance
                         language at all. Best application in the pipeline,
                         paper 76 / realistic 27. Rejected 02:20 two days later:
                         "we are unable to offer sponsorship for this role."
    BCG X    2026-09-13  posting clean, graduation window an exact match, and
                         the portal refuses with "you are not eligible".

`screen_job.py` reads postings. It cannot read forms, and the form is where the
applications are dying. That is a gap in the design, not a tuning problem.

WHAT IS ACTUALLY READABLE. Measured 2026-09-13, not assumed:

    Greenhouse   FULL FORM via ?questions=true. Kikoff returned 14 questions
                 including "Do you now or in the future require visa sponsorship
                 to continue working in the United States?" with Yes/No.
                 Anthropic returned 15 questions and ZERO authorization items,
                 so the check discriminates rather than always firing.
    Lever        NO form fields in the postings API. Keys are description,
                 lists, salaryRange and so on. Nothing to read.
    Ashby        NO applicationFormDefinition in the job-board API.
    Workday      behind the candidate session.
    Oracle HCM   behind the candidate session.
    BCG / other  bespoke portals, nothing public.

So this returns MANUAL for most employers, and that is the honest answer: open
the form and look. A two-minute check beats a two-hour build.

    form_check.py <url>
    form_check.py --app <pipeline id>

exit 0 clean, 1 flagged, 2 manual check required, 3 hard blocker
"""
import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# The question that has now closed two applications in a week. Its mere presence
# is not proof of rejection: he answers honestly and some employers proceed.
# But Equifax asked it and rejected in 48 hours, so it is a FLAG, loudly.
SPONSOR_Q = re.compile(
    r"(now\s+or\s+in\s+the\s+future|currently\s+or\s+in\s+the\s+future|future)"
    r"[^?]{0,80}(sponsor|visa)"
    r"|require[^?]{0,40}(visa\s+)?sponsor"
    r"|need[^?]{0,30}sponsor"
    r"|authoriz\w+\s+to\s+work[^?]{0,60}without\s+sponsor"
    r"|without\s+(visa\s+|employer\s+)?sponsor", re.I)

# These are absolute for a non-citizen. If they appear as a form question the
# application is over regardless of how the posting read.
HARD_Q = re.compile(
    r"\b(u\.?s\.?\s+citizen|united\s+states\s+citizen|citizenship\s+status"
    r"|security\s+clearance|active\s+clearance|do\s+you\s+hold\s+a\s+clearance"
    r"|export\s+control|itar)\b", re.I)

# BCG-style gating: a fixed list of schools the employer recruits from. If the
# dropdown has no University of Missouri the application cannot be submitted.
SCHOOL_Q = re.compile(r"\b(school|university|institution|college|alma\s+mater)\b", re.I)


# An export-control or citizenship-status question that OFFERS a lawful non-citizen
# option is a disclosure, not a gate. ASM International's export-control question
# lists "Alien Authorized to Work", which is exactly what he is on CPT and OPT, so
# calling it a BLOCKER would have withdrawn a viable row. That is the same mistake
# as the 2026-09-09 false withdrawals, and the cost of a false BLOCKER is higher
# than the cost of a FLAG: one discards a real opportunity, the other asks him to
# look. When the options say he can answer honestly and continue, downgrade.
ESCAPE_OPT = re.compile(
    r"alien\s+authorized|authorized\s+to\s+work|non[- ]?(us|u\.s\.)\s*person"
    r"|require\s+sponsorship|refugee|asylee|none\s+of\s+the\s+above", re.I)


def _get(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, f"__ERROR__ {e}"



def _resolve_embed_token(url: str, jid: str):
    """Find the real Greenhouse board token behind a company-hosted ?gh_jid= page.

    The hostname is NOT the token often enough to matter: DigitalOcean's board is
    `digitalocean98`, discoverable only inside a Next.js chunk. Guessing it wrong
    once caused seven false "definitive dead" verdicts and six live rows were
    wrongly withdrawn on 2026-09-09. So every candidate is VERIFIED against the
    board before it is used, and an unresolved token returns None rather than a
    confident wrong answer.
    """
    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].split(".")[0]
    candidates = [host, host.replace("-", "")]
    # the page itself usually names the board in a script tag
    code, body = _get(url)
    if code == 200 and body:
        candidates += re.findall(r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([\w-]+)", body)
        candidates += re.findall(r"[\"']([a-z0-9-]{3,30})[\"']\s*[,:]\s*[\"']?greenhouse", body, re.I)
    seen = set()
    for tok in candidates:
        if not tok or tok in seen or tok in ("v1", "boards", "embed", "job_app"):
            continue
        seen.add(tok)
        c, b = _get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs/{jid}")
        if c == 200:
            return tok
    return None


def greenhouse_questions(url: str, known_token: str | None = None):
    """Return (token, job_id, [question dicts]) or None if not a Greenhouse URL.

    known_token comes from the pipeline row's notes. Several board tokens have
    already been worked out the hard way and written down (DigitalOcean's is
    `digitalocean98`, recorded on row #61 after it took a Next.js chunk to find).
    Re-deriving what is already known is how the 2026-09-09 false-withdrawal
    incident happened, so use the recorded value when there is one.
    """
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", url)
    if m:
        tok, jid = m.group(1), m.group(2)
    else:
        m2 = re.search(r"[?&]gh_jid=(\d+)", url)
        if not m2:
            return None
        jid = m2.group(1)
        tok = _resolve_embed_token(url, jid) or known_token
        if not tok:
            return ("?", jid, None)
    code, body = _get(
        f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs/{jid}?questions=true")
    if code != 200:
        return (tok, jid, None)
    try:
        return (tok, jid, json.loads(body).get("questions") or [])
    except Exception:
        return (tok, jid, None)


def classify(questions):
    """Return (verdict, findings). Never guesses when it cannot see the form."""
    hard, flags, school = [], [], []
    for q in questions:
        label = (q.get("label") or "").strip()
        opts = []
        for f in q.get("fields", []):
            opts += [(v.get("label") or "") for v in (f.get("values") or [])]
        blob = label + " " + " ".join(opts)
        if HARD_Q.search(blob):
            # only a real gate if there is no lawful non-citizen option to pick
            if opts and ESCAPE_OPT.search(" ".join(opts)):
                flags.append((label, opts[:6]))
            else:
                hard.append(label)
        elif SPONSOR_Q.search(blob):
            flags.append((label, opts[:6]))
        elif SCHOOL_Q.search(label) and len(opts) > 3:
            school.append((label, len(opts)))
    if hard:
        return "BLOCKER", {"hard": hard, "sponsor": flags, "school": school}
    if flags or school:
        return "FLAG", {"hard": [], "sponsor": flags, "school": school}
    return "CLEAN", {"hard": [], "sponsor": [], "school": []}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?")
    ap.add_argument("--app", type=int, help="read the url from this pipeline row")
    a = ap.parse_args()

    url = a.url
    known = None
    if a.app:
        out = subprocess.run([sys.executable, str(HERE / "pipeline.py"),
                              "show", str(a.app), "--json"],
                             capture_output=True, text=True).stdout
        try:
            doc = json.loads(out)
            row = doc.get("application", doc)   # pipeline.py nests under "application"
            url = row.get("url")
            m = re.search(r"board token is ([\w-]+)",
                          json.dumps(doc), re.I)   # notes may live on the row or in history
            if m:
                known = m.group(1)
        except Exception:
            pass
    if not url:
        print("form_check: need a url or --app <id>")
        return 2

    gh = greenhouse_questions(url, known)
    if gh is None:
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        print(f"form_check: MANUAL CHECK REQUIRED  ({host})")
        print("  This ATS does not expose its application form. Measured 2026-09-13:")
        print("  Lever and Ashby return no form fields; Workday, Oracle HCM and")
        print("  bespoke portals keep the form behind a candidate session.")
        print("")
        print("  OPEN THE APPLY PAGE AND READ THE QUESTIONS BEFORE BUILDING. Look for:")
        print("    * 'now or in the future require sponsorship'  <- closed Equifax in 48h")
        print("    * citizenship or security clearance           <- absolute, stop")
        print("    * a school dropdown with a fixed list         <- BCG-style gating")
        return 2

    tok, jid, questions = gh
    if questions is None:
        print(f"form_check: MANUAL CHECK REQUIRED  (greenhouse {tok}/{jid}, form not returned)")
        return 2

    verdict, f = classify(questions)
    print(f"form_check: {verdict}  (greenhouse {tok}/{jid}, {len(questions)} questions)")
    for h in f["hard"]:
        print(f"  BLOCKER  {h[:110]}")
        print("           Absolute for a non-citizen. Do not build.")
    for label, opts in f["sponsor"]:
        print(f"  FLAG     {label[:110]}")
        if opts:
            print(f"           options: {', '.join(o for o in opts if o)[:90]}")
        print("           He must answer YES. Emerson and Equifax both asked a form")
        print("           question like this after a clean posting, and both closed.")
    for label, n in f["school"]:
        print(f"  FLAG     {label[:80]}  ({n} fixed options)")
        print("           Check University of Missouri is in the list before building.")
    if verdict == "CLEAN":
        print("  No sponsorship, citizenship, clearance or school-gate question found.")
    return {"BLOCKER": 3, "FLAG": 1, "CLEAN": 0}[verdict]


if __name__ == "__main__":
    sys.exit(main())
