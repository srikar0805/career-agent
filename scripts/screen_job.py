#!/usr/bin/env python3
"""Fetch a real job description and decide whether Srikar meets the minimum bar.

The old watcher matched on TITLE only, which is why a morning's list could be
half defense contractors he can never work for. This reads the posting itself
and screens against profile/identity.yaml, so a job only reaches him if he
actually clears the stated minimums.

Two kinds of finding, and the distinction matters:

  BLOCKER  a stated minimum he cannot meet, ever, by trying harder. Citizenship,
           clearance, an explicit no-sponsorship line, a PhD requirement, a
           years-of-experience floor above his 1.3, or a required language he
           has no repository for. One blocker drops the job.

  FLAG     something he should see but that does not disqualify. Immediate
           full-time start (he cannot until May 2027), heavy relocation, or a
           preferred-but-not-required technology he lacks.

Deliberately conservative in both directions: it will not drop a job on a
"preferred" line, and it will not pass one that says "must be a U.S. citizen".
Ambiguity resolves toward showing him the job, because a false drop is
invisible and a false pass costs him ten minutes.
"""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (career-agent)"}

# ---------------------------------------------------------------- fetching

def _get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _detag(raw: str) -> str:
    t = html.unescape(raw)
    t = re.sub(r"(?s)<(script|style).*?</\1>", " ", t)
    t = re.sub(r"<(br|/p|/div|/li|/h\d|/tr)[^>]*>", "\n", t)
    t = re.sub(r"<li[^>]*>", "  * ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()


def fetch_jd(url: str) -> str:
    """Return posting text. Uses each ATS's public JSON where one exists."""
    try:
        m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", url)
        if m:
            d = json.loads(_get(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}"))
            return _detag(d.get("content", ""))

        m = re.search(r"ashbyhq\.com/([\w-]+)/([0-9a-f-]{36})", url)
        if m:
            d = json.loads(_get(f"https://api.ashbyhq.com/posting-api/job-board/{m[1]}"))
            for j in d.get("jobs", []):
                if j.get("id") == m[2]:
                    return _detag(j.get("descriptionHtml", ""))
            return ""

        m = re.search(r"jobs\.lever\.co/([\w-]+)/([0-9a-f-]{36})", url)
        if m:
            d = json.loads(_get(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}"))
            # `additional` is where Lever employers put the EEO and work-authorization
            # paragraph. Without it Callan #259's "unable to sponsor or take over
            # sponsorship" was invisible to this screener (found 2026-09-16); the
            # 12 Sep withdrawal only happened because Stage 2 read the page itself.
            return _detag(d.get("description", "") + " " +
                          " ".join(s.get("text", "") + " " + s.get("content", "")
                                   for s in d.get("lists", []) or []) + " " +
                          d.get("additional", ""))

        m = re.search(r"([\w-]+)\.bamboohr\.com/careers/(\d+)", url)
        if m:
            d = json.loads(_get(f"https://{m[1]}.bamboohr.com/careers/{m[2]}/detail"))
            jo = d.get("result", d).get("jobOpening", {})
            return _detag(jo.get("description", ""))

        return _detag(_get(url))          # generic HTML, best effort
    except Exception as e:
        return f"__FETCH_FAILED__ {e}"


# ---------------------------------------------------------------- screening

CITIZEN = re.compile(
    r"(u\.?s\.?\s*citizen(ship)?\s*(is\s*)?(require|only|mandat)|must be a u\.?s\.? citizen"
    r"|security clearance|active clearance|secret clearance|\bts/sci\b|\bitar\b|export[- ]control"
    r"|public trust|dod clearance|government clearance)", re.I)

# Sanofi 2026-08-21 slipped through and it should not have. Two failures:
# the distance window was 80 chars and the real sentence needed ~95, and it
# says "at the time of application or in the future" rather than the "now or in
# the future" the pattern expected. A posting that names CPT/OPT/STEM OPT and
# excludes them is the least ambiguous signal there is, so it gets its own rule.
EXCLUDES_F1 = re.compile(
    r"\b(cpt|opt|stem\s*opt|f-?1)\b[^.]{0,140}(do(es)?\s+not\s+meet|are\s+not\s+eligible"
    r"|not\s+eligible|do(es)?\s+not\s+qualify|are\s+excluded|ineligible)"
    # Atlassian 2026-09-14 passed clean on "This position is not eligible for F1
    # and J1 students": the leading alternative knew f-1 but this trailing one
    # did not, and "not eligible" came first in the sentence.
    r"|(do(es)?\s+not\s+meet|not\s+eligible|ineligible)[^.]{0,140}\b(cpt|opt|stem\s*opt|f-?1|j-?1)\b"
    r"|permanent(ly)?\s+authorized\s+to\s+work[^.]{0,120}(not\s+require|without)\s+sponsor",
    re.I)

# Fulton Bank 2026-09-13 passed clean on "authorized to work in the United
# States without sponsorship for a work visa by Fulton Bank currently or in the
# future". The pattern knew "now or in the future" and "current or future" but
# not "currently or in the future", which is the same sentence with an adverb.
NO_SPONSOR_EVER = re.compile(
    # 2026-09-15, Epic Systems. "Eligibility to work in the U.S. without visa
    # sponsorship" passed every pattern, because they all expected "authorized"
    # and "United States". Epic's sister posting adds a TN carve-out, which is
    # the tell that "without sponsorship" means never, so it belongs here.
    # "U.S." is allowed through as a unit: the span otherwise refuses periods
    # so it cannot run across sentences, and "U.S." has two.
    r"eligib\w*\s+to\s+work(?:u\.s\.|[^.\n]){0,60}without\s+(visa\s+|employer\s+|employment\s+)?sponsor|"
    r"(now\s+or\s+in\s+the\s+future|current(?:ly)?\s+or\s+(?:in\s+the\s+)?future)[^.\n]{0,150}sponsor"
    r"|sponsor[^.\n]{0,150}(now\s+or\s+in\s+the\s+future|current(?:ly)?\s+or\s+(?:in\s+the\s+)?future)"
    r"|permanent(ly)?\s+authorized\s+to\s+work[^.\n]{0,60}without\s+sponsor"
    # United Airlines 2026-09-02 passed clean on "Must be legally authorized to
    # work in the United States for any employer without sponsorship". The
    # pattern expected "permanently"; the common phrasings are "legally" and
    # "lawfully", and "for any employer" is the tell that they mean permanent
    # authorization rather than a work permit with an end date.
    r"|(legal|lawful|permanent)\w*\s+authorized\s+to\s+work[^.\n]{0,90}without\s+(visa\s+|employment\s+)?sponsor"
    r"|authoriz\w+\s+to\s+work[^.\n]{0,60}for\s+any\s+employer"
    r"|without\s+(the\s+)?need\s+(for|of)\s+(current\s+or\s+future\s+)?(visa\s+|employment\s+)?sponsor", re.I)

# 2026-09-11, Emerson req 26009560. The posting's ONLY authorization line was
# "Legal authorization to work in the United States", listed under required
# qualifications. That is literally satisfiable: he has legal authorization on
# CPT now and on OPT from June 2027. Every pattern above correctly passed it.
# Srikar applied, and Emerson then said they will not sponsor.
#
# So the bare phrase, with no "without sponsorship" and no "for any employer"
# qualifier, is a PRACTICAL no-sponsorship signal on campus and new-grad reqs
# even though it is not a literal one. It does NOT become a blocker, because
# the plain reading is true and blocking on it would drop reqs he can take.
# It becomes a flag, so the next one is surfaced BEFORE a resume is built.
BARE_LEGAL_AUTH = re.compile(
    r"(legal|lawful)\w*\s+authoriz\w+\s+to\s+work\s+in\s+the\s+(u\.?s\.?|united\s+states)",
    re.I)

NO_SPONSOR = re.compile(
    r"(not?\s+(be\s+)?(able\s+to\s+)?(provide|offer|sponsor)\w*\s+(visa\s+)?sponsor"
    r"|do(es)?\s+not\s+sponsor|without\s+(the\s+)?need\s+for\s+sponsor"
    r"|no\s+visa\s+sponsorship|unable\s+to\s+sponsor|sponsorship\s+is\s+not\s+(available|offered)"
    r"|not\s+(currently\s+)?(be\s+)?(able\s+to\s+|considering\s*).{0,30}sponsor"
    r"|will\s+not\s+sponsor|cannot\s+sponsor"
    # KeyCorp 2026-09-14: "NOT eligible for employment visa sponsorship for
    # non-U.S. citizens" carried two qualifiers, and the pattern allowed one.
    r"|not\s+eligible\s+for\s+(?:(?:visa|immigration|employment|work)\s+){0,2}sponsor"
    r"|not\s+(available|open)\s+for\s+(visa\s+)?sponsor"
    r"|no\s+(current\s+or\s+future\s+)?(need\s+for\s+)?immigration\s+sponsorship"
    # Aramark 2026-09-14 passed clean on "Must be eligible to work in the United
    # States without employer sponsorship". "Eligible" is not "authorized", and
    # "employer" was not one of the qualifiers the patterns above allowed.
    r"|(eligible|authoriz\w+)\s+to\s+work[^.\n]{0,60}without\s+(?:\w+\s+){0,2}sponsor"
    r"|does\s+not\s+(offer|provide)\s+.{0,25}(cpt|opt))", re.I)

# 2026-09-02. Johns Hopkins APL and Publicis reached the queue as PASS. The
# fetch had returned 1,778 and 5,372 characters of icims page scaffolding, not
# a posting, so there was no citizenship line to find and the screener called
# it clean. Character count is not evidence that a job description was read.
# Every real posting contains at least one of these words; scaffolding has none.
JD_MARKERS = re.compile(
    r"\b(responsibilit\w*|qualification\w*|requirement\w*|what you.{0,3}ll do|"
    r"about the role|who you are|job description|preferred skills|"
    r"years of experience|we.{0,3}re looking for|minimum qualifications|"
    r"what you.{0,3}ll bring|role overview|job overview|skills and experience)\b",
    re.I)
# The trailing \b after a PREFIX never matches: "responsibilit\b" cannot match
# inside "Responsibilities". The first version of this rule would have called a
# perfectly readable posting unreadable and hidden it. \w* fixes it.

# Srikar is looking for FULL-TIME roles only, stated 2026-09-04. Internships,
# co-ops and part-time postings come out at the title stage, before any fetch.
# SUMMER_INTERN below already existed but only caught summer programmes; this
# catches the rest, including part-time and contract-shaped listings.
NOT_FULL_TIME = re.compile(
    r"\b(intern|interns|internship|internships|co-?op|"
    r"part.?time|apprentice(ship)?|work.?study|"
    r"summer\s+(analyst|associate|scholar)|"
    r"student\s+(worker|assistant|trainee))\b", re.I)

# Federally funded labs and UARCs. Nearly every posting requires U.S.
# citizenship, and many state it only on a page the fetcher cannot reach.
# Employer identity is a more reliable signal here than the fetched text.
# Applicant-tracking page chrome. If these appear, the fetch grabbed the site,
# not the job, whatever else happens to be on the page.
SCAFFOLD = re.compile(
    r"set to disconnect automatically|Go to the main content|My Jobpage|"
    r"tag of every page in order|Taleo Registration Page|session will end in|"
    r"Click OK to reset the timer|Jobs Matching My Profile", re.I)

CITIZENSHIP_EMPLOYERS = re.compile(
    r"(johns hopkins applied physics|\bapl\b|lincoln laborator|sandia|"
    r"los alamos|lawrence livermore|oak ridge|pacific northwest national|"
    r"idaho national|argonne|brookhaven national|jet propulsion|draper|"
    r"aerospace corporation|institute for defense analyses|mitre|"
    r"national security agency|federally funded research|two six technolog)", re.I)

# Employers that have told him directly they will not sponsor. The posting is
# not evidence either way for these, so the employer name is the evidence.
# This is a FLAG, not a blocker: OPT plus STEM OPT gives him 36 months from
# June 2027 that need no petition, only E-Verify enrolment and an I-983
# signature for the STEM half. Whether an employer that says "no sponsorship"
# will still take an OPT hire is a question to ask, not one to assume.
#
#   Emerson, 2026-09-11. Req 26009560 said only "Legal authorization to work in
#   the United States". Srikar applied and was then told there is no
#   sponsorship. See also BARE_LEGAL_AUTH above.
SAID_NO_SPONSOR_EMPLOYERS = re.compile(r"(emerson)", re.I)

# He holds F-1 status in the United States. A role based in another country
# needs that country's authorization, which he does not have.
NON_US_LOCATION = re.compile(
    r"\b(united kingdom|england|scotland|wales|northern ireland|"
    r"republic of ireland|luxembourg|india|poland|germany|france|spain|"
    r"netherlands|portugal|belgium|switzerland|sweden|denmark|norway|"
    r"canada|singapore|australia|new zealand|japan|china|hong kong|"
    r"south korea|israel|brazil|argentina|mexico|colombia|"
    r"united arab emirates|saudi arabia|south africa|egypt|nigeria|kenya)\b"
    r"|\bUK\b|\bU\.K\.|\bROI\b"
    r"|remote in (?!usa\b|us\b|the us\b|united states)",
    re.I)
# Anchored on COUNTRY names, not city names. The first version matched bare
# "melbourne" and dropped L3Harris in Melbourne, FLORIDA. Manchester, Berlin,
# Paris and Dublin all name US towns too. Every genuinely foreign row in the
# feed carries its country in the location string, so the country is enough.

# Alignment Healthcare 2026-09-15 passed clean on "Required: PhD in Computer
# Science": the requirement word came BEFORE the degree, as a label, and the
# pattern only looked after it. "Preferred: PhD" must still pass.
PHD = re.compile(r"(ph\.?d\.?|doctora\w+)\s+(is\s+)?(require|mandat|must)"
                 r"|\brequired:?\s+(?:an?\s+)?(?:ph\.?d\.?|doctora\w+)\b", re.I)

# "5+ years", "minimum of 3 years", "at least 4 years", "6 or more years"
# KeyCorp 2026-09-14 passed clean on "3-5 years of compliance, regulatory and
# community development experience": the range collapsed to "3 years" correctly,
# but 52 characters of domain words sat between "years" and "experience" and the
# window was 40. Bank and hospital reqs name the domain in that gap routinely.
# Chobani 2026-09-15 passed clean on "5+ years in a data analyst, data engineer,
# or BI developer role": the floor named the ROLE rather than "experience", so
# neither pattern saw it. "role" and "position" now close the phrase too.
YOE = re.compile(r"(?:(\d+)\s*(?:\+|or\s+more)?\s*years?|minimum of (\d+) years?|at least (\d+) years?)"
                 r"[^.\n]{0,70}?(experience|industry|professional|role|position)", re.I)

# A RANGE is not a floor. StorageMart 2026-09-03 says "1-3 years of
# professional web development experience" and the digit pattern below read
# the 3 and dropped the job. In "1-3 years" or "two to four years" the FLOOR
# is the first number. Strip ranges out before the floor patterns run.
YOE_RANGE = re.compile(
    r"(\d+)\s*(?:-|\u2013|\u2014|to|or)\s*(\d+)\s*\+?\s*years?", re.I)

# Postings often spell the floor out. "Two to three years of relevant
# experience" on U.S. Bank's Software Engineer 1 was invisible to the digit
# pattern above, so an experienced-hire req read as open to a new graduate.
WORD_NUM = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,
            "seven":7,"eight":8,"nine":9,"ten":10}
# U.S. Bank 2026-09-13 passed clean on "Six or more years of experience", and
# OU Health the same day on "At least three (3) years of related experience":
# the "or more" tail and the bracketed digit both sat between the word and
# "years", so neither pattern saw a floor. Both forms are common in bank and
# hospital postings.
YOE_WORDS = re.compile(r"\b(" + "|".join(WORD_NUM) + r")\b(?:\s*\(\d+\))?"
                       r"(?:\s*(?:to|-|or)\s*(?:" + "|".join(WORD_NUM) + r"))?"
                       r"\s*(?:\+\s*|or\s+more\s+)?years?[^.\n]{0,70}?(experience|industry|professional|role|position)", re.I)

# Languages/stacks with no repository behind them. Only a blocker when the
# posting REQUIRES it, never when it says "preferred".
#
# THIS LIST IS NOW PRUNED FROM profile/skills.yaml AT IMPORT. The hardcoded
# version was audited on 2026-08-20 and was wrong twice over: it listed C++,
# which EV-040 backs with a 710-line file, and C#, which TigerVerse backs with
# 9 files. On 2026-09-04 it dropped three PayPal roles for "requires .net"
# after Srikar had already told us he used .NET at MAQ. A static list of things
# he cannot do will always rot; derive it instead.
ABSENT = {
    "c++": r"\bc\+\+\b", "c#": r"\bc#\b", ".net": r"\.net\b|\basp\.net\b",
    "golang": r"\bgo(?:lang)?\b(?!\s*to)", "scala": r"\bscala\b",
    "kotlin": r"\bkotlin\b", "swift": r"\bswift\b", "ruby": r"\bruby\b",
    "php": r"\bphp\b", "rust": r"\brust\b", "embedded": r"\bembedded\b",
    "verilog": r"\bverilog\b|\bvhdl\b", "matlab": r"\bmatlab\b",
    "aws": r"\baws\b|amazon web services", "gcp": r"\bgcp\b|google cloud",
}

# Drop anything skills.yaml now backs. Names differ between the two files, so
# map them explicitly rather than guessing.
_SKILL_ALIAS = {"c++": "cpp", "c#": "c-sharp", ".net": "dotnet", "golang": "golang",
                "scala": "scala", "kotlin": "kotlin", "swift": "swift",
                "ruby": "ruby", "php": "php", "rust": "rust", "matlab": "matlab",
                "aws": "aws", "gcp": "gcp"}
_HELD = {"verified", "advanced", "working", "asserted-by-srikar"}
try:
    import yaml as _yaml
    _sk = {e["name"]: e.get("level") for e in
           _yaml.safe_load((ROOT / "profile" / "skills.yaml").read_text())}
    for _k, _name in _SKILL_ALIAS.items():
        if _sk.get(_name) in _HELD:
            ABSENT.pop(_k, None)
except Exception:
    pass   # a missing or unreadable skills file must not break screening
REQUIRED_CTX = re.compile(
    r"(required|requirement|must have|minimum qualif|basic qualif|you have|you must"
    r"|proficien|qualifications:)", re.I)
PREFERRED_CTX = re.compile(r"(preferred|nice to have|bonus|a plus|desirable|ideally)", re.I)

IMMEDIATE = re.compile(r"(start (full.?time )?(right away|immediately)|immediate start"
                       r"|available to start immediately|not a new grad role)", re.I)

MAX_YOE = 2          # he has ~1.3 years; a floor above 2 is a real wall

# Below this, the fetch almost certainly got a JS shell rather than the posting.
# A short document with no blockers in it is NOT a clean job, it is an unread
# one, and reporting PASS there is how L3Harris slipped through on 1,446 chars.
MIN_JD_CHARS = 900

# Defense, aerospace and gov-contract employers carry citizenship/ITAR
# requirements that frequently live outside the posting body. Never an
# automatic drop, always a manual check before he spends an evening on one.
ITAR_EMPLOYERS = re.compile(
    r"\b(l3harris|lockheed|northrop|raytheon|rtx|general dynamics|boeing|anduril"
    r"|spacex|viasat|leidos|booz allen|mitre|sandia|savannah river|battelle"
    r"|draper|aerospace corp|blue origin|palantir|bae systems|honeywell faa"
    r"|jacobs|peraton|caci|saic|parsons|kbr|amentum)\b", re.I)


# "at least one ... such as Golang, Java, C++, Python" is an OR list, and
# blocking on a single member of it is wrong: he clears that one twice over.
# But "programming with C/C++ or Rust" is ALSO an OR list, and he has none of
# those three. So the test is not "is this a list", it is "does the list
# contain something he actually has". Both readings were wrong before this.
ALTERNATIVE_CTX = re.compile(
    r"(at least one|one or more|such as|e\.g\.|for example|any of|either"
    r"|one of the following|or similar)", re.I)

# What he demonstrably has, verified against all 43 repositories.
HAS = re.compile(r"\b(python|java(?!script)|typescript|javascript|sql|bash|shell"
                 r"|node\.?js|react|pytorch)\b", re.I)


# Graduation-window screening. Campus programs state a window, and a summer
# internship's window is deliberately AFTER the following summer, because they
# want someone with a year of school left to convert. Srikar finishes in
# May 2027, so a "graduating Nov 2027 to Aug 2028" summer program is a hard no
# even though nothing else in the posting excludes him. Bank of America's
# Summer Analyst 2027 passed every other filter and is exactly this case.
GRAD_MONTH = r"(january|february|march|april|may|june|july|august|september|october|november|december|winter|spring|summer|fall|autumn)"
GRAD_WINDOW = re.compile(
    r"(?:graduat\w+|degree\s+completion|completion\s+timeframe|conferral)"
    r"[^.]{0,120}?"
    + GRAD_MONTH + r"\s*(20\d\d)"
    r"[^.]{0,40}?(?:and|to|through|[-\u2013])\s*"
    + GRAD_MONTH + r"\s*(20\d\d)", re.I)

# A degree conferred no earlier than this is too late for him.
GRAD_DATE = (2027, 5)          # May 2027
_MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
           "july":7,"august":8,"september":9,"october":10,"november":11,
           "december":12,"winter":1,"spring":5,"summer":7,"fall":9,"autumn":9}

SUMMER_INTERN = re.compile(
    r"\b(summer\s+(analyst|intern|internship)\s*(program)?|"
    r"(10|ten|9|nine|11|eleven|12|twelve)[-\s]week\s+(summer\s+)?(internship|program))\b", re.I)


def _requires(text: str, pattern: str) -> bool:
    """True only when the tech appears in a REQUIRED context, not a preferred one,
    and not as one option inside a list of acceptable alternatives."""
    for m in re.finditer(pattern, text, re.I):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        window = text[max(0, line_start - 220): line_end if line_end > 0 else len(text)]
        if PREFERRED_CTX.search(window):
            continue
        # The sentence the term sits in, not the wider window: an OR list is
        # local, while "Minimum Qualifications:" may be several lines above.
        sentence = text[max(0, m.start() - 130): m.end() + 130]
        # Only forgive the missing tech when the same list offers one he holds.
        if (ALTERNATIVE_CTX.search(sentence) or "/" in sentence) and HAS.search(sentence):
            continue
        if REQUIRED_CTX.search(window):
            return True
    return False


def screen(jd: str, company: str = "") -> dict:
    blockers, flags = [], []
    if jd.startswith("__FETCH_FAILED__"):
        return {"verdict": "UNKNOWN", "blockers": [], "flags": ["could not fetch posting"], "jd_chars": 0}

    if (m := CITIZEN.search(jd)):
        blockers.append(f"citizenship/clearance: \"{m.group(0)[:52]}\"")
    if (m := EXCLUDES_F1.search(jd)):
        blockers.append(f"explicitly excludes CPT/OPT/F-1: \"{' '.join(m.group(0).split())[:70]}\"")
    elif (m := NO_SPONSOR_EVER.search(jd)):
        blockers.append(f"no sponsorship EVER: \"{m.group(0)[:52]}\"")
    elif (m := NO_SPONSOR.search(jd)):
        # Not fatal. 12 months OPT + 24 months STEM OPT need nothing from them.
        flags.append(f"says it does not sponsor, but he has ~36 months that cost "
                     f"them nothing: \"{m.group(0)[:44]}\"")
    elif (m := BARE_LEGAL_AUTH.search(jd)):
        flags.append(f"lists \"legal authorization to work in the US\" as a "
                     f"requirement with no qualifier. He MEETS it on OPT, but "
                     f"Emerson used exactly this wording and then declined to "
                     f"sponsor. Ask before building a resume.")
    if SAID_NO_SPONSOR_EMPLOYERS.search(company or ""):
        flags.append("this employer has already told him directly that it does "
                     "not sponsor. Confirm whether an OPT hire is still possible "
                     "before building a resume.")
    if (m := PHD.search(jd)):
        blockers.append(f"PhD required: \"{m.group(0)[:40]}\"")

    # Employer identity first: it is knowable even when the posting is not.
    if CITIZENSHIP_EMPLOYERS.search(company or ""):
        return {"verdict": "DROP", "flags": [], "jd_chars": len(jd),
                "blockers": ["federally funded lab or UARC, U.S. citizenship "
                             "required for nearly every posting"]}

    # An unreadable posting is not a clean one. Say so instead of passing it.
    # ONE marker is not enough: Textron's Taleo shell scored a PASS on 2026-09-03
    # because the word "Qualifications" appears in the site's search furniture.
    # A real posting hits several distinct markers; page chrome hits one by luck.
    if jd and (SCAFFOLD.search(jd)
               or len({m.group(1).lower() for m in JD_MARKERS.finditer(jd)}) < 2):
        return {"verdict": "UNKNOWN", "blockers": [], "jd_chars": len(jd),
                "flags": [f"{len(jd)} chars retrieved but none of it reads like a "
                          f"job description, likely page scaffolding. Not screened"]}

    # Collapse "1-3 years" to "1 years" so the floor patterns see the lower
    # bound rather than the upper one.
    jd_yoe = YOE_RANGE.sub(lambda m: f"{m.group(1)} years", jd)

    worst = 0
    for m in YOE.finditer(jd_yoe):
        n = int(next(g for g in m.groups()[:3] if g))
        worst = max(worst, n) if n <= 15 else worst
    for m in YOE_WORDS.finditer(jd_yoe):
        n = WORD_NUM.get(m.group(1).lower(), 0)
        worst = max(worst, n) if n <= 15 else worst
    if worst > MAX_YOE:
        blockers.append(f"{worst}+ years experience required (he has ~1.3)")

    for name, pat in ABSENT.items():
        if _requires(jd, pat):
            blockers.append(f"requires {name}, no repository behind it")

    # Graduation window. A stated window that closes before he finishes, or
    # opens after he finishes, is a hard filter no recruiter will waive.
    for m in GRAD_WINDOW.finditer(jd):
        lo_mon, lo_yr, hi_mon, hi_yr = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        lo = (lo_yr, _MONTHS.get(lo_mon.lower(), 1))
        hi = (hi_yr, _MONTHS.get(hi_mon.lower(), 12))
        if lo <= hi and not (lo <= GRAD_DATE <= hi):
            side = "opens after" if GRAD_DATE < lo else "closed before"
            blockers.append(
                f"graduation window {side} May 2027: "
                f"\"{' '.join(m.group(0).split())[:80]}\"")
            break

    # A summer internship wants someone with school left afterwards. He does not
    # have any after May 2027, so these are structurally out even when the
    # window is not spelled out.
    if SUMMER_INTERN.search(jd) and not re.search(r"full[- ]time\s+(analyst|program|role)", jd, re.I):
        flags.append("reads as a SUMMER internship, which wants a returning "
                     "student; he graduates May 2027 and has no year left to return to")

    if IMMEDIATE.search(jd):
        flags.append("wants an immediate full-time start; he cannot before May 2027")

    if ITAR_EMPLOYERS.search(company or "") or ITAR_EMPLOYERS.search(jd[:1500]):
        flags.append("defense/aerospace employer: verify citizenship or ITAR "
                     "requirements before spending time on it")

    if blockers:
        verdict = "DROP"
    elif len(jd) < MIN_JD_CHARS:
        verdict = "UNKNOWN"
        flags.insert(0, f"only {len(jd)} chars retrieved, posting likely "
                        f"JavaScript-rendered. Not screened, read it yourself")
    else:
        verdict = "PASS"
    return {"verdict": verdict, "blockers": blockers,
            "flags": flags, "jd_chars": len(jd)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: screen_job.py <job-url>")
    jd = fetch_jd(sys.argv[1])
    r = screen(jd, sys.argv[2] if len(sys.argv) > 2 else "")
    print(f"{r['verdict']}  ({r['jd_chars']} chars of JD)")
    for b in r["blockers"]:
        print(f"  BLOCKER  {b}")
    for f in r["flags"]:
        print(f"  flag     {f}")
