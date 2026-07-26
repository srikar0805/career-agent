---
name: interview-prep
description: Build an interview prep pack for a specific role and company. Derives the 8 most likely questions from the actual posting and company research, builds each answer from a real STAR record in the evidence bank, stress-tests every answer against three interviewer lenses, and supplies 3 strategic questions to ask. Use when the user has an interview coming up.
trigger: /interview-prep
---

# /interview-prep

Prep for a specific interview at a specific company. Not a generic question list.

```
/interview-prep "ML Engineer" Stripe
/interview-prep --app 14
/interview-prep --app 14 --stage onsite       # screen | technical | onsite | final
/interview-prep --drill                        # interactive mock, one question at a time
```

## What this does that a question list does not

A list of common interview questions is freely available and nearly useless, because the answers are the hard part and the follow-ups are harder still.

This produces answers built from the user's actual evidence bank, then attacks each one from three independent interviewer perspectives and reports **which follow-up the user cannot currently answer**. That last item is the most valuable output here. A candidate who knows exactly where their story is thin can either shore it up or choose a different story. A candidate who rehearsed a smooth answer and never considered "how did you measure that?" is in worse shape than one who did not prepare, because they will be fluent for ninety seconds and then visibly unravel.

## Bootstrap

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
python connectors/build_evidence.py stats
```

Check the STAR coverage number. If few atoms have STAR records, most answers will be thin, so say that up front and offer to fill the gaps first.

Read `profile/evidence.yaml`, `profile/narrative.md`, and `templates/style-rules.md`.

Pull the history:

```bash
python scripts/pipeline.py show <app-id>
```

If a tailored resume was generated for this role, read it and its `trace.md`. **The interviewer is holding that resume.** Every claim on it is a question they may ask, and the prep must cover all of them.

## Step 1: Research, in parallel

Dispatch at once:

- `jd-analyst` on the posting. You need the ranked must-haves and "WHY THIS ROLE EXISTS", because interviewers probe the thing they are actually worried about.
- `company-researcher` on the company. You need their technical context and recent work, which drives both the likely technical questions and the questions worth asking back.

## Step 2: Derive the eight questions

Not from a generic list. Derive them:

- **Two or three from the ranked must-haves.** For each top requirement, what question would verify it? That is a question they will ask.
- **One or two from the resume you sent.** The most surprising or strongest claim on it invites a probe.
- **One from the role's implied pain.** If `jd-analyst` says the team is drowning in technical debt, expect a question about working in a messy codebase.
- **One or two behavioral,** chosen for this company and level rather than at random. Conflict, failure, ownership, ambiguity.
- **One about the candidate's specific vulnerability.** A gap against a stated requirement, a short tenure, a career pivot, a work authorization question. Prepare it rather than hoping it is skipped.

Adjust by stage: a recruiter screen is motivation, comp, logistics, and a two-minute background story. An onsite is depth and behavioral. A final round is judgment and scope.

## Step 3: Build and attack each answer

For each question, dispatch `interview-panel`. It builds the answer from an evidence id and attacks it from three lenses: hiring manager, peer engineer, bar raiser.

Run these in parallel across questions rather than sequentially.

For every answer, the output must include:

- The evidence id it is built from
- The STAR structure, with what the candidate specifically owned
- **Spoken runtime.** Candidates massively underestimate this. Anything over two minutes loses the room, and you should say so bluntly when an answer runs long.
- The follow-up each lens would ask
- The hardest follow-up, answered
- **Where the answer is exposed.** The specific follow-up the evidence bank cannot currently support.

## Step 4: The two-minute story

Every interview opens with some version of "tell me about yourself" and most candidates waste it on chronology.

Build one: where you are now, the one thing you have done that matters most for this role, and why this company specifically. Ninety seconds to two minutes spoken. It should end on a note that invites the interviewer's first real question, which means ending on the thing you most want to be asked about.

## Step 5: The three questions to ask

Questions that signal strategic thinking, meaning they could only be asked by someone who did real research and is evaluating the company rather than hoping to be chosen.

Good shapes:

- About a specific technical decision they made publicly. "Your blog post on moving off the monolith mentioned keeping the billing path. Is that still the plan?"
- About what success looks like in the role, in a way that reveals whether they have thought about it. "What would you want the person in this seat to have changed in six months?"
- About the actual problem behind the req. "The posting emphasizes reliability heavily. What is currently breaking?"
- About the team's biggest open disagreement. Reveals a great deal and interviewers enjoy answering it.

Banned: anything answerable from the careers page, anything about compensation at the wrong stage, and "what is the culture like."

Also prepare one question specifically for each interviewer type: recruiter, hiring manager, peer, skip-level.

## Step 6: The vulnerability drill

List every honest weakness in this candidacy for this specific role. For each, write the prepared response.

Rules for these:

- **Never deny a real gap.** Interviewers can tell, and the denial costs more than the gap.
- Acknowledge, then redirect to the closest real evidence, then state what you would do about it.
- Work authorization gets a plain, factual, unapologetic answer. State the status, state what it requires, move on. Hedging here reads as evasion on a topic where evasion is fatal.
- A career pivot needs a coherent one-sentence story, and `profile/narrative.md` should already hold it.

## Step 7: Deliver

Write to `data/artifacts/<slug>/interview-prep.md` and show the user:

1. The role, stage, and what the panel is likely optimizing for
2. The two-minute story, written out
3. Eight questions, each with framework, evidence id, runtime, follow-ups, and exposure
4. Three strategic questions plus per-interviewer variants
5. The vulnerability drill
6. **The top three exposures, collected in one place.** This is what to work on tonight.
7. Logistics: what to have open, what to bring, what to review immediately before

Log it:

```bash
python scripts/pipeline.py artifact <app-id> --kind interview_prep --path data/artifacts/<slug>/interview-prep.md
python scripts/pipeline.py task <app-id> --kind follow_up \
  --description "thank you note within 24h" --due <interview date>
```

## Drill mode

With `--drill`, run an interactive mock: ask one question, wait for the user's real answer, then respond as `interview-panel` with what each lens thought and the follow-up they would have asked. Do not move on until the answer holds. This is far more useful than reading prepared answers and should be recommended when there is time.

## Rules

- **Every answer comes from an evidence id.** An answer the user cannot defend under follow-up is worse than no answer.
- **Never invent a detail to make a story land better.** The user will repeat it in the room.
- **Say when a story is weak because the underlying experience is thin.** The fix is a different story, not better wording.
- Be blunt about runtime and about exposures. Encouragement here has a real cost.
- Prepare the honest answer to the question the user is dreading. That is the one that decides the interview.
