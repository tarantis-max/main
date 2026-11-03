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
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ai_bot_check import run
from readiness import CHECKS, Crawl

JOBS: dict[str, Crawl] = {}

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
            target = (q.get("url") or [""])[0].strip()
            if not target:
                self._send(400, b'{"error":"url is required"}', "application/json")
                return
            try:
                c = Crawl(target,
                          max_pages=max(1, min(int((q.get("max") or ["500"])[0]), 20000)),
                          subdomains=(q.get("subdomains") or ["0"])[0] == "1",
                          exclude=(q.get("exclude") or [""])[0])
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
                return
            jid = uuid.uuid4().hex[:8]
            JOBS[jid] = c
            threading.Thread(target=c.run, daemon=True).start()
            self._send(200, json.dumps({"id": jid}).encode(), "application/json")
        elif u.path in ("/api/crawl/status", "/api/crawl/stop", "/api/crawl/csv"):
            jid = (parse_qs(u.query).get("id") or [""])[0]
            c = JOBS.get(jid)
            if not c:
                self._send(404, b'{"error":"unknown job"}', "application/json")
            elif u.path.endswith("stop"):
                c.stop()
                self._send(200, b'{"ok":true}', "application/json")
            elif u.path.endswith("csv"):
                self.send_response(200)
                body = c.to_csv().encode()
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="ai-readiness-{c.host}.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                pages = [{k: v for k, v in p.items() if k != "_links"} for p in list(c.results)]
                self._send(200, json.dumps({"summary": c.summary(), "pages": pages}).encode(), "application/json")
        elif u.path == "/api/checks":
            self._send(200, json.dumps([{"id": a, "label": b, "rule": r, "critical": k} for a, b, r, k in CHECKS]).encode(), "application/json")
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
    print(f"AI Bot Access Checker running at {url}  (Ctrl+C to stop)")
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
