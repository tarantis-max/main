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

from ai_bot_check import BOTS, DENY, Group, collect_sitemap_urls, fetch, parse_robots, parse_sitemaps, robots_verdict

CRAWLER_UA = "Mozilla/5.0 (compatible; AIReadinessChecker/1.0; site self-audit)"

# Bots whose access is scored: AI search + user-triggered fetchers (they put pages in AI answers).
SCORED_BOTS = [b[0] for b in BOTS if b[2] in ("search", "user") and b[0] not in DENY]  # denied bots never count against a page
TRAINING_BOTS = [b[0] for b in BOTS if b[2] == "training"]

SKIP_EXT = re.compile(
    r"\.(pdf|jpe?g|png|gif|webp|svg|ico|bmp|tiff?|mp[34]|m4[av]|mov|avi|wmv|webm|zip|gz|tgz|rar|7z|"
    r"docx?|xlsx?|pptx?|csv|txt|xml|json|rss|atom|ics|css|js|woff2?|ttf|eot|exe|dmg|iso)$", re.I)

def load_messages() -> dict:
    """messages.json next to this file: priority pages, proof points, banned phrases, numeric claims, inventory."""
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


MESSAGES = load_messages()


def _outdated_rules() -> list[tuple[dict, "re.Pattern"]]:
    """messages.json outdated_phrases, compiled. {OLD_YEARS} = 2000 through two years ago."""
    old_years = "|".join(str(y) for y in range(2000, dt.date.today().year - 1))
    out = []
    for x in MESSAGES.get("outdated_phrases", []):
        try:
            out.append((x, re.compile(x["pattern"].replace("{OLD_YEARS}", old_years), re.I)))
        except re.error:
            pass
    return out


OUTDATED = _outdated_rules()
QUANT_RE = re.compile(r"\d+(\.\d+)?\s?%|\$\s?\d|\b\d{1,3}(,\d{3})+\b|\b\d+\s+(students|graduates|programs|years|teams|clubs|scholarships|faculty|alumni|employers)\b", re.I)
YEAR_RE = re.compile(r"\b20[1-3]\d\b")
OWNER_RE = re.compile(r"\b(reviewed by|written by|page owner|content owner|maintained by|author:|by dr\.)", re.I)
PUBLISHED_RE = re.compile(r"\b(published|posted)( on)?:?\s+(\w+\.? \d{1,2},? 20\d\d|\d{1,2}/\d{1,2}/20\d\d)", re.I)
UPDATED_RE = re.compile(r"\b(updated|last (updated|reviewed|modified))( on)?:?\s+(\w+\.? \d{1,2},? 20\d\d|\d{1,2}/\d{1,2}/20\d\d|\w+ 20\d\d)", re.I)


DEFAULTS = {
    "official_name": "Methodist University",
    "city": "Fayetteville",
    "region": "NC",
    "former_names": ["Methodist College"],
}

# id, label, pass criterion, critical (critical fail => page is "Not ready")
CHECKS = [
    ("http_ok", "HTTP 200", "Page returns HTTP 200 to a normal request.", True),
    ("ai_search_allowed", "AI search bots allowed", "robots.txt allows every AI search and user-fetch bot for this URL, except bots on the deny list.", True),
    ("indexable", "No noindex/noai", "No noindex, none, noai or noimageai in meta robots or X-Robots-Tag.", True),
    ("server_text", "Server-rendered text", "At least 150 words of visible text in the raw HTML (most AI crawlers do not run JavaScript).", True),
    ("title", "Title", "<title> present, 10-70 characters, and does not start with a separator (\"| Site Name\" means the page name is missing).", False),
    ("meta_desc", "Meta description", "Meta description present, 50-160 characters.", False),
    ("one_h1", "Single H1", "Exactly one <h1>.", False),
    ("headings", "Subheadings", "At least one <h2> (content is structured into sections).", False),
    ("canonical", "Canonical URL", "<link rel=canonical> present.", False),
    ("structured_data", "Structured data", "At least one JSON-LD (schema.org) block.", False),
    ("schema_valid", "Valid structured data", "Every JSON-LD block is valid JSON (passes if the page has none).", False),
    ("official_name", "Official name", "The official name appears in the <title>, og:site_name, or JSON-LD.", False),
    ("current_dates", "No past terms", "The latest academic year or term named on the page is not before the current academic year (e.g. a page whose newest mention is 2024-25 or Fall 2024 fails; a list that runs up to 2026-27 passes). Exempt: pages with a publish date, and pages under /news/, /blog/, /stories/, /press/ or /archive.", False),
    ("lang", "Language", "<html lang> attribute set.", False),
    ("open_graph", "Open Graph", "og:title and og:description present.", False),
    ("img_alt", "Image alt text", "At least 90% of <img> tags have non-empty alt text (passes if no images).", False),
    ("freshness", "Freshness signal", "Last-Modified header, article:modified_time, or dateModified/datePublished in JSON-LD.", False),
    ("fast", "Response time", "HTML delivered in under 2 seconds.", False),
]
CHECKS += [
    ("mobile_viewport", "Mobile-friendly", "<meta name=viewport> with width=device-width (page adapts to phones).", False),
    ("clean_url", "Clean URL", "URL path is lowercase, uses hyphens not underscores, and is under 100 characters. Filter/query URLs are judged at site level.", False),
    ("readable", "Readable text", "On key student pages (admissions, cost, aid, visit, program home pages): paragraph text reads at grade 12 or below (Flesch-Kincaid). Not applicable to other pages or under 100 words.", False),
    ("question_headings", "Answers questions", "On key student pages (admissions, cost, aid, visit, program home pages): at least one H2/H3 phrased as a question, or FAQPage schema. Not applicable to other pages.", False),
    ("program_schema", "Program schema", "On program pages (/program/<name>/, /degrees/<name>/, /majors/<name>/): EducationalOccupationalProgram or Course schema. Not applicable to other pages or noindex pages.", False),
]
CATEGORY = {
    "ai_search_allowed": "AI access", "indexable": "AI access",
    "http_ok": "Technical SEO", "fast": "Technical SEO", "mobile_viewport": "Technical SEO", "clean_url": "Technical SEO",
    "canonical": "Technical SEO", "lang": "Technical SEO",
    "title": "On-page SEO", "meta_desc": "On-page SEO", "one_h1": "On-page SEO", "headings": "On-page SEO",
    "open_graph": "On-page SEO", "img_alt": "On-page SEO",
    "structured_data": "Structured data", "schema_valid": "Structured data", "program_schema": "Structured data",
    "server_text": "Content (GEO/AEO)", "readable": "Content (GEO/AEO)", "question_headings": "Content (GEO/AEO)",
    "current_dates": "Content (GEO/AEO)", "freshness": "Content (GEO/AEO)", "official_name": "Content (GEO/AEO)",
}
AREAS = ["AI access", "Technical SEO", "On-page SEO", "Structured data", "Content (GEO/AEO)"]
KEY_PATH = re.compile(r"admission|apply|tuition|cost|financial[-_]?aid|scholarship|visit|tour", re.I)
NOT_KEY_PATH = re.compile(r"/(news|event|events|blog|stories|directory|people)(/|$)", re.I)
AEO_PATH = re.compile(r"admission|apply|tuition|cost|financial[-_]?aid|scholarship|program|degree|major|graduate|undergraduate|"
                      r"transfer|international|military|visit|housing", re.I)
PROGRAM_PATH = re.compile(r"/(program|programs|degrees?|majors?)/[^/]+/?$", re.I)
QUESTION_RE = re.compile(r"\?\s*$|^(who|what|when|where|why|how|which|can|do|does|is|are|will|should)\b", re.I)
PROGRAM_TYPES = {"EducationalOccupationalProgram", "Course", "WorkBasedProgram"}


def fk_grade(text: str) -> float | None:
    """Flesch-Kincaid grade level; None if under 100 words."""
    text = re.sub(r"([^.!?\s])\s*\n", r"\1.\n", text)  # paragraphs without end punctuation still end a sentence
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    if len(words) < 100:
        return None
    sentences = max(1, len(re.findall(r"[.!?]+(\s|$)", text)))
    syl = 0
    for w in words:
        w = w.lower().strip("'")
        n = len(re.findall(r"[aeiouy]+", w))
        if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
            n -= 1
        syl += max(1, n)
    return round(0.39 * len(words) / sentences + 11.8 * syl / len(words) - 15.59, 1)


CHECK_IDS = [c[0] for c in CHECKS]
LABEL_OF = {c[0]: c[1] for c in CHECKS}
CRITICAL = {c[0] for c in CHECKS if c[3]}

# PDF topics: matched against the PDF's URL and link text only (PDFs are not downloaded).
PDF_TOPICS = {
    "Tuition & fees": r"tuition|\bfees?\b|cost of attendance|\bcoa\b|pricing|\bcosts?\b",
    "Financial aid": r"financial[\s_-]*aid|scholarships?[\s_-]*(application|request|form|guide|booklet|option)|fafsa|net[\s_-]*price",
    "Deadlines & calendar": r"deadline|academic[\s_-]*calendar|important[\s_-]*dates|\bcalendar\b",
    "Admission requirements": r"admissions?[\s_-]*(requirements?|criteria|checklist|guide)|how[\s_-]*to[\s_-]*apply|application[\s_-]*(checklist|deadline|requirements?)",
    "Catalog & programs": r"catalog|bulletin|curriculum|degree[\s_-]*(plan|map|sheet|requirements)|course[\s_-]*descriptions|program[\s_-]*of[\s_-]*study|checklist",
}
HOSTING_SUFFIXES = ("wpenginepowered.com", "wpengine.com", "pantheonsite.io", "kinsta.cloud", "kinsta.com", "netlify.app",
                    "vercel.app", "herokuapp.com", "azurewebsites.net", "cloudfront.net", "amazonaws.com", "wpcomstaging.com",
                    "flywheelsites.com", "pressable.com", "github.io")
LEGACY_HOST = re.compile(r"^(www)?(old|legacy|staging|stage|dev|test|beta|preview|archive)[0-9]*\.|(^|\.)(old|legacy|staging|stage|dev|test)[0-9]*\.", re.I)
APP_HOST = re.compile(r"^(apply|applyforonline|donate|give|giving|appointments?|munet|sft|support|help|servicedesk|portal|my|mymu|login|sso|cas|"
                      r"webmail|mail|canvas|blackboard|moodle|selfservice|banner|pay|payments)\.", re.I)
LOGIN_TITLE = re.compile(r"\b(log ?in|sign ?in|web client)\b", re.I)
LOGIN_PATH = re.compile(r"/(login|log-in|signin|sign-in|logout|servicedesk|portal|wp-admin|wp-login|account|my-account|cas)(/|\.|$)", re.I)
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


def term_years(text: str) -> list[int]:
    """Academic-year start of every academic year or term mentioned (past, current or future)."""
    out = []
    for m in AY_RE.finditer(text):
        y1, y2 = int(m.group(1)), m.group(2)
        if int(y2[-2:]) == (y1 + 1) % 100:
            out.append(y1)
    for m in TERM_RE.finditer(text):
        season, y = m.group(1).lower(), int(m.group(2))
        out.append(y if season in ("fall", "autumn", "winter") else y - 1)
    return out


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
        self.logos: list[str] = []
        self.login_form = False
        self.subheads: list[str] = []
        self.p_main: list[str] = []
        self.p_other: list[str] = []
        self._h = None
        self._hbuf: list[str] = []
        self._main = 0
        self._in_p = 0
        self._pcur: list[str] = []
        self.first_p: dict[str, tuple[int, int]] = {}
        self._recent: list[str] = []
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
        self._chrome = 0            # depth inside nav/header/footer/aside (site chrome, not page content)
        self.body_links: list[str] = []
        self.h2_body = 0
        self.body_text: list[str] = []
        self._body_len = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag != "img":
            self._recent = (self._recent + [a.get("class", "") + " " + a.get("id", "")])[-3:]
        if tag in ("nav", "header", "footer", "aside") or a.get("role", "").lower() in ("navigation", "banner", "contentinfo", "complementary"):
            self._chrome += 1
            a["data-chrome"] = "1"
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
            if not self._chrome:
                self.body_links.append(a["href"])
            self._a, self._a_href = [], a["href"]
        elif tag == "h1":
            self.h1 += 1
        if tag in ("h2", "h3"):
            self._h, self._hbuf = tag, []
        if tag in ("main", "article"):
            self._main += 1
        if tag == "p":
            self._in_p += 1
            self._pcur = []
        elif tag == "h2":
            self.h2 += 1
            if not self._chrome:
                self.h2_body += 1
        elif tag == "input" and a.get("type", "").lower() == "password":
            self.login_form = True
        elif tag == "img":
            self.imgs += 1
            if a.get("alt", "").strip():
                self.imgs_alt += 1
            src = a.get("src") or a.get("data-src") or ""
            own = " ".join((src, a.get("alt", ""), a.get("class", ""), a.get("id", ""))).lower()
            near = " ".join(self._recent).lower()  # class/id of the few elements just before (e.g. <a class="logo">)
            if src and ("logo" in own or "logo" in near or "brand" in near):
                self.logos.append(src)
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in_jsonld = True
            self._buf = []
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == self._h:
            self.subheads.append(" ".join(" ".join(self._hbuf).split()))
            self._h = None
        if tag in ("main", "article") and self._main:
            self._main -= 1
        if tag == "p" and self._in_p:
            self._in_p -= 1
            n = len(" ".join(self._pcur).split())
            if n >= 10:
                key = "main" if self._main else "other"
                if key not in self.first_p and not self._chrome:
                    self.first_p[key] = (n, self.h2_body)  # (words, body H2s seen before it)
            (self.p_main if self._main else self.p_other).append("\n")  # paragraph end = sentence break
        if tag == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._buf))
            self._in_jsonld = False
        if tag == "a" and self._a is not None:
            self.anchors.append((self._a_href, " ".join(" ".join(self._a).split())))
            self._a = None
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag in ("nav", "header", "footer", "aside") and self._chrome:
            self._chrome -= 1

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
            if not self._chrome and self._body_len < self.MAX_TEXT:
                self.body_text.append(data)
                self._body_len += len(data)
            if self._a is not None:
                self._a.append(data)
            if self._h:
                self._hbuf.append(data)
            if self._in_p:
                (self.p_main if self._main else self.p_other).append(data)
                self._pcur.append(data)


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


def lenient_jsonld(blocks: list[str]) -> list[dict]:
    """Best-effort repair of invalid JSON-LD (single quotes, mismatched quotes, trailing commas).
    Used only to recover values for the suggested fix; repaired blocks never count as valid."""
    out = []
    for b in blocks:
        try:
            json.loads(b.strip())
            continue  # valid blocks are handled by parse_jsonld
        except ValueError:
            pass
        t = re.sub(r"'([^'\"\n]*)\"", r"'\1'", b)                      # 'value"  -> 'value'
        t = re.sub(r"'([^'\\\n]*)'", lambda m: json.dumps(m.group(1)), t)  # 'x' -> "x"
        t = re.sub(r",(\s*[}\]])", r"\1", t)                              # trailing commas
        objs, bad = parse_jsonld([t])
        if not bad:
            out.extend(objs)
    return out


def schema_explainer(state: str, failed: int, total: int) -> list[str]:
    """Plain-language explanation of a site-wide structured data problem. state: invalid | missing."""
    if state == "invalid":
        what = ("Every page carries a block of hidden code (structured data, JSON-LD) meant to state the school's official facts "
                "in a form machines read reliably: name, address, phone, logo, website and official accounts. On this site the block "
                "exists but contains syntax errors, so Google, Bing, ChatGPT, Claude and other systems ignore it entirely. "
                f"It fails on {failed} of {total} pages checked, which means the error is in a shared template (header or footer).")
    else:
        what = ("Structured data (JSON-LD) is hidden code that states the school's official facts in a form machines read reliably: "
                f"name, address, phone, logo, website and official accounts. None was found on any of the {total} pages checked.")
    impact = ("Impact: low to moderate. Pages are not blocked or penalized and still appear in search results and AI answers, "
              "because those systems mostly read page text. What is lost is control of the school's identity: search engines and AI "
              "fill in the logo, address and contact details from third-party sources, errors there go uncorrected, and it is harder "
              "to tell this school apart from similarly named schools or its former name.")
    if state == "invalid":
        impact += " Google Search Console reports it as \"Unparsable structured data\" on every affected page."
    fix = ("Fix: about one hour for a web developer. "
           + ("Replace the broken block in the shared template with the corrected snippet (Site Readiness tab, Structured data card) "
              "and fix any empty site-address variable in that template. " if state == "invalid" else
              "Add the corrected snippet (Site Readiness tab, Structured data card) to the shared header template, or turn on "
              "organization schema in an SEO plugin. ")
           + "Then check the homepage at validator.schema.org (one CollegeOrUniversity item, no errors) and re-run this crawl. "
             "This is also the prerequisite for program, event and FAQ structured data, where the larger visibility gains are.")
    return [what, impact, fix]


PP_ELEMENTS = [
    ("direct_answer", "Direct answer", "The first paragraph of the main content is 20-80 words and comes before the first H2."),
    ("proof", "Proof", "The page states at least one number (%, $, count) and at least one year, so outcomes are dated. "
              "Also requires at least one approved proof point from messages.json."),
    ("connections", "Connections", "Links in the page body (not menus or footer) to at least {n} of: School of Medicine, Admissions, Scholarships and aid, Outcomes and careers."),
    ("authority", "Authority", "Named owner, author or reviewer, plus a published date and an updated date (visible or in page metadata)."),
    ("structure", "Structure", "At least 2 H2s in the page body, at least one question heading or FAQPage, 150+ words of server-rendered text, mobile viewport. (Invalid structured data is reported separately.)"),
]


def pp_elements(p: dict) -> dict:
    d, ch, pp = p["detail"], p["checks"], p["detail"].get("pp", {})
    need = MESSAGES.get("connections_required", 3)
    need_proof = MESSAGES.get("proof_points_required_on_priority_page", 1)
    return {
        "direct_answer": bool(pp.get("direct_answer")),
        "proof": bool(pp.get("proof")) and len(d.get("msg", {}).get("proof", [])) >= need_proof,
        "connections": len(pp.get("connections", [])) >= need,
        "authority": bool(pp.get("owner") and pp.get("published") and pp.get("updated")),
        "structure": (d.get("h2_count", 2) >= 2 and (d.get("question_headings", 0) > 0 or d.get("faq_schema"))
                      and ch.get("server_text") is True and ch.get("mobile_viewport") is True),
    }


# ---------------------------------------------------------------- two-part grade: Access + Answer quality

ANSWER_PARTS = [  # id, label, weight (sums to 100), what earns it
    ("direct_answer", "Direct answer", 25, "The first paragraph of the main content is 20-80 words and comes before the first H2."),
    ("proof", "Proof", 25, "States a number and a year, plus at least one approved proof point."),
    ("structure", "Structure", 20, "2+ H2s, a question heading or FAQ schema, 150+ words of server-rendered text, mobile viewport."),
    ("connections", "Connections", 10, "Body links to 2 of: School of Medicine, Admissions, Scholarships and aid, Outcomes and careers (half credit for 1)."),
    ("authority", "Authority", 10, "Half for a named owner or author, half for a date a reader can see."),
    ("accuracy", "Accurate and current", 10, "No outdated wording, no number that differs from the approved figure, no off-brand phrase."),
]
CITABLE_AT = 70  # answer quality needed for "Ready" on key pages
GRADES = ("Ready", "Readable, not citable", "Not ready")


def access_ok(p: dict) -> bool:
    """Can AI reach and read the page: the critical checks (loads, AI search bots allowed, no noindex/noai, text in the HTML)."""
    return p["status"] == 200 and not any(p["checks"].get(c) is False for c in CRITICAL)


def answer_parts(p: dict) -> dict:
    """Credit 0-1 for each answer-quality part."""
    d, pp = p["detail"], p["detail"].get("pp", {})
    el = pp_elements(p)
    need = MESSAGES.get("connections_required", 2)
    msg = d.get("msg", {})
    approved = {c["id"]: c["approved"] for c in MESSAGES.get("numeric_claims", [])}
    wrong_number = any(v != approved.get(k) for k, vals in msg.get("claims", {}).items() if k in approved for v, _ in vals)
    return {
        "direct_answer": 1.0 if el["direct_answer"] else 0.0,
        "proof": 1.0 if el["proof"] else 0.0,
        "structure": 1.0 if el["structure"] else 0.0,
        "connections": min(1.0, len(pp.get("connections", [])) / max(1, need)),
        "authority": 0.5 * bool(pp.get("owner")) + 0.5 * bool(pp.get("date_visible") or pp.get("published")),
        "accuracy": 0.0 if (msg.get("outdated") or msg.get("banned") or wrong_number) else 1.0,
    }


def answer_score(p: dict) -> int:
    parts = answer_parts(p)
    return round(sum(w * parts[i] for i, _, w, _ in ANSWER_PARTS))


def regrade(p: dict, key: bool) -> dict:
    """Set access, answer_score (key and priority pages only) and the grade. Works on saved pages too (rescore)."""
    p["access"] = access_ok(p)
    p["answer_score"] = answer_score(p) if (key and p["access"]) else None
    if not p["access"]:
        p["grade"] = "Not ready"
    elif key:
        p["grade"] = "Ready" if p["answer_score"] >= CITABLE_AT else "Readable, not citable"
    else:
        p["grade"] = "Ready"  # news, directory, events and the like: Access only
    return p


def answer_summary(pages: list[dict]) -> dict:
    """Key pages = every live key or priority page; one that fails Access counts as not citable."""
    live = [p for p in pages if p["status"] == 200 and (p["detail"].get("key_page") or p["detail"].get("priority"))]
    keyp = [p for p in live if p.get("answer_score") is not None]
    return {"key_pages": len(live), "citable": sum(1 for p in keyp if p["answer_score"] >= CITABLE_AT),
            "key_pages_no_access": len(live) - len(keyp),
            "average": round(sum(p["answer_score"] for p in keyp) / len(keyp)) if keyp else None,
            "access_pass": sum(1 for p in pages if p.get("access")), "pages": len(pages), "citable_at": CITABLE_AT,
            "parts": [{"id": i, "label": lbl, "weight": w, "rule": r,
                       "earned_pct": round(100 * sum(answer_parts(p)[i] for p in keyp) / len(keyp)) if keyp else None}
                      for i, lbl, w, r in ANSWER_PARTS]}


def priority_report(c: "Crawl", pages: list[dict]) -> dict:
    """EAB priority-page standard: each listed page scored on five elements; optimized = all five."""
    by = {p["url"]: p for p in pages}
    by.update({p.get("redirected_from"): p for p in pages if p.get("redirected_from")})
    rows = []
    for u in c.priority_pages:
        p = by.get(u)
        if not p:
            rows.append({"url": u, "status": "not crawled", "elements": {}, "score": None, "optimized": False})
            continue
        if p["status"] != 200:
            rows.append({"url": u, "status": p["status"], "elements": {}, "score": 0, "optimized": False})
            continue
        el = pp_elements(p)
        pp = p["detail"].get("pp", {})
        rows.append({"url": u, "status": 200, "title": p["detail"]["title"], "elements": el, "score": sum(el.values()),
                     "optimized": all(el.values()), "connections_found": pp.get("connections", []),
                     "proof_points": p["detail"].get("msg", {}).get("proof", []),
                     "first_paragraph_words": pp.get("first_paragraph_words", 0),
                     "owner": bool(pp.get("owner")), "published": bool(pp.get("published")), "updated": bool(pp.get("updated"))})
    key = [p for p in pages if p["status"] == 200 and p["detail"].get("key_page")]
    key_opt = sum(1 for p in key if all(pp_elements(p).values()))
    need = MESSAGES.get("connections_required", 3)
    return {
        "rows": rows,
        "elements": [{"id": a, "label": b, "rule": r.format(n=need)} for a, b, r in PP_ELEMENTS],
        "optimized": sum(1 for r in rows if r["optimized"]),
        "total": len(rows),
        "element_pass": {a: sum(1 for r in rows if r["elements"].get(a)) for a, _, _ in PP_ELEMENTS},
        "key_pages": len(key), "key_pages_optimized": key_opt,
    }


def message_report(c: "Crawl", pages: list[dict]) -> dict:
    ok = [p for p in pages if p["status"] == 200]
    home = next((p for p in ok if p["url"].rstrip("/") == c.start.rstrip("/")), None)
    prio = {u for u in c.priority_pages}
    prio_pages = [p for p in ok if p["url"] in prio]
    proof = []
    for x in MESSAGES.get("proof_points", []):
        proof.append({"id": x["id"], "label": x["label"],
                      "homepage": bool(home and x["id"] in home["detail"].get("msg", {}).get("proof", [])),
                      "priority_pages": sum(1 for p in prio_pages if x["id"] in p["detail"].get("msg", {}).get("proof", [])),
                      "site_pages": sum(1 for p in ok if x["id"] in p["detail"].get("msg", {}).get("proof", []))})
    banned = []
    for x in MESSAGES.get("banned_phrases", []):
        hits = [p["url"] for p in ok if x["phrase"] in p["detail"].get("msg", {}).get("banned", [])]
        banned.append({"phrase": x["phrase"], "pages": len(hits), "sample": hits[:10]})
    outdated = []
    for x, _ in OUTDATED:
        live, news, snip = [], [], ""
        for p in ok:
            for oid, sn in p["detail"].get("msg", {}).get("outdated", []):
                if oid == x["id"]:
                    (news if NEWS_PATH.search(urlsplit(p["url"]).path) else live).append(p["url"])
                    snip = snip or sn
        outdated.append({"id": x["id"], "phrase": x["phrase"], "use_instead": x.get("use_instead", ""), "pages": len(live), "news": len(news),
                         "template": len(ok) >= 5 and len(live) + len(news) >= 0.8 * len(ok),
                         "sample": live[:15], "news_sample": news[:10], "snippet": snip})
    claims = []
    for cl in MESSAGES.get("numeric_claims", []):
        vals: dict = {}
        for p in ok:
            for v, snip in p["detail"].get("msg", {}).get("claims", {}).get(cl["id"], []):
                e = vals.setdefault(str(v), {"value": v, "pages": 0, "sample": [], "snippet": snip})
                if p["url"] not in e["sample"]:
                    e["pages"] += 1
                    if len(e["sample"]) < 5:
                        e["sample"].append(p["url"])
        found = sorted(vals.values(), key=lambda e: -e["pages"])
        off = [e for e in found if e["value"] != cl["approved"]]
        claims.append({"id": cl["id"], "label": cl["label"], "approved": cl["approved"], "values": found,
                       "consistent": not off, "found": bool(found), "off_pages": sum(e["pages"] for e in off)})
    return {
        "proof_points": proof,
        "homepage_proof_points": sum(1 for x in proof if x["homepage"]),
        "banned": banned,
        "banned_pages": len({u for b in banned for u in b["sample"]}),
        "outdated": outdated,
        "outdated_pages": sum(x["pages"] for x in outdated),
        "outdated_news": sum(x["news"] for x in outdated),
        "claims": claims,
        "conflicting_claims": sum(1 for x in claims if x["found"] and not x["consistent"]),
        "priority_without_proof": [p["url"] for p in prio_pages if not p["detail"].get("msg", {}).get("proof")],
    }


def inventory_report(c: "Crawl", pages: list[dict]) -> dict:
    ok = [p for p in pages if p["status"] == 200]
    home = next((p for p in ok if p["url"].rstrip("/") == c.start.rstrip("/")), None)
    inv = MESSAGES.get("inventory", {})
    site_has = lambda k: [p["url"] for p in ok if k in p["detail"].get("inventory", [])]
    rows = []
    for k in ("net_price_calculator", "cost_page", "parents_page", "virtual_tour"):
        if k in inv:
            hits = site_has(k)
            rows.append({"id": k, "label": inv[k]["label"], "pass": bool(hits), "detail": f"linked from {len(hits)} page(s)" if hits else "not found on any crawled page"})
    if "virtual_tour" in inv:
        secs = MESSAGES.get("virtual_tour_sections", [])
        missing = []
        for sec in secs:
            pg = next((p for p in ok if urlsplit(p["url"]).path == sec), None)
            if not pg or "virtual_tour" not in pg["detail"].get("inventory", []):
                missing.append(sec + ("" if pg else " (not crawled)"))
        rows.append({"id": "virtual_tour_placement", "label": "Virtual tour linked from academics, admissions, student life, housing and visit pages",
                     "pass": not missing, "detail": ("missing on: " + ", ".join(missing)) if missing else f"all {len(secs)} pages"})
    for k in ("instagram", "youtube", "tiktok"):
        if k in inv:
            ok_ = bool(home and k in home["detail"].get("inventory", []))
            rows.append({"id": k, "label": inv[k]["label"] + " on homepage", "pass": ok_, "detail": "found" if ok_ else "not found"})
    progs = [p for p in ok if p["checks"].get("program_schema") is not None]
    with_out = [p for p in progs if p["detail"].get("outcomes")]
    rows.append({"id": "program_outcomes", "label": "Every program home page states an outcome (placement, pass rate, salary, employment)",
                 "pass": bool(progs) and len(with_out) == len(progs),
                 "detail": f"{len(with_out)} of {len(progs)} program pages",
                 "missing": [p["url"] for p in progs if not p["detail"].get("outcomes")][:20]})
    return {"rows": rows, "passed": sum(1 for r in rows if r["pass"]), "total": len(rows)}


def area_scores(pages: list[dict]) -> list[dict]:
    """Pass rate (0-100) per area across all applicable page checks."""
    out = []
    for area in AREAS:
        ids = [c for c, a in CATEGORY.items() if a == area]
        vals = [p["checks"].get(c) for p in pages for c in ids]
        vals = [v for v in vals if v is not None]
        out.append({"area": area, "score": round(100 * sum(vals) / len(vals)) if vals else None,
                    "checks": [LABEL_OF[c] for c in ids]})
    return out


def site_issues(c: "Crawl", pages: list[dict]) -> dict:
    """Site-level SEO/GEO findings that no single page can show."""
    hosting_links, unchecked = dict(c.hosting_links), list(c.unchecked)
    # a legacy host only counts if it still answers; one that no longer exists is just a dead link target
    hosts = Counter(urlsplit(p["url"]).netloc.lower() for p in pages if isinstance(p["status"], int))
    legacy = sorted(h for h in hosts if LEGACY_HOST.search(h))
    dead_legacy = [{"url": p["url"], "linked_from": c.referrers.get(p["url"], [])} for p in pages
                   if not isinstance(p["status"], int) and LEGACY_HOST.search(urlsplit(p["url"]).netloc.lower())]
    sections: dict[str, list[int]] = {}
    for p in pages:
        if p["status"] != 200:
            continue
        sp = urlsplit(p["url"])
        parts = [x for x in sp.path.split("/") if x]
        key = sp.netloc.lower() + "/" + (parts[0] + "/" if parts else "")
        t = sections.setdefault(key, [0, 0])
        t[0] += 1
        t[1] += p["checks"].get("indexable") is False
    noindex = sorted(([k, n, x] for k, (n, x) in sections.items() if n >= 10 and x / n >= 0.9), key=lambda r: -r[1])
    former = [p["url"] for p in pages if p["detail"].get("former_names_found")]
    ok_all = [p for p in pages if p["status"] == 200 and p["checks"].get("indexable") is not False]

    def canonical_self(p):
        cu = norm(p["detail"].get("canonical_url") or "") if p["detail"].get("canonical_url") else ""
        return not cu or cu == p["url"]
    ok = [p for p in ok_all if not urlsplit(p["url"]).query and canonical_self(p)]  # canonical pages only
    facets = [p["url"] for p in ok_all if urlsplit(p["url"]).query and canonical_self(p) and not LOGIN_PATH.search(urlsplit(p["url"]).path)]
    start_host = urlsplit(c.start).netloc.lower()
    # sitemap coverage (start host only)
    not_in_sitemap = [p["url"] for p in ok if urlsplit(p["url"]).netloc.lower() == start_host and p["url"] not in c.sitemap_urls] if c.sitemap_urls else []
    crawled = {p["url"]: p for p in pages}
    sitemap_broken = [u for u in c.sitemap_urls if u in crawled and crawled[u]["status"] != 200]
    sitemap_noindex = [u for u in c.sitemap_urls if u in crawled and crawled[u]["checks"].get("indexable") is False]
    # internal links
    orphans = [p["url"] for p in ok if c.inlinks.get(p["url"], 0) == 0 and p["url"].rstrip("/") != c.start.rstrip("/")]
    broken_links = [{"url": p["url"], "status": p["status"], "linked_from": c.referrers.get(p["url"], [])}
                    for p in pages if p["status"] != 200 and c.inlinks.get(p["url"], 0) > 0]
    # duplicates
    def dups(key):
        g: dict[str, list[str]] = {}
        for p in ok:
            v = (p["detail"].get(key) or "").strip().lower()
            if v:
                g.setdefault(v, []).append(p["url"])
        groups = sorted((v for v in g.values() if len(v) > 1), key=len, reverse=True)
        return {"pages": sum(len(v) for v in groups), "groups": len(groups),
                "top": [{"text": (crawled[v[0]]["detail"].get(key) or "")[:120], "pages": len(v), "sample": v[:3]} for v in groups[:5]]}
    trust = (c.home or {}).get("trust", {})
    wp = getattr(c, "wp", None) or {"checked": False}
    wordpress = {"checked": wp.get("checked", False), "available": wp.get("available", False), "note": wp.get("note", "")}
    if wp.get("available"):
        pub = wp.get("published") or {}
        not_sm = [u for u in pub if u not in c.sitemap_urls] if c.sitemap_urls else []
        hidden_all = [u for u in not_sm if c.inlinks.get(u, 0) == 0 and u.rstrip("/") != c.start.rstrip("/")]
        # event-calendar venues and organizers are created automatically by the events plugin: a noindex fix, not content
        listing = [u for u in hidden_all if WP_LISTING_TYPE.search(pub.get(u, ""))]
        hidden = [u for u in hidden_all if u not in set(listing)]
        file_redirects = [x for x in wp.get("suspects", []) if x.get("opens_file", True)]
        media_n = wp.get("media", 0)
        wordpress.update({"published": len(pub), "by_type": wp.get("by_type", {}), "media": media_n,
                          "media_limited": media_n < max(200, len(pub) // 4),
                          "not_in_sitemap": len(not_sm), "not_in_sitemap_sample": not_sm[:15],
                          "listing_pages": len(listing), "listing_sample": listing[:10],
                          "listing_types": sorted({pub.get(u, "") for u in listing}),
                          "hidden": len(hidden), "hidden_sample": hidden[:15],
                          "file_redirects": len(file_redirects), "file_redirect_sample": file_redirects[:15]})
    return {
        "wordpress": wordpress,
        "legacy_hosts": [{"host": h, "pages": hosts[h]} for h in legacy],
        "dead_legacy_links": dead_legacy[:20],
        "hosting_links": sorted(({"host": h, "links": n} for h, n in hosting_links.items()), key=lambda r: -r["links"]),
        "noindex_sections": [{"section": k, "pages": n, "noindex": x} for k, n, x in noindex],
        "former_name_pages": len(former),
        "former_name_sample": former[:25],
        "unchecked": unchecked,
        "sitemap": {"urls": len(c.sitemap_urls), "pages_not_in_sitemap": len(not_in_sitemap), "not_in_sitemap_sample": not_in_sitemap[:10],
                    "broken": len(sitemap_broken), "broken_sample": sitemap_broken[:10],
                    "noindex": len(sitemap_noindex), "noindex_sample": sitemap_noindex[:10]},
        "orphans": {"count": len(orphans), "sample": orphans[:10]},
        "indexable_query_urls": {"count": len(facets), "sample": facets[:10],
                                 "sections": [{"section": k, "pages": v} for k, v in Counter(urlsplit(u).path for u in facets).most_common(5)]},
        "broken_internal_links": {"count": len(broken_links), "sample": broken_links[:10]},
        "duplicate_titles": dups("title"),
        "duplicate_descriptions": dups("desc"),
        "faq_pages": sum(1 for p in ok if p["detail"].get("faq_schema")),
        "program_schema_pages": sum(1 for p in ok_all if p["checks"].get("program_schema") is True),  # same pages as the check
        "program_pages": sum(1 for p in ok_all if p["checks"].get("program_schema") is not None),
        "median_reading_grade": (lambda g: g[len(g) // 2] if g else None)(sorted(p["detail"]["reading_grade"] for p in ok if p["detail"].get("reading_grade") is not None)),
        "trust": {"Privacy policy link": trust.get("privacy_link"), "Phone or contact link": trust.get("contact"),
                  "Street address": trust.get("street_address"), "Accessibility statement link": trust.get("accessibility_link")} if trust else {},
    }


def schema_state(check_failures: list[dict]) -> str:
    """Site-wide structured data state: 'invalid' or 'missing' when it fails on 90%+ of pages, else ''."""
    by = {c["id"]: c for c in check_failures}
    if by.get("schema_valid", {}).get("pct", 0) >= 90:
        return "invalid"
    if by.get("structured_data", {}).get("pct", 0) >= 90:
        return "missing"
    return ""


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
    schema_types = sorted({t for o in objs for t in types_of(o)})
    has_faq = "FAQPage" in schema_types
    key_page = (bool(PROGRAM_PATH.search(sp.path)) or bool(KEY_PATH.search(sp.path))) and not NOT_KEY_PATH.search(sp.path) and not sp.query
    grade_level = fk_grade(" ".join(p.p_main if "".join(p.p_main).strip() else p.p_other))
    title = " ".join(p.title.split())
    desc = re.sub(r"[\ufeff\u200b\u200c\u200d\u2060]", "", p.meta.get("description", "")).strip()
    text = " ".join(" ".join(p.text).split())
    body = " ".join(" ".join(p.body_text).split()) or text   # page content without menus/header/footer
    page_text = f"{title} {body}"
    body_links_abs = [urljoin(url, h.strip()) for h in p.body_links]
    links_abs = [urljoin(url, h.strip()) for h in p.links]
    # A. priority page elements (EAB standard)
    fp = p.first_p.get("main") or p.first_p.get("other")
    conn = [label for label, rx in MESSAGES.get("connections", {}).items()
            if any(re.search(rx, urlsplit(u).path, re.I) and norm(u) != norm(url) for u in body_links_abs)]
    meta_author = p.meta.get("author", "").strip()
    pp = {
        "direct_answer": bool(fp and 20 <= fp[0] <= 80 and fp[1] == 0),
        "proof": bool(QUANT_RE.search(text) and YEAR_RE.search(text)),
        "connections": conn,
        "owner": bool(meta_author or re.search(r'"(author|reviewedBy|editor)"', " ".join(p.jsonld)) or OWNER_RE.search(text)),
        "published": bool(p.meta.get("article:published_time") or '"datePublished"' in " ".join(p.jsonld) or PUBLISHED_RE.search(text)),
        "updated": bool(p.meta.get("article:modified_time") or '"dateModified"' in " ".join(p.jsonld) or UPDATED_RE.search(text)),
        "first_paragraph_words": fp[0] if fp else 0,
        # a date a reader can see (or a post's published date); the CMS's hidden modified stamp does not count
        "date_visible": bool(PUBLISHED_RE.search(text) or UPDATED_RE.search(text) or p.meta.get("article:published_time")),
    }
    # B. messages
    msg = {
        "proof": [x["id"] for x in MESSAGES.get("proof_points", []) if re.search(x["pattern"], page_text, re.I)],
        "banned": [x["phrase"] for x in MESSAGES.get("banned_phrases", []) if re.search(x["pattern"], page_text, re.I)],
        "claims": {},
        "outdated": [],
    }
    full_text = f"{title} {text}"  # includes header/footer: a stale footer is a site-template fix
    for x, rx in OUTDATED:
        m_ = rx.search(full_text)
        if m_:
            a, b = max(0, m_.start() - 60), min(len(full_text), m_.end() + 60)
            msg["outdated"].append([x["id"], " ".join(full_text[a:b].split())])
    dated_page = bool(NEWS_PATH.search(sp.path) or p.meta.get("article:published_time") or '"datePublished"' in jsonld_raw)
    for cl in MESSAGES.get("numeric_claims", []):
        if dated_page:
            continue  # news and dated pages report past figures legitimately
        for m in re.finditer(cl["pattern"], page_text, re.I):
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            v = int(v) if v.is_integer() else v
            snip = page_text[max(0, m.start() - 40): m.end() + 40].strip()
            msg["claims"].setdefault(cl["id"], []).append([v, snip])
    # D. inventory signals (links and text)
    hay = " ".join(links_abs) + " " + " ".join(t for _, t in p.anchors)
    inv = [k for k, x in MESSAGES.get("inventory", {}).items() if re.search(x["pattern"], hay, re.I)]
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
        "title": 10 <= len(title) <= 70 and not re.match(r"^\s*[|\-\u2013\u2014:\u00b7]", title),
        "meta_desc": 50 <= len(desc) <= 160,
        "one_h1": p.h1 == 1,
        "headings": p.h2 >= 1,
        "canonical": bool(p.canonical),
        "structured_data": bool(p.jsonld),
        "schema_valid": invalid_jsonld == 0,
        "official_name": (not official) or official.casefold() in name_haystack,
        "current_dates": dated_exempt or not stale or max(term_years(f"{title} {text}") or [0]) >= cfg["ay_start"],
        "lang": bool(p.lang),
        "open_graph": bool(p.meta.get("og:title") and p.meta.get("og:description")),
        "img_alt": p.imgs == 0 or p.imgs_alt / p.imgs >= 0.9,
        "freshness": fresh,
        "fast": elapsed < 2.0,
        "mobile_viewport": "width=device-width" in p.meta.get("viewport", "").replace(" ", "").lower(),
        "clean_url": (sp.path == sp.path.lower() and "_" not in sp.path and len(sp.path) < 100),
        "readable": None if (grade_level is None or not key_page) else grade_level <= 12,
        "question_headings": (any(QUESTION_RE.search(h) for h in p.subheads if h) or has_faq) if key_page else None,
        "program_schema": (bool(set(schema_types) & PROGRAM_TYPES) if PROGRAM_PATH.search(sp.path) and not bad_directives else None),
    }
    if r["status"] != 200:
        res = {k: (False if k == "http_ok" else None) for k in res}  # content checks do not apply to error pages
    applicable = [v for v in res.values() if v is not None]
    score = 0 if r["status"] != 200 else round(100 * sum(applicable) / len(applicable))

    pdfs = []
    for href, atext in p.anchors:
        absu = urljoin(url, href.strip())
        if urlsplit(absu).path.lower().endswith(".pdf"):
            pdfs.append((urlunsplit(urlsplit(absu)._replace(fragment="")), atext))
    social = sorted({clean_profile(urljoin(url, h)) for h in p.links
                     if any(urlsplit(urljoin(url, h)).netloc.lower().removeprefix("www.").endswith(s) for s in SOCIAL)} - {""})
    # logo: first <img> whose src/alt/class/id mentions "logo"; prefer SVG/PNG
    logos = [urljoin(url, x) for x in p.logos]
    logo = next((x for x in logos if urlsplit(x).path.lower().endswith((".svg", ".png"))), logos[0] if logos else "")

    out = {
        "url": url,
        "status": r["status"] or r["error"],
        "score": score,  # technical score: share of the 23 checks passed
        "grade": "",
        "checks": res,
        "failed": [c for c in CHECK_IDS if res[c] is False],
        "detail": {
            "title": title[:120],
            "words": p.words,
            "h1": p.h1,
            "h2_count": p.h2_body,
            "images": p.imgs,
            "images_with_alt": p.imgs_alt,
            "ms": round(elapsed * 1000),
            "blocked_ai_search_bots": blocked_search,
            "blocked_training_bots": blocked_training,
            "directives": bad_directives,
            "schema_types": schema_types,
            "desc": desc[:200],
            "canonical_url": urljoin(url, p.canonical) if p.canonical else "",
            "key_page": key_page,
            "pp": pp,
            "msg": msg,
            "outcomes": bool(re.search(MESSAGES.get("outcome_pattern", "$^"), body, re.I)),
            "inventory": inv,
            "reading_grade": grade_level,
            "question_headings": sum(1 for h in p.subheads if h and QUESTION_RE.search(h)),
            "faq_schema": has_faq,
            "invalid_jsonld_blocks": invalid_jsonld,
            "former_names_found": former_found,
            "past_terms": stale[:10],
            "dated_exempt": dated_exempt,
            "login_form": p.login_form,
        },
        "_links": p.links,
        "_pdfs": pdfs,
        "_objs": objs,
        "_recovered": lenient_jsonld(p.jsonld) if invalid_jsonld else [],
        "_social": social,
        "_meta": {"logo": logo},
        "_trust": {
            "privacy_link": any("privacy" in (h + " " + t).lower() for h, t in p.anchors),
            "contact": any(h.lower().startswith("tel:") for h, _ in p.anchors) or bool(re.search(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b", text)),
            "street_address": bool(re.search(r"\b\d{2,6}\s+[A-Z][A-Za-z]+(\s[A-Z][A-Za-z]+)*\s(Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Lane|Way|Highway|Hwy)\b", text)),
            "accessibility_link": any("accessib" in (h + " " + t).lower() for h, t in p.anchors),
        },
    }
    return regrade(out, key_page)


def clean_profile(u: str) -> str:
    """Reduce a social link to the profile URL; drop share/intent links."""
    sp = urlsplit(u)
    host = sp.netloc.lower().removeprefix("www.")
    parts = [x for x in sp.path.split("/") if x]
    if not parts or parts[0].lower() in ("sharer", "sharer.php", "share", "intent", "home", "hashtag", "watch", "p", "reel", "status"):
        return ""
    if host.endswith("flickr.com") and parts[0] == "photos" and len(parts) >= 2:
        parts = parts[:2]
    elif host.endswith("linkedin.com") and parts[0] in ("school", "company", "in") and len(parts) >= 2:
        parts = parts[:2]
    elif host.endswith(("facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com", "pinterest.com")):
        parts = parts[:1]
    return f"https://{sp.netloc.lower()}/" + "/".join(parts) + ("/" if host.endswith(("flickr.com", "linkedin.com")) else "")


# ---------------------------------------------------------------- site-level reports

def org_report(home: dict | None, cfg: dict, origin: str) -> dict:
    """Check the homepage organization schema and build a ready-to-paste replacement."""
    objs = (home or {}).get("objs", [])
    orgs = [o for o in objs if set(types_of(o)) & set(ORG_TYPES)]
    org = next((o for o in orgs if "CollegeOrUniversity" in types_of(o)), orgs[0] if orgs else {})
    rec = [o for o in (home or {}).get("recovered", []) if set(types_of(o)) & set(ORG_TYPES)]
    rorg = {} if org else next((o for o in rec if "CollegeOrUniversity" in types_of(o)), rec[0] if rec else {})
    src = org or rorg  # values to show and reuse; checks still pass only on valid schema
    tag = " (in invalid block, ignored)" if rorg else ""

    def get_addr(o):
        a = o.get("address")
        if isinstance(a, list) and a and isinstance(a[0], dict):
            return a[0]
        return a if isinstance(a, dict) else {}

    def absolute(v: str) -> str:
        return v if v.startswith(("http://", "https://")) else ""

    addr = get_addr(org)
    saddr = get_addr(src)
    name = _str(org.get("name"))
    rows = [
        ("Organization schema on homepage", bool(org), ", ".join(types_of(org)) if org else (
            "invalid JSON-LD on homepage (%d block(s)), ignored by search engines and AI" % home["invalid"]
            if home and home.get("invalid") else "none found")),
        ("Type is CollegeOrUniversity", "CollegeOrUniversity" in types_of(org), (", ".join(types_of(src)) + tag) if src else "-"),
        ("name is the official name", name.strip().casefold() == cfg["official_name"].strip().casefold(), (_str(src.get("name")) + tag) if src.get("name") else "-"),
        ("url present", bool(org.get("url")), (_str(src.get("url")) + tag) if src.get("url") else "-"),
        ("logo present", bool(org.get("logo")), (_str(src.get("logo")) + tag) if src.get("logo") else "-"),
        ("address city matches", bool(addr) and _str(addr.get("addressLocality")).strip().casefold() == cfg["city"].strip().casefold(),
         (_str(saddr.get("addressLocality")) + tag) if saddr.get("addressLocality") else "-"),
        ("address state matches", bool(addr) and _region_ok(_str(addr.get("addressRegion")), cfg["region"]),
         (_str(saddr.get("addressRegion")) + tag) if saddr.get("addressRegion") else "-"),
        ("sameAs (official profiles) present", bool(org.get("sameAs")), (_str(src.get("sameAs")) + tag) if src.get("sameAs") else "-"),
    ]
    snippet = {
        "@context": "https://schema.org",
        "@type": "CollegeOrUniversity",
        "@id": origin + "/#organization",
        "name": cfg["official_name"],
        "url": origin + "/",
        # never the og:image: that is a social share image, not a logo
        "logo": absolute(_str(src.get("logo"))) or (home or {}).get("logo") or "REPLACE-WITH-FULL-URL-OF-LOGO-IMAGE",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": _str(saddr.get("streetAddress")) or "REPLACE-WITH-STREET-ADDRESS",
            "addressLocality": cfg["city"],
            "addressRegion": cfg["region"],
            "postalCode": _str(saddr.get("postalCode")).strip('" ') or "REPLACE-WITH-ZIP",
            "addressCountry": "US",
        },
    }
    tel = _str(src.get("telephone"))
    snippet["telephone"] = tel or "REPLACE-WITH-MAIN-PHONE"
    same = src.get("sameAs")
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
        "has_org": bool(org),
        "home_invalid": (home or {}).get("invalid", 0),
        "recovered": bool(rorg),
        "logo_source": "existing schema" if org.get("logo") else ("homepage <img> named logo" if (home or {}).get("logo") else "not found"),
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


WP_LISTING_TYPE = re.compile(r"venue|organizer|organiser|tribe_|location|speaker", re.I)
WP_SKIP_TYPES = {"attachment", "nav_menu_item", "wp_block", "wp_template", "wp_template_part", "wp_navigation",
                 "wp_global_styles", "wp_font_family", "wp_font_face"}
FILE_PATH = re.compile(r"/wp-content/uploads/|\.(jpe?g|png|gif|webp|svg|pdf|docx?|pptx?|xlsx?|mp4|mp3|zip)$", re.I)


def wp_list(origin: str, rest_base: str, fields: str, cap: int, delay: float) -> tuple[list[dict] | None, str]:
    """One WordPress REST collection, 100 per request. None if the site does not expose it."""
    out, page = [], 1
    while len(out) < cap:
        r = fetch(f"{origin}/wp-json/wp/v2/{rest_base}?per_page=100&page={page}&_fields={fields}", CRAWLER_UA, max_bytes=8_000_000)
        if r["status"] == 400 and page > 1:  # past the last page
            break
        if r["status"] != 200:
            return (out, "") if page > 1 else (None, f"HTTP {r['status'] or r['error']}")
        try:
            items = json.loads(r["body"])
        except ValueError:
            return (out, "") if page > 1 else (None, "not a WordPress JSON response")
        if not isinstance(items, list) or not items:
            break
        out.extend(x for x in items if isinstance(x, dict))
        total = _header(r["headers"], "x-wp-totalpages")
        if (total.isdigit() and page >= int(total)) or len(items) < 100:
            break
        page += 1
        time.sleep(delay)
    return out, ""


class Crawl:
    """Breadth-first, same-site crawl. Thread-safe progress for the web UI."""

    def __init__(self, start: str, max_pages: int = 500, subdomains: bool = False,
                 workers: int = 4, delay: float = 0.5, exclude: str = "",
                 official_name: str | None = None, city: str | None = None, region: str | None = None,
                 former_names: list[str] | None = None, priority_pages: list[str] | None = None, wordpress: bool = True):
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
        if priority_pages is None:  # default list only applies to the site it was written for
            dflt = MESSAGES.get("priority_pages", [])
            priority_pages = [u for u in dflt if urlsplit(u).netloc.lower() == self.host.lower()]
        self.priority_pages = [norm(u if "://" in u else urljoin(self.origin + "/", u.strip())) for u in priority_pages if u.strip()]
        self.priority_set = set(self.priority_pages)
        self.results: list[dict] = []
        self.pdfs: dict[str, dict] = {}
        self.schema_types: Counter = Counter()
        self.home: dict | None = None
        self.skipped: dict[str, int] = {}
        self.app_pages: list[str] = []   # apps, logins, donation forms: not content, not graded
        self.copies = 0                  # ?query pages whose canonical is another page: links followed, not graded
        self.unchecked: list[str] = []
        self.sitemap_urls: set[str] = set()
        self.wp: dict = {"checked": False}
        self.check_wordpress = wordpress
        self.inlinks: Counter = Counter()
        self.referrers: dict[str, list[str]] = {}
        self.hosting_links: Counter = Counter()
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
    def wordpress(self) -> dict:
        """Published pages/posts and media from the WordPress REST API (/wp-json/wp/v2/), when the site exposes it.
        Finds pages no link or sitemap points to, and media addresses that look like a former page
        (e.g. /academics/medicine-2/ opening an image because /academics/medicine/ is a page)."""
        groups = self.robots(self.origin)
        if robots_verdict(groups, "AIReadinessChecker", "/wp-json/wp/v2/pages")[0] == "blocked":
            return {"checked": True, "available": False, "note": "robots.txt blocks /wp-json/"}
        types_r = fetch(f"{self.origin}/wp-json/wp/v2/types", CRAWLER_UA)
        bases = {"pages": "page", "posts": "post"}
        if types_r["status"] == 200:
            try:
                for slug, t in (json.loads(types_r["body"]) or {}).items():
                    if slug not in WP_SKIP_TYPES and isinstance(t, dict) and t.get("rest_base") and t.get("viewable", True):
                        bases[t["rest_base"]] = slug
            except (ValueError, AttributeError):
                pass
        published: dict[str, str] = {}
        by_type: Counter = Counter()
        note = ""
        for base, slug in bases.items():
            items, err = wp_list(self.origin, base, "link", 20_000, self.delay)
            if items is None:
                if base == "pages":
                    return {"checked": True, "available": False, "note": err}
                continue
            for x in items:
                u = norm(str(x.get("link") or ""))
                if u and self.in_scope(u) and u not in published:
                    published[u] = slug
                    by_type[slug] += 1
        media, err = wp_list(self.origin, "media", "link,source_url", 20_000, self.delay)
        page_paths = {urlsplit(u).path.rstrip("/") for u in list(published) + list(self.sitemap_urls)}
        suspects = []
        for x in media or []:
            link = str(x.get("link") or "")
            path = urlsplit(link).path.rstrip("/")
            m = re.search(r"-\d+$", path)
            if m and path[: m.start()] in page_paths and path not in page_paths:
                suspects.append({"url": norm(link), "page": path[: m.start()] + "/", "file": str(x.get("source_url") or "")})
        if media is None:
            note = "media list not available (" + err + ")"
        for sx in suspects[:50]:  # confirm where the address actually goes
            r = fetch(sx["url"], CRAWLER_UA, max_bytes=2048)
            sx["status"], sx["goes_to"] = r["status"], r["final_url"]
            sx["opens_file"] = bool(FILE_PATH.search(urlsplit(r["final_url"] or "").path)) or "html" not in _header(r["headers"], "content-type").lower()
            time.sleep(self.delay)
        return {"checked": True, "available": True, "note": note, "published": published, "by_type": dict(by_type),
                "media": len(media or []), "suspects": suspects}

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

    def _app(self, url: str) -> None:
        self._skip("app, login or donation page (not content, not graded)")
        with self._lock:
            if len(self.app_pages) < 200:
                self.app_pages.append(url)

    def _visit(self, url: str) -> dict | None:
        sp = urlsplit(url)
        if url != self.start and (APP_HOST.search(sp.netloc) or LOGIN_PATH.search(sp.path)):
            self._app(url)
            return None
        groups = self.robots(f"{sp.scheme}://{sp.netloc}")
        path = (sp.path or "/") + (f"?{sp.query}" if sp.query else "")
        if robots_verdict(groups, "AIReadinessChecker", path)[0] == "blocked":
            self._skip("blocked for crawler by robots.txt")
            return None
        for attempt in range(4):
            t0 = time.time()
            r = fetch(url, CRAWLER_UA, max_bytes=3_000_000)
            elapsed = time.time() - t0
            time.sleep(self.delay)
            transient = r["status"] in (429, 502, 503, 504) or (r["status"] is None and "timed out" in str(r["error"]).lower())
            if not transient:
                break
            ra = _header(r["headers"], "retry-after")
            time.sleep(min(int(ra), 60) if ra.isdigit() else 2 * 2 ** attempt)
        if transient:
            self._skip("could not check (rate-limited or timed out after 4 tries)")
            with self._lock:
                if len(self.unchecked) < 200:
                    self.unchecked.append(url)
            return None
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
        if url != self.start and (page["detail"]["login_form"] or LOGIN_TITLE.search(page["detail"].get("title") or "")):
            self._app(final)
            return None
        cu = (page["detail"].get("canonical_url") or "").strip()
        if fs.query and page["status"] == 200 and cu and norm(urljoin(final, cu)) != final:
            page["_copy"] = True  # filtered or paged copy: follow its links, do not grade it
        if final != url:
            page["redirected_from"] = url
        if (url in self.priority_set or final in self.priority_set or url == self.start) and not page["detail"]["key_page"]:  # the homepage always counts
            page["detail"]["priority"] = True
            regrade(page, True)
        if url == self.start:
            page["_is_home"] = True
        return page

    def _absorb(self, page: dict) -> None:
        """Move private per-page data into site-level aggregates."""
        objs = page.pop("_objs")
        recovered = page.pop("_recovered")
        social = page.pop("_social")
        meta = page.pop("_meta")
        trust = page.pop("_trust")
        for t in page["detail"]["schema_types"]:
            self.schema_types[t] += 1
        if page.pop("_is_home", False):
            self.home = {"url": page["url"], "objs": objs, "social": social, "logo": meta.get("logo", ""),
                         "invalid": page["detail"]["invalid_jsonld_blocks"], "recovered": recovered, "trust": trust}
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
            for u in self.priority_pages:  # always crawl priority pages first
                if u not in seen and self.in_scope(u):
                    seen.add(u)
                    frontier.append(u)
            self.robots(self.origin)
            sm = self._sitemaps.get(self.origin) or [self.origin + "/sitemap.xml"]
            all_sm, _ = collect_sitemap_urls(sm, 50_000, max_sitemaps=200)
            self.sitemap_urls = {norm(u) for u in all_sm}
            sm_urls = all_sm[: self.max_pages * 2]
            for u in sm_urls:
                u = norm(u)
                if u not in seen and self.in_scope(u):
                    seen.add(u)
                    frontier.append(u)
            try:
                if self.check_wordpress:
                    self.wp = self.wordpress()
            except Exception as ex:  # never let the WordPress check stop the crawl
                self.wp = {"checked": True, "available": False, "note": f"{type(ex).__name__}: {ex}"}
            extra = [u for u in (self.wp.get("published") or {}) if u not in seen]
            for u in extra:
                seen.add(u)
            at = 1 + len(self.priority_pages)
            frontier[at:at] = extra  # published but not in the sitemap: crawl before the long tail
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
                        for nu in {norm(urljoin(page["url"], h.strip())) for h in page["_links"]}:
                            if nu != page["url"] and self.in_scope(nu):
                                self.inlinks[nu] += 1
                                refs = self.referrers.setdefault(nu, [])
                                if len(refs) < 3:
                                    refs.append(page["url"])
                        for href in page.pop("_links"):
                            nu = norm(urljoin(page["url"], href.strip()))
                            nh = urlsplit(nu).netloc.lower()
                            if nh.endswith(HOSTING_SUFFIXES):
                                self.hosting_links[nh] += 1
                            if nu not in seen and self.in_scope(nu):
                                seen.add(nu)
                                frontier.append(nu)
                        if page.pop("_copy", False):
                            with self._lock:
                                self.copies += 1
                            continue
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
        fails = {c: sum(1 for p in pages if p["checks"].get(c) is False) for c in CHECK_IDS}
        grades = {g: sum(1 for p in pages if p["grade"] == g) for g in GRADES}
        ay = self.cfg["ay_start"]
        return {
            "start": self.start,
            "state": self.state,
            "error": self.error,
            "pages": n,
            "queued": self.queued,
            "max_pages": self.max_pages,
            "skipped": dict(self.skipped),
            "copies": self.copies,
            "app_pages": list(self.app_pages[:25]),
            "elapsed_s": round((self.finished or time.time()) - self.started),
            "avg_score": round(sum(p["score"] for p in pages) / n) if n else 0,
            "grades": grades,
            "answer": answer_summary(pages),
            "academic_year": f"{ay}-{str(ay + 1)[-2:]}",
            "settings": {k: v for k, v in self.cfg.items() if k != "ay_start"},
            "check_failures": [{"id": c[0], "label": c[1], "rule": c[2], "critical": c[3],
                                "failed": fails[c[0]], "pct": round(100 * fails[c[0]] / n) if n else 0} for c in CHECKS],
            "organization": org_report(home, self.cfg, self.origin) if home or self.state != "running" else None,
            "site_issues": site_issues(self, pages),
            "areas": area_scores(pages),
            "priority_pages": priority_report(self, pages),
            "messages": message_report(self, pages),
            "inventory": inventory_report(self, pages),
            "schema_state": schema_state(cf_list := [{"id": c[0], "pct": round(100 * fails[c[0]] / n) if n else 0} for c in CHECKS]),
            "schema_explainer": schema_explainer(schema_state(cf_list), fails["schema_valid"] if schema_state(cf_list) == "invalid" else fails["structured_data"], n) if n and schema_state(cf_list) else [],
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
        w.writerow(["url", "status", "answer_quality", "access", "technical_score", "grade", "failed_checks", "title", "words", "ms",
                    "blocked_ai_search_bots", "blocked_training_bots", "directives",
                    "schema_types", "former_names_found", "past_terms", "in_sitemap", "linked_from"] + CHECK_IDS)
        with self._lock:
            pages = list(self.results)
        for p in sorted(pages, key=lambda p: (p.get("answer_score") if p.get("answer_score") is not None else 1000, p["score"])):
            d = p["detail"]
            w.writerow([p["url"], p["status"], "" if p.get("answer_score") is None else p["answer_score"], "yes" if p.get("access") else "no", p["score"], p["grade"], " ".join(p["failed"]), d["title"], d["words"], d["ms"],
                        " ".join(d["blocked_ai_search_bots"]), " ".join(d["blocked_training_bots"]), " ".join(d["directives"]),
                        " ".join(d["schema_types"]), "; ".join(d["former_names_found"]), "; ".join(d["past_terms"]),
                        "yes" if p["url"] in self.sitemap_urls else "no", " ".join(self.referrers.get(p["url"], []))]
                       + [{True: "PASS", False: "FAIL"}.get(p["checks"].get(c), "N/A") for c in CHECK_IDS])
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
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests per worker")
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
