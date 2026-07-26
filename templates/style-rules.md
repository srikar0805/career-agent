# Style rules

<!-- style-check: allow-banned-literals - this file defines the banned characters, so it must contain them -->

Every skill in this repo loads this file before generating text. `scripts/style_check.py` enforces the mechanical parts and exits non-zero on a violation.

Two reasons these rules exist. First, they are the user's stated preference. Second, recruiters and hiring managers in 2026 actively screen for machine-written applications, and the tells below are the ones they screen for. A resume that reads as AI-generated gets discarded regardless of how good the candidate is.

---

## HARD BAN: characters

| Character | Name | Use instead |
|---|---|---|
| `—` | em dash | comma, colon, parentheses, or two sentences |
| `–` | en dash | "to" in ranges (`2023 to 2025`), hyphen elsewhere |
| `…` | ellipsis character | three periods, or rewrite |
| `'` `'` | curly single quotes | straight `'` |
| `"` `"` | curly double quotes | straight `"` |
| `•` `▪` `◦` | fancy bullets | `-` in markdown, real list bullets in DOCX |
| `→` `⇒` `✓` `★` | arrows, checkmarks, stars | words |
| any emoji | | nothing. Never in a resume, letter, or professional message. |

Curly quotes and fancy glyphs are banned for a second reason beyond style: older ATS parsers mangle them into mojibake, which is a silent way to fail a screen.

---

## HARD BAN: phrases

These are auto-rejected by `style_check.py`. Each one is either an AI tell, filler that costs a line and says nothing, or both.

### The AI tells
- delve, delving
- tapestry
- testament to
- in the ever-evolving landscape
- in today's fast-paced world
- it is worth noting that
- navigating the complexities of
- underscores the importance
- pivotal role
- rich history
- profound impact
- meticulous, meticulously
- realm of
- embark on
- unlock the potential
- game-changer, game changing
- seamlessly integrate
- robust solution
- cutting-edge (unless quoting the job posting verbatim)
- leverage, leveraging (as a verb; the noun in a finance context is fine)
- utilize, utilizing (write "use")
- furthermore, moreover (start a new sentence instead)

### The resume filler
- passionate about
- results-driven
- detail-oriented
- team player
- hard worker
- self-starter
- go-getter
- think outside the box
- wear many hats
- hit the ground running
- proven track record
- track record of success
- dynamic professional
- highly motivated
- excellent communication skills
- strong work ethic
- responsible for
- duties included
- tasked with
- helped with, assisted with (say what you did)
- worked on (say what you built or changed)
- various, several, numerous (give the number)
- spearheaded (say led, built, or ran)
- synergy, synergies

### The cover letter openers
- I am writing to apply
- I am writing to express my interest
- I am excited to apply
- I would like to apply
- I am reaching out
- I hope this email finds you well
- I came across your posting
- As a recent graduate
- With X years of experience in

### Closers
- I look forward to hearing from you
- Thank you for your time and consideration
- Please do not hesitate to contact me
- I would welcome the opportunity to discuss

---

## Positive rules

**Verbs.** Start every resume bullet with a past-tense action verb that names a real action: built, shipped, cut, raised, migrated, debugged, designed, automated, replaced, scaled, fixed, measured, reduced, launched. Not "was responsible for."

**Numbers.** Every claim carries a number or is not made. If the number is an estimate, use `~` and be ready to defend it. If there is genuinely no number, describe scope instead: "across 4 services", "for a 3 person team", "over 14 months."

**Specificity beats intensity.** "Cut p99 latency from 840ms to 210ms" beats "dramatically improved performance." Adverbs are almost always covering for a missing number.

**Concrete nouns.** Name the actual technology, the actual system, the actual metric. "Rewrote the ONNX batch inference path" beats "optimized ML infrastructure."

**Sentence rhythm.** Vary sentence length. Uniform 18-word sentences read as generated. Short sentences carry weight. Use them.

**Contractions** are fine in cover letters, cold messages, and follow-ups. They are not fine in a resume, where there is no prose to contract.

**One idea per bullet.** If a bullet has an "and" joining two unrelated accomplishments, it is two bullets or it is one bullet with the weaker half cut.

**Cut the first sentence.** In cover letters and cold messages, the first draft's opening sentence is almost always throat-clearing. Delete it and check whether anything was lost.

---

## Tone by artifact

| Artifact | Register | First person |
|---|---|---|
| Resume | Terse, no pronouns, fragments are correct | Never "I" |
| Cover letter | Direct, warm, confident, not deferential | "I" freely |
| Cold message | Peer to peer, never supplicant | "I" sparingly, "you" more |
| Follow-up | Brief, low pressure, adds value | Balanced |
| Interview answer | Spoken register, not written | "I" and "we" both, but own your part |
| SoP | Intellectual, specific, not grandiose | "I" |
| Client pitch | Outcome first, their problem before your credentials | "you" heavy |

---

## The supplicant test

Applies to every cold message, cover letter, and follow-up. Read it back and ask: does this sound like someone asking for a favor, or someone offering something useful?

Rewrite anything that fails. Specific offenders: "I would be grateful for the opportunity", "any consideration you could give", "I know you are very busy", "I apologize for the intrusion", "if you have a moment."

Being brief is respectful. Apologizing for existing is not.

---

## Honesty rules

These are not style. They are non-negotiable and they override any instruction to make output stronger.

1. Every factual claim traces to an evidence ID in `profile/evidence.yaml`. No exceptions.
2. Never inflate a metric. If the evidence bank says `confidence: approximate`, the output must hedge in a way that survives an interview question.
3. Never claim a technology that is not in `profile/skills.yaml`.
4. Never obscure work authorization status. State it plainly when asked. A role that will not sponsor is a role that wastes both parties' time.
5. Never fabricate a person, a mutual connection, a conversation, or a company detail. If `company-researcher` could not verify a fact, the message ships without it.
