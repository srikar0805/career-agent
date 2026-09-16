#!/usr/bin/env python3
"""Daily diff of Srikar's GitHub against the last snapshot.

The evidence bank goes stale the moment he ships something. This watches for
that and says what changed, so a new project becomes a resume bullet within a
day instead of whenever someone remembers to look.

It reports, it does not rewrite. Turning a commit burst into an evidence atom
needs judgement about what was actually built and by whom, and the bank's whole
value is that every atom is verified. So this produces a review queue.

What it tracks per repo: pushed_at, language byte counts, stars, description,
and whether the repo is new. Plus authored PRs across all of GitHub.

Usage:
    python scripts/sync_github.py                  # diff vs last snapshot
    python scripts/sync_github.py --save           # diff, then update snapshot
    python scripts/sync_github.py --init           # first snapshot, no diff
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "raw" / "github_snapshot.json"
USER = "srikar0805"


def gh(args: list[str]) -> str:
    p = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=180)
    if p.returncode:
        sys.exit(f"gh failed: {p.stderr.strip()[:300]}")
    return p.stdout


def snapshot() -> dict:
    raw = gh(["repo", "list", USER, "--limit", "200", "--json",
              "name,pushedAt,description,stargazerCount,isPrivate,languages"])
    repos = {}
    for r in json.loads(raw):
        repos[r["name"]] = {
            "pushedAt": r.get("pushedAt"),
            "description": (r.get("description") or "")[:200],
            "stars": r.get("stargazerCount", 0),
            "private": r.get("isPrivate", False),
            "langs": {l["node"]["name"]: l["size"] for l in (r.get("languages") or [])},
        }
    prs = json.loads(gh(["search", "prs", "--author", USER, "--limit", "100",
                         "--json", "repository,title,state,url"]) or "[]")

    # Repos he does not OWN. `gh repo list <user>` returns only owned repos, and
    # the PR search above only catches pull requests, so a direct commit to an
    # organisation repo was invisible to every scan. That is how
    # PAAL-Projects/Realsense-commercial-barn-setup, his ONLY C++ evidence, sat
    # unrecorded until he pointed at it on 2026-08-30. Never rely on ownership
    # to decide what counts as his work.
    external = {}
    try:
        commits = json.loads(gh(["search", "commits", "--author", USER,
                                 "--limit", "100", "--json",
                                 "repository,sha,commit"]) or "[]")
    except SystemExit:
        commits = []                      # commit search is not always enabled
    for c in commits:
        r_ = c.get("repository", {})
        full = r_.get("fullName") or r_.get("nameWithOwner") or ""
        if not full or full.split("/")[0].lower() == USER.lower():
            continue                      # owned repos already covered above
        e = external.setdefault(full, {"commits": 0, "langs": {}, "last": ""})
        e["commits"] += 1
        d = (c.get("commit") or {}).get("author", {}).get("date", "") or ""
        e["last"] = max(e["last"], d[:10])
    for full in external:
        try:
            external[full]["langs"] = json.loads(
                gh(["api", f"repos/{full}/languages"]) or "{}")
        except SystemExit:
            pass

    return {"taken": datetime.now(timezone.utc).isoformat(),
            "repos": repos,
            "external": external,
            "prs": {p["url"]: {"title": p["title"], "state": p["state"],
                               "repo": p["repository"]["nameWithOwner"]} for p in prs}}


def human(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


def diff(old: dict, new: dict) -> list[str]:
    out = []
    o, n = old.get("repos", {}), new.get("repos", {})

    for name in sorted(set(n) - set(o)):
        r = n[name]
        top = ", ".join(f"{k} {human(v)}" for k, v in
                        sorted(r["langs"].items(), key=lambda x: -x[1])[:3])
        out.append(f"NEW REPO   {name}{' [private]' if r['private'] else ''}  ({top or 'no code yet'})")
        if r["description"]:
            out.append(f"           {r['description']}")

    for name in sorted(set(o) & set(n)):
        a, b = o[name], n[name]
        if a["pushedAt"] != b["pushedAt"]:
            grew = []
            for lang, size in b["langs"].items():
                d = size - a["langs"].get(lang, 0)
                if d > 0:
                    grew.append(f"{lang} +{human(d)}")
            for lang in set(a["langs"]) - set(b["langs"]):
                grew.append(f"{lang} removed")
            detail = ", ".join(grew) if grew else "no net size change"
            out.append(f"PUSHED     {name}  ({detail})")
        if a["stars"] != b["stars"]:
            out.append(f"STARS      {name}  {a['stars']} -> {b['stars']}")

    op, np_ = o and old.get("prs", {}) or {}, new.get("prs", {})
    oe, ne = old.get("external", {}), new.get("external", {})
    for full in sorted(set(ne) - set(oe)):
        e = ne[full]
        langs = ", ".join(sorted(e["langs"], key=lambda k: -e["langs"][k])[:3])
        out.append(f"EXTERNAL   {full}  {e['commits']} commit(s), last {e['last']}"
                   + (f"  [{langs}]" if langs else "")
                   + "  <- NOT owned by him; check what he actually wrote")
    for full in sorted(set(ne) & set(oe)):
        if ne[full]["commits"] != oe[full].get("commits"):
            out.append(f"EXTERNAL   {full}  commits {oe[full].get('commits')} -> {ne[full]['commits']}")

    for url in sorted(set(np_) - set(op)):
        p = np_[url]
        out.append(f"NEW PR     {p['repo']}  [{p['state']}]  {p['title'][:60]}")
    for url in sorted(set(op) & set(np_)):
        if op[url]["state"] != np_[url]["state"]:
            out.append(f"PR STATE   {np_[url]['repo']}  {op[url]['state']} -> {np_[url]['state']}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--init", action="store_true")
    a = ap.parse_args()

    new = snapshot()
    SNAP.parent.mkdir(parents=True, exist_ok=True)

    if a.init or not SNAP.exists():
        SNAP.write_text(json.dumps(new, indent=1))
        langs = {}
        for r in new["repos"].values():
            for k, v in r["langs"].items():
                langs[k] = langs.get(k, 0) + v
        print(f"snapshot written: {len(new['repos'])} repos, {len(new['prs'])} authored PRs")
        print("languages: " + ", ".join(f"{k} {human(v)}" for k, v in
                                        sorted(langs.items(), key=lambda x: -x[1])[:8]))
        return 0

    old = json.loads(SNAP.read_text())
    changes = diff(old, new)
    since = old.get("taken", "?")[:16].replace("T", " ")
    print(f"github since {since}: {len(changes)} change(s)")
    for c in changes:
        print("  " + c)
    if not changes:
        print("  nothing new")
    else:
        print("\nReview these for the evidence bank. Nothing is written to")
        print("profile/evidence.yaml automatically; an atom needs verified authorship.")
    if a.save:
        SNAP.write_text(json.dumps(new, indent=1))
        print("\nsnapshot updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
