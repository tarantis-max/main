#!/usr/bin/env python3
"""Local web app for the AI bot access checker.

Run:   python3 app.py            (then open http://localhost:8000)
       python3 app.py --port 9000
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ai_bot_check import run
from readiness import CHECKS, DEFAULTS, MESSAGES, Crawl
from report import build as build_report
from bundle import make_bundle, VERSION
from compare import Compare
from answers import AnswerRun, key_status, save_keys, load_questions, list_openai_models, list_gemini_models, load_keys
from runall import RunAll, load_settings, save_settings, PRESETS

JOBS: dict[str, Crawl] = {}


def busy() -> str:
    """A crawl and a comparison at the same time slow each other down and distort response times."""
    if any(r.state in ("pending", "running") for r in RUNALLS.values()):
        return "Run everything is in progress. Wait for it to finish or stop it first."
    if any(c.state in ("pending", "running") for c in JOBS.values()):
        return "A Site Readiness crawl is running. Wait for it to finish or stop it first, so response times stay accurate."
    if any(c.state in ("pending", "running") for c in COMPARES.values()):
        return "A competitor comparison is running. Wait for it to finish or stop it first, so response times stay accurate."
    return ""
COMPARES: dict[str, Compare] = {}
ANSWERS: dict[str, AnswerRun] = {}
RUNALLS: dict[str, RunAll] = {}


def _register(kind: str, obj) -> None:
    """Steps of Run everything also appear in their own tabs (and the bundle/report buttons there)."""
    {"crawl": JOBS, "compare": COMPARES, "answers": ANSWERS}[kind][kind[0] + "-" + uuid.uuid4().hex[:6]] = obj


def safe_name(s: str) -> str:
    """File-name-safe on Windows, macOS and Linux."""
    import re
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-") or "site"

HERE = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif u.path == "/api/check":
            q = parse_qs(u.query)
            target = (q.get("url") or [""])[0].strip()
            if not target:
                self._send(400, b'{"error":"url is required"}', "application/json")
                return
            try:
                scan = min(int((q.get("scan") or ["0"])[0] or 0), 500)
                rep = run(target, probe=q.get("probe", ["1"])[0] != "0", scan=scan)
                self._send(200, json.dumps(rep).encode(), "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(), "application/json")
        elif u.path == "/api/crawl/start":
            q = parse_qs(u.query)
            if busy():
                self._send(409, json.dumps({"error": busy()}).encode(), "application/json")
                return
            target = (q.get("url") or [""])[0].strip()
            if not target:
                self._send(400, b'{"error":"url is required"}', "application/json")
                return
            try:
                c = Crawl(target,
                          max_pages=max(1, min(int((q.get("max") or ["500"])[0]), 20000)),
                          subdomains=(q.get("subdomains") or ["0"])[0] == "1",
                          exclude=(q.get("exclude") or [""])[0],
                          official_name=q["name"][0] if "name" in q else None,
                          city=q["city"][0] if "city" in q else None,
                          region=q["state"][0] if "state" in q else None,
                          former_names=q["former"][0].split(",") if "former" in q else None,
                          priority_pages=[x for x in q["priority"][0].splitlines() if x.strip()] if "priority" in q else None)
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
                return
            jid = uuid.uuid4().hex[:8]
            JOBS[jid] = c
            threading.Thread(target=c.run, daemon=True).start()
            self._send(200, json.dumps({"id": jid}).encode(), "application/json")
        elif u.path == "/api/compare/start":
            q = parse_qs(u.query)
            if busy():
                self._send(409, json.dumps({"error": busy()}).encode(), "application/json")
                return
            sites = [x for x in (q.get("sites") or [""])[0].replace(",", "\n").splitlines() if x.strip()]
            if len(sites) < 2:
                self._send(400, b'{"error":"enter your site and at least one competitor"}', "application/json")
                return
            if len(sites) > 11:
                self._send(400, b'{"error":"up to 10 competitors"}', "application/json")
                return
            cmp_ = Compare(sites, max(20, min(int((q.get("max") or ["200"])[0]), 1000)))
            cid = uuid.uuid4().hex[:8]
            COMPARES[cid] = cmp_
            threading.Thread(target=cmp_.run, daemon=True).start()
            self._send(200, json.dumps({"id": cid}).encode(), "application/json")
        elif u.path in ("/api/compare/status", "/api/compare/stop", "/api/compare/csv", "/api/compare/report"):
            cmp_ = COMPARES.get((parse_qs(u.query).get("id") or [""])[0])
            if not cmp_:
                self._send(404, b'{"error":"unknown comparison"}', "application/json")
            elif u.path.endswith("stop"):
                cmp_.stop()
                self._send(200, b'{"ok":true}', "application/json")
            elif u.path.endswith("csv"):
                body = cmp_.to_csv().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="competitor-comparison-{time.strftime("%Y%m%d-%H%M")}.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path.endswith("report"):
                self._send(200, cmp_.report().encode(), "text/html; charset=utf-8")
            else:
                self._send(200, json.dumps(cmp_.status()).encode(), "application/json")
        elif u.path == "/api/answers/keys":
            self._send(200, json.dumps(key_status()).encode(), "application/json")
        elif u.path in ("/api/answers/openai-models", "/api/answers/gemini-models"):
            prov = "openai" if "openai" in u.path else "gemini"
            key = load_keys().get(prov, "")
            if not key:
                self._send(400, json.dumps({"error": f"Save a {'Google Gemini' if prov == 'gemini' else 'OpenAI'} key first."}).encode(), "application/json")
                return
            try:
                models = list_openai_models(key) if prov == "openai" else list_gemini_models(key)
                self._send(200, json.dumps({"models": models}).encode(), "application/json")
            except RuntimeError as ex:
                self._send(502, json.dumps({"error": str(ex)}).encode(), "application/json")
        elif u.path == "/api/answers/questions":
            self._send(200, json.dumps(load_questions()).encode(), "application/json")
        elif u.path == "/api/answers/start":
            q = parse_qs(u.query)
            provs = [p for p in (q.get("providers") or ["anthropic,openai,perplexity,gemini"])[0].split(",") if p.strip()]
            ids = [x for x in (q.get("ids") or [""])[0].split(",") if x.strip()]
            run_ = AnswerRun(provs, ids, (q.get("domain") or ["methodist.edu"])[0])
            if not run_.providers:
                self._send(400, json.dumps({"error": "No API key for " + ", ".join(run_.missing_keys) + ". Add keys first."}).encode(), "application/json")
                return
            aid = uuid.uuid4().hex[:8]
            ANSWERS[aid] = run_
            threading.Thread(target=run_.run, daemon=True).start()
            self._send(200, json.dumps({"id": aid, "missing_keys": run_.missing_keys}).encode(), "application/json")
        elif u.path in ("/api/answers/status", "/api/answers/stop", "/api/answers/csv", "/api/answers/report"):
            run_ = ANSWERS.get((parse_qs(u.query).get("id") or [""])[0])
            if not run_:
                self._send(404, b'{"error":"unknown run"}', "application/json")
            elif u.path.endswith("stop"):
                run_.stop()
                self._send(200, b'{"ok":true}', "application/json")
            elif u.path.endswith("csv"):
                body = run_.to_csv().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="ai-answers-{time.strftime("%Y%m%d-%H%M")}.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path.endswith("report"):
                self._send(200, run_.report().encode(), "text/html; charset=utf-8")
            else:
                self._send(200, json.dumps({"summary": run_.summary(), "results": list(run_.results)}).encode(), "application/json")
        elif u.path == "/api/bundle":
            c = JOBS.get((parse_qs(u.query).get("id") or [""])[0])
            if not c:
                self._send(404, b"Unknown crawl. Run a crawl first.", "text/plain")
                return
            if c.state == "running":
                self._send(409, b"The crawl is still running. Stop it or wait for it to finish.", "text/plain")
                return
            try:
                if getattr(c, "access", None) is None:
                    c.access = run(c.start, probe=True, scan=200)
                done = [x for x in COMPARES.values() if x.rows]
                ans = [x for x in ANSWERS.values() if x.results]
                body = make_bundle(c, c.access, done[-1] if done else None, ans[-1] if ans else None)
                stamp = time.strftime("%Y%m%d-%H%M")
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="ai-readiness-results-{safe_name(c.host)}-{stamp}.zip"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._send(500, f"Bundle failed: {type(e).__name__}: {e}".encode(), "text/plain")
        elif u.path == "/api/report":
            c = JOBS.get((parse_qs(u.query).get("id") or [""])[0])
            if not c:
                self._send(404, b"Unknown crawl. Run a crawl first.", "text/plain")
                return
            if c.state == "running":
                self._send(409, b"The crawl is still running. Stop it or wait for it to finish, then open the report.", "text/plain")
                return
            try:
                if getattr(c, "access", None) is None:
                    c.access = run(c.start, probe=True, scan=200)
                ans = [x for x in ANSWERS.values() if x.results]
                html = build_report(c.summary(), list(c.results), c.pdf_report(), c.access, ans[-1].summary() if ans else None)
                self._send(200, html.encode(), "text/html; charset=utf-8")
            except Exception as e:
                self._send(500, f"Report failed: {type(e).__name__}: {e}".encode(), "text/plain")
        elif u.path in ("/api/crawl/status", "/api/crawl/stop", "/api/crawl/csv", "/api/crawl/pdfcsv"):
            jid = (parse_qs(u.query).get("id") or [""])[0]
            c = JOBS.get(jid)
            if not c:
                self._send(404, b'{"error":"unknown job"}', "application/json")
            elif u.path.endswith("stop"):
                c.stop()
                self._send(200, b'{"ok":true}', "application/json")
            elif u.path.endswith("csv"):
                self.send_response(200)
                pdf = u.path.endswith("pdfcsv")
                body = (c.pdf_csv() if pdf else c.to_csv()).encode()
                name = f"ai-readiness-{'pdfs' if pdf else 'pages'}-{safe_name(c.host)}.csv"
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                pages = [{k: v for k, v in p.items() if not k.startswith("_")} for p in list(c.results)]
                self._send(200, json.dumps({"summary": c.summary(), "pages": pages, "pdfs": c.pdf_report()}).encode(), "application/json")
        elif u.path == "/api/all/settings":
            self._send(200, json.dumps({**load_settings(), "presets": PRESETS}).encode(), "application/json")
        elif u.path in ("/api/all/status", "/api/all/stop", "/api/all/bundle", "/api/all/report"):
            r = RUNALLS.get((parse_qs(u.query).get("id") or [""])[0])
            if not r:
                self._send(404, b'{"error":"unknown run"}', "application/json")
            elif u.path.endswith("stop"):
                r.stop()
                self._send(200, b'{"ok":true}', "application/json")
            elif u.path.endswith("status"):
                self._send(200, json.dumps(r.status()).encode(), "application/json")
            elif not r.saved:
                self._send(409, b"Results are saved when the run finishes.", "text/plain")
            elif u.path.endswith("bundle"):
                body = Path(r.saved["bundle"]).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{Path(r.saved["bundle"]).stem}-{time.strftime("%Y%m%d-%H%M")}.zip"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._send(200, Path(r.saved["report"]).read_bytes(), "text/html; charset=utf-8")
        elif u.path == "/api/version":
            self._send(200, json.dumps({"version": VERSION}).encode(), "application/json")
        elif u.path == "/api/defaults":
            self._send(200, json.dumps({**DEFAULTS, "priority_pages": MESSAGES.get("priority_pages", [])}).encode(), "application/json")
        elif u.path == "/api/checks":
            self._send(200, json.dumps([{"id": a, "label": b, "rule": r, "critical": k} for a, b, r, k in CHECKS]).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urlsplit(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if u.path == "/api/all/start":
            if busy() or any(a.state == "running" for a in ANSWERS.values()):
                self._send(409, json.dumps({"error": busy() or "An AI answer test is running. Wait for it to finish or stop it first."}).encode(), "application/json")
                return
            try:
                settings = save_settings({**load_settings(), **json.loads(raw or b"{}")})
            except Exception as ex:
                self._send(400, json.dumps({"error": f"settings: {ex}"}).encode(), "application/json")
                return
            r = RunAll(settings, register=_register)
            rid = uuid.uuid4().hex[:8]
            RUNALLS[rid] = r
            threading.Thread(target=r.run, daemon=True).start()
            self._send(200, json.dumps({"id": rid}).encode(), "application/json")
        elif u.path == "/api/answers/keys":
            try:
                d = json.loads(raw or b"{}")
                save_keys(**{k: v for k, v in d.items() if isinstance(v, str)})
                self._send(200, json.dumps(key_status()).encode(), "application/json")
            except Exception as ex:
                self._send(400, json.dumps({"error": str(ex)}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, fmt, *args):
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://localhost:{a.port}"
    print(f"AI Access & Readiness {VERSION} running at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
