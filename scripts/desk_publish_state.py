#!/usr/bin/env python3
"""Track whether data/desk.html has changed since it was last PUBLISHED.

The daily run rebuilds desk.html but cannot publish it: Stage 2 has no Artifact
tool. So the published page only moves when an interactive session republishes,
and it drifts silently in between. On 2026-09-13 Srikar found both Mulligan rows
still listed as open on the published page; the local file had been correct for
days and the published one was stamped 9 SEP, four days behind. The same class of
staleness bit once before, on 2 September.

This makes the drift loud instead of silent, the same way the Stage 2 failure
banner does.

    desk_publish_state.py mark  [path]   record the current content as published
    desk_publish_state.py check [path]   exit 0 fresh, 1 stale, 2 never marked

WHY IT HASHES A SUBSET, NOT THE FILE. build_desk.py rewrites the date stamp on
every single run, so a whole-file hash would differ every day even when nothing
substantive moved, and a warning that fires daily is a warning nobody reads.
What actually matters to a reader is the status-strip counters and the table
rows, so only those are hashed. Change a row, change the hash. Change only the
date, and the hash holds.
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_DESK = REPO / "data" / "desk.html"
STATE = REPO / "data" / ".desk_published.json"


def content_hash(path: Path) -> str:
    """Hash the counters and the table bodies, nothing else."""
    s = path.read_text(encoding="utf-8", errors="replace")
    counters = re.findall(r'<div class="n">(\d+)</div>', s)
    bodies = re.findall(r"<tbody.*?</tbody>", s, re.S)
    payload = "|".join(counters) + "\n" + "\n".join(bodies)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    desk = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DESK

    if not desk.exists():
        print(f"desk-publish: {desk} not found")
        return 0  # nothing to warn about

    now = content_hash(desk)

    if cmd == "mark":
        STATE.write_text(json.dumps({
            "hash": now,
            "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "path": str(desk),
        }, indent=2) + "\n")
        print(f"desk-publish: marked as published, {now[:12]}")
        return 0

    if cmd != "check":
        print(__doc__)
        return 2

    prev = load()
    if not prev:
        print("desk-publish: STALE, no publish has ever been recorded")
        return 2
    if prev.get("hash") == now:
        print(f"desk-publish: fresh, published {prev.get('published_at', '?')[:10]}")
        return 0

    print("desk-publish: STALE, the rows or counters changed since the last publish "
          f"on {prev.get('published_at', '?')[:10]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
