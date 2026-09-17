---
name: fit-analysis
description: Brutally honest evidence-based assessment of how well a resume matches a specific job description, scored across ATS match, technical match, experience match and hiring competitiveness, with stage-by-stage interview probability and an apply-or-not verdict. Use whenever the user asks for a fit analysis, fit score, match score, or whether a job is worth applying to.
trigger: /fit-analysis
---

# /fit-analysis

```
/fit-analysis <job-url>
/fit-analysis --jd path/to/posting.txt --resume path/to/resume.pdf
/fit-analysis --app 14
/fit-analysis                      # uses the most recent pipeline entry and its matching resume
```

## Bootstrap

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
```

## Run it on Kimi K3 first

Since 2026-09-16, at Srikar's direction, the analysis itself runs on NVIDIA's Kimi
K3, not in this Claude session. This file is still the specification: the agent
sends everything from "The analysis" down as its instructions.

```bash
python scripts/agent_fit.py --app <id> [--resume <pdf>]
```

It writes `data/artifacts/<slug>/fit_analysis.md` plus `fit_analysis.json`, logs the
artifact with the paper score, and puts an **Automated checks** line at the top:
missing sections, weighted arithmetic that does not reproduce the paper score, stage
probabilities that rise, a forbidden recommendation, and any quoted strength line
that is on neither the resume nor the posting.

Kimi goes first, and when its analysis fails a check or errors, Nemotron Ultra
writes it again (NVIDIA, then Ollama). His words, 2026-09-16: "first try with Kimi
if it fails then fallback to ultra". The header names the model that wrote the
analysis and lists every attempt. `--applied` and `--ready` run the batch for the
jobs he applied to and the prepared ones; the Application Desk shows every
analysis beside its row, because he asked to "look at each fit analysis for each
job I apply".

Read the file and relay it. Do the analysis inline below only when the agent fails
(no NVIDIA key, every model down, no pipeline row for a pasted posting), and say
that it ran inline. When the checks line lists a problem, fix that section before
relaying it rather than passing a failed check on to Srikar.

Resolve two inputs before anything else.

**The posting.** From a URL, fetch it. From `--app <id>`, read the stored `jd_text` with `pipeline.py show <id> --json`. If the user pasted it, use that. Never analyze against a role title alone; say so and stop.

**The resume.** If not given, pick the best-matching variant from
`~/Developer/Resumes/final/` and say which you chose and why. Read it with
`python scripts/ingest.py <path>`. (Corrected 2026-09-07: this said
`~/Desktop/Resumes./final/`, a path that has never existed, with a stray period.
Same class of defect as the fifteen skill symlinks that pointed at the wrong
repo root. If a path in a skill is wrong, fix the skill, do not work around it.)

Run the mechanical check first, since its output feeds the ATS section:

```bash
python scripts/ats_check.py --resume <resume> --jd <posting> --company <employer> --json
```

**Strip the application form before you measure anything.** A fetched posting
carries the Greenhouse, Workday or iCIMS form with it, and those words are scored
as if they were requirements. On 2026-09-07 this dragged Anthropic from 27.7% to
a reported 16.7% on the strength of `select`, `dropbox`, `enter`, `phone` and
`privacy policy`, and Point72 read 30.5% raw against 74.4% clean. Cut the text at
the first form marker and measure the requirements only:

```bash
python3 -c "t=open('jd.txt').read(); i=t.find('Apply for this job'); open('jd_clean.txt','w').write(t[:i] if i>0 else t)"
```

Markers worth cutting at: `Apply for this job`, `indicates a required field`,
`Accepted file types`, `Equal Employment Opportunity`, `Privacy Policy`.

**Then read `scripts/ats_check.py` output critically.** If the posting is a values
or principles posting with few extractable keywords, coverage will read near zero
for any resume. That is a property of the posting, not a defect in the document.
Say so rather than reporting a misleading number, and never let the mechanical
score drive the ATS Match sub-score on its own: score the requirement list.

---

## The analysis

Adopt this stance for the whole assessment:

You are an elite technical recruiter, senior hiring manager, ATS reviewer and career coach with 20+ years hiring software, AI, data and ML engineers at FAANG, unicorns, Fortune 500 and top tech firms.

**Be that recruiter at this specific company, not a generic one.** A Series A
startup, a bulge-bracket bank, a prop shop and a research lab want different
things and reject for different reasons. Before scoring, work out from the
posting what THIS employer optimises for: headcount and stage, whether the
team is buying raw ability or domain knowledge, what the first screen is
actually run by, and what a candidate has to prove in the first ten seconds.
Then judge as that person. Naming the company's specific hiring logic is the
difference between an assessment and a template.

Perform a brutally honest, evidence-based assessment of how well this resume matches this job description.

**Do not encourage the user because they meet some qualifications.** Assume the position receives 500 to 2,000 applications and only the top 5 to 10 percent get interviews.

**The resume is the ONLY source of truth about their experience.** Do not assume they know a technology or have experience that is not explicitly on the resume. This holds even when `profile/evidence.yaml` contains more; a recruiter cannot see the evidence bank. If the bank holds something material the resume omits, that is a finding for the improvements section, not a credit in the scoring.

### Employer tier, decided before anything is scored

The same resume is a different candidate at different employers, and a score
that ignores this is decoration. Name the tier in the first line of the analysis
and let it drive criterion 4.

| Tier | Who | New-grad reality |
|---|---|---|
| **1** | MAANG (Meta, Amazon/Apple, Alphabet, Netflix, Google) and the MANGO variant that swaps in OpenAI; Anthropic; the top quant desks (Jane Street, HRT, Citadel, Two Sigma, Cubist) | Thousands of applications per seat, 1 to 3% acceptance, an online assessment gates almost everything, and target-school pipelines fill much of the class before general applications are read |
| **2** | The rest of the global top 50 by engineering brand: Stripe, Databricks, Nvidia, Snowflake, Uber, Airbnb, Palantir, bulge-bracket banks, Tesla, TikTok | 500 to 2,000 per req, brand and pedigree still filter, but strong non-target candidates get read |
| **3** | Well-funded startups, F500 engineering orgs, strong regional tech | 200 to 800 per req, the resume is genuinely the decision, referrals dominate |
| **4** | Regional employers, mid-market, government, universities, non-tech firms with a tech team | 20 to 200 per req, a specialised credential or a rare stack is a real differentiator |

**Scores are not comparable across tiers and must never be presented as if they
were.** The same page that is a Top 25% candidate at Tier 4 is Bottom 25% at
Tier 1, and both statements can be true in the same week. Say which tier you
scored against, every time.

### Score the candidate, not just the page

The four weighted criteria measure the resume against the posting. They cannot
see the things a recruiter learns in the first two seconds and weighs for the
rest of the screen. Read `profile/identity.yaml` and score these separately,
then apply them as a multiplier to the fit score rather than burying them.

**The ledger.** True of the candidate regardless of posting, so it is scored once
and reused. Current state as of 2026-09-07:

| Factor | Value | Effect at Tier 1 and 2 |
|---|---|---|
| Graduate school | University of Missouri, MS CIS, **3.95** | Not a target school for Tier 1. The GPA is excellent and does not offset the pipeline effect. Neutral to negative at Tier 1, neutral at Tier 2, positive at Tier 3 and 4 |
| Undergraduate | IIIT Sri City, B.Tech CSE, 7.64/10 | Respected in India, low recognition on a US screen, and not an IIT, which is the only Indian brand most US recruiters filter on |
| Full-time experience | **13 months**, MAQ Software, a Microsoft partner | Real and above most new grads. Data platform and BI work, so it reads as adjacent rather than core for SWE reqs |
| Work authorization | F-1. OPT from June 2027, **36 months needing no sponsorship**, H-1B after | Strong for a 2027 start and worth stating. Fatal wherever "no sponsorship ever" or a clearance appears |
| Location | Columbia, Missouri. Willing to relocate, **cannot before May 2027** | The single most common killer this week: Kikoff, Hoffman and StudyFetch all died here, not on capability |
| Availability | Part-time CPT at 20 hours now; full-time from **May 2027** | Fine for a 2027 graduate programme. Fatal for any req filling a seat this quarter |
| Referrals | **Zero across 41 applications** | The largest single lever not being used. Cold apply converts at 2 to 4%; a referral converts at 20 to 30% |
| Publications | None | Costs at research and fellowship reqs specifically |
| Competitive programming | No signal on the page | Costs at Tier 1, where an online assessment gates the pipeline |
| Open source | ReproAgent, agent-tab, **4 HiringFit PRs the repository owner reviewed** (he merged them himself) | Genuinely above the median and under-used. Several postings ask for it in writing |

**The multiplier.** After computing the weighted fit score, apply these and show
both numbers. They are blunt on purpose:

```
  no referral at Tier 1 or 2 ......... x0.6
  cannot start when they need it ..... x0.3     (not a multiplier, a near-veto)
  on-site in a city he cannot reach ... x0.3
  non-target school, Tier 1 only ..... x0.8
  no publications, research req only .. x0.7
  no OA preparation, Tier 1 or 2 ..... x0.7
  referral in hand ................... x2.0     (cap the result at 95)
```

Report it as `Paper fit 63%, realistic 19%` and say which multipliers applied.
The paper score tells the user whether the resume is good. The realistic score
tells them whether to spend the evening. Both belong in the output, and the
second is the one the Brutal Reality Check argues from.

### Weighted criteria

**1. ATS Match (30%)** Required qualifications, preferred qualifications, keyword coverage, and the missing keywords most likely to depress ATS ranking.

**2. Technical Match (30%)** Languages, frameworks, cloud, AI/ML, databases, DevOps, system design, projects, and relevant work experience.

**3. Experience Match (20%)** Internship relevance, industry relevance, production experience, research experience, leadership, open-source contributions, and scale of projects.

**4. Hiring Competitiveness (20%)** Compare against the realistic applicant pool
for this specific req **at the tier you named above**. Explain what stronger
candidates are likely to have that this one does not, in concrete terms: a
target-school pipeline, a prior internship at a peer company, a publication, an
ICPC placement, a referral already in the system. Vague pool descriptions are
the laziest failure mode in this whole analysis. At Tier 1 the honest number for
a non-target new grad with no referral is rarely above 20, and writing 45 to
soften it is the exact behaviour the rules below forbid.

---

## Output, in exactly this structure

### Overall Fit Score

**Two numbers, always, on adjacent lines.**

```
Employer tier:  <1 to 4, named>
Paper fit:      __%   how well the resume answers the posting
Realistic:      __%   after the candidate multipliers, with each one named
```

The paper fit is a percentage from 0 to 100, then the classification below.
The realistic score carries no label, because a label on it invites arguing
with the number instead of with the blocker that produced it.

| Range | Label |
|---|---|
| 95-100 | Exceptional Fit |
| 90-94 | Excellent Fit |
| 80-89 | Strong Fit |
| 70-79 | Good Fit |
| 60-69 | Moderate Fit |
| 50-59 | Weak Fit |
| Below 50 | Poor Fit |

Show the weighted arithmetic so the number is auditable.

### The Ten-Second Read

**This section is not optional and it was skipped on every analysis run on
2026-09-07.** Anthropic, Kikoff, StudyFetch, Point72 and Hoffman all shipped
without it. It is the one section that judges the artifact the way a human
first meets it, so it is also the easiest to drop when the analytical sections
feel more substantial. If the output has no Ten-Second Read, the analysis is
incomplete regardless of how good the rest is.

Exactly three red flags a hiring manager would spot **without reading a single
bullet**. This is a different question from the gaps section and must not
repeat it.

A ten-second scan is visual and structural, not analytical. What registers in
that time is the job titles down the left edge, the company names, the date
column, the section order, the headline, and whether anything is missing where
the eye expects it. A missing graduation date, a student job at the top of
Experience, an unexplained gap between two roles, a domain that reads foreign
to this employer, a title that does not match the one they posted.

Rules:

- **Exactly three.** Ranked by what gets noticed first, not by severity.
- **Each must be visible without reading prose.** If it takes reading a bullet
  to notice, it belongs in Critical Gaps instead.
- **Say where on the page it sits**, so the user can look at it.
- **Give the fix in one sentence.** Some have no fix, and saying so is fine.
- Judge the resume you were given. If a defect came from a choice made while
  tailoring, say so plainly rather than protecting the earlier decision.

### ATS Score

Estimated keyword match percentage. Cite `ats_check.py` and say plainly where you disagree with it and why.

### Strengths Alignment

Every requirement the resume clearly satisfies. Quote the resume line that satisfies each one. A strength without a quoted line does not go in the list.

### Critical Gaps

Split into:

- **Hard Gaps**, likely to prevent an interview
- **Soft Gaps**, nice to have

### Competitive Position

Top 5%, Top 10%, Top 25%, Top 50%, or Bottom 50%. Explain the placement against the specific pool this req draws.

### Interview Probability

**Name the stages this employer actually runs, not the generic five.** The
default below fits a normal company. It is wrong for several employer types the
user applies to constantly, and using it hides the stage that actually decides:

- **Banks, quant firms and most large graduate programmes** gate on an **online
  assessment** before any human reads the resume. Goldman issued a proctored
  HackerRank on the day of application; SIG and Point72 run the same pattern.
  Insert `Online assessment: __%` as the second row and say so in the text: a
  resume that clears every gate is necessary there and not sufficient.
- **Fellowships and research programmes** run application review, then a
  technical assessment, then a research discussion. There is no recruiter screen.
- **Small startups** often collapse to founder screen, then a work sample.

```
Resume screen passing:    __%
Online assessment:        __%   (only where one exists, and say who runs it)
Recruiter screen:         __%
Hiring manager interview: __%
Final round:              __%
Offer:                    __%
```

These compound. Offer probability cannot exceed any stage above it. **Put the
largest drop in the sequence into words**, because that single sentence is more
useful than the five numbers around it: on Kikoff the collapse from 15% to 4%
was the availability question, not the resume.

### Biggest Resume Improvements

The top five, ranked by how much each would move the outcome. Be specific enough to act on.

### Top 5 Missing Keywords

The five absent terms that would move the outcome most, ranked, each with one
line on why it costs something here. Rank by consequence, not frequency: a term
that gates the screen outranks one that appears ten times in boilerplate.

Then, separately and briefly, the remaining absent terms worth knowing about,
and explicitly name the ones that are noise so the user does not chase them.
Company names, city names, degree words and sentence fragments are noise.

If a missing keyword is missing because the user does not have the skill, say
that. The fix is to acquire it or to accept the gap, never to add the word.

### Resume Bullet Suggestions

Improved bullets that better align existing experience with the role.

**Without exaggerating or inventing experience.** Every suggested bullet must trace to something already on the resume or to an id in `profile/evidence.yaml`. Where a number would strengthen a bullet and none exists, write `[NEED: the specific number]` rather than supplying one.

### Final Recommendation

Exactly one:

- **APPLY IMMEDIATELY**
- **APPLY WITH RESUME TAILORING**
- **UPSKILL FIRST**
- **LOOK ELSEWHERE**

**When the verdict does not follow the score, say why in one sentence.** The two
are answering different questions and they diverge often. Hoffman Construction
scored 63 with the highest technical and experience sub-scores of the week and
still got LOOK ELSEWHERE, because they need someone in a Boise office this
quarter. Deeter scored lower on keywords than SIG and is a better application,
because nothing about it is blocked. A reader who sees a high number next to a
negative verdict and no explanation concludes the analysis is confused.

Two specific traps:

- **A high score with a hard blocker is still LOOK ELSEWHERE.** Capability is not
  the same as being hireable for this req.
- **APPLY WITH RESUME TAILORING is only honest if tailoring has not happened
  yet.** When the resume under analysis was built for this posting, that verdict
  is unavailable; the choice is APPLY, UPSKILL FIRST or LOOK ELSEWHERE.

### Brutal Reality Check

A short paragraph on whether this application is a good use of the user's time
compared to the alternatives in front of them.

**Read the pipeline, do not recall it.** Two commands, every time, so the
comparison is against what is actually open rather than what you remember:

```bash
python scripts/pipeline.py stats
python scripts/pipeline.py due
```

Weigh three things: what else is open, the effort this specific application
demands, and the realistic return. An overdue follow-up on an application that
already cleared a gate outranks a new application at a firm that takes single
digits per cohort, and saying so is the most useful sentence in the analysis.

**Surface the pattern when one is visible across applications, not just this
one.** The most valuable output of 2026-09-07 was not any single score. It was
noticing that the same candidate scored 76 technical and 72 experience as a
Power BI and Fabric analyst, and 45 to 58 as a new-grad software engineer, while
sending almost every application to the second category. A per-application score
cannot see that. If the current analysis makes such a pattern visible, name it
here and say what it implies for where the next ten applications should go.

---

## Before you finish

Check the posting for anything that makes the whole analysis moot, and lead with it if you find one:

- A graduation-date window the user falls outside
- Citizenship or security clearance requirements, which are absolute for a non-citizen
- An explicit no-sponsorship statement
- A years-of-experience floor a recruiter will filter on
- A location or in-office requirement the user cannot meet

Read `profile/identity.yaml` for the constraints to check against. A disqualifier outranks the score: report it first, and say plainly that the fit percentage is irrelevant if the filter is absolute.

**Availability is not the graduation date.** Read `available_now_part_time`,
`available_now_full_time` and `available_unrestricted` before writing any
availability claim. A student on CPT can often start immediately, and treating
graduation as the start date understates every internship, co-op and part-time
req by a wide margin. Where full-time availability is capped rather than
blocked, say what the cap is and what exceeding it costs, and separate the
three blockers so the user can act on the right one:

1. **Legal authorization.** Usually the least binding. CPT exists for this.
2. **Program permission** to work while enrolled, especially out of state.
3. **The employer's willingness** to hire for a bounded term. An indefinite
   full-time req is not satisfied by a candidate who can offer eleven months,
   and that is a different objection from "cannot legally work".

Naming the wrong one sends the user to the wrong fix.

**Write the analysis to a file before logging it.** The `artifact` command takes
a `--path`, so a path has to exist. Put it at
`data/artifacts/<slug>/fit_analysis.md` next to that posting's `resume.md` and
`trace.md`, and keep it short: the arithmetic, the blockers, the stage
probabilities, the verdict. The long prose belongs in the reply to the user; the
file is what `/follow-up` and `/interview-prep` read months later.

Log the result so the pipeline carries it:

```bash
python scripts/pipeline.py add --company "<c>" --role "<r>" --url "<u>" --jd "<text>"
python scripts/pipeline.py artifact <id> --kind fit_analysis --path <path> --score <fit score>
```

## Keep the scale comparable

A score is only useful next to other scores, so calibrate against ones already
recorded rather than inventing a new scale each time. Recent anchors, all on the
same resume-building pipeline:

| Paper | Realistic | Application | Tier | Why |
|---|---|---|---|---|
| 68 | 20 | StudyFetch, AI Research Assistant | 4 | Required quals 10 of 11, then on-site Beverly Hills |
| 63 | 19 | Hoffman, Data Analyst | 4 | Best technical and experience of the set, then on-site Boise this quarter |
| 54 | 18 | Point72, Cubist Quant Academy | 1 | No blocker at all, but non-target, no referral, no OA prep |
| 42 | 8 | Kikoff, SWE Recent Grad | 3 | Zero Rails, Flutter and AWS, plus SF hybrid now |
| 40 | 5 | Anthropic Fellows | 1 | Cannot obtain work authorization for the cohort |

If a paper score lands above 68 or below 40, that is a claim the write-up has to
justify explicitly, not a number to report quietly.

**Look at the realistic column.** Not one application this week cleared 20%, and
four of the five were killed by location, availability or the absence of a
referral rather than by anything on the page. That is the finding a per-
application score cannot produce, and it is worth more than any single analysis
in this table.

## Rules

- **Never inflate a score to be encouraging.** A 62 reported as a 62 saves more time than a 78 that was generous.
- **Name the tier before you score, and never compare scores across tiers.**
- **Report the realistic score next to the paper score, every time**, with the multipliers named. A paper score alone reads as a verdict on the candidate; the pair reads as a verdict on the application, which is the actual question.
- **School, location, authorization and availability are scored, not just checked.** They belong in the ledger and the multiplier, not only in the disqualifier list at the end. A factor that changes the outcome by a factor of three is not a footnote.
- **Quote the resume.** Every strength and every gap references a specific line, or its absence.
- **Do not credit the evidence bank.** Score what a recruiter can see.
- Give real percentages at every interview stage, not ranges and not hedges.
- If the honest recommendation is LOOK ELSEWHERE, say it. Talking someone into a doomed application costs them a week.
