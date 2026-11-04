#!/usr/bin/env python3
"""Run every check in one go: bot access, full site crawl, competitor comparison, AI answer test,
then save the results bundle and executive report to results/<date-time>/.

From the app: the "Run everything" button.
From a terminal or a scheduled task (cron / Task Scheduler):
    python3 runall.py                 settings from runall.json (created with defaults on first run)
    python3 runall.py --skip answers  skip one or more steps: access, crawl, compare, answers
Standard library only. API keys come from environment variables or keys.json, never from runall.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import threading
import time
from pathlib import Path

from ai_bot_check import run as bot_access
from answers import AnswerRun
from bundle import make_bundle
from compare import Compare
from readiness import Crawl
from report import build as build_report

HERE = Path(__file__).resolve().parent
SETTINGS_FILE = HERE / "runall.json"
DEFAULTS = {
    "site": "https://www.methodist.edu",
    "max_pages": 5000,
    "subdomains": True,
    "exclude": "",
    "competitors": None,  # filled from PRESETS below
    "compare_pages": 200,
    "providers": ["anthropic", "openai", "perplexity", "gemini"],
    "out_dir": "results",
}
PRESETS = {
    # EAB "Methodist's Application Overlaps" (Digital and Virtual Engagement deck, p. 25): top 9 by overlap, plus Campbell
    "eab_overlap": {"label": "EAB application overlap (top 9) + Campbell", "sites": [
        "https://www.wingate.edu", "https://www.charlotte.edu", "https://www.ncat.edu", "https://www.ecu.edu", "https://www.lr.edu",
        "https://www.ncsu.edu", "https://www.nccu.edu", "https://www.unc.edu", "https://www.uncg.edu", "https://www.campbell.edu"]},
    # EAB AI Visibility audit, Oct. 19, 2026: seven-institution peer set (MU plus these six)
    "eab_ai_peers": {"label": "EAB AI visibility peer set", "sites": [
        "https://www.campbell.edu", "https://www.wingate.edu", "https://catawba.edu", "https://www.barton.edu",
        "https://www.pfeiffer.edu", "https://belmontabbeycollege.edu"]},
}
DEFAULTS["competitors"] = list(PRESETS["eab_overlap"]["sites"])
STEPS = [("access", "Bot access"), ("crawl", "Site crawl"), ("compare", "Competitors"), ("answers", "AI answers"), ("save", "Save results")]


def load_settings() -> dict:
    s = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            s.update({k: v for k, v in json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass
    return s


def save_settings(s: dict) -> dict:
    clean = {k: s.get(k, v) for k, v in DEFAULTS.items()}
    clean["max_pages"] = max(1, min(int(clean["max_pages"]), 20000))
    clean["compare_pages"] = max(20, min(int(clean["compare_pages"]), 1000))
    clean["competitors"] = [u.strip() for u in clean["competitors"] if str(u).strip()][:10]
    clean["subdomains"] = bool(clean["subdomains"])
    SETTINGS_FILE.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    return clean


class RunAll:
    """Runs the steps one after another. A failed or skipped step does not stop the later ones."""

    def __init__(self, settings: dict, skip: list[str] | None = None, register=None):
        self.s = settings
        self.skip = set(skip or [])
        self.register = register or (lambda kind, obj: None)  # lets the app show each step in its own tab
        self.steps = {k: {"id": k, "label": lbl, "state": "skipped" if k in self.skip else "waiting", "detail": "", "seconds": None}
                      for k, lbl in STEPS}
        self.state = "pending"
        self.current = ""
        self.crawl: Crawl | None = None
        self.access: dict | None = None
        self.compare: Compare | None = None
        self.answers: AnswerRun | None = None
        self.child = None
        self.saved: dict[str, str] = {}
        self.started = time.time()
        self.finished: float | None = None
        self._stop = threading.Event()

    # ---- helpers
    def _wait(self, obj) -> None:
        self.child = obj
        t = threading.Thread(target=obj.run, daemon=True)
        t.start()
        while t.is_alive():
            if self._stop.is_set():
                obj.stop()
            t.join(1)
        self.child = None

    def _step(self, key: str, fn) -> None:
        st = self.steps[key]
        if key in self.skip:
            return
        if self._stop.is_set():
            st["state"] = "stopped"
            return
        self.current = key
        st["state"] = "running"
        t0 = time.time()
        try:
            st["detail"] = fn() or ""
            st["state"] = "stopped" if self._stop.is_set() else "done"
        except Exception as ex:
            st["state"], st["detail"] = "error", f"{type(ex).__name__}: {ex}"
        st["seconds"] = round(time.time() - t0)

    # ---- steps
    def _access(self):
        self.access = bot_access(self.s["site"], probe=True, scan=200)
        bots = self.access.get("bots") or self.access.get("results") or []
        return f"{len(bots)} bots checked" if bots else "done"

    def _crawl(self):
        c = Crawl(self.s["site"], max_pages=int(self.s["max_pages"]), subdomains=bool(self.s["subdomains"]), exclude=self.s.get("exclude") or "")
        self.crawl = c
        self.register("crawl", c)
        self._wait(c)
        if c.state == "error":
            raise RuntimeError(c.error)
        if self.access is not None:
            c.access = self.access
        return f"{len(c.results)} pages checked"

    def _compare(self):
        sites = [self.s["site"]] + list(self.s.get("competitors") or [])
        if len(sites) < 2:
            self.steps["compare"]["state"] = "skipped"
            return "no competitors listed"
        cmp_ = Compare(sites, int(self.s["compare_pages"]))
        self.compare = cmp_
        self.register("compare", cmp_)
        self._wait(cmp_)
        if cmp_.state == "error":
            raise RuntimeError(cmp_.error)
        return f"{len(cmp_.rows)} of {len(cmp_.sites)} sites"

    def _answers(self):
        r = AnswerRun(list(self.s.get("providers") or []))
        if not r.providers:
            raise RuntimeError("no API keys found for " + ", ".join(r.missing_keys or ["any provider"]))
        self.answers = r
        self.register("answers", r)
        self._wait(r)
        if r.state == "error":
            raise RuntimeError(r.error)
        sm = r.summary()
        miss = f"; no key for {', '.join(r.missing_keys)}" if r.missing_keys else ""
        return f"{sm['done']} of {sm['total']} answers, broad mention {sm.get('broad_mention')}%, citation share (broad) {sm.get('citation_share_broad')}%{miss}"

    def _save(self):
        if self.crawl is None or not self.crawl.results:
            raise RuntimeError("no crawl results to save")
        if getattr(self.crawl, "access", None) is None:
            self.crawl.access = self.access or bot_access(self.crawl.start, probe=True, scan=200)
        out = HERE / self.s.get("out_dir", "results") / dt.datetime.now().strftime("%Y-%m-%d-%H%M")
        out.mkdir(parents=True, exist_ok=True)
        host = self.crawl.host.replace(":", "-")
        zp = out / f"ai-readiness-results-{host}.zip"
        zp.write_bytes(make_bundle(self.crawl, self.crawl.access, self.compare if self.compare and self.compare.rows else None,
                                   self.answers if self.answers and self.answers.results else None))
        rp = out / "executive-report.html"
        rp.write_text(build_report(self.crawl.summary(), list(self.crawl.results), self.crawl.pdf_report(), self.crawl.access,
                                   self.answers.summary() if self.answers and self.answers.results else None), encoding="utf-8")
        self.saved = {"folder": str(out), "bundle": str(zp), "report": str(rp)}
        return str(out)

    def run(self) -> None:
        self.state = "running"
        try:
            self._step("access", self._access)
            self._step("crawl", self._crawl)
            self._step("compare", self._compare)
            self._step("answers", self._answers)
            stopped = self._stop.is_set()
            self._stop.clear()  # always save what finished, even after Stop
            self._step("save", self._save)
            self.state = "stopped" if stopped else ("done" if all(s["state"] in ("done", "skipped") for s in self.steps.values()) else "done with errors")
        finally:
            self.current = ""
            self.finished = time.time()

    def stop(self) -> None:
        self._stop.set()

    def progress(self) -> str:
        k, ch = self.current, self.child
        if k == "crawl" and ch is not None:
            return f"{len(ch.results)} of up to {ch.max_pages} pages"
        if k == "compare" and ch is not None:
            st = ch.status()
            return f"site {min(st['done'] + 1, len(st['sites']))} of {len(st['sites'])}: {st['current']} ({st['current_pages']} pages)"
        if k == "answers" and ch is not None:
            return f"{len(ch.results)} of {len(ch.questions) * max(1, len(ch.providers))} answers"
        return ""

    def status(self) -> dict:
        return {"state": self.state, "current": self.current, "progress": self.progress(), "steps": list(self.steps.values()),
                "saved": self.saved, "elapsed_s": round((self.finished or time.time()) - self.started), "settings": self.s}


def main() -> int:
    ap = argparse.ArgumentParser(description="Run every check and save the results bundle and executive report.")
    ap.add_argument("--skip", default="", help="comma-separated steps to skip: access, crawl, compare, answers")
    a = ap.parse_args()
    if not SETTINGS_FILE.exists():
        save_settings(DEFAULTS)
        print(f"created {SETTINGS_FILE.name} with default settings", file=sys.stderr)
    r = RunAll(load_settings(), [x.strip() for x in a.skip.split(",") if x.strip()])
    t = threading.Thread(target=r.run, daemon=True)
    t.start()
    last = ""
    try:
        while t.is_alive():
            t.join(5)
            line = f"{dict(STEPS).get(r.current, '')}: {r.progress()}" if r.current else ""
            if line and line != last:
                print(line, file=sys.stderr)
                last = line
    except KeyboardInterrupt:
        r.stop()
        t.join()
    for s in r.steps.values():
        print(f"{s['label']:<14} {s['state']:<9} {s['detail']}", file=sys.stderr)
    if r.saved:
        print(f"saved to {r.saved['folder']}", file=sys.stderr)
    return 0 if r.state == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
