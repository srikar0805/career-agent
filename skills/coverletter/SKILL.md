---
name: coverletter
description: Write a cover letter under 200 words that opens with a hook instead of "I am applying for", maps each paragraph to a real need in the posting, and backs every claim with an evidence id. Use when the user wants a cover letter, letter of interest, or application note for a specific role.
trigger: /coverletter
---

# /coverletter

A cover letter that gets read. Under 200 words, hook first, every claim backed.

```
/coverletter "ML Engineer" Stripe
/coverletter --jd path/to/posting.txt
/coverletter --app 14
/coverletter --long                # 300 word cap, for academic or senior roles
```

## The premise

Most cover letters are not read. The ones that are read get about fifteen seconds, and the reader is deciding one thing: does this person understand what we actually need, or did they send us a template?

That means the letter has one job. Not to summarize the resume, which the reader already has. Not to express enthusiasm, which every applicant expresses. To demonstrate, in the first sentence, that the applicant understood the problem behind the posting.

Under 200 words is not a stylistic preference. It is the length at which a busy person finishes it.

## Bootstrap

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
```

Read `templates/style-rules.md` and `profile/voice.md`. Confirm `profile/evidence.yaml` exists, or send the user to `/career-setup`.

## Step 1: Research, in parallel

Dispatch both at once:

- `jd-analyst` on the posting. You need "WHY THIS ROLE EXISTS" and the ranked must-haves.
- `company-researcher` on the company. You need one specific, sourced, recent fact.

The letter cannot be written well without both. If `company-researcher` returns nothing usable, that changes the strategy rather than blocking it: lead with the candidate's own work instead of the company's, and say so to the user.

## Step 2: Pick the hook

The opening sentence is most of the letter. It must be a sentence that could not be sent to any other company.

**Hooks that work**, roughly in order of strength:

1. **A specific observation about their problem, connected to something you have done.** "Your engineering blog post on cutting cold-start latency described the same tradeoff I hit rebuilding an inference path last summer, and I landed somewhere different."
2. **A relevant result, stated flatly, no preamble.** "I cut p99 inference latency from 840ms to 210ms on a system serving 12M records a day. Your posting says the serving stack is the bottleneck."
3. **A genuine question about a public technical decision they made.** Only if you can then say something intelligent about it.
4. **A concrete connection.** A person you both know who suggested you write, a talk of theirs you attended, an open source contribution to their project.

**Hooks that fail**, all banned by `templates/style-rules.md`: anything beginning "I am writing to apply", "I am excited about", "I came across your posting", "As a recent graduate", or a restatement of the job title back at them.

**The test**: if the first sentence could be pasted into a letter to a different company by changing one proper noun, it is not a hook. Rewrite it.

## Step 3: Structure

Four paragraphs, 200 words total.

**Paragraph 1, the hook.** One or two sentences. No throat-clearing. Do not name the role in the first sentence; the reader knows which role you applied to.

**Paragraph 2, the strongest proof.** One specific thing you did that maps to their top-ranked must-have. Numbers. One evidence id. This paragraph is why they keep reading.

**Paragraph 3, the second angle.** Either a second must-have, or the thing that makes you unusual for this role. If the `jd-analyst` found an unstated pain, this is where you address it. Still backed by evidence.

**Paragraph 4, the close.** Confident, short, no supplication. State the next step. Do not thank them for their time, do not say you look forward to hearing from them, do not apologize for anything.

If the candidate has a real gap against a stated requirement, address it in one clause in paragraph 3 rather than hoping it goes unnoticed. Directness reads as confidence; an unexplained gap reads as an oversight.

## Step 4: Cut

Write the draft, then do this before showing anyone:

1. **Delete the first sentence.** Check whether anything was lost. Usually it was throat-clearing and the letter now opens better.
2. **Delete every adverb.** Then put back only the ones whose absence changes the meaning. There will be almost none.
3. **Delete every sentence that summarizes the resume.** They have the resume.
4. **Delete every sentence about how much you want the role.** Wanting it is assumed by the act of applying.
5. **Count.** Over 200 words, cut the weakest paragraph entirely rather than trimming all four evenly. An amputation reads better than a uniform squeeze.

## Step 5: Review

Dispatch in parallel:

- `fact-checker` on the draft
- `resume-judge` on the draft, using the alternate dimensions at the bottom of `templates/rubric-resume.md`: Hook strength, Pain mapping, Ask clarity, plus Vocabulary mirroring, Specificity, Authenticity
- `recruiter-screener` on the draft

Enforce the cap mechanically:

```bash
python scripts/style_check.py data/artifacts/<slug>/cover-letter.md --max-words 200
```

The word cap is a hard constraint. A 214-word letter is not finished. Revise up to three passes on the same priority order as `/resume-rewrite`: hallucinations first, then judge blocking items, then screener reasons.

## Step 6: Ship

```bash
python scripts/render.py data/artifacts/<slug>/cover-letter.md \
  -o data/artifacts/<slug>/cover-letter.docx --style letter
python scripts/pipeline.py artifact <app-id> --kind cover_letter \
  --path data/artifacts/<slug>/cover-letter.docx --evidence "EV-..."
```

Show the user the letter in full, the word count, the sourced fact the hook rests on with its URL so they can verify it, and the evidence id behind each claim.

## Rules

- **The hook fact must be real and sourced.** A fabricated detail about a company, in a letter sent to someone who works there, is the worst possible failure mode of this entire repo.
- Under 200 words unless `--long`. No exceptions for "this one really needed more."
- Never restate the resume.
- Never open with the banned phrases. The style checker enforces it and you should not need the checker to catch it.
- Never grovel. Run the supplicant test in `templates/style-rules.md`.
- Contractions are good here. This is prose a person reads, not a resume.
- If the research turned up nothing and the candidate has no real connection to this company, say so. A competent generic letter honestly labeled is more useful than a fake-specific one.
