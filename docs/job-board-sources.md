# Dice and Indeed in the daily run

Added 2026-09-13.

## Registered locally, not used through the claude.ai connectors

```bash
claude mcp add --transport http dice   https://mcp.dice.com/mcp
claude mcp add --transport http indeed https://mcp.indeed.com/claude/mcp
```

The claude.ai connectors for both already work, but their tool names carry a
server-side UUID (`mcp__bfcf4953-...__search_jobs`) that is resolved per session
and stored nowhere on disk. Allowlisting a UUID would break silently the day it
rotates, and this repo has already lost 19 consecutive runs to one silent Stage 2
failure. `claude mcp add` pins the name, so `mcp__dice__*` and `mcp__indeed__*`
are stable.

| Server | Status |
|---|---|
| `dice` | Connected, no authentication required |
| `indeed` | **Needs OAuth once.** Run `/mcp` in an interactive `claude` session and authorize it. Until then the stage skips it silently. |

`indeed`'s `get_resume` is deliberately not allowlisted. The run has no reason to
read his stored Indeed resume.

## The measurement that changed the design

First live Dice query, 2026-09-13: Data Engineer, full-time, posted in the last
7 days. The `willingToSponsor` facet came back:

```
  willingToSponsor  false  308
  willingToSponsor  true     4
```

**1.3%.** And all four were unusable on inspection:

1. Data & AI Delivery Lead, Washington DC, "Local Candidates Only", senior.
2. Data Engineer with Databricks, Remote, `$50+` hourly, employmentType
   "Full-time, Third Party", an IT staffing firm.
3. Azure Data Engineer, Barrington IL, "Experience: 5 Years", staffing firm.
4. Technical Program Manager, NYC, "Long-term engagement", wrong role.

The sponsor-willing segment of Dice is mostly body shops.

## Why the obvious filter is the wrong primary filter

`willing_to_sponsor: true` looks like the perfect answer to the blocker that
killed Emerson. It is not, because **he does not need sponsorship.** OPT plus
STEM OPT gives him 36 months from June 2027 requiring no petition from any
employer. A posting that does not advertise sponsorship is not closed to him.
Only an explicit no-sponsorship line is, and `screen_job.py` already catches
those.

Filtering on `willing_to_sponsor` alone would have discarded 308 of 312
postings, almost all of which he can take.

So the prompt runs **two passes per role family**: one with the filter as a
lead generator, one without it as the actual search.

## Role families, in priority order

Data Analyst, Data Engineer, Data Scientist, Business Intelligence Analyst,
Analytics Engineer, then Software Engineer. His data fit scores run roughly
twenty points above his software scores and almost every application still goes
to software.

Locations are unrestricted: he confirmed 2026-09-12 that he relocates anywhere.
What disqualifies a posting is the timing of required presence, never the city.

## Results are leads, not rows

Nothing goes straight from a board into `pipeline.db`. Each hit is run through
`screen_job.py`, dropped if NOT_FULL_TIME or carrying a citizenship, clearance
or no-sponsorship blocker, deduped by company and title, and recorded with its
board and job id. Prefer the employer's own ATS URL over the board URL when the
row is created.

Also drop anything whose `employmentType` or `employerType` contains
"Third Party".

---

# Published desk staleness check

Added 2026-09-13, after both Mulligan rows showed as open on the published
Artifact while `data/desk.html` had been correct for days and the published page
was stamped 9 SEP. The same class of staleness bit once before, on 2 September.

The daily run rebuilds the desk but **cannot publish it**: Stage 2 has no
Artifact tool. So the published page only moves when an interactive session
republishes, and it drifts silently in between.

`scripts/desk_publish_state.py` makes the drift loud:

```bash
python scripts/desk_publish_state.py check   # exit 0 fresh, 1 stale, 2 never marked
python scripts/desk_publish_state.py mark    # record the current content as published
```

Stage 1 runs `check` straight after `build_desk.py`. On a non-zero exit it puts a
banner at the top of `data/logs/QUEUE.md` and fires a macOS notification, the
same mechanism already used for Stage 2 failures.

**It hashes the counters and the `<tbody>` blocks, not the whole file.**
`build_desk.py` rewrites the date stamp every run, so a whole-file hash would
differ daily even when nothing moved, and a warning that fires every day is a
warning nobody reads. Verified: a date-only change does not trigger it, a single
counter change does.

**The one manual step.** After republishing the Artifact, run
`python scripts/desk_publish_state.py mark`. Nothing else clears the banner,
which is deliberate: the marker should only ever be set by someone who actually
published.

---

# MCP scope gotcha, found 2026-09-13 by running the daily run

The first real run reported: *"The dice, indeed and linkedin servers registered
locally were not offered to this session."* It was right.

`claude mcp add` defaults to **local scope, keyed to the current working
directory**. The servers were registered from `~/Documents/my-projects`, but
`daily_run.sh` does `cd "$REPO"` into `~/Developer/career-agent`, which is a
different project, so Stage 2 was never offered them and its one Dice call was
denied by the allowlist.

Fixed by re-registering all three at user scope and removing the project-scoped
duplicates:

```bash
claude mcp add --scope user --transport http dice   https://mcp.dice.com/mcp
claude mcp add --scope user --transport http indeed https://mcp.indeed.com/claude/mcp
claude mcp add --scope user linkedin -- uvx mcp-server-linkedin@latest
```

**Verify from the repo directory, not from wherever you happen to be:**

```bash
cd ~/Developer/career-agent && claude mcp list
```

If a server is missing there, Stage 2 will not see it no matter what
`claude mcp list` says elsewhere.
