#!/usr/bin/env python3
"""Page check: scan ONE web page for everything the site crawl looks for, and say what was found.

    python3 pagescan.py https://www.methodist.edu
    python3 pagescan.py www.methodist.edu/academics/medicine/admissions/faq/ --json

Uses the same checks as the Site Readiness crawl (readiness.check_page), plus robots.txt for every AI bot,
EAB's five priority-page elements, approved proof points and numbers, banned and outdated wording, and the
homepage organization schema. Standard library only. Reads one page (and the site's robots.txt); no crawl.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from urllib.parse import urlsplit

from ai_bot_check import run as bot_access
from readiness import CHECKS, MESSAGES, PP_ELEMENTS, OUTDATED, Crawl, org_report, pp_elements


def _label(items: list[dict], key: str = "id") -> dict:
    return {x[key]: x for x in items}


def scan(url: str) -> dict:
    """Scan one page. Returns a dict; on failure, "error" says why."""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    c = Crawl(url, max_pages=1, wordpress=False)
    page = c._visit(c.start)
    out = {"url": c.start, "checked": dt.datetime.now().isoformat(timespec="seconds")}
    if page is None:
        out["error"] = "The page could not be checked: " + (", ".join(c.skipped) or "no response") + "."
        return out
    page.pop("_links", None)
    c._absorb(page)  # same step the crawl uses: prepares the homepage's organization data
    d = page["detail"]
    out.update({"final_url": page["url"], "redirected": page["url"] != c.start, "status": page["status"],
                "score": page["score"], "grade": page["grade"]})
    if page["status"] != 200:
        out["error"] = f"The page returned HTTP {page['status']}, so only that was checked."
        return out

    # 1. every page check, in plain words
    out["checks"] = [{"id": i, "label": lbl, "rule": rule, "critical": crit,
                      "result": {True: "pass", False: "fail"}.get(page["checks"].get(i), "not applicable")}
                     for i, lbl, rule, crit in CHECKS]

    # 2. the basics a person would look at
    out["basics"] = {"title": d.get("title", ""), "description": d.get("desc", ""), "words": d.get("words"),
                     "h1": d.get("h1"), "h2": d.get("h2_count"), "question_headings": d.get("question_headings"),
                     "reading_grade": d.get("reading_grade"), "response_ms": d.get("ms"),
                     "canonical": d.get("canonical_url", ""), "noindex_or_noai": d.get("directives", []),
                     "schema_types": d.get("schema_types", []), "invalid_structured_data_blocks": d.get("invalid_jsonld_blocks", 0),
                     "faq_schema": bool(d.get("faq_schema")), "past_terms": d.get("past_terms", []),
                     "former_names": d.get("former_names_found", [])}

    # 3. AI bots: robots.txt for this exact page
    try:
        acc = bot_access(c.start, probe=False, scan=0)
        bots = acc.get("bots", [])
        out["bots"] = {
            "search_blocked": [b["bot"] for b in bots if b["purpose"] in ("search", "user") and b["policy"] != "deny" and b["robots_txt"] == "blocked"],
            "search_allowed": [b["bot"] for b in bots if b["purpose"] in ("search", "user") and b["policy"] != "deny" and b["robots_txt"] != "blocked"],
            "training_blocked": [b["bot"] for b in bots if b["purpose"] == "training" and b["policy"] != "deny" and b["robots_txt"] == "blocked"],
            "deny_list_not_blocked": [b["bot"] for b in bots if b["policy"] == "deny" and b["robots_txt"] != "blocked"],
        }
    except Exception as ex:  # robots.txt unreachable: report, carry on
        out["bots"] = {"error": f"{type(ex).__name__}: {ex}"}

    # 4. EAB priority-page standard
    need = MESSAGES.get("connections_required", 3)
    el = pp_elements(page)
    pp = d.get("pp", {})
    out["eab"] = {"elements": [{"id": i, "label": lbl, "rule": rule.format(n=need), "pass": bool(el.get(i))} for i, lbl, rule in PP_ELEMENTS],
                  "score": sum(1 for v in el.values() if v), "connections_found": pp.get("connections", []),
                  "first_paragraph_words": pp.get("first_paragraph_words")}

    # 5. messages: proof points, numbers, banned and outdated wording
    msg = d.get("msg", {})
    proof = _label(MESSAGES.get("proof_points", []))
    claims = _label(MESSAGES.get("numeric_claims", []))
    outdated = {x["id"]: x for x, _ in OUTDATED}
    out["messages"] = {
        "proof_points": [proof[i]["label"] for i in msg.get("proof", []) if i in proof],
        "proof_points_missing": [x["label"] for k, x in proof.items() if k not in msg.get("proof", [])],
        "numbers": [{"label": claims[k]["label"], "approved": claims[k]["approved"],
                     "found": sorted({v for v, _ in vals}), "snippet": vals[0][1] if vals else "",
                     "matches": all(v == claims[k]["approved"] for v, _ in vals)}
                    for k, vals in msg.get("claims", {}).items() if k in claims and vals],
        "banned": msg.get("banned", []),
        "outdated": [{"phrase": outdated[k]["phrase"], "use_instead": outdated[k].get("use_instead", ""), "snippet": sn}
                     for k, sn in msg.get("outdated", []) if k in outdated],
    }

    # 6. homepage only: organization schema
    if c.home and urlsplit(page["url"]).path in ("", "/"):
        org = org_report(c.home, c.cfg, c.origin)
        out["organization"] = {"passed": org.get("passed"), "total": org.get("total"),
                               "rows": [{"label": r["label"], "pass": r["pass"], "found": r["found"]} for r in org.get("rows", [])]}

    out["findings"] = findings(out)
    return out


def findings(s: dict) -> list[dict]:
    """Plain-language list, most important first: level = problem | check | good."""
    f = []
    crit = [x for x in s.get("checks", []) if x["critical"] and x["result"] == "fail"]
    for x in crit:
        f.append({"level": "problem", "text": f"Critical: {x['label']}. {x['rule']}"})
    b = s.get("bots", {})
    if b.get("search_blocked"):
        f.append({"level": "problem", "text": "robots.txt blocks AI search bots from this page: " + ", ".join(b["search_blocked"]) + "."})
    if b.get("deny_list_not_blocked"):
        f.append({"level": "check", "text": "Deny-list bots not blocked in robots.txt: " + ", ".join(b["deny_list_not_blocked"]) + "."})
    bs = s.get("basics", {})
    if bs.get("invalid_structured_data_blocks"):
        f.append({"level": "problem", "text": f"{bs['invalid_structured_data_blocks']} structured data block(s) have errors, so search engines and AI ignore them."})
    for o in s.get("messages", {}).get("outdated", []):
        f.append({"level": "problem", "text": f"Outdated wording: {o['phrase']}. Use instead: {o['use_instead']}. (“…{o['snippet'][:120]}…”)"})
    for n in s.get("messages", {}).get("numbers", []):
        if not n["matches"]:
            f.append({"level": "problem", "text": f"{n['label']}: page says {', '.join(map(str, n['found']))}; approved figure is {n['approved']}."})
    for p in s.get("messages", {}).get("banned", []):
        f.append({"level": "check", "text": f"Off-brand phrase: “{p}”."})
    for x in s.get("checks", []):
        if x["id"] == "schema_valid" and bs.get("invalid_structured_data_blocks"):
            continue  # already reported above in plain words
        if not x["critical"] and x["result"] == "fail":
            f.append({"level": "check", "text": f"{x['label']}: {x['rule']}"})
    eab = s.get("eab", {})
    miss = [e["label"] for e in eab.get("elements", []) if not e["pass"]]
    if miss:
        f.append({"level": "check", "text": f"EAB priority-page standard: {eab.get('score', 0)} of 5. Missing: {', '.join(miss)}."})
    org = s.get("organization")
    if org and org.get("total") and org.get("passed") != org.get("total"):
        f.append({"level": "problem", "text": f"Homepage organization schema: {org['passed']} of {org['total']} checks pass."})
    if bs.get("past_terms"):
        f.append({"level": "check", "text": "Names past terms: " + ", ".join(bs["past_terms"]) + "."})
    good = [x["label"] for x in s.get("checks", []) if x["result"] == "pass"]
    if good:
        f.append({"level": "good", "text": f"{len(good)} checks pass, including: " + ", ".join(good[:8]) + "."})
    pps = s.get("messages", {}).get("proof_points", [])
    if pps:
        f.append({"level": "good", "text": "Approved proof points on this page: " + "; ".join(pps) + "."})
    order = {"problem": 0, "check": 1, "good": 2}
    return sorted(f, key=lambda x: order[x["level"]])  # stable: problems first, in the order found


def as_text(s: dict) -> str:
    lines = [f"Page check: {s['url']}", f"Checked {s['checked']}"]
    if s.get("redirected"):
        lines.append(f"Redirects to {s['final_url']}")
    if s.get("error"):
        return "\n".join(lines + ["", s["error"]])
    lines.append(f"Score {s['score']} of 100 · {s['grade']}")
    b = s["basics"]
    lines += ["", f"Title: {b['title']}", f"Description: {b['description'] or '(none)'}",
              f"Words: {b['words']} · H1: {b['h1']} · H2: {b['h2']} · question headings: {b['question_headings']} · reading grade: {b['reading_grade']}",
              f"Structured data: {', '.join(b['schema_types']) or 'none valid'}" + (f" · {b['invalid_structured_data_blocks']} block(s) with errors" if b['invalid_structured_data_blocks'] else ""),
              f"noindex/noai: {', '.join(b['noindex_or_noai']) or 'none'}", ""]
    mark = {"problem": "PROBLEM", "check": "CHECK  ", "good": "OK     "}
    lines += [f"{mark[x['level']]} {x['text']}" for x in s["findings"]]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan one web page for AI readiness and say what was found.")
    ap.add_argument("url")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args()
    s = scan(a.url)
    print(json.dumps(s, indent=2, ensure_ascii=False) if a.json else as_text(s))
    return 1 if s.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
