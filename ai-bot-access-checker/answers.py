"""AI answer tester: asks a fixed question bank to AI assistants with web search on, and scores
whether the institution is mentioned, cited, accurate, and not confused with another school.

Providers (raw HTTP, standard library only):
  anthropic   POST https://api.anthropic.com/v1/messages   (web_search_20260209 server tool)
  openai      POST https://api.openai.com/v1/responses      (web_search tool)
  perplexity  POST https://api.perplexity.ai/v1/agent       (Agent API; web_search tool; preset or model)
  gemini      POST generativelanguage.googleapis.com/v1beta/models/{model}:generateContent (google_search grounding)

Keys are read from the environment (ANTHROPIC_API_KEY, OPENAI_API_KEY, PERPLEXITY_API_KEY, GEMINI_API_KEY) or from
keys.json next to this file ({"anthropic": "...", "openai": "...", "perplexity": "...", "gemini": "..."}). Never commit keys.json; it is in .gitignore.

CLI:  python3 answers.py --out answers.html --csv answers.csv [--providers anthropic,openai] [--ids B01,C01]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from html import escape as e
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ANTHROPIC_MODEL = "claude-opus-5-5"
OPENAI_MODEL = "gpt-5"  # editable in keys.json as "openai_model"; the error from OpenAI names valid models if this is stale
PERPLEXITY_MODEL = "low"            # editable as "perplexity_model": a preset ("low", "medium", ...) or a model such as "openai/gpt-5.6-sol"
GEMINI_MODEL = "gemini-2.5-flash"   # editable as "gemini_model"; "List my models" shows what the key can use
PROVIDERS = ("anthropic", "openai", "perplexity", "gemini")
TIMEOUT = 180
SYSTEM = ("You are helping a prospective college student. Answer the question directly and concisely (under 250 words), "
          "using web search to get current facts. Name specific institutions. Include the sources you used.")


# ---------------------------------------------------------------- config

def load_questions() -> dict:
    with open(os.path.join(HERE, "questions.json"), encoding="utf-8") as f:
        return json.load(f)


def load_keys() -> dict:
    keys = {}
    try:
        with open(os.path.join(HERE, "keys.json"), encoding="utf-8") as f:
            keys = json.load(f)
    except FileNotFoundError:
        pass
    # an exported environment variable wins over keys.json, so a key can live only in the shell
    for name, env in (("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY"),
                      ("perplexity", "PERPLEXITY_API_KEY"), ("gemini", "GEMINI_API_KEY")):
        if os.environ.get(env, "").strip():
            keys[name] = os.environ[env]
        keys.setdefault(name, "")
    return {k: (v or "").strip() if isinstance(v, str) else v for k, v in keys.items()}


def key_status() -> dict:
    k = load_keys()
    return {"anthropic": bool(k.get("anthropic")), "openai": bool(k.get("openai")),
            "perplexity": bool(k.get("perplexity")), "gemini": bool(k.get("gemini")),
            "openai_model": k.get("openai_model") or OPENAI_MODEL, "anthropic_model": ANTHROPIC_MODEL,
            "perplexity_model": k.get("perplexity_model") or PERPLEXITY_MODEL, "gemini_model": k.get("gemini_model") or GEMINI_MODEL}


def save_keys(**fields: str | None) -> None:
    """Accepts anthropic, openai, perplexity, gemini (keys) and openai_model, perplexity_model, gemini_model."""
    k = {}
    try:
        with open(os.path.join(HERE, "keys.json"), encoding="utf-8") as f:
            k = json.load(f)
    except FileNotFoundError:
        pass
    for name, val in fields.items():
        if val is None or name not in ("anthropic", "openai", "perplexity", "gemini", "openai_model", "perplexity_model", "gemini_model"):
            continue
        if val.strip():
            k[name] = val.strip()
    with open(os.path.join(HERE, "keys.json"), "w", encoding="utf-8") as f:
        json.dump(k, f, indent=2)
    try:
        os.chmod(os.path.join(HERE, "keys.json"), 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------- HTTP

def _post(url: str, headers: dict, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as ex:
            txt = ex.read().decode("utf-8", "replace")[:2000]
            if ex.code in (429, 500, 502, 503, 529) and attempt < 2:
                ra = ex.headers.get("retry-after")
                time.sleep(min(int(ra), 60) if ra and ra.isdigit() else 5 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {ex.code}: {txt}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as ex:
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"{type(ex).__name__}: {ex}") from None
    raise RuntimeError("unreachable")


def list_openai_models(key: str) -> list[str]:
    """Model ids the key can use, chat-capable ones first (gpt-*, o*), newest first."""
    req = urllib.request.Request("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
            data = json.loads(r.read().decode("utf-8", "replace")).get("data", [])
    except urllib.error.HTTPError as ex:
        raise RuntimeError(f"HTTP {ex.code}: {ex.read().decode('utf-8', 'replace')[:300]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        raise RuntimeError(f"{type(ex).__name__}: {ex}") from None
    skip = ("embedding", "whisper", "tts", "dall-e", "moderation", "realtime", "audio", "transcribe", "image", "search", "babbage", "davinci", "instruct")
    ids = [m.get("id", "") for m in data if m.get("id")]
    chat = [i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4")) and not any(s in i for s in skip)]

    def key_(i: str):
        m = re.match(r"gpt-(\d+(?:\.\d+)?)", i)
        ver = float(m.group(1)) if m else -1.0
        small = ("-mini" in i or "-nano" in i)
        return (0 if m else 1, -ver, small, i.count("-"), i)  # gpt-* first, newest version first, full size before mini/nano
    return sorted(chat, key=key_)


def list_gemini_models(key: str) -> list[str]:
    """Models the key can use for generateContent, newest first."""
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
            data = json.loads(r.read().decode("utf-8", "replace")).get("models", [])
    except urllib.error.HTTPError as ex:
        raise RuntimeError(f"HTTP {ex.code}: {ex.read().decode('utf-8', 'replace')[:300]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        raise RuntimeError(f"{type(ex).__name__}: {ex}") from None
    ids = [m["name"].split("/", 1)[-1] for m in data if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    ids = [i for i in ids if i.startswith("gemini") and not any(s in i for s in ("embedding", "image", "tts", "audio", "live", "exp"))]
    return sorted(ids, key=lambda i: (("-lite" in i), ("flash" in i), i), reverse=False)


# ---------------------------------------------------------------- providers

def ask_anthropic(q: str, key: str) -> dict:
    """Returns {text, urls, usage}. Handles pause_turn by resending the conversation."""
    headers = {"x-api-key": key, "anthropic-version": "2026-10-21"}
    messages = [{"role": "user", "content": q}]
    usage = {"input": 0, "output": 0, "searches": 0}
    for _ in range(4):
        resp = _post("https://api.anthropic.com/v1/messages", headers, {
            "model": ANTHROPIC_MODEL, "max_tokens": 4096, "system": SYSTEM,
            "output_config": {"effort": "low"},
            "tools": [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
            "messages": messages,
        })
        u = resp.get("usage", {})
        usage["input"] += u.get("input_tokens", 0)
        usage["output"] += u.get("output_tokens", 0)
        usage["searches"] += (u.get("server_tool_use") or {}).get("web_search_requests", 0)
        if resp.get("stop_reason") == "pause_turn":
            messages = messages + [{"role": "assistant", "content": resp["content"]}]
            continue
        break
    if resp.get("stop_reason") == "refusal":
        return {"text": "", "urls": [], "usage": usage, "error": "refusal: " + str((resp.get("stop_details") or {}).get("category"))}
    text, urls = [], []
    for block in resp.get("content", []):
        t = block.get("type")
        if t == "text":
            text.append(block.get("text", ""))
            for c in block.get("citations") or []:
                if c.get("url"):
                    urls.append(c["url"])
        elif t == "web_search_tool_result":
            content = block.get("content")
            if isinstance(content, list):
                for r in content:
                    if r.get("type") == "web_search_result" and r.get("url"):
                        urls.append(r["url"])
    return {"text": "\n".join(text).strip(), "urls": urls, "usage": usage}


def ask_openai(q: str, key: str, model: str) -> dict:
    headers = {"Authorization": f"Bearer {key}"}
    body = {"model": model, "instructions": SYSTEM, "input": q,
            "tools": [{"type": "web_search"}], "max_output_tokens": 16000,
            "reasoning": {"effort": "low"}}
    try:
        resp = _post("https://api.openai.com/v1/responses", headers, body)
    except RuntimeError as ex:
        if "reasoning" not in str(ex):
            raise
        body.pop("reasoning")  # non-reasoning models reject the parameter
        resp = _post("https://api.openai.com/v1/responses", headers, body)
    text, urls = [], []
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    text.append(c.get("text", ""))
                    for a in c.get("annotations") or []:
                        if a.get("url"):
                            urls.append(a["url"])
        elif item.get("type") == "web_search_call":
            for r in ((item.get("action") or {}).get("sources") or []):
                if isinstance(r, dict) and r.get("url"):
                    urls.append(r["url"])
    u = resp.get("usage", {})
    usage = {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0), "searches": 0}
    out = "\n".join(text).strip()
    if not out:
        reason = (resp.get("incomplete_details") or {}).get("reason") or resp.get("status") or "empty answer"
        return {"text": "", "urls": urls, "usage": usage, "error": f"openai returned no answer text ({reason})"}
    return {"text": out, "urls": urls, "usage": usage}


def _parse_responses_output(resp: dict) -> tuple[str, list[str]]:
    """Text and source URLs from a Responses-style payload (OpenAI and Perplexity's Agent API).
    Accepts output[].message.content[].output_text (+ url annotations), a top-level output_text,
    and Perplexity's top-level citations / search_results."""
    text, urls = [], []
    for item in resp.get("output") or []:
        t = item.get("type")
        if t == "message":
            for c in item.get("content") or []:
                if c.get("type") in ("output_text", "text"):
                    text.append(c.get("text", ""))
                    for a in c.get("annotations") or []:
                        if a.get("url"):
                            urls.append(a["url"])
        elif t in ("web_search_call", "search_results", "web_search"):
            for r in ((item.get("action") or {}).get("sources") or item.get("results") or item.get("search_results") or []):
                if isinstance(r, dict) and r.get("url"):
                    urls.append(r["url"])
    if not text and isinstance(resp.get("output_text"), str):
        text.append(resp["output_text"])
    urls += [u for u in resp.get("citations") or [] if isinstance(u, str)]
    urls += [r.get("url") for r in resp.get("search_results") or [] if isinstance(r, dict) and r.get("url")]
    return "\n".join(text).strip(), urls


PERPLEXITY_AGENT_URL = "https://api.perplexity.ai/v1/agent"


def _perplexity_body(q: str, model: str) -> dict:
    """A value with a provider prefix ("openai/gpt-5.6-sol") or a sonar model name is sent as `model`;
    anything else ("low", "medium", ...) is sent as a `preset`, which bundles model, tools and limits."""
    body = {"input": q, "instructions": SYSTEM, "tools": [{"type": "web_search"}]}
    if "/" in model or model.startswith("sonar"):
        body["model"] = model
    else:
        body["preset"] = model
    return body


def ask_perplexity(q: str, key: str, model: str) -> dict:
    """Perplexity Agent API (POST /v1/agent). Web grounding is the web_search tool; answer text comes from
    output_text or the output message items, URL citations from text annotations and search_results items."""
    headers = {"Authorization": f"Bearer {key}"}
    body = _perplexity_body(q, model)
    try:
        resp = _post(PERPLEXITY_AGENT_URL, headers, body)
    except RuntimeError as ex:
        msg = str(ex)
        if not msg.startswith("HTTP 400"):
            raise  # 401 key, 403 credits, 429 already retried with Retry-After
        if "tool" in msg:            # a preset that already bundles its tools may reject an explicit list
            body.pop("tools", None)
        if "instructions" in msg:    # fold the system prompt into the input instead
            body.pop("instructions", None)
            body["input"] = f"{SYSTEM}\n\nQuestion: {q}"
        resp = _post(PERPLEXITY_AGENT_URL, headers, body)
    text, urls = _parse_responses_output(resp)
    u = resp.get("usage", {})
    usage = {"input": u.get("input_tokens", u.get("prompt_tokens", 0)), "output": u.get("output_tokens", u.get("completion_tokens", 0)), "searches": 0}
    if not text:
        reason = (resp.get("incomplete_details") or {}).get("reason") or resp.get("status") or "empty answer"
        return {"text": "", "urls": urls, "usage": usage, "error": f"perplexity returned no answer text ({reason}); response fields: {sorted(resp.keys())}"}
    return {"text": text, "urls": urls, "usage": usage}


def smoke_test(provider: str) -> int:
    """One minimal real request; prints only the HTTP status and response shape, never the key."""
    keys = load_keys()
    if not keys.get(provider):
        env = {"perplexity": "PERPLEXITY_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}[provider]
        print(f"No {provider} key. Create one in the provider's console and export {env} in your terminal (or save it on the AI Answers tab).")
        return 2
    fn = {"perplexity": lambda: ask_perplexity("What is the capital of France? One word.", keys["perplexity"], keys.get("perplexity_model") or PERPLEXITY_MODEL),
          "anthropic": lambda: ask_anthropic("What is the capital of France? One word.", keys["anthropic"]),
          "openai": lambda: ask_openai("What is the capital of France? One word.", keys["openai"], keys.get("openai_model") or OPENAI_MODEL),
          "gemini": lambda: ask_gemini("What is the capital of France? One word.", keys["gemini"], keys.get("gemini_model") or GEMINI_MODEL)}[provider]
    try:
        r = fn()
    except RuntimeError as ex:
        code = str(ex).split(":", 1)[0]
        hint = {"HTTP 401": "authentication failed: check or rotate the key", "HTTP 403": "forbidden: usually missing paid credit or no access to this model",
                "HTTP 429": "rate limited: retried with Retry-After and still limited; try again later"}.get(code, "")
        print(f"{provider}: {code} {hint}".rstrip())
        return 1
    if r.get("error"):
        print(f"{provider}: 200 but {r['error']}")
        return 1
    print(f"{provider}: HTTP 200 · answer {len(r['text'])} chars · {len(r['urls'])} source URL(s)")
    return 0


def ask_gemini(q: str, key: str, model: str) -> dict:
    """generateContent with Google Search grounding; sources in candidates[].groundingMetadata.groundingChunks[].web.uri."""
    resp = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", {"x-goog-api-key": key}, {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": q}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"maxOutputTokens": 2048},
    })
    cands = resp.get("candidates") or []
    if not cands:
        reason = (resp.get("promptFeedback") or {}).get("blockReason") or "no candidates"
        return {"text": "", "urls": [], "usage": {}, "error": f"gemini: {reason}"}
    c = cands[0]
    text = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", []))
    gm = c.get("groundingMetadata") or {}
    urls = [(ch.get("web") or {}).get("uri") for ch in gm.get("groundingChunks") or [] if (ch.get("web") or {}).get("uri")]
    u = resp.get("usageMetadata", {})
    return {"text": text.strip(), "urls": urls, "usage": {"input": u.get("promptTokenCount", 0), "output": u.get("candidatesTokenCount", 0), "searches": 0}}


# ---------------------------------------------------------------- scoring

def _host(u: str) -> str:
    return urlsplit(u).netloc.lower().removeprefix("www.")


def score(qd: dict, bank: dict, text: str, urls: list[str], home_domain: str) -> dict:
    alias_rx = "|".join(f"(?:{a})" for a in bank["institution_aliases"])
    mentioned = bool(re.search(alias_rx, text, re.I))
    cited_urls = sorted({u for u in urls if _host(u) == home_domain or _host(u).endswith("." + home_domain)})
    other_hosts = sorted({_host(u) for u in urls if _host(u) and not (_host(u) == home_domain or _host(u).endswith("." + home_domain))})
    peers = [p for p in bank.get("peers", []) if re.search(r"\b" + re.escape(p), text, re.I)]
    first_mu = (re.search(alias_rx, text, re.I) or type("m", (), {"start": lambda self: 10**9})()).start()
    # a confusion only if the other school is named before (or instead of) the institution; a disambiguation
    # aside after naming the right school ("not Southern Methodist") does not count
    confused = [c for c in bank.get("confusion_terms", []) for m in [re.search(c, text, re.I)] if m and m.start() < first_mu]
    missing = [m for m in qd.get("must_contain", []) if not re.search(m, text, re.I)]
    forbidden = [m for m in qd.get("must_not_contain", []) if re.search(m, text, re.I)]
    accurate = None if not qd.get("must_contain") and not qd.get("must_not_contain") else (not missing and not forbidden)
    if qd["type"] == "branded":
        ok = mentioned and not confused and accurate is not False
    else:
        ok = mentioned
    return {"mentioned": mentioned, "cited": bool(cited_urls), "cited_urls": cited_urls[:5], "other_sources": other_hosts[:8],
            "peers_mentioned": peers, "confused_with": confused, "missing_facts": missing, "forbidden_found": forbidden,
            "accurate": accurate, "pass": ok}


# ---------------------------------------------------------------- run

class AnswerRun:
    def __init__(self, providers: list[str], ids: list[str] | None = None, home_domain: str = "methodist.edu"):
        self.bank = load_questions()
        self.keys = load_keys()
        self.providers = [p for p in providers if self.keys.get(p)]
        self.missing_keys = [p for p in providers if not self.keys.get(p)]
        self.questions = [q for q in self.bank["questions"] if not ids or q["id"] in ids]
        self.home_domain = home_domain
        self.results: list[dict] = []
        self.state = "pending"
        self.error = ""
        self.started = time.time()
        self.finished: float | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def run(self) -> None:
        self.state = "running"
        try:
            if not self.providers:
                raise RuntimeError("No API keys found. Add them under Keys on the AI Answers tab.")
            for qd in self.questions:
                for prov in self.providers:
                    if self._stop.is_set():
                        break
                    t0 = time.time()
                    try:
                        if prov == "anthropic":
                            a = ask_anthropic(qd["q"], self.keys["anthropic"])
                        elif prov == "openai":
                            a = ask_openai(qd["q"], self.keys["openai"], self.keys.get("openai_model") or OPENAI_MODEL)
                        elif prov == "perplexity":
                            a = ask_perplexity(qd["q"], self.keys["perplexity"], self.keys.get("perplexity_model") or PERPLEXITY_MODEL)
                        elif prov == "gemini":
                            a = ask_gemini(qd["q"], self.keys["gemini"], self.keys.get("gemini_model") or GEMINI_MODEL)
                        else:
                            a = {"text": "", "urls": [], "usage": {}, "error": f"unknown provider {prov}"}
                    except RuntimeError as ex:
                        a = {"text": "", "urls": [], "usage": {}, "error": str(ex)}
                    if not a.get("error") and not a.get("text"):
                        a["error"] = f"{prov} returned no answer text"
                    row = {"id": qd["id"], "type": qd["type"], "topic": qd["topic"], "question": qd["q"], "provider": prov,
                           "answer": a["text"], "error": a.get("error", ""), "seconds": round(time.time() - t0, 1), "usage": a.get("usage", {})}
                    row.update(score(qd, self.bank, a["text"], a["urls"], self.home_domain) if not a.get("error") else
                               {"mentioned": None, "cited": None, "cited_urls": [], "other_sources": [], "peers_mentioned": [],
                                "confused_with": [], "missing_facts": [], "forbidden_found": [], "accurate": None, "pass": None})
                    with self._lock:
                        self.results.append(row)
                if self._stop.is_set():
                    break
            self.state = "stopped" if self._stop.is_set() else "done"
        except Exception as ex:
            self.state, self.error = "error", f"{type(ex).__name__}: {ex}"
        finally:
            self.finished = time.time()

    def stop(self):
        self._stop.set()

    def summary(self) -> dict:
        with self._lock:
            rows = list(self.results)
        ok = [r for r in rows if not r["error"]]

        def rate(xs, key):
            xs = [r for r in xs if r.get(key) is not None]
            return round(100 * sum(1 for r in xs if r[key]) / len(xs)) if xs else None

        by_prov = {}
        for p in self.providers:
            pr = [r for r in ok if r["provider"] == p]
            by_prov[p] = {
                "answered": len(pr), "errors": sum(1 for r in rows if r["provider"] == p and r["error"]),
                "branded_mention": rate([r for r in pr if r["type"] == "branded"], "mentioned"),
                "category_mention": rate([r for r in pr if r["type"] == "category"], "mentioned"),
                "cited": rate(pr, "cited"),
                "accurate": rate([r for r in pr if r["type"] == "branded"], "accurate"),
                "confused": sum(1 for r in pr if r["confused_with"]),
            }
        src = {}
        for r in ok:
            for h in r["other_sources"]:
                src[h] = src.get(h, 0) + 1
        peer = {}
        for r in ok:
            if r["type"] == "category":
                for p in r["peers_mentioned"]:
                    peer[p] = peer.get(p, 0) + 1
        cat = [r for r in ok if r["type"] == "category"]
        tok_in = sum(r["usage"].get("input", 0) for r in rows)
        tok_out = sum(r["usage"].get("output", 0) for r in rows)
        return {
            "state": self.state, "error": self.error, "providers": self.providers, "missing_keys": self.missing_keys,
            "questions": len(self.questions), "done": len(rows), "total": len(self.questions) * max(1, len(self.providers)),
            "elapsed_s": round((self.finished or time.time()) - self.started),
            "branded_mention": rate([r for r in ok if r["type"] == "branded"], "mentioned"),
            "category_mention": rate(cat, "mentioned"),
            "citation_rate": rate(ok, "cited"),
            "accuracy": rate([r for r in ok if r["type"] == "branded"], "accurate"),
            "confusions": sum(1 for r in ok if r["confused_with"]),
            "by_provider": by_prov,
            "top_sources": sorted(({"host": h, "answers": n} for h, n in src.items()), key=lambda x: -x["answers"])[:15],
            "peer_mentions": sorted(({"peer": p, "answers": n} for p, n in peer.items()), key=lambda x: -x["answers"]),
            "category_total": len(cat),
            "tokens": {"input": tok_in, "output": tok_out},
            "date": dt.date.today().isoformat(),
        }

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "type", "topic", "question", "provider", "pass", "mentioned", "cited", "accurate", "confused_with",
                    "peers_mentioned", "missing_facts", "cited_urls", "other_sources", "error", "answer"])
        with self._lock:
            rows = list(self.results)
        for r in rows:
            w.writerow([r["id"], r["type"], r["topic"], r["question"], r["provider"], r["pass"], r["mentioned"], r["cited"], r["accurate"],
                        "; ".join(r["confused_with"]), "; ".join(r["peers_mentioned"]), "; ".join(r["missing_facts"]),
                        " ".join(r["cited_urls"]), " ".join(r["other_sources"]), r["error"], r["answer"]])
        return buf.getvalue()

    def report(self) -> str:
        return build_answers_report(self.summary(), list(self.results), self.bank)


# ---------------------------------------------------------------- report

def build_answers_report(s: dict, rows: list[dict], bank: dict) -> str:
    inst = bank["institution"]

    def pct(v):
        return "-" if v is None else f"{v}%"

    def pill(v, good=True):
        if v is None:
            return '<span class="pill">-</span>'
        return f'<span class="pill {"ok" if bool(v) == good else "bad"}">{"yes" if v else "no"}</span>'

    prov_rows = "".join(
        f"<tr><td>{e(p)}</td><td>{d['answered']}</td><td>{pct(d['branded_mention'])}</td><td>{pct(d['category_mention'])}</td>"
        f"<td>{pct(d['cited'])}</td><td>{pct(d['accurate'])}</td><td>{d['confused']}</td><td>{d['errors']}</td></tr>"
        for p, d in s["by_provider"].items())
    q_rows = "".join(
        f"<tr><td class='nw'>{e(r['id'])}</td><td>{e(r['question'])}</td><td>{e(r['provider'])}</td>"
        f"<td>{pill(r['mentioned'])}</td><td>{pill(r['cited'])}</td><td>{pill(r['accurate']) if r['type'] == 'branded' else '-'}</td>"
        f"<td>{e(', '.join(r['peers_mentioned'])) or '-'}</td>"
        f"<td>{('<span class=\"bad\">' + e(', '.join(r['confused_with'])) + '</span>') if r['confused_with'] else ('<span class=\"bad\">missing: ' + e(', '.join(r['missing_facts'])) + '</span>') if r['missing_facts'] else (e(r['error'][:80]) if r['error'] else '-')}</td></tr>"
        for r in rows)
    answers = "".join(
        f"<details><summary><b>{e(r['id'])}</b> {e(r['question'])} <span class='muted'>({e(r['provider'])})</span></summary>"
        f"<pre>{e(r['answer'] or r['error'])}</pre><p class='note'>Cited {inst}: {e(', '.join(r['cited_urls'])) or 'no'} · Other sources: {e(', '.join(r['other_sources'])) or 'none'}</p></details>"
        for r in rows)
    src = "".join(f"<tr><td>{e(x['host'])}</td><td>{x['answers']}</td></tr>" for x in s["top_sources"])
    peers = "".join(f"<tr><td>{e(x['peer'])}</td><td>{x['answers']} of {s['category_total']}</td></tr>" for x in s["peer_mentions"][:12])
    mu_cat = round(s["category_mention"] / 100 * s["category_total"]) if s["category_mention"] is not None else 0
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Answer Test</title><style>
body{{margin:0;background:#fff;color:#1b1b1f;font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}} main{{max-width:1000px;margin:0 auto;padding:32px 24px}}
h1{{font-size:24px;margin:0}} h2{{font-size:16px;margin:24px 0 8px;border-bottom:2px solid #1b1b1f;padding-bottom:4px}}
.meta,.note,.muted{{color:#5f6068;font-size:12px}} table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #dcdce2;vertical-align:top}} th{{font-size:11px;text-transform:uppercase;color:#5f6068}} td.nw{{white-space:nowrap}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}} .tile{{border:1px solid #dcdce2;border-radius:8px;padding:10px 12px}} .tile b{{display:block;font-size:24px}} .tile span{{color:#5f6068;font-size:12px}}
.pill{{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:600}} .ok{{color:#1a7f37;background:#e7f6ec}} .bad{{color:#b42318;background:#fdecea}}
pre{{white-space:pre-wrap;background:#f5f5f7;padding:10px;border-radius:6px;font-size:12px}} details{{margin:6px 0}}
.bar{{position:sticky;top:0;background:#fff;border-bottom:1px solid #dcdce2;padding:10px 24px;text-align:right}} .bar button{{padding:8px 16px;border:0;border-radius:6px;background:#2f5bd3;color:#fff;font-weight:600;cursor:pointer}}
@media print{{.bar{{display:none}} details{{break-inside:avoid}}}}
</style></head><body><div class="bar"><button onclick="window.print()">Print / Save as PDF</button></div><main>
<h1>AI Answer Test: {e(inst)}</h1>
<div class="meta">{e(s['date'])} · {s['questions']} questions · {e(', '.join(s['providers']))} · web search on · {s['elapsed_s']}s</div>
<div class="tiles">
<div class="tile"><b>{pct(s['branded_mention'])}</b><span>branded questions that mention {e(inst)}</span></div>
<div class="tile"><b>{pct(s['category_mention'])}</b><span>category questions that mention {e(inst)}</span></div>
<div class="tile"><b>{pct(s['citation_rate'])}</b><span>answers citing {e(bank.get('home_domain', 'methodist.edu'))}</span></div>
<div class="tile"><b>{pct(s['accuracy'])}</b><span>branded answers with all required facts</span></div>
</div>
<p><b>Reading this.</b> Branded questions name the school; category questions do not. EAB's audit standard: branded mention near 100% is expected; the growth opportunity is category mention. Confusions = answers that mixed {e(inst)} up with another "Methodist" institution ({s['confusions']} found).</p>
<h2>By provider</h2>
<table><thead><tr><th>Provider</th><th>Answered</th><th>Branded mention</th><th>Category mention</th><th>Cites site</th><th>Accurate</th><th>Confusions</th><th>Errors</th></tr></thead><tbody>{prov_rows}</tbody></table>
<h2>Who gets named on category questions</h2>
<table><thead><tr><th>Institution</th><th>Mentioned in</th></tr></thead><tbody><tr><td><b>{e(inst)}</b></td><td><b>{mu_cat} of {s['category_total']}</b></td></tr>{peers}</tbody></table>
<h2>Sources the AIs used instead of {e(inst)}'s site</h2>
<p class="note">These third-party sites shape what AI says. Check that each one's listing for {e(inst)} is current.</p>
<table><thead><tr><th>Source</th><th>Answers</th></tr></thead><tbody>{src}</tbody></table>
<h2>Every question</h2>
<table><thead><tr><th>ID</th><th>Question</th><th>Provider</th><th>Mentioned</th><th>Cited</th><th>Accurate</th><th>Peers named</th><th>Issue</th></tr></thead><tbody>{q_rows}</tbody></table>
<h2>Answers</h2>
{answers}
<p class="note">Method: each question is sent once per provider with web search enabled and a neutral system prompt. Mentioned = the answer names the institution. Cited = a search result or citation is on the institution's domain. Accurate = every required fact in questions.json appears and no forbidden term does (branded questions with rules only). Tokens used: {s['tokens']['input']:,} in, {s['tokens']['output']:,} out.</p>
</main></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Ask AI assistants a question bank and score mentions, citations and accuracy.")
    ap.add_argument("--providers", default="anthropic,openai,perplexity,gemini")
    ap.add_argument("--ids", default="", help="comma-separated question ids to run (default all)")
    ap.add_argument("--domain", default="methodist.edu")
    ap.add_argument("--out", default="ai-answers.html")
    ap.add_argument("--csv")
    ap.add_argument("--json")
    ap.add_argument("--smoke", metavar="PROVIDER", help="send one minimal request to a provider and print only the status")
    a = ap.parse_args()
    if a.smoke:
        return smoke_test(a.smoke)
    run = AnswerRun([p.strip() for p in a.providers.split(",") if p.strip()], [x.strip() for x in a.ids.split(",") if x.strip()], a.domain)
    if run.missing_keys:
        print("no key for: " + ", ".join(run.missing_keys), file=sys.stderr)
    t = threading.Thread(target=run.run, daemon=True)
    t.start()
    try:
        while t.is_alive():
            t.join(2)
            print(f"\r{len(run.results)} of {len(run.questions) * max(1, len(run.providers))} answers   ", end="", file=sys.stderr)
    except KeyboardInterrupt:
        run.stop()
        t.join()
    print(file=sys.stderr)
    s = run.summary()
    if s["error"]:
        print("error: " + s["error"], file=sys.stderr)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(run.report())
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            f.write(run.to_csv())
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"summary": s, "results": run.results}, f, indent=2)
    print(f"branded mention {s['branded_mention']}%, category mention {s['category_mention']}%, cited {s['citation_rate']}%, accurate {s['accuracy']}%", file=sys.stderr)
    print(f"wrote {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
