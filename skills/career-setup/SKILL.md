---
name: career-setup
description: One-time intake. Reads GitHub, career and research documents, and the LinkedIn export, then builds the evidence bank, identity, skills, voice, and narrative files that every other career skill depends on. Use before any other career-agent skill, or to refresh the profile after new work.
trigger: /career-setup
---

# /career-setup

Build the evidence bank. Everything else in this repo depends on it.

```
/career-setup                    # full build
/career-setup --refresh          # re-pull sources, merge into the existing bank
/career-setup --gaps             # only fill in missing metrics
/career-setup --skip-github
```

## What this is doing

It reads what you have actually done, from sources that cannot flatter you, and turns it into atomic records with stable ids. After this runs, no other skill ever invents anything about you. They select from these records.

The intake is deliberately not a questionnaire. Most of what a normal intake asks for is already sitting in your GitHub history and your old resumes. The only questions worth your time are the ones no document can answer, which are almost always the numbers.

## Step 1: Collect

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
```

Run the three connectors. GitHub and documents can run concurrently.

```bash
python connectors/github.py
python connectors/docs.py
python connectors/linkedin.py
```

**If `gh` is not authenticated**, the GitHub connector fails with a clear message. Stop and tell the user to run `gh auth login` in their terminal, since it needs a browser and you cannot do it for them. Offer to continue without GitHub, and be explicit about what that costs: commit history, repo languages, and external pull requests are the strongest evidence available for an engineer, and a bank built without them will be thin.

**If no LinkedIn export exists**, that is fine. Tell the user how to get one and continue. Note what they are missing: the endorsement data and the warm-intro connection graph.

**Before the document scan**, show them what will be read:

```bash
python connectors/docs.py --list-only
```

Confirm the scope looks right. The scanner refuses tax, loan, lease, passport, DS-160, and I-20 folders outright, but the user should see the list regardless.

Then build the packet:

```bash
python connectors/build_evidence.py pack
```

## Step 2: Read the packet

Read `data/raw/evidence_packet.md` in full. If it is large, read it in sections.

While reading, hold three questions:

1. **What did this person actually build, and how do I know?**
2. **Where do sources agree?** The same accomplishment appearing in a repo README, an old resume, and a LinkedIn position is the strongest signal in the packet.
3. **Where do sources conflict?** Two resumes describing the same project with different numbers is not something to average. It is something to ask about.

## Step 3: Write the evidence bank

Write `profile/evidence.yaml`. One atom per distinct accomplishment.

```yaml
- id: EV-001
  role: "ML Engineer Intern, Acme"        # or project: for personal work
  period: "2025-06/2025-08"
  action: "Rebuilt the batch inference path from per-row calls to vectorized ONNX"
  metric: {value: 4.2, unit: "x", dimension: "throughput"}
  scope: "12M records/day, 3 person team"
  tech: [python, onnx, ray, aws-batch]
  skills: [performance-optimization, mlops]
  star:
    situation: "..."
    task: "..."
    action: "..."
    result: "..."
  confidence: verified
  sources: ["github:srikar0805/ReproAgent", "Srikar_Resume.pdf p1"]
```

Rules for writing atoms:

- **One accomplishment per atom.** Not one per repo and not one per job. A single job usually produces three to six atoms.
- **`sources` is mandatory.** An atom with no source is a hallucination with extra steps.
- **Never invent a metric.** If the packet does not contain the number, omit the `metric` key entirely. Do not estimate, do not use a plausible round number, do not write a range you made up. The gap is the point; it becomes a question in Step 5.
- **`confidence: verified`** only when a source states the fact directly. A commit count is verified. "Improved performance" with no measurement is `unverifiable`.
- **Write STAR for the strongest atoms.** Those are what `/interview-prep` uses. Ten strong STAR records beat forty atoms without them.
- **Coursework is usually not evidence.** A class assignment is not an accomplishment. A course project with real scope, real users, or real engineering depth is. Most of the 224 documents scanned will contribute nothing, and that is the correct outcome.

Aim for 25 to 60 atoms. Fewer than 15 means the packet was under-read. More than 80 usually means assignments got in.

## Step 4: Write the rest of the profile

**`profile/identity.yaml`.** Some of this you must ask, because no document reliably states it and getting it wrong wastes real applications:

```yaml
name: ""
email: ""
phone: ""
location: ""
github: ""
linkedin: ""
website: ""

work_authorization: ""        # ask. Be exact.
needs_sponsorship: true       # ask. This filters every job search.
authorized_countries: []

target_roles: []
target_locations: []
open_to_remote: true
comp_floor: null
timeline: ""                  # "actively searching" | "casually looking" | "graduating May 2027"
```

Ask about work authorization plainly and record the exact answer. It drives the `discover.py` filter and it must be stated honestly in every application. Vagueness here costs interviews later.

**`profile/skills.yaml`.** Every skill, its proficiency, and the evidence ids that back it. A skill with no backing atom does not go in the file, because nothing may claim it later.

```yaml
- name: python
  level: advanced          # foundational | working | advanced | expert
  years: 4
  evidence: [EV-001, EV-007, EV-014]
  endorsed: 12             # from LinkedIn, if available
```

**`profile/voice.md`.** Paste two or three real samples of the user's own writing, pulled from their existing cover letters or SoPs. Every skill reads this so output sounds like them. Note their actual habits: sentence length, formality, whether they use contractions, how they open and close.

**`profile/narrative.md`.** The positioning: who they are in one sentence, the through-line connecting their work, why they are targeting these roles, and the prepared answer for each red flag (a pivot, a gap, a short tenure, work authorization). `/interview-prep` and `/coverletter` both read this.

## Step 5: The gap interview

This is the only part that requires the user's time, and it is worth it.

```bash
python connectors/build_evidence.py validate
python connectors/build_evidence.py gaps
```

`gaps` lists every atom with no metric and suggests the specific question to ask for each.

Ask them **in one batch**, grouped and numbered, not one at a time. Make each question concrete and easy:

> Six of your records are missing the number that would make them strong. Answers can be rough.
>
> 1. **agent-tab-extension** (5,837 commits over 14 months). How many people use it? Store installs, active users, or "just me" are all fine answers.
> 2. **ReproAgent**. What did it automate, and how long did that take manually before?
> 3. ...

Accept "I do not know" and "roughly N". Record the latter with `confidence: approximate`, which forces every future document to hedge appropriately.

Then write the answers into the atoms and re-run `validate`.

## Step 6: Report

Show:

```bash
python connectors/build_evidence.py stats
```

Plus:

- **The five strongest atoms**, since these will lead most resumes
- **Anything surprising the sources revealed.** A project the user under-represents is a common and valuable find.
- **Coverage gaps.** Target roles their evidence does not support well.
- **What is still missing**, meaning atoms without metrics or STAR records
- **Any conflicts between sources**, surfaced rather than silently resolved
- **Any ATS problems in their existing resumes**, from the ingest warnings

Then point at the next step, usually `/job-hunt` or `/resume-rewrite`.

## Rules

- **Never invent a fact, a metric, a date, or a technology.** Everything traces to a source or it is not written.
- **Never write a metric the user did not confirm.** An omitted metric is a solvable gap. A fabricated one poisons the whole bank, because every downstream skill trusts it.
- Surface conflicts, do not resolve them silently.
- Get work authorization exactly right.
- `profile/` is gitignored. Say so, so the user knows their data is not going to end up in a public repo.
