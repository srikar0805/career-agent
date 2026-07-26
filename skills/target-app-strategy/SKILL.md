---
name: target-app-strategy
description: Build a 7-day job search plan naming real open roles pulled live from job boards, with search terms, warm-intro paths from the LinkedIn connection graph, and a daily action checklist written into the pipeline as tasks. Use when the user wants a job search strategy, outreach plan, or does not know where to start.
trigger: /target-app-strategy
---

# /target-app-strategy

A 7-day plan naming real open roles and real people, not generic advice.

```
/target-app-strategy "ML Engineer" "AI infrastructure" remote
/target-app-strategy "Data Scientist" fintech "New York"
/target-app-strategy --size seed          # seed | series-a-c | growth | enterprise
/target-app-strategy --replan             # rebuild from current pipeline state
```

## The premise

Most job search advice fails because it is abstract. "Network more" and "tailor your resume" are true and useless. What a person needs on Monday morning is a list of things to do that takes under two hours and names specific companies, specific roles, and specific people.

This plan is built from live board data and the user's actual connection graph. Every day's tasks land in the pipeline database, so the plan is a thing that can be executed and tracked rather than a document that gets read once.

## Bootstrap

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
python scripts/pipeline.py stats
```

Read `profile/identity.yaml` for constraints. **Work authorization, location, and timeline drive everything.** A plan that ignores a sponsorship requirement wastes a week of real effort.

## Step 1: Pull real roles

```bash
python scripts/discover.py --query "<role>" --location "<location>" --limit 60
```

This hits public Greenhouse, Lever, and Ashby board APIs plus RemoteOK, deduplicates, and filters by the constraints in `identity.yaml`.

If it returns thin results, widen: adjacent titles, adjacent locations, adjacent seniority. Report what you widened and why rather than silently returning a different search.

Then dispatch `jd-analyst` across the top candidates in parallel to rank them by genuine fit rather than title match.

## Step 2: Find the warm paths

This step is what separates a real plan from a list of links.

```bash
python scripts/pipeline.py who <company>
```

Run it for every shortlisted company. If a LinkedIn export was imported, `data/raw/linkedin.json` holds `connections_by_company`, so you can check the whole shortlist at once.

Sort the shortlist into three tiers:

- **Tier 1, warm.** A first-degree connection works there. Referral path. Roughly ten times the response rate of a cold application, and it is not close.
- **Tier 2, semi-warm.** A connection at a similar company who could introduce, or a shared school, or a shared open source project.
- **Tier 3, cold.** No path. Application plus cold outreach to the hiring manager.

**Tier 1 companies get the week's attention.** A plan that spends five days on cold applications while three warm paths sit untouched is a bad plan, and this is the single most common mistake in a self-directed job search.

## Step 3: Build the week

Structure the seven days so that the highest-leverage work happens while energy is highest, and so that nothing is blocked waiting on a reply.

**Day 1, setup and the warm list.** Resume baseline for the target role. Identify every Tier 1 path. Draft the intro requests. This day produces the most value in the whole week.

**Day 2, warm outreach and the top applications.** Send the intro requests. Apply to the two or three best-fit roles with fully tailored materials.

**Day 3, the middle of the shortlist.** Applications with tailored resumes. Quality over volume: four well-targeted applications beat twenty generic ones and take about the same time once the evidence bank exists.

**Day 4, cold outreach.** Hiring managers at Tier 3 companies where the role fit is strong. Research first, three to five messages, not twenty.

**Day 5, breadth and follow-ups.** More applications. First follow-ups on anything from Day 1 and 2 that has gone quiet.

**Day 6, positioning.** LinkedIn profile work, portfolio, or whatever gap the week exposed. Lower energy day, non-urgent work.

**Day 7, review and replan.** What got responses, what did not, what to change. Run `pipeline.py stats` and look at the actual conversion.

Adjust this shape to the user's real constraints. Someone employed full time gets a different week than someone searching full time, and you should ask which it is if `identity.yaml` does not say.

## Step 4: Write it into the pipeline

Every role goes in:

```bash
python scripts/pipeline.py add --company "<c>" --role "<r>" --url "<u>" \
  --source <board> --status shortlisted --sponsors <0|1>
```

Every action becomes a dated task:

```bash
python scripts/pipeline.py task <app-id> --kind <apply|outreach|follow_up|research> \
  --description "<specific action>" --due <date>
```

Then the user can run `/pipeline` or `pipeline.py due` any morning and see exactly what today holds. The plan survives contact with a busy week because it is data, not prose.

## Step 5: Search terms and boards

Give the actual strings, not the advice to search.

- **Board searches**, written out, per board, with the filters set
- **LinkedIn boolean strings** for finding roles, and separately for finding the hiring manager at a target company
- **The company watchlist**: for companies with no current opening but strong fit, the direct URL to their board so the user can check weekly
- **Where this role is actually posted.** Some roles live on niche boards rather than the big ones, and naming the right board saves more time than any search string.

## Step 6: Deliver

```
TARGET: <role> in <industry>, <location>
CONSTRAINTS: <work auth, timeline, comp floor from identity.yaml>

THE SHORTLIST
  tier 1, warm       <n> companies
  tier 2, semi-warm  <n>
  tier 3, cold       <n>
  <table: company, role, fit, path, who, link>

THE WEEK
  Day 1 <date>  <2 to 4 concrete actions, each with the company named>
  ...

SEARCH TERMS
  <written out per board>

WHAT I WIDENED AND WHY
  <if the initial search was thin>

WHAT WOULD CHANGE THIS PLAN
  <the assumption most likely to be wrong, and what to do if it is>
```

Then confirm the tasks are in the pipeline and tell the user the one command that shows today's work.

## Rules

- **Name real companies and real roles with real links.** A plan containing "apply to 5 startups" has failed.
- **Warm paths before cold volume,** always. If the user has ten first-degree connections at target companies, the week is about those ten.
- **Honor the constraints in `identity.yaml`.** A role that will not sponsor when sponsorship is needed does not go on the list, and you say why rather than quietly dropping it.
- Four tailored applications beat twenty generic ones. The evidence bank makes tailoring cheap, so there is no excuse for volume spraying.
- Never promise response rates. Report what the user's own pipeline stats show once there is data.
- If the search returns almost nothing, that is the finding. Say it, and discuss whether the target needs to change.
