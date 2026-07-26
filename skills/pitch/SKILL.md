---
name: pitch
description: Write a freelance proposal or a cold client pitch framed around the client's outcome and ROI rather than your credentials. Uses the evidence bank for proof. Use for freelance work, consulting proposals, client outreach, contract bids, or upwork-style applications.
trigger: /pitch
---

# /pitch

Freelance proposals and client outreach. Same engine as the job skills, different frame.

```
/pitch "Acme Corp" "data pipeline build"
/pitch --cold "Acme Corp"                    # cold outreach, no brief
/pitch --brief path/to/rfp.pdf               # respond to a posted brief
/pitch --rate                                 # work out what to charge
```

## The frame shift

A job application answers "should we hire this person?" A client pitch answers "will this spend return more than it costs?"

That difference changes everything downstream. A hiring manager is evaluating you. A client is evaluating a purchase. They do not care about your trajectory, your growth, or your fit with a team, because none of those things exist in a three-month engagement. They care about whether the problem goes away and what it costs.

Practical consequences:

- **Lead with their outcome, not your background.** Credentials are supporting evidence, placed after the outcome, not before it.
- **Talk in money and time.** "Cut p99 latency 4x" is a job-interview line. "Cut p99 latency 4x, which took checkout abandonment from 8% to 5%" is a client line.
- **Risk is their main objection, not capability.** Most clients have been burned by a contractor before. Reducing perceived risk beats demonstrating more skill.
- **Scope is the deliverable.** A pitch with vague scope is a pitch the client cannot say yes to, because they cannot tell what they are buying.

## Bootstrap

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
```

Read `profile/evidence.yaml`, `profile/voice.md`, `templates/style-rules.md`.

## Step 1: Research

Dispatch `company-researcher`. For a client pitch you want their business situation, not just their tech: what they sell, who to, what is publicly breaking or growing, recent funding, whether they are hiring for the thing you would do (a strong signal that the need is real and budgeted).

If responding to a brief, dispatch `jd-analyst` on it. A brief is a job posting with a budget, and the same decoding applies: what is the real problem, what is padding, what is the unstated worry.

## Step 2: Structure the pitch

**The outcome, 1 to 2 sentences.** What will be true after this engagement that is not true now. In their terms. This is the entire opening.

**The problem, as you understand it.** Restate it in a way that demonstrates you understand it better than the brief described. This is where most pitches win or lose, because a client reading their own problem described more clearly than they wrote it concludes you have seen it before.

**The approach, 3 to 5 steps.** Concrete enough to be credible, not so detailed that you are working for free. Name the actual first step.

**The proof, 1 or 2 items.** From the evidence bank. The most similar thing you have done, with the number. One strong proof beats a portfolio.

**Scope and timeline.** Explicit. What is included, what is not, how long, what you need from them. The exclusions matter as much as the inclusions and they prevent the engagement from silently expanding.

**Price.** State it. A proposal without a number forces another round of email and loses momentum.

**Risk reduction.** A paid discovery phase, a milestone structure, a small first engagement. This is what converts a hesitant client, and it is the most commonly omitted section.

## Step 3: Pricing

With `--rate`, work it out rather than guessing.

- **Value anchor first.** What is this problem costing them per month? Price against that, not against your hourly rate.
- **Project price over hourly** where the scope is knowable. Hourly caps your upside, invites scrutiny of your hours, and makes efficiency a punishment.
- **Three tiers convert better than one price**, because it moves the decision from "yes or no" to "which one", and the middle tier is usually chosen.
- **Never lead with a rate.** The number lands very differently after the outcome section than before it.
- Include a specific payment schedule. Ambiguity here becomes a collections problem later.

Be honest about the uncertainty in any estimate, and price the uncertainty rather than absorbing it.

## Step 4: Cold client outreach

If no brief exists, this is a cold message and the rules from `/cold-message-manager` apply, with one addition: lead with a problem you can see from outside.

"Your checkout flow makes four sequential API calls before rendering, which is most of the 2.8 second load time I measured" is a cold open that gets a reply, because it is free work delivered up front and it proves capability better than any credential.

Under 120 words. One specific observation, one relevant result, one small ask.

## Step 5: Review

Dispatch in parallel:

- `fact-checker` on the draft
- `resume-judge` on the alternate dimensions, with Pain mapping weighted heavily since it is the core of a pitch
- `recruiter-screener`, reframed as the client: a busy non-technical buyer deciding whether this is worth a call

```bash
python scripts/style_check.py data/artifacts/pitch/<slug>.md
```

Check by hand:

- Does the first sentence talk about them or about you? It must be them.
- Is there a number tied to their business, not just your technical result?
- Is the scope specific enough to say yes to?
- Is the price stated?
- Is there a risk-reduction option?

## Step 6: Log

```bash
python scripts/pipeline.py add --track freelance --company "<client>" --role "<engagement>" --status shortlisted
python scripts/pipeline.py artifact <id> --kind pitch --path <...>
python scripts/pipeline.py task <id> --kind follow_up --description "follow up on proposal" --due <date + 5 days>
```

The `freelance` track shares the pipeline, so `/follow-up` and `/pipeline` work on client proposals unchanged.

## Rules

- **Never promise an outcome you cannot deliver.** A job application that oversells costs an interview. A proposal that oversells costs a contract, a reference, and possibly a refund.
- Every proof claim traces to an evidence id, same as everywhere else.
- Never quote a price the user has not agreed to. Propose it and let them decide.
- Never work the problem for free beyond one observation. A full solution in the pitch is a solution they can take elsewhere.
- Be explicit about what is out of scope. Scope creep starts in the proposal.
- If the client's problem is not one the user can actually solve, say so.
