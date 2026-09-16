#!/bin/bash
# Daily Application Desk run, driven by launchd rather than a live Claude session.
#
# WHY THIS EXISTS: the in-session cron job dies whenever Claude exits and expires
# after seven days regardless. This survives reboots, logouts and closed laptops.
#
# TWO STAGES, and the split is deliberate:
#   Stage 1 is pure Python and ALWAYS runs. Job discovery, JD screening and the
#           GitHub diff need no model and no auth beyond `gh`. Even if stage 2
#           fails completely, the day's data is collected and logged.
#   Stage 2 asks Claude Code to do the judgement work: build resumes, draft
#           outreach, republish the desk. It is allowed to fail without taking
#           stage 1 down with it.
#
# launchd gives a process almost no environment: no shell profile, no PATH to
# Homebrew, no interactive terminal. Every binary below is therefore absolute.

set -uo pipefail

REPO="/Users/srikarreddy/Developer/career-agent"
PY="$REPO/.venv/bin/python"
CLAUDE="/Users/srikarreddy/.local/bin/claude"
LOGDIR="$REPO/data/logs"
STAMP="$(/bin/date +%Y-%m-%d)"
LOG="$LOGDIR/daily-$STAMP.log"

# Homebrew for tectonic/pdftotext/gh, plus the user bin for claude.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Users/srikarreddy/.local/bin"
export HOME="/Users/srikarreddy"

/bin/mkdir -p "$LOGDIR"
exec >>"$LOG" 2>&1
echo ""
echo "=========================================================="
echo "RUN $(/bin/date '+%Y-%m-%d %H:%M:%S %Z')"
echo "=========================================================="

cd "$REPO" || { echo "FATAL: repo not found at $REPO"; exit 1; }

# SINGLE RUN AT A TIME. On 2026-09-14 a manual run was started at 11:57 and the
# scheduled launchd run fired at 12:04 while it was still in Stage 2. Both wrote
# to the same log and both touched pipeline.db, and the first run's Stage 2 was
# lost entirely. Two processes writing one SQLite file is a real corruption
# hazard, not just messy output.
#
# mkdir is atomic on every filesystem this will ever see, which is why it is the
# lock rather than a plain -f test.
LOCKDIR="$REPO/data/.daily_run.lock"
if ! /bin/mkdir "$LOCKDIR" 2>/dev/null; then
  OWNER="$(/bin/cat "$LOCKDIR/pid" 2>/dev/null || echo unknown)"
  if [ "$OWNER" != "unknown" ] && /bin/kill -0 "$OWNER" 2>/dev/null; then
    echo "ALREADY RUNNING as pid $OWNER, started $(/bin/cat "$LOCKDIR/started" 2>/dev/null)."
    echo "Exiting rather than racing it. Nothing was changed."
    exit 0
  fi
  echo "stale lock from pid $OWNER, its process is gone. Reclaiming."
  /bin/rm -rf "$LOCKDIR" && /bin/mkdir "$LOCKDIR" || { echo "FATAL: cannot take the lock"; exit 1; }
fi
echo "$$" > "$LOCKDIR/pid"
/bin/date '+%Y-%m-%d %H:%M:%S' > "$LOCKDIR/started"
trap '/bin/rm -rf "$LOCKDIR"' EXIT INT TERM

# Wait for the network. On a laptop waking from sleep, launchd fires before
# Wi-Fi has associated, and every fetch would fail for no good reason.
for i in $(seq 1 30); do
  if /usr/bin/curl -sf --max-time 5 -o /dev/null https://raw.githubusercontent.com; then break; fi
  echo "  no network yet, retry $i/30"; /bin/sleep 10
done

echo ""
echo "--- STAGE 1a: new postings -------------------------------"
"$PY" scripts/watch_simplify.py --days 2 --commit
echo "  exit: $?"

echo ""
echo "--- STAGE 1a2: data roles --------------------------------"
# The SimplifyJobs feed is a software-engineering list, so Data Analyst, Data
# Engineer, Data Scientist and BI roles were structurally invisible: 42 of 42
# applications went to SWE reqs while a fit analysis scored him 76 technical as a
# Power BI and Fabric analyst. This sweeps 54 verified ATS boards for data titles.
"$PY" scripts/discover_data.py --limit 30 --commit
echo "  exit: $?"

echo ""
echo "--- STAGE 1a3: every ATS board the pipeline has seen -----"
# Added 2026-09-16, the Tsenta-style breadth Srikar asked for. discover_data.py
# sweeps 54 hand-verified boards; this sweeps every board named in any pipeline
# URL (161 at launch, across Greenhouse, Ashby, Lever, Workday, SmartRecruiters
# and Oracle) and grows on its own. Harvest runs first so boards from rows added
# earlier in THIS run are swept today rather than tomorrow. Boards where an
# employer has already said no in writing are skipped. Nothing here submits
# anything: Srikar chose staged submission.
"$PY" scripts/discover_ats.py harvest 2>&1 | grep -vE "^[[:space:]]+ok " | tail -12
"$PY" scripts/discover_ats.py sweep --limit 60 --commit 2>&1 \
  | grep -E "^sweeping|listed|blocked on|new and|QUALIFIED|committed|Error|Traceback"
echo "  exit: ${PIPESTATUS[0]}"

echo ""
echo "--- STAGE 1b: github diff --------------------------------"
"$PY" scripts/sync_github.py --save
echo "  exit: $?"

echo ""
echo "--- STAGE 1c: pipeline state -----------------------------"
"$PY" scripts/pipeline.py stats
# Two copies on purpose: the Desktop one is for him, the repo one is the copy
# Claude can actually read back, since TCC blocks ~/Desktop from the CLI.
"$PY" scripts/export_csv.py --all -o "$REPO/data/job_tracker.csv"
"$PY" scripts/export_csv.py -o "$REPO/data/applied.csv"
/bin/cp "$REPO/data/job_tracker.csv" "$HOME/Desktop/SaiSrikar_job_tracker.csv" 2>/dev/null
/bin/cp "$REPO/data/applied.csv" "$HOME/Desktop/SaiSrikar_applied.csv" 2>/dev/null

echo ""
echo "--- STAGE 1c2: retire dead postings ----------------------"
# Nothing rechecked a posting after discovery, so rows sat in the queue as
# "Apply" long after the req closed. The first sweep on 2026-09-07 found 20
# dead rows out of 115, 17% of the queue. Definitive deaths (the ATS's own API
# says the job is gone) are retired automatically; heuristic ones are reported
# and left alone, because a false positive silently deletes a real opportunity.
"$PY" scripts/liveness_check.py --workers 8 --commit
echo "  exit: $?"

echo ""
echo "--- STAGE 1d: handoff queue -------------------------------"
"$PY" "$REPO/scripts/build_queue.py"

# Rebuild the desk's tables from the database. Without this the open-roles
# table is whatever it was the last time someone edited the HTML by hand, so
# the watcher's new finds never reach the page and roles already applied to
# keep showing as open. DESK_HTML can point anywhere; the default keeps a
# copy in the repo that survives the session scratchpad being cleared.
DESK_HTML="${DESK_HTML:-$REPO/data/desk.html}"
if [ -f "$DESK_HTML" ]; then
  "$PY" "$REPO/scripts/build_desk.py" "$DESK_HTML"

  # PUBLISH DRIFT. This run rebuilds desk.html but CANNOT publish it: Stage 2
  # has no Artifact tool. So the published page only moves when an interactive
  # session republishes, and in between it drifts silently. On 2026-09-13 Srikar
  # found both Mulligan rows still listed as open on the published page while
  # the local file had been correct for days and the published one was stamped
  # 9 SEP. Same class of staleness as 2 September.
  #
  # Make it loud. The check hashes only the counters and the table bodies, not
  # the whole file, because build_desk.py rewrites the date stamp every run and
  # a warning that fires daily is a warning nobody reads.
  set +e
  DESK_STATE_OUT="$("$PY" "$REPO/scripts/desk_publish_state.py" check "$DESK_HTML" 2>&1)"
  DESK_STALE=$?
  set -e
  echo "  $DESK_STATE_OUT"
  if [ "$DESK_STALE" -ne 0 ]; then
    QF="$REPO/data/logs/QUEUE.md"
    if [ -f "$QF" ]; then
      /usr/bin/printf '%s\n' \
        "> **PUBLISHED DESK IS STALE $(/bin/date +%Y-%m-%d).** data/desk.html has" \
        "> newer rows than the published Artifact. The daily run cannot publish," \
        "> so ask an interactive session to republish it, then run:" \
        "> \`python scripts/desk_publish_state.py mark\`" "" | /usr/bin/tee /tmp/_qd.$$ >/dev/null
      /bin/cat "$QF" >> /tmp/_qd.$$ && /bin/mv /tmp/_qd.$$ "$QF"
    fi
    /usr/bin/osascript -e 'display notification "Published desk is stale. See QUEUE.md." with title "career-agent daily" sound name "Basso"' 2>/dev/null || true
  fi
else
  echo "desk: $DESK_HTML not found, skipping rebuild"
fi

echo ""
echo "--- STAGE 2: Claude builds resumes and the desk ----------"

# AUTH. Stage 2 failed silently every day from 2026-08-20 to 2026-09-07, 19 runs,
# reporting "OAuth session expired and could not be refreshed". Claude Code keeps
# its OAuth token in the macOS Keychain and launchd could not refresh it.
#
# SUBSCRIPTION ONLY. Srikar set this constraint on 2026-09-08: the daily run must
# cost nothing beyond the Max plan he already pays for. An ANTHROPIC_API_KEY is a
# SEPARATE metered account, billed per token to a card, and it does NOT draw on
# the Max plan. A key is already sitting in ~/.zshrc, and Claude Code prefers a
# key over the keychain token whenever one is present in the environment, so an
# inherited variable would silently move every run onto paid API billing.
#
# So the key is actively removed here rather than merely not set. This is a
# guard, not a default.
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "  auth: ANTHROPIC_API_KEY was present in the environment. UNSETTING it,"
  echo "        because that bills a separate metered account rather than the Max"
  echo "        plan. Subscription auth only, by Srikar's instruction."
  unset ANTHROPIC_API_KEY
fi
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# The keychain token is the only credential this run may use. If it has lapsed,
# the fix is one interactive `claude` on this Mac; nothing here can refresh it.
if /usr/bin/security find-generic-password -s "Claude Code-credentials" >/dev/null 2>&1; then
  echo "  auth: keychain OAuth token present, using the Max subscription"
else
  echo "  auth: NO keychain token found. Run 'claude' once interactively."
fi

if [ ! -x "$CLAUDE" ]; then
  echo "  SKIPPED: claude not executable at $CLAUDE"
  echo "  Stage 1 data is above and the CSVs are on the Desktop."
  exit 0
fi

PROMPT="$REPO/scripts/daily_prompt.txt"
if [ ! -f "$PROMPT" ]; then
  echo "  SKIPPED: $PROMPT missing"
  exit 0
fi

# --print runs headless. Permission mode is the least-privilege one that still
# lets it edit files in the repo; it cannot submit forms or send mail regardless,
# because nothing in the prompt or the repo is wired to do either.
# macOS has no `timeout`; it is GNU coreutils. perl's alarm is always present.
# DICE AND INDEED, added 2026-09-13. Two job-board MCP servers registered LOCALLY
# under stable names rather than used through the claude.ai connectors.
#
# WHY LOCAL. The claude.ai connectors work, but their tool names carry a
# server-side UUID (mcp__bfcf4953-...__search_jobs) that is resolved per session
# and appears NOWHERE on disk. Allowlisting a UUID would break silently the day
# it changes, and this repo has already lost 19 consecutive runs to one silent
# Stage 2 failure. `claude mcp add` pins the name, so mcp__dice__* and
# mcp__indeed__* are stable.
#
#   dice     https://mcp.dice.com/mcp          connected, no auth needed
#   indeed   https://mcp.indeed.com/claude/mcp needs OAuth once, run /mcp in an
#            interactive `claude` session. Until then the stage just skips it.
#
# indeed's get_resume is deliberately NOT allowlisted. The run has no reason to
# read his stored Indeed resume and there is no point granting the access.

# LINKEDIN MCP, added 2026-09-13 at Srikar's explicit direction.
#
# stickerdaniel/linkedin-mcp-server drives his OWN logged-in LinkedIn session in
# a browser. He was told plainly, before choosing this, that automated LinkedIn
# access risks account restriction and that his Premium account with its InMail
# credits is currently the single most valuable asset in the search. He chose it
# anyway. That is his call and it is recorded here rather than argued again.
#
# EIGHT READ TOOLS ARE ALLOWLISTED. TWO ARE DELIBERATELY NOT:
#
#     connect_with_person   sends connection requests
#     send_message          sends LinkedIn messages
#
# Those two are never added. They would violate the HARD CONSTRAINTS block in
# daily_prompt.txt ("Never send a LinkedIn message or connection request.
# Everything is staged for him to send"), and the allowlist is the ENFORCEMENT
# of that rule, not a reminder of it. A model that decided to send anyway is
# stopped by the harness, which is the point of putting it here rather than in
# the prompt. If either name ever appears on these lines, it is a bug.
#
# The stage no-ops harmlessly when the MCP is not configured: an allowlisted
# tool that does not exist is simply never offered.

# ALLOWLIST, added 2026-09-08 after the first successful Stage 2 run reported
# that acceptEdits refused every python, grep, curl and Gmail call, so it could
# draft but not log, fetch, rebuild or check mail. Scoped to: the repo's own venv
# python (pipeline.py, build_desk.py, the seven gates, discover_data.py), grep,
# page fetches, and READ-ONLY Gmail. Nothing here can send mail, send a LinkedIn
# message, or submit a form; those remain hard constraints in daily_prompt.txt
# and no tool that could do them is allowed.
#
# RETRY ON TRANSIENT NETWORK FAILURE. Two of the first three authenticated runs
# died on "Can't reach the API server (ENOTFOUND)" while every interactive test
# passed. This Mac resolves through campus DNS (128.206.130.244), which drops for
# seconds at a time. A DNS blip must not cost the day: up to three attempts, 90
# seconds apart, and ONLY a network error retries. A refusal, a crash or the
# 60-minute alarm fails once and stops.
#
# NOTE the comments sit ABOVE the command. An earlier edit put them inside the
# backslash continuation, which commented out the perl alarm and ran claude
# unwrapped. Keep the command contiguous.
RC=1
for ATTEMPT in 1 2 3; do
  OUT="$LOGDIR/stage2-attempt-$ATTEMPT-$STAMP.out"
  /usr/bin/perl -e 'alarm shift; exec @ARGV' 3600 \
    "$CLAUDE" --print --permission-mode acceptEdits --add-dir "$REPO" \
      --allowedTools \
        "Bash(./.venv/bin/python:*)" "Bash($REPO/.venv/bin/python:*)" \
        "Bash(grep:*)" "Bash(pdftotext:*)" "Bash(tectonic:*)" "Bash(sqlite3:*)" \
        "Bash($REPO/scripts/form_check.py:*)" \
        "WebFetch" \
        "mcp__claude_ai_Gmail__search_threads" "mcp__claude_ai_Gmail__get_thread" "mcp__claude_ai_Gmail__get_message" \
        "mcp__linkedin__search_people" "mcp__linkedin__get_company_employees" \
        "mcp__linkedin__get_person_profile" "mcp__linkedin__search_companies" \
        "mcp__linkedin__get_company_profile" "mcp__linkedin__search_jobs" \
        "mcp__linkedin__get_job_details" "mcp__linkedin__close_session" \
        "mcp__dice__search_jobs" "mcp__dice__get_job_details" "mcp__dice__get_company" \
        "mcp__indeed__search_jobs" "mcp__indeed__get_job_details" "mcp__indeed__get_company_data" \
      < "$PROMPT" 2>&1 | /usr/bin/tee "$OUT"
  RC=${PIPESTATUS[0]}
  if [ "$RC" -eq 0 ]; then break; fi
  if /usr/bin/grep -qE "ENOTFOUND|Can't reach the API server|ECONNRESET|ETIMEDOUT|EAI_AGAIN" "$OUT"; then
    echo "  attempt $ATTEMPT: transient network error, retrying in 90s"
    /bin/sleep 90
    continue
  fi
  break
done
echo "  claude exit: $RC"
if [ $RC -eq 142 ]; then echo "  (timed out after 60 minutes)"; fi
if [ $RC -ne 0 ]; then
  echo "  Stage 2 failed. Stage 1 data above is still valid and the CSVs are"
  echo "  on the Desktop."
  # A failure nobody sees is a failure that runs for 19 days. Surface it in the
  # one file he actually opens, and on screen.
  QF="$REPO/data/logs/QUEUE.md"
  if [ -f "$QF" ]; then
    /usr/bin/printf '%s\n' \
      "> **STAGE 2 FAILED $(/bin/date +%Y-%m-%d), exit $RC.** Claude did not run." \
      "> Job collection and the pipeline below are still current. Resume drafting," \
      "> posting triage and the desk republish did not happen. Check" \
      "> data/logs/daily-$STAMP.log." "" | /usr/bin/tee /tmp/_q.$$ >/dev/null
    /bin/cat "$QF" >> /tmp/_q.$$ && /bin/mv /tmp/_q.$$ "$QF"
  fi
  /usr/bin/osascript -e 'display notification "Stage 2 did not run. See QUEUE.md." with title "career-agent daily" sound name "Basso"' 2>/dev/null || true
fi

echo ""
echo "RUN COMPLETE $(/bin/date '+%H:%M:%S')"
