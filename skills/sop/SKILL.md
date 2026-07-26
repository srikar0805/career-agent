---
name: sop
description: Write a statement of purpose for a graduate program, or a cold research email to a professor grounded in their actual recent papers. Uses the research corpus and evidence bank. Use for grad school applications, PhD or MS statements, research outreach, or contacting faculty.
trigger: /sop
---

# /sop

Statements of purpose and research outreach that show you read the work.

```
/sop "MS Computer Science" "University of Missouri"
/sop --professor "Dong Xu" --school Mizzou     # cold research email
/sop --phd "Machine Learning" --school CMU
/sop --revise path/to/draft.docx
```

## Two different documents

**The statement of purpose** is read by a committee, quickly, alongside three hundred others. It answers: what do you want to work on, why are you prepared to work on it, and why here specifically. The last question is where almost every SoP fails, because "your program has excellent faculty" is what everyone writes.

**The cold email to a professor** is read by one person who receives many of these and deletes most unread. It succeeds only when it demonstrates, in the first two sentences, that you read their actual work. Not their bio, not their lab's homepage. A paper.

These need different drafts. Do not adapt one into the other.

## Bootstrap

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
```

Read `profile/evidence.yaml`, `profile/narrative.md`, `profile/voice.md`, and `templates/style-rules.md`.

The document scan already collected research and coursework material. Prior SoPs are especially useful here, both as voice samples and as a record of what has already been claimed:

```bash
python -c "
import json
d=json.load(open('data/raw/documents.json'))
for x in d['documents']:
    if x['kind'] in ('sop','paper','recommendation'):
        print(x['kind'], '|', x['name'])
"
```

Read the prior SoPs in full before writing anything.

## Step 1: Research the actual work

Dispatch `company-researcher`, pointed at the lab or the professor rather than a company.

For a professor, you need:

- Their **three to five most recent papers**, with the actual findings, not just titles
- What **open problem** the recent work leaves. This is the single most important thing you will find, because it is what a prospective student can speak to.
- Whether they are **currently taking students**, if that is public
- Their **current funding or project direction**, from lab pages and recent grants

Read the papers themselves, at least abstract, introduction, and conclusion. An email that cites a paper title is transparently a search result. An email that engages with the limitation stated in the conclusion is from someone who read it.

For a program, you need: the specific faculty whose work matches, the actual research groups, curriculum specifics, and anything that genuinely differentiates it. If the honest answer is that nothing does, the SoP should focus on faculty fit rather than manufacturing a reason.

## Step 2: The SoP

Roughly 800 to 1200 words unless the program states otherwise. Check the stated limit and honor it exactly.

**Opening, 1 paragraph.** A specific technical problem you care about and how you came to it. Concrete, ideally something you personally hit. Not "I have been fascinated by artificial intelligence since childhood", which is the most common opening in the stack and conveys nothing.

**Preparation, 2 to 3 paragraphs.** What you have actually done, from the evidence bank, framed as intellectual development rather than a resume in prose. The question a committee is answering is whether you can do research, so emphasize: what you did when the approach failed, what you chose not to do and why, what you learned that changed your direction. A project narrated as a sequence of decisions demonstrates research capability. The same project narrated as a list of technologies does not.

**Fit, 1 to 2 paragraphs.** The part that decides it. Name specific faculty and specific papers. Say what you would want to work on with them and why your preparation connects. This paragraph should be impossible to send to another school. If you could swap the school name and send it, rewrite it.

**Direction, 1 paragraph.** What you want to do after. Specific enough to show you have thought about it, not so specific that it reads as naive.

## Step 3: The cold email to a professor

Under 200 words. Structure:

1. **One sentence naming a specific finding or limitation in a recent paper of theirs.** With enough detail that it is clear you read it.
2. **One or two sentences connecting your own work to it.** From the evidence bank, with a real result. This is the bridge and it is the hardest part.
3. **One sentence on what you would want to do.** Concrete, and ideally something they would find interesting rather than something you find convenient.
4. **A small, clear ask.** "Are you taking students for Fall 2027?" Not "I would be grateful for any opportunity."

Attach a CV. Mention it in one clause, do not describe it.

Send from an academic address if one exists. Subject line should be specific: "Question about [paper topic], prospective MS applicant" beats "Prospective Student Inquiry".

## Step 4: Review

Dispatch in parallel:

- `fact-checker` on the draft. Every claim about your own work traces to an evidence id.
- `resume-judge` using the alternate dimensions, with Hook strength on the opening
- `recruiter-screener`, reframed as an admissions committee member reading their two hundredth application. Same adversarial posture, same reject-by-default stance.

```bash
python scripts/style_check.py data/artifacts/sop/<slug>.md --max-words <limit>
```

Then check by hand:

- Could this be sent to a different school by changing the name? If yes, the fit paragraph failed.
- Does it cite specific papers, or just faculty names?
- Does the preparation section show research thinking, or list technologies?
- Is there a single sentence of unearned grandiosity? Cut it.

## Step 5: Deliver

The document, the word count against the stated limit, the papers cited with links so the user can verify you represented them correctly, evidence ids used, and what remains weak.

For a professor email, also give the subject line and note what to attach.

```bash
python scripts/pipeline.py add --track grad --company "<school>" --role "<program>" --status shortlisted
python scripts/pipeline.py artifact <id> --kind sop --path <...>
```

The `grad` track keeps academic applications in the same pipeline with the same follow-up mechanics, and `/follow-up` works on them unchanged.

## Rules

- **Never cite a paper you have not read.** A professor will notice within one sentence, and the recovery is impossible.
- **Never misrepresent a finding.** Same reason, worse consequence.
- Never claim research experience the evidence bank does not support.
- Honor the stated word limit exactly. Committees notice.
- No grandiosity. "I hope to revolutionize the field" reads as inexperience to every person who will read it.
- If the fit is genuinely weak, say so. Applying to a program with no faculty match is expensive and usually futile, and knowing that early is worth more than a well-written statement.
