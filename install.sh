#!/usr/bin/env bash
# career-agent installer.
# Idempotent. Safe to re-run after you pull changes.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${HOME}/.claude"
SKILL_DST="${CLAUDE_DIR}/skills"
AGENT_DST="${CLAUDE_DIR}/agents"
PATH_FILE="${CLAUDE_DIR}/career-agent-path"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "  \033[32mok\033[0m    %s\n" "$1"; }
warn() { printf "  \033[33mwarn\033[0m  %s\n" "$1"; }
fail() { printf "  \033[31mfail\033[0m  %s\n" "$1"; }
step() { printf "\n\033[1m%s\033[0m\n" "$1"; }

FAILED=0

bold "career-agent installer"
echo "repo: ${REPO}"

# ----------------------------------------------------------------------------
step "1. Python environment"

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 not found. Install it and re-run."
  exit 1
fi
ok "python3 $(python3 --version 2>&1 | cut -d' ' -f2)"

if [ ! -d "${REPO}/.venv" ]; then
  python3 -m venv "${REPO}/.venv" && ok "created .venv" || { fail "could not create .venv"; exit 1; }
else
  ok ".venv already exists"
fi

# shellcheck disable=SC1091
source "${REPO}/.venv/bin/activate"
python -m pip install --quiet --upgrade pip
if python -m pip install --quiet -r "${REPO}/requirements.txt"; then
  ok "dependencies installed"
else
  fail "pip install failed. See requirements.txt"
  FAILED=1
fi

# ----------------------------------------------------------------------------
step "2. GitHub CLI"

if command -v gh >/dev/null 2>&1; then
  ok "gh $(gh --version | head -1 | cut -d' ' -f3)"
else
  warn "gh not installed"
  if command -v brew >/dev/null 2>&1; then
    echo "  installing via homebrew, this takes a minute..."
    if brew install gh; then ok "gh installed"; else fail "brew install gh failed"; FAILED=1; fi
  else
    fail "no homebrew. Install gh manually: https://cli.github.com"
    FAILED=1
  fi
fi

if command -v gh >/dev/null 2>&1; then
  if gh auth status >/dev/null 2>&1; then
    ok "gh authenticated as $(gh api user --jq .login 2>/dev/null || echo '?')"
  else
    warn "gh is not authenticated"
    echo ""
    echo "  Run this yourself, it needs a browser login:"
    echo ""
    echo "      gh auth login"
    echo ""
    echo "  Choose: GitHub.com -> HTTPS -> authenticate in browser."
    echo "  Then re-run this installer."
  fi
fi

# ----------------------------------------------------------------------------
step "3. Registering skills and agents"

mkdir -p "${SKILL_DST}" "${AGENT_DST}"

link_count=0
for d in "${REPO}"/skills/*/; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"
  target="${SKILL_DST}/${name}"
  if [ -L "${target}" ]; then
    rm "${target}"
  elif [ -e "${target}" ]; then
    warn "${name} exists in ~/.claude/skills and is NOT a symlink. Skipping, move it aside first."
    continue
  fi
  ln -s "$d" "${target}" && link_count=$((link_count + 1))
done
ok "${link_count} skills linked into ${SKILL_DST}"

agent_count=0
for f in "${REPO}"/agents/*.md; do
  [ -f "$f" ] || continue
  name="$(basename "$f")"
  target="${AGENT_DST}/${name}"
  if [ -L "${target}" ]; then
    rm "${target}"
  elif [ -e "${target}" ]; then
    warn "${name} exists in ~/.claude/agents and is NOT a symlink. Skipping."
    continue
  fi
  ln -s "$f" "${target}" && agent_count=$((agent_count + 1))
done
ok "${agent_count} agents linked into ${AGENT_DST}"

# Skills are symlinked, so they cannot infer the repo root from their own path
# reliably across shells. Record it once, here.
echo "${REPO}" > "${PATH_FILE}"
ok "repo path recorded at ${PATH_FILE}"

# ----------------------------------------------------------------------------
step "4. Data directories"

mkdir -p "${REPO}/profile" "${REPO}/data/raw" "${REPO}/data/artifacts"
ok "profile/ and data/ ready (both gitignored)"

if python "${REPO}/scripts/db.py" init >/dev/null 2>&1; then
  ok "pipeline database initialized"
else
  warn "could not initialize pipeline.db, run: python scripts/db.py init"
fi

# ----------------------------------------------------------------------------
step "5. Self-test"

if python "${REPO}/scripts/style_check.py" "${REPO}/templates/rubric-resume.md" >/dev/null 2>&1; then
  ok "style checker runs"
else
  # The rubric intentionally quotes banned phrases as examples, so a non-zero
  # exit here is expected. We only care that it executed.
  if python -c "import sys; sys.path.insert(0,'${REPO}/scripts'); import style_check" 2>/dev/null; then
    ok "style checker runs"
  else
    fail "style_check.py is broken"
    FAILED=1
  fi
fi

# ----------------------------------------------------------------------------
step "Done"

if [ "${FAILED}" -eq 0 ]; then
  echo "Everything installed."
else
  echo "Installed with warnings above."
fi

cat <<'EOF'

Next step, in Claude Code from any directory:

    /career-setup

That reads your GitHub, your documents, and your LinkedIn export if present,
then builds your evidence bank. Everything else depends on it.

To include LinkedIn: go to LinkedIn > Settings > Data Privacy > Get a copy of
your data, request the full archive, and drop the ZIP into data/raw/.
EOF
