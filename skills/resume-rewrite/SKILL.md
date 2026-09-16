---
name: resume-rewrite
description: Rewrite a resume for a specific target role using the evidence bank, then run it through an adversarial recruiter screen, an anchored quality judge, an ATS parse audit, and a hallucination check, revising until it passes. Use when the user wants a resume tailored, rewritten, improved, or checked against a job posting.
trigger: /resume-rewrite
---

# /resume-rewrite

Rewrite a resume so a recruiter who screens two hundred a day stops on it.

```
/resume-rewrite                                   # target role from the pipeline, or ask
/resume-rewrite "ML Engineer" "seed-stage AI startup"
/resume-rewrite --jd path/to/posting.txt
/resume-rewrite --jd-url https://boards.greenhouse.io/...
/resume-rewrite --app 14                          # a specific pipeline application
/resume-rewrite --quick                           # single pass, no revise loop
```

## What makes this different from asking an LLM to rewrite a resume

Three things, and they are the whole point:

1. **Bullets are selected from the evidence bank, not invented.** Every line traces to an `EV-` id in `profile/evidence.yaml`. A `fact-checker` agent blocks the draft if any claim does not.
2. **It is a loop, not a single pass.** Draft, then four agents attack it in parallel, then revise against what they found, then attack again. It stops when the recruiter screener says INTERVIEW and the judge clears the rubric, not when the model feels done.
3. **The judge cannot see its own previous work.** Each scoring pass runs in a fresh subagent, so the score reflects the rubric rather than drifting upward across revisions.

**This skill is split.** `SKILL.md` is the rules and is loaded every time you
invoke it. `skills/resume-rewrite/reference.md` holds the incident behind each
rule and is loaded ONLY when a gate actually fails or you are about to bend a
rule. Read the one section you need, never the whole file. The split was made
2026-09-14 because the skill had reached 590 lines and was being re-injected in
full eight times in one session.

## Bootstrap

Run this first, every time:

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
```

Then check the evidence bank exists:

```bash
python connectors/build_evidence.py stats
```

If `profile/evidence.yaml` is missing, stop and tell the user to run `/career-setup` first. Do not attempt to write a resume without it; that is the mode this repo exists to eliminate.

Read `templates/style-rules.md` and `profile/voice.md` before writing anything.

## Step 0: Read the FORM, not just the posting

Run this before anything else, every time:

```bash
python scripts/form_check.py <url>        # or --app <pipeline id>
```

**Three applications died at the form in one week, every one after a posting
that screened completely clean.** Emerson: the posting said only "Legal
authorization to work in the United States", he applied, and was told there is
no sponsorship. Equifax: the posting had no sponsorship, citizenship or
clearance language at all, it was the strongest application in the pipeline at
paper 76 and realistic 27, and it was rejected at 02:20 two days later with "we
are unable to offer sponsorship for this role". BCG X: posting clean, graduation
window an exact match, and the portal simply refuses.

`screen_job.py` reads postings. The form is a different document and it is where
the applications are dying.

**What the exit code means:**

| Exit | Verdict | What to do |
|---|---|---|
| 3 | `BLOCKER` | A citizenship or clearance gate with no lawful non-citizen option. **Do not build.** Withdraw the row and say why |
| 1 | `FLAG` | A sponsorship question, or a fixed school list. Build only after telling him it is there and what it has cost before |
| 2 | `MANUAL` | The ATS does not expose its form. Lever, Ashby, Workday, Oracle and bespoke portals all fall here. **Ask him to open the apply page and read the questions before you build** |
| 0 | `CLEAN` | No gate found. Proceed |

Measured on 2026-09-13 across 27 live Greenhouse rows: **2 BLOCKER, 17 FLAG,
6 MANUAL, 2 CLEAN.** Only two of twenty-seven were clean. A FLAG is therefore
normal and is not on its own a reason to skip a posting; it is a reason to say
so in the report and let him decide, because he answers honestly and some
employers still proceed.

**A false BLOCKER costs more than a false FLAG.** ASM International's
export-control question lists "Alien Authorized to Work", which is exactly what
he is, so it is a disclosure and not a gate. `form_check.py` downgrades any
citizenship-shaped question that offers a lawful non-citizen option. If you ever
withdraw a row on a BLOCKER, read the options first.

## Step 1: Establish the target

You need a job posting. In order of preference:

- `--jd` file path, or `--jd-url` (fetch it)
- `--app <id>`, then `python scripts/pipeline.py show <id> --json` and use the stored `jd_text`
- The user pasted it into the conversation
- Only a role title and company type were given

If you have an actual posting, dispatch the `jd-analyst` agent on it. Do not skip this. Its ranked must-haves and its "THE ONE THING" line drive every decision below.

If you have only a role title and company type, say so plainly, then write against the general shape of that role. Tell the user that supplying the actual posting would materially improve the result, and continue rather than blocking.

If a company name is available, dispatch `company-researcher` in parallel with `jd-analyst`.

## Step 2: Select evidence

Read `profile/evidence.yaml` in full.

Rank every atom against the posting's ranked must-haves. Selection rules:

- **Eight to twelve atoms total** for a one-page resume. Fewer, stronger beats more, weaker.
- **The single strongest atom for the top must-have goes in the first bullet of the most recent role.** That bullet is most of the six-second decision.
- **Cut, do not shrink.** An atom that does not map to a ranked requirement comes out entirely. Compressing it to one line still costs a line and still dilutes.
- **Prefer atoms with `metric` present.** An atom with no metric goes in only if it proves a must-have nothing else covers, and then it leads with scope instead.
- **Respect `confidence`.** An `approximate` atom must be hedged in a way that survives "how did you measure that?"
- **Never use an atom the posting gives you no reason to include,** however proud the user is of it.

Report which atoms you selected and which strong ones you left out, with the reason. The user often knows something about relevance that the bank does not capture.

## Step 3: Write the draft

Write to `data/artifacts/<company>-<role>/resume.md` in the markdown subset that `scripts/render.py` accepts:

```markdown
# Full Name
email | phone | github.com/user | linkedin.com/in/user | City, Country

## Experience

### Title | Company | Location | Start to End
- Bullet with a number in it.

## Projects

### Project Name | Tech, Stack, Here | Date
- Bullet.

## Education

### Degree | Institution | Location | Years

## Skills
Comma separated, every one backed by a bullet above.
```

Writing rules, on top of `templates/style-rules.md`:

- Start every bullet with a past-tense action verb
- Mirror the posting's exact vocabulary for concepts, from the `jd-analyst` vocabulary table
- Vary bullet length. Uniform length reads as generated and the screener is watching for it.
- No pronouns, no articles where they can be dropped, no adverbs
- One idea per bullet
- Keep a parallel file `data/artifacts/<company>-<role>/trace.md` mapping every bullet to its `EV-` id. This is what makes the fact check possible and what lets the user prepare for interviews.

### What the top screens actually reward

`templates/style-rules.md` already governs verbs, numbers, concrete nouns and
rhythm. What follows is the layer above that, and it is the difference between a
clean resume and one that survives a Google, Meta, Amazon or Microsoft screen.

**Every bullet answers three things, outcome first: what changed, by how much,
and what you did to cause it.** Google publishes this as "Accomplished X as
measured by Y by doing Z", and Amazon, Meta and Microsoft screen for the same
shape under other names. Order matters, because a six-second scan reads the
front of the line and stops.

    See reference.md for the worked weak/strong pair.

**Scale belongs on the page and is not the same thing as a metric.** A metric
says the thing got better. Scale says the thing was big enough to be hard.
Requests per second, rows, users, dollars, team size, duration, systems
integrated. On `EV-020`, "10,000+ concurrent requests" is scale and "200ms
latency cut" is a metric; the entry needs both. The Google Recruiter lens in
Step 4b rejects on "no scale anywhere on the page", so **three scale figures per
resume is the floor**.

**The decision happens in the top third.** Header, tagline, and the first two
bullets of the most recent role. Everything below either confirms a decision
already made or fails to contradict it. So the strongest evidence for the
posting's top requirement goes in the first bullet of the most recent role and
never lower, even when an older job matches the posting better. When the better
evidence does sit in an older job, the fix is the tagline, not reordering the
page: reverse-chronological order is not negotiable and `chrono_check.py`
enforces it.

**The tagline is governed, not freestyle.** Two centred lines under the header,
on every variant, carrying exactly three things: the role as the posting words
it, the three to five technologies that posting ranks highest, and the degree
with GPA. Nothing else. No objective statement, no "seeking a challenging role",
no adjectives about yourself. It is the only place on the page where the target
title may be named directly, which is how a resume matches a req that the
experience section cannot.

**The "so what" test, on every bullet before shipping.** Read it and ask once.
"Built a RAG service" fails. "Built the RAG service the lab queries daily"
passes, because someone uses it. A bullet that survives names a person, a
system or a number that is different because the work happened.

**For Amazon and Amazon-shaped employers, seed the leadership principles.** Never
name one on the page; choose atoms that demonstrate them. Mapping in reference.md.

## Step 4: The review loop

Run up to three passes. In each pass, dispatch these **in parallel, in a single message**:

- `fact-checker` on the draft, with `profile/evidence.yaml`
- `ats-auditor` on the rendered file, with the posting
- `resume-judge` on the draft, with the posting
- `recruiter-screener` on the draft, with the posting

Render before auditing so the ATS check sees the real artifact, which is the
compiled PDF, not a DOCX:

```bash
tectonic main.tex && python scripts/ats_check.py --resume main.pdf --jd <posting>
```

Merge the verdicts by priority:

1. **`fact-checker` BLOCKED beats everything.** Fix hallucinations and inflations first, always. A resume that scores 95 and contains an invented metric is a failure, not a success.
2. **`ats-auditor` FATAL** next. A document a parser cannot read has no other properties worth discussing.
3. **`resume-judge` blocking items** next. Apply its literal rewrite lines; that is why it produces them.
4. **`recruiter-screener` reject reasons** last, because they are usually a symptom of the above.

Then revise and run the pass again. Each agent call is a fresh subagent, so none of them see the previous round.

**Exit conditions.** Stop when `recruiter-screener` returns INTERVIEW and `resume-judge` returns PASS and `fact-checker` returns PASS. Or stop after three passes. Passing Step 4 does not finish the resume: Step 4b still has to clear.

If you stop at three passes without passing, do not present the draft as finished. Report exactly what is blocking, and say which of these it is:

- **Missing evidence.** The bank has no atom that proves a must-have. The fix is not writing; it is either adding real evidence or accepting the gap.
- **Missing metrics.** Atoms exist but have no numbers. Run `python connectors/build_evidence.py gaps` and ask the user for the specific numbers.
- **Genuine role mismatch.** The candidate does not meet the bar for this posting. Say so. This is useful information and softening it wastes the user's applications.

## Step 4b: The panel

The four agents in Step 4 check that the document is true, parseable and
well-built. They do not answer the only question that matters to a human:
**would I bring this person in?**

So before shipping, run the draft past four named reviewers. Dispatch them **in
parallel, in a single message**, each in a fresh subagent so none sees another's
verdict. Give each one the resume, the posting, and its own lens verbatim.

**Amazon Bar Raiser.** Your job is to protect the bar, not to fill the role. Ask
whether this person would raise the average of the team they are joining. You
want quantified outcomes, personal ownership, and evidence the candidate went
deep rather than wide. Reject on: responsibilities described instead of results;
"helped with", "worked on", "was involved in"; team achievements with no stated
personal contribution; any number without a baseline; scope you cannot size.
Name the specific bullet each objection lands on.

**Microsoft Hiring Manager.** You are filling a real vacancy on your own team.
You want depth in at least one area, evidence of collaboration, and evidence the
person learns. Reject on: breadth with no depth anywhere; no sign of working with
anyone else; projects that were built but never shipped or used; a stack list
with nothing behind it; no evidence of handling something they did not already
know how to do.

**Google Recruiter.** You have six seconds and 400 other resumes. You scan the
title column, the company column, the dates, the education line and the top
bullet, in that order. Reject on: unclear or inflated titles; unexplained gaps;
no scale anywhere on the page; the first bullet of the most recent role failing
to state an outcome; formatting that costs you time; keywords from the posting
missing where you expect them. Say what you saw and in what order.

**Meta Engineering Manager.** You care about impact and speed. What did this
person personally ship, how quickly, and what changed because of it? Reject on:
process description with no outcome; no evidence of shipping to real users; no
evidence of operating under ambiguity; ownership that stops at "contributed";
work that reads like coursework rather than production.

Merge the four the same way as Step 4: fix anything that appears in more than one
reviewer's rejects first, since a defect two lenses catch is a defect. Then work
the individual objections in the order Bar Raiser, Meta, Microsoft, Google,
because the first two demand content changes and the last two are usually cured
by the first two.

**Exit condition: all four recommend an interview.** Not three. If a reviewer
still rejects after three passes, do not quietly ship it. Report which reviewer,
on which bullet, and why, and say plainly whether the fix is a rewrite, missing
evidence, or a genuine mismatch with the posting. A resume that three of four
would advance is useful information, and pretending otherwise wastes an
application.

Do not let the panel push the page into invention. Every objection is answered
from `profile/evidence.yaml` or it is answered with `[NEED: the specific number]`
and a question to the user. A Bar Raiser complaint about a missing baseline is
not licence to supply one.

### When subagents are not available

Steps 1, 4 and 4b are written around dispatching agents in parallel. Some
sessions cannot dispatch them at all. **Do not skip the work.** Run every lens
inline, in the same order and against the same rejection criteria, and say in
the report that they ran inline rather than as independent reviewers, because a
lens applied by the same writer who produced the draft is weaker evidence than
one applied by a fresh reader.

What does not change either way is Step 5. The deterministic gates are the half
of this skill that actually catches defects, they need no model at all, and
their output goes in the report verbatim. Every resume built on 2026-09-07 ran
in this mode.

## Step 5: Ship it

```bash
python scripts/style_check.py data/artifacts/<slug>/resume.md
# DOCX only if the posting demands Word. Otherwise ATS-check the PDF itself.
python scripts/ats_check.py --resume <resume.pdf> --jd <posting>
```

### The gate, on the PDF, every single time

A resume is not finished until all of these pass on the compiled PDF. Run them
on the actual output file, not the markdown or the `.tex`: every defect they
catch exists only after rendering. **A check you did not run is not a check.**

```bash
python scripts/page_check.py    <resume.pdf>            # fills the page, no orphan page, no internal holes
python scripts/line_check.py    <resume.pdf>            # every wrapped bullet ends past 60% of the column
python scripts/spacing_check.py <main.tex> <resume.pdf> # one spacing value, one bullet rhythm
python scripts/chrono_check.py  <resume.pdf>            # reverse-chronological, no unexplained overlap
python scripts/title_check.py   <resume.pdf>            # job titles match the ones actually held
python scripts/tex_check.py     <main.tex>              # stray markup, ligatures, extractability
pdftotext -layout <resume.pdf> - | grep -nE "^[A-Z][A-Z &]{3,}$"   # read the headings back
```

**The rules. Every one cost a sent resume. `skills/resume-rewrite/reference.md`
has the incident behind each; read only the section you are questioning.**

- **Never retitle a job.** Titles come from `profile/titles.yaml` verbatim. A title is a factual claim a background check verifies against payroll.
- **Fill the page to the last line**, within a third of an inch. Fill with real evidence from the bank, never filler.
- **Certifications get a section, never a mention.** All four credentials, every variant, each with a working `Verify` link. Cut a project before a certification.
- **Open every link signed out before shipping.** A 404 is worse than no link; a repo with a security problem is worse than no project. Guardian AI (`EV-019`) and SPD-React (`EV-042`) stay off every page until theirs are fixed.
- **The Microsoft credential lapses 2026-11-26.** Once it does, the Verify link disproves the line above it.
- **One `\itemsep` value for the whole document.** Fill a short page by tuning that one value, never by spacing a single section differently.
- **Every job on every variant. Three projects maximum.** Experience outweighs a personal project every time. Cut order: fourth project, then third, floor of two; then the weakest bullet in an experience entry, longest-serving job last; never a whole job, a degree or a certification.
- **Measure the page, do not eyeball it.** `pdftotext -bbox-layout` and read consecutive `yMin`/`yMax` pairs.
- **Fix a runt by arithmetic.** Measure the column, compute `need = int(width * 0.60)`, size the edit to the deficit. Editing by feel wastes a dozen builds.
- **Use `extarticle`, not `article`.** `article` silently ignores 8pt and 9pt.
- **Tie every multi-word keyword with `~`**, especially in the skills block, so LaTeX cannot split it across lines and cost the ATS match.
- **Standard section headings only**, checked against `CANONICAL_HEADINGS` in `scripts/ats_check.py`.
- **Three standing exclusions:** the C++ barn camera bullet is retired unless a posting names C++ or systems programming among its stated requirements; never name a language construct (`std::mutex`, `lock_guard`, `RAII`); no unverified numbers and none sourced to another resume.

Log it, so `/follow-up` and `/interview-prep` can use it later:

```bash
python scripts/pipeline.py artifact <app-id> --kind resume \
  --path data/artifacts/<slug>/resume.pdf \
  --score <judge-score> --verdict <screener-verdict> \
  --evidence "EV-001,EV-014,..."
```

If no pipeline entry exists yet, create one with `pipeline.py add` first.

## Step 6: Report

Show the user:

- **The resume itself**, rendered in the response so they can read it without opening a file
- **Score movement**: ATS keyword coverage before and after, judge score, screener verdict
- **What changed and why**, as a short list. "Replaced the top bullet because it described a responsibility; the new one leads with the throughput number, which is their first stated requirement."
- **Every bullet with its evidence id**, so they know what they will be asked about
- **What you cut**, and why
- **Gaps you could not close**, stated plainly
- **Where the resume actually sits in the funnel.** At Goldman, SIG, Point72 and
  every bank or quant programme, an online assessment gates the pipeline before
  a human reads a word. A resume that clears every gate in this skill is
  necessary there and not sufficient. Say so, so that a strong page is never
  mistaken for a strong position. The same applies in reverse: when a posting
  has no such gate and the fit is real, say that the resume is the whole
  decision and worth the extra pass
- **File path** for the PDF, plus the DOCX only if the posting required one

## Rules

The build gate above already lists the page-mechanics rules. These are the ones
that govern what goes ON the page.


- **No em dashes, anywhere, ever.** Hard style rule across everything written for Srikar, enforced by `style_check.py`. Use a comma, a colon or a full stop. It is also an AI tell that recruiters screen for.
- Never invent a metric. Not once, not as a placeholder that looks real. Use `[NEED: throughput before and after]` and ask.
- Never add a skill to the skills section that no bullet demonstrates.
- Never claim a technology absent from `profile/skills.yaml`.
- If the user asks you to add something the evidence does not support, say what the evidence supports instead and let them decide. Do not silently comply and do not refuse; give them the accurate version and the choice.
- Work authorization is stated honestly when the posting or form asks. Never obscure it.
- **Full-time roles only**, as of 2026-09-04. No internships, co-ops, part-time, apprenticeships or summer analyst programmes. `NOT_FULL_TIME` in `screen_job.py` drops them at the title stage before any fetch.
- **Ship the PDF. Do not build a DOCX unless the posting demands one.** Reversed 2026-09-07 at Srikar's direction after two were built nobody asked for. `render.py` produces a visibly worse document than the one every gate ran against. Build one only when a posting names Word specifically. Cover letters are unaffected. See reference.
- One page unless the user has ten or more years of experience.
- Numbers on the page must trace to an `EV-` id whose source is not another resume. `EV-002` is sourced only to `Srikar_Resume_ML.pdf`, so its "9 architectures" and "0.94 macro-F1" stay off new resumes until they are traced. Use the method without the figure rather than dropping the evidence entirely.
- **When two records disagree about a number, go to the primary source. Do not trust the `metric` field.** On 2026-09-04 `EV-018`'s metric said 5 merged pull requests while `titles.yaml` and the evidence bank's own header comment both said 4. The metric was believed and 5 went onto eight resumes, four of which were sent. The GitHub API settled it: 6 PRs opened on `dhpiyush/hiring-fit`, 4 merged, 2 still open, and one of the merged ones a revert. A `metric:` value is a summary someone typed; the repository, the transcript or the credential page is the fact. Reconcile against the thing itself, then fix every file.
- **Every number on the page needs an answer to "how did you measure that?"** before it ships, not after an interview is scheduled. The `trace.md` records which `EV-` id a bullet came from; it does not record whether the claim can be defended out loud. Two atoms on recent pages fail this today: `EV-004`'s GPU-infrastructure claims, whose only source is another resume, and `EV-034`'s Power Automate flow, where Srikar recalls the shape and not the systems. Both are usable, both need him warned in the report, and neither should reach a page silently.
- Run the checks on the compiled PDF and paste the output. A check you did not run is not a check, and a check that finds nothing to check has failed, not passed.
