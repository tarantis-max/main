"""Results bundle: one zip with everything needed to review a run.

Contents: manifest.json, summary.json, pages.csv, pdfs.csv, bot-access.json, report.html.
All data is public website data (URLs, titles, check results); no personal information.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import platform
import zipfile

from ai_bot_check import DENY
from readiness import CHECKS, Crawl
from report import build as build_report

VERSION = "2026.11.04.33"


def make_bundle(c: Crawl, access: dict | None, comparison=None, answers=None) -> bytes:
    summary = c.summary()
    pages = [{k: v for k, v in p.items() if not k.startswith("_")} for p in list(c.results)]
    manifest = {
        "tool": "AI Access & Readiness",
        "version": VERSION,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "start_url": c.start,
        "crawl_state": c.state,
        "pages_checked": len(pages),
        "max_pages": c.max_pages,
        "include_subdomains": c.subdomains,
        "exclude_regex": c.exclude.pattern if c.exclude else "",
        "settings": {k: v for k, v in c.cfg.items() if k != "ay_start"},
        "academic_year": summary["academic_year"],
        "deny_list": DENY,
        "checks": [{"id": a, "label": b, "rule": r, "critical": k} for a, b, r, k in CHECKS],
        "files": {
            "summary.json": "crawl summary: grades, check failure counts, organization schema, PDF counts",
            "pages.json": "every page with all check results and details",
            "pages.csv": "same as pages.json, spreadsheet format",
            "pdfs.csv": "linked PDFs with key-fact and past-term flags",
            "bot-access.json": "per-bot robots.txt, sitemap coverage, live probe and policy results",
            "report.html": "executive report",
            "comparison.json / comparison.csv / comparison.html": "latest competitor comparison, if one was run",
            "answers.json / answers.csv / answers.html": "latest AI answer test, if one was run (answers only; no API keys)",
        },
    }
    st = comparison.status() if comparison is not None else None
    if st:
        manifest["comparison"] = "complete" if st["state"] == "done" else f"partial: {st['done']} of {len(st['sites'])} sites, status {st['state']}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("summary.json", json.dumps(summary, indent=2))
        z.writestr("pages.json", json.dumps(pages, indent=1))
        z.writestr("pages.csv", c.to_csv())
        z.writestr("pdfs.csv", c.pdf_csv())
        z.writestr("bot-access.json", json.dumps(access, indent=2) if access else "null")
        z.writestr("report.html", build_report(summary, list(c.results), c.pdf_report(), access, answers.summary() if answers is not None else None))
        if comparison is not None:
            z.writestr("comparison.json", json.dumps(st, indent=2))
            z.writestr("comparison.csv", comparison.to_csv())
            z.writestr("comparison.html", comparison.report())
        if answers is not None:
            z.writestr("answers.json", json.dumps({"summary": answers.summary(), "results": answers.results}, indent=2))
            z.writestr("answers.csv", answers.to_csv())
            z.writestr("answers.html", answers.report())
    return buf.getvalue()
