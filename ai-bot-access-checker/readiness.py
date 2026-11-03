#!/usr/bin/env python3
"""AI readiness crawler.

Crawls a site (homepage links + sitemaps, same host) and scores every HTML page
against fixed pass/fail checks for AI search / answer engines.

CLI:  python3 readiness.py https://www.methodist.edu --max 500 --csv out.csv
Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from ai_bot_check import BOTS, Group, collect_sitemap_urls, fetch, parse_robots, parse_sitemaps, robots_verdict

CRAWLER_UA = "Mozilla/5.0 (compatible; AIReadinessChecker/1.0; site self-audit)"

# Bots whose access is scored: AI search + user-triggered fetchers (they put pages in AI answers).
SCORED_BOTS = [b[0] for b in BOTS if b[2] in ("search", "user")]
TRAINING_BOTS = [b[0] for b in BOTS if b[2] == "training"]

SKIP_EXT = re.compile(
    r"\.(pdf|jpe?g|png|gif|webp|svg|ico|bmp|tiff?|mp[34]|m4[av]|mov|avi|wmv|webm|zip|gz|tgz|rar|7z|"
    r"docx?|xlsx?|pptx?|csv|txt|xml|json|rss|atom|ics|css|js|woff2?|ttf|eot|exe|dmg|iso)$", re.I)

# id, label, pass criterion, critical (critical fail => page is "Not ready")
CHECKS = [
    ("http_ok", "HTTP 200", "Page returns HTTP 200 to a normal request.", True),
    ("ai_search_allowed", "AI search bots allowed", "robots.txt allows every AI search and user-fetch bot for this URL.", True),
    ("indexable", "No noindex/noai", "No noindex, none, noai or noimageai in meta robots or X-Robots-Tag.", True),
    ("server_text", "Server-rendered text", "At least 150 words of visible text in the raw HTML (most AI crawlers do not run JavaScript).", True),
    ("title", "Title", "<title> present, 10-70 characters.", False),
    ("meta_desc", "Meta description", "Meta description present, 50-160 characters.", False),
    ("one_h1", "Single H1", "Exactly one <h1>.", False),
    ("headings", "Subheadings", "At least one <h2> (content is structured into sections).", False),
    ("canonical", "Canonical URL", "<link rel=canonical> present.", False),
    ("structured_data", "Structured data", "At least one JSON-LD (schema.org) block.", False),
    ("lang", "Language", "<html lang> attribute set.", False),
    ("open_graph", "Open Graph", "og:title and og:description present.", False),
    ("img_alt", "Image alt text", "At least 90% of <img> tags have non-empty alt text (passes if no images).", False),
    ("freshness", "Freshness signal", "Last-Modified header, article:modified_time, or dateModified/datePublished in JSON-LD.", False),
    ("fast", "Response time", "HTML delivered in under 2 seconds.", False),
]
CHECK_IDS = [c[0] for c in CHECKS]
CRITICAL = {c[0] for c in CHECKS if c[3]}


def grade(score: int, results: dict) -> str:
    if any(results.get(c) is False for c in CRITICAL):
        return "Not ready"
    if score >= 80:
        return "Ready"
    if score >= 50:
        return "Needs work"
    return "Not ready"


# ---------------------------------------------------------------- HTML parsing

class PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.h1 = 0
        self.h2 = 0
        self.imgs = 0
        self.imgs_alt = 0
        self.lang = ""
        self.links: list[str] = []
        self.jsonld: list[str] = []
        self.words = 0
        self._skip = 0
        self._in_title = False
        self._in_jsonld = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "").strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key and "content" in a:
                self.meta[key] = (self.meta.get(key, "") + "," + a["content"]).strip(",") if key == "robots" else a["content"]
        elif tag == "link" and "canonical" in a.get("rel", "").lower().split():
            self.canonical = a.get("href", "")
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "h1":
            self.h1 += 1
        elif tag == "h2":
            self.h2 += 1
        elif tag == "img":
            self.imgs += 1
            if a.get("alt", "").strip():
                self.imgs_alt += 1
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in_jsonld = True
            self._buf = []
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._buf))
            self._in_jsonld = False
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_jsonld:
            self._buf.append(data)
        elif not self._skip:
            self.words += len(data.split())


# ---------------------------------------------------------------- page check

def _header(headers: dict, name: str) -> str:
    return next((v for k, v in headers.items() if k.lower() == name), "")


def check_page(url: str, r: dict, elapsed: float, groups: list[Group]) -> dict:
    p = PageParser()
    try:
        p.feed(r["body"].decode("utf-8", "replace"))
    except Exception:
        pass
    sp = urlsplit(url)
    path = (sp.path or "/") + (f"?{sp.query}" if sp.query else "")

    blocked_search = [b for b in SCORED_BOTS if robots_verdict(groups, b, path)[0] == "blocked"]
    blocked_training = [b for b in TRAINING_BOTS if robots_verdict(groups, b, path)[0] == "blocked"]

    directives = set()
    for d in (_header(r["headers"], "x-robots-tag") + "," + p.meta.get("robots", "")).lower().split(","):
        d = d.split(":")[-1].strip()
        if d:
            directives.add(d)
    bad_directives = sorted(directives & {"noindex", "none", "noai", "noimageai"})

    jsonld = " ".join(p.jsonld)
    title = " ".join(p.title.split())
    desc = p.meta.get("description", "").strip()
    fresh = bool(_header(r["headers"], "last-modified") or p.meta.get("article:modified_time")
                 or re.search(r'"date(Modified|Published)"', jsonld))

    res = {
        "http_ok": r["status"] == 200,
        "ai_search_allowed": not blocked_search,
        "indexable": not bad_directives,
        "server_text": p.words >= 150,
        "title": 10 <= len(title) <= 70,
        "meta_desc": 50 <= len(desc) <= 160,
        "one_h1": p.h1 == 1,
        "headings": p.h2 >= 1,
        "canonical": bool(p.canonical),
        "structured_data": bool(p.jsonld),
        "lang": bool(p.lang),
        "open_graph": bool(p.meta.get("og:title") and p.meta.get("og:description")),
        "img_alt": p.imgs == 0 or p.imgs_alt / p.imgs >= 0.9,
        "freshness": fresh,
        "fast": elapsed < 2.0,
    }
    score = round(100 * sum(res.values()) / len(res))
    return {
        "url": url,
        "status": r["status"] or r["error"],
        "score": score,
        "grade": grade(score, res),
        "checks": res,
        "failed": [c for c in CHECK_IDS if not res[c]],
        "detail": {
            "title": title[:120],
            "words": p.words,
            "h1": p.h1,
            "images": p.imgs,
            "images_with_alt": p.imgs_alt,
            "ms": round(elapsed * 1000),
            "blocked_ai_search_bots": blocked_search,
            "blocked_training_bots": blocked_training,
            "directives": bad_directives,
        },
        "_links": p.links,
    }


# ---------------------------------------------------------------- crawler

def norm(u: str) -> str:
    sp = urlsplit(u)
    path = sp.path or "/"
    return urlunsplit((sp.scheme.lower(), sp.netloc.lower(), path, sp.query, ""))


class Crawl:
    """Breadth-first, same-site crawl. Thread-safe progress for the web UI."""

    def __init__(self, start: str, max_pages: int = 500, subdomains: bool = False,
                 workers: int = 4, delay: float = 0.25, exclude: str = ""):
        if "://" not in start:
            start = "https://" + start
        self.start = norm(start)
        self.host = urlsplit(self.start).netloc
        self.base = self.host[4:] if self.host.startswith("www.") else self.host
        self.max_pages = max_pages
        self.subdomains = subdomains
        self.workers = workers
        self.delay = delay
        self.exclude = re.compile(exclude) if exclude else None
        self.results: list[dict] = []
        self.skipped: dict[str, int] = {}
        self.queued = 0
        self.state = "pending"
        self.error = ""
        self.started = time.time()
        self.finished: float | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._robots: dict[str, list[Group]] = {}

    # -- scope
    def in_scope(self, u: str) -> bool:
        sp = urlsplit(u)
        if sp.scheme not in ("http", "https"):
            return False
        h = sp.netloc.lower()
        if self.subdomains:
            ok = h == self.base or h.endswith("." + self.base)
        else:
            ok = h == self.host
        return ok and not SKIP_EXT.search(sp.path) and not (self.exclude and self.exclude.search(u))

    def robots(self, origin: str) -> list[Group]:
        if origin not in self._robots:
            r = fetch(origin + "/robots.txt", CRAWLER_UA)
            if r["status"] == 200:
                text = r["body"].decode("utf-8", "replace")
                self._robots[origin] = parse_robots(text)
                self._robots[origin + "#sitemaps"] = parse_sitemaps(text)  # type: ignore[assignment]
            else:
                self._robots[origin] = []
                self._robots[origin + "#sitemaps"] = []  # type: ignore[assignment]
        return self._robots[origin]

    def _skip(self, why: str):
        with self._lock:
            self.skipped[why] = self.skipped.get(why, 0) + 1

    def _visit(self, url: str) -> dict | None:
        sp = urlsplit(url)
        origin = f"{sp.scheme}://{sp.netloc}"
        groups = self.robots(origin)
        path = (sp.path or "/") + (f"?{sp.query}" if sp.query else "")
        if robots_verdict(groups, "AIReadinessChecker", path)[0] == "blocked":
            self._skip("blocked for crawler by robots.txt")
            return None
        t0 = time.time()
        r = fetch(url, CRAWLER_UA, max_bytes=3_000_000)
        elapsed = time.time() - t0
        time.sleep(self.delay)
        final = norm(r["final_url"] or url)
        if final != url and not self.in_scope(final):
            self._skip("redirects off-site")
            return None
        ctype = _header(r["headers"], "content-type").lower()
        if r["status"] == 200 and ctype and "html" not in ctype:
            self._skip("not HTML")
            return None
        page = check_page(final, r, elapsed, self.robots(f"{urlsplit(final).scheme}://{urlsplit(final).netloc}"))
        if final != url:
            page["redirected_from"] = url
        return page

    def run(self) -> None:
        self.state = "running"
        try:
            seen: set[str] = {self.start}
            frontier: list[str] = [self.start]
            origin = f"{urlsplit(self.start).scheme}://{self.host}"
            self.robots(origin)
            sm = self._robots.get(origin + "#sitemaps") or [origin + "/sitemap.xml"]
            sm_urls, _ = collect_sitemap_urls(sm, self.max_pages * 2)  # type: ignore[arg-type]
            for u in sm_urls:
                u = norm(u)
                if u not in seen and self.in_scope(u):
                    seen.add(u)
                    frontier.append(u)
            done_urls: set[str] = set()
            with ThreadPoolExecutor(max_workers=self.workers) as ex:
                running = {}
                while (frontier or running) and not self._stop.is_set():
                    while frontier and len(running) < self.workers and len(self.results) + len(running) < self.max_pages:
                        u = frontier.pop(0)
                        running[ex.submit(self._visit, u)] = u
                    self.queued = len(frontier)
                    if not running:
                        break
                    done, _ = wait(running, timeout=1, return_when=FIRST_COMPLETED)
                    for f in done:
                        running.pop(f)
                        page = f.result()
                        if not page or page["url"] in done_urls:
                            continue
                        done_urls.add(page["url"])
                        for href in page.pop("_links"):
                            nu = norm(urljoin(page["url"], href.strip()))
                            if nu not in seen and self.in_scope(nu):
                                seen.add(nu)
                                frontier.append(nu)
                        with self._lock:
                            self.results.append(page)
            self.state = "stopped" if self._stop.is_set() else "done"
        except Exception as e:
            self.state, self.error = "error", f"{type(e).__name__}: {e}"
        finally:
            self.finished = time.time()

    def stop(self):
        self._stop.set()

    # -- reporting
    def summary(self) -> dict:
        with self._lock:
            pages = list(self.results)
        n = len(pages)
        fails = {c: sum(1 for p in pages if not p["checks"][c]) for c in CHECK_IDS}
        grades = {g: sum(1 for p in pages if p["grade"] == g) for g in ("Ready", "Needs work", "Not ready")}
        return {
            "start": self.start,
            "state": self.state,
            "error": self.error,
            "pages": n,
            "queued": self.queued,
            "max_pages": self.max_pages,
            "skipped": dict(self.skipped),
            "elapsed_s": round((self.finished or time.time()) - self.started),
            "avg_score": round(sum(p["score"] for p in pages) / n) if n else 0,
            "grades": grades,
            "check_failures": [{"id": c[0], "label": c[1], "rule": c[2], "critical": c[3],
                                "failed": fails[c[0]], "pct": round(100 * fails[c[0]] / n) if n else 0} for c in CHECKS],
        }

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["url", "status", "score", "grade", "failed_checks", "title", "words", "ms",
                    "blocked_ai_search_bots", "blocked_training_bots", "directives"] + CHECK_IDS)
        with self._lock:
            pages = list(self.results)
        for p in sorted(pages, key=lambda p: p["score"]):
            d = p["detail"]
            w.writerow([p["url"], p["status"], p["score"], p["grade"], " ".join(p["failed"]), d["title"], d["words"], d["ms"],
                        " ".join(d["blocked_ai_search_bots"]), " ".join(d["blocked_training_bots"]), " ".join(d["directives"])]
                       + ["PASS" if p["checks"][c] else "FAIL" for c in CHECK_IDS])
        return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description="Crawl a site and score AI readiness per page.")
    ap.add_argument("url")
    ap.add_argument("--max", type=int, default=500, help="max pages (default 500)")
    ap.add_argument("--subdomains", action="store_true", help="include subdomains of the base domain")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.25, help="seconds between requests per worker")
    ap.add_argument("--exclude", default="", help="regex; matching URLs are skipped")
    ap.add_argument("--csv", help="write per-page results to this CSV file")
    ap.add_argument("--json", action="store_true", help="print summary as JSON")
    a = ap.parse_args()
    c = Crawl(a.url, a.max, a.subdomains, a.workers, a.delay, a.exclude)
    t = threading.Thread(target=c.run, daemon=True)
    t.start()
    try:
        while t.is_alive():
            t.join(2)
            print(f"\rcrawled {len(c.results)}  queued {c.queued}", end="", file=sys.stderr)
    except KeyboardInterrupt:
        c.stop()
        t.join()
    print(file=sys.stderr)
    s = c.summary()
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            f.write(c.to_csv())
    if a.json:
        print(json.dumps(s, indent=2))
    else:
        print(f"{s['start']}: {s['pages']} pages, avg score {s['avg_score']}, {s['grades']}")
        for cf in s["check_failures"]:
            print(f"  {cf['label']:<24} failing on {cf['pct']:>3}% ({cf['failed']})" + ("  [critical]" if cf["critical"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
