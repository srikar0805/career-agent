# career-agent, for any agent working in this repo

Read `~/.agent/SHARED.md` and `~/.agent/memory/INDEX.md` first. They hold the standing rules and what
the other agent learned last. `CLAUDE.md` in this repo is a symlink to this file.

## This repository

The pipeline is documented in `docs/architecture.md` and summarized in the README. Five stages:
collect, screen, decide, build one application, follow. Stage 4 runs for one posting at a time, from a
link Srikar sends, through `scripts/apply_flow.py --url <link>`.

## Rules that are not negotiable here

- **Never submit an application and never type into an employer's form.** The pipeline produces a
  resume, a cover letter and an answer sheet; Srikar applies.
- **Never invent a number or a claim.** Everything traces to `profile/evidence.yaml`. A claim with no
  atom is a `[NEED: ...]` and a question, never a plausible figure.
- **This repository is public.** `profile/`, `data/` and `latex/` are gitignored and hold his personal
  data. Never commit them, never paste their contents into an issue, a commit message or a public page.
- **Keys live in the macOS keychain** (`nvidia-api-key`, `gemini-api-key`, `ollama-api-key`). Never in a
  file, a command or a log.
- **No em dashes or en dashes anywhere**, including code comments and commit messages.
- **Every resume PDF passes six gates** before it is shown: page, line, spacing, chrono, title, tex.
- **LinkedIn**: read and search only, under the daily budget in `scripts/agent_recruiters.py`. Never
  connect, never message.

## Conventions

- Python 3, standard library first; the venv is `.venv`.
- Comments say why, with the date and the incident that caused the rule, in the style of the existing files.
- A model's output is never trusted: it is checked by script before it reaches a document.
