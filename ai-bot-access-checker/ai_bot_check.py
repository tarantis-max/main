#!/usr/bin/env python3
"""AI bot access checker.

For a given site, reports whether known AI crawlers are allowed or blocked by:
  1. robots.txt        (RFC 9309: longest match wins, Allow wins ties, * and $ supported)
  2. HTTP response     (fetches the page with each bot's User-Agent, compares to a browser baseline)
  3. Page directives   (X-Robots-Tag header and <meta name="robots|<bot>"> tags, incl. noai/noimageai)
  4. Policy files      (/llms.txt, /ai.txt presence)

Standard library only. Usage:
  python3 ai_bot_check.py https://www.example.edu
  python3 ai_bot_check.py https://www.example.edu/admissions --json
  python3 ai_bot_check.py example.edu --no-probe
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

TIMEOUT = 15
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# (robots.txt token, operator, purpose, full User-Agent string used for the HTTP probe)
# purpose: training = model training data; search = AI search index; user = fetch on a user's request
BOTS = [
    ("GPTBot", "OpenAI", "training", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.1; +https://openai.com/gptbot"),
    ("OAI-SearchBot", "OpenAI", "search", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot"),
    ("ChatGPT-User", "OpenAI", "user", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot"),
    ("ClaudeBot", "Anthropic", "training", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)"),
    ("Claude-SearchBot", "Anthropic", "search", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-SearchBot/1.0; +https://www.anthropic.com)"),
    ("Claude-User", "Anthropic", "user", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +https://www.anthropic.com)"),
    ("Google-Extended", "Google", "training", None),  # robots.txt token only; crawls as Googlebot
    ("Googlebot", "Google", "search", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"),
    ("Applebot-Extended", "Apple", "training", None),  # robots.txt token only; crawls as Applebot
    ("Applebot", "Apple", "search", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15 (Applebot/0.1; +http://www.apple.com/go/applebot)"),
    ("Bingbot", "Microsoft", "search", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm) Chrome/116.0.1938.76 Safari/537.36"),
    ("PerplexityBot", "Perplexity", "search", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)"),
    ("Perplexity-User", "Perplexity", "user", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)"),
    ("Meta-ExternalAgent", "Meta", "training", "meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)"),
    ("Meta-ExternalFetcher", "Meta", "user", "meta-externalfetcher/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)"),
    ("Amazonbot", "Amazon", "training", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot) Chrome/119.0.6045.214 Safari/537.36"),
    ("Bytespider", "ByteDance", "training", "Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36 (compatible; Bytespider; spider-feedback@bytedance.com)"),
    ("CCBot", "Common Crawl", "training", "CCBot/2.0 (https://commoncrawl.org/faq/)"),
    ("cohere-ai", "Cohere", "user", "cohere-ai"),
    ("MistralAI-User", "Mistral", "user", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; MistralAI-User/1.0; +https://docs.mistral.ai/robots)"),
    ("DuckAssistBot", "DuckDuckGo", "user", "DuckAssistBot/1.2; (+http://duckduckgo.com/duckassistbot.html)"),
    ("AI2Bot", "Allen Institute", "training", "Mozilla/5.0 (compatible) AI2Bot (+https://www.allenai.org/crawler)"),
    ("Diffbot", "Diffbot", "training", "Mozilla/5.0 (compatible; Diffbot/0.1; +http://www.diffbot.com)"),
    # Additional training / dataset crawlers
    ("anthropic-ai", "Anthropic", "training", None),  # legacy token, still honored
    ("Claude-Web", "Anthropic", "user", None),  # legacy token
    ("GoogleOther", "Google", "training", "Mozilla/5.0 (compatible; GoogleOther)"),
    ("Google-CloudVertexBot", "Google", "training", "Mozilla/5.0 (compatible; Google-CloudVertexBot; +https://cloud.google.com/enterprise-search)"),
    ("FacebookBot", "Meta", "training", "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php) FacebookBot"),
    ("cohere-training-data-crawler", "Cohere", "training", "cohere-training-data-crawler/1.0"),
    ("YouBot", "You.com", "search", "Mozilla/5.0 (compatible; YouBot (+http://www.you.com))"),
    ("PetalBot", "Huawei", "search", "Mozilla/5.0 (compatible;PetalBot;+https://webmaster.petalsearch.com/site/petalbot)"),
    ("PanguBot", "Huawei", "training", "Mozilla/5.0 (compatible; PanguBot;+https://www.huaweicloud.com/)"),
    ("Timpibot", "Timpi", "training", "Timpibot/0.8 (+http://www.timpi.io)"),
    ("ImagesiftBot", "Hive", "training", "Mozilla/5.0 (compatible; ImagesiftBot; +imagesift.com)"),
    ("Omgilibot", "Webz.io", "training", "omgilibot/0.4 +http://omgili.com"),
    ("Webzio-Extended", "Webz.io", "training", None),
    ("Kangaroo Bot", "Kangaroo LLM", "training", "Mozilla/5.0 (compatible; Kangaroo Bot/1.0; +https://kangaroollm.com.au/kangaroo-bot/)"),
    ("img2dataset", "LAION", "training", "Mozilla/5.0 (compatible; img2dataset; +https://github.com/rom1504/img2dataset)"),
]

AI_DIRECTIVES = {"noai", "noimageai", "noindex", "none"}


def load_policy() -> dict[str, str]:
    """Deny list from bot_policy.json next to this file: {bot token: reason}."""
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_policy.json")
    try:
        with open(path, encoding="utf-8") as f:
            return dict(json.load(f).get("deny", {}))
    except FileNotFoundError:
        return {}


DENY = load_policy()


def deny_robots_snippet(tokens: list[str]) -> str:
    """robots.txt group that blocks the given bots from the whole site."""
    return "".join(f"User-agent: {t}\n" for t in tokens) + "Disallow: /\n" if tokens else ""


def fully_blocked(row: dict, scanned: int) -> bool:
    """Policy compliance: blocked on the checked URL and on every sampled sitemap page, or refused by the server."""
    if str(row.get("http_probe", "")).startswith(("blocked", "challenged")):
        return True
    return row["robots_txt"] == "blocked" and (not scanned or row.get("site_allowed", 0) == 0)


# ---------------------------------------------------------------- HTTP

def _ctx() -> ssl.SSLContext:
    return ssl.create_default_context()


def fetch(url: str, ua: str, max_bytes: int = 512_000) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx()) as r:
            body = r.read(max_bytes)
            return {"status": r.status, "headers": dict(r.headers), "body": body, "final_url": r.geturl(), "error": None}
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read(max_bytes)
        except Exception:
            pass
        return {"status": e.code, "headers": dict(e.headers or {}), "body": body, "final_url": url, "error": None}
    except Exception as e:  # DNS, TLS, timeout, reset
        return {"status": None, "headers": {}, "body": b"", "final_url": url, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- robots.txt (RFC 9309)

@dataclass
class Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, path)


def parse_sitemaps(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.lower().startswith("sitemap:"):
            out.append(line.split(":", 1)[1].strip())
    return out


def rules_for(groups: list[Group], token: str) -> list[str]:
    t = token.lower()
    matched = [g for g in groups if t in g.agents] or [g for g in groups if "*" in g.agents]
    return [("Allow: " if a else "Disallow: ") + p for g in matched for a, p in g.rules if p]


def parse_robots(text: str) -> list[Group]:
    groups: list[Group] = []
    cur: Group | None = None
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if cur is None or not last_was_agent:
                cur = Group()
                groups.append(cur)
            cur.agents.append(val.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            if cur is not None:
                cur.rules.append((key == "allow", val))
            last_was_agent = False
        else:
            last_was_agent = False  # sitemap, crawl-delay, etc.
    return groups


def _rule_regex(path: str) -> re.Pattern:
    anchored = path.endswith("$")
    if anchored:
        path = path[:-1]
    pat = ".*".join(re.escape(unquote(p)) for p in path.split("*"))
    return re.compile("^" + pat + ("$" if anchored else ""))


def robots_verdict(groups: list[Group], token: str, path: str) -> tuple[str, str]:
    """Return (verdict, matched_group_label). verdict in allowed|blocked."""
    t = token.lower()
    matched = [g for g in groups if t in g.agents]
    label = token
    if not matched:
        matched = [g for g in groups if "*" in g.agents]
        label = "*"
    if not matched:
        return "allowed", "no matching group"
    rules = [r for g in matched for r in g.rules]
    path = unquote(path or "/")
    best: tuple[int, bool] | None = None  # (length, allow)
    for allow, rpath in rules:
        if rpath == "":
            continue  # empty Disallow = allow all
        if _rule_regex(rpath).match(path):
            score = (len(rpath), allow)
            if best is None or score > best:  # longer wins; on tie Allow (True) wins
                best = score
    if best is None or best[1]:
        return "allowed", label
    return "blocked", label


# ---------------------------------------------------------------- sitemaps

def collect_sitemap_urls(sitemaps: list[str], limit: int) -> tuple[list[str], list[str]]:
    """Breadth-first over sitemap indexes. Returns (page_urls, sitemaps_read)."""
    import gzip
    import xml.etree.ElementTree as ET
    queue, seen, pages, read = list(sitemaps), set(), [], []
    while queue and len(pages) < limit and len(read) < 25:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        r = fetch(sm, BROWSER_UA, max_bytes=20_000_000)
        if r["status"] != 200:
            continue
        body = r["body"]
        if body[:2] == b"\x1f\x8b":
            try:
                body = gzip.decompress(body)
            except Exception:
                continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            continue
        read.append(sm)
        locs = [e.text.strip() for e in root.iter() if e.tag.endswith("loc") and e.text]
        if root.tag.endswith("sitemapindex"):
            queue.extend(locs)
        else:
            pages.extend(locs)
    # sample evenly so one section does not dominate
    if len(pages) > limit:
        step = len(pages) / limit
        pages = [pages[int(i * step)] for i in range(limit)]
    return pages, read


def _path_of(u: str) -> str:
    sp = urlsplit(u)
    return (sp.path or "/") + (f"?{sp.query}" if sp.query else "")


# ---------------------------------------------------------------- page directives

class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.metas: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        name = a.get("name", "").lower()
        if name and "content" in a:
            self.metas[name] = (self.metas.get(name, "") + "," + a["content"].lower()).strip(",")


def directives_for(token: str, headers: dict, metas: dict) -> list[str]:
    t = token.lower()
    found: set[str] = set()
    for k, v in headers.items():
        if k.lower() != "x-robots-tag":
            continue
        for part in v.split(","):
            part = part.strip().lower()
            if ":" in part:  # "gptbot: noindex"
                who, d = (s.strip() for s in part.split(":", 1))
                if who == t:
                    found.add(d)
            else:
                found.add(part)
    for name in ("robots", t):
        for d in metas.get(name, "").split(","):
            d = d.strip()
            if d:
                found.add(d)
    return sorted(found & AI_DIRECTIVES)


# ---------------------------------------------------------------- probe classification

CHALLENGE_MARKERS = (b"cf-chl", b"challenge-platform", b"captcha", b"access denied", b"attention required")


def classify(probe: dict, baseline: dict) -> str:
    if probe["error"]:
        return "error"
    s = probe["status"]
    if s in (401, 403, 406, 429, 451, 503) and baseline["status"] != s:
        return f"blocked ({s})"
    if s and s >= 400:
        return f"error ({s})" if baseline["status"] == s else f"blocked ({s})"
    low = probe["body"][:20000].lower()
    if any(m in low for m in CHALLENGE_MARKERS) and not any(m in baseline["body"][:20000].lower() for m in CHALLENGE_MARKERS):
        return "challenged"
    return f"allowed ({s})"


# ---------------------------------------------------------------- main

def normalize(url: str) -> str:
    if "://" not in url:
        url = "https://" + url
    return url


def run(url: str, probe: bool, scan: int = 0) -> dict:
    url = normalize(url)
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")

    robots = fetch(origin + "/robots.txt", BROWSER_UA)
    sitemaps: list[str] = []
    if robots["status"] == 200:
        robots_text = robots["body"].decode("utf-8", "replace")
        groups = parse_robots(robots_text)
        sitemaps = parse_sitemaps(robots_text)
        robots_state = "found"
    elif robots["status"] and 400 <= robots["status"] < 500:
        groups, robots_state = [], f"missing ({robots['status']}) - all allowed"
    else:
        # RFC 9309: unreachable robots.txt (5xx/network) => assume full disallow
        groups = [Group(agents=["*"], rules=[(False, "/")])]
        robots_state = f"unreachable ({robots['status'] or robots['error']}) - treated as disallow all"

    baseline = fetch(url, BROWSER_UA)
    mp = MetaParser()
    try:
        mp.feed(baseline["body"].decode("utf-8", "replace"))
    except Exception:
        pass

    policy_files = {}
    for f in ("/llms.txt", "/ai.txt"):
        r = fetch(origin + f, BROWSER_UA, max_bytes=2048)
        ctype = next((v for k, v in r["headers"].items() if k.lower() == "content-type"), "")
        is_html = "html" in ctype.lower() or r["body"][:200].lstrip().lower().startswith((b"<!doctype", b"<html"))
        policy_files[f] = "present" if r["status"] == 200 and not is_html else "absent"

    probes: dict[str, dict] = {}
    if probe:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {tok: ex.submit(fetch, url, ua) for tok, _, _, ua in BOTS if ua}
            probes = {tok: f.result() for tok, f in futs.items()}

    scan_pages: list[str] = []
    sitemaps_read: list[str] = []
    if scan:
        scan_pages, sitemaps_read = collect_sitemap_urls(sitemaps or [origin + "/sitemap.xml"], scan)

    rows = []
    for tok, op, purpose, ua in BOTS:
        verdict, grp = robots_verdict(groups, tok, path)
        http = "n/a (token only)" if not ua else ("skipped" if not probe else classify(probes[tok], baseline))
        rows.append({
            "bot": tok, "operator": op, "purpose": purpose,
            "robots_txt": verdict, "robots_group": grp,
            "http_probe": http,
            "page_directives": directives_for(tok, baseline["headers"], mp.metas),
            "rules": rules_for(groups, tok),
            "policy": "deny" if tok in DENY else "allow",
            "policy_reason": DENY.get(tok, ""),
        })
        if scan_pages:
            blocked = [u for u in scan_pages if robots_verdict(groups, tok, _path_of(u))[0] == "blocked"]
            rows[-1]["site_allowed"] = len(scan_pages) - len(blocked)
            rows[-1]["site_blocked_sample"] = blocked[:10]

    return {
        "url": url,
        "robots_txt": robots_state,
        "baseline_status": baseline["status"] or baseline["error"],
        "policy_files": policy_files,
        "sitemaps": sitemaps,
        "sitemaps_read": len(sitemaps_read),
        "pages_scanned": len(scan_pages),
        "bots": rows,
        "deny_not_blocked": [r["bot"] for r in rows if r["policy"] == "deny" and not fully_blocked(r, len(scan_pages))],
    }


def print_table(rep: dict) -> None:
    print(f"URL:        {rep['url']}")
    print(f"robots.txt: {rep['robots_txt']}")
    print(f"Browser:    {rep['baseline_status']}")
    print("Files:      " + ", ".join(f"{k} {v}" for k, v in rep["policy_files"].items()))
    print()
    if rep["pages_scanned"]:
        print(f"Site scan:  {rep['pages_scanned']} sitemap URLs from {rep['sitemaps_read']} sitemap(s)")
    hdr = ("BOT", "OPERATOR", "PURPOSE", "POLICY", "ROBOTS.TXT", "HTTP PROBE", "DIRECTIVES", "SITE ALLOWED")
    rows = [(r["bot"], r["operator"], r["purpose"], r["policy"],
             r["robots_txt"] + ("" if r["robots_group"] in (r["bot"], "no matching group") else f" [{r['robots_group']}]"),
             r["http_probe"], ",".join(r["page_directives"]) or "-",
             f"{r['site_allowed']}/{rep['pages_scanned']}" if "site_allowed" in r else "-") for r in rep["bots"]]
    w = [max(len(str(x[i])) for x in rows + [hdr]) for i in range(len(hdr))]
    for row in [hdr] + rows:
        print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(row)))
    print()
    print("ROBOTS.TXT [*] = no bot-specific group; the wildcard group applied.")
    print("HTTP PROBE tests User-Agent based blocking only. IP-verified blocks (e.g. Cloudflare) are not detectable this way.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Check which AI crawlers can access a URL.")
    ap.add_argument("url")
    ap.add_argument("--json", action="store_true", help="output JSON")
    ap.add_argument("--no-probe", action="store_true", help="skip per-bot HTTP requests")
    ap.add_argument("--scan", type=int, default=0, metavar="N", help="also check N URLs from the site's sitemaps")
    a = ap.parse_args()
    rep = run(a.url, probe=not a.no_probe, scan=a.scan)
    if not a.json and rep["deny_not_blocked"]:
        print_table(rep)
        print("\nPOLICY: these denied bots are NOT fully blocked: " + ", ".join(rep["deny_not_blocked"]))
        print("Add to robots.txt (and block the same User-Agents at the CDN/firewall, since some ignore robots.txt):\n")
        print(deny_robots_snippet(rep["deny_not_blocked"]))
        return 0
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        print_table(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
