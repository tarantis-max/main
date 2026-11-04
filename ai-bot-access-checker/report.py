#!/usr/bin/env python3
"""Executive report: turns bot-access + readiness crawl data into a printable HTML report.

Web app: "Executive report" button on the Site Readiness tab (after a crawl).
CLI:     python3 report.py https://www.methodist.edu --max 500 --out report.html
Standard library only. Save as PDF with the browser's Print dialog.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import threading
from html import escape as e
from urllib.parse import urlsplit

from ai_bot_check import deny_robots_snippet, fully_blocked
from readiness import NOT_KEY_PATH, MESSAGES, CHECKS, CATEGORY, Crawl

LABEL = {c[0]: c[1] for c in CHECKS}
CRITICAL = {c[0] for c in CHECKS if c[3]}

# check id -> (why it matters, what to do, owner)
ISSUES = {
    "http_ok": ("Broken or erroring pages cannot be read or cited.", "Fix or redirect every page that does not return HTTP 200, and update links pointing to it.", "Web team"),
    "ai_search_allowed": ("Blocked pages cannot appear in ChatGPT, Claude, Perplexity or Copilot answers.", "Remove robots.txt rules that block AI search and user-fetch bots from these pages.", "Web team"),
    "indexable": ("noindex or noai tags tell AI systems not to use the page.", "Remove noindex, none, noai and noimageai from pages that should be found.", "Web team"),
    "server_text": ("Most AI crawlers do not run JavaScript, so they see these pages as nearly empty.", "Render the main page content in the HTML the server sends (server-side rendering), not only through JavaScript.", "Web team"),
    "title": ("The title is the main label AI systems show and match on.", "Keep every title 10-70 characters. Most failures are too long: the \" | Methodist University\" ending uses 23 characters, so keep the page part under 47. (Duplicate titles are a separate action.)", "Content owners"),
    "meta_desc": ("The description is often used as the summary of the page.", "Write a unique 50-160 character description for every page.", "Content owners"),
    "one_h1": ("A single main heading tells AI systems what the page is about.", "Use exactly one H1 per page.", "Content owners"),
    "headings": ("Sections with subheadings are easier to extract and quote accurately.", "Break content into sections with H2 subheadings.", "Content owners"),
    "canonical": ("Without a canonical URL, duplicate versions of a page compete with each other.", "Add a canonical link to every page in the site template.", "Web team"),
    "structured_data": ("Structured data states facts (programs, events, contacts) in a form machines read reliably.", "Add schema.org JSON-LD to page templates (organization, programs, events, breadcrumbs).", "Web team"),
    "schema_valid": ("Invalid structured data is ignored entirely.", "Fix the JSON-LD errors on the listed pages.", "Web team"),
    "official_name": ("Pages that never state the official name are harder to attribute to the school.", "Include the official name in page titles or site name tags (template change).", "Web team"),
    "no_former_name": ("The former name can cause AI answers to use an outdated identity.", "Replace the former name on current pages. Keep it only on history pages.", "Content owners"),
    "current_dates": ("Pages naming past terms get cited as current, producing wrong answers about dates and costs.", "Update or retire pages that name past academic years or terms.", "Content owners"),
    "lang": ("The language attribute helps AI systems process the page correctly.", "Set the lang attribute in the site template.", "Web team"),
    "open_graph": ("Open Graph tags supply the title and summary when a page is shared or previewed.", "Add og:title and og:description to the site template.", "Web team"),
    "img_alt": ("Images without alt text are invisible to AI systems and to screen readers.", "Add descriptive alt text to images.", "Content owners"),
    "freshness": ("Without a date signal, AI systems cannot tell whether information is current.", "Send a Last-Modified header or add dateModified to page structured data.", "Web team"),
    "fast": ("Slow pages may time out for crawlers.", "Improve server response time to under 2 seconds.", "Web team"),
    "mobile_viewport": ("Search engines rank and display the mobile version of pages first.", "Add <meta name=viewport content=\"width=device-width, initial-scale=1\"> to the template.", "Web team"),
    "clean_url": ("Short, readable URLs are easier for people and machines to understand and share.", "Use lowercase, hyphenated URLs without query strings for public pages; redirect old forms.", "Web team"),
    "readable": ("Plain language is easier for students to read and for AI to quote accurately.", "Rewrite paragraph text to grade 12 or below: shorter sentences, everyday words.", "Content owners"),
    "question_headings": ("AI answers and featured snippets favor content that answers the questions students ask.", "Add question-style subheadings or an FAQ section (with FAQPage schema) to admissions, cost, aid and program pages.", "Content owners"),
    "program_schema": ("Program schema tells search engines and AI the degree, length, cost and format of each program.", "Add EducationalOccupationalProgram schema to the program page template.", "Web team"),
}

PRIORITY_RE = re.compile(
    r"admission|apply|tuition|cost|financial[-_]?aid|scholarship|academics?|programs?|majors?|degrees?|"
    r"deadline|calendar|visit|contact|about|graduate|undergraduate", re.I)


def _pct(a: int, b: int) -> int:
    return round(100 * a / b) if b else 0


def _grade_pill(g: str) -> str:
    cls = {"Ready": "ok", "Needs work": "warn", "Not ready": "bad"}.get(g, "")
    return f'<span class="pill {cls}">{e(g)}</span>'


def build(summary: dict, pages: list[dict], pdfs: list[dict], access: dict | None, answers: dict | None = None) -> str:
    s = summary
    n = s["pages"]
    g = s["grades"]
    host = urlsplit(s["start"]).netloc
    d = dt.date.today()
    today = f"{d:%B} {d.day}, {d.year}"
    org = s.get("organization") or {"passed": 0, "total": 0, "rows": [], "snippet": ""}
    org_ok = org["total"] > 0 and org["passed"] == org["total"]

    # ---- bot access
    bots = (access or {}).get("bots", [])
    scanned = (access or {}).get("pages_scanned", 0)

    def blocked(b):
        return (b["robots_txt"] == "blocked" or (scanned and b.get("site_allowed", 1) == 0)
                or str(b["http_probe"]).startswith(("blocked", "challenged")))

    def partial(b):
        return scanned and 0 < b.get("site_allowed", scanned) < scanned

    denied = [b for b in bots if b.get("policy") == "deny"]
    search = [b for b in bots if b["purpose"] in ("search", "user") and b.get("policy") != "deny"]
    training = [b for b in bots if b["purpose"] == "training" and b.get("policy") != "deny"]
    deny_open = [b for b in denied if not fully_blocked(b, scanned)]
    search_blocked = [b for b in search if blocked(b)]
    training_blocked = [b for b in training if blocked(b)]
    search_partial = [b for b in search if not blocked(b) and partial(b)]

    # ---- priority pages
    # by address; news, events and filtered (?query) copies are not key pages
    key_all = [p for p in pages if p["url"].rstrip("/") == s["start"].rstrip("/")
               or (PRIORITY_RE.search(urlsplit(p["url"]).path) and not NOT_KEY_PATH.search(urlsplit(p["url"]).path) and not urlsplit(p["url"]).query)]
    prio = [p for p in key_all if p["status"] == 200]  # a broken address is a broken link (Site-level findings), not a page to grade
    key_broken = len(key_all) - len(prio)
    prio.sort(key=lambda p: (p["score"], p["url"]))
    prio_ready = sum(1 for p in prio if p["grade"] == "Ready")

    # ---- verdict (fixed rules, stated in the report)
    pct_ready = _pct(g["Ready"], n)
    if pct_ready >= 80 and not search_blocked and org_ok:
        verdict, vcls = "Ready", "ok"
    elif pct_ready >= 50 and not search_blocked:
        verdict, vcls = "Partially ready", "warn"
    else:
        verdict, vcls = "Not ready", "bad"

    # ---- key findings
    findings, other = [], []
    if access:
        if search_blocked:
            findings.append(f"<b>{len(search_blocked)} of {len(search)} AI search and answer bots are blocked</b>: "
                            + e(", ".join(b["bot"] for b in search_blocked)) + ". These pages cannot appear in their answers.")
        else:
            findings.append(f"<b>All {len(search)} AI search and answer bots can reach the site</b> (ChatGPT, Claude, Perplexity, Copilot and others).")
        if search_partial:
            other.append(f"{len(search_partial)} AI search bots are blocked from part of the site by robots.txt.")
        other.append(f"{len(training_blocked)} of {len(training)} AI training bots are blocked. This is a policy choice, not a readiness defect.")
        if denied:
            if deny_open:
                findings.append(f"<b>Policy: {len(deny_open)} of {len(denied)} denied bots are not fully blocked</b>: "
                                + e(", ".join(b["bot"] for b in deny_open)) + ".")
            else:
                other.append(f"Policy: all {len(denied)} denied bots are fully blocked.")
    else:
        findings.append("Bot access was not checked.")
    findings.append(f"<b>{pct_ready}% of {n} pages are Ready</b> for AI search. {g['Needs work']} need work and {g['Not ready']} are not ready.")
    # Deliberate exclusions are not defects: a host that is entirely blocked or noindexed (an internal system), and a
    # section where every page is noindexed (reported once, under "Confirm noindex sections are intended").
    live = [p for p in pages if p["status"] == 200]
    by_host: dict = {}
    for p in live:
        by_host.setdefault(urlsplit(p["url"]).netloc.lower(), []).append(p)
    private_hosts = sorted(h for h, ps in by_host.items() if h != urlsplit(s["start"]).netloc.lower()
                           and all(p["checks"].get("ai_search_allowed") is False or p["checks"].get("indexable") is False for p in ps))
    nsec = {x["section"] for x in (s.get("site_issues") or {}).get("noindex_sections", [])}

    def _section(u):
        sp = urlsplit(u)
        parts = [x for x in sp.path.split("/") if x]
        return sp.netloc.lower() + "/" + (parts[0] + "/" if parts else "")

    deliberate = {p["url"] for p in live if urlsplit(p["url"]).netloc.lower() in private_hosts or _section(p["url"]) in nsec}
    adj = []
    for c in s["check_failures"]:
        if c["id"] in ("indexable", "ai_search_allowed") and deliberate:
            real = sum(1 for p in live if p["checks"].get(c["id"]) is False and p["url"] not in deliberate)
            c = {**c, "failed": real, "pct": round(100 * real / max(1, n))}
        adj.append(c)
    fails = sorted((c for c in adj if c["failed"]), key=lambda c: (-c["critical"], -c["failed"]))
    crit = [c for c in fails if c["critical"]]
    if crit:
        findings.append("Critical issues: " + "; ".join(f"{e(c['label'])} on {c['failed']} page(s)" for c in crit) + ".")
    if private_hosts:
        other.append("Blocked or noindexed on purpose, not counted as problems: " + ", ".join(
            f"<b>{e(h)}</b> ({len(by_host[h])} page(s), appears to be an internal system)" for h in private_hosts) + ".")
    top = sorted(fails, key=lambda c: -c["failed"])[:1]
    if top:
        other.append(f"Most common issue: <b>{e(top[0]['label'])}</b>, failing on {top[0]['pct']}% of pages.")
    sd_state = s.get("schema_state", "")
    if sd_state == "invalid":
        findings.append("<b>The site's official identity data is broken on every page.</b> The structured data in a shared template "
                        "has syntax errors, so search engines and AI ignore it. Low-to-moderate impact; about one hour to fix.")
    elif sd_state == "missing":
        findings.append("<b>The site has no structured data.</b> Search engines and AI get no machine-readable statement of the "
                        "school's official name, address, logo or accounts. Low-to-moderate impact; about one hour to fix.")
    if prio:
        findings.append(f"<b>{prio_ready} of {len(prio)} key student pages</b> (admissions, tuition, aid, programs, contact) are Ready.")
    other.append(f"Homepage organization schema: <b>{org['passed']} of {org['total']}</b> checks pass." if org["total"] else "Homepage organization schema was not checked.")
    pc = s["pdf_counts"]
    if pc["total"]:
        findings.append(f"{pc['total']} PDFs are linked. {pc['key_facts']} hold key facts that AI crawlers may not read; {pc['past_terms']} name past terms.")

    si = s.get("site_issues") or {}
    ppr, msr, inr = s.get("priority_pages") or {}, s.get("messages") or {}, s.get("inventory") or {}
    an = answers or {}
    if an.get("done"):
        nm = e(s['settings']['official_name'] or 'the school')
        if an.get("broad_mention") is not None:
            bm = next(iter((an.get("benchmarks") or {}).values()), {})
            vs = (f" (EAB, Oct. 19: {bm['brand_mention_peer_set']}% mention, {bm['citation_share']}% citation share)" if bm else "")
            findings.append(f"<b>AI answers ({e(an['date'])}): {nm} is named in {an['broad_mention']}% of broad questions</b> and holds "
                            f"{an.get('citation_share_broad') if an.get('citation_share_broad') is not None else '-'}% of their cited sources{vs}. "
                            f"Branded questions: {an['branded_mention']}% mention, {an['accuracy'] if an['accuracy'] is not None else '-'}% accurate. "
                            f"Niche questions (few right answers): {an.get('niche_mention', '-')}%.")
        else:
            findings.append(f"<b>AI answers ({e(an['date'])}):</b> {e(str(an['branded_mention']))}% of branded questions and "
                            f"<b>{e(str(an['category_mention']))}% of category questions</b> mention {nm}; "
                            f"{e(str(an['citation_rate']))}% of answers cite the site; {an['confusions']} answer(s) confused it with another school.")
    if ppr.get("total"):
        findings.append(f"<b>{ppr['optimized']} of {ppr['total']} priority pages meet all five elements</b> of EAB's priority-page standard "
                        "(direct answer, proof, connections, authority, structure).")
    conflicts = [x for x in msr.get("claims", []) if x["found"] and not x["consistent"]]
    if conflicts or any(b["pages"] for b in msr.get("banned", [])):
        parts = []
        if conflicts:
            parts.append(f"{len(conflicts)} number(s) conflict with approved figures ("
                         + "; ".join(f"{e(x['label'])}: approved {x['approved']}, site also says "
                                     + ", ".join(str(v['value']) for v in x['values'] if v['value'] != x['approved']) for x in conflicts[:3]) + ")")
        nb = [b for b in msr.get("banned", []) if b["pages"]]
        if nb:
            parts.append("off-brand phrases on the site: " + ", ".join(f"\"{e(b['phrase'])}\" ({b['pages']} page(s))" for b in nb))
        findings.append("<b>Message consistency:</b> " + "; ".join(parts) + ".")
    legacy = si.get("legacy_hosts", [])
    if legacy:
        findings.append("<b>Old or staging site is publicly reachable</b>: " + e(", ".join(h["host"] for h in legacy))
                        + ". Search engines and AI can index and cite outdated pages from it.")
    for sec in si.get("noindex_sections", []):
        other.append(f"Section <b>{e(sec['section'])}</b>: {sec['noindex']} of {sec['pages']} pages are marked noindex, so search engines and AI skip them.")
    for h in si.get("hosting_links", [])[:3]:
        other.append(f"{h['links']} links point to the hosting provider's domain <b>{e(h['host'])}</b> instead of the school's domain.")
    wpo = si.get("wordpress", {})
    if wpo.get("available"):
        other.append(f"WordPress lists {wpo.get('published', 0)} published pages and posts and {wpo.get('media', 0)} media files. "
                     f"{wpo.get('not_in_sitemap', 0)} published page(s) are missing from the sitemap; {wpo.get('hidden', 0)} of those have no links either.")
        for x in wpo.get("file_redirect_sample", [])[:5]:
            other.append(f"<b>{e(urlsplit(x['url']).path)}</b> opens a file ({e((x.get('goes_to') or x.get('file') or '').rsplit('/', 1)[-1])}) "
                         f"but looks like a former version of <b>{e(x['page'])}</b>.")
    elif wpo.get("checked"):
        other.append("WordPress page list not checked (" + e(wpo.get("note") or "not available") + "): pages with no links and no sitemap entry cannot be found.")
    if si.get("former_name_pages"):
        other.append(f"{si['former_name_pages']} pages mention a former name. Review list only (not scored): history pages and bios are expected.")

    # ---- actions (ranked: bot access, critical, then by pages affected)
    actions = []
    if deny_open:
        actions.append(("Block policy-denied bots", f"{len(deny_open)} denied bots can still crawl: {', '.join(b['bot'] for b in deny_open)}.",
                        "Add the robots.txt group in Appendix D, and block the same User-Agents at the CDN/firewall, because some of these bots ignore robots.txt.",
                        "Web team", "Site-wide"))
    if legacy:
        actions.append(("Retire or block the old/staging site", "Outdated copies of pages can be indexed and cited as current.",
                        "Shut it down, password-protect it, or redirect it to the live site; then remove it from search consoles.",
                        "Web team", ", ".join(h["host"] for h in legacy)))
    if search_blocked:
        actions.append(("Unblock AI search and answer bots", f"{len(search_blocked)} bots blocked: {', '.join(b['bot'] for b in search_blocked)}.",
                        "Remove the robots.txt rules or firewall/CDN rules that block them.", "Web team", "Site-wide"))
    if sd_state:
        sd_fail = next((c for c in s["check_failures"] if c["id"] == ("schema_valid" if sd_state == "invalid" else "structured_data")), {"failed": n})
        actions.append(("Fix broken structured data in the site template" if sd_state == "invalid" else "Add structured data to the site template",
                        "Search engines and AI cannot confirm the school's official name, address, logo and accounts from the site.",
                        ("Replace the broken JSON-LD block in the shared template with the corrected snippet (app: Site Readiness tab, Structured data card), "
                         "fix the empty site-address variable, validate the homepage at validator.schema.org, re-run this crawl."
                         if sd_state == "invalid" else
                         "Add the corrected snippet (app: Site Readiness tab, Structured data card) to the shared header template or enable organization "
                         "schema in an SEO plugin, validate at validator.schema.org, re-run this crawl."),
                        "Web team", f"{sd_fail['failed']} page(s), ~1 hour"))
    skip_ids = {"schema_valid", "structured_data"} if sd_state else set()
    merged_broken = False
    for c in [c for c in fails if c["id"] not in skip_ids][:6]:
        why, fix, owner = ISSUES[c["id"]]
        if c["id"] == "http_ok":  # one action for broken pages and the links to them
            merged_broken = True
            actions.append(("Critical: Fix broken pages and the links to them",
                            "Links to missing or failing pages send students and AI to dead ends and waste crawl budget.",
                            "Fix or redirect each page that does not load, and update the links pointing to it. Each broken page and the page "
                            "linking to it are listed in Site-level findings and in the Pages CSV (linked_from column).",
                            "Web team + Content owners", f"{c['failed']} page(s)"))
            continue
        actions.append((("Critical: " if c["critical"] else "") + c["label"], why, fix, owner, f"{c['failed']} page(s), {c['pct']}%"))
    if org["total"] and not org_ok and not sd_state:
        actions.append(("Fix homepage organization schema", "AI systems use it to identify the school correctly.",
                        "Paste the generated snippet (app: Site Readiness tab, Structured data card) into the homepage after replacing every REPLACE-WITH value.", "Web team", "Homepage"))
    if ppr.get("total") and ppr["optimized"] < ppr["total"]:
        ep = ppr.get("element_pass", {})
        weakest = sorted(ppr.get("elements", []), key=lambda x: ep.get(x["id"], 0))[:2]
        actions.insert(min(3, len(actions)), ("Renovate the priority pages",
                        "These pages answer the questions MU most needs to win in search and AI; EAB found only 20 of 187 pages optimized.",
                        "Bring each priority page to all five elements (Appendix F). Weakest: "
                        + ", ".join(f"{x['label']} ({ep.get(x['id'], 0)} of {ppr['total']} pass)" for x in weakest) + ".",
                        "Content owners + Web team", f"{ppr['total'] - ppr['optimized']} of {ppr['total']} page(s)"))
    if conflicts:
        actions.append(("Use one set of approved numbers", "Conflicting figures undercut credibility, and AI may repeat the wrong one.",
                        "Update every page to the approved figure in messages.json; pages are listed in Appendix G.", "Marketing",
                        f"{sum(x['off_pages'] for x in conflicts)} page(s)"))
    nb = [b for b in msr.get("banned", []) if b["pages"]]
    if nb:
        actions.append(("Remove off-brand phrases", "The message guide bars these phrases.", "Rewrite the pages listed in Appendix G.",
                        "Marketing", f"{sum(b['pages'] for b in nb)} page(s)"))
    od = [x for x in msr.get("outdated", []) if x["pages"] or x["news"]]
    od_live = [x for x in od if x["pages"]]
    od_news = [x for x in od if x["news"] and not x.get("template")]
    pos = min(3, len(actions))
    for ma in MESSAGES.get("manual_actions", []):
        row = (ma["title"], ma["why"], ma["fix"], ma["owner"], ma.get("scope", ""))
        if ma.get("priority") == "high":
            actions.insert(pos, row)
            pos += 1
        else:
            actions.append(row)
    tmpl = [x for x in od if x.get("template")]
    if tmpl:
        actions.insert(pos, ("Fix outdated wording in the site template",
                        "These appear on nearly every page: " + "; ".join(x["phrase"] for x in tmpl) + ".",
                        "Change the shared header/footer: " + "; ".join(f"{x['phrase']} -> {x['use_instead']}" for x in tmpl) + ".",
                        "Web team", "Site-wide"))
        pos += 1
    od_live = [x for x in od_live if not x.get("template")]
    if od_live:
        actions.insert(pos, ("Update outdated wording",
                        "Out-of-date facts on live pages get repeated by AI as current: " + "; ".join(f"{x['phrase']} ({x['pages']})" for x in od_live[:5]) + ".",
                        "Replace each with the current wording in Appendix G (\"Use instead\"). Pages are listed there.",
                        "Content owners", f"{sum(x['pages'] for x in od_live)} page(s)"))
    if od_news:
        actions.append(("Add update notes to dated news posts",
                        "Older posts are accurate for their date, but AI quotes them as current.",
                        "Add a one-line \"Update:\" note at the top of each post with today's fact; do not rewrite the post. Posts are listed in Appendix G.",
                        "Marketing", f"{sum(x['news'] for x in od_news)} post(s)"))
    inv_fail = [r for r in inr.get("rows", []) if not r["pass"]]
    if inv_fail:
        actions.append(("Close content gaps", "Students look for cost, outcomes and a virtual visit before they inquire.",
                        "Add: " + "; ".join(r["label"] for r in inv_fail) + ".", "Marketing + Web team", f"{len(inv_fail)} gap(s)"))
    smap, orph, bl = si.get("sitemap", {}), si.get("orphans", {}), si.get("broken_internal_links", {})
    dt_, dd_ = si.get("duplicate_titles", {}), si.get("duplicate_descriptions", {})
    if bl.get("count") and not merged_broken:
        actions.append(("Fix broken internal links", "Links to missing pages waste crawl budget and send students and AI to dead ends.",
                        "Update or remove links to the pages listed in Site-level findings (each shows where it is linked from).", "Web team", f"{bl['count']} broken page(s)"))
    dlg = si.get("dead_legacy_links", [])
    if dlg:
        targets = "; ".join("%s (linked from %s)" % (urlsplit(x["url"]).path + ("?" + urlsplit(x["url"]).query if urlsplit(x["url"]).query else ""),
                                                      ", ".join(urlsplit(u).path for u in x["linked_from"][:2]) or "unknown") for x in dlg[:5])
        actions.append(("Remove links to the retired old site",
                        urlsplit(dlg[0]["url"]).netloc + " no longer exists, but pages still link to it. Visitors and crawlers hit a dead end.",
                        "Point each link to the current page on the main site: " + targets + ".",
                        "Content owners", f"{len(dlg)} link target(s)"))
    if smap.get("broken") or smap.get("noindex"):
        actions.append(("Clean the XML sitemap", "Sitemaps should list only live, indexable pages.",
                        "Remove broken and noindex URLs from the sitemap.", "Web team", f"{smap.get('broken', 0)} broken, {smap.get('noindex', 0)} noindex"))
    if smap.get("urls") and smap.get("pages_not_in_sitemap"):
        actions.append(("Add missing pages to the sitemap", "Pages missing from the sitemap are found later, or not at all.",
                        "Make sure the sitemap generator includes every public, indexable page.", "Web team", f"{smap['pages_not_in_sitemap']} page(s)"))
    fq = si.get("indexable_query_urls", {})
    if fq.get("count"):
        actions.append(("Stop indexing of filter URLs", "Filtered list pages (e.g. ?category=, ?department=) are near-duplicates that compete with real pages and waste crawl budget.",
                        "Add noindex, or a canonical tag pointing to the unfiltered page, on filtered list URLs; keep them out of the sitemap.", "Web team",
                        f"{fq['count']} URL(s)"))
    wpi = si.get("wordpress", {})
    if wpi.get("file_redirects"):
        actions.append(("Redirect former page addresses that now open a file",
                        "These addresses were probably pages once (a \"-2\" version of a live page). Search results and AI may still show the old page text; clicking opens an image or PDF.",
                        "301-redirect each to the live page it duplicates (shown in Site-level findings), not to the file; request a recrawl in Google Search Console.",
                        "Web team", f"{wpi['file_redirects']} address(es)"))
    if wpi.get("hidden"):
        actions.append(("Link, redirect or unpublish hidden WordPress pages",
                        "Published pages with no links and no sitemap entry go stale unnoticed, and search engines that already know them keep showing them.",
                        "For each page: link it from its section and add it to the sitemap, or redirect it to its replacement, or unpublish it.",
                        "Content owners + Web team", f"{wpi['hidden']} page(s)"))
    if orph.get("count"):
        actions.append(("Link to orphan pages", "Pages with no internal links get little authority and are hard for crawlers to reach.",
                        "Link to each orphan page from its parent section, or retire it.", "Content owners", f"{orph['count']} page(s)"))
    if dt_.get("pages") or dd_.get("pages"):
        actions.append(("Make titles and descriptions unique", "Duplicates make pages compete with each other in search.",
                        "Give each page its own title and meta description.", "Content owners", f"{dt_.get('pages', 0)} titles, {dd_.get('pages', 0)} descriptions"))
    if si.get("hosting_links"):
        actions.append(("Replace hosting-provider links", "Search engines and AI may cite the provider's domain instead of the school's.",
                        "Rewrite links (often PDFs) from the hosting domain to the school's domain; redirect the hosting domain.", "Web team",
                        f"{sum(h['links'] for h in si['hosting_links'])} link(s)"))
    if si.get("noindex_sections"):
        actions.append(("Confirm noindex sections are intended", "Noindexed sections never appear in search or AI answers.",
                        "Decide per section; remove noindex where students should find the content (e.g. events).", "Marketing",
                        ", ".join(x["section"].split("/", 1)[1] or "/" for x in si["noindex_sections"][:3])))
    if pc["key_facts"]:
        actions.append(("Move key facts out of PDFs", "Most AI crawlers read PDFs poorly or not at all.",
                        "Publish tuition, aid, deadline, requirement and catalog facts as web page text.", "Content owners", f"{pc['key_facts']} PDF(s)"))
    if pc["past_terms"]:
        actions.append(("Update or label outdated PDFs", "Outdated PDFs get cited as current.",
                        "Update, replace or unlink PDFs that name past terms (maps, calendars, brochures). Keep historical records "
                        "(graduation rates, enrollment, degrees awarded) but label them as historical in the link text and page.",
                        "Content owners", f"{pc['past_terms']} PDF(s)"))

    def bot_row(b):
        st = "Blocked" if blocked(b) else ("Partly blocked" if partial(b) else "Allowed")
        cls = {"Blocked": "bad", "Partly blocked": "warn", "Allowed": "ok"}[st]
        cov = f"{_pct(b['site_allowed'], scanned)}%" if scanned and "site_allowed" in b else "-"
        return (f"<tr><td>{e(b['bot'])}</td><td>{e(b['operator'])}</td><td>{e(b['purpose'])}</td>"
                f"<td><span class='pill {cls}'>{st}</span></td><td>{cov}</td><td>{e(b['http_probe'])}</td></tr>")

    # ---- HTML row helpers (kept out of the template for Python 3.9 compatibility)
    def fail_pills(p):
        out = "".join('<span class="pill %s">%s</span>' % ("bad" if f in CRITICAL else "warn", e(LABEL[f])) for f in p["failed"])
        return out or "none"

    def prio_row(p):
        crit = [LABEL[f] for f in p["failed"] if f in CRITICAL]
        txt = "%d failed" % len(p["failed"]) if p["failed"] else "none"
        if crit:
            txt += ' · <span class="crit">critical: %s</span>' % e(", ".join(crit))
        return "<tr><td>%d</td><td>%s</td><td class='url'>%s</td><td>%s</td></tr>" % (
            p["score"], _grade_pill(p["grade"]), e(urlsplit(p["url"]).path or "/"), txt)

    def check_row(c):
        crit_tag = ' <span class="crit">(critical)</span>' if c["critical"] else ""
        return "<tr class='sm'><td class='nw'><b>%s</b>%s</td><td>%s</td><td class='nw'>%d (%d%%)</td></tr>" % (e(c["label"]), crit_tag, e(c["rule"]), c["failed"], c["pct"])

    def org_row(r):
        cls, txt = ("ok", "pass") if r["pass"] else ("bad", "fail")
        return "<tr><td>%s</td><td><span class='pill %s'>%s</span></td><td class='url'>%s</td></tr>" % (e(r["label"]), cls, txt, e(r["found"]))

    def pdf_row(p):
        return "<tr><td class='url'>%s</td><td>%s</td><td>%s</td><td>%d page(s)</td></tr>" % (
            e(urlsplit(p["url"]).path.split("/")[-1]), e(", ".join(p["topics"])) or "-", e(", ".join(p["past_terms"])) or "-", p["linked_from_count"])

    def action_row(i, a):
        return "<tr><td>%d</td><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % ((i,) + tuple(e(x) for x in a))

    prio_html = "".join(prio_row(p) for p in prio[:10]) or '<tr><td colspan="4">No key student pages found in this crawl.</td></tr>'
    key_broken_note = (f" {key_broken} more key-page addresses are broken links (not found or server error); they are listed under Site-level findings, with the page that links to each." if key_broken else "")
    checks_html = "".join(check_row(c) for c in s["check_failures"])
    org_html = "".join(org_row(r) for r in org["rows"] if not r["pass"]) or '<tr><td colspan="3">All checks pass.</td></tr>'
    pdf_html = "".join(pdf_row(p) for p in [x for x in pdfs if x["topics"] or x["past_terms"]][:10]) or '<tr><td colspan="4">None flagged.</td></tr>'
    def exec_row(i, a):
        act, why, _fix, owner, scope = a
        return "<tr><td>%d</td><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (i, e(act), e(why), e(owner), e(scope))

    actions_html = "".join(exec_row(i, a) for i, a in enumerate(actions[:5], 1)) or '<tr><td colspan="5">No actions needed.</td></tr>'
    more_note = ('<p class="note">%d more action(s) and the steps for each are in the Action plan.</p>' % (len(actions) - 5)) if len(actions) > 5 else (
        '<p class="note">Steps for each action are in the Action plan.</p>' if actions else "")
    more_actions_html = ""
    if actions:
        more_actions_html = ('<h2>Action plan</h2><table><thead><tr><th>#</th><th>Action</th><th>What to do</th>'
                             '<th>Owner</th><th>Scope</th></tr></thead><tbody>%s</tbody></table>'
                             % "".join("<tr><td>%d</td><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (i, e(a[0]), e(a[2]), e(a[3]), e(a[4]))
                                       for i, a in enumerate(actions, 1)))
    if other:
        more_actions_html += '<h2>Other findings</h2><ul class="f">%s</ul>' % "".join("<li>%s</li>" % x for x in other)
    findings_html = "".join("<li>%s</li>" % x for x in findings)
    snippet_html = ('<p class="note">A ready-to-paste fix is generated on the Site Readiness tab of the app (Structured data card).</p>') if org["total"] and not org_ok else ""
    deny_appendix = ""
    if deny_open:
        deny_appendix = ('<h2>Appendix D: Block denied bots</h2><p class="note">Add to robots.txt. Also block these User-Agents at the CDN or firewall, '
                         'because robots.txt is voluntary.</p><pre>%s</pre>' % e(deny_robots_snippet([b["bot"] for b in deny_open])))
        deny_appendix += '<p class="note"><b>Reasons:</b> %s.</p>' % "; ".join("%s: %s" % (e(b["bot"]), e(b.get("policy_reason", ""))) for b in deny_open)
    sd_html = ""
    if s.get("schema_explainer"):
        sd_html = ('<h2>About the structured data issue</h2>' + "".join("<p>%s</p>" % e(x) for x in s["schema_explainer"])
                   + '<p class="note"><b>How to verify:</b> (1) validator.schema.org on the homepage shows one CollegeOrUniversity item with no errors; '
                     '(2) Google Search Console, Enhancements, shows no "Unparsable structured data" errors after Google recrawls; '
                     '(3) this crawl shows "Valid structured data" passing on every page and 8 of 8 homepage organization checks.</p>')
    org_passed_txt = "%d of %d checks pass." % (org["passed"], org["total"])
    skipped_txt = ", ".join("%s (%d)" % (k, v) for k, v in s["skipped"].items()) or "none"
    stopped_txt = "crawl stopped early; " if s["state"] == "stopped" else ""
    # ---- Appendix F/G/H: priority pages, messages, inventory
    def fmt_vals(x):
        return ", ".join("%s (%d)" % (v["value"], v["pages"]) for v in x["values"])

    def outdated_row(x):
        snip = ('<br><span class="note">"...' + e(x["snippet"][:140]) + '..."</span>') if x["snippet"] else ""
        where = ", ".join(urlsplit(u).path for u in (x["sample"] + x["news_sample"])[:8]) or "-"
        return "<tr><td>%s%s</td><td>%s</td><td>%d</td><td>%d</td><td class='url'>%s</td></tr>" % (
            e(x["phrase"]) + (" <b>(site template)</b>" if x.get("template") else ""), snip, e(x["use_instead"]), x["pages"], x["news"], e(where))

    ai_html = ""
    tick = lambda b: '<span class="pill ok">pass</span>' if b else '<span class="pill bad">fail</span>'
    brand_html = ""
    if an.get("done"):
        pc_ = lambda v: "-" if v is None else f"{v}%"
        pr = "".join(f"<tr><td>{e(p)}</td><td>{d['answered']}</td><td>{pc_(d['branded_mention'])}</td><td>{pc_(d.get('niche_mention'))}</td><td>{pc_(d.get('broad_mention'))}</td>"
                     f"<td>{pc_(d['cited'])}</td><td>{pc_(d.get('citation_share_broad'))}</td><td>{pc_(d['accurate'])}</td><td>{d['confused']}</td></tr>"
                     for p, d in an.get("by_provider", {}).items())
        sov = ""
        for pname, members in (an.get("peer_sets") or {}).items():
            sov += (f"<p class='note'><b>Share of voice, {e(pname)} (broad questions):</b> "
                    + ", ".join(f"{e(m['college'])} {pc_(m['rate'])}" for m in members) + ".</p>")
        named = an.get("colleges_named") or [{"college": x["peer"], "answers": x["answers"]} for x in an.get("peer_mentions", [])]
        peers = ", ".join(f"{x['college']} ({x['answers']})" for x in named[:10]) or "none"
        srcs = ", ".join(f"{x['host']} ({x['answers']})" for x in an.get("top_sources", [])[:8]) or "none"
        ai_html = ('<h2>Appendix I: AI answer test</h2><p class="note">%s · %d questions, web search on. Branded = names the school; niche = general, few right answers; '
                       'broad = general, many answers. Citation share = the site\'s share of all sources cited. Full answers are in answers.html in the results bundle.</p>'
                       '<table><thead><tr><th>Provider</th><th>Answered</th><th>Branded</th><th>Niche</th><th>Broad</th><th>Cites site</th><th>Citation share (broad)</th><th>Accurate</th><th>Confusions</th></tr></thead><tbody>%s</tbody></table>'
                       '%s<p class="note"><b>Most-named colleges on general questions (answers out of %d):</b> %s. <b>Sources used instead of the site:</b> %s.</p>'
                       % (e(an["date"]), an["questions"], pr, sov, an.get("category_total", 0), e(peers), e(srcs)))
    if ppr.get("total"):
        els = ppr.get("elements", [])
        brand_html += ('<h2>Appendix F: Priority pages (EAB standard)</h2><p class="note">'
                       + " ".join(f"<b>{e(x['label'])}</b>: {e(x['rule'])}" for x in els)
                       + f" Optimized = all five. Site-wide, {ppr.get('key_pages_optimized', 0)} of {ppr.get('key_pages', 0)} key student pages meet all five.</p>"
                       + '<table><thead><tr><th>Page</th>' + "".join(f"<th>{e(x['label'])}</th>" for x in els) + '<th>Score</th></tr></thead><tbody>'
                       + "".join("<tr><td class='url'>%s</td>%s<td>%s</td></tr>" % (
                           e(urlsplit(r["url"]).path or "/"),
                           "".join(f"<td>{tick(r['elements'].get(x['id']))}</td>" for x in els) if r["elements"] else f"<td colspan='{len(els)}'>{e(str(r['status']))}</td>",
                           "-" if r["score"] is None else f"{r['score']}/5") for r in ppr["rows"])
                       + "</tbody></table>")
    if msr.get("proof_points"):
        brand_html += ('<h2>Appendix G: Message consistency</h2><p class="note">Source: messages.json, pre-filled from the MU brand positioning statements.</p>'
                       '<table><thead><tr><th>Approved proof point</th><th>Homepage</th><th>Priority pages</th><th>All pages</th></tr></thead><tbody>'
                       + "".join(f"<tr><td>{e(x['label'])}</td><td>{tick(x['homepage'])}</td><td>{x['priority_pages']} of {ppr.get('total', 0)}</td><td>{x['site_pages']}</td></tr>" for x in msr["proof_points"])
                       + '</tbody></table><table style="margin-top:10px"><thead><tr><th>Number</th><th>Approved</th><th>Found on site (pages)</th><th>Result</th></tr></thead><tbody>'
                       + "".join(f"<tr><td>{e(x['label'])}</td><td>{x['approved']}</td><td>{e(fmt_vals(x)) or 'not stated'}</td><td>{tick(x['consistent']) if x['found'] else '-'}</td></tr>" for x in msr["claims"])
                       + "</tbody></table>"
                       + "".join(f"<p class='note'><b>\"{e(b['phrase'])}\"</b> on {b['pages']} page(s): {e(', '.join(urlsplit(u).path for u in b['sample'][:5]))}</p>" for b in msr.get("banned", []) if b["pages"])
                       + ('<h3 style="font-size:14px;margin:14px 0 6px">Outdated wording</h3><p class="note">Source: messages.json (outdated_phrases). '
                          'Live pages: rewrite. News posts: add an update note.</p>'
                          '<table><thead><tr><th>Outdated</th><th>Use instead</th><th>Live pages</th><th>News posts</th><th>Where</th></tr></thead><tbody>'
                          + "".join(outdated_row(x) for x in msr.get("outdated", []))
                          + "</tbody></table>" if msr.get("outdated") else ""))
    if inr.get("rows"):
        brand_html += ('<h2>Appendix H: Content inventory</h2><table><thead><tr><th>Item</th><th>Result</th><th>Detail</th></tr></thead><tbody>'
                       + "".join(f"<tr><td>{e(r['label'])}</td><td>{tick(r['pass'])}</td><td>{e(r['detail'])}</td></tr>" for r in inr["rows"])
                       + "</tbody></table>")
    coverage = [
        ("Title tags and meta descriptions", "SEO", "Automated: Title, Meta description, unique titles/descriptions"),
        ("Clear headings, simple content", "SEO / AEO", "Automated: Single H1, Subheadings, Readable text"),
        ("Match real search queries (question-style content)", "AEO / GEO", "Automated: Answers questions; Manual: query research in Search Console"),
        ("Keep content fresh", "GEO", "Automated: No past terms, Freshness signal"),
        ("Structured data: Organization", "SEO / GEO", "Automated: homepage organization schema, Valid structured data"),
        ("Structured data: program pages (EducationalOccupationalProgram, Course)", "SEO / GEO", "Automated: Program schema"),
        ("Structured data: FAQPage", "AEO", "Automated: FAQ pages count"),
        ("HowTo schema for application steps", "AEO", "Not checked: Google retired HowTo rich results in 2023"),
        ("Mobile-responsive", "Technical SEO", "Automated: Mobile-friendly"),
        ("Clean, accessible URLs", "Technical SEO", "Automated: Clean URL"),
        ("Site speed", "Technical SEO", "Automated: Response time (server only; full page speed needs PageSpeed Insights)"),
        ("Clear sitemap", "Technical SEO", "Automated: sitemap coverage, broken and noindex sitemap URLs"),
        ("Internal linking / topical authority", "SEO / GEO", "Automated: orphan pages, broken internal links"),
        ("Backlinks", "SEO", "Manual: needs an SEO tool (e.g. Semrush, Ahrefs)"),
        ("Trust signals (privacy, contact info)", "GEO", "Automated: homepage trust checks"),
        ("Accessibility (alt text, language)", "On-page", "Automated: Image alt text, Language"),
        ("AI crawler access", "GEO", "Automated: Bot Access, AI search bots allowed, No noindex/noai"),
        ("Keyword and competitor research", "SEO", "Manual: Search Console, keyword tools; competitor scan compares site readiness"),
        ("Search Console analysis, organic rankings, traffic", "SEO", "Manual: needs Search Console / analytics access"),
        ("AI prompt analysis, AI traffic, indexing across AI platforms", "GEO", "Automated: AI answer test (see Appendix I; mention, citation share, accuracy across Claude, ChatGPT, Perplexity, Gemini); Manual: AI referral traffic in analytics"),
    ]
    coverage_html = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (e(a), e(b), e(c)) for a, b, c in coverage)
    areas = s.get("areas") or []
    def area_cls(v):
        return "ok" if v is not None and v >= 90 else "warn" if v is not None and v >= 70 else "bad"
    areas_html = ('<div class="areas">' + "".join(
        '<div class="area %s"><b>%s</b><span>%s</span></div>' % (area_cls(a["score"]), "-" if a["score"] is None else a["score"], e(a["area"]))
        for a in areas) + '</div><p class="note">Area score = share of applicable page checks passed (90+ green, 70-89 amber, below 70 red). '
        'SEO = Technical + On-page; GEO/AEO = Content + Structured data.</p>') if areas else ""
    # site-level findings table
    def yn(ok):
        return '<span class="pill ok">pass</span>' if ok else '<span class="pill bad">fail</span>'
    site_rows = []
    if si:
        smap = si.get("sitemap", {})
        site_rows += [
            ("XML sitemap lists live pages only", not smap.get("broken") and not smap.get("noindex"), f"{smap.get('urls', 0)} URLs; {smap.get('broken', 0)} broken, {smap.get('noindex', 0)} noindex"),
            ("Every indexable page is in the sitemap", bool(smap.get("urls")) and not smap.get("pages_not_in_sitemap"), f"{smap.get('pages_not_in_sitemap', 0)} page(s) missing" if smap.get("urls") else "no sitemap found"),
            ("No broken internal links", not si.get("broken_internal_links", {}).get("count"), f"{si.get('broken_internal_links', {}).get('count', 0)} broken page(s) linked"),
            ("No orphan pages", not si.get("orphans", {}).get("count"), f"{si.get('orphans', {}).get('count', 0)} page(s) not linked from any crawled page"),
            ("Filter/query URLs are not indexable", not si.get("indexable_query_urls", {}).get("count"),
             f"{si.get('indexable_query_urls', {}).get('count', 0)} indexable filter URL(s)" + (" on " + ", ".join(x["section"] for x in si.get("indexable_query_urls", {}).get("sections", [])[:3]) if si.get("indexable_query_urls", {}).get("sections") else "")),
            ("Unique titles", not si.get("duplicate_titles", {}).get("pages"), f"{si.get('duplicate_titles', {}).get('pages', 0)} pages share a title"),
            ("Unique meta descriptions", not si.get("duplicate_descriptions", {}).get("pages"), f"{si.get('duplicate_descriptions', {}).get('pages', 0)} pages share a description"),
            ("No old or staging hosts", not si.get("legacy_hosts"), ", ".join(h["host"] for h in si.get("legacy_hosts", [])) or "none"),
            ("No links to hosting-provider domains", not si.get("hosting_links"), ", ".join(f"{h['host']} ({h['links']})" for h in si.get("hosting_links", [])[:3]) or "none"),
            ("FAQ structured data in use", si.get("faq_pages", 0) > 0, f"{si.get('faq_pages', 0)} page(s) with FAQPage"),
            ("Program pages have program schema", si.get("program_pages", 0) > 0 and si.get("program_schema_pages", 0) == si.get("program_pages", 0),
             f"{si.get('program_schema_pages', 0)} of {si.get('program_pages', 0)} program pages"),
            ("Median reading grade 12 or below", si.get("median_reading_grade") is not None and si["median_reading_grade"] <= 12, f"grade {si.get('median_reading_grade')}"),
        ] + [("Homepage: " + k, bool(v), "found" if v else "not found") for k, v in si.get("trust", {}).items()]
        wpi = si.get("wordpress", {})
        if wpi.get("available"):
            site_rows += [
                ("Every published WordPress page is linked or in the sitemap", not wpi.get("hidden"),
                 f"{wpi.get('hidden', 0)} of {wpi.get('published', 0)} published page(s)/post(s) hidden: "
                 + (", ".join(urlsplit(u).path for u in wpi.get("hidden_sample", [])[:5]) or "none")),
                ("No former page addresses that open a file", not wpi.get("file_redirects"),
                 ", ".join(f"{urlsplit(x['url']).path} -> {urlsplit(x.get('goes_to') or x.get('file') or '').path.rsplit('/', 1)[-1]}" for x in wpi.get("file_redirect_sample", [])[:5]) or "none"),
            ]

    site_html = ('<h2>Site-level SEO and GEO findings</h2><table><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>'
                 + "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (e(a), yn(b), e(c)) for a, b, c in site_rows)
                 + "</tbody></table>") if site_rows else ""
    unchecked_txt = ("; %d page(s) could not be checked (rate-limited or timed out) and are not graded" % len(si.get("unchecked", []))) if si.get("unchecked") else ""
    search_tile = ("%d/%d" % (len(search) - len(search_blocked), len(search))) if access else "-"
    prio_tile = ("%d/%d" % (prio_ready, len(prio))) if prio else "-"
    verdict_txt = {
        "Ready": "The site is ready to be found and cited by AI search.",
        "Partially ready": "The site can be found by AI search, but many pages need fixes before they are reliably cited.",
        "Not ready": "AI search cannot reliably find or cite the site. Fix the critical items below first.",
    }[verdict]
    if access:
        order = {"search": 0, "user": 1}
        tb = ", ".join(b["bot"] for b in training_blocked) or "none"
        training_line = ('<p><b>Training bots:</b> %d of %d blocked (%s). Blocking training is a policy choice and does not affect AI search visibility.</p>'
                         % (len(training_blocked), len(training), e(tb)))
        deny_line = ""
        if denied:
            deny_line = ('<p><b>Denied by policy</b> (bot_policy.json): %d of %d fully blocked. Not blocked: %s.</p>'
                         % (len(denied) - len(deny_open), len(denied), e(", ".join(b["bot"] for b in deny_open)) or "none"))
        def names(lst, cls):
            return "".join('<span class="pill %s">%s</span>' % (cls, e(x["bot"] + " (" + x["operator"] + ")")) for x in lst) or '<span class="note">none</span>'
        allowed = [b for b in search if not blocked(b) and not partial(b)]
        bots_html = (
            '<table><tbody>'
            '<tr><td class="nw"><b>Blocked</b><br><span class="note">%d bots</span></td><td>%s</td></tr>'
            '<tr><td class="nw"><b>Partly blocked</b><br><span class="note">%d bots</span></td><td>%s</td></tr>'
            '<tr><td class="nw"><b>Allowed</b><br><span class="note">%d bots</span></td><td>%s</td></tr>'
            '</tbody></table>' % (len(search_blocked), names(search_blocked, "bad"), len(search_partial), names(search_partial, "warn"),
                                  len(allowed), names(allowed, "ok"))
            + training_line + deny_line
            + '<p class="note">AI search and answer bots only. Blocked: robots.txt blocks the homepage, robots.txt blocks every sampled sitemap page, '
              'or a live request using the bot&#39;s identity was refused. %s '
              'Blocks that verify the bot&#39;s network address (e.g. Cloudflare bot management) cannot be detected this way. '
              'Per-bot detail is on the Bot Access tab of the app.</p>' % (
                ("Partly blocked: robots.txt blocks some of the %d sampled sitemap pages." % scanned) if scanned
                else "No sitemap pages were found, so partial blocks were not measured."))
    else:
        bots_html = "<p>Not checked.</p>"

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Readiness Report</title>
<style>
  :root {{ --fg:#1b1b1f; --muted:#5f6068; --line:#dcdce2; --ok:#1a7f37; --okbg:#e7f6ec; --bad:#b42318; --badbg:#fdecea; --warn:#8a5a00; --warnbg:#fff4d6; --accent:#2f5bd3; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#fff; color:var(--fg); font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; }}
  main {{ max-width:900px; margin:0 auto; padding:32px 24px 48px; }}
  h1 {{ font-size:26px; margin:0; }}
  h2 {{ font-size:17px; margin:28px 0 10px; padding-bottom:6px; border-bottom:2px solid var(--fg); }}
  .meta {{ color:var(--muted); margin:4px 0 20px; }}
  .verdict {{ display:flex; gap:16px; align-items:center; padding:16px 18px; border-radius:10px; margin-bottom:16px; }}
  .verdict.ok {{ background:var(--okbg); }} .verdict.warn {{ background:var(--warnbg); }} .verdict.bad {{ background:var(--badbg); }}
  .verdict b.v {{ font-size:22px; }}
  .verdict.ok b.v {{ color:var(--ok); }} .verdict.warn b.v {{ color:var(--warn); }} .verdict.bad b.v {{ color:var(--bad); }}
  .tiles {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
  .tile {{ border:1px solid var(--line); border-radius:8px; padding:10px 12px; }}
  .tile b {{ display:block; font-size:24px; }}
  .tile span {{ color:var(--muted); font-size:12px; }}
  ul.f li {{ margin-bottom:6px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
  th {{ font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }}
  td.url {{ word-break:break-all; }}
  .pill {{ display:inline-block; padding:1px 7px; border-radius:999px; font-size:11px; font-weight:600; white-space:nowrap; margin:1px 2px 1px 0; }}
  .ok {{ color:var(--ok); background:var(--okbg); }} .bad {{ color:var(--bad); background:var(--badbg); }} .warn {{ color:var(--warn); background:var(--warnbg); }}
  .note {{ color:var(--muted); font-size:12px; }}
  pre {{ background:#f5f5f7; border:1px solid var(--line); border-radius:6px; padding:10px; font-size:11px; white-space:pre-wrap; word-break:break-all; }}
  .bar {{ position:sticky; top:0; background:#fff; border-bottom:1px solid var(--line); padding:10px 24px; text-align:right; }}
  .bar button {{ padding:8px 16px; border:0; border-radius:6px; background:var(--accent); color:#fff; font-weight:600; cursor:pointer; }}
  .pb {{ break-before:page; }}
  h2.part {{ border:0; font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin:36px 0 0; padding:0; }}
  .areas {{ display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin-top:10px; }}
  .area {{ border-radius:8px; padding:8px 10px; }}
  .area b {{ display:block; font-size:20px; }}
  .area span {{ font-size:11px; }}
  .crit {{ color:var(--bad); font-weight:600; }}
  td.nw {{ white-space:nowrap; }}
  tr.sm td {{ font-size:12px; padding:4px 8px; }}
  @media (max-width:640px) {{ .tiles {{ grid-template-columns:repeat(2,1fr); }} }}
  @media print {{ body {{ font-size:11.5px; }} table {{ font-size:10.5px; }} tr.sm td {{ font-size:10px; padding:3px 6px; }} th,td {{ padding:4px 6px; }} h2 {{ margin:18px 0 8px; font-size:15px; }} .bar {{ display:none; }} main {{ padding:0; max-width:none; }} h2 {{ break-after:avoid; }} tr {{ break-inside:avoid; }} @page {{ margin:0.6in; }} }}
</style></head><body>
<div class="bar"><button onclick="window.print()">Print / Save as PDF</button></div>
<main>
<h1>AI Readiness Report</h1>
<div class="meta">{e(host)} · {e(today)} · {n} pages checked · academic year {e(s['academic_year'])}</div>

<div class="verdict {vcls}"><b class="v">{verdict}</b>
<div>{verdict_txt}</div></div>

<div class="tiles">
  <div class="tile"><b>{pct_ready}%</b><span>pages Ready</span></div>
  <div class="tile"><b>{s['avg_score']}</b><span>average page score (of 100)</span></div>
  <div class="tile"><b>{search_tile}</b><span>AI search bots allowed</span></div>
  <div class="tile"><b>{prio_tile}</b><span>key student pages Ready</span></div>
</div>

{areas_html}
<h2>Key findings</h2>
<ul class="f">{findings_html}</ul>

<h2>Top actions</h2>
<p class="note">Ranked by impact. Owner = who does the work.</p>
<table><thead><tr><th>#</th><th>Action</th><th>Why it matters</th><th>Owner</th><th>Scope</th></tr></thead><tbody>
{actions_html}
</tbody></table>
{more_note}

<h2 class="pb part">Details</h2>
{more_actions_html}
{sd_html}
{site_html}
<h2>Key student pages</h2>
<p class="note">Picked automatically by web address: the homepage plus live pages whose address contains admissions, apply, tuition, cost, financial aid, scholarships, academics, programs, majors, degrees, deadlines, calendar, visit, contact, about, graduate or undergraduate (news, events and filtered copies excluded). Not the same as the 20 EAB priority pages in Appendix F. Worst 10 shown; the Pages CSV has the full list and every failed check.{key_broken_note}</p>
<table><thead><tr><th>Score</th><th>Grade</th><th style="width:38%">Page</th><th>Failed checks</th></tr></thead><tbody>
{prio_html}
</tbody></table>

<h2>AI bot access</h2>
{bots_html}

<h2 class="pb part">Method and appendices</h2>
<h2>Method</h2>
<p class="note">
<b>Bot policy.</b> Bots in bot_policy.json are excluded from AI search counts and scoring; a denied bot counts as blocked only when robots.txt blocks it on the homepage and on every sampled sitemap page, or the server refuses it.<br>
<b>Verdict rules.</b> Ready: at least 80% of pages Ready, no AI search bot blocked, and every homepage organization schema check passes. Partially ready: at least 50% of pages Ready and no AI search bot blocked. Not ready: anything else.<br>
<b>Page grades.</b> Score = checks passed ÷ {len(CHECKS)} × 100. Ready: score 80 or higher and no critical fail. Needs work: score 50-79 and no critical fail. Not ready: score below 50 or any critical fail.<br>
<b>Scope.</b> Started at {e(s['start'])}; {n} pages checked (limit {s['max_pages']}); {stopped_txt}skipped: {e(skipped_txt)}{e(unchecked_txt)}. Error pages (not HTTP 200) are scored only on HTTP 200. Former-name mentions are a review list and are not scored.
"Past" means before the current academic year ({e(s['academic_year'])}), which starts July 1. PDFs are judged by file name and link text only.
</p>
<h2>Appendix A: All checks</h2>
<table><thead><tr><th>Check</th><th>Pass when</th><th>Pages failing</th></tr></thead><tbody>
{checks_html}
</tbody></table>

<h2>Appendix B: Homepage organization schema</h2>
<p class="note">{org_passed_txt} Failing checks shown.</p>
<table><thead><tr><th>Check</th><th>Result</th><th>Found</th></tr></thead><tbody>
{org_html}
</tbody></table>
{snippet_html}

<h2>Appendix C: PDFs to review</h2>
<p class="note">Up to 10 shown, past terms first; the PDFs CSV has the full list.</p>
<table><thead><tr><th>PDF</th><th>Key facts</th><th>Past terms</th><th>Linked from</th></tr></thead><tbody>
{pdf_html}
</tbody></table>

{deny_appendix}
<h2>Appendix E: Coverage of the EAB search visibility checklist</h2>
<p class="note">Source: EAB, "Navigating Search Visibility in the AI Era" (2025). Automated = checked by this tool on every crawl. Manual = needs data this tool cannot crawl.</p>
<table><thead><tr><th>Guide item</th><th>Area</th><th>Coverage</th></tr></thead><tbody>
{coverage_html}
</tbody></table>
{brand_html}
{ai_html}
</main></body></html>"""
    return html


def main() -> int:
    ap = argparse.ArgumentParser(description="Crawl a site and write an executive AI readiness report (HTML).")
    ap.add_argument("url")
    ap.add_argument("--max", type=int, default=500)
    ap.add_argument("--subdomains", action="store_true")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--out", default="ai-readiness-report.html")
    ap.add_argument("--bundle", help="also write a results bundle zip to this path")
    a = ap.parse_args()
    from ai_bot_check import run
    c = Crawl(a.url, a.max, a.subdomains, exclude=a.exclude)
    t = threading.Thread(target=c.run, daemon=True)
    t.start()
    try:
        while t.is_alive():
            t.join(2)
            print(f"\rcrawled {len(c.results)}  queued {c.queued}", end="", file=sys.stderr)
    except KeyboardInterrupt:
        c.stop()
        t.join()
    print("\nchecking bot access…", file=sys.stderr)
    access = run(c.start, probe=True, scan=200)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(build(c.summary(), list(c.results), c.pdf_report(), access))
    print(f"wrote {a.out}", file=sys.stderr)
    if a.bundle:
        from bundle import make_bundle
        with open(a.bundle, "wb") as f:
            f.write(make_bundle(c, access))
        print(f"wrote {a.bundle}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
