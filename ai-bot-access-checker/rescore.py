#!/usr/bin/env python3
"""Rescore saved results bundles with the current grading (Access + Answer quality), so runs compare.

    python3 rescore.py ai-readiness-results-www.methodist.edu-20261104-1306.zip
    python3 rescore.py old1.zip old2.zip --report-dir rescored

Prints old vs new grades for each bundle; with --report-dir, also writes each bundle's executive report rebuilt
with the new grading. Reads pages.json, summary.json and bot-access.json from the bundle; the bundle is not changed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile

from readiness import GRADES, answer_summary, regrade
from report import build as build_report


def rescore(path: str) -> tuple[dict, list[dict], dict, dict | None, dict | None]:
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        pages = json.loads(z.read("pages.json"))
        summary = json.loads(z.read("summary.json"))
        manifest = json.loads(z.read("manifest.json")) if "manifest.json" in names else {}
        access = json.loads(z.read("bot-access.json")) if "bot-access.json" in names else None
        answers = json.loads(z.read("answers.json")).get("summary") if "answers.json" in names else None
    old = dict(summary.get("grades", {}))
    prio = {r["url"] for r in (summary.get("priority_pages") or {}).get("rows", [])}
    for p in pages:
        if p["url"] in prio and not p["detail"].get("key_page"):
            p["detail"]["priority"] = True
        regrade(p, bool(p["detail"].get("key_page") or p["detail"].get("priority")))
    summary["grades"] = {g: sum(1 for p in pages if p["grade"] == g) for g in GRADES}
    summary["answer"] = answer_summary(pages)
    info = {"file": os.path.basename(path), "version": manifest.get("version", "?"), "created": manifest.get("created", "?"),
            "pages": summary.get("pages"), "old_grades": old, "new_grades": summary["grades"], "answer": summary["answer"]}
    return info, pages, summary, access, answers


def main() -> int:
    ap = argparse.ArgumentParser(description="Rescore results bundles with the current grading.")
    ap.add_argument("bundles", nargs="+")
    ap.add_argument("--report-dir", help="write a rebuilt executive report for each bundle into this folder")
    a = ap.parse_args()
    if a.report_dir:
        os.makedirs(a.report_dir, exist_ok=True)
    for path in a.bundles:
        try:
            info, pages, summary, access, answers = rescore(path)
        except (OSError, KeyError, ValueError, zipfile.BadZipFile) as ex:
            print(f"{path}: could not read it ({type(ex).__name__}: {ex})", file=sys.stderr)
            continue
        ans = info["answer"]
        print(f"\n{info['file']}  (created {info['created']}, version {info['version']}, {info['pages']} pages)")
        print("  before: " + ", ".join(f"{k} {v}" for k, v in info["old_grades"].items()))
        print("  after:  " + ", ".join(f"{k} {v}" for k, v in info["new_grades"].items()))
        print(f"  key student pages citable: {ans['citable']} of {ans['key_pages']} (answer quality {ans['citable_at']}+), "
              f"average {ans['average']}; pages passing Access: {ans['access_pass']} of {ans['pages']}")
        if info["version"] != "?" and info["version"] < "2026.11.04.24":
            print("  note: this run predates the outdated-wording check, so 'accurate and current' is over-credited; compare with care")
        if a.report_dir:
            out = os.path.join(a.report_dir, os.path.splitext(info["file"])[0] + "-rescored.html")
            with open(out, "w", encoding="utf-8") as f:
                f.write(build_report(summary, pages, [], access, answers))
            print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
