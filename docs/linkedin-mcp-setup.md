# LinkedIn people discovery in the daily run

Set up 2026-09-13 at Srikar's explicit direction, after being told the risk.

## What is actually doing the work

**Agent Reach (`Panniantong/Agent-Reach`) is not in the pipeline.** Its CLI has
no read or search command: the subcommands are `setup`, `install`, `configure`,
`doctor`, `uninstall`, `skill`, `format`, `transcribe`. It is an installer,
configurator and health checker that routes you to upstream tools. Its
`agent_reach/channels/linkedin.py` is a seventy-line check that tells you to go
install something else.

**The tool that does the work is `stickerdaniel/linkedin-mcp-server`**, Apache
2.0, 3.4k stars, actively maintained. It drives Srikar's own logged-in LinkedIn
session in a browser and exposes the profile, company, people and job tools.

## The risk, recorded once so it is not re-argued

Automated LinkedIn access can get an account restricted. Srikar's Premium
account currently holds his InMail credits, four pending connection requests and
the only outreach channel the search runs on, against zero referrals in 43
applications. He was given the read-only alternative and chose this. That is his
call. The caps below are how the risk is managed rather than ignored.

## Install, three commands, run by Srikar

The agent cannot run the first one: installing a package from a remote archive
is blocked by the Claude Code auto-mode classifier, correctly.

```bash
python3 -m venv ~/.agent-reach-venv && ~/.agent-reach-venv/bin/pip install "https://github.com/Panniantong/agent-reach/archive/main.zip"
```

```bash
uv tool install mcporter && ~/.agent-reach-venv/bin/agent-reach doctor
```

Then the login. **Only Srikar runs this.** It opens a LinkedIn sign-in and
stores a session; the agent never sees or types the password.

```bash
uvx mcp-server-linkedin@latest --login
```

Finally register it with Claude Code so Stage 2 is offered the tools:

```bash
claude mcp add linkedin -- uvx mcp-server-linkedin@latest
```

Verify with `claude mcp list`. The server must appear as `linkedin`, because the
allowlist entries in `daily_run.sh` are `mcp__linkedin__*`.

## Where the session actually lives

Confirmed 2026-09-13 after the login ran:

```
~/.linkedin-mcp/profile/          24 MB browser profile
~/.linkedin-mcp/cookies.json      exported session cookies
~/.linkedin-mcp/source-state.json
```

Earlier verification in this repo guessed `~/.linkedin-mcp-server` and
`~/.linkedin_mcp_cookie`. Both are wrong. Use the paths above.

`invalid-state-*` directories are superseded earlier login attempts and are safe
to delete.

**`cookies.json` is a live LinkedIn session credential in plaintext.** It is mode
600, owner only, which is correct. Never commit it, never put it in a synced or
backed-up folder, and treat a machine with this file as a machine that is logged
into LinkedIn. To revoke, sign out of all sessions from LinkedIn settings and
delete `~/.linkedin-mcp/`.

## MCP servers connect at session start

A server added with `claude mcp add` is NOT available to the Claude Code session
that added it. Its tools appear only in sessions started afterwards. If
`search_people` is missing, restart the session before assuming the setup is
broken.

## What is allowlisted, and what never will be

Eight read tools are on the Stage 2 allowlist in `scripts/daily_run.sh`:

```
search_people          get_company_employees   get_person_profile
search_companies       get_company_profile     search_jobs
get_job_details        close_session
```

Two are deliberately absent and must stay absent:

```
connect_with_person    send_message
```

They would violate the HARD CONSTRAINTS block in `daily_prompt.txt`. **The
allowlist is the enforcement of that rule, not a reminder of it.** A model that
decided to send anyway is stopped by the harness. If either name ever appears on
an allowlist line, that is a bug, not a feature request.

## The caps

Per run: **three companies, two searches each, four profiles opened, one
session.** Written into `daily_prompt.txt`. Volume is what flags accounts. Three
good contacts a week beats a fast crawl that loses the account.

## Who the run is told to look for

A campus recruiter is a gatekeeper and cannot refer him. A referral comes from an
engineer or engineering manager with internal portal access. Priority order:

1. Someone listing **University of Missouri at a Missouri employer**. That
   pipeline has never been used once and it is the only place his school helps.
2. An engineer holding the **exact title on the req**.
3. Anyone **2nd degree with a named mutual**, because a warm intro costs no
   InMail credit.

Connection count and last activity get recorded, because a dormant profile with
86 connections will not answer a cold message however well it matches. That was
the Christian VanMeter finding on 2026-09-11.

## Turning it off

Remove the eight `mcp__linkedin__*` lines from `daily_run.sh`, or
`claude mcp remove linkedin`. The stage no-ops harmlessly when the tools are not
offered, so removing the server is enough and no prompt edit is needed.

---

# LinkedIn job search, added 2026-09-14

`search_jobs` and `get_job_details` were already on the Stage 2 allowlist from
the 13 Sep setup. What was missing was the instruction to use them, and a budget.

## The budget was split, not grown

The people half was reduced to pay for the jobs half. Total browser operations
per run are unchanged at about ten:

| | Before | Now |
|---|---|---|
| Job searches | 0 | **2**, `max_pages=1` |
| Job detail fetches | 0 | **3** max |
| Companies for people work | 3 | **2** |
| Searches per company | 2 | **1** |
| Profiles opened | 4 | **2** |
| Sessions | 1 | 1 |

## `max_pages` is the parameter that matters

It defaults to **3**, and every page is a real browser page load. Seven role
families at the default would be twenty-one loads in a single run. Volume is what
gets accounts restricted, and this account already produced two "verify your new
device" emails on setup alone, before a single search ran. **Always pass
`max_pages=1`.**

## Fixed arguments, every call

```
job_type         = "full_time"            full-time only, standing rule since 4 Sep
experience_level = "entry,associate"
date_posted      = "past_week"            matches the run cadence
sort_by          = "date"
max_pages        = 1
```

## Keywords rotate by weekday

One family per day rather than all seven at once: Data Analyst, Data Engineer,
Data Scientist, Business Intelligence Analyst, Machine Learning Engineer,
Analytics Engineer, Software Engineer. Each day's keyword runs twice, once
`work_type="remote"` and once `location="United States"`. Every family is covered
across a week with no daily burst.

Data families come first in the week because his data fit scores run roughly
twenty points above his software scores.

## A LinkedIn result is a lead, never a row

LinkedIn is an aggregator. Its listing is a copy, often stale, often missing the
real application form. Each surviving result goes through `screen_job.py`, then
`form_check.py`, then **the employer's own ATS posting is found and used as the
row's URL**. The LinkedIn job id goes in the notes for traceability.

**"Easy Apply" is the weakest kind of lead, not the most convenient one.** It
hides the employer's real screening questions entirely, which is exactly what
killed Emerson, Equifax and DigitalOcean.

## Live capability test, 2026-09-14

One `search_jobs` call, `keywords="Data Analyst"`, US, full_time,
entry+associate, past_week, date-sorted, `max_pages=1`. It worked: LinkedIn
accepted every filter, returned **10 job_ids**, and `close_session` succeeded.

Two findings that changed the prompt:

**The experience filter is a hint, not a constraint.** "Senior Business
Intelligence Analyst" and "Senior HR Systems Analyst" both came back under
`entry,associate`. The prompt now drops by title after the search: senior, staff,
principal, lead, manager, director, architect, II, III, Sr.

**The source is thin and noisy.** Ten results from one page against a header
claiming a thousand-plus matches, and only one of the first five was plausibly
relevant. LinkedIn job search is a supplement to the ATS sweeps, not a
replacement. A run that produces nothing usable is a normal result.

**Deprecation watch.** The results page carried a LinkedIn banner saying classic
job search is being retired starting September 2026. This tool drives the classic
URL, so `search_jobs` may degrade without warning. The prompt says to report it
once and skip, not to work around it.
