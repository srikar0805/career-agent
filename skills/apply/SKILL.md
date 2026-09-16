---
name: apply
description: End to end application for one role. Analyzes the posting, tailors the resume and cover letter through the review loop, answers the standard screening questions, pre-fills the application, and logs everything to the pipeline. Stops before submission so the user reviews and submits. Use when the user wants to apply to a specific job.
trigger: /apply
---

# /apply

Everything for one application, in one pass, stopping short of the submit button.

```
/apply 14                                    # pipeline id
/apply https://boards.greenhouse.io/...
/apply --company Stripe --role "ML Engineer"
```

## What this does not do

It does not submit anything. Every application ends with materials ready and a filled-in answer sheet, and the user does the submitting.

That is a deliberate design choice, not a limitation. Automated submission is brittle, breaks silently when a form changes, and produces applications the candidate has not read. The expensive part of applying was never the form; it was the tailoring, and that is what this automates.

## Step 1: Get the posting

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
```

From a pipeline id, read the stored posting:

```bash
python scripts/pipeline.py show <id> --json
```

From a URL, fetch it and create the pipeline entry:

```bash
python scripts/pipeline.py add --company "<c>" --role "<r>" --url "<u>" \
  --source <board> --status shortlisted --jd "<full text>"
```

## Step 2: Analyze, in parallel

Dispatch at once:

- `jd-analyst` on the posting
- `company-researcher` on the company

Also check the two things that decide whether to continue at all:

```bash
python scripts/pipeline.py who <company>       # warm path?
python scripts/pipeline.py list --company <company>   # prior history?
```

Then read the FORM, before a single resume line is written:

```bash
python scripts/prefill.py --app <id> --no-log
```

It reads the real application form where the ATS exposes one (Greenhouse, via
`?questions=true`), answers every question it can from `profile/answers.yaml`,
and heads the packet with the `form_check` verdict and a WARNING line for any
question whose honest answer probably filters him out. Measured on 2026-09-16
across 25 open Greenhouse rows: ID.me asks "Are you graduating Summer of 2027",
Celonis "completing your degree in June 2027 or later", and both honest answers
are No. Emerson, Equifax, DigitalOcean and BCG all died at the form, not the
page, so this runs first.

**Stop and check with the user before continuing if any of these is true:**

- `jd-analyst` flags a hard disqualifier, especially work authorization. Applying anyway wastes an hour and produces a rejection that teaches nothing.
- The packet says `Form check: BLOCKER`, or carries a WARNING line.
- A warm connection exists. A referral through that person is worth far more than a cold application, and applying cold first can actually burn the referral, because the recruiter now has the application in hand.

## Step 3: Build the materials

Run `/resume-rewrite` for this posting, including its full review loop. Do not shortcut it.

Then run `/coverletter`, but only if the application asks for one or the posting suggests it will be read. A cover letter nobody opens is an hour spent for nothing, and many engineering applications never surface it.

Both land in `data/artifacts/<company>-<role>/`.

## Step 4: The packet

The deterministic answers are not written by hand any more. Rebuild the packet
now that the resume exists, so its Files section points at the real PDF:

```bash
python scripts/prefill.py --app <id>        # writes data/artifacts/<slug>/packet-<id>.md and logs it
```

Every answer carries one status. Treat them differently:

| Status | Meaning | What you do |
|---|---|---|
| FILLED | from `profile/answers.yaml` or `pipeline.db`, dropdown option already matched | nothing |
| CONFIRM | near-certain, never confirmed by him | list it under Before you submit |
| DECISION | consents, attestations, pronouns, EEO, location and team preferences | never choose; list it |
| NEEDS YOU | unknown (address, transcript, non-compete, government-official status) | ask; never guess |
| OPEN | free text for this role | write it, Step 5 |

**Do not overwrite a FILLED answer to make the application look better.**
Work authorization in particular is answered the same way on every form:
authorized Yes, sponsorship now or in the future Yes, with the 36-month OPT and
STEM OPT explanation wherever a text box allows it. The sponsorship question has
closed more of his applications than anything else, and answering it falsely is
a false statement on an employment application.

When a packet has a NEEDS YOU that the answer bank should have covered, the fix
is a new rule in `scripts/prefill.py` or a value in `profile/answers.yaml`, not
a one-off answer typed into this packet. The next form will ask it again.

For ATSs whose form is not publicly readable (Lever, Ashby, Workday, Oracle,
iCIMS, bespoke portals) the packet holds the standard answers instead, and the
user matches them to the form on the page.

## Step 5: The open-ended answers

Only the OPEN rows are written, and only here. Draft each from `profile/voice.md`,
the `company-researcher` finding and the evidence ids listed under `open_ended`
in `profile/answers.yaml`:

- Why this company: one specific, checkable reason. No flattery.
- Why this role, tell me about yourself, proudest project: the evidence ids per role family in `answers.yaml`.
- Technical prompts ("Imagine you are building a computer vision system..."): answer from what he has actually built; `EV-044` to `EV-047` for vision.
- Never use TigerVerse (`EV-041`) until authorship is confirmed.
- No em dashes. Short. These boxes are screened, not read closely.

Append them to the packet under a `## Written answers` heading, each under the
exact question label, so the packet stays the single sheet he works from.

If the user wants, you can open the application page in the browser so they can work through it with the packet beside them. **Fill fields only if they explicitly ask, never submit, never tick a consent or attestation box, and never enter anything into a field the user has not seen.**

## Step 6: Log

```bash
python scripts/pipeline.py artifact <id> --kind resume --path <...> --score <n> --verdict <v> --evidence "EV-..."
python scripts/pipeline.py artifact <id> --kind cover_letter --path <...>
python scripts/pipeline.py move <id> applied          # only after the user confirms they submitted
python scripts/pipeline.py task <id> --kind follow_up \
  --description "follow up if no response" --due <date + 10 days>
```

**Move to `applied` only after the user says they actually submitted.** A pipeline that thinks an application was sent when it was not is worse than no pipeline, because the follow-up will reference something that never happened.

## Step 7: Report

- Both documents, shown in full
- ATS coverage, judge score, screener verdict
- Evidence ids used, so the user knows their interview surface
- The packet path, its status counts, and every WARNING, NEEDS YOU and DECISION line verbatim
- The warm path, if one exists, and whether to use it before submitting
- What was flagged as a risk
- The follow-up date

## Rules

- Never submit. Never click a final action. Never enter credentials.
- Never apply past a hard disqualifier without saying so plainly first.
- Never state work authorization inaccurately, in any field, for any reason.
- Never pre-select a consent, privacy acknowledgement, attestation or EEO answer. `prefill.py` marks them DECISION and they stay his.
- Check for the warm path before applying cold, every time.
- If the resume loop could not clear the bar, say so before the user submits, and say what is blocking. Submitting a failing resume is a choice the user gets to make with the information in hand.
