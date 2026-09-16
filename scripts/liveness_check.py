#!/usr/bin/env python3
"""Retire pipeline rows whose posting has gone dead.

WHY THIS EXISTS. Nothing rechecked a posting after discovery, so a row stayed in
the queue as "Apply" forever. On 2026-09-07 Srikar found nine dead rows by hand
in a single day: four Tesla reqs, MCHCP, Wintermute, Datalab USA, a stale Kikoff
req, Bank of America and NRG Energy. The oldest open rows date to early August,
so a meaningful share of the queue is postings nobody can apply to any more.

TWO CONFIDENCE LEVELS, and the distinction is the whole point.

  definitive  The ATS's own public API says the job is gone. Greenhouse, Ashby
              and Lever all expose one, and a 404 or an absent id from those is
              a fact, not an inference. Safe to act on automatically.

  likely      A heuristic: an HTTP 404/410, a redirect away from the posting to
              a board root, or specific "no longer available" text. Good signal,
              but a JS-rendered ATS can look dead when it is not, so these are
              reported and never withdrawn unless asked.

A false positive here silently deletes a real opportunity, which is worse than
leaving a dead row on the page, so the default is to report and change nothing.

Usage:
    python scripts/liveness_check.py                     # dry run, report only
    python scripts/liveness_check.py --commit            # withdraw definitive
    python scripts/liveness_check.py --commit --include-likely
    python scripts/liveness_check.py --older-than 14 --json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, now  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

# Deliberately specific. "closed" or "filled" alone match live postings that
# merely mention the words, so every pattern here names the posting itself.
DEAD_TEXT = re.compile(
    r"no longer accept\w* applications"
    r"|this (job|position|posting|req\w*) is no longer"
    r"|the (job|position) you (are|were) looking for is no longer"
    r"|position has been filled"
    r"|this (job|position|posting) (has been|is) closed"
    r"|job (posting )?not found"
    r"|we are no longer accepting"
    r"|sorry,? (this|that) job",
    re.I,
)

# A redirect that lands on a board root rather than a posting means the req is
# gone. Greenhouse appends ?error=true, which is unambiguous.
BOARD_ROOT = re.compile(
    r"greenhouse\.io/[\w-]+/?(\?|$)"
    r"|\?error=true"
    r"|jobs\.lever\.co/[\w-]+/?(\?|$)"
    r"|jobs\.ashbyhq\.com/[\w-]+/?(\?|$)",
    re.I,
)


def _get(url: str, timeout: int = 20, limit: int | None = 300_000):
    """Return (status, final_url, body). Never raises for HTTP errors.

    limit caps the bytes read. It exists so a heuristic fetch of some vendor's
    500 KB marketing page does not blow up memory, and 300 KB is plenty for
    that. It is WRONG for a JSON API: on 2026-09-13 the Crusoe Ashby board came
    back at 299,271 bytes of a larger body, json.loads raised on an unterminated
    string, check_ashby swallowed the exception and returned None, and the row
    fell through to the plain HTTP check, which saw the SPA shell's 200 and
    called a dead posting alive. Pass limit=None from every API probe.
    """
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read() if limit is None else r.read(limit)
            return r.status, r.geturl(), raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(60_000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, url, body
    except Exception as e:
        return None, url, f"__ERROR__ {e}"


def check_greenhouse(url: str):
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", url)
    if not m:
        return None
    code, _, _ = _get(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}")
    if code == 200:
        return ("alive", "definitive", "greenhouse api 200")
    if code in (404, 410):
        return ("dead", "definitive", f"greenhouse api {code}")
    return None


def check_ashby(url: str):
    m = re.search(r"ashbyhq\.com/([\w-]+)/([0-9a-f-]{36})", url)
    if not m:
        return None
    code, _, body = _get(f"https://api.ashbyhq.com/posting-api/job-board/{m[1]}",
                         limit=None)
    if code != 200:
        return None
    try:
        ids = {j.get("id") for j in json.loads(body).get("jobs", [])}
    except Exception as exc:
        # NEVER fall through to the heuristic on a parse failure. That is what
        # turned dead Crusoe #64 into "alive" for weeks: an unparseable board
        # returned None, and the caller's HTTP fallback saw the Ashby SPA
        # shell answer 200 for a posting that no longer exists.
        return ("unknown", "", f"ashby board did not parse: {type(exc).__name__}")
    if m[2] in ids:
        return ("alive", "definitive", "ashby board lists it")
    return ("dead", "definitive", "ashby board no longer lists it")


def check_lever(url: str):
    m = re.search(r"jobs\.lever\.co/([\w-]+)/([0-9a-f-]{36})", url)
    if not m:
        return None
    code, _, _ = _get(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}")
    if code == 200:
        return ("alive", "definitive", "lever api 200")
    if code in (404, 410):
        return ("dead", "definitive", f"lever api {code}")
    return None


def check_gh_embed(url: str):
    """A company careers page that embeds Greenhouse via ?gh_jid=NNNN.

    ADDED 2026-09-09 after a false negative: DigitalOcean row #61 sat 'alive' for
    19 days because the careers URL returns HTTP 200 and injects the posting
    client-side, so there was no dead text to match.

    REWRITTEN THE SAME DAY after the first version did real damage. It guessed the
    board token from the hostname, and a WRONG TOKEN 404s exactly like a retired
    job. That produced seven "definitive dead" verdicts, six of them false, and
    six live rows were withdrawn. DigitalOcean's real token is "digitalocean98",
    which no hostname rule would ever produce; it lives in a Next.js chunk under
    /careers/position/apply.

    So the rule now is: a token is only trusted after the BOARD ITSELF answers with
    jobs. If the board does not resolve, this returns UNKNOWN and the row is left
    alone. A false drop is invisible and permanent; a false keep costs one click.
    """
    m = re.search(r"[?&]gh_jid=(\d+)", url)
    if not m:
        return None
    jid = m.group(1)
    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].split(".")[0]

    for tok in (host, host.replace("-", "")):
        bcode, _, bbody = _get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs", limit=None)
        if bcode != 200:
            continue
        try:
            if not json.loads(bbody).get("jobs"):
                continue
        except Exception:
            continue
        # The board is real, so a 404 on the job is the job and not the token.
        jcode, _, _ = _get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs/{jid}")
        if jcode == 200:
            return ("alive", "definitive", f"greenhouse board {tok} serves job {jid}")
        if jcode in (404, 410):
            return ("dead", "definitive", f"greenhouse board {tok} no longer has job {jid}")
        return None

    # No verified board. Never guess a job dead from an unverified token.
    return ("unknown", "", f"greenhouse embed, board token for {host} not resolved")


def check_generic(url: str):
    code, final, body = _get(url)
    if code is None:
        return ("unknown", "", body[:90])
    if code in (404, 410):
        return ("dead", "likely", f"http {code}")
    if code >= 500:
        return ("unknown", "", f"http {code}, server side")
    if final != url and BOARD_ROOT.search(final):
        return ("dead", "likely", f"redirected to a board root: {final[:70]}")
    m = DEAD_TEXT.search(body)
    if m:
        return ("dead", "likely", f'text: "{m.group(0)[:48]}"')
    return ("alive", "", f"http {code}")


def check(row: dict) -> dict:
    url = (row.get("url") or "").strip()
    if not url.startswith("http"):
        return {**row, "verdict": "unknown", "confidence": "", "why": "no usable url"}
    for probe in (check_greenhouse, check_ashby, check_lever, check_gh_embed):
        r = probe(url)
        if r:
            return {**row, "verdict": r[0], "confidence": r[1], "why": r[2]}
    r = check_generic(url)
    return {**row, "verdict": r[0], "confidence": r[1], "why": r[2]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="discovered",
                    help="which pipeline status to sweep (default: discovered)")
    ap.add_argument("--older-than", type=int, default=0,
                    help="only rows discovered at least N days ago")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--commit", action="store_true",
                    help="withdraw rows found dead")
    ap.add_argument("--include-likely", action="store_true",
                    help="with --commit, also withdraw heuristic (likely) deaths")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    conn = connect()
    conn.row_factory = sqlite3.Row
    q = "SELECT id, company, role, url, discovered_at FROM applications WHERE status=?"
    args: list = [a.status]
    if a.older_than:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=a.older_than)).isoformat()
        q += " AND discovered_at <= ?"
        args.append(cutoff)
    q += " ORDER BY id"
    if a.limit:
        q += f" LIMIT {int(a.limit)}"
    rows = [dict(r) for r in conn.execute(q, args)]
    if not rows:
        print(f"no rows with status '{a.status}'")
        return 0

    print(f"checking {len(rows)} '{a.status}' rows with {a.workers} workers ...\n")
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        results = list(ex.map(check, rows))

    dead_def = [r for r in results if r["verdict"] == "dead" and r["confidence"] == "definitive"]
    dead_lik = [r for r in results if r["verdict"] == "dead" and r["confidence"] == "likely"]
    unknown = [r for r in results if r["verdict"] == "unknown"]
    alive = [r for r in results if r["verdict"] == "alive"]

    if a.json:
        print(json.dumps(results, indent=2))
    else:
        for label, group in (("DEAD (definitive)", dead_def), ("DEAD (likely)", dead_lik)):
            if not group:
                continue
            print(f"{label}  {len(group)}")
            for r in group:
                print(f"  #{r['id']:<4} {(r['company'] or '')[:26]:28} "
                      f"{(r['role'] or '')[:42]:44} {r['why']}")
            print()
        if unknown:
            print(f"UNKNOWN  {len(unknown)}  (never withdrawn automatically)")
            for r in unknown[:10]:
                print(f"  #{r['id']:<4} {(r['company'] or '')[:26]:28} {r['why'][:60]}")
            if len(unknown) > 10:
                print(f"  ... and {len(unknown) - 10} more")
            print()
        print(f"alive {len(alive)}   dead {len(dead_def) + len(dead_lik)} "
              f"({len(dead_def)} definitive, {len(dead_lik)} likely)   unknown {len(unknown)}")

    if not a.commit:
        if dead_def or dead_lik:
            print("\ndry run, nothing changed. To retire them:")
            print("  python scripts/liveness_check.py --commit"
                  + ("  --include-likely" if dead_lik else ""))
        return 0

    to_close = dead_def + (dead_lik if a.include_likely else [])
    for r in to_close:
        conn.execute(
            "UPDATE applications SET status='withdrawn', closed_at=?, updated_at=?, "
            "notes=COALESCE(NULLIF(notes,''),'') || ? WHERE id=?",
            (now(), now(),
             f"[liveness {datetime.now().date()}] posting is dead ({r['confidence']}): {r['why']}.",
             r["id"]))
        conn.execute(
            "INSERT INTO interactions (application_id, kind, direction, summary, "
            "occurred_at, created_at) VALUES (?,?,?,?,?,?)",
            (r["id"], "status_change", "in", f"discovered -> withdrawn (posting dead: {r['why']})",
             now(), now()))
        # A task on a dead application is worse than no task.
        conn.execute("UPDATE tasks SET status='dropped', completed_at=? "
                     "WHERE application_id=? AND status='open'", (now(), r["id"]))
    conn.commit()
    print(f"\nwithdrew {len(to_close)} row(s)"
          + ("" if a.include_likely else f", left {len(dead_lik)} 'likely' alone"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
