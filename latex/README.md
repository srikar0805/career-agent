# latex/

Overleaf project sources. Gitignored, same as `profile/` and `data/`.

## Option A: clone from Overleaf (two-way)

Overleaf Git integration is available on the free tier. Dropbox Sync and
GitHub Sync are the premium ones.

    git config --global credential.helper osxkeychain
    git clone https://git.overleaf.com/<project-id> latex/<name>

Username can be anything. Password is the token from Overleaf Account
Settings, Project synchronisation, Generate token. Enter it at the terminal
prompt so the keychain stores it. Edits push straight back to Overleaf.

## Option B: drop the source in (one-way)

Overleaf project, Menu, Download, Source. Unzip into `latex/<name>/`.
Same editing and compiling loop, you re-upload the result yourself.

## The loop

    python scripts/tex_check.py latex/<name>/main.tex --jd posting.txt
    python scripts/tex_check.py latex/<name>/main.tex --compare old.pdf

`tex_check.py` compiles with tectonic and measures what an ATS actually
receives: literal space glyphs, Unicode mapping, column layout, keyword
coverage. `--compare` diffs two builds so a proposed fix either moves the
numbers or gets discarded.
