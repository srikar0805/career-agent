#!/usr/bin/env python3
"""Fill a Greenhouse application in a visible Chrome window, then STOP.

Srikar asked on 2026-09-16 for the application to be filled automatically, and
earlier the same day chose staged submission: he presses submit. So this types
the answers, uploads the resume, marks what needs his eyes, and hands the window
to him. It has no code path that submits: the only clicks it makes are on
dropdown options, and a guard refuses any element that looks like a submit,
apply or send control.

What gets filled:
  FILLED and CONFIRM answers from prefill.py (CONFIRM fields get a yellow outline)
  the resume PDF recorded for the row
  CHECKED open-ended answers from the packet's "## Written answers" (DRAFT ones are not)
What never gets filled:
  DECISION (consents, attestations, pronouns, EEO, location preferences)
  NEEDS YOU (left blank with a red outline when required)

The page's field ids are the Greenhouse API field names (first_name, resume,
question_15028917008), verified against a live form on 2026-09-16.

    autofill.py --app 300                     open the real form, fill, wait for you
    autofill.py --app 300 --url file:///...   fill a local copy (tests)
    autofill.py --app 300 --url ... --headless --screenshot out.png

Chrome runs with its own profile in data/.autofill-chrome: signed out of
everything, no access to his normal browser sessions.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from form_check import greenhouse_questions             # noqa: E402
from prefill import answer, artifact_path, board_token, load_row, write_packet   # noqa: E402

PROFILE_DIR = ROOT / "data" / ".autofill-chrome"
FORBIDDEN = re.compile(r"submit|apply|send|finish|confirm\s+application", re.I)


def written_answers(packet: Path) -> dict[str, str]:
    """CHECKED answers from the packet, keyed by question label."""
    text = packet.read_text() if packet.exists() else ""
    if "## Written answers" not in text:
        return {}
    out = {}
    for block in text.split("## Written answers", 1)[1].split("\n### ")[1:]:
        label, _, body = block.partition("\n")
        parts = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
        if len(parts) >= 2 and parts[-1].startswith("_CHECKED"):
            out[label.strip()] = "\n\n".join(parts[:-1])
    return out


def plan(app_id: int) -> tuple[str, list[dict]]:
    row = load_row(app_id)
    gh = greenhouse_questions(row.get("url") or "", board_token(row))
    if not gh or gh[2] is None:
        raise SystemExit(f"#{app_id}: not a readable Greenhouse form. Open {row.get('url')} and use the packet.")
    tok, jid, questions = gh
    packet, _, _ = write_packet(app_id)
    ready = written_answers(packet)
    steps, prev = [], None
    for q in questions:
        res = answer(q, row, prev)
        prev = res
        for f in (q.get("fields") or [])[:1]:
            name, ftype = f.get("name", ""), f.get("type", "")
            step = {"id": name, "type": ftype, "label": res["label"], "status": res["status"],
                    "required": res["required"], "value": res["answer"]}
            if ftype == "input_file":
                p = artifact_path(app_id, "resume") if name == "resume" else artifact_path(app_id, "cover_letter")
                step.update(value=p if p and Path(p).exists() else "", status="FILLED" if p and Path(p).exists() else "NEEDS YOU")
            elif res["status"] == "OPEN":
                text = ready.get(res["label"], "")
                step.update(value=text, status="FILLED" if text else "OPEN")
            elif name in ("resume_text", "cover_letter_text"):
                step.update(value="", status="SKIP")
            steps.append(step)
    steps += standard_sections()
    # The EMBED url, not /{tok}/jobs/{jid}: C3.ai hosts its form inside c3.ai, and on
    # 2026-09-16 the board page for c3iot showed only a site search box, no form at all.
    return f"https://job-boards.greenhouse.io/embed/job_app?for={tok}&token={jid}", steps


def standard_sections() -> list[dict]:
    """Greenhouse's built-in location, education and EEO blocks. The questions API does not
    list them, but C3.ai's form requires seven of them (read from the live page 2026-09-16).
    Each is filled only if it exists on the page. EEO answers are always his decision."""
    import yaml
    idn = yaml.safe_load((ROOT / "profile" / "identity.yaml").read_text())
    ms = next((e for e in idn.get("education", []) if "M.S." in e.get("degree", "")), {})
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
              "October", "November", "December"]
    sy, sm = (ms.get("start") or "2025-08").split("-")
    ey, em = (ms.get("expected_graduation") or "2027-05").split("-")

    def combo(fid, label, typed, patterns, status="FILLED", required=True):
        return {"id": fid, "type": "combobox", "label": label, "status": status, "required": required,
                "value": typed, "patterns": patterns, "optional_field": True}

    def text(fid, label, value):
        return {"id": fid, "type": "input_text", "label": label, "status": "FILLED", "required": True,
                "value": value, "optional_field": True}
    return [
        combo("country", "Country", "United States",   # Capco spells it differently; never the Minor Outlying Islands
              [r"^\s*United States\s*$", r"^\s*United States of America\b", r"^\W*United States(?!.*(Minor|Outlying|Virgin))", r"^\s*USA\b"]),
        combo("candidate-location", "Location (City)", "Columbia", [r"^\s*Columbia,\s*Missouri", r"Columbia.*(Missouri|\bMO\b)"]),
        combo("school--0", "School", "University of Missouri",
              [r"University of Missouri\W*Columbia", r"^\s*University of Missouri\s*$", r"University of Missouri(?!.*(Kansas|St\.? Louis|Science))"],
              status="CONFIRM"),
        combo("degree--0", "Degree", "Master", [r"^\s*Master'?s?\s+Degree\s*$", r"^\s*Master"]),
        combo("discipline--0", "Discipline", "Computer",
              [r"^\s*Computer and Information Sciences?\s*$", r"^\s*Computer Science\s*$", r"Computer"], status="CONFIRM"),
        combo("start-month--0", "Start date month", months[int(sm) - 1], [rf"^\s*{months[int(sm) - 1]}\s*$"]),
        text("start-year--0", "Start date year", sy),
        combo("end-month--0", "End date month", months[int(em) - 1], [rf"^\s*{months[int(em) - 1]}\s*$"]),
        text("end-year--0", "End date year", ey),
    ] + [{"id": fid, "type": "combobox", "label": label, "status": "DECISION", "required": False, "value": "",
          "optional_field": True}
         for fid, label in (("gender", "Gender"), ("hispanic_ethnicity", "Hispanic/Latino"),
                            ("veteran_status", "Veteran status"), ("disability_status", "Disability status"))]


async def fill(url: str, steps: list[dict], headless: bool, screenshot: str | None) -> dict:
    from playwright.async_api import async_playwright
    done = {"filled": [], "confirm": [], "left_for_you": [], "failed": []}
    async with async_playwright() as p:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        ctx = await p.chromium.launch_persistent_context(str(PROFILE_DIR), channel="chrome", headless=headless,
                                                         viewport={"width": 1280, "height": 900})
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(url, wait_until="networkidle", timeout=90000)

        async def safe_click(loc):
            """Click a dropdown option and nothing else. Buttons, links, submit inputs,
            forms, and anything not marked role=option are refused outright."""
            meta = await loc.evaluate("""e => ({tag: e.tagName, type: e.type || '', role: e.getAttribute('role') || '',
                                               text: (e.innerText || e.value || '').trim().slice(0, 60),
                                               inButton: !!e.closest('button, a, [type=submit]')})""")
            if (meta["role"] != "option" or meta["tag"] in ("BUTTON", "A", "FORM") or meta["type"] == "submit"
                    or meta["inButton"] or re.match(r"^\s*(submit|apply now|send application)\b", meta["text"], re.I)):
                raise RuntimeError(f"refused to click {meta['tag'].lower()} '{meta['text'][:40]}': not a dropdown option")
            await loc.click()

        def field(fid: str):
            # Attribute selectors, never "#id": Greenhouse multi-selects are named "question_38291335002[]"
            # and render as "question_38291335002[]_<option id>", neither of which is a valid #selector.
            base = fid[:-2] if fid.endswith("[]") else fid
            return page.locator(f'[id="{base}"]') if not fid.endswith("[]") else page.locator(f'[id^="{base}[]"]')

        async def outline(fid: str, colour: str):
            try:
                loc = field(fid)
                if await loc.count():
                    await loc.first.evaluate(f"e => e.style.outline = '3px solid {colour}'")
            except Exception:
                pass                                   # a cosmetic outline must never stop the fill

        for s in steps:
            present = await field(s["id"]).count() > 0
            if s.get("optional_field") and not present:
                continue                               # a standard section this form does not have
            if s["status"] in ("DECISION", "NEEDS YOU", "OPEN", "SKIP") or not s["value"]:
                # a conditional follow-up ("if you answered yes...") is not his to answer unless he said yes
                if s["required"] and s["status"] != "SKIP" and not re.match(r"\s*if\s+you", s["label"], re.I):
                    done["left_for_you"].append(f"{s['status']}: {s['label'][:80]}")
                    await outline(s["id"], "#d33")
                continue
            try:
                if not present:
                    raise RuntimeError("field not on the page")
                box = field(s["id"]).first
                if s["type"] == "input_file":
                    await box.set_input_files(s["value"])
                elif s["type"].startswith("multi_value") or s["type"] == "combobox":
                    # a FORCED click: these menus open on mousedown, and Capco's city input is 3.5px wide
                    # inside a wrapper, so a normal click never passes Playwright's checks and times out
                    # after 30s (2026-09-16). Focus alone does not open the menu either; tested live.
                    await box.click(force=True, timeout=5000)
                    await box.fill(s["value"][:60], timeout=10000)
                    # Poll, do not guess a delay: school and city lists come from a search API that took
                    # longer than a fixed 6s on Srikar's Capco run (2026-09-16). Retype key by key once.
                    visible = page.locator("[role=option]:visible")   # only the open menu's options
                    patterns = s.get("patterns") or [rf"^\s*{re.escape(s['value'])}\s*$", re.escape(s["value"][:60])]
                    opt = None
                    for attempt in range(2):
                        if attempt == 1:
                            await box.fill("")
                            await box.press_sequentially(s["value"][:60], delay=50)
                        for _ in range(24):
                            await page.wait_for_timeout(500)
                            for pat in patterns:
                                cand = visible.filter(has_text=re.compile(pat, re.I))
                                if await cand.count():
                                    opt = cand.first
                                    break
                            if opt is not None:
                                break
                        if opt is not None:
                            break
                    if opt is None:
                        await box.fill("")
                        raise RuntimeError(f"no option matched '{s['value'][:40]}' within 24s")
                    await safe_click(opt)
                else:
                    # InterSystems "Employment History" (2026-09-16) is not a text box on the page, so
                    # fill() threw. A widget this cannot type into is his to answer, not a failure.
                    fillable = await box.evaluate("e => ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.tagName) || e.isContentEditable")
                    if not fillable:
                        done["left_for_you"].append(f"not a text box, answer it by hand: {s['label'][:70]}")
                        await outline(s["id"], "#d33")
                        continue
                    await box.fill(s["value"])
                done["filled"].append(s["label"][:80])
                if s["status"] == "CONFIRM":
                    done["confirm"].append(s["label"][:80])
                    await outline(s["id"], "#e0b000")
            except Exception as e:
                done["failed"].append(f"{s['label'][:70]}: {str(e).splitlines()[0][:90]}")
                await outline(s["id"], "#d33")

        banner = (f"career-agent filled {len(done['filled'])} field(s). Yellow = check the value. "
                  f"Red = yours to answer ({len(done['left_for_you'])}). Consents are untouched. "
                  "Nothing was submitted: review everything, then press Submit yourself.")
        await page.evaluate("""(t) => { const d = document.createElement('div'); d.textContent = t;
            d.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#1b6b66;color:#fff;padding:10px 16px;font:14px system-ui';
            document.body.appendChild(d); window.scrollTo(0, 0); }""", banner)
        if screenshot:
            await page.screenshot(path=screenshot, full_page=True)
        if headless:                                   # tests read back what landed on the page
            done["values"] = await page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('input[id],textarea[id]')]
                .map(e => [e.id, e.type === 'file' ? [...e.files].map(f => f.name).join(',') : e.value]))""")
            done["submitted"] = await page.evaluate("window.SUBMITTED === true")
        if not headless:
            print("window is yours: review, answer the red fields, press Submit, then close the window.")
            await page.wait_for_event("close", timeout=0)
        await ctx.close()
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", type=int, required=True)
    ap.add_argument("--url", help="override the form URL (a local copy for tests)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--screenshot")
    a = ap.parse_args()
    url, steps = plan(a.app)
    done = asyncio.run(fill(a.url or url, steps, a.headless, a.screenshot))
    print(f"filled {len(done['filled'])}, to confirm {len(done['confirm'])}, left for you {len(done['left_for_you'])}, failed {len(done['failed'])}")
    for x in done["left_for_you"]:
        print("  yours:  ", x)
    for x in done["failed"]:
        print("  failed: ", x)
    print("NOT submitted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
