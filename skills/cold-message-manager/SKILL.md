---
name: cold-message-manager
description: Write a cold LinkedIn or email message to a hiring manager, under 80 words, opening with a specific verifiable insight about their business and ending with a frictionless ask. Checks the LinkedIn connection graph for a warm intro first. Use for cold outreach to hiring managers, recruiters, or anyone at a target company.
trigger: /cold-message-manager
---

# /cold-message-manager

A cold message a hiring manager actually replies to. Under 80 words.

```
/cold-message-manager Stripe "ML Engineer"
/cold-message-manager Stripe "ML Engineer" --to "Jane Roe"
/cold-message-manager --app 14
/cold-message-manager --email          # email instead of LinkedIn, allows a subject line
```

## Before writing anything: check for a warm path

```bash
python scripts/pipeline.py who <company>
```

If the user has a first-degree LinkedIn connection at this company, **stop and say so**. A warm introduction converts several times better than the best cold message ever written, and sending a cold message to a stranger at a company where you know someone is a strategic mistake.

In that case, write the intro request to the connection instead, which is a different and much easier message: it is short, it is to someone who already knows you, and the ask is small.

Only proceed with cold outreach when there is genuinely no warm path.

## Bootstrap

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
```

Read `templates/style-rules.md` and `profile/voice.md`.

Check whether this company has been contacted before:

```bash
python scripts/pipeline.py list --company <company>
python scripts/pipeline.py show <app-id>
```

If a message was already sent, this is a follow-up, not a cold message. Use `/follow-up` instead.

## Why 80 words

A hiring manager sees your message as three lines in a LinkedIn preview on a phone. They decide whether to open it from those three lines. Anything past 80 words is not read before the decision to reply is already made, so it exists only to make the message look longer, which is a reason not to open it.

The constraint is also a forcing function. At 80 words there is no room for a paragraph about how much you admire the company, which is exactly the paragraph you should not write.

## Step 1: Find the insight

Dispatch `company-researcher`. You need one fact that is recent, specific, connectable, and sourced with a URL.

If a specific person is named, research their public professional work too: recent talks, posts, papers, shipped projects. A message that references what *they* built outperforms one that references what their company announced.

**If nothing usable comes back**, do not invent something. Tell the user the research came up empty and offer the alternative: a short message that leads with the candidate's own relevant result instead. It is a weaker opening but an honest one, and it will not blow up in an interview.

## Step 2: The four parts

**1. The insight, 1 sentence.** Specific to them. Demonstrates you did work before writing. Never flattery. Never "I have been following your company."

**2. The bridge, 1 sentence.** Connect that insight to something you have actually done. This is where the evidence id goes. The bridge is the hardest sentence in the message and it is what separates a real cold message from a mail merge.

**3. The proof, 1 sentence.** One number. The single most relevant thing you have done. Not a summary of your background.

**4. The ask, 1 sentence.** Frictionless. The recipient should be able to say yes in four words.

Good asks: "Worth a 15 minute call Thursday?" "Open to me sending a short writeup?" "Is the team still hiring for this?"

Bad asks: "I would love to connect and learn more about opportunities." "Let me know if you would like to chat." "I would welcome the chance to discuss how my background aligns." Each of these makes the recipient do the work of deciding what happens next, so nothing happens next.

## Step 3: Three variants

Generate three, at genuinely different angles:

- **A: insight-led.** Opens with the observation about their business.
- **B: result-led.** Opens with your strongest number, then connects it to their problem.
- **C: question-led.** Opens with a real technical question about a decision they made publicly. Highest risk, highest reply rate when the question is good, and actively bad when the question is generic.

Then dispatch `recruiter-screener` on all three and have it pick the winner from the recipient's perspective. Show the user all three anyway, with the reasoning, since they know things about the relationship that you do not.

## Step 4: Enforce

```bash
python scripts/style_check.py data/artifacts/<slug>/cold-message.md --max-words 80
```

Also verify by hand:

- Does sentence one contain a fact that could not apply to another company?
- Is there a number in it?
- Can the recipient say yes in four words?
- Does it pass the supplicant test in `templates/style-rules.md`?
- Is every factual claim traceable? Dispatch `fact-checker` if any claim about the candidate is non-trivial.

For LinkedIn connection requests specifically, the note field caps at 300 characters, which is tighter than 80 words. Say which limit you wrote to.

## Step 5: Log it

```bash
python scripts/pipeline.py contact --name "<name>" --title "<title>" --company "<company>" --relationship cold
python scripts/pipeline.py log <app-id> --kind cold_message --direction out \
  --channel linkedin --summary "cold message to <name>" --body-file data/artifacts/<slug>/cold-message.md
python scripts/pipeline.py task <app-id> --kind follow_up \
  --description "follow up on cold message to <name>" --due <date + 7 days>
```

Storing the body matters: `/follow-up` reads it so the follow-up does not repeat what was already said.

## Step 6: Report

Give the user the winning message ready to paste, the two alternates, the sourced fact with its URL so they can confirm it before sending, the word count, and the date the follow-up task is set for.

**You do not send anything.** Every message stops at the draft. The user sends it.

## Rules

- **Never fabricate a company fact, a mutual connection, or a conversation.** The recipient works there and will know.
- **Never send to a stranger when a warm path exists.** Check first, every time.
- 80 words. A 90-word message is not finished.
- No flattery. No "I hope this finds you well." No apologizing for reaching out.
- Peer to peer register. The candidate is offering something useful, not requesting a favor.
- One ask. A message with two asks gets neither.
- If the company has already rejected the candidate for this role, say so and recommend against messaging.
