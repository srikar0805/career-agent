# /resume-rewrite reference

Why each rule in `SKILL.md` exists. **Every rule here was got wrong on a resume
that had already been sent to an employer. None of them are hypothetical.**

`SKILL.md` carries the rules and is loaded on every invocation. This file carries
the incidents and is loaded ONLY when a gate actually fails or a rule is about to
be bent. Splitting them on 2026-09-14 cut the per-invocation cost of
`/resume-rewrite` by roughly two thirds; the skill had reached 590 lines and was
being re-injected in full eight times in a single session.

Read the section here that matches the rule you are questioning. Do not read the
whole file.

## The gate: why each rule exists

A resume is not finished until all of these pass on the compiled PDF. Run
them on the actual output file, not on the markdown or the `.tex`, because
every defect they catch is one that exists only after rendering.

```bash
python scripts/page_check.py    <resume.pdf>            # fills the page, no orphan page, no internal holes
python scripts/line_check.py    <resume.pdf>            # every wrapped bullet ends past 60% of the column
python scripts/spacing_check.py <main.tex> <resume.pdf> # one spacing value, one bullet rhythm
python scripts/chrono_check.py  <resume.pdf>            # reverse-chronological, no unexplained overlap
python scripts/title_check.py   <resume.pdf>            # job titles match the ones actually held
python scripts/tex_check.py     <main.tex>              # stray markup, ligatures, extractability
pdftotext -layout <resume.pdf> - | grep -nE "^[A-Z][A-Z &]{3,}$"   # read the headings back
```

Every rule below is here because it was got wrong on a resume that had already
been sent to an employer. None of them are hypothetical.

**Never retitle a job.** Titles come from `profile/titles.yaml` and are copied
exactly. Tailoring the bullets under a job to a posting is the whole point of
this skill; changing the title of the job is a factual claim about employment
that a background check verifies against payroll, and the cost of being caught
is a rescinded offer rather than a lost interview. This drifts easily because
it does not feel like lying: "Student Assistant, Technical (AI Image
Engineering)" becomes "Data Engineer (Student Technical Assistant)" on a data
resume to help the reader, and one job ends up with six spellings across six
files, none of them the one on the offer letter. If a title reads badly for a
target, the fix is a stronger first bullet, not a better title.

**Fill the page to the last line.** `page_check.py` passes when the last line
sits within a third of an inch of the bottom margin. A page that stops short
reads as thin no matter how good the content is. Fill it with real evidence
first, an unused atom from the bank; only relax spacing once there is nothing
true left to add. Never pad with filler to hit the number.

**Certifications get a section, never a mention.** Every resume carries a
`CERTIFICATIONS` section listing all four credentials: the Microsoft Fabric
Analytics Engineer Associate, the IBM Road to Practitioner, and both
DeepLearning.AI courses. Putting the certification in the header line next to
the degree does not count; it reads as a passing detail and Srikar considers it
missing, correctly. Use the `\certificationsItem` macro that already exists in
`resume.cls`, and separate the items with `\\` or they run together on one line.
This was got wrong for a long time: an audit found the Microsoft credential on
one of eight recent resumes, because it had been filed as a data credential and
dropped from software engineering variants. It is a verifiable third-party
credential and it belongs on every variant.

**Every certification carries a verification link.** The right-hand column is a
short clickable word, `Verify`, matching the `Github` links used on projects.
Not the bare URL, which is long and ugly and pushed a degree onto a second page
the one time it was tried. The URLs live on `EV-032`, `EV-033` and `EV-034B` in
the evidence bank as `verify_url`, so they never need to be asked for again.
Load every link signed out before shipping. A verification link that 404s in
front of a recruiter is worse than no link at all.

**Open every link on the page before shipping, signed out.** The four
certification `Verify` links, the GitHub link on every project, LinkedIn. Two
failure modes, both live in this repo:

1. A 404 in front of a recruiter is worse than no link at all.
2. **A repository with a security problem is worse than no project.** Guardian
   AI (`EV-019`) and SPD-React (`EV-042`) are strong work and both are held off
   every page until the issue in each is fixed and the affected secrets are
   rotated. The specifics are deliberately not written here: this repository is
   public. A reviewer who clicks through to a security problem has made a
   judgment about the candidate, and no bullet recovers from it.

**Watch the Microsoft credential expiry.** It lapses 2026-11-26 and the renewal
window is already open. Once it lapses, the Verify link on every shipped resume
disproves the line above it.

**One spacing value for the whole document.** `spacing_check.py` enforces this.
Every `\itemsep` in the file carries the same value, no `itemize` opens with a
`\vspace`, and all five section headers in `resume.cls` use the same rule
spacing. The defect this catches shipped on more than forty templates: project
bullet lists carried a `\vspace{-0.5em}` that experience lists did not, so
project bullets sat half a line tighter under their title, and `workSection`
used `0.3em` above its rule while `\education` and `\skills` used `0.4em` with
`\education` missing its `-0.3em` below entirely. Srikar spotted it on sight:
one section spaced differently from another is what makes a resume look
amateur, and no amount of good content compensates.

**Every job goes on every resume. Three projects, maximum.** Set by Srikar on
2026-09-07, and it reverses how several pages had been built that week. All four
positions appear on every variant: PAAL, MAQ Software, SP Software and HiringFIT.
**Experience outweighs a personal project every time**, so a job is never dropped
to make room for one, however well the project matches the posting. A recruiter
reads the employer column before anything else, and a gap there is a question;
a missing side project is not.

This had drifted badly. The Deeter, SIG, Point72 and StudyFetch pages each ran
three employers and four or five projects, because HiringFIT is one month in 2023
on a React dashboard and it kept losing to a better-matched repository. That was
the wrong trade. HiringFIT is employment, it is corroborated by 4 pull requests
an external maintainer merged, and it closes the 2023 stretch of the timeline.

**The order of what to cut when the page is over**, top of the list first:

1. The fourth project, then the third, down to a floor of two.
2. The weakest bullet inside an experience entry, longest-serving job last.
3. Never a whole job. Never a degree. Never a certification.

**To fill a short page, tune the one shared `\itemsep` and re-measure.** Never
add a `\vspace` to a single section. Never delete a degree to make room for a
project; if a project does not fit, the project loses.

**Measure the page, do not eyeball it.** When spacing looks wrong, get the
numbers before changing anything:

```bash
pdftotext -bbox-layout <resume.pdf> /tmp/r.xml
```

Then read consecutive `yMin`/`yMax` pairs to get the real gaps. On a correct
document they cluster into exactly three values: the leading inside one wrapped
bullet, a slightly larger gap between bullets, and a larger one between entries.
Two lines on the same `yMin` are the left and right halves of one header row,
not two lines. Guessing at spacing produces the whack-a-mole loop where every
fix creates a new defect somewhere else.

**Fix a runt by arithmetic, not by iteration.** `line_check.py` fails any
wrapped bullet whose last line stops before 60% of the column. Measure the
column width in characters, compute `need = int(width * 0.60)`, and size the
edit to the exact deficit. Editing by feel and rebuilding to see what happened
wastes a dozen builds and usually breaks a different bullet.

**Make the font size actually apply.** `\LoadClass[9pt]{article}` silently does
nothing: `article` accepts only 10, 11 and 12pt. Use `extarticle`, which honours
8pt and 9pt. Every resume built before this was found rendered at 10pt no matter
what the class options said.

**Check that multi-word keywords survive the line break, then stop them breaking
at all.** An ATS matching "modern deployment and build tooling" will not match it
when the renderer splits it across two lines. Verify each multi-word term from the
posting appears intact on a single line, in every occurrence, not just the first
one found.

Detection is not enough, because the break point moves every time the text
around it changes. **Tie every multi-word term with `~` instead of a space**, so
LaTeX cannot break it: `\textbf{feature~engineering}`, `\textbf{Intel~RealSense}`,
`\textbf{machine~learning}`. Do this in the skills block especially, where terms
are dense and wrapping is unpredictable. On the U.S. Bank Data Scientist resume
`feature engineering`, `model lifecycle` and `stakeholder requirements` were all
split, and tying 27 terms lifted ATS coverage from 54.8% to 59.6% with no content
change at all.

**What does not go on the page.** Three standing exclusions, each from Srikar
directly:

*The C++ barn camera bullet is retired.* Any phrasing of it: "Rebuilt the barn
camera service in C++", "710-line Intel RealSense manager", "V4L2 backend",
"wiringPi motor GPIO". It is embedded work on pages that are otherwise about
applications, web services and AI, and it kept crowding out bullets that answer
the posting. C++ stays in the skills line without a bullet. Lead the PAAL role
with the software work instead, in this order: the RAG service, the evaluation
harness, the reporting automation, the documentation and pytest suite, then
troubleshooting long-running jobs. **If a posting genuinely requires C++ or
hardware integration, ask him before reaching for it.** Tesla req 221961 named
"modern C++ (14/17/20)" as one of five requirements, which is the exception that
justified putting it back on that one page. **Point72 / Cubist is the second,
recorded 2026-09-07**, where two desirable qualifications read "Experience in
Python and C++" and "systems programming (e.g. kernel development, compilers,
embedded systems, networking, file systems, debuggers)". On that one it went on
without asking first and Srikar was told in the report rather than beforehand.
The working rule is now: put it on when a posting names C++ or systems
programming among its stated requirements, keep it off everything else, frame it
as concurrent systems code, and say plainly in the report that it is on and how
to remove it.

*Never name a language construct.* `std::mutex`, `lock_guard` and `RAII` are
banned outright. They are line-level implementation detail: a recruiter skips
them and an engineer does not need them to believe the claim. Say what the code
achieves. "Keeps shared pipeline state thread-safe under concurrent capture"
beats naming the header you included. `multithreading` and `concurrency` are
fine in a skills line, and `C++ (C++11/14/17)` answers a modern-C++ requirement
without the primitives. These had spread to ten templates and ten shipped PDFs
before they were caught.

*No unverified numbers, and no numbers sourced to another resume.* The six
untraced PAAL figures stay off every page: 9 architectures, ConvNeXt-V2, 0.34M
params and 44x, 14,600 images per second with 140x and 5ms, the 56 GB cache, and
250 defects across 8 rounds. Every one of them was searched for in his
repositories on 2026-09-04 and appears only in `career-agent-data/profile/`, his
portfolio site and `narrative.md`, never in code. Use the technique without the
figure: "optimised inference with AMP and fp16, channels-last memory format and
batched pipelines" is true and says enough.

**Standard section headings only.** Read the headings back out of the PDF and
check them against `CANONICAL_HEADINGS` in `scripts/ats_check.py`. `PROJECTS`,
`EXPERIENCE`, `TECHNICAL SKILLS`, `EDUCATION`, `CERTIFICATIONS`. Not "Things
You Can Open And Try", not "Also Built", not any invented name however well it
describes the content. An ATS parses an unrecognized heading as body text and
files everything under it in the wrong field.



---

## Why the DOCX rule reversed

- **Ship the PDF. Do not build a DOCX unless the posting demands one.** Reversed
  2026-09-07 at Srikar's direction, after two were built that nobody asked for.
  The old rule said to ship DOCX wherever it was accepted, on the theory that a
  LaTeX PDF contains no space characters (word gaps are glyph positioning, so a
  naive parser reads one continuous string). That risk is real but theoretical:
  `tex_check.py` reports poppler reading these PDFs with **0 glued** words, and
  Greenhouse, Workday, iCIMS, Ashby and Lever all use capable parsers. The cost
  is not theoretical. `render.py` emits 10.5pt Calibri in plain Normal and
  List Bullet styles, with company and dates on separate lines, no right-aligned
  date column, no section rules and no `Verify` links. It is a different and
  worse document than the one every gate in this skill was run against, and at
  798 words it does not hold one page. Shipping it hands the reader the ugly
  version of work that passed `page_check`, `line_check` and `spacing_check`.
  Check the posting's accepted file types. `pdf` is listed first essentially
  everywhere. Build a DOCX only when a posting names Word specifically, or when
  an ATS is known to be a naive extractor, and say why in that resume's header
  comment. Cover letters are unaffected: Srikar asked for those as documents
  on 2026-09-04 and that still stands.

## The outcome-first bullet, worked example

Weak    Built an evaluation harness scoring models on macro-F1 and ROC-AUC.
    Strong  Replaced an architecture choice made on intuition and redirected
            what the lab collects, by building the harness that scores every
            candidate on macro-F1, ROC-AUC, MCC and bootstrap intervals.

Not every bullet can carry an outcome, and forcing one produces invention. The
rule is that the **first bullet under every role must**, and at least half the
page overall must. A page of mechanism with no outcomes is a job description.

## Amazon leadership principles, atom mapping

**For Amazon and Amazon-shaped employers, seed the leadership principles.**
Amazon interviews against 16 named principles and the Bar Raiser reads the
resume for them before the loop starts. Four are reachable from this bank
without invention:

| Principle | Atom |
|---|---|
| Ownership | `EV-037`, led three engineers through a migration end to end |
| Dive Deep | `EV-039` and `EV-011`, every figure reconciled to its origin |
| Bias for Action | `EV-022` and `EV-023`, shipped without being asked |
| Deliver Results | any bullet carrying a measured outcome |

Never name a principle on the page. Choose the atoms that demonstrate it.
