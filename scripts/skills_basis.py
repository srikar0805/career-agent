#!/usr/bin/env python3
"""Skills section: every technology the posting names that he has actually used. No model.

Srikar's rule, 2026-09-16: "if they mention any technologies, add them to the resume;
just add every skill, but for the experience, projects and education make sure they
are perfect." Agreed with one boundary he was told about: a technology he has NO
record of using is not written in, because application forms have him certify the
resume is accurate (Celonis: "I confirm the information provided in this
application, including but not limited to my resume... is accurate"). Those are
listed for him to confirm instead; one word from him adds them to profile/skills.yaml
and every later resume picks them up.

A technology counts as USED when any of these says so:
  profile/skills.yaml at any level except "unbacked" (working, advanced, verified,
    foundational, coursework-asserted, asserted-by-srikar)
  the tech list of any evidence atom, whatever its confidence
It goes on the CONFIRM list when the posting names it and only these say so:
  skills.yaml "unbacked" (claimed on an old resume, no record found by the audit)
  a language in his GitHub repos (the snapshot has no fork flag, so a fork's Rust
    would otherwise read as his own)
  nothing at all

The skills line no longer needs a bullet behind it, by his instruction. Bullets,
projects and education are untouched here and stay strictly evidence-checked
(scripts/agent_keywords.py, the resume-rewrite skill).

    skills_basis.py --app 291 --tex latex/resume/.../main.tex            report only
    skills_basis.py --app 291 --tex latex/resume/.../main.tex --apply    add, compile, gate
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

# canonical key -> (display name, pattern, category hint). Category hints match the words
# resume.cls skill categories use ("Languages", "Full stack & APIs", "Cloud & data", ...).
LEXICON: dict[str, tuple[str, str, str]] = {
    # languages
    "python": ("Python", r"python", "lang"), "java": ("Java", r"java(?!\s*script)", "lang"),
    "javascript": ("JavaScript", r"javascript|\bjs\b", "lang"), "typescript": ("TypeScript", r"typescript", "lang"),
    "sql": ("SQL", r"\bsql\b", "lang"), "c": ("C", r"(?<![\w#+])c(?![\w#+])(?=\s*(?:,|/|\)|and|or|\+\+)?)", "lang"),
    "c++": ("C++", r"c\+\+", "lang"), "c#": ("C#", r"c#|\.net\s+c#", "lang"), "go": ("Go", r"\bgolang\b|\bgo\b(?=\s*(?:,|/|\)|and|or))", "lang"),
    "rust": ("Rust", r"\brust\b", "lang"), "ruby": ("Ruby", r"\bruby\b", "lang"), "scala": ("Scala", r"\bscala\b", "lang"),
    "kotlin": ("Kotlin", r"\bkotlin\b", "lang"), "swift": ("Swift", r"\bswift\b", "lang"), "r": ("R", r"(?<![\w-])R(?![\w-])(?=\s*(?:,|/|\)|and|or))", "lang"),
    "bash": ("Bash", r"\bbash\b|shell scripting", "lang"), "php": ("PHP", r"\bphp\b", "lang"), "matlab": ("MATLAB", r"\bmatlab\b", "lang"),
    "html": ("HTML", r"\bhtml5?\b", "lang"), "css": ("CSS", r"\bcss3?\b", "lang"), "dax": ("DAX", r"\bdax\b", "lang"),
    # web and APIs
    "react": ("React", r"\breact(?:\.js|js)?\b(?!\s*native)", "web"), "next.js": ("Next.js", r"next\.?js", "web"),
    "node.js": ("Node.js", r"node\.?js|\bnode\b", "web"), "angular": ("Angular", r"\bangular", "web"), "vue": ("Vue", r"\bvue(?:\.js)?\b", "web"),
    "django": ("Django", r"\bdjango\b", "web"), "flask": ("Flask", r"\bflask\b", "web"), "fastapi": ("FastAPI", r"fast\s?api", "web"),
    "spring": ("Spring Boot", r"spring\s*boot|spring\s+framework|spring\s+mvc", "web"), "express": ("Express", r"express\.?js|\bexpress\b(?=\s*[,/)])", "web"),
    "graphql": ("GraphQL", r"graphql", "web"), "rest": ("REST APIs", r"\brest(?:ful)?\b(?:\s*apis?)?", "web"),
    "dotnet": (".NET", r"\.net\b|dotnet", "web"), "tailwind": ("Tailwind CSS", r"tailwind", "web"),
    # data and databases
    "postgresql": ("PostgreSQL", r"postgres(?:ql)?", "data"), "mysql": ("MySQL", r"mysql", "data"), "mongodb": ("MongoDB", r"mongo(?:db)?", "data"),
    "redis": ("Redis", r"\bredis\b", "data"), "kafka": ("Apache Kafka", r"kafka", "data"), "spark": ("Apache Spark", r"\bspark\b(?!\s*ar)", "data"),
    "pyspark": ("PySpark", r"pyspark", "data"), "airflow": ("Airflow", r"airflow", "data"), "dbt": ("dbt", r"\bdbt\b", "data"),
    "snowflake": ("Snowflake", r"snowflake", "data"), "databricks": ("Databricks", r"databricks", "data"), "bigquery": ("BigQuery", r"big\s?query", "data"),
    "cassandra": ("Cassandra", r"cassandra", "data"), "clickhouse": ("ClickHouse", r"clickhouse", "data"), "elasticsearch": ("Elasticsearch", r"elastic\s?search", "data"),
    "pandas": ("pandas", r"\bpandas\b", "data"), "numpy": ("NumPy", r"numpy", "data"), "power-bi": ("Power BI", r"power\s?bi", "data"),
    "tableau": ("Tableau", r"tableau", "data"), "excel": ("Excel", r"\bexcel\b", "data"), "microsoft-fabric": ("Microsoft Fabric", r"microsoft fabric|\bfabric\b", "data"),
    "azure-data-factory": ("Azure Data Factory", r"data factory|\badf\b", "data"), "etl": ("ETL", r"\betl\b|\belt\b", "data"),
    "hadoop": ("Hadoop", r"hadoop", "data"), "sqlite": ("SQLite", r"sqlite", "data"), "dynamodb": ("DynamoDB", r"dynamo\s?db", "data"),
    # cloud and devops
    "aws": ("AWS", r"\baws\b|amazon web services", "cloud"), "azure": ("Azure", r"\bazure\b", "cloud"), "gcp": ("GCP", r"\bgcp\b|google cloud", "cloud"),
    "docker": ("Docker", r"docker", "cloud"), "kubernetes": ("Kubernetes", r"kubernetes|\bk8s\b", "cloud"), "terraform": ("Terraform", r"terraform", "cloud"),
    "linux": ("Linux", r"\blinux\b|\bunix\b", "cloud"), "git": ("Git", r"\bgit\b(?!hub|lab)", "cloud"), "github-actions": ("GitHub Actions", r"github actions", "cloud"),
    "ci-cd": ("CI/CD", r"ci\s*/\s*cd|continuous integration", "cloud"), "jenkins": ("Jenkins", r"jenkins", "cloud"), "gitlab-ci": ("GitLab CI", r"gitlab", "cloud"),
    "ansible": ("Ansible", r"ansible", "cloud"), "prometheus": ("Prometheus", r"prometheus", "cloud"), "grafana": ("Grafana", r"grafana", "cloud"),
    "microservices": ("Microservices", r"micro-?services?", "cloud"),
    # ML and AI
    "pytorch": ("PyTorch", r"pytorch", "ml"), "tensorflow": ("TensorFlow", r"tensorflow", "ml"), "scikit-learn": ("scikit-learn", r"scikit|sklearn", "ml"),
    "opencv": ("OpenCV", r"opencv", "ml"), "llm": ("LLMs", r"\bllms?\b|large language model", "ml"), "rag": ("RAG", r"\brag\b|retrieval[- ]augmented", "ml"),
    "langchain": ("LangChain", r"langchain", "ml"), "hugging-face": ("Hugging Face", r"hugging\s?face", "ml"), "yolo": ("YOLO", r"\byolo", "ml"),
    "selenium": ("Selenium", r"selenium", "web"), "pytest": ("pytest", r"pytest", "web"), "jira": ("Jira", r"\bjira\b", "cloud"),
}
CATEGORY_WORDS = {"lang": r"language", "web": r"full|stack|api|web|framework|front|back", "data": r"data|database|analytic|bi\b",
                  "cloud": r"cloud|devops|platform|infra|tool", "ml": r"ml|machine|ai\b|learning|model"}
NOT_USED_LEVELS = {"unbacked"}


def _k(s: str) -> str:
    return re.sub(r"[\s_]+", "-", s.lower().strip())


def records() -> tuple[dict[str, str], dict[str, str]]:
    """(used: key -> where it is recorded, weak: key -> why it needs his confirmation)."""
    used, weak = {}, {}
    for s in yaml.safe_load((ROOT / "profile" / "skills.yaml").read_text()):
        key = _k(s["name"])
        if str(s.get("level")) in NOT_USED_LEVELS:
            weak[key] = "on an old resume, but the audit found no record of use"
        else:
            used[key] = f"skills.yaml ({s.get('level')})"
    for a in yaml.safe_load((ROOT / "profile" / "evidence.yaml").read_text()):
        for t in a.get("tech") or []:
            if isinstance(t, str):
                used.setdefault(_k(t), f"{a['id']}")
        # merged pull requests are verified use of Git even where no tech list names it
        if re.search(r"pull request|merged into|\bPRs?\b", f"{a.get('action')} {a.get('scope')}", re.I):
            used.setdefault("git", f"{a['id']} (merged pull requests)")
    snap = ROOT / "data" / "raw" / "github_snapshot.json"
    if snap.exists():
        d = json.loads(snap.read_text())
        repos = d.get("repos", d)
        for name, r in (repos.items() if isinstance(repos, dict) else enumerate(repos)):
            for lang in (r.get("langs") or {}) if isinstance(r, dict) else {}:
                key = _k(lang)
                if key not in used:
                    weak.setdefault(key, f"a language in your GitHub repo {r.get('name', name)} (possibly a fork)")
    for alias, canon in (("apache-kafka", "kafka"), ("apache-spark", "spark"), ("rest-api", "rest"), ("rest-apis", "rest"),
                         ("node", "node.js"), ("nextjs", "next.js"), ("powerbi", "power-bi"), ("postgres", "postgresql"),
                         ("sklearn", "scikit-learn"), ("fabric", "microsoft-fabric"), ("adf", "azure-data-factory"),
                         ("reactjs", "react"), ("github-action", "github-actions"), ("cicd", "ci-cd"), ("shell", "bash"),
                         ("github", "git"), ("git-github", "git"), ("nodejs", "node.js"), ("tailwind-css", "tailwind")):
        if alias in used:
            used.setdefault(canon, used[alias])
        if alias in weak and canon not in used:
            weak.setdefault(canon, weak[alias])
    # What a recorded technology plainly includes. Not guesses: FastAPI is a REST framework,
    # and Next.js pages styled with Tailwind are HTML and CSS work.
    for have, implies in (("fastapi", ("rest",)), ("nextjs", ("html", "css", "react")), ("next.js", ("html", "css", "react")),
                          ("tailwind", ("css",)), ("tailwind-css", ("css",))):
        if have in used:
            for k in implies:
                used.setdefault(k, f"implied by {have} ({used[have]})")
    return used, weak


def posting_terms(text: str) -> dict[str, str]:
    """key -> the posting's own spelling, for every lexicon technology the posting names."""
    out = {}
    for key, (display, pat, _) in LEXICON.items():
        flags = 0 if key in ("r", "c") else re.I
        m = re.search(pat, text, flags)
        if m:
            # the canonical name, never the posting's casing: "html" and "css" went onto five
            # resumes in lower case that way on 2026-09-16
            out[key] = display
    return out


def resume_plain(tex: str) -> str:
    # LaTeX comments never reach the PDF; the C3.ai source mentions Java only in one
    tex = "\n".join(re.sub(r"(?<!\\)%.*$", "", l) for l in tex.splitlines())
    return re.sub(r"\s+", " ", re.sub(r"\\[a-zA-Z]+|[{}\\]", " ", tex.replace("~", " ")))


def plan(posting: str, tex: str) -> dict:
    used, weak = records()
    named = posting_terms(posting)
    on_page = resume_plain(tex)
    add, confirm, already = [], [], []
    for key, display in named.items():
        pat = LEXICON[key][1]
        if re.search(pat, on_page, 0 if key in ("r", "c") else re.I):
            already.append(display)
        elif key in used:
            add.append({"key": key, "name": display, "source": used[key], "category": LEXICON[key][2]})
        else:
            confirm.append({"name": display, "why": weak.get(key, "no record anywhere in your profile or evidence")})
    return {"add": add, "confirm": confirm, "already_on_resume": already}


def latex_name(name: str) -> str:
    return name.replace("#", r"\#").replace("&", r"\&").replace("%", r"\%").replace(" ", "~")


def insert(tex: str, items: list[dict]) -> str:
    """Append each name to the skills= line whose category best matches, else the last one."""
    lines = tex.splitlines(keepends=True)
    blocks = []                                   # (category text, index of the skills= line)
    cat = ""
    for i, l in enumerate(lines):
        m = re.match(r"\s*category\s*=\s*(.*?),?\s*$", l)
        if m:
            cat = m.group(1)
        if re.match(r"\s*skills\s*=", l):
            blocks.append((cat, i))
    if not blocks:
        raise ValueError("no skills= lines in this resume")
    for it in items:
        target = next((i for c, i in blocks if re.search(CATEGORY_WORDS[it["category"]], c, re.I)), blocks[-1][1])
        line = lines[target].rstrip("\n")
        lines[target] = f"{line}{{,}} \\textbf{{{latex_name(it['name'])}}}\n"
    return "".join(lines)


def apply(app_id: int, tex_path: Path, dry: bool) -> dict:
    from agent_keywords import compile_tex, gates
    from agent_verdict import posting_text, row
    r = row(app_id)
    posting = posting_text(r)
    original = tex_path.read_text()
    rep = plan(posting, original)
    rep["applied"], rep["dropped_for_space"] = [], []
    if dry or not rep["add"]:
        return rep
    backup = tex_path.with_name("main.pre-skills.tex")
    if not backup.exists():
        shutil.copy2(tex_path, backup)
    items = list(rep["add"])
    while items:
        tex_path.write_text(insert(original, items))
        g = gates(tex_path, tex_path.parent / "main.pdf") if compile_tex(tex_path) else None
        if g and all(g.values()):
            rep["applied"], rep["gates"] = [i["name"] for i in items], g
            return rep
        rep["dropped_for_space"].append(items.pop()["name"])     # the posting names these in order of appearance
    tex_path.write_text(original)
    compile_tex(tex_path)
    rep["gates"] = "every addition broke a PDF gate; the resume is unchanged"
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", type=int, required=True)
    ap.add_argument("--tex", type=Path, required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    rep = apply(a.app, a.tex.resolve(), dry=not a.apply)
    print("already on the resume:", ", ".join(rep["already_on_resume"]) or "none")
    print("add (you have used these):", ", ".join(f"{i['name']} [{i['source']}]" for i in rep["add"]) or "none")
    if a.apply:
        print("applied:", ", ".join(rep["applied"]) or "none", "| dropped for space:", ", ".join(rep["dropped_for_space"]) or "none")
        print("gates:", rep.get("gates"))
    print("CONFIRM, not added (tell me if you have used any):")
    for c in rep["confirm"]:
        print(f"  {c['name']}: {c['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
