#!/usr/bin/env python3
"""Pull real engineering evidence out of GitHub.

Most resumes describe projects the way the author remembers them. GitHub knows
what actually happened: how long the work ran, how many commits, what the code
is really written in, whether anyone else used it. That gap is where the good
resume bullets live.

Two sources, merged:
  1. The GitHub API via the authenticated `gh` CLI. Covers public and private
     repos, plus pull requests you opened on other people's projects, which is
     the strongest external-contribution signal there is.
  2. Local clones. The API reports a language byte histogram; the clone shows
     you the dependency manifests, the actual test setup, and the real shape of
     the project.

Writes data/raw/github.json for build_evidence.py to consume.

Usage:
    python connectors/github.py                       # auth'd user
    python connectors/github.py --user srikar0805
    python connectors/github.py --local ~/Documents/my-projects
    python connectors/github.py --limit 50 --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "raw" / "github.json"

# Repos that are almost never worth putting on a resume. Filtered by default.
NOISE_NAMES = {"dotfiles", "config", "test", "tests", "hello-world", "playground",
               "scratch", "tmp", "practice", "learning", "tutorial"}

MANIFESTS = {
    "package.json": "node",
    "requirements.txt": "python",
    "pyproject.toml": "python",
    "Pipfile": "python",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "pom.xml": "java",
    "build.gradle": "java",
    "Gemfile": "ruby",
    "composer.json": "php",
    "Dockerfile": "docker",
    "docker-compose.yml": "docker",
    "*.csproj": "dotnet",
}

TEST_DIRS = {"test", "tests", "__tests__", "spec", "e2e"}
CI_PATHS = [".github/workflows", ".circleci", ".gitlab-ci.yml", "Jenkinsfile"]


class GhError(RuntimeError):
    pass


def gh(*args: str, parse: bool = True, timeout: int = 60):
    """Run a gh command. Raises GhError with something actionable."""
    if not shutil.which("gh"):
        raise GhError("gh is not installed. Run install.sh, or: brew install gh")
    try:
        proc = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "GH_PAGER": "", "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired:
        raise GhError(f"gh {' '.join(args[:3])} timed out")

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "not logged" in err.lower() or "authentication" in err.lower():
            raise GhError("gh is not authenticated. Run: gh auth login")
        raise GhError(f"gh {' '.join(args[:3])} failed: {err[:300]}")

    if not parse:
        return proc.stdout
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        raise GhError(f"gh {' '.join(args[:3])} returned non-JSON output")


def whoami() -> str:
    return gh("api", "user", "--jq", ".login", parse=False).strip()


def list_repos(user: str, limit: int) -> list[dict]:
    fields = ("name,description,url,isPrivate,isFork,isArchived,primaryLanguage,"
              "repositoryTopics,stargazerCount,forkCount,createdAt,pushedAt,"
              "diskUsage,licenseInfo,homepageUrl")
    return gh("repo", "list", user, "--limit", str(limit), "--json", fields) or []


def repo_languages(full_name: str) -> dict[str, int]:
    try:
        return gh("api", f"repos/{full_name}/languages") or {}
    except GhError:
        return {}


def repo_readme(full_name: str) -> str:
    """README as text. This is where the project's own claims live."""
    try:
        raw = gh("api", f"repos/{full_name}/readme",
                 "-H", "Accept: application/vnd.github.raw", parse=False)
        return raw[:20000]
    except GhError:
        return ""


def repo_commits(full_name: str, author: str, cap: int = 500) -> dict:
    """Commit history authored by this user.

    The counts matter less than the span. "312 commits over 14 months" is a
    defensible claim about sustained ownership. "312 commits" alone is not.
    """
    try:
        data = gh("api", "-X", "GET", f"repos/{full_name}/commits",
                  "-f", f"author={author}", "-f", "per_page=100",
                  "--paginate", "--slurp") or []
    except GhError:
        return {"count": 0, "first": None, "last": None, "messages": []}

    commits = [c for page in data for c in (page if isinstance(page, list) else [page])]
    if not commits:
        return {"count": 0, "first": None, "last": None, "messages": []}

    dates, messages = [], []
    for c in commits[:cap]:
        try:
            dates.append(c["commit"]["author"]["date"])
            messages.append(c["commit"]["message"].splitlines()[0][:120])
        except (KeyError, TypeError, IndexError):
            continue

    dates.sort()
    return {
        "count": len(commits),
        "first": dates[0] if dates else None,
        "last": dates[-1] if dates else None,
        "span_days": _span_days(dates),
        # Commit subjects describe what was actually built, in the author's own
        # words, at the time. Better source material than a year-old memory.
        "messages": messages[:120],
    }


def _span_days(dates: list[str]) -> int | None:
    if len(dates) < 2:
        return None
    try:
        a = datetime.fromisoformat(dates[0].replace("Z", "+00:00"))
        b = datetime.fromisoformat(dates[-1].replace("Z", "+00:00"))
        return (b - a).days
    except ValueError:
        return None


def external_prs(user: str, limit: int = 100) -> list[dict]:
    """Pull requests opened on repos the user does not own.

    A merged PR into somebody else's codebase is third-party proof that your
    code met an external bar. Worth more than any self-owned repo.
    """
    try:
        prs = gh("search", "prs", "--author", user, "--limit", str(limit),
                 "--json", "repository,title,url,state,createdAt,isDraft") or []
    except GhError:
        return []
    out = []
    for pr in prs:
        repo_full = (pr.get("repository") or {}).get("nameWithOwner", "")
        if repo_full and not repo_full.lower().startswith(f"{user.lower()}/"):
            out.append({
                "repo": repo_full,
                "title": pr.get("title"),
                "url": pr.get("url"),
                "state": pr.get("state"),
                "created_at": pr.get("createdAt"),
            })
    return out


def scan_local(root: Path, identities: set[str] | None = None) -> dict[str, dict]:
    """What the API cannot see: real project structure.

    Keyed by lowercased repo name so it can be joined against the API results.
    """
    identities = identities or set()
    found: dict[str, dict] = {}
    if not root.exists():
        return found

    for d in sorted(root.iterdir()):
        if not (d / ".git").exists():
            continue

        remote = _git(d, "remote", "get-url", "origin")
        name = None
        if remote:
            m = re.search(r"[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", remote.strip())
            if m:
                name = m.group(2)
        name = (name or d.name).lower()

        stack, deps = set(), []
        for manifest, tech in MANIFESTS.items():
            hits = list(d.glob(manifest)) if "*" in manifest else ([d / manifest] if (d / manifest).exists() else [])
            if hits:
                stack.add(tech)
                if manifest == "package.json":
                    deps += _node_deps(hits[0])
                elif manifest in ("requirements.txt", "pyproject.toml"):
                    deps += _py_deps(hits[0])

        has_tests = any((d / t).is_dir() for t in TEST_DIRS) or bool(list(d.glob("**/test_*.py"))[:1])
        has_ci = any((d / c).exists() for c in CI_PATHS)

        total = _git(d, "rev-list", "--count", "HEAD")
        total_n = int(total) if total and total.isdigit() else None

        # Commits authored BY THIS USER, not commits in the repo. A cloned or
        # forked open source project has thousands of commits by other people,
        # and counting them as the user's work manufactures a resume claim they
        # cannot defend for even one interview question. This distinction is
        # the whole reason the field exists.
        mine, top_author, others = _authored_by_user(d, identities)

        found[name] = {
            "local_path": str(d),
            "stack": sorted(stack),
            "dependencies": sorted(set(deps))[:60],
            "has_tests": has_tests,
            "has_ci": has_ci,
            "total_commits": total_n,
            "my_commits": mine,
            "top_author": top_author,
            "contributor_count": others,
            # A repo where the user wrote a small fraction of the history is
            # somebody else's project sitting on their disk.
            "likely_not_mine": bool(total_n and mine is not None
                                    and total_n > 20 and mine / total_n < 0.20),
            "first_commit": _git(d, "log", "--reverse", "--format=%aI", "--max-count=1") or None,
            "last_commit": _git(d, "log", "-1", "--format=%aI") or None,
            "source_files": _count_source(d),
        }
    return found


def _authored_by_user(repo: Path, identities: set[str]) -> tuple[int | None, str | None, int]:
    """Count commits authored by the user, plus who actually owns the history."""
    shortlog = _git(repo, "shortlog", "-sne", "--all", "--no-merges")
    if not shortlog:
        return None, None, 0

    rows: list[tuple[int, str]] = []
    for line in shortlog.splitlines():
        line = line.strip()
        if not line:
            continue
        count, _, who = line.partition("\t")
        try:
            rows.append((int(count.strip()), who.strip()))
        except ValueError:
            continue

    if not rows:
        return None, None, 0

    mine = 0
    for count, who in rows:
        low = who.lower()
        if any(ident and ident in low for ident in identities):
            mine += count

    rows.sort(reverse=True)
    return mine, rows[0][1], len(rows)


def user_identities(login: str) -> set[str]:
    """Strings that identify the user in a git author line.

    Git author identity is whatever was configured at commit time, which is
    routinely a different email than the GitHub account. Matching on several
    signals avoids undercounting the user's own work.
    """
    idents = {login.lower()}
    for key in ("user.email", "user.name"):
        try:
            v = subprocess.run(["git", "config", "--global", key],
                               capture_output=True, text=True, timeout=10)
            if v.returncode == 0 and v.stdout.strip():
                idents.add(v.stdout.strip().lower())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    try:
        emails = gh("api", "user/emails", "--jq", ".[].email", parse=False)
        idents.update(e.strip().lower() for e in emails.splitlines() if e.strip())
    except GhError:
        pass  # user:email scope not granted, the other signals still work
    return {i for i in idents if i}


def _git(repo: Path, *args: str) -> str | None:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=25)
        return p.stdout.strip() if p.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _node_deps(p: Path) -> list[str]:
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return []
    return list((data.get("dependencies") or {}).keys()) + \
           list((data.get("devDependencies") or {}).keys())


def _py_deps(p: Path) -> list[str]:
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return re.findall(r"^\s*([A-Za-z][\w.-]+)", text, re.M)[:80]


def _count_source(d: Path) -> int:
    exts = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".cpp",
            ".c", ".rb", ".php", ".swift", ".kt", ".scala", ".m", ".ipynb"}
    n = 0
    skip = {"node_modules", ".git", ".venv", "venv", "dist", "build", "__pycache__"}
    for p in d.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts and not (skip & set(p.parts)):
            n += 1
            if n > 5000:
                break
    return n


def is_noise(repo: dict) -> bool:
    name = (repo.get("name") or "").lower()
    if name in NOISE_NAMES:
        return True
    if repo.get("isFork") and not repo.get("stargazerCount"):
        return True
    return False


def collect(user: str | None, local_root: Path | None, limit: int,
            include_forks: bool, workers: int = 8) -> dict:
    user = user or whoami()
    print(f"github user: {user}", file=sys.stderr)

    repos = list_repos(user, limit)
    print(f"  {len(repos)} repos returned", file=sys.stderr)

    if not include_forks:
        before = len(repos)
        repos = [r for r in repos if not is_noise(r)]
        if before != len(repos):
            print(f"  {before - len(repos)} filtered as forks or scratch repos", file=sys.stderr)

    identities = user_identities(user)
    local = scan_local(local_root, identities) if local_root else {}
    if local:
        print(f"  {len(local)} local clones scanned", file=sys.stderr)

    def enrich(r: dict) -> dict:
        full = f"{user}/{r['name']}"
        r["full_name"] = full
        r["languages"] = repo_languages(full)
        r["readme"] = repo_readme(full)
        r["commits"] = repo_commits(full, user)
        r["local"] = local.get(r["name"].lower())
        r["topics"] = [t.get("name") for t in (r.get("repositoryTopics") or []) if t]
        r.pop("repositoryTopics", None)
        return r

    enriched: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(enrich, r): r["name"] for r in repos}
        for i, fut in enumerate(as_completed(futures), 1):
            name = futures[fut]
            try:
                enriched.append(fut.result())
            except Exception as e:
                print(f"  skipped {name}: {e}", file=sys.stderr)
            print(f"\r  enriched {i}/{len(futures)}", end="", file=sys.stderr)
    print(file=sys.stderr)

    # Substance first: sustained commit history beats a starred one-off.
    def substance(r: dict) -> float:
        loc = r.get("local") or {}
        if loc.get("likely_not_mine"):
            return -1.0
        return (
            (r.get("commits") or {}).get("count", 0) * 2
            + r.get("stargazerCount", 0) * 10
            + (50 if loc.get("has_tests") else 0)
            + (30 if loc.get("has_ci") else 0)
        )

    enriched.sort(key=substance, reverse=True)

    prs = external_prs(user)
    if prs:
        print(f"  {len(prs)} external pull requests", file=sys.stderr)

    orphan_locals = {k: v for k, v in local.items()
                     if k not in {r["name"].lower() for r in enriched}}

    return {
        "user": user,
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "repo_count": len(enriched),
        "repos": enriched,
        "external_prs": prs,
        # Clones with no matching remote repo. Usually private work or a repo
        # under a different account. Surfaced rather than silently dropped.
        "local_only": orphan_locals,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect GitHub evidence.")
    ap.add_argument("--user", help="defaults to the authenticated gh user")
    ap.add_argument("--local", default=str(Path.home() / "Documents" / "my-projects"),
                    help="directory of local clones to deep-scan")
    ap.add_argument("--no-local", action="store_true")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--include-forks", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--json", action="store_true", help="print to stdout as well")
    args = ap.parse_args()

    try:
        data = collect(
            args.user,
            None if args.no_local else Path(args.local).expanduser(),
            args.limit,
            args.include_forks,
        )
    except GhError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nwrote {out}  ({data['repo_count']} repos, "
          f"{len(data['external_prs'])} external PRs)", file=sys.stderr)

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print("\ntop repos by substance:")
        for r in data["repos"][:12]:
            c = r.get("commits") or {}
            loc = r.get("local") or {}
            bits = [f"{c.get('count', 0)} commits"]
            if c.get("span_days"):
                bits.append(f"{c['span_days']}d span")
            if r.get("stargazerCount"):
                bits.append(f"{r['stargazerCount']} stars")
            if loc.get("has_tests"):
                bits.append("tests")
            if loc.get("has_ci"):
                bits.append("ci")
            if loc.get("likely_not_mine"):
                bits.append(f"NOT YOURS: {loc.get('my_commits', 0)}/{loc.get('total_commits')} "
                            f"commits, owned by {loc.get('top_author', '?')}")
            lang = (r.get("primaryLanguage") or {}).get("name") or "?"
            print(f"  {r['name'][:32]:<34}{lang[:12]:<14}{', '.join(bits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
