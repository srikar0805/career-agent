---
name: linkedin-profile
description: Rewrite a LinkedIn headline, About section, and top experience entries to rank in recruiter search for a target role. Derives the actual boolean strings recruiters use, then writes to match them. Use when the user wants their LinkedIn profile improved, optimized, or rewritten.
trigger: /linkedin-profile
---

# /linkedin-profile

Rewrite a LinkedIn profile so recruiters searching for your target role actually find you, and so the ones who find you keep reading.

```
/linkedin-profile "ML Engineer" "AI infrastructure"
/linkedin-profile "Data Scientist" fintech --current path/to/profile.txt
/linkedin-profile --headline-only
```

## Two different problems

A LinkedIn profile has to survive two separate filters and most rewrites only address one.

**Retrieval.** A recruiter using LinkedIn Recruiter searches with boolean strings. If your profile does not contain the literal terms they search, you are not in the result set and nothing else about your profile matters. This is a keyword problem.

**Conversion.** Once you are in the result set, you get about the same six seconds a resume gets. What is visible without clicking: your headline in full, your photo, your current title, and roughly the first three lines of your About section. Everything else requires the recruiter to have already decided you are worth more time.

Optimize for retrieval first, because conversion is irrelevant if you are never surfaced. Then make the visible surface earn the click.

## Bootstrap

```bash
REPO="$(cat ~/.claude/career-agent-path)"
cd "$REPO" && source .venv/bin/activate
```

Read `templates/style-rules.md`, `profile/voice.md`, and `profile/evidence.yaml`.

If a LinkedIn export was imported, read `data/raw/linkedin.json` for the current headline, About text, positions, and, most usefully, the endorsement counts. **Skills other people endorsed are independent evidence of what to lead with**, as opposed to what the candidate believes their strengths are. Weight endorsed skills above self-reported ones.

If no export exists, ask the user to paste their current profile, or offer to read it from their browser.

## Step 1: Derive the search strings

Before writing, work out what a recruiter hiring for this role would actually type. Dispatch `jd-analyst` on two or three real postings for the target role, pulled with `discover.py` if none are at hand, and extract the vocabulary they share.

Recruiter searches look like this:

```
("machine learning engineer" OR "ML engineer" OR "MLE") AND (PyTorch OR TensorFlow)
AND (Kubernetes OR Docker) AND ("model serving" OR inference OR deployment)
```

Note what this means for the profile:

- **Title variants matter.** A profile that says only "ML Engineer" misses a search for "Machine Learning Engineer". Both spellings need to appear somewhere.
- **Acronym and expansion both.** "NLP" and "natural language processing".
- **Tools are searched as literals.** "PyTorch" not "deep learning frameworks".
- **Recruiters search seniority terms** that may not be in your title: senior, staff, lead.

Produce the actual boolean strings you are targeting and show them to the user. They are the specification the rewrite is written against.

## Step 2: The headline

220 characters. This is the highest-value text on the profile: it appears in search results, in every comment you leave, in every connection request, and at the top of the profile.

The default LinkedIn generates, which is just your current title and company, wastes it entirely.

Structure that works:

```
<Target role title> | <2 or 3 searchable specialties> | <one specific proof or differentiator>
```

Rules:

- **Lead with the target role, not the current one**, when the user is moving toward something. Recruiters search the role they are filling.
- Pack searchable terms, but it must still read as written by a human. A headline that is thirty keywords separated by pipes reads as desperate and converts badly.
- Include one thing nobody else has. A number, a specific system, a distinctive combination.
- No "aspiring", ever. No "seeking opportunities", which signals unemployment before it signals anything about capability. No "| He/Him |" mixed into keyword territory; pronouns belong in the dedicated field.
- Front-load. Mobile truncates at roughly 60 characters in some views.

Produce three headline options at different angles and explain the tradeoff of each.

## Step 3: The About section

**The first three lines are the whole game.** LinkedIn truncates at roughly 300 characters with a "see more" link, and most readers never click it. Write those three lines as though they are the entire section, then write the rest for the people who click.

Structure:

- **Lines 1 to 3.** The hook. What you do, for whom, with one specific proof. No autobiography, no "I am a passionate technologist", no starting at university.
- **Middle.** Two or three short paragraphs of specifics, each backed by an evidence id. Numbers. Real systems. This is where the searchable long-tail keywords live naturally.
- **A short list.** Technologies and specialties, plainly listed. Recruiters skim for this and search engines index it.
- **Close.** What you are looking for and how to reach you. One or two lines.

Write in first person. LinkedIn is not a resume and third-person About sections read strangely.

Keep paragraphs to two or three lines. Dense blocks do not get read on a phone.

## Step 4: The top three experience entries

Same discipline as `/resume-rewrite`, with two differences:

- The role description field is indexed by search, so it carries more keyword weight than the equivalent resume text
- There is more room, so an entry can carry three to five bullets instead of two

Everything else holds: bullets come from `profile/evidence.yaml`, every one has a number, every one traces to an evidence id, no invented claims.

## Step 5: Review

Dispatch in parallel:

- `fact-checker` on the full rewritten profile
- `recruiter-screener`, prompted specifically to evaluate this as a search result and a profile view rather than as a resume
- `resume-judge` using the alternate dimensions, with Hook strength applied to the first three lines of About

Then run the retrieval check by hand: for each boolean string from Step 1, confirm the required literals actually appear in the new profile. Report any search you would still not surface in, and say what it would cost to fix.

```bash
python scripts/style_check.py data/artifacts/linkedin/profile.md
```

## Step 6: Deliver

Write the output so it can be pasted field by field, because LinkedIn's editor is field-based:

```
=== HEADLINE (220 char limit, yours: <n>) ===
<text>

=== ABOUT (2600 char limit, yours: <n>) ===
--- visible before "see more", first ~300 chars ---
<text>
--- rest ---
<text>

=== EXPERIENCE 1: <Title> at <Company> ===
<text>
```

Then report: the boolean searches this now ranks for, the ones it still does not and why, which endorsed skills you led with, and the evidence id behind every claim.

## Rules

- Never claim a title the user has not held. "Aspiring ML Engineer" is bad, and "ML Engineer" when they have never held the role is worse, because it is false. Write the headline around what they have actually built instead.
- Never keyword stuff. A profile engineered purely for retrieval fails conversion, and increasingly fails LinkedIn's own ranking.
- Every claim traces to an evidence id, same as everywhere else in this repo.
- You do not update LinkedIn. You produce text the user pastes. Never attempt to log in or post on their behalf.
