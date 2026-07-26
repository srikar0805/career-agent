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

## Step 4: The review loop

Run up to three passes. In each pass, dispatch these **in parallel, in a single message**:

- `fact-checker` on the draft, with `profile/evidence.yaml`
- `ats-auditor` on the rendered file, with the posting
- `resume-judge` on the draft, with the posting
- `recruiter-screener` on the draft, with the posting

Render before auditing so the ATS check sees the real artifact:

```bash
python scripts/render.py data/artifacts/<slug>/resume.md -o data/artifacts/<slug>/resume.docx
```

Merge the verdicts by priority:

1. **`fact-checker` BLOCKED beats everything.** Fix hallucinations and inflations first, always. A resume that scores 95 and contains an invented metric is a failure, not a success.
2. **`ats-auditor` FATAL** next. A document a parser cannot read has no other properties worth discussing.
3. **`resume-judge` blocking items** next. Apply its literal rewrite lines; that is why it produces them.
4. **`recruiter-screener` reject reasons** last, because they are usually a symptom of the above.

Then revise and run the pass again. Each agent call is a fresh subagent, so none of them see the previous round.

**Exit conditions.** Stop when `recruiter-screener` returns INTERVIEW and `resume-judge` returns PASS and `fact-checker` returns PASS. Or stop after three passes.

If you stop at three passes without passing, do not present the draft as finished. Report exactly what is blocking, and say which of these it is:

- **Missing evidence.** The bank has no atom that proves a must-have. The fix is not writing; it is either adding real evidence or accepting the gap.
- **Missing metrics.** Atoms exist but have no numbers. Run `python connectors/build_evidence.py gaps` and ask the user for the specific numbers.
- **Genuine role mismatch.** The candidate does not meet the bar for this posting. Say so. This is useful information and softening it wastes the user's applications.

## Step 5: Ship it

```bash
python scripts/style_check.py data/artifacts/<slug>/resume.md
python scripts/render.py data/artifacts/<slug>/resume.md -o data/artifacts/<slug>/resume.docx --pdf
python scripts/ats_check.py --resume data/artifacts/<slug>/resume.docx --jd <posting>
```

Log it, so `/follow-up` and `/interview-prep` can use it later:

```bash
python scripts/pipeline.py artifact <app-id> --kind resume \
  --path data/artifacts/<slug>/resume.docx \
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
- **File paths** for the DOCX and PDF

## Rules

- Never invent a metric. Not once, not as a placeholder that looks real. Use `[NEED: throughput before and after]` and ask.
- Never add a skill to the skills section that no bullet demonstrates.
- Never claim a technology absent from `profile/skills.yaml`.
- If the user asks you to add something the evidence does not support, say what the evidence supports instead and let them decide. Do not silently comply and do not refuse; give them the accurate version and the choice.
- Work authorization is stated honestly when the posting or form asks. Never obscure it.
- One page unless the user has ten or more years of experience.
