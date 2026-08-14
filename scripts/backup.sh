#!/usr/bin/env bash
# Back up the personal data to the PRIVATE repository.
#
# profile/, data/ and latex/ are excluded from the public career-agent repo by
# .gitignore, because they hold a student ID, a phone number, work
# authorization status and every extracted career document. They are tracked
# instead by a second git dir at .git-private, which shares this working tree,
# so nothing moves on disk and no script path changes.
#
#   ./scripts/backup.sh                 commit and push with a dated message
#   ./scripts/backup.sh "some message"  commit and push with your own message
#   ./scripts/backup.sh --status        show what has changed, push nothing
#
# The push refuses to run if the remote is not private. That check is the whole
# point of this script: everything else here is convenience.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
export GIT_DIR="$REPO/.git-private" GIT_WORK_TREE="$REPO"

if [ ! -d "$GIT_DIR" ]; then
    echo "no .git-private here. The data backup repo is not set up." >&2
    exit 1
fi

if [ "${1:-}" = "--status" ]; then
    git status --short
    echo
    echo "tracked: $(git ls-files | wc -l | tr -d ' ') files"
    exit 0
fi

# Refuse to push personal data anywhere public. Checked every run, not once at
# setup, because a repository's visibility can be changed later by accident.
remote_url="$(git remote get-url origin 2>/dev/null || true)"
if [ -n "$remote_url" ]; then
    slug="$(printf '%s' "$remote_url" | sed -E 's#.*github\.com[:/]##; s#\.git$##')"
    vis="$(gh repo view "$slug" --json visibility -q .visibility 2>/dev/null || echo UNKNOWN)"
    if [ "$vis" != "PRIVATE" ]; then
        echo "REFUSING TO PUSH: $slug is $vis, not PRIVATE." >&2
        echo "This tree contains work authorization status and a student ID." >&2
        exit 1
    fi
fi

git add -f profile data latex
git rm --cached -q -r --ignore-unmatch \
    'latex/**/*.aux' 'latex/**/*.log' 'latex/**/*.out' \
    '**/__pycache__' '**/*.pyc' 2>/dev/null || true

if git diff --cached --quiet; then
    echo "nothing changed since the last backup."
    exit 0
fi

echo "backing up $(git diff --cached --name-only | wc -l | tr -d ' ') changed file(s) to $slug ($vis)"
git commit -q -m "${1:-backup $(date '+%Y-%m-%d %H:%M')}"
git push -q origin main
echo "pushed."
