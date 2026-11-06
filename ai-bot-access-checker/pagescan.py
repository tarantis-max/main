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
    """Plain-language list, most important first: level = problem | check | good, each with a fix and an owner."""
    from report import ISSUES  # the executive report's own wording, so both reports agree
    f = []

    def add(level, text, fix="", owner=""):
        f.append({"level": level, "text": text, "fix": fix, "owner": owner})

    bs = s.get("basics", {})
    for x in s.get("checks", []):
        if x["critical"] and x["result"] == "fail":
            why, fix, owner = ISSUES.get(x["id"], ("", "", ""))
            add("problem", f"Critical: {x['label']}. {why or x['rule']}", fix, owner)
    b = s.get("bots", {})
    if b.get("search_blocked"):
        add("problem", "robots.txt blocks AI search bots from this page: " + ", ".join(b["search_blocked"]) + ".",
            "Remove the robots.txt rules that block these bots for this page.", "Web team")
    if bs.get("invalid_structured_data_blocks"):
        add("problem", f"{bs['invalid_structured_data_blocks']} structured data block(s) have errors, so search engines and AI ignore them.",
            "Replace the broken JSON-LD block in the shared template with the corrected snippet, then check the page at validator.schema.org.", "Web team")
    org = s.get("organization")
    if org and org.get("total") and org.get("passed") != org.get("total"):
        add("problem", f"Homepage organization schema: {org['passed']} of {org['total']} checks pass.",
            "Fixing the structured data block fixes most of these; the table under Organization schema shows each value.", "Web team")
    for o in s.get("messages", {}).get("outdated", []):
        tmpl = any(w in o["phrase"].lower() for w in ("twitter", "copyright"))  # these live in the shared footer
        add("problem", f"Outdated wording: {o['phrase']} (“…{o['snippet'][:120]}…”).",
            f"Change it to: {o['use_instead']}." + (" It is in the site footer, so one template change fixes every page." if tmpl else ""),
            "Web team" if tmpl else "Content owner")
    for n in s.get("messages", {}).get("numbers", []):
        if not n["matches"]:
            add("problem", f"{n['label']}: the page says {', '.join(map(str, n['found']))}; the approved figure is {n['approved']}.",
                f"Change it to {n['approved']}, or update the approved figure in messages.json if {n['approved']} is wrong.", "Marketing")
    if b.get("deny_list_not_blocked"):
        add("check", "Deny-list bots not blocked in robots.txt: " + ", ".join(b["deny_list_not_blocked"]) + ".",
            "Add the deny-list group from the executive report (Appendix D) to robots.txt, and block the same bots at the CDN or firewall.", "Web team")
    for p in s.get("messages", {}).get("banned", []):
        add("check", f"Off-brand phrase: “{p}”.", "Rewrite using the approved brand language.", "Marketing")
    for x in s.get("checks", []):
        if x["id"] == "schema_valid" and bs.get("invalid_structured_data_blocks"):
            continue  # already reported above in plain words
        if not x["critical"] and x["result"] == "fail":
            why, fix, owner = ISSUES.get(x["id"], ("", "", ""))
            add("check", f"{x['label']}: {why or x['rule']}", fix or x["rule"], owner)
    eab = s.get("eab", {})
    miss = [e for e in eab.get("elements", []) if not e["pass"]]
    if miss:
        add("check", f"EAB priority-page standard: {eab.get('score', 0)} of 5. Missing: {', '.join(e['label'] for e in miss)}.",
            " ".join(f"{e['label']}: {e['rule']}" for e in miss), "Content owner")
    if bs.get("past_terms"):
        add("check", "Names past terms: " + ", ".join(bs["past_terms"]) + ".", "Update the dates, or label the content as historical.", "Content owner")
    good = [x["label"] for x in s.get("checks", []) if x["result"] == "pass"]
    if good:
        add("good", f"{len(good)} of {len(s.get('checks', []))} checks pass, including: " + ", ".join(good[:8]) + ".")
    pps = s.get("messages", {}).get("proof_points", [])
    if pps:
        add("good", "Approved proof points on this page: " + "; ".join(pps) + ".")
    order = {"problem": 0, "check": 1, "good": 2}
    return sorted(f, key=lambda x: order[x["level"]])  # stable: problems first, in the order found


def report_html(s: dict) -> str:
    """One-page printable report of a page check."""
    from html import escape as e
    css = """body{margin:0;background:#fff;color:#1b1b1f;font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:960px;margin:0 auto;padding:32px 24px}h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:26px 0 8px;border-bottom:2px solid #1b1b1f;padding-bottom:4px}
.meta,.note{color:#5f6068;font-size:12px}.url{overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #dcdce2;vertical-align:top}th{font-size:11px;text-transform:uppercase;color:#5f6068}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}.tile{border:1px solid #dcdce2;border-radius:8px;padding:10px 12px}
.tile b{display:block;font-size:24px}.tile span{color:#5f6068;font-size:12px}.pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:600}
.ok{color:#1a7f37;background:#e7f6ec}.bad{color:#b42318;background:#fdecea}.warn{color:#9a6700;background:#fff4d6}.na{color:#5f6068;background:#eef0f2}
.bar{position:sticky;top:0;background:#fff;border-bottom:1px solid #dcdce2;padding:10px 24px;text-align:right}
.bar button{padding:8px 16px;border:0;border-radius:6px;background:#2f5bd3;color:#fff;font-weight:600;cursor:pointer}
@media (max-width:640px){.tiles{grid-template-columns:repeat(2,1fr)}}@media print{.bar{display:none}main{padding:0}h2{break-after:avoid}tr{break-inside:avoid}}"""
    head = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>Page Check: {e(s.get('final_url') or s['url'])}</title><style>{css}</style></head><body>"
            "<div class='bar'><button onclick='window.print()'>Print / Save as PDF</button></div><main>")
    top = (f"<h1>Page Check</h1><div class='meta url'>{e(s.get('final_url') or s['url'])}"
           + (f" (redirected from {e(s['url'])})" if s.get("redirected") else "") + f" · checked {e(s['checked'].replace('T', ' '))}</div>")
    if s.get("error"):
        return head + top + f"<p class='bad' style='padding:10px;border-radius:6px'>{e(s['error'])}</p></main></body></html>"
    f = s["findings"]
    probs, checks, goods = ([x for x in f if x["level"] == lv] for lv in ("problem", "check", "good"))
    b, bots = s["basics"], s.get("bots", {})
    lead = (f"<p><b>{len(probs)} problem(s) to fix and {len(checks)} item(s) to check.</b> "
            f"The page scores {s['score']} of 100 ({e(s['grade'])}) on the readiness checks and meets {s['eab']['score']} of EAB’s 5 priority-page elements.</p>")
    tiles = ("<div class='tiles'>"
             f"<div class='tile'><b>{s['score']}</b><span>readiness score of 100 · {e(s['grade'])}</span></div>"
             f"<div class='tile'><b>{len(probs)}</b><span>problems to fix</span></div>"
             f"<div class='tile'><b>{s['eab']['score']} of 5</b><span>EAB priority-page elements</span></div>"
             f"<div class='tile'><b>{b.get('reading_grade') if b.get('reading_grade') is not None else '-'}</b><span>reading grade (12 or below is the goal)</span></div></div>")

    def rows(items):
        return "".join(f"<tr><td>{i}</td><td>{e(x['text'])}</td><td>{e(x['fix'])}</td><td class='nw'>{e(x['owner'])}</td></tr>" for i, x in enumerate(items, 1))
    t_head = "<table><thead><tr><th>#</th><th style='width:38%'>What we found</th><th>How to fix it</th><th>Owner</th></tr></thead><tbody>"
    body = ""
    if probs:
        body += "<h2>Problems to fix</h2>" + t_head + rows(probs) + "</tbody></table>"
    if checks:
        body += "<h2>Worth checking</h2>" + t_head + rows(checks) + "</tbody></table>"
    if goods:
        body += "<h2>What’s working</h2><ul>" + "".join(f"<li>{e(x['text'])}</li>" for x in goods) + "</ul>"
    pill = lambda v: "<span class='pill ok'>pass</span>" if v else "<span class='pill bad'>fail</span>"
    body += ("<h2>Page basics</h2><table><tbody>"
             f"<tr><td>Title</td><td>{e(b['title']) or '-'}</td></tr>"
             f"<tr><td>Description</td><td>{e(b['description']) or 'none'}</td></tr>"
             f"<tr><td>Headings</td><td>{b['h1']} H1 · {b['h2']} H2 · {b['question_headings']} phrased as questions</td></tr>"
             f"<tr><td>Words</td><td>{b['words']}</td></tr>"
             f"<tr><td>Structured data</td><td>{e(', '.join(b['schema_types'])) or 'none valid'}"
             + (f" · {b['invalid_structured_data_blocks']} block(s) with errors" if b['invalid_structured_data_blocks'] else "") + "</td></tr>"
             f"<tr><td>noindex / noai</td><td>{e(', '.join(b['noindex_or_noai'])) or 'none'}</td></tr>"
             f"<tr><td>AI search bots</td><td>{len(bots.get('search_allowed', []))} allowed"
             + (f"; blocked: {e(', '.join(bots['search_blocked']))}" if bots.get("search_blocked") else "") + "</td></tr>"
             f"<tr><td>Response time</td><td>{b['response_ms']} ms</td></tr></tbody></table>")
    body += ("<h2>EAB priority-page standard: " + str(s["eab"]["score"]) + " of 5</h2><table><tbody>"
             + "".join(f"<tr><td class='nw'><b>{e(x['label'])}</b></td><td>{pill(x['pass'])}</td><td class='note'>{e(x['rule'])}</td></tr>" for x in s["eab"]["elements"])
             + f"</tbody></table><p class='note'>Connections found in the page body: {e(', '.join(s['eab']['connections_found'])) or 'none'}.</p>")
    m = s["messages"]
    body += (f"<h2>Messages</h2><p><b>Approved proof points on this page:</b> {e('; '.join(m['proof_points'])) or 'none'}</p>"
             f"<p class='note'>Not on this page: {e('; '.join(m['proof_points_missing'])) or 'none'}</p>")
    if m["numbers"]:
        body += ("<table><thead><tr><th>Number</th><th>Approved</th><th>On this page</th><th>Result</th></tr></thead><tbody>"
                 + "".join(f"<tr><td>{e(n['label'])}</td><td>{n['approved']}</td><td>{e(', '.join(map(str, n['found'])))}</td><td>{pill(n['matches'])}</td></tr>" for n in m["numbers"])
                 + "</tbody></table>")
    if s.get("organization"):
        o = s["organization"]
        body += (f"<h2>Organization schema (homepage): {o['passed']} of {o['total']}</h2><table><tbody>"
                 + "".join(f"<tr><td>{e(r['label'])}</td><td>{pill(r['pass'])}</td><td class='note url'>{e(str(r['found']))}</td></tr>" for r in o["rows"])
                 + "</tbody></table>")
    res = {"pass": "<span class='pill ok'>pass</span>", "fail": "<span class='pill bad'>fail</span>"}
    na_pill = "<span class='pill na'>n/a</span>"
    body += ("<h2>All page checks</h2><table><thead><tr><th>Check</th><th>Result</th><th>Passes when</th></tr></thead><tbody>"
             + "".join(f"<tr><td><b>{e(c['label'])}</b>{' (critical)' if c['critical'] else ''}</td><td>{res.get(c['result'], na_pill)}</td><td class='note'>{e(c['rule'])}</td></tr>" for c in s["checks"])
             + "</tbody></table>"
             "<p class='note'>Method: one page and the site’s robots.txt, read the way the AI Access &amp; Readiness site crawl reads every page. "
             "Approved numbers, proof points and outdated wording come from messages.json; EAB elements from EAB’s priority-page standard.</p>")
    return head + top + lead + tiles + body + "</main></body></html>"


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
    ap.add_argument("--report", metavar="FILE", help="also write a printable HTML report, e.g. page-check.html")
    a = ap.parse_args()
    s = scan(a.url)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as fh:
            fh.write(report_html(s))
        print(f"wrote {a.report}", file=sys.stderr)
    print(json.dumps(s, indent=2, ensure_ascii=False) if a.json else as_text(s))
    return 1 if s.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
