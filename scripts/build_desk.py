#!/usr/bin/env python3
"""Regenerate the desk's tables from pipeline.db.

The desk was hand-edited for its first two weeks, which meant the open-roles
table was a frozen snapshot: the daily watcher kept adding rows to the pipeline
and none of them reached the page, while roles that had since been applied to
stayed listed as open. This rebuilds both tables and the counters from the
database so the page cannot drift from the pipeline again.

Everything outside the two <tbody> blocks and the status strip is left alone,
so the notes, the contacts table and the CSS survive untouched.
"""
import json, re, subprocess, sys, html
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
# Default anchored to the repo, not the cwd. It used to be the bare string
# "desk.html", so the script only worked when run from inside data/ and died
# with FileNotFoundError everywhere else. Same class of defect as the dead
# skill paths: fix the path, do not work around it.
DESK = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "data" / "desk.html"


def pipeline(status):
    out = subprocess.run([sys.executable, str(HERE / "pipeline.py"),
                          "list", "--status", status, "--json"],
                         capture_output=True, text=True).stdout
    return json.loads(out or "[]")


def esc(s):
    return html.escape(str(s or ""), quote=True)


def open_rows(rows, fold_after=12):
    """Roles still to apply to. Anything we recorded as INELIGIBLE is dropped:
    those are kept in the pipeline so the watcher does not resurface them, not
    because they belong on a page of things to do."""
    rows = [r for r in rows if "INELIGIBLE" not in (r.get("role") or "")]
    rows.sort(key=lambda r: -(r.get("id") or 0))
    out = []
    for i, r in enumerate(rows):
        cls = "" if i < fold_after else "more"
        loc = (r.get("location") or "")[:24]
        out.append(
            f'          <tr class="{cls}"><td class="mono">{r["id"]}</td>'
            f'<td class="co">{esc(r["company"])[:26]}</td>'
            f'<td>{esc(r["role"])[:58]}</td>'
            f'<td class="mono">{esc(loc)}</td>'
            f'<td><a class="apply" href="{esc(r.get("url") or "#")}" target="_blank" '
            f'rel="noopener">Apply</a></td></tr>')
    return "\n".join(out), len(rows)


PILL = {"applied": ("p-new", "Applied"), "screening": ("p-ok", "In process"),
        "rejected": ("p-crit", "Rejected")}


def sent_rows(groups):
    out = []
    # in-process first, then applied, then rejections at the bottom
    for status in ("screening", "applied", "rejected"):
        rows = sorted(groups.get(status, []), key=lambda r: -(r.get("id") or 0))
        for r in rows:
            cls, label = PILL[status]
            out.append(
                f'          <tr><td class="mono">{r["id"]}</td>'
                f'<td class="co">{esc(r["company"])[:26]}</td>'
                f'<td>{esc(r["role"])[:58]}</td>'
                f'<td class="age">{esc((r.get("applied_at") or "")[:10])}</td>'
                f'<td><span class="pill {cls}">{label}</span></td>'
                f'<td><a class="apply" href="{esc(r.get("url") or "#")}" target="_blank" '
                f'rel="noopener">View</a></td></tr>')
    return "\n".join(out)


def swap_tbody(doc, table_id, body):
    i = doc.index(f'<table id="{table_id}">')
    a = doc.index("<tbody>", i) + len("<tbody>")
    b = doc.index("</tbody>", a)
    return doc[:a] + "\n" + body + "\n        " + doc[b:]


def main():
    groups = {s: pipeline(s) for s in
              ("discovered", "applied", "screening", "rejected")}
    doc = DESK.read_text()

    body, n_open = open_rows(groups["discovered"])
    doc = swap_tbody(doc, "t-open", body)
    doc = swap_tbody(doc, "t-app", sent_rows(groups))

    n_sent = len(groups["applied"]) + len(groups["screening"]) + len(groups["rejected"])
    counts = {"Open to apply": n_open, "Actually sent": n_sent,
              "In process": len(groups["screening"]),
              "Replies": len(groups["rejected"])}
    for label, n in counts.items():
        doc = re.sub(r'(<div class="n">)\d+(</div><div class="k">' + re.escape(label) + ')',
                     rf'\g<1>{n}\g<2>', doc)
    doc = re.sub(r'(<h2>1 &middot; Open now &mdash; )\d+', rf'\g<1>{n_open}', doc)
    doc = re.sub(r'(<h2>2 &middot; Sent &mdash; )\d+', rf'\g<1>{n_sent}', doc)
    doc = re.sub(r'(data-t="t-open" data-n=")\d+(">Show all )\d+',
                 rf'\g<1>{max(0, n_open - 12)}\g<2>{n_open}', doc)

    # The date stamp and the section-2 heading were outside every rewrite, so a
    # freshly rebuilt page still read "2 SEP 2026 / 35 sent". Srikar read stale
    # rows off it for five days and re-reported them twice. Refresh them here.
    stamp = datetime.now().strftime("%-d %b %Y").upper()
    doc = re.sub(r'(<div class="stamp">[^<]*<br>)[^<]*(</div>)', rf'\g<1>{stamp}\g<2>', doc)
    doc = re.sub(
        r'(<h2>2 &middot; Sent &mdash; )\d+( confirmed by email, )\d+( in process, )\d+( rejected)',
        rf'\g<1>{n_sent}\g<2>{len(groups["screening"])}\g<3>{len(groups["rejected"])}\g<4>', doc)

    DESK.write_text(doc)
    print(f"desk rebuilt: {n_open} open, {n_sent} sent "
          f"({len(groups['screening'])} in process, {len(groups['rejected'])} rejected)")


if __name__ == "__main__":
    main()
