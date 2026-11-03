#!/usr/bin/env python3
"""AI readiness crawler.

Crawls a site (homepage links + sitemaps, same host) and scores every HTML page
against fixed pass/fail checks for AI search / answer engines. Also produces:
  - a structured data report for the homepage organization schema, with a ready-to-paste fix
  - a PDF report: PDFs that hold key facts or mention past academic years

CLI:  python3 readiness.py https://www.methodist.edu --max 500 --csv pages.csv --pdf-csv pdfs.csv
Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from ai_bot_check import BOTS, Group, collect_sitemap_urls, fetch, parse_robots, parse_sitemaps, robots_verdict

CRAWLER_UA = "Mozilla/5.0 (compatible; AIReadinessChecker/1.0; site self-audit)"

# Bots whose access is scored: AI search + user-triggered fetchers (they put pages in AI answers).
SCORED_BOTS = [b[0] for b in BOTS if b[2] in ("search", "user")]
TRAINING_BOTS = [b[0] for b in BOTS if b[2] == "training"]

SKIP_EXT = re.compile(
    r"\.(pdf|jpe?g|png|gif|webp|svg|ico|bmp|tiff?|mp[34]|m4[av]|mov|avi|wmv|webm|zip|gz|tgz|rar|7z|"
    r"docx?|xlsx?|pptx?|csv|txt|xml|json|rss|atom|ics|css|js|woff2?|ttf|eot|exe|dmg|iso)$", re.I)

DEFAULTS = {
    "official_name": "Methodist University",
    "city": "Fayetteville",
    "region": "NC",
    "former_names": ["Methodist College"],
}

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
    ("schema_valid", "Valid structured data", "Every JSON-LD block is valid JSON (passes if the page has none).", False),
    ("official_name", "Official name", "The official name appears in the <title>, og:site_name, or JSON-LD.", False),
    ("no_former_name", "No former name", "The page text and title contain none of the former names. History pages may fail legitimately: review them.", False),
    ("current_dates", "No past terms", "The page names no academic year or term from before the current academic year (e.g. 2024-25, Fall 2024). Exempt: pages with a publish date, and pages under /news/, /blog/, /stories/, /press/ or /archive.", False),
    ("lang", "Language", "<html lang> attribute set.", False),
    ("open_graph", "Open Graph", "og:title and og:description present.", False),
    ("img_alt", "Image alt text", "At least 90% of <img> tags have non-empty alt text (passes if no images).", False),
    ("freshness", "Freshness signal", "Last-Modified header, article:modified_time, or dateModified/datePublished in JSON-LD.", False),
    ("fast", "Response time", "HTML delivered in under 2 seconds.", False),
]
CHECK_IDS = [c[0] for c in CHECKS]
CRITICAL = {c[0] for c in CHECKS if c[3]}

# PDF topics: matched against the PDF's URL and link text only (PDFs are not downloaded).
PDF_TOPICS = {
    "Tuition & fees": r"tuition|\bfees?\b|cost of attendance|\bcoa\b|pricing|\bcosts?\b",
    "Financial aid": r"financial[\s_-]*aid|scholarship|fafsa|net[\s_-]*price",
    "Deadlines & calendar": r"deadline|academic[\s_-]*calendar|important[\s_-]*dates|\bcalendar\b",
    "Admission requirements": r"admission|requirements|how[\s_-]*to[\s_-]*apply",
    "Catalog & programs": r"catalog|bulletin|curriculum|degree[\s_-]*(plan|map|sheet|requirements)|course[\s_-]*descriptions|program[\s_-]*of[\s_-]*study|checklist",
}
NEWS_PATH = re.compile(r"/(news|blog|blogs|stories|story|press|press-releases|archive|archives)(/|$)", re.I)
SOCIAL = ("facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "youtube.com",
          "tiktok.com", "wikipedia.org", "wikidata.org", "flickr.com", "pinterest.com")
ORG_TYPES = ("CollegeOrUniversity", "EducationalOrganization", "Organization", "School")
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def grade(score: int, results: dict) -> str:
    if any(results.get(c) is False for c in CRITICAL):
        return "Not ready"
    if score >= 80:
        return "Ready"
    if score >= 50:
        return "Needs work"
    return "Not ready"


# ---------------------------------------------------------------- dates

def academic_year_start(today: dt.date | None = None) -> int:
    """Academic year starts July 1. On 2026-11-03 this returns 2026 (AY 2026-27)."""
    today = today or dt.date.today()
    return today.year if today.month >= 7 else today.year - 1


AY_RE = re.compile(r"\b(20\d{2})\s*[-–—/]\s*((?:20)?\d{2})\b")
TERM_RE = re.compile(r"\b(fall|autumn|spring|summer|winter)\s+(?:semester\s+|term\s+|session\s+)?(20\d{2})\b", re.I)


def past_terms(text: str, ay: int) -> list[str]:
    """Mentions of academic years or terms that ended before the current academic year `ay`."""
    found = []
    for m in AY_RE.finditer(text):
        y1, y2 = int(m.group(1)), m.group(2)
        if int(y2[-2:]) == (y1 + 1) % 100 and y1 < ay:
            found.append(m.group(0))
    for m in TERM_RE.finditer(text):
        season, y = m.group(1).lower(), int(m.group(2))
        # Fall/Autumn Y and Winter Y belong to AY Y-(Y+1); Spring/Summer Y belong to AY (Y-1)-Y.
        stale = y < ay if season in ("fall", "autumn", "winter") else y <= ay
        if stale:
            found.append(m.group(0))
    out, seen = [], set()
    for f in found:
        k = " ".join(f.split()).lower()
        if k not in seen:
            seen.add(k)
            out.append(" ".join(f.split()))
    return out


# ---------------------------------------------------------------- HTML parsing

class PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    MAX_TEXT = 300_000

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
        self.anchors: list[tuple[str, str]] = []
        self.jsonld: list[str] = []
        self.words = 0
        self.text: list[str] = []
        self._text_len = 0
        self._skip = 0
        self._in_title = False
        self._in_jsonld = False
        self._buf: list[str] = []
        self._a: list[str] | None = None
        self._a_href = ""

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
            self._a, self._a_href = [], a["href"]
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
        if tag == "a" and self._a is not None:
            self.anchors.append((self._a_href, " ".join(" ".join(self._a).split())))
            self._a = None
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_jsonld:
            self._buf.append(data)
        elif not self._skip:
            self.words += len(data.split())
            if self._text_len < self.MAX_TEXT:
                self.text.append(data)
                self._text_len += len(data)
            if self._a is not None:
                self._a.append(data)


# ---------------------------------------------------------------- JSON-LD

def parse_jsonld(blocks: list[str]) -> tuple[list[dict], int]:
    """Return (all nested objects that carry an @type, number of blocks that failed to parse)."""
    objs, invalid = [], 0

    def walk(x):
        if isinstance(x, dict):
            if "@type" in x:
                objs.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for b in blocks:
        b = b.strip()
        if b.startswith("<!--"):
            b = b[4:]
        if b.endswith("-->"):
            b = b[:-3]
        b = b.strip()
        if b.startswith("//<![CDATA[") or b.startswith("<![CDATA["):
            b = b.split("[CDATA[", 1)[1].rsplit("]]>", 1)[0].rstrip("/ \n")
        if not b:
            continue
        try:
            walk(json.loads(b))
        except (ValueError, RecursionError):
            invalid += 1
    return objs, invalid


def types_of(o: dict) -> list[str]:
    t = o.get("@type", [])
    return [str(x).rsplit("/", 1)[-1] for x in (t if isinstance(t, list) else [t])]


def _str(v) -> str:
    if isinstance(v, dict):
        return str(v.get("url") or v.get("@id") or v.get("name") or "")
    if isinstance(v, list):
        return ", ".join(_str(x) for x in v)
    return "" if v is None else str(v)


# ---------------------------------------------------------------- page check

def _header(headers: dict, name: str) -> str:
    return next((v for k, v in headers.items() if k.lower() == name), "")


def _region_ok(found: str, want: str) -> bool:
    f, w = found.strip().casefold(), want.strip().casefold()
    if not w:
        return True
    full = US_STATES.get(want.strip().upper(), "").casefold()
    abbr = next((k for k, v in US_STATES.items() if v.casefold() == w), "").casefold()
    return f in {w, full, abbr} - {""}


def check_page(url: str, r: dict, elapsed: float, groups: list[Group], cfg: dict) -> dict:
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

    jsonld_raw = " ".join(p.jsonld)
    objs, invalid_jsonld = parse_jsonld(p.jsonld)
    title = " ".join(p.title.split())
    desc = p.meta.get("description", "").strip()
    text = " ".join(" ".join(p.text).split())
    fresh = bool(_header(r["headers"], "last-modified") or p.meta.get("article:modified_time")
                 or re.search(r'"date(Modified|Published)"', jsonld_raw))

    # name checks
    official = cfg["official_name"].strip()
    name_haystack = f"{title} {p.meta.get('og:site_name', '')} {jsonld_raw}".casefold()
    former_found = [n for n in cfg["former_names"]
                    if n and re.search(r"\b" + re.escape(n) + r"\b", f"{title} {text}", re.I)]

    # date checks
    published = bool(p.meta.get("article:published_time") or re.search(r'"datePublished"', jsonld_raw))
    dated_exempt = published or bool(NEWS_PATH.search(sp.path))
    stale = past_terms(f"{title} {text}", cfg["ay_start"])

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
        "schema_valid": invalid_jsonld == 0,
        "official_name": (not official) or official.casefold() in name_haystack,
        "no_former_name": not former_found,
        "current_dates": dated_exempt or not stale,
        "lang": bool(p.lang),
        "open_graph": bool(p.meta.get("og:title") and p.meta.get("og:description")),
        "img_alt": p.imgs == 0 or p.imgs_alt / p.imgs >= 0.9,
        "freshness": fresh,
        "fast": elapsed < 2.0,
    }
    score = round(100 * sum(res.values()) / len(res))

    pdfs = []
    for href, atext in p.anchors:
        absu = urljoin(url, href.strip())
        if urlsplit(absu).path.lower().endswith(".pdf"):
            pdfs.append((urlunsplit(urlsplit(absu)._replace(fragment="")), atext))
    social = sorted({urljoin(url, h).split("?")[0] for h in p.links
                     if any(urlsplit(urljoin(url, h)).netloc.lower().removeprefix("www.").endswith(s) for s in SOCIAL)})

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
            "schema_types": sorted({t for o in objs for t in types_of(o)}),
            "invalid_jsonld_blocks": invalid_jsonld,
            "former_names_found": former_found,
            "past_terms": stale[:10],
            "dated_exempt": dated_exempt,
        },
        "_links": p.links,
        "_pdfs": pdfs,
        "_objs": objs,
        "_social": social,
        "_meta": {"og:image": p.meta.get("og:image", "")},
    }


# ---------------------------------------------------------------- site-level reports

def org_report(home: dict | None, cfg: dict, origin: str) -> dict:
    """Check the homepage organization schema and build a ready-to-paste replacement."""
    objs = (home or {}).get("objs", [])
    orgs = [o for o in objs if set(types_of(o)) & set(ORG_TYPES)]
    org = next((o for o in orgs if "CollegeOrUniversity" in types_of(o)), orgs[0] if orgs else {})
    addr = org.get("address") if isinstance(org.get("address"), dict) else {}
    if isinstance(org.get("address"), list) and org["address"] and isinstance(org["address"][0], dict):
        addr = org["address"][0]
    name = _str(org.get("name"))
    rows = [
        ("Organization schema on homepage", bool(org), ", ".join(types_of(org)) if org else "none found"),
        ("Type is CollegeOrUniversity", "CollegeOrUniversity" in types_of(org), ", ".join(types_of(org)) or "-"),
        ("name is the official name", name.strip().casefold() == cfg["official_name"].strip().casefold(), name or "-"),
        ("url present", bool(org.get("url")), _str(org.get("url")) or "-"),
        ("logo present", bool(org.get("logo")), _str(org.get("logo")) or "-"),
        ("address city matches", bool(addr) and _str(addr.get("addressLocality")).strip().casefold() == cfg["city"].strip().casefold(),
         _str(addr.get("addressLocality")) or "-"),
        ("address state matches", bool(addr) and _region_ok(_str(addr.get("addressRegion")), cfg["region"]),
         _str(addr.get("addressRegion")) or "-"),
        ("sameAs (official profiles) present", bool(org.get("sameAs")), _str(org.get("sameAs")) or "-"),
    ]
    snippet = {
        "@context": "https://schema.org",
        "@type": "CollegeOrUniversity",
        "@id": origin + "/#organization",
        "name": cfg["official_name"],
        "url": origin + "/",
        "logo": _str(org.get("logo")) or (home or {}).get("og_image") or "REPLACE-WITH-FULL-URL-OF-LOGO-IMAGE",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": _str(addr.get("streetAddress")) or "REPLACE-WITH-STREET-ADDRESS",
            "addressLocality": cfg["city"],
            "addressRegion": cfg["region"],
            "postalCode": _str(addr.get("postalCode")) or "REPLACE-WITH-ZIP",
            "addressCountry": "US",
        },
    }
    tel = _str(org.get("telephone"))
    snippet["telephone"] = tel or "REPLACE-WITH-MAIN-PHONE"
    same = org.get("sameAs")
    same = same if isinstance(same, list) else ([same] if same else [])
    same = sorted(set(map(str, same)) | set((home or {}).get("social", [])))
    snippet["sameAs"] = same or ["REPLACE-WITH-OFFICIAL-SOCIAL-PROFILE-URLS"]
    if cfg["former_names"]:
        snippet["alternateName"] = cfg["former_names"]
    return {
        "home_url": (home or {}).get("url", ""),
        "rows": [{"label": a, "pass": b, "found": c} for a, b, c in rows],
        "passed": sum(1 for _, b, _ in rows if b),
        "total": len(rows),
        "snippet": '<script type="application/ld+json">\n' + json.dumps(snippet, indent=2) + "\n</script>",
    }


def pdf_rows(pdfs: dict, ay: int) -> list[dict]:
    rows = []
    for u, d in pdfs.items():
        hay = re.sub(r"[_+]", " ", f"{unquote(urlsplit(u).path)} {' '.join(d['texts'])}")
        topics = [t for t, rx in PDF_TOPICS.items() if re.search(rx, hay, re.I)]
        # second pass with hyphens as spaces catches file names like fall-2024.pdf
        stale = past_terms(hay + " " + hay.replace("-", " "), ay)
        rows.append({
            "url": u,
            "link_text": " | ".join(sorted(t for t in d["texts"] if t))[:200],
            "topics": topics,
            "past_terms": stale,
            "linked_from_count": d["count"],
            "linked_from": d["pages"],
        })
    rows.sort(key=lambda r: (not r["past_terms"], not r["topics"], -r["linked_from_count"]))
    return rows


# ---------------------------------------------------------------- crawler

def norm(u: str) -> str:
    sp = urlsplit(u)
    path = sp.path or "/"
    return urlunsplit((sp.scheme.lower(), sp.netloc.lower(), path, sp.query, ""))


class Crawl:
    """Breadth-first, same-site crawl. Thread-safe progress for the web UI."""

    def __init__(self, start: str, max_pages: int = 500, subdomains: bool = False,
                 workers: int = 4, delay: float = 0.25, exclude: str = "",
                 official_name: str | None = None, city: str | None = None, region: str | None = None,
                 former_names: list[str] | None = None):
        if "://" not in start:
            start = "https://" + start
        self.start = norm(start)
        self.host = urlsplit(self.start).netloc
        self.base = self.host[4:] if self.host.startswith("www.") else self.host
        self.origin = f"{urlsplit(self.start).scheme}://{self.host}"
        self.max_pages = max_pages
        self.subdomains = subdomains
        self.workers = workers
        self.delay = delay
        self.exclude = re.compile(exclude) if exclude else None
        self.cfg = {
            "official_name": DEFAULTS["official_name"] if official_name is None else official_name,
            "city": DEFAULTS["city"] if city is None else city,
            "region": DEFAULTS["region"] if region is None else region,
            "former_names": [n.strip() for n in (DEFAULTS["former_names"] if former_names is None else former_names) if n.strip()],
            "ay_start": academic_year_start(),
        }
        self.results: list[dict] = []
        self.pdfs: dict[str, dict] = {}
        self.schema_types: Counter = Counter()
        self.home: dict | None = None
        self.skipped: dict[str, int] = {}
        self.queued = 0
        self.state = "pending"
        self.error = ""
        self.started = time.time()
        self.finished: float | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._robots: dict[str, list[Group]] = {}
        self._sitemaps: dict[str, list[str]] = {}

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
            text = r["body"].decode("utf-8", "replace") if r["status"] == 200 else ""
            self._sitemaps[origin] = parse_sitemaps(text)
            self._robots[origin] = parse_robots(text)
        return self._robots[origin]

    def _skip(self, why: str):
        with self._lock:
            self.skipped[why] = self.skipped.get(why, 0) + 1

    def _visit(self, url: str) -> dict | None:
        sp = urlsplit(url)
        groups = self.robots(f"{sp.scheme}://{sp.netloc}")
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
        fs = urlsplit(final)
        page = check_page(final, r, elapsed, self.robots(f"{fs.scheme}://{fs.netloc}"), self.cfg)
        if final != url:
            page["redirected_from"] = url
        if url == self.start:
            page["_is_home"] = True
        return page

    def _absorb(self, page: dict) -> None:
        """Move private per-page data into site-level aggregates."""
        objs = page.pop("_objs")
        social = page.pop("_social")
        meta = page.pop("_meta")
        for t in page["detail"]["schema_types"]:
            self.schema_types[t] += 1
        if page.pop("_is_home", False):
            self.home = {"url": page["url"], "objs": objs, "social": social, "og_image": meta.get("og:image", "")}
        for u, t in page.pop("_pdfs"):
            d = self.pdfs.setdefault(u, {"texts": set(), "pages": [], "count": 0})
            d["texts"].add(t)
            if page["url"] not in d["pages"]:
                d["count"] += 1
                if len(d["pages"]) < 5:
                    d["pages"].append(page["url"])

    def run(self) -> None:
        self.state = "running"
        try:
            seen: set[str] = {self.start}
            frontier: list[str] = [self.start]
            self.robots(self.origin)
            sm = self._sitemaps.get(self.origin) or [self.origin + "/sitemap.xml"]
            sm_urls, _ = collect_sitemap_urls(sm, self.max_pages * 2)
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
                            self._absorb(page)
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
            pdfs = pdf_rows(self.pdfs, self.cfg["ay_start"])
            types = self.schema_types.most_common()
            home = self.home
        n = len(pages)
        fails = {c: sum(1 for p in pages if not p["checks"][c]) for c in CHECK_IDS}
        grades = {g: sum(1 for p in pages if p["grade"] == g) for g in ("Ready", "Needs work", "Not ready")}
        ay = self.cfg["ay_start"]
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
            "academic_year": f"{ay}-{str(ay + 1)[-2:]}",
            "settings": {k: v for k, v in self.cfg.items() if k != "ay_start"},
            "check_failures": [{"id": c[0], "label": c[1], "rule": c[2], "critical": c[3],
                                "failed": fails[c[0]], "pct": round(100 * fails[c[0]] / n) if n else 0} for c in CHECKS],
            "organization": org_report(home, self.cfg, self.origin) if home or self.state != "running" else None,
            "schema_types": [{"type": t, "pages": k} for t, k in types],
            "pdf_counts": {
                "total": len(pdfs),
                "key_facts": sum(1 for r in pdfs if r["topics"]),
                "past_terms": sum(1 for r in pdfs if r["past_terms"]),
            },
        }

    def pdf_report(self) -> list[dict]:
        with self._lock:
            return pdf_rows(self.pdfs, self.cfg["ay_start"])

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["url", "status", "score", "grade", "failed_checks", "title", "words", "ms",
                    "blocked_ai_search_bots", "blocked_training_bots", "directives",
                    "schema_types", "former_names_found", "past_terms"] + CHECK_IDS)
        with self._lock:
            pages = list(self.results)
        for p in sorted(pages, key=lambda p: p["score"]):
            d = p["detail"]
            w.writerow([p["url"], p["status"], p["score"], p["grade"], " ".join(p["failed"]), d["title"], d["words"], d["ms"],
                        " ".join(d["blocked_ai_search_bots"]), " ".join(d["blocked_training_bots"]), " ".join(d["directives"]),
                        " ".join(d["schema_types"]), "; ".join(d["former_names_found"]), "; ".join(d["past_terms"])]
                       + ["PASS" if p["checks"][c] else "FAIL" for c in CHECK_IDS])
        return buf.getvalue()

    def pdf_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["pdf_url", "link_text", "key_fact_topics", "past_terms", "linked_from_pages", "linked_from_examples"])
        for r in self.pdf_report():
            w.writerow([r["url"], r["link_text"], "; ".join(r["topics"]), "; ".join(r["past_terms"]),
                        r["linked_from_count"], " ".join(r["linked_from"])])
        return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description="Crawl a site and score AI readiness per page.")
    ap.add_argument("url")
    ap.add_argument("--max", type=int, default=500, help="max pages (default 500)")
    ap.add_argument("--subdomains", action="store_true", help="include subdomains of the base domain")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.25, help="seconds between requests per worker")
    ap.add_argument("--exclude", default="", help="regex; matching URLs are skipped")
    ap.add_argument("--name", default=DEFAULTS["official_name"], help="official institution name")
    ap.add_argument("--city", default=DEFAULTS["city"])
    ap.add_argument("--state", default=DEFAULTS["region"])
    ap.add_argument("--former", default=",".join(DEFAULTS["former_names"]), help="comma-separated former names")
    ap.add_argument("--csv", help="write per-page results to this CSV file")
    ap.add_argument("--pdf-csv", help="write the PDF report to this CSV file")
    ap.add_argument("--json", action="store_true", help="print summary as JSON")
    a = ap.parse_args()
    c = Crawl(a.url, a.max, a.subdomains, a.workers, a.delay, a.exclude,
              official_name=a.name, city=a.city, region=a.state, former_names=a.former.split(","))
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
    if a.pdf_csv:
        with open(a.pdf_csv, "w", newline="") as f:
            f.write(c.pdf_csv())
    if a.json:
        print(json.dumps(s, indent=2))
        return 0
    print(f"{s['start']}: {s['pages']} pages, avg score {s['avg_score']}, {s['grades']}  (academic year {s['academic_year']})")
    for cf in s["check_failures"]:
        print(f"  {cf['label']:<24} failing on {cf['pct']:>3}% ({cf['failed']})" + ("  [critical]" if cf["critical"] else ""))
    org = s["organization"]
    if org:
        print(f"\nOrganization schema ({org['passed']}/{org['total']} pass) on {org['home_url'] or 'homepage not crawled'}")
        for r in org["rows"]:
            print(f"  {'PASS' if r['pass'] else 'FAIL'}  {r['label']:<36} {r['found'][:80]}")
        if org["passed"] < org["total"]:
            print("\nRecommended homepage snippet (replace every REPLACE-WITH value):\n" + org["snippet"])
    pc = s["pdf_counts"]
    print(f"\nPDFs linked: {pc['total']}, with key-fact topics: {pc['key_facts']}, naming past terms: {pc['past_terms']}")
    print("Schema types found: " + (", ".join(f"{x['type']} ({x['pages']})" for x in s["schema_types"]) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
