# Resume scoring rubric

Used by the `resume-judge` agent. Score each dimension 0 to 10 against the written anchors below, then compute the weighted total.

**Why the anchors matter.** An LLM asked to "score this resume out of 100" produces a different number every run and drifts upward when it sees its own previous draft. Anchoring each score band to concrete example text makes the score reproducible. Judge against the anchors, not against your impression.

**Rules for the judge:**
1. You are scoring one draft in isolation. You have not seen a previous version. Do not ask about one.
2. Quote the exact line you are scoring. A score without a quote is not a score.
3. Default down. If a bullet sits between two bands, give it the lower one.
4. Every dimension gets a specific rewrite suggestion, not "make it stronger."

**Pass threshold: 80 weighted, with no single dimension below 6.**
A 92 with a 4 in Evidence Density is a fail. One rotten dimension sinks the document.

---

## Dimension 1: Evidence density (weight 25)

Does every bullet make a measurable claim, or does it describe a job description?

| Score | Anchor |
|---|---|
| 0-2 | Bullets restate duties. "Responsible for maintaining the data pipeline and working with stakeholders." Nothing happened. Nothing was measured. |
| 3-5 | Action verbs but no numbers. "Rebuilt the data pipeline to improve reliability." Something happened, but nobody can tell how much. |
| 6-7 | Most bullets carry a number, some do not. "Rebuilt the ingestion pipeline, cutting failures by 60%" next to "Collaborated with the platform team on tooling." |
| 8-9 | Every bullet carries a number or an explicit scope. Numbers are outcomes, not activity. "Cut pipeline failure rate from 12% to 4% across 40 daily jobs." |
| 10 | Every bullet is an outcome with a baseline and a result, and the numbers escalate in significance down the section. Reader finishes knowing exactly what this person moved. |

**Activity numbers do not count.** "Wrote 5,000 lines of code" and "attended 30 meetings" are volume, not outcome. Score them as if the number were absent.

---

## Dimension 2: Relevance ranking (weight 20)

Is the most job-relevant content in the most-read position?

| Score | Anchor |
|---|---|
| 0-2 | Ordering is purely chronological with no regard for the target role. A backend job posting, and the top bullet is about a design system. |
| 3-5 | Relevant content is present but buried. The one bullet that proves the core requirement is fourth in the second role. |
| 6-7 | Top role leads with relevant work, but within-role bullet ordering is arbitrary. |
| 8-9 | Within every role, the bullet that best proves a stated requirement leads. Irrelevant work is cut, not shrunk. |
| 10 | The document reads as though it was written for this posting only. Every retained line maps to a ranked requirement, and the requirement it maps to is obvious. |

**Cutting scores higher than shrinking.** A resume that dropped three irrelevant bullets outscores one that kept them at one line each.

---

## Dimension 3: Vocabulary mirroring (weight 15)

Does the resume use the posting's words for the same concepts?

| Score | Anchor |
|---|---|
| 0-2 | Different vocabulary throughout. Posting says "distributed systems", resume says "big backend stuff." Keyword match is near zero. |
| 3-5 | Some overlap by coincidence. No evidence anyone read the posting. |
| 6-7 | Core technical keywords present, but the framing language differs. Posting emphasizes "reliability", resume talks only about "features." |
| 8-9 | Required skills appear with the posting's exact wording, placed inside real achievement bullets rather than a keyword dump. |
| 10 | Terminology matches, and the resume also mirrors the posting's implied priorities. If the posting mentions on-call three times, this resume shows on-call ownership. |

**Keyword stuffing scores 0, not 10.** A skills section listing 40 technologies with no bullet backing any of them is a fail on this dimension and a fail on honesty. Every keyword must be load-bearing somewhere.

---

## Dimension 4: The six-second zone (weight 15)

Top third of page one: name, headline, first role, first two bullets. That is what actually gets read before the accept or reject.

| Score | Anchor |
|---|---|
| 0-2 | Top third is contact details, a generic objective, and an education entry. Zero proof of capability above the fold. |
| 3-5 | A summary paragraph of adjectives. "Motivated engineer with strong problem solving skills." Reader learns nothing and moves on. |
| 6-7 | First role and title are relevant, but the opening bullet is the weakest one in the section. |
| 8-9 | Opening bullet is the single strongest, most job-relevant achievement in the document, with a number in it. |
| 10 | A reader who stops after six seconds already knows the role fit, the seniority, and one specific impressive thing. Everything below is confirmation. |

---

## Dimension 5: Specificity (weight 15)

Concrete nouns and real systems, or abstractions and adverbs?

| Score | Anchor |
|---|---|
| 0-2 | Pure abstraction. "Improved system performance and enhanced user experience through various optimizations." |
| 3-5 | Named the domain but not the thing. "Optimized the backend services for better latency." |
| 6-7 | Named technologies, vague on the change. "Used Redis and Postgres to improve API response times." |
| 8-9 | Names the system, the change, and the mechanism. "Replaced per-request Postgres lookups with a Redis read-through cache, cutting p99 from 840ms to 210ms." |
| 10 | As above, plus the constraint that made it hard. "...under a hard 200ms SLA, with no cache-invalidation regressions across 3 dependent services." |

Adverbs are a tell. "Significantly", "dramatically", "greatly" almost always mark a missing number. Deduct for each one.

---

## Dimension 6: Authenticity (weight 10)

Does this read as written by a person, and specifically by this person?

| Score | Anchor |
|---|---|
| 0-2 | Reads as generated. Uniform sentence length, banned phrases present, em dashes, "passionate about", perfectly parallel structure in every bullet. A recruiter discards it. |
| 3-5 | No banned phrases, but the rhythm is machine-flat. Every bullet is 16 to 19 words with identical grammatical shape. |
| 6-7 | Human enough, but generic. Could belong to any of two hundred candidates with the same background. |
| 8-9 | Specific details only this person would know. Bullet length varies with the weight of the content. Voice matches `profile/voice.md`. |
| 10 | Has a point of view. The reader forms an impression of how this person thinks about problems, not just what they shipped. |

**Automatic 0 on this dimension** if `scripts/style_check.py` fails. Run it before scoring.

---

## Scoring output format

Return exactly this structure:

```
SCORE: <weighted total>/100    VERDICT: PASS | FAIL

D1 Evidence density    <n>/10  (w25)
D2 Relevance ranking   <n>/10  (w20)
D3 Vocabulary mirror   <n>/10  (w15)
D4 Six-second zone     <n>/10  (w15)
D5 Specificity         <n>/10  (w15)
D6 Authenticity        <n>/10  (w10)

BLOCKING (fix before this can ship):
  1. [D<n>] "<exact quoted line>"
     Problem: <one sentence>
     Rewrite: "<the actual replacement line>"

NON-BLOCKING (would raise the score):
  1. ...

STRONGEST LINE: "<quote>"  (keep this, it is doing the work)
WEAKEST LINE:   "<quote>"  (cut or rewrite)
```

Every BLOCKING item must include a literal replacement line, written out. "Add a metric here" is not a rewrite. If the metric is unknown, write the line with a `[NEED: throughput before/after]` placeholder so the user knows exactly which number to supply.

---

## Applying this to other artifacts

Cover letters, cold messages, and SoPs reuse D3, D5, and D6 unchanged. Swap D1, D2, and D4 for:

- **Hook strength** (weight 25): does sentence one earn sentence two? An opener that could be sent to any company scores 0.
- **Pain mapping** (weight 20): does each paragraph answer a real need stated or implied in the posting?
- **Ask clarity** (weight 15): is the next step specific, small, and easy to say yes to? "Let me know if you would like to chat" scores 3. "Worth a 15 minute call Thursday or Friday?" scores 9.
