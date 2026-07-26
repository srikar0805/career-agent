---
name: follow-up
description: Write a follow-up message after an application, interview, or networking call that restates fit in one sentence, adds one new piece of value, and prompts a clear next step. Reads the pipeline history so it never repeats what was already said. Use for following up, checking in, nudging, or thanking after any career interaction.
trigger: /follow-up
---

# /follow-up

The message that reopens a conversation without sounding desperate.

```
/follow-up 14                              # by pipeline application id
/follow-up interview "Jane Roe" Stripe
/follow-up application Anthropic
/follow-up --due                           # everything due today, one at a time
```

## Why most follow-ups fail

They contain no new information. "I wanted to check in on my application" gives the recipient nothing to respond to, so the easiest reply is no reply. Worse, it transfers the work of the interaction onto them: they now have to look up your status, decide what to say, and write it.

A follow-up that works does the opposite. It carries one thing the recipient did not have before, and it makes replying easier than not replying.

The desperation signal is not frequency. It is emptiness. A message every ten days that each time adds something real reads as diligent. Two messages that both say "just checking in" read as anxious.

## Bootstrap

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
```

## Step 1: Read the history. This is the whole skill.

```bash
python scripts/pipeline.py show <app-id>
```

This returns every prior interaction with its stored body text. Read all of it.

You are looking for:

- **What was already said.** Never repeat a point from a previous message. If the cold message already led with the latency number, the follow-up cannot.
- **What they said back.** Any reply changes the register completely. A recipient who engaged is a warm contact, not a cold one.
- **How long it has been.** Drives both timing advice and tone.
- **What stage this is.** A post-interview follow-up and a post-application nudge are different messages with different goals.
- **Anything promised.** If the candidate said they would send a writeup, the follow-up is that writeup arriving, which is the easiest and best follow-up there is.

If there is no history in the pipeline, ask the user what happened rather than guessing. A follow-up that misremembers the interaction is worse than none.

## Step 2: Timing

Check the elapsed time and give an honest recommendation, including "do not send this yet."

| Situation | Send after | Notes |
|---|---|---|
| Post-interview thank you | Same day, within 24 hours | Non-negotiable. Late reads as an afterthought. |
| After an interview, no decision communicated | 5 to 7 business days past their stated timeline | If they gave a date, wait until after it. Following up early signals you were not listening. |
| Application, no response | 7 to 10 days | Once. A second nudge on a silent application is noise. |
| Cold message, no response | 7 days, once more, then stop | Two attempts is the ceiling. Three is a pattern the recipient notices. |
| Networking call | 24 to 48 hours | With something concrete from the conversation. |
| Post-rejection | 1 to 2 weeks | Only if genuinely worth staying in touch. Short, no argument about the decision. |

If it is too early, say so and set the task instead:

```bash
python scripts/pipeline.py task <app-id> --kind follow_up --description "..." --due <date>
```

## Step 3: The three parts

**1. Fit, in one sentence.** Not a summary of your candidacy. One line, ideally referencing something specific from the last interaction, which proves you were listening. "The on-call ownership piece we talked about is the part I have actually done."

**2. One new piece of value.** This is the part that makes it a message worth sending. Options, roughly best first:

- Something you built or wrote since the conversation, especially if prompted by it
- A concrete answer to a question you fumbled in the interview. Interviewers respect this a great deal; it shows you kept thinking.
- A relevant article, tool, or approach that speaks to a problem they described
- A genuinely new result from your own work
- A relevant update in your situation, such as another offer, handled carefully

If you cannot find one new thing, **do not send the message.** Say that to the user plainly, and suggest what would create something worth sending.

**3. A clear next step.** Specific and small. "Should I send that writeup?" "Is the role still open?" "Worth a short call before your Friday deadline?"

Never "let me know if you have any updates", which asks them to do the work.

## Step 4: Calibrate the register

**After an interview.** Warm, specific, short. Reference an actual moment. Answer the question you did not answer well. Under 150 words.

**On a silent application.** Brief, low pressure, one new thing, easy out. Under 100 words. Assume they are busy rather than uninterested, and write as though that is obviously true.

**On a silent cold message.** Shorter than the original. Do not resend the original. New angle, new value, and an explicit acknowledgment that this is the last one. "I will leave it here, but if the team is still looking, my writeup on X is at the link."

**After a networking call.** Reference something specific they said. Deliver anything you promised. No ask at all, or a very small one. This message is about being someone worth remembering, not about extracting a referral.

**After a rejection.** Very short. Thank them without groveling, do not relitigate the decision, and leave a door open only if you would genuinely want to walk through it. This is the message that occasionally produces a role six months later, and it only works when it is sincere.

**With a competing offer.** Factual, no ultimatum, a real deadline. "I have an offer with a decision due the 14th. I would rather be at your company, so I wanted to give you the chance to weigh in." Never bluff about an offer that does not exist.

## Step 5: Check

```bash
python scripts/style_check.py data/artifacts/<slug>/follow-up.md --max-words 150
```

Then verify by hand:

- Does this repeat anything from a previous message? Compare against the stored bodies. If yes, rewrite.
- Is there exactly one new piece of value, and is it real?
- Can they reply in one line?
- Does it pass the supplicant test? No apologizing for following up. No "I know you are busy." No "I hope I am not bothering you."

Dispatch `fact-checker` if it contains any new claim about the candidate.

## Step 6: Log

```bash
python scripts/pipeline.py log <app-id> --kind follow_up --direction out \
  --summary "<one line>" --body-file data/artifacts/<slug>/follow-up.md
python scripts/pipeline.py task <app-id> --kind follow_up --description "<next>" --due <date>
```

Storing the body is what makes the *next* follow-up possible without repetition.

## Step 7: Report

The message ready to send, the word count, what new value it carries, what you deliberately did not repeat and where that came from, when to send it, and what the next scheduled touch is.

**You do not send it.** Drafts only.

## Rules

- **Never send an empty follow-up.** No new value means no message. Say so rather than producing filler.
- **Never repeat a prior point.** The pipeline history exists so you can check.
- Never guess at what happened in an interaction you have no record of. Ask.
- Never bluff a competing offer, a deadline, or another company's interest.
- Two attempts maximum on anything cold. Then stop, and tell the user to stop.
- Shorter than the message before it, every time.
