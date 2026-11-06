#!/usr/bin/env python3
"""Findability check: start on one page, follow links outward, and report how many clicks away each key fact is.

    python3 findability.py https://www.methodist.edu/academics/medicine/
    python3 findability.py www.methodist.edu/academics/medicine/ --report findability.html --json

Topics live in messages.json under "findability" (editable). For each topic it reports the closest page that
states the fact in its own text (menus and footers don't count), the clicks from the start page, the path, and
whether the path uses links in page text or menus only. Pages inside the start's section are followed; pages
outside it are read but not followed. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlsplit

from ai_bot_check import fetch, robots_verdict
from readiness import APP_HOST, CRAWLER_UA, LOGIN_PATH, MESSAGES, SKIP_EXT, Crawl, PageParser, norm, _header

CFG = MESSAGES.get("findability", {})
STATUSES = ("OK", "Buried", "PDF only", "No figure", "Not found")
MEANING = {
    "OK": "Stated in page text, on the start page or one click away through a link in page text.",
    "Buried": "Stated in page text, but 2 or more clicks away or reached only through menus.",
    "PDF only": "Not stated on any page reached; a PDF about it is linked (PDF contents not read).",
    "No figure": "A page about it was reached, but no page states the fact.",
    "Not found": "Nothing about it within the click limit.",
}


def pick_set(start: str, set_id: str | None) -> tuple[str, dict]:
    sets = CFG.get("sets", {})
    if not sets:
        raise ValueError("messages.json has no findability topics.")
    if set_id:
        if set_id not in sets:
            raise ValueError(f"Unknown topic set '{set_id}'. Choose one of: {', '.join(sets)}.")
        return set_id, sets[set_id]
    path = urlsplit(start).path or "/"
    for k, v in sets.items():
        if v.get("section") and path.startswith(v["section"]):
            return k, v
    k = next(iter(sets))
    return k, sets[k]


def _sentence(text: str, m: re.Match) -> str:
    dot = text.rfind(". ", 0, m.start())
    a = max(dot + 2 if dot != -1 else 0, m.start() - 160, 0)
    b = text.find(". ", m.end())
    b = min(b + 1 if b != -1 else len(text), m.end() + 160)
    return text[a:b].strip()


class Find:
    """Breadth-first walk from one page. Thread-safe progress for the web UI."""

    def __init__(self, start: str, set_id: str | None = None, max_clicks: int | None = None, max_pages: int | None = None,
                 delay: float = 0.3, workers: int = 4):
        start = start.strip()
        if "://" not in start:
            start = "https://" + start
        self.start = norm(start)
        self.set_id, self.tset = pick_set(self.start, set_id)
        self.max_clicks = int(max_clicks or CFG.get("max_clicks", 3))
        self.max_pages = int(max_pages or CFG.get("max_pages", 300))
        sp = urlsplit(self.start)
        sec = self.tset.get("section") or ""
        self.section = sec if sec and (sp.path or "/").startswith(sec) else (sp.path.rsplit("/", 1)[0] + "/" if sp.path else "/")
        self.host = sp.netloc
        self.delay, self.workers = delay, workers
        self._crawl = Crawl(self.start, max_pages=1, wordpress=False)  # robots.txt and scope rules
        self.nodes: dict[str, dict] = {}   # url -> {clicks, menu, path, title, text, status}
        self.pdfs: dict[str, dict] = {}    # pdf url -> {text, clicks, menu, path}
        self.skipped: dict[str, int] = {}
        self.state, self.progress, self.error = "pending", "", ""
        self.result: dict | None = None
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _skip(self, why: str):
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def _get(self, url: str) -> dict:
        sp = urlsplit(url)
        if url != self.start and (APP_HOST.search(sp.netloc) or LOGIN_PATH.search(sp.path)):
            return {"skip": "app or login page"}
        groups = self._crawl.robots(f"{sp.scheme}://{sp.netloc}")
        if robots_verdict(groups, "AIReadinessChecker", (sp.path or "/") + (f"?{sp.query}" if sp.query else ""))[0] == "blocked":
            return {"skip": "blocked by robots.txt"}
        for attempt in range(3):
            r = fetch(url, CRAWLER_UA, max_bytes=3_000_000)
            time.sleep(self.delay)
            if r["status"] not in (429, 502, 503, 504) and r["status"] is not None:
                break
            time.sleep(2 * 2 ** attempt)
        if r["status"] != 200:
            return {"status": r["status"], "skip": f"HTTP {r['status'] or 'no response'}"}
        if "html" not in _header(r["headers"], "content-type").lower():
            return {"skip": "not HTML"}
        p = PageParser()
        try:
            p.feed(r["body"].decode("utf-8", "replace"))
        except Exception:
            pass
        final = norm(r["final_url"] or url)
        body = set()
        for h in p.body_links:
            body.add(norm(urljoin(final, h.split("#")[0])))
        links = []  # (url, link text, in page text?)
        for h, t in p.anchors:
            if not h or h.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            u = norm(urljoin(final, h.split("#")[0]))
            links.append((u, t, u in body))
        return {"status": 200, "final": final, "title": " ".join(p.title.split()), "links": links,
                "text": " ".join(" ".join(p.body_text).split()), "heads": " | ".join(p.subheads)}

    def _inside(self, u: str) -> bool:
        return (urlsplit(u).path or "/").startswith(self.section)

    def _in_site(self, u: str) -> bool:
        return urlsplit(u).scheme in ("http", "https") and self._crawl.in_scope(u)

    def run(self) -> dict:
        self.state = "running"
        try:
            self._walk()
            self.result = self._report()
            self.state = "stopped" if self._stop.is_set() else "done"
        except Exception as e:  # report, don't crash the app
            self.error, self.state = f"{type(e).__name__}: {e}", "error"
        return self.result or {"url": self.start, "error": self.error}

    def _walk(self):
        self.nodes[self.start] = {"clicks": 0, "menu": 0, "path": []}
        level, fetched = [self.start], 0
        seen_final: set[str] = set()
        for clicks in range(self.max_clicks + 1):
            if not level or self._stop.is_set():
                break
            level = level[: max(0, self.max_pages - fetched)]
            self.progress = f"{clicks} click(s) out: reading {len(level)} page(s); {fetched} read so far"
            with ThreadPoolExecutor(self.workers) as ex:
                got = list(ex.map(lambda u: (u, None if self._stop.is_set() else self._get(u)), level))
            fetched += len(level)
            nxt: dict[str, None] = {}
            for u, g in got:
                n = self.nodes[u]
                if g is None:
                    continue
                if g.get("skip"):
                    n["status"] = g.get("status")
                    self._skip(g["skip"])
                    continue
                if g["final"] in seen_final:
                    n["dup_of"] = g["final"]
                    continue
                seen_final.add(g["final"])
                n.update(status=200, final=g["final"], title=g["title"], text=g["text"], heads=g["heads"])
                inside = self._inside(g["final"])
                expand = clicks < self.max_clicks and inside
                for v, text, in_body in g["links"]:
                    cand = {"clicks": clicks + 1, "menu": n["menu"] + (0 if in_body else 1),
                            "path": n["path"] + [{"text": text or urlsplit(v).path, "via": "text" if in_body else "menu", "url": v}]}
                    if urlsplit(v).path.lower().endswith(".pdf"):
                        if not inside:
                            continue
                        old = self.pdfs.get(v)
                        if clicks + 1 <= self.max_clicks and (not old or (cand["clicks"], cand["menu"]) < (old["clicks"], old["menu"])):
                            self.pdfs[v] = {**cand, "text": text}
                        continue
                    if not expand or not self._in_site(v) or SKIP_EXT.search(urlsplit(v).path):
                        continue
                    old = self.nodes.get(v)
                    if old is None:
                        self.nodes[v] = cand
                        nxt[v] = None
                    elif old["clicks"] == cand["clicks"] and cand["menu"] < old["menu"]:
                        self.nodes[v] = cand  # same distance, more of the route in page text
            level = list(nxt)
        self.progress = f"done: {sum(1 for n in self.nodes.values() if n.get('status') == 200)} page(s) read"

    def _where(self, url: str, n: dict, m: re.Match | None = None) -> dict:
        w = {"url": n.get("final", url), "title": n.get("title", ""), "clicks": n["clicks"],
             "menu_only": n["menu"] > 0, "path": n["path"]}
        if m:
            w["snippet"] = _sentence(n["text"], m)
        return w

    def _report(self) -> dict:
        skip = re.compile(self.tset.get("skip_pages") or r"(?!x)x", re.I)  # people and news pages: not where students look
        read = {u: n for u, n in self.nodes.items() if n.get("status") == 200 and "text" in n and not skip.search(urlsplit(n["final"]).path)}
        ctx = re.compile(self.tset.get("context") or ".", re.I)

        def relevant(n, m) -> bool:
            """Section pages always count; a page outside the section counts only when the topic's subject is named near the fact."""
            if self._inside(n["final"]):
                return True
            return bool(ctx.search(n["text"][max(0, m.start() - 300): m.end() + 300]))
        topics = []
        for t in self.tset.get("topics", []):
            fact, about = re.compile(t["fact"], re.I), re.compile(t["page"], re.I)
            notnear = re.compile(t["not_near"], re.I) if t.get("not_near") else None
            stated = []
            for u, n in read.items():
                m = next((m for m in fact.finditer(n["text"]) if relevant(n, m)
                          and not (notnear and notnear.search(n["text"][max(0, m.start() - 80): m.end() + 80]))), None)
                if m:
                    stated.append((n["clicks"], n["menu"] > 0, u, n, m))
            stated.sort(key=lambda x: (x[0], x[1], x[2]))
            row = {"id": t["id"], "label": t["label"], "terms": {"page": t["page"], "fact": t["fact"]}}
            if stated:
                c, menu, u, n, m = stated[0]
                ok = c == 0 or (c == 1 and not menu)
                row["status"] = "OK" if ok else "Buried"
                row["where"] = self._where(u, n, m)
                row["also_on"] = [self._where(u2, n2) for _, _, u2, n2, _ in stated[1:6]]
                row["stated_on"] = len(stated)
            else:
                pdfs = sorted(((p["clicks"], p["menu"] > 0, u, p) for u, p in self.pdfs.items()
                               if about.search(p.get("text", "") + " " + urlsplit(u).path.rsplit("/", 1)[-1].replace("-", " "))),
                              key=lambda x: (x[0], x[1], x[2]))
                def about_pages(field):
                    return sorted(((n["clicks"], n["menu"] > 0, u, n) for u, n in read.items() if about.search(field(u, n))
                                   and (self._inside(n["final"]) or ctx.search(n.get("title", "")))), key=lambda x: (x[0], x[1], x[2]))
                pages = (about_pages(lambda u, n: n.get("title", "") + " " + urlsplit(n.get("final", u)).path.replace("-", " "))
                         or about_pages(lambda u, n: n.get("heads", "")))  # headings only when no title or address matches
                if pdfs:
                    c, menu, u, p = pdfs[0]
                    row["status"] = "PDF only"
                    row["where"] = {"url": u, "title": p.get("text") or u.rsplit("/", 1)[-1], "clicks": c, "menu_only": menu, "path": p["path"]}
                elif pages:
                    row["status"] = "No figure"
                    row["where"] = self._where(pages[0][2], pages[0][3])
                    row["also_on"] = [self._where(u2, n2) for _, _, u2, n2 in pages[1:4]]
                else:
                    row["status"] = "Not found"
            row["fix"] = self._fix(row)
            topics.append(row)
        start = self.nodes[self.start]
        return {"url": self.start, "start_title": start.get("title", ""), "checked": dt.datetime.now().isoformat(timespec="seconds"),
                "set": self.set_id, "set_label": self.tset.get("label", self.set_id), "section": self.section,
                "max_clicks": self.max_clicks, "pages_read": len(read), "pdfs_seen": len(self.pdfs),
                "page_cap_hit": len(self.nodes) > self.max_pages, "skipped": self.skipped,
                "stopped": self._stop.is_set(), "error": None if start.get("status") == 200 else f"The start page could not be read ({start.get('status') or 'no response'}).",
                "counts": {s: sum(1 for r in topics if r["status"] == s) for s in STATUSES},
                "topics": topics, "meaning": MEANING}

    def _fix(self, r: dict) -> str:
        w = r.get("where") or {}
        page = w.get("title") or w.get("url", "")
        if r["status"] == "OK":
            return "None."
        if r["status"] == "Buried":
            why = f"{w['clicks']} clicks away" if w["clicks"] >= 2 else "reached only through a menu"
            return f"It is {why}. Add a link in the start page's text to \"{page}\", using words a student would search for, or state it on the start page."
        if r["status"] == "PDF only":
            return f"Put the facts from \"{page}\" in page text and link that page from the start page's text; keep the PDF as a download."
        if r["status"] == "No figure":
            return f"State the fact on \"{page}\" in a sentence that answers the question directly."
        return f"Add a page or section that answers this, inside {self.section}, and link it from the start page's text."


def report_html(s: dict) -> str:
    """Printable findability report."""
    from html import escape as e
    css = """body{margin:0;background:#fff;color:#1b1b1f;font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1000px;margin:0 auto;padding:32px 24px}h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:26px 0 8px;border-bottom:2px solid #1b1b1f;padding-bottom:4px}
.meta,.note,.muted{color:#5f6068;font-size:12px}.url{overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #dcdce2;vertical-align:top}th{font-size:11px;text-transform:uppercase;color:#5f6068}
.tiles{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:16px 0}.tile{border:1px solid #dcdce2;border-radius:8px;padding:10px 12px}
.tile b{display:block;font-size:24px}.tile span{color:#5f6068;font-size:12px}.pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:600;white-space:nowrap}
.ok{color:#1a7f37;background:#e7f6ec}.bad{color:#b42318;background:#fdecea}.warn{color:#9a6700;background:#fff4d6}.na{color:#5f6068;background:#eef0f2}
.bar{position:sticky;top:0;background:#fff;border-bottom:1px solid #dcdce2;padding:10px 24px;text-align:right}
.bar button{padding:8px 16px;border:0;border-radius:6px;background:#2f5bd3;color:#fff;font-weight:600;cursor:pointer}q{font-style:italic}
code{font-size:11px;overflow-wrap:anywhere}@media (max-width:640px){.tiles{grid-template-columns:repeat(2,1fr)}}
@media print{.bar{display:none}main{padding:0}h2{break-after:avoid}tr{break-inside:avoid}}"""
    head = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>Findability: {e(s.get('start_title') or s['url'])}</title><style>{css}</style></head><body>"
            "<div class='bar'><button onclick='window.print()'>Print / Save as PDF</button></div><main>")
    top = (f"<h1>Findability: {e(s.get('set_label', ''))}</h1><div class='meta url'>Start page: {e(s['url'])}"
           f"{' (' + e(s['start_title']) + ')' if s.get('start_title') else ''} · checked {e(s.get('checked', '').replace('T', ' '))}</div>")
    if s.get("error"):
        return head + top + f"<p class='bad' style='padding:10px;border-radius:6px'>{e(s['error'])}</p></main></body></html>"
    cls = {"OK": "ok", "Buried": "warn", "PDF only": "warn", "No figure": "bad", "Not found": "bad"}
    c = s["counts"]
    n = len(s["topics"])
    lead = (f"<p><b>{c['OK']} of {n} topics are easy to find</b>: stated in page text on the start page or one click away through a link in page text. "
            f"{n - c['OK']} need work. Read {s['pages_read']} pages up to {s['max_clicks']} clicks out"
            f"{'; stopped early' if s.get('stopped') else ''}{'; page limit reached' if s.get('page_cap_hit') else ''}.</p>")
    tiles = "<div class='tiles'>" + "".join(f"<div class='tile'><b>{c[k]}</b><span><span class='pill {cls[k]}'>{k}</span></span></div>" for k in STATUSES) + "</div>"

    def path(w):
        steps = ["Start page"] + [f"{x['text'][:60]}{' (menu)' if x['via'] == 'menu' else ''}" for x in w.get("path", [])]
        return " → ".join(e(x) for x in steps)
    rows = ""
    for r in s["topics"]:
        w = r.get("where")
        where = "—"
        if w:
            where = (f"<a class='url' href='{e(w['url'])}'>{e(w.get('title') or w['url'])}</a><div class='muted'>{w['clicks']} click(s): {path(w)}</div>"
                     + (f"<div class='muted'><q>{e(w['snippet'])}</q></div>" if w.get("snippet") else ""))
        rows += (f"<tr><td><b>{e(r['label'])}</b></td><td><span class='pill {cls[r['status']]}'>{r['status']}</span></td>"
                 f"<td>{where}</td><td>{e(r['fix'])}</td></tr>")
    table = ("<h2>Topics</h2><table><thead><tr><th style='width:18%'>Topic</th><th>Status</th><th style='width:44%'>Closest page that answers it</th>"
             f"<th>Fix</th></tr></thead><tbody>{rows}</tbody></table>")
    also = ""
    for r in s["topics"]:
        if r.get("also_on"):
            also += f"<tr><td>{e(r['label'])}</td><td>" + "<br>".join(f"<a class='url' href='{e(x['url'])}'>{e(x.get('title') or x['url'])}</a> <span class='muted'>({x['clicks']} click(s){', menu only' if x['menu_only'] else ''})</span>" for x in r["also_on"]) + "</td></tr>"
    if also:
        also = "<h2>Other pages that state it</h2><table><tbody>" + also + "</tbody></table>"
    meaning = "<h2>What the statuses mean</h2><table><tbody>" + "".join(f"<tr><td><span class='pill {cls[k]}'>{k}</span></td><td>{e(v)}</td></tr>" for k, v in s["meaning"].items()) + "</tbody></table>"
    method = (f"<h2>Method and limits</h2><ul><li>Starts at the page above and follows links up to {s['max_clicks']} clicks. Pages under <code>{e(s['section'])}</code> are followed; pages outside it are read but not followed.</li>"
              "<li>A fact counts only when it is in the page's own text. Menus, headers, footers and sidebars don't count. A menu link still counts as a click, but the path is marked “menu”.</li>"
              "<li>Matching uses word patterns, so unusual wording can be missed. The patterns searched are listed below and can be edited in messages.json (findability).</li>"
              "<li>PDF contents are not read. People and news pages are not counted.</li></ul>"
              "<table><thead><tr><th>Topic</th><th>Page about it</th><th>Fact stated</th></tr></thead><tbody>"
              + "".join(f"<tr><td>{e(r['label'])}</td><td><code>{e(r['terms']['page'])}</code></td><td><code>{e(r['terms']['fact'])}</code></td></tr>" for r in s["topics"])
              + "</tbody></table>")
    return head + top + lead + tiles + table + also + meaning + method + "</main></body></html>"


def main() -> int:
    ap = argparse.ArgumentParser(description="How many clicks from a page to the facts a student looks for.")
    ap.add_argument("url", nargs="?", help="start page (default: the topic set's start page)")
    ap.add_argument("--set", help="topic set in messages.json (default: matched from the address)")
    ap.add_argument("--clicks", type=int, help="click limit (default 3)")
    ap.add_argument("--max-pages", type=int)
    ap.add_argument("--report", help="write a printable HTML report to this file")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args()
    url = a.url or CFG.get("sets", {}).get(a.set or "medicine", {}).get("start")
    if not url:
        ap.error("give a start page")
    f = Find(url, a.set, a.clicks, a.max_pages)
    t = threading.Thread(target=f.run, daemon=True)
    t.start()
    while t.is_alive():
        t.join(5)
        print(f"  {f.progress}", file=sys.stderr)
    s = f.result or {"url": f.start, "error": f.error}
    if a.json:
        print(json.dumps(s, indent=2))
    elif s.get("error"):
        print(s["error"])
    else:
        print(f"\nFindability: {s['set_label']} from {s['url']} ({s['pages_read']} pages read, up to {s['max_clicks']} clicks)")
        for r in s["topics"]:
            w = r.get("where")
            at = f"{w['clicks']} click(s){', menu only' if w['menu_only'] else ''}: {w['url']}" if w else ""
            print(f"  {r['status']:<10} {r['label']:<55} {at}")
    if a.report:
        with open(a.report, "w", encoding="utf-8") as fh:
            fh.write(report_html(s))
        print(f"wrote {a.report}", file=sys.stderr)
    return 0 if not s.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
