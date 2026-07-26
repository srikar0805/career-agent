---
name: job-hunt
description: Find open roles from public job board APIs, rank them by genuine fit against the evidence bank, check for warm intro paths, and load the shortlist into the pipeline. Use when the user wants to find jobs, search for roles, or see what is open.
trigger: /job-hunt
---

# /job-hunt

Find real open roles, ranked by whether the user can actually win them.

```
/job-hunt "machine learning engineer"
/job-hunt "data scientist" --location remote
/job-hunt --companies stripe,anthropic,figma
/job-hunt --watchlist                    # only companies in profile/companies.yaml
```

## Step 1: Search

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate

python scripts/discover.py --query "<terms>" --location "<location>" \
  --limit 60 --out data/raw/discovered.json
```

This hits public Greenhouse, Lever, and Ashby board APIs plus RemoteOK, deduplicates, and drops roles that conflict with `profile/identity.yaml`, including postings that state citizenship or no-sponsorship when sponsorship is needed.

It reports how many boards responded. If that number is low, the network or the watchlist is the problem, not the market.

If results are thin, widen deliberately and say what you widened: adjacent titles, adjacent seniority, adjacent locations. Never silently return a different search than the one requested.

To search companies not in the default watchlist, use `--companies`. Board tokens are the company's slug on their ATS, visible in their careers page URL.

## Step 2: Rank by real fit

`discover.py` ranks by keyword and freshness, which is a starting point, not an answer. Now do the part that matters.

Read `profile/evidence.yaml` and `profile/skills.yaml`. Dispatch `jd-analyst` **in parallel** across the top 12 to 15 postings.

For each, work out:

- **Coverage.** Which of the ranked must-haves does the evidence bank actually prove? Not "could plausibly claim", prove.
- **Hard blockers.** Work authorization, location, years of experience where a recruiter is filtering on it, required credentials.
- **The stretch gap.** How far above the user's demonstrated level is this? One level up is worth applying to. Three is not.
- **The one thing.** What would this application have to lead with?

Then sort into four buckets and be honest about the boundaries:

- **Strong.** Evidence covers every must-have. Apply with a tailored resume.
- **Stretch.** Covers most, missing one. Worth applying if there is a warm path or a genuine hook. These are where good outcomes actually come from, so do not dismiss them.
- **Weak.** Missing multiple must-haves. Applying costs an hour and returns nothing. Say so.
- **Blocked.** A hard filter the user fails. Do not apply, and say which filter.

## Step 3: Check the warm paths

For every company in Strong and Stretch:

```bash
python scripts/pipeline.py who <company>
```

If the LinkedIn export was imported, `data/raw/linkedin.json` has `connections_by_company` so the whole shortlist can be checked at once.

**Mark every company where a connection exists.** A referral is worth more than any amount of resume tailoring, and the shortlist should be ordered with that in mind rather than by raw fit score.

Also check whether the user already has history here:

```bash
python scripts/pipeline.py list --company <company>
```

Do not surface a role at a company that recently rejected them for the same position without flagging it.

## Step 4: Load the pipeline

```bash
python scripts/pipeline.py add --company "<c>" --role "<r>" --url "<u>" \
  --source <board> --location "<l>" --status <discovered|shortlisted> \
  --sponsors <0|1> --jd "<full posting text>"
```

Store the full posting text. It means `/resume-rewrite`, `/coverletter`, and `/interview-prep` can all work from the real requirements later, even after the posting comes down, which they routinely do.

Strong roles go in as `shortlisted`. Everything else as `discovered`.

## Step 5: Report

```
SEARCH: "<query>" <location>
<n> boards responded, <n> postings, <n> after filters

STRONG  <n>
  #<id>  <company>  <role>
         covers: <must-haves the evidence proves>
         warm:   <person, or "no path">
         lead with: <the one thing>
         <url>

STRETCH  <n>
  ...   missing: <the gap> | worth it because: <reason>

WEAK  <n>       <one line each, with the missing must-have>
BLOCKED  <n>    <one line each, with the specific filter>

FILTERED OUT
  <what discover.py dropped and why, especially sponsorship filters>

PATTERN
  <What the shortlist says about the market for this profile. If most postings
  want a skill the evidence bank does not cover, that is the most important
  finding here and it should change what the user works on, not just where
  they apply.>
```

Close with a recommendation: the two or three roles to apply to first, in order, with the reason. Then offer `/apply <id>`.

## Rules

- **Never inflate fit.** A Weak role labeled Strong costs the user an hour and a rejection. The bucket boundaries exist to be enforced.
- **Warm paths reorder the list.** A Stretch role where the user knows someone outranks a Strong role where they do not.
- **Respect the identity filters.** A role that will not sponsor when sponsorship is needed is Blocked, not Stretch.
- Report the pattern across the shortlist, not just the individual roles. That is the part the user cannot see for themselves.
- Store the full posting text. Postings disappear and the pipeline should not lose them.
