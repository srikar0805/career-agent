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

**Stop and check with the user before continuing if either of these is true:**

- `jd-analyst` flags a hard disqualifier, especially work authorization. Applying anyway wastes an hour and produces a rejection that teaches nothing.
- A warm connection exists. A referral through that person is worth far more than a cold application, and applying cold first can actually burn the referral, because the recruiter now has the application in hand.

## Step 3: Build the materials

Run `/resume-rewrite` for this posting, including its full review loop. Do not shortcut it.

Then run `/coverletter`, but only if the application asks for one or the posting suggests it will be read. A cover letter nobody opens is an hour spent for nothing, and many engineering applications never surface it.

Both land in `data/artifacts/<company>-<role>/`.

## Step 4: The screening questions

Most of the real time cost of applying is here, in the free-text boxes. Prepare answers for the standard set so the user is pasting rather than composing:

- Why this company? Use the `company-researcher` finding. Two or three sentences, specific, no flattery.
- Why this role? Connect to the evidence bank and to a real trajectory.
- Work authorization status. The exact, honest wording from `profile/identity.yaml`. Never soften or obscure this.
- Salary expectation. Use `comp_floor` from identity. If the field allows text, a range with a note that it is negotiable beats a single number.
- Notice period and start date.
- Location and relocation willingness.
- Any posting-specific question, which `jd-analyst` will have flagged.
- Links: GitHub, LinkedIn, portfolio.

Keep answers short. These boxes are screened, not read closely, and the same honesty rules apply as everywhere else.

Save to `data/artifacts/<slug>/application-answers.md`.

## Step 5: The pre-filled sheet

Produce a single copy-paste sheet, ordered the way the form asks:

```
=== <Company> / <Role> ===
URL: <application url>

BASICS
  Name             <value>
  Email            <value>
  Phone            <value>
  Location         <value>
  LinkedIn         <value>
  GitHub           <value>

FILES
  Resume           data/artifacts/<slug>/resume.docx
  Cover letter     data/artifacts/<slug>/cover-letter.docx

QUESTIONS
  Q: Why <company>?
  A: <answer, ready to paste>

  Q: Work authorization
  A: <exact honest answer>

  ...

BEFORE YOU SUBMIT
  - <anything requiring a judgment call the user must make>
  - <any question this skill could not answer>
```

If the user wants, you can open the application page in the browser so they can work through it with the sheet beside them. **Fill fields only if they explicitly ask, never submit, and never enter anything into a field the user has not seen.**

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
- The answer sheet
- The warm path, if one exists, and whether to use it before submitting
- What was flagged as a risk
- The follow-up date

## Rules

- Never submit. Never click a final action. Never enter credentials.
- Never apply past a hard disqualifier without saying so plainly first.
- Never state work authorization inaccurately, in any field, for any reason.
- Check for the warm path before applying cold, every time.
- If the resume loop could not clear the bar, say so before the user submits, and say what is blocking. Submitting a failing resume is a choice the user gets to make with the information in hand.
