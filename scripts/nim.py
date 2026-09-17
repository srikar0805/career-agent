#!/usr/bin/env python3
"""NVIDIA-hosted models as worker agents. One client, one roster, one usage log.

WHY THIS EXISTS. On 2026-09-16 Srikar asked to split the pipeline into one agent
per task to cut Opus 5 usage, with the bulk work on NVIDIA's API. Measured the
same day: the daily Stage 2 run was not on Opus at all (Fable 5.1, 2 to 4.5M
cached tokens a run). The Opus usage was one interactive session re-reading 400K
to 800K tokens of history on every turn. So the saving comes from small, fresh
contexts per task, and NVIDIA workers take the reading-heavy tasks off Claude
entirely: posting verdicts, fit analysis, keyword gaps, mail triage, board
scouting, open-ended packet answers.

WHAT THE KEY BUYS. An NVIDIA API key reaches model endpoints at
integrate.api.nvidia.com (OpenAI-compatible). The agents themselves are the
scripts in this repo; NVIDIA does not host them.

THE KEY never lives in this repository, which is public. Stored once by Srikar:

    security add-generic-password -a "$USER" -s nvidia-api-key -w

(the trailing -w with no value prompts for it, so it stays out of shell history).
NVIDIA_API_KEY in the environment overrides the keychain.

    nim.py models                  what the endpoint serves right now
    nim.py check                   key present, and which model each role resolves to
    nim.py ping                    one tiny call per role, marks models that refuse
    nim.py ask --role R "prompt"   one call, for debugging

Every call is appended to data/logs/nim-usage.jsonl: role, model, tokens,
latency, outcome. Nothing is sent without a role, so the log says what left the
machine and why.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://integrate.api.nvidia.com/v1"
MODELS_CACHE = ROOT / "data" / "nim_models.json"
HEALTH = ROOT / "data" / "nim_health.json"          # models that refused this key
USAGE = ROOT / "data" / "logs" / "nim-usage.jsonl"

# Ordered candidates per role, resolved against the live model list. The order is
# a starting guess from model size and family, NOT a measurement; `bakeoff`
# results replace it (data/nim_roster.json) once the key is in.
ROSTER: dict[str, list[str]] = {
    # fast structured extraction from public postings. Measured 2026-09-16: lightning
    # reasons on every call and took 25 to 50s to say one word, so it is out; super,
    # gpt-oss and glm-flash all got a 5-field extraction and 6 mail triages right,
    # at medians of 3.7s, 14s and 126s under the same load.
    "scout":    ["nvidia/nemotron-3-super-120b-a12b", "openai/gpt-oss-20b", "z-ai/glm-5.3-flash"],
    # judgment against his profile: verdicts, fit analysis, keyword gaps
    "analyst":  ["nvidia/nemotron-3-super-120b-a12b", "moonshotai/kimi-k3", "deepseek-ai/deepseek-v4-flash-0731"],
    # prose in his voice: open-ended answers, resume bullet revisions
    "writer":   ["moonshotai/kimi-k3", "nvidia/nemotron-3-ultra-550b-a55b", "z-ai/glm-5.3"],
    # the fit analysis (scripts/agent_fit.py). Kimi K3 at Srikar's direction, 2026-09-16.
    # He also named DeepSeek V4 Pro: NVIDIA answered 410 Gone (end of life) the same day.
    "fit":      ["moonshotai/kimi-k3", "nvidia/nemotron-3-ultra-550b-a55b"],
    # short classification of mail
    "triage":   ["nvidia/nemotron-3-super-120b-a12b", "openai/gpt-oss-20b", "z-ai/glm-5.3-flash"],
}
ROSTER_OVERRIDE = ROOT / "data" / "nim_roster.json"

MIN_INTERVAL = 1.6          # seconds between calls: stays under a 40 requests/minute limit
_last_call = 0.0


class NimError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def api_key() -> str:
    k = os.environ.get("NVIDIA_API_KEY", "").strip()
    if k:
        return k
    try:
        return subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "nvidia-api-key", "-w"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def _request(method: str, path: str, body: dict | None = None, timeout: int = 180, auth: bool = True):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if auth:
        key = api_key()
        if not key:
            raise NimError("no NVIDIA key: run  security add-generic-password -a \"$USER\" -s nvidia-api-key -w")
        headers["Authorization"] = f"Bearer {key}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")[:400]
        return e.code, {"error": text}
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as e:
        # mistral-nemotron hung past 120s on 2026-09-16 and the raw timeout crashed
        # the caller. A hang is a retryable failure like a 503, not an exception.
        return 599, {"error": f"{type(e).__name__}: {e}"[:200]}


# ---------------------------------------------------------------- Gemini, a second provider
#
# Added 2026-09-16 when Srikar offered a Gemini key. Reason: nemotron-3-ultra is the only
# NVIDIA model that passed the verdict bake-off, and it timed out twice on his Greenboard
# run the same afternoon, so one overloaded endpoint could stop the whole flow.
# The key is the AI Studio kind (generativelanguage.googleapis.com), in the keychain as
# `gemini-api-key`. Models are addressed as "gemini/<name>" in rosters.
#
# PRIVACY. Google may use free-tier prompts to improve its models. Gemini is therefore
# allowed postings and resume facts only: never the mail triage role.
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODELS_CACHE = ROOT / "data" / "gemini_models.json"
GEMINI_ROLES = {"analyst", "fit", "writer", "scout"}


def gemini_key() -> str:
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    try:
        return subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "gemini-api-key", "-w"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def _gemini_http(method: str, url: str, body: dict | None, timeout: int):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json", "x-goog-api-key": gemini_key()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "replace")[:400]}
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as e:
        return 599, {"error": f"{type(e).__name__}: {e}"[:200]}


def _gemini_chat(model: str, system: str, user: str, max_tokens: int, temperature: float, timeout: int):
    """One generateContent call, reshaped to look like the OpenAI-style reply chat() expects."""
    name = model.split("/", 1)[1]
    code, d = _gemini_http("POST", f"{GEMINI_BASE}/models/{name}:generateContent", {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
    }, timeout)
    if code != 200:
        return code, d
    cand = (d.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
    u = d.get("usageMetadata") or {}
    return 200, {"choices": [{"message": {"content": text},
                              "finish_reason": "length" if cand.get("finishReason") == "MAX_TOKENS" else "stop"}],
                 "usage": {"prompt_tokens": u.get("promptTokenCount"), "completion_tokens": u.get("candidatesTokenCount"),
                           "thinking_tokens": u.get("thoughtsTokenCount")}}


def gemini_models(refresh: bool = False) -> list[str]:
    if not gemini_key():
        return []
    if not refresh and GEMINI_MODELS_CACHE.exists() and time.time() - GEMINI_MODELS_CACHE.stat().st_mtime < 86400:
        return json.loads(GEMINI_MODELS_CACHE.read_text())
    code, d = _gemini_http("GET", f"{GEMINI_BASE}/models?pageSize=200", None, 30)
    if code != 200:
        return []
    ids = sorted("gemini/" + m["name"].split("/")[-1] for m in d.get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", []))
    GEMINI_MODELS_CACHE.write_text(json.dumps(ids, indent=0) + "\n")
    return ids


# ---------------------------------------------------------------- Ollama Cloud, a third provider
#
# Added 2026-09-16 when Srikar added an Ollama key (keychain `ollama-api-key`). Its cloud serves
# models NVIDIA could not that night: nemotron-3-ultra on a working host (NVIDIA's returned
# "function not found"), deepseek-v4-pro (410 Gone on NVIDIA) and qwen3.5:397b (every Qwen
# retired on NVIDIA). OpenAI-compatible at https://ollama.com/v1. Addressed as "ollama/<model>".
OLLAMA_BASE = "https://ollama.com/v1"
OLLAMA_MODELS_CACHE = ROOT / "data" / "ollama_models.json"


def ollama_key() -> str:
    k = os.environ.get("OLLAMA_API_KEY", "").strip()
    if k:
        return k
    try:
        return subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "ollama-api-key", "-w"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def _ollama_http(method: str, path: str, body: dict | None, timeout: int):
    req = urllib.request.Request(OLLAMA_BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json",
                                                         "Authorization": f"Bearer {ollama_key()}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "replace")[:400]}
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as e:
        return 599, {"error": f"{type(e).__name__}: {e}"[:200]}


def ollama_models(refresh: bool = False) -> list[str]:
    if not ollama_key():
        return []
    if not refresh and OLLAMA_MODELS_CACHE.exists() and time.time() - OLLAMA_MODELS_CACHE.stat().st_mtime < 86400:
        return json.loads(OLLAMA_MODELS_CACHE.read_text())
    code, d = _ollama_http("GET", "/models", None, 30)
    if code != 200:
        return []
    ids = sorted("ollama/" + m["id"] for m in d.get("data", []))
    OLLAMA_MODELS_CACHE.write_text(json.dumps(ids, indent=0) + "\n")
    return ids


def models(refresh: bool = False) -> list[str]:
    if not refresh and MODELS_CACHE.exists() and time.time() - MODELS_CACHE.stat().st_mtime < 86400:
        return json.loads(MODELS_CACHE.read_text()) + gemini_models() + ollama_models()
    code, d = _request("GET", "/models", auth=False, timeout=30)
    if code != 200:
        raise NimError(f"model list HTTP {code}")
    ids = sorted(m["id"] for m in d.get("data", []))
    MODELS_CACHE.write_text(json.dumps(ids, indent=0) + "\n")
    return ids + gemini_models(refresh) + ollama_models(refresh)


HEALTH_TTL_HOURS = 6


def _health() -> dict:
    """Models that refused this key recently. Marks EXPIRE: on 2026-09-16 nemotron-3-ultra
    answered 500, 500, then 404 during an NVIDIA incident, and a permanent mark would have
    switched off the only model that passed the verdict bake-off for good."""
    try:
        h = json.loads(HEALTH.read_text())
    except Exception:
        return {}
    cutoff = datetime.now(timezone.utc).timestamp() - HEALTH_TTL_HOURS * 3600
    return {m: v for m, v in h.items() if datetime.fromisoformat(v.get("at", "1970-01-01T00:00:00+00:00")).timestamp() > cutoff}


def candidates(role: str) -> list[str]:
    roster = dict(ROSTER)
    if ROSTER_OVERRIDE.exists():
        roster.update(json.loads(ROSTER_OVERRIDE.read_text()))
    if role not in roster:
        raise NimError(f"unknown role {role!r}; roles: {', '.join(roster)}")
    live, bad = set(models()), _health()
    return [m for m in roster[role] if m in live and m not in bad
            and (not m.startswith("gemini/") or role in GEMINI_ROLES)]      # mail never goes to Gemini


def _log(entry: dict) -> None:
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    with USAGE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _strip_reasoning(text: str) -> str:
    # several of these models think out loud before answering
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def parse_json(text: str):
    """The first JSON object or array in a reply, tolerating code fences and preamble."""
    t = _strip_reasoning(text)
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip())
    # try every position that opens an object or array, earliest first, so a
    # top-level list is not mistaken for the first object inside it
    for start in [i for i, ch in enumerate(t) if ch in "{["]:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise NimError(f"no JSON in reply: {t[:160]!r}")


# Per-call read timeout by role. The heavy roles send 6K to 10K tokens and normally take
# 70 to 150s; on 2026-09-16 Srikar's Greenboard run stopped after two 180s timeouts
# on nemotron-3-ultra while NVIDIA was loaded.
ROLE_TIMEOUT = {"analyst": 420, "writer": 420, "fit": 600}


def chat(role: str, system: str, user: str, *, want_json: bool = False, max_tokens: int = 1500,
         temperature: float = 0.2, purpose: str = "", model: str | None = None) -> dict:
    """One call. Falls through the role's candidates when a model refuses this key.

    `model` pins one model and disables the fallback (the bake-off uses it).
    Returns {"text", "json" (when want_json), "model", "usage", "ms", "truncated"}.
    """
    global _last_call
    tried = []
    for model in ([model] if model else candidates(role)):
        for attempt in range(4):
            wait = MIN_INTERVAL - (time.time() - _last_call)
            if wait > 0:
                time.sleep(wait)
            _last_call = time.time()
            t0 = time.time()
            if model.startswith("ollama/"):
                code, d = _ollama_http("POST", "/chat/completions", {
                    "model": model.split("/", 1)[1], "max_tokens": max_tokens, "temperature": temperature,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                }, ROLE_TIMEOUT.get(role, 180))
            elif model.startswith("gemini/"):
                if role not in GEMINI_ROLES:
                    raise NimError(f"role {role} may not use Gemini (privacy: mail stays off the free tier)")
                code, d = _gemini_chat(model, system, user, max_tokens, temperature, ROLE_TIMEOUT.get(role, 180))
            else:
                code, d = _request("POST", "/chat/completions", {
                    "model": model, "max_tokens": max_tokens, "temperature": temperature,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                }, timeout=ROLE_TIMEOUT.get(role, 180))
            entry = {"at": now(), "role": role, "purpose": purpose, "model": model, "http": code,
                     "ms": int((time.time() - t0) * 1000), "chars_sent": len(system) + len(user)}
            if code == 200:
                choice = (d.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                text = _strip_reasoning(msg.get("content") or "")
                entry["usage"] = d.get("usage") or {}
                entry["finish_reason"] = choice.get("finish_reason")
                # "length" means the budget ran out, usually inside hidden reasoning. On
                # 2026-09-16 that made the keyword agent report "0 edits proposed" when it
                # had produced nothing at all. Callers must treat it as a failure.
                out = {"text": text, "model": model, "usage": entry["usage"], "ms": entry["ms"],
                       "truncated": choice.get("finish_reason") == "length"}
                if want_json:
                    try:
                        out["json"] = parse_json(text)
                    except NimError as e:
                        entry["outcome"] = "bad json"
                        _log(entry)
                        tried.append(f"{model}: {e}")
                        break                                   # next model, not a retry of this one
                entry["outcome"] = "ok"
                _log(entry)
                return out
            entry["outcome"] = str(d.get("error", ""))[:200]
            _log(entry)
            if code == 599 and attempt >= 1:                    # hung twice: move on to the next model
                tried.append(f"{model}: timed out")
                break
            if code in (429, 500, 502, 503, 504, 599):
                if attempt == 3:              # four server errors in a row: say so, rather than "none available"
                    tried.append(f"{model}: HTTP {code} on every retry")
                    break
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            if code in (401,):
                raise NimError("the NVIDIA key was rejected (401)")
            if code == 404 and attempt > 0:                     # a 404 right after 5xx is the outage, not the key
                tried.append(f"{model}: HTTP 404 during server errors")
                break
            if code in (403, 404, 422):                         # this key cannot use this model
                h = _health()
                h[model] = {"http": code, "at": now(), "why": entry["outcome"][:120]}
                HEALTH.write_text(json.dumps(h, indent=1) + "\n")
            tried.append(f"{model}: HTTP {code}")
            break
    raise NimError(f"role {role}: every candidate failed ({'; '.join(tried) or 'none available'})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["models", "check", "ping", "ask"])
    ap.add_argument("--role", default="scout")
    ap.add_argument("prompt", nargs="?")
    a = ap.parse_args()

    if a.cmd == "models":
        print("\n".join(models(refresh=True)))
        return 0
    if a.cmd == "check":
        print(f"key: {'present' if api_key() else 'MISSING (see the docstring)'}")
        for role in ROSTER:
            c = candidates(role)
            print(f"  {role:8} -> {c[0] if c else 'NONE AVAILABLE'}" + (f"   (fallbacks: {', '.join(c[1:])})" if c[1:] else ""))
        return 0 if api_key() else 2
    if a.cmd == "ping":
        ok = True
        for role in ROSTER:
            try:
                r = chat(role, "Reply with exactly: ok", "ping", max_tokens=400, purpose="ping")
                print(f"  {role:8} {r['model']:45} {r['text'][:30]!r}")
            except NimError as e:
                ok = False
                print(f"  {role:8} FAILED {e}")
        return 0 if ok else 1
    r = chat(a.role, "You are a concise assistant.", a.prompt or "", purpose="ask")
    print(f"[{r['model']}] {r['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
