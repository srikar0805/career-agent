---
name: pipeline
description: Show the job search pipeline. Status board, conversion by stage, stale applications, follow-ups due, and contact graph. Use when the user wants to see their applications, check status, review progress, or find what needs attention.
trigger: /pipeline
---

# /pipeline

The state of the search, with the parts that need attention pulled to the front.

```
/pipeline                        # board plus what needs attention
/pipeline stats                  # conversion funnel
/pipeline due                    # follow-ups due
/pipeline stale                  # gone quiet
/pipeline show 14                # one application in full
/pipeline who Stripe             # contacts at a company
/pipeline add                    # log something applied to outside this tool
```

## Step 1: Pull

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate

python scripts/pipeline.py stats
python scripts/pipeline.py due --days 3
python scripts/pipeline.py stale --days 10
python scripts/pipeline.py list --open
```

## Step 2: Present it usefully

A raw table is not the deliverable. Order by what needs action.

```
NEEDS ATTENTION
  overdue   <n>  <the specific follow-ups, with how late>
  today     <n>
  stale     <n>  <applications quiet 10+ days>

ACTIVE
  interviewing  <n>   <company / role / days since last contact>
  screening     <n>
  applied       <n>
  shortlisted   <n>   <not yet applied, which is where things silently die>

FUNNEL
  applied      <n>
  screening    <n>  <rate>
  interviewing <n>  <rate>
  offer        <n>  <rate>

CLOSED
  rejected <n>   withdrawn <n>   ghosted <n>
```

Then say what the numbers mean. The funnel is the diagnostic and most users will not read it correctly on their own.

- Low applied-to-screening: the resume or the targeting. Roughly under 10% is a signal.
- Screens but no technical rounds: the story is not landing.
- Technical rounds but no offers: depth under follow-up.
- A large `shortlisted` count: roles are being found and not applied to, which is the most common silent failure in a job search.
- Lots of `ghosted`: follow-ups are not happening, and this is entirely fixable.

Only draw conclusions the sample supports. Under about ten applications, say the sample is too small rather than reading noise.

## Step 3: One action

End with a single next thing, same rule as `/career`. Time-critical first, then overdue, then highest leverage.

## Adding history

If the user applied to things before setting this up, backfill:

```bash
python scripts/pipeline.py add --company "<c>" --role "<r>" --status applied
python scripts/pipeline.py move <id> <status>
```

If a LinkedIn export was imported, `data/raw/linkedin.json` may contain a `job_applications` table. Offer to backfill from it, which reconstructs months of history in one pass.

## Rules

- Never invent a number. If the pipeline is empty, it is empty, and the answer is `/job-hunt`.
- Never present the board without the diagnosis. A table the user has to interpret alone is the thing they already had.
- Flag stale applications every time. Silence is where searches die.
- Do not over-read small samples.
