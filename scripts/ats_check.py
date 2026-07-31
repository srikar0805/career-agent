#!/usr/bin/env python3
"""Mechanical ATS check. Deliberately dumb.

style-check: allow-banned-literals (normalize() maps banned punctuation to ASCII)

This answers only questions that are NOT judgment calls:
  - Can a parser read this file at all?
  - Does the literal string the posting used appear in the resume?
  - Are the section headings ones a parser recognizes?

It does NOT judge whether a bullet is convincing, whether the achievement is
impressive, or whether the writing is good. That is the `resume-judge` agent's
job, and an LLM is far better at it. Keeping the two separate is the point:
the agent cannot fake a keyword being present, and this script cannot pretend
to have taste.

Usage:
    python scripts/ats_check.py --resume resume.md --jd posting.txt
    python scripts/ats_check.py --resume resume.pdf --jd-text "..." --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest import read  # noqa: E402

# Terms an ATS keyword-matches on, that a naive tokenizer would miss or split.
# Not exhaustive by design. The JD itself is the primary source; this list only
# ensures multi-token and punctuated technologies survive extraction.
TECH_VOCAB = {
    "machine learning", "deep learning", "natural language processing", "computer vision",
    "reinforcement learning", "large language models", "generative ai", "data science",
    "data engineering", "data pipeline", "feature engineering", "model deployment",
    "mlops", "devops", "ci/cd", "a/b testing", "time series", "recommender systems",
    "distributed systems", "microservices", "event driven", "message queue",
    "rest api", "graphql", "grpc", "web sockets", "service mesh",
    "python", "java", "javascript", "typescript", "golang", "rust", "c++", "c#",
    "scala", "kotlin", "swift", "ruby", "php", "r", "matlab", "sql", "nosql", "bash",
    "pytorch", "tensorflow", "keras", "scikit-learn", "sklearn", "pandas", "numpy",
    "scipy", "xgboost", "lightgbm", "hugging face", "transformers", "onnx", "jax",
    "langchain", "llamaindex", "vector database", "rag", "fine-tuning", "embeddings",
    "react", "next.js", "vue", "angular", "svelte", "node.js", "express", "django",
    "flask", "fastapi", "spring boot", "rails", ".net",
    "postgresql", "postgres", "mysql", "mongodb", "redis", "cassandra", "dynamodb",
    "elasticsearch", "snowflake", "bigquery", "redshift", "databricks", "clickhouse",
    "spark", "hadoop", "kafka", "airflow", "dbt", "flink", "beam", "dagster",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ansible", "helm",
    "jenkins", "github actions", "gitlab ci", "argocd", "prometheus", "grafana",
    "datadog", "opentelemetry", "sagemaker", "vertex ai", "lambda", "ec2", "s3",
    "git", "linux", "unix", "agile", "scrum", "kanban", "jira", "figma", "tableau",
    "power bi", "looker", "excel", "unit testing", "integration testing", "tdd",
}

# JD word -> what counts as the same thing on a resume. An ATS that does exact
# matching will not do this for you, but a human recruiter will, and the resume
# should ideally contain the posting's exact spelling anyway. Aliases exist so
# the "missing" list does not scream about things you actually have.
ALIASES: dict[str, set[str]] = {
    "machine learning": {"ml", "machine-learning"},
    "natural language processing": {"nlp"},
    "computer vision": {"cv", "opencv"},
    "javascript": {"js", "es6", "ecmascript"},
    "typescript": {"ts"},
    "kubernetes": {"k8s"},
    "postgresql": {"postgres", "psql"},
    "continuous integration": {"ci", "ci/cd"},
    "amazon web services": {"aws"},
    "google cloud platform": {"gcp", "google cloud"},
    "scikit-learn": {"sklearn", "scikit learn"},
    "node.js": {"nodejs", "node"},
    "next.js": {"nextjs"},
    "c++": {"cpp"},
    "large language models": {"llm", "llms"},
    "infrastructure as code": {"iac", "terraform"},
    "object oriented programming": {"oop", "oops"},
    "data structures and algorithms": {"dsa", "data structures", "algorithms"},
}

# Headings ATS parsers are trained to find. Creative section names ("What I
# Bring", "My Journey") get parsed as body text, and everything under them
# lands in the wrong field.
CANONICAL_HEADINGS = {
    "experience", "work experience", "professional experience", "employment",
    "education", "skills", "technical skills", "projects", "certifications",
    "publications", "summary", "professional summary", "awards", "achievements",
    "volunteer", "languages", "interests", "coursework", "research",
}

STOPWORDS = {
    "the", "and", "for", "with", "you", "our", "will", "are", "have", "who",
    "this", "that", "from", "your", "their", "them", "they", "has", "was",
    "not", "but", "all", "can", "any", "may", "out", "how", "why", "what",
    "work", "team", "role", "job", "company", "years", "year", "experience",
    "strong", "good", "great", "able", "help", "need", "want", "well", "more",
    "new", "use", "using", "used", "including", "such", "other", "across",
    "within", "into", "about", "than", "when", "where", "which", "while",
    "would", "should", "could", "must", "also", "high", "best", "like",
    "plus", "nice", "bonus", "required", "preferred", "qualifications",
    "requirements", "responsibilities", "candidate", "candidates", "position",
    "opportunity", "benefits", "salary", "apply", "please", "email", "resume",
    # Words that introduce a requirement without being one. These pollute the
    # missing list with terms nobody can add to a resume.
    "proficiency", "proficient", "familiarity", "familiar", "expertise",
    "knowledge", "understanding", "contributions", "minimum", "basic",
    "advanced", "solid", "deep", "hands-on", "demonstrated", "proven",
    "ability", "skills", "background", "track", "record", "plus'",
    "minimum qualifications", "preferred qualifications", "basic qualifications",
    # HTML and CSS residue. Postings fetched from an ATS API sometimes carry
    # markup through, and without this every "div" and "span" is reported as a
    # missing requirement.
    "div", "span", "href", "nbsp", "amp", "quot", "strong", "img", "src",
    "class", "style", "http", "https", "www", "com", "org", "html", "utm",
    # Boilerplate that appears in almost every posting and matches nothing
    # useful on a resume.
    "equal", "opportunity", "employer", "compensation", "equity", "benefits",
    "disability", "veteran", "gender", "identity", "orientation", "religion",
    "applicants", "accommodation", "transparency", "annual", "base", "range",
}

REQUIRED_MARKERS = re.compile(
    r"(required|requirements|must have|must-have|qualifications|you have|"
    r"minimum qualifications|basic qualifications|what you.ll need)", re.I)
PREFERRED_MARKERS = re.compile(
    r"(preferred|nice to have|nice-to-have|bonus|plus|desired|"
    r"preferred qualifications)", re.I)


def normalize(text: str) -> str:
    t = text.lower()
    t = t.replace("’", "'").replace("–", "-").replace("—", "-")
    t = re.sub(r"[^\w\s+#./'-]", " ", t)
    # Collapse horizontal whitespace only. Newlines are load-bearing: the
    # "experience with X, Y, Z" extractor uses them as list-item boundaries,
    # and without them a single regex swallows three bullets at once.
    return re.sub(r"[^\S\n]+", " ", t)


def section_weights(jd: str) -> list[tuple[str, float]]:
    """Split the JD into chunks and weight them.

    A skill listed under "Requirements" matters more than one in the company
    boilerplate. Weighting by section is the single cheapest way to make the
    missing-keyword list actionable rather than a wall of noise.
    """
    lines = jd.splitlines()
    chunks: list[tuple[str, float]] = []
    weight = 1.0
    buf: list[str] = []
    for line in lines:
        if REQUIRED_MARKERS.search(line) and len(line) < 120:
            if buf:
                chunks.append(("\n".join(buf), weight)); buf = []
            weight = 3.0
        elif PREFERRED_MARKERS.search(line) and len(line) < 120:
            if buf:
                chunks.append(("\n".join(buf), weight)); buf = []
            weight = 1.5
        buf.append(line)
    if buf:
        chunks.append(("\n".join(buf), weight))
    return chunks


def extract_keywords(jd: str) -> dict[str, float]:
    """Pull weighted requirement keywords out of a posting."""
    scores: dict[str, float] = {}

    def bump(term: str, w: float) -> None:
        term = term.strip().lower()
        if len(term) < 2 or term in STOPWORDS:
            return
        scores[term] = scores.get(term, 0.0) + w

    for chunk, weight in section_weights(jd):
        norm = normalize(chunk)

        # Known multi-token technologies, matched as whole phrases.
        for term in TECH_VOCAB:
            if re.search(r"(?<![\w+#])" + re.escape(term) + r"(?![\w+#])", norm):
                bump(term, weight * 2.0)

        # "experience with X, Y, and Z" and friends. The list right after these
        # phrases is almost always the real requirement set.
        for m in re.finditer(
            r"(?:experience (?:with|in|using)|proficien\w+ (?:with|in)|"
            r"familiarity with|knowledge of|skilled in|expertise in)\s+([^.;\n]{3,140})",
            norm,
        ):
            for part in re.split(r",| and | or |/", m.group(1)):
                part = part.strip(" -\t")
                # Reject run-on fragments. A genuine requirement is a short
                # noun phrase, not half a sentence.
                if 2 < len(part) < 40 and len(part.split()) <= 4:
                    bump(part, weight * 1.5)

        # Capitalized proper nouns from the original casing, which catches
        # product and framework names not in TECH_VOCAB.
        for m in re.finditer(r"\b([A-Z][a-zA-Z0-9+#.]{2,}(?:\s[A-Z][a-zA-Z0-9+#.]{2,})?)\b", chunk):
            cand = m.group(1).lower()
            if cand not in STOPWORDS and not cand.istitle() or cand in TECH_VOCAB:
                bump(cand, weight * 0.5)

        # Bare single tokens as a floor, so nothing is missed entirely.
        for tok in re.findall(r"\b[a-z][a-z0-9+#.-]{2,}\b", norm):
            if tok not in STOPWORDS:
                bump(tok, weight * 0.15)

    # Keep the meaningful tail only.
    return {k: v for k, v in scores.items() if v >= 1.0}


def present_in(term: str, resume_norm: str) -> str | None:
    """Return how the term was found: 'exact', 'alias', or None."""
    pattern = r"(?<![\w+#])" + re.escape(term) + r"(?![\w+#])"
    if re.search(pattern, resume_norm):
        return "exact"
    for canon, alts in ALIASES.items():
        group = {canon} | alts
        if term in group:
            for alt in group:
                if alt != term and re.search(
                    r"(?<![\w+#])" + re.escape(alt) + r"(?![\w+#])", resume_norm
                ):
                    return "alias"
    return None


def _canonical_match(s: str) -> str | None:
    """Match a heading to a canonical one, tolerating common qualifiers.

    Real resumes write "Academic Projects", "Relevant Experience", and
    "Professional Certifications". Those all land in the right ATS field, so
    flagging them as unrecognized is noise that trains the user to ignore the
    warnings that matter.
    """
    if s in CANONICAL_HEADINGS:
        return s
    words = set(s.split())
    for canon in CANONICAL_HEADINGS:
        cw = set(canon.split())
        if cw and cw <= words and len(words - cw) <= 1:
            return canon
    return None


def check_headings(resume: str) -> list[str]:
    warnings: list[str] = []
    found: set[str] = set()
    lines = resume.splitlines()

    # The first few lines are the name and contact block. A name in caps looks
    # exactly like a section heading to any heuristic, and it is not one.
    for line in lines[3:]:
        s = re.sub(r"^[#*\-\s]+", "", line).strip().rstrip(":").lower()
        # A heading has no digits. "CGPA 7.78" and "2020 to 2024" are content
        # that happens to be short and uppercase, not section names.
        looks_like_heading = (
            2 <= len(s) <= 40
            and not any(c.isdigit() for c in s)
            and (line.isupper() or line.strip().startswith("#") or s in CANONICAL_HEADINGS)
        )
        if looks_like_heading:
            canon = _canonical_match(s)
            # A short heading is unambiguous. A long one is usually a sentence
            # fragment that happened to look like a heading, so the word cap
            # keeps those out of the warnings. But an all-caps line under 40
            # characters is a section name with near certainty however long it
            # runs, and long invented headings ("THINGS YOU CAN OPEN AND TRY")
            # are exactly the ones that need catching.
            cap = 7 if line.isupper() else 4
            if canon:
                found.add(canon)
            elif len(s.split()) <= cap and s:
                warnings.append(
                    f'section heading "{s}" is not one ATS parsers recognize. '
                    f"Use a standard name so the content lands in the right field."
                )

    if not any(h in found for h in ("experience", "work experience", "professional experience", "employment")):
        warnings.append('no recognized "Experience" heading found. Parsers key off this to build work history.')
    if "education" not in found:
        warnings.append('no "Education" heading found.')
    if not any(h in found for h in ("skills", "technical skills")):
        warnings.append('no "Skills" heading found. Keyword matchers look here first.')
    return warnings


def check_contact(resume: str) -> list[str]:
    warnings: list[str] = []
    if not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", resume):
        warnings.append("no email address found. The application cannot be attributed to you.")
    if not re.search(r"(\+?\d[\d\s().-]{7,}\d)", resume):
        warnings.append("no phone number found.")
    return warnings


def run(resume_text: str, jd_text: str, parse_warnings: list[str],
        company: str | None = None) -> dict:
    resume_norm = normalize(resume_text)
    keywords = extract_keywords(jd_text)

    # The company's own name is repeated throughout its posting, so it scores
    # very high and then reports as a top missing keyword. A resume should not
    # contain the employer's name, so this is pure noise.
    if company:
        for token in re.split(r"[\s,.]+", company.lower()):
            if len(token) > 2:
                keywords.pop(token, None)
        keywords.pop(company.lower(), None)

    hits, misses = [], []
    got = 0.0
    total = 0.0
    for term, weight in sorted(keywords.items(), key=lambda kv: -kv[1]):
        total += weight
        how = present_in(term, resume_norm)
        if how:
            got += weight if how == "exact" else weight * 0.7
            hits.append({"term": term, "weight": round(weight, 2), "match": how})
        else:
            misses.append({"term": term, "weight": round(weight, 2)})

    coverage = round(100 * got / total, 1) if total else 0.0

    warnings = list(parse_warnings)
    warnings += check_headings(resume_text)
    warnings += check_contact(resume_text)

    words = len(re.findall(r"\b[\w'-]+\b", resume_text))
    if words < 250:
        warnings.append(f"{words} words is thin. Most single-page resumes run 400 to 600.")
    elif words > 900:
        warnings.append(f"{words} words is long. Trim toward 600.")

    return {
        "coverage_percent": coverage,
        "keywords_found": len(hits),
        "keywords_missing": len(misses),
        "resume_words": words,
        "present": hits,
        "missing": misses[:40],
        "parse_warnings": warnings,
        # Mechanical gate only. Passing this does not mean the resume is good,
        # it means a parser will not silently destroy it.
        "mechanical_pass": coverage >= 65 and not any(
            "no extractable text" in w or "multi-column" in w for w in warnings
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Mechanical ATS parse and keyword check.")
    ap.add_argument("--resume", required=True, help="path to resume (pdf, docx, md, txt)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--jd", help="path to job posting")
    g.add_argument("--jd-text", help="job posting as a string")
    ap.add_argument("--company", help="employer name, excluded from keyword scoring")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rp = Path(args.resume).expanduser()
    if not rp.exists():
        print(f"no such resume: {rp}", file=sys.stderr)
        return 2
    doc = read(rp)
    if doc.error:
        print(f"cannot read resume: {doc.error}", file=sys.stderr)
        return 2

    if args.jd:
        jp = Path(args.jd).expanduser()
        if not jp.exists():
            print(f"no such posting: {jp}", file=sys.stderr)
            return 2
        jd_doc = read(jp)
        jd_text = jd_doc.text
    else:
        jd_text = args.jd_text

    result = run(doc.text, jd_text, doc.warnings, args.company)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["mechanical_pass"] else 1

    verdict = "PASS" if result["mechanical_pass"] else "FAIL"
    print(f"ATS MECHANICAL {verdict}")
    print(f"  keyword coverage  {result['coverage_percent']}%  "
          f"({result['keywords_found']} present, {result['keywords_missing']} missing)")
    print(f"  resume length     {result['resume_words']} words")

    if result["parse_warnings"]:
        print("\n  parse warnings")
        for w in result["parse_warnings"]:
            print(f"    - {w}")

    if result["missing"]:
        print("\n  missing, highest weight first")
        for m in result["missing"][:20]:
            print(f"    {m['weight']:>6.1f}  {m['term']}")
        print("\n  Only add a term if you can back it with an evidence ID.")
        print("  Listing a skill you cannot defend in an interview is worse than missing it.")

    return 0 if result["mechanical_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
