---
name: career
description: Career search orchestrator. Reads pipeline state, tells the user what to do next, and routes to the right specialized skill. Use when the user asks about their job search generally, wants to know what to work on, says they are stuck, or does not know which command they need.
trigger: /career
---

# /career

The front door. Knows where the search stands and what to do next.

```
/career                          # status plus the next action
/career "I have an interview at Stripe Thursday"
/career "nobody is responding"
/career weekly                   # review the week, replan
```

## What this does

Every other skill in this repo does one job well. This one figures out which job needs doing, then hands off.

It is also the skill that notices things the user will not: an application that has been silent for three weeks, a follow-up that is four days overdue, a conversion rate that says the resume is fine but the targeting is wrong.

## Step 1: Read the state

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate

python scripts/pipeline.py stats
python scripts/pipeline.py due --days 2
python scripts/pipeline.py stale --days 10
python scripts/pipeline.py list --open
python connectors/build_evidence.py stats
```

If `profile/evidence.yaml` does not exist, the answer is `/career-setup` and nothing else. Say so and stop.

## Step 2: Diagnose

Read the numbers before saying anything. The funnel tells you where the problem is, and the fix is completely different at each stage.

| What the data shows | The actual problem | The fix |
|---|---|---|
| Few applications sent | Volume, or targeting paralysis | `/target-app-strategy` |
| Many applications, almost no screens | The resume is not surviving the screen, or the targeting is wrong | `/resume-rewrite`, then check fit honestly |
| Screens happen, no technical rounds | The story or the fit narrative is not landing | `/interview-prep`, work the two-minute story |
| Technical rounds, no offers | Depth under follow-up | `/interview-prep --drill` |
| Applications sent, total silence | No warm paths being used | `/target-app-strategy`, prioritize the connection graph |
| Things are stale | Follow-ups are not happening | `/follow-up --due` |

**Be specific about which one it is, and say why the data supports it.** "You have 23 applications and 1 screen. That is a 4% response rate, and the usual cause at that ratio is the resume, not the volume." A vague "keep going" is worse than nothing.

If there is not enough data to diagnose, say that too. Four applications is not a sample.

## Step 3: Answer or route

If the user asked something specific, answer it, then route.

| They said | Route to |
|---|---|
| Interview coming up | `/interview-prep` |
| Found a role they want | `/apply` |
| Need a resume | `/resume-rewrite` |
| Need a cover letter | `/coverletter` |
| Want to reach a hiring manager | `/cold-message-manager` |
| Silence from a company | `/follow-up` |
| Do not know where to start | `/target-app-strategy` |
| Want to find roles | `/job-hunt` |
| LinkedIn is not working | `/linkedin-profile` |
| Grad school or a professor | `/sop` |
| Freelance or client work | `/pitch` |
| Want to see everything | `/pipeline` |

Do not just name the command. Invoke it, with the arguments already filled in from pipeline state. The user should not have to restate what you already know.

## Step 4: The one next action

End with exactly one thing to do next, sized to under an hour.

Not a list of five. A job search stalls on decision fatigue more than on effort, and a person who opens this and sees six priorities does none of them.

Pick using this order:

1. Anything time-critical. An interview in 48 hours beats everything.
2. Anything overdue. A follow-up four days late is losing value every day.
3. The highest-leverage unblocked action. Usually a warm intro, since those convert far better than anything else available.
4. The diagnosed bottleneck from Step 2.

## Weekly review

With `weekly`, do the honest version:

- What was sent, what came back, real conversion by stage
- What changed since last week, in numbers
- What is not working, named plainly
- One thing to change, not five
- Replan the coming week, writing tasks into the pipeline

Compare against the user's own history rather than any external benchmark. Their trend is the only meaningful signal.

## Rules

- **Lead with data, not encouragement.** "You have 3 stale applications and a follow-up due today" is useful. "You are doing great, keep it up" is not.
- **One next action.** Always exactly one.
- **Name the bottleneck plainly**, including when it is that the user is targeting roles they are not currently competitive for. That is a hard thing to hear and an expensive thing not to know.
- Never invent progress. If the pipeline is empty, say it is empty.
- If the user is discouraged, be useful rather than reassuring. The most reassuring thing available is a correct diagnosis and a small next step.
