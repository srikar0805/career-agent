#!/usr/bin/env python3
"""NVIDIA agent: fit a base resume's Experience and Projects to the approved bullet form, by choosing, never writing.

Srikar, 2026-09-17: the bullets were "very weak" and "vague"; he approved a rewrite in the form
of a friend's Amazon-offer resume (Srikar_Resume_DigitalOcean) and then said "You are using too
much of Opus 5 ... you can use NVIDIA models also". Opus wrote and fact-traced the bullets once:
data/artifacts/_bullet_library/library.md plus the bases already rewritten. This agent only
selects and orders from that pool for another base's target role, so it cannot introduce a claim.

Checked, not trusted:
  every bullet is, character for character, a bullet from the pool (library or a rewritten base)
  every bullet sits under the job or project it was written for
  every job keeps its header exactly (titles, dates) and its order; SP Software and HiringFIT keep one or more
  no two near-duplicate bullets, no git statistics (lines, files), nothing from a HOLD project
  the page compiles and passes all six PDF gates; on a page-fill failure the model gets the
  gate output and adjusts, up to 4 rounds, and the base is restored if nothing passes

    agent_bullets.py --base Srikar_Resume_StudyFetch
    agent_bullets.py --base Srikar_Resume_StudyFetch --dry-run     print the choice, write nothing
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
LIB = ROOT / "data" / "artifacts" / "_bullet_library" / "library.md"
RES = ROOT / "latex" / "resume"
BLOCK = re.compile(r"\\(experienceItem|customItem)\[(.*?)\n\s*\]\s*\\begin\{itemize\}(.*?)\\end\{itemize\}", re.S)
GIT_STATS = re.compile(r"\d[\d,]*\s+lines|\bacross \d+ files|\+\d[\d,]* lines", re.I)


def job_key(text: str) -> str:
    t = text.lower()
    for key, pat in (("lab", r"agricultur|image engineer"), ("maq", r"\bmaq\b"), ("sp", r"sp software"), ("hiringfit", r"hiringfit")):
        if re.search(pat, t):
            return key
    return ""


def project_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.split(r"\{,\}|,", title.strip())[0].lower())[:14]


def plain(item: str) -> str:
    s = re.sub(r"\\textbf\{([^}]*)\}", r"\1", item)
    s = s.replace(r"\%", "%").replace(r"\&", "&").replace("~", " ")
    return re.sub(r"\s+", " ", re.sub(r"^\\item\s*", "", s)).strip()


def pool(exclude_base: str) -> tuple[dict, dict]:
    """bullets {id: {...}} and project headers {key: header latex}."""
    bullets, headers, seen = {}, {}, set()

    def add(text, comment, where, source):
        text = text.strip()
        if text in seen or GIT_STATS.search(text):
            return
        seen.add(text)
        ev = sorted(set(re.findall(r"EV-\d+[A-Z]?", comment)))
        fam = (re.search(r"\[(swe|data|ml|ai)\]", comment) or [None, ""])[1]
        bullets[f"B{len(bullets) + 1:03d}"] = {"latex": text, "comment": comment.strip(), "where": where, "ev": ev,
                                               "family": fam, "chars": len(plain(text)), "source": source}

    lines = LIB.read_text().splitlines()
    section, where, hold = "", "", False
    for i, l in enumerate(lines):
        if l.startswith("## "):
            section = l[3:].strip().lower()
        if section.startswith("questions") or section.startswith("not used"):
            break
        if l.startswith("### ") and section == "experience":
            where = job_key(l)
        if l.startswith("#### "):
            hold = False
            if section == "projects":
                where = "project:" + project_key(l.split(",", 1)[1] if "," in l else l[5:])
        if l.startswith("Status:") and "HOLD" in l:
            hold = True
        if l.startswith(r"\item") and where and not hold:
            comment = lines[i + 1] if i + 1 < len(lines) and lines[i + 1].lstrip().startswith("%") else ""
            add(l, comment, where, "library")
    for d in sorted(RES.glob("Srikar_Resume_*/main.pre-bullets.tex")):
        base = d.parent
        if base.name == exclude_base or not (base / "main.tex").exists():
            continue
        tex = (base / "main.tex").read_text()
        if tex == d.read_text():
            continue                                    # not rewritten
        for kind, head, body in BLOCK.findall(tex):
            if kind == "experienceItem":
                where = job_key(head)
            else:
                title = re.search(r"title=(.*?),\s*\n", head + "\n").group(1)
                where = "project:" + project_key(title)
                headers.setdefault(where, "\\customItem[" + head + "\n    ]")
            items = re.findall(r"(\\item [^\n]*)\n((?:\s*%[^\n]*\n)*)", body + "\n")
            for text, comment in items:
                add(text, comment, where, base.name)
    return bullets, headers


def base_parts(tex: str) -> tuple[int, int, list[tuple[str, str]]]:
    a = tex.index(r"\begin{workSection}{Experience}")
    b = tex.index(r"\skills{")
    jobs = [(job_key(h), "\\experienceItem[" + h + "\n    ]") for k, h, _ in BLOCK.findall(tex[a:b]) if k == "experienceItem"]
    return a, b, jobs


def assemble(choice: dict, jobs, bullets, headers) -> str:
    def items(ids):
        out = []
        for i in ids:
            x = bullets[i]
            out.append("        " + x["latex"] + ("\n        " + x["comment"] if x["comment"] else ""))
        return "\n".join(out)
    exp = [f"    {head}\n    \\begin{{itemize}}\n        \\itemsep -4pt {{}}\n{items(choice['experience'][key])}\n    \\end{{itemize}}\n"
           for key, head in jobs]
    proj = [f"    {headers[p['project']]}\n    \\begin{{itemize}}\n        \\itemsep -4pt {{}}\n{items(p['bullets'])}\n    \\end{{itemize}}\n"
            for p in choice["projects"]]
    return ("\\begin{workSection}{Experience}\n\n" + "\n".join(exp) + "\n\\end{workSection}\n\n"
            "\\begin{workSection}{Projects}\n\n" + "\n".join(proj) + "\n\\end{workSection}\n\n")


def validate(choice: dict, jobs, bullets, headers) -> list[str]:
    errs, used = [], []
    exp = choice.get("experience") or {}
    for key, _ in jobs:
        ids = exp.get(key) or []
        if not ids:
            errs.append(f"job {key} has no bullets; every job stays on the page")
        for i in ids:
            if i not in bullets:
                errs.append(f"{i} is not a pool id")
            elif bullets[i]["where"] != key:
                errs.append(f"{i} belongs to {bullets[i]['where']}, not {key}")
            used.append(i)
    for p in choice.get("projects") or []:
        if p.get("project") not in headers:
            errs.append(f"project {p.get('project')} has no header in the pool")
        for i in p.get("bullets") or []:
            if i not in bullets:
                errs.append(f"{i} is not a pool id")
            elif bullets[i]["where"] != p.get("project"):
                errs.append(f"{i} belongs to {bullets[i]['where']}, not {p.get('project')}")
            used.append(i)
    if len(set(used)) != len(used):
        errs.append("a bullet is used twice")
    words = {i: set(re.findall(r"[a-z0-9]+", plain(bullets[i]["latex"]).lower())) for i in used if i in bullets}
    ids = list(words)
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            a, b = words[ids[x]], words[ids[y]]
            if a and b and len(a & b) / len(a | b) > 0.55:
                errs.append(f"{ids[x]} and {ids[y]} say nearly the same thing; keep one")
    return errs


SYSTEM = """You assemble the Experience and Projects sections of a one-page resume for Sai Srikar Reddy Kolli by \
CHOOSING bullets from a fixed pool of approved, fact-checked bullets. You never write or edit a bullet; you return ids.
Rules:
- Every job listed keeps 1 or more bullets: lab 3 to 5, maq 3 to 5, sp exactly 1, hiringfit 1 or 2.
- Choose 2 or 3 projects that have a header, 1 or 2 bullets each.
- Pick what this base's target role reads first: its header comment says the role. Lead each job with its strongest bullet for that role. Prefer bullets whose family tag matches the role (swe, data, ml, ai).
- Never two bullets that make the same point.
- Page budget: a bullet under about 138 characters is 1 line, otherwise 2 lines. The approved reference page holds 27 bullet lines in these two sections; aim for 26 to 28 and adjust when told the page is under or over full.
Reply with ONE JSON object: {"experience": {"lab": [ids], "maq": [ids], "sp": [ids], "hiringfit": [ids]}, "projects": [{"project": "<project key>", "bullets": [ids]}], "why": "one sentence"}"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", help="pin one model (e.g. moonshotai/kimi-k3 while NVIDIA's Ultra times out)")
    a = ap.parse_args()
    from agent_keywords import compile_tex, gates
    from nim import NimError, chat

    d = RES / a.base
    tex_path = d / "main.tex"
    original = tex_path.read_text()
    if not (d / "main.pre-bullets.tex").exists():
        shutil.copy2(tex_path, d / "main.pre-bullets.tex")
        if (d / "main.pdf").exists():
            shutil.copy2(d / "main.pdf", d / "main.pre-bullets.pdf")
    src = (d / "main.pre-bullets.tex").read_text()
    start, end, jobs = base_parts(src)
    bullets, headers = pool(a.base)
    target = "\n".join(l for l in src.splitlines()[:30] if l.startswith("%"))[:1800]
    menu = "\n".join(f"{i} [{x['where']}] [{x['family'] or '-'}] {x['chars']}ch {'/'.join(x['ev'])}: {plain(x['latex'])}"
                     for i, x in bullets.items())
    prompt = (f"BASE: {a.base}\nTARGET ROLE (the base's header comment):\n{target}\n\n"
              f"JOBS ON THIS PAGE, in order: {', '.join(k for k, _ in jobs)}\n"
              f"PROJECT KEYS WITH HEADERS: {', '.join(sorted(headers))}\n\nPOOL:\n{menu}")
    feedback = ""
    for rnd in range(1, 5):
        try:
            res = chat("writer", SYSTEM, prompt + feedback, want_json=True, max_tokens=6000, temperature=0.2,
                       purpose=f"bullets {a.base}", model=a.model)
        except NimError as e:
            print(f"{a.base}: model unavailable: {e}")
            return 1
        choice = res.get("json") if isinstance(res.get("json"), dict) else {}
        errs = validate(choice, jobs, bullets, headers)
        if errs:
            feedback = "\n\nYOUR LAST ANSWER WAS REJECTED:\n- " + "\n- ".join(errs[:12]) + "\nFix these and answer again."
            print(f"  round {rnd} [{res['model'].split('/')[-1]}]: rejected, {len(errs)} problem(s): {errs[0]}", flush=True)
            continue
        new = src[:start] + assemble(choice, jobs, bullets, headers) + src[end:]
        if a.dry_run:
            print(json.dumps(choice, indent=1))
            return 0
        tex_path.write_text(new)
        g = gates(tex_path, d / "main.pdf") if compile_tex(tex_path) else {"compile": False}
        if all(g.values()):
            print(f"{a.base}: OK in round {rnd} [{res['model'].split('/')[-1]}], "
                  f"{sum(len(v) for v in choice['experience'].values()) + sum(len(p['bullets']) for p in choice['projects'])} bullets. {choice.get('why', '')[:160]}")
            return 0
        page = subprocess.run([sys.executable, str(HERE / "page_check.py"), str(d / "main.pdf")], capture_output=True, text=True)
        line = subprocess.run([sys.executable, str(HERE / "line_check.py"), str(d / "main.pdf")], capture_output=True, text=True)
        failed = [k for k, v in g.items() if not v]
        feedback = (f"\n\nYOUR LAST CHOICE COMPILED BUT FAILED: {failed}.\npage_check says:\n{(page.stdout + page.stderr)[-700:]}\n"
                    f"line_check says:\n{(line.stdout + line.stderr)[-500:]}\n"
                    "If the page is under full, add a bullet or swap a 1-line bullet for a 2-line one; if it spills to a "
                    "second page, drop or shorten one. If a bullet ends in a short last line, swap it for another variant.")
        print(f"  round {rnd} [{res['model'].split('/')[-1]}]: gates failed {failed}", flush=True)
    tex_path.write_text(original)
    compile_tex(tex_path)
    print(f"{a.base}: FAILED after 4 rounds; restored the base unchanged")
    return 1


if __name__ == "__main__":
    sys.exit(main())
