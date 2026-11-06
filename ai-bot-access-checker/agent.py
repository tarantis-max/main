#!/usr/bin/env python3
"""AI readiness agent: run every check, have Claude verify the findings against the live pages, and send a summary.

    python3 agent.py                         run everything + findability, review, send
    python3 agent.py --skip answers          skip steps (access, crawl, compare, answers, findability)
    python3 agent.py --review                review the newest results bundle again (no new checks)
    python3 agent.py --review bundle.zip     review that results bundle (a .zip, or a folder that holds one)
    python3 agent.py --dry-run               do everything except send email / Teams

Schedule it on the VM (see README, "Agent"). Settings: agent.json (created on first run, not in git).
Secrets: ANTHROPIC_API_KEY (or keys.json "anthropic"); AGENT_SMTP_PASSWORD (or keys.json "smtp_password");
AGENT_TEAMS_WEBHOOK (or keys.json "teams_webhook"). They are never written to results.

What the agent does with the results: for each candidate finding it may open the page on the site (read-only, this
site only) to confirm it, drops false matches with a reason, compares with the previous run, and writes a fix list
and a draft email for the web team. It never changes the website. A person reviews and sends the email.
Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import smtplib
import ssl
import sys
import threading
import urllib.request
import zipfile
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

from ai_bot_check import fetch
from answers import _post, load_keys
from findability import CFG as FIND_CFG, NAV_TEXT, Find, report_html as find_report
from readiness import CRAWLER_UA, GRADES, PageParser, _header, answer_summary, apply_key_checks, regrade
from report import build as build_report

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "agent.json"
DEFAULTS = {
    "model": "claude-sonnet-5-5",
    "effort": "medium",
    "max_turns": 30,
    "max_page_reads": 40,
    "min_checks": 10,
    "findability": [
        {"url": "https://www.methodist.edu/", "set": "undergraduate"},
        {"url": "https://www.methodist.edu/academics/medicine/", "set": "medicine"},
        {"url": "https://www.methodist.edu/", "set": "medicine"},
    ],
    "email_to": [],
    "email_from": "",
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "owners": ["Web team", "Marketing", "Admissions", "Financial Aid", "School of Medicine", "IT"],
}
API_URL = os.environ.get("AGENT_API_BASE", "https://api.anthropic.com") + "/v1/messages"
PRICE = {"claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0), "claude-haiku-5-5": (0.10, 0.50)}  # $ per 1M tokens in/out


def load_config() -> dict:
    c = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            c.update({k: v for k, v in json.loads(CONFIG_FILE.read_text(encoding="utf-8")).items() if k in DEFAULTS})
        except (OSError, ValueError) as ex:
            print(f"agent.json could not be read ({ex}); using defaults", file=sys.stderr)
    else:
        CONFIG_FILE.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
        print(f"created {CONFIG_FILE.name}: add email_to and the SMTP settings to get the summary by email", file=sys.stderr)
    return c


def secret(env: str, key: str) -> str:
    return os.environ.get(env, "").strip() or str(load_keys().get(key) or "").strip()


# ---------------------------------------------------------------- 1. checks

def run_checks(skip: list[str]) -> Path:
    from runall import RunAll, load_settings
    r = RunAll(load_settings(), [s for s in skip if s != "findability"])
    t = threading.Thread(target=r.run, daemon=True)
    t.start()
    last = ""
    while t.is_alive():
        t.join(10)
        line = f"{r.current}: {r.progress()}" if r.current else ""
        if line and line != last:
            print("  " + line, file=sys.stderr)
            last = line
    for s in r.steps.values():
        print(f"  {s['label']:<14} {s['state']:<9} {s['detail']}", file=sys.stderr)
    if not r.saved:
        raise SystemExit("The checks saved nothing, so there is nothing to review.")
    return Path(r.saved["folder"])


def run_findability(folder: Path, starts: list[dict]) -> None:
    for i, st in enumerate(starts, 1):
        print(f"  findability {i} of {len(starts)}: {st['url']} ({st.get('set') or 'auto'})", file=sys.stderr)
        f = Find(st["url"], st.get("set") or None)
        res = f.run()
        (folder / f"findability-{i}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
        (folder / f"findability-{i}.html").write_text(find_report(res), encoding="utf-8")


# ---------------------------------------------------------------- 2. digest (what the agent reviews)

def _bundle_files(folder: Path) -> dict:
    """The run's JSON files, from its results bundle (.zip) or from an unpacked bundle folder."""
    want = ("summary.json", "pages.json", "bot-access.json", "answers.json", "manifest.json")
    zips = sorted(z for z in folder.glob("*.zip") if BUNDLE_NAME.search(z.name)) or sorted(folder.glob("*.zip"))
    out = {}
    if zips:
        with zipfile.ZipFile(zips[-1]) as z:
            names = set(z.namelist())
            out = {n: json.loads(z.read(n)) for n in want if n in names}
    else:
        out = {n: json.loads((folder / n).read_text(encoding="utf-8")) for n in want if (folder / n).exists()}
    if "summary.json" not in out or "pages.json" not in out:
        raise SystemExit(f"{folder} has no results bundle (summary.json and pages.json).")
    return out


def digest(folder: Path) -> dict:
    b = _bundle_files(folder)
    summary, pages = b["summary.json"], b["pages.json"]
    access = b.get("bot-access.json")
    answers = b.get("answers.json") or {}
    prio = {r["url"] for r in (summary.get("priority_pages") or {}).get("rows", [])}
    for p in pages:  # current grading, so runs made with older versions compare (same as rescore.py)
        if p["url"] in prio and not p["detail"].get("key_page"):
            p["detail"]["priority"] = True
            apply_key_checks(p)
        regrade(p, bool(p["detail"].get("key_page") or p["detail"].get("priority")))
    summary["grades"] = {g: sum(1 for p in pages if p["grade"] == g) for g in GRADES}
    summary["answer"] = answer_summary(pages)
    col: dict = {}
    build_report(summary, pages, [], access, answers.get("summary"), collect=col)  # regrades old bundles, ranks the actions
    ans = summary.get("answer") or {}
    d = {
        "run": folder.name,
        "site": summary.get("start") or summary.get("site") or "",
        "version": (b.get("manifest.json") or {}).get("version", "?"),
        "headline": {
            "pages_crawled": summary.get("pages"), "grades": summary.get("grades"),
            "key_pages": ans.get("key_pages"), "key_pages_citable": ans.get("citable"), "citable_at": ans.get("citable_at"),
            "average_answer_quality": ans.get("average"), "pages_passing_access": ans.get("access_pass"),
            "answer_parts_earned_pct": {p.get("id"): p.get("earned_pct") for p in ans.get("parts", [])},
        },
        "actions": [{"rank": i, "title": a[0], "why": a[1], "fix": a[2], "owner": a[3], "scope": a[4]}
                    for i, a in enumerate(col.get("actions", []), 1)][:25],
        "worst_key_pages": [{"url": p["url"], "grade": p.get("grade"), "answer_quality": p.get("answer_score"), "title": p["detail"].get("title")}
                            for p in sorted((p for p in pages if (p["detail"].get("key_page") or p["detail"].get("priority")) and p.get("answer_score") is not None),
                                            key=lambda p: p.get("answer_score") or 0)[:12]],
    }
    if access:
        bots = access.get("bots") or []
        d["bots_blocked"] = [{"bot": x.get("bot"), "purpose": x.get("purpose"), "robots_txt": x.get("robots_txt"), "server": x.get("http_probe"),
                              "policy": x.get("policy")}
                             for x in bots if str(x.get("robots_txt", "")).startswith("blocked") or str(x.get("http_probe", "")).startswith(("blocked", "challenged"))][:25]
        d["denied_bots_not_blocked"] = access.get("deny_not_blocked")
    s = answers.get("summary")
    if s:
        d["ai_answers"] = {k: s.get(k) for k in ("answers_total", "branded_mention", "niche_mention", "broad_mention", "citation_rate",
                                                 "citation_share", "citation_share_broad", "accuracy", "confusions", "date")}
        wrong = [r for r in answers.get("results", []) if r.get("rep", 1) == 1 and r.get("accurate") is False]
        d["ai_answers"]["inaccurate"] = [{"id": r["id"], "provider": r["provider"], "question": r["question"],
                                          "missing_facts": r.get("missing_facts"), "forbidden_found": r.get("forbidden_found"),
                                          "confused_with": r.get("confused_with"), "answer_excerpt": (r.get("answer") or "")[:500]}
                                         for r in wrong][:40]
    finds = []
    for fp in sorted(folder.glob("findability-*.json")):
        f = json.loads(fp.read_text(encoding="utf-8"))
        if f.get("error"):
            finds.append({"start": f.get("url"), "error": f["error"]})
            continue
        finds.append({"start": f["url"], "topics": f["set_label"], "warning": f.get("warning"), "counts": f["counts"],
                      "rows": [{"topic": r["label"], "status": r["status"], "page": (r.get("where") or {}).get("url"),
                                "clicks": (r.get("where") or {}).get("clicks"), "menu_only": (r.get("where") or {}).get("menu_only"),
                                "quote": (r.get("where") or {}).get("snippet", "")[:300]} for r in f["topics"]]})
    if finds:
        d["findability"] = finds
    return d


BUNDLE_NAME = re.compile(r"ai-readiness-results.*\.zip$", re.I)


def _is_run(d: Path) -> bool:
    return any(BUNDLE_NAME.search(z.name) for z in d.glob("*.zip")) or ((d / "summary.json").exists() and (d / "pages.json").exists())


def _newest(places: list[Path]) -> Path | None:
    found = []
    for pl in places:
        if pl.is_dir():
            found += [z for z in pl.rglob("*.zip") if BUNDLE_NAME.search(z.name)]
            found += [d / "summary.json" for d in pl.rglob("*") if d.is_dir() and (d / "summary.json").exists() and (d / "pages.json").exists()]
    return max(found, key=lambda f: f.stat().st_mtime) if found else None


def find_run(arg: str) -> Path:
    """Turn what --review was given into a run folder: a run folder, a folder holding one at any depth,
    a results bundle .zip anywhere, or "latest" (the newest bundle in results, this folder, or Downloads)."""
    results = HERE / "results"
    if arg == "latest":
        downloads = [Path.home() / "Downloads"] + sorted(Path.home().glob("OneDrive*/Downloads"))  # OneDrive can move Downloads
        newest = _newest([results]) or _newest(downloads) or next((z for z in sorted(HERE.glob("*.zip"), key=lambda z: z.stat().st_mtime, reverse=True)
                                                             if BUNDLE_NAME.search(z.name)), None)
        if not newest:
            raise SystemExit("No results bundle found in the results folder, this folder or Downloads. Download one from the app "
                             "(Site Readiness, Download results bundle) or use Run everything, then try again.")
        print(f"  using the newest results: {newest}", file=sys.stderr)
        arg = str(newest)
    p = Path(arg.strip().strip('"')).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p) if (Path.cwd() / p).exists() else (HERE / p)
    if not p.exists():
        raise SystemExit(f"{p} does not exist. Give a results bundle .zip or a folder, or use --review with nothing after it for the newest bundle.")
    if p.is_file():
        if p.name == "summary.json":
            return p.parent
        if p.suffix.lower() != ".zip":
            raise SystemExit(f"{p.name} is not a results bundle (.zip).")
        if results in p.resolve().parents:
            return p.parent  # already inside a results folder
        stamp = re.search(r"(\d{8}-\d{4})", p.name)
        folder = results / (stamp.group(1) if stamp else p.stem)  # the review's files need a folder of their own
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / p.name
        if not dest.exists():
            import shutil
            shutil.copy2(p, dest)
            print(f"  copied {p.name} to {folder}", file=sys.stderr)
        return folder
    if _is_run(p):
        return p
    newest = _newest([p])
    if newest:
        return find_run(str(newest))
    listing = ", ".join(sorted(x.name for x in p.iterdir())[:15]) or "nothing"
    raise SystemExit(f"No results bundle in {p} (it contains: {listing}). Put the ai-readiness-results-....zip file there, "
                     "or run  python3 agent.py --review  with nothing after it to use the newest bundle.")


def previous_digest(folder: Path) -> dict | None:
    """The agent digest of the most recent earlier run, for month-over-month comparison."""
    earlier = sorted(p for p in folder.parent.iterdir() if p.is_dir() and p.name < folder.name and (p / "agent-digest.json").exists())
    if not earlier:
        return None
    try:
        return json.loads((earlier[-1] / "agent-digest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- 3. review (Claude, with read-only page access)

SYSTEM = """You review the monthly AI-readiness results for a university website and turn them into a short, correct fix list.

The results come from automated checks that match word patterns, so some findings are false matches. Your job:
1. Check the candidate findings (ranked actions, findability rows, inaccurate AI answers) before you confirm them. Use read_page to open the page on the site and look for the evidence. Confirm a finding only when the page shows it. Typical false matches: a number about something else (a salary, a 1970s history fact, a national statistic), a phrase inside a menu or footer, a page about a different program.
2. Drop false matches and say why in one sentence.
3. Compare with the previous run when one is given: what improved, what got worse, what is new.
4. Write the fix list. Each fix: what is wrong, where (one URL), the evidence (a short quote or what you saw), the exact fix, the owner, and the priority (now = hurts AI answers today or is broken; next = this month; later).
5. Write a draft email to the web team (Marcom). Plain text, short, numbered fixes, no jargon, no hedging. Start with one sentence on how the site is measured and the headline numbers.

Rules:
- Use only facts from the results or from pages you read; never invent numbers or URLs. Write in plain, definite language.
- Keep each finding's meaning. Broken is not missing, outdated is not wrong, a menu-only link is not a missing link. If the results say "fix broken structured data", the fix is to repair it, not to add it.
- Template problems (structured data, meta tags, footer code) live in the HTML source: search them with source=true. A text search that finds nothing does not prove something is absent; read_page tells you when words appear only in the HTML source or only in menus and footers.
- Each fix's URL is the page that has the problem. Never give an address that redirects somewhere else, except when the redirect itself is the problem. For a section-wide problem, give the most important page in that section.
- If a page now shows a finding is already fixed, move it to dismissed with the reason "already fixed".
- Check at least the top {min_checks} findings with read_page before you submit, highest-ranked first; spend your remaining page reads on the next ones. Mark only what you did not read as status "not_checked".
- When you are done, call submit_review once with the complete review."""


def _tools(owners: list[str]) -> list[dict]:
    fix = {"type": "object", "additionalProperties": False,
           "required": ["title", "url", "evidence", "fix", "owner", "priority", "status"],
           "properties": {"title": {"type": "string"}, "url": {"type": "string"}, "evidence": {"type": "string"}, "fix": {"type": "string"},
                          "owner": {"type": "string", "enum": owners}, "priority": {"type": "string", "enum": ["now", "next", "later"]},
                          "status": {"type": "string", "enum": ["confirmed", "not_checked"]}}}
    return [
        {"name": "read_page",
         "description": "Read one page on the website being reviewed (read-only). Returns the title and the page's own text (menus, header and footer removed). "
                        "With 'find', returns only the sentences containing those words (case-insensitive; separate alternatives with |); if they are not in the page's own text, it says whether they appear in menus/footer or only in the HTML source. "
                        "With source=true, searches the raw HTML instead (use it for structured data, meta tags and template code).",
         "input_schema": {"type": "object", "additionalProperties": False, "required": ["url"],
                          "properties": {"url": {"type": "string"}, "find": {"type": "string"}, "source": {"type": "boolean"}}}},
        {"name": "submit_review", "strict": True,
         "description": "Submit the finished review. Call once, at the end.",
         "input_schema": {"type": "object", "additionalProperties": False,
                          "required": ["summary", "changes_since_last_run", "fixes", "dismissed", "email_subject", "email_body"],
                          "properties": {
                              "summary": {"type": "string", "description": "3-5 sentences: where the site stands and what matters most."},
                              "changes_since_last_run": {"type": "array", "items": {"type": "string"}},
                              "fixes": {"type": "array", "items": fix},
                              "dismissed": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["finding", "reason"],
                                                                       "properties": {"finding": {"type": "string"}, "reason": {"type": "string"}}}},
                              "email_subject": {"type": "string"},
                              "email_body": {"type": "string"}}}},
    ]


def _find_rx(find: str) -> "re.Pattern":
    """Words to look for: read as a pattern (a|b) and also literally, so 'ld+json' or '$65,000' match as typed."""
    try:
        re.compile(find)
        return re.compile(f"(?:{find})|{re.escape(find)}", re.I)
    except re.error:
        return re.compile(re.escape(find), re.I)


def read_page(url: str, find: str = "", source: bool = False, site: str = "") -> str:
    """The read_page tool. Only the reviewed site (and its subdomains) can be read."""
    sp = urlsplit(url if "://" in url else "https://" + url)
    base = urlsplit(site).netloc.lower().removeprefix("www.")
    host = sp.netloc.lower()
    if not base or not (host == base or host.endswith("." + base)):
        return f"Refused: only pages on {base or 'the reviewed site'} can be read."
    r = fetch(sp.geturl(), CRAWLER_UA, max_bytes=3_000_000)
    if r["status"] != 200:
        return f"HTTP {r['status'] or 'no response'} ({r.get('error') or 'error'}) for {url}"
    raw = r["body"].decode("utf-8", "replace")
    final = r["final_url"] or url
    head = f"URL: {final}\n" + (f"(redirected from {url})\n" if final != url else "")
    if "html" not in _header(r["headers"], "content-type").lower():
        return head + f"Not an HTML page ({_header(r['headers'], 'content-type')})."
    if source:
        if not find:
            return head + raw[:6000]
        rx = _find_rx(find)
        hits = [raw[max(0, m.start() - 200): m.end() + 300] for m in rx.finditer(raw)][:10]
        return head + ("\n---\n".join(hits) if hits else f"No match for '{find}' in the HTML source.")
    p = PageParser()
    try:
        p.feed(raw)
    except Exception:
        pass
    text = " ".join(NAV_TEXT.sub(" ", " ".join(p.body_text)).split())
    head += f"Title: {' '.join(p.title.split())}\n"
    if find:
        rx = _find_rx(find)
        sents = re.split(r"(?<=[.!?])\s+", text)
        hits = [s for s in sents if rx.search(s)][:15]
        if hits:
            return head + "\n".join(f"- {s[:400]}" for s in hits)
        # not in the page's own text: say where else it is, so absence is never assumed
        full = " ".join(" ".join(p.text).split())
        chrome = list(dict.fromkeys(full[max(0, m.start() - 150): m.end() + 150] for m in rx.finditer(full)))[:5]
        if chrome:
            return head + f"Not in the page's own text. Found only in menus, header, footer or sidebars:\n" + "\n".join(f"- {c}" for c in chrome)
        src = [raw[max(0, m.start() - 200): m.end() + 300] for m in rx.finditer(raw)][:5]
        if src:
            return head + f"Not in any visible text. Found only in the HTML source (code, structured data, meta tags or hidden elements):\n" + "\n---\n".join(src)
        return head + f"'{find}' does not appear anywhere on this page: not in the text, the menus, or the HTML source."
    return head + text[:6000] + ("…" if len(text) > 6000 else "")


def review(d: dict, prev: dict | None, cfg: dict) -> dict:
    key = secret("ANTHROPIC_API_KEY", "anthropic")
    if not key:
        raise SystemExit("No Anthropic API key: set ANTHROPIC_API_KEY or add it to keys.json.")
    headers = {"x-api-key": key, "anthropic-version": "2026-10-21", "anthropic-beta": "server-side-fallback-2026-07-01"}
    tools = _tools(cfg["owners"])
    min_checks = min(int(cfg.get("min_checks", 10)), int(cfg["max_page_reads"]))
    system = SYSTEM.replace("{min_checks}", str(min_checks))
    pushed_back = False
    msg = ("Results of this run:\n```json\n" + json.dumps(d, indent=1) + "\n```\n\n"
           + ("Previous run, for comparison:\n```json\n" + json.dumps(prev, indent=1) + "\n```\n" if prev else "There is no previous run to compare with.\n")
           + f"\nYou may read up to {cfg['max_page_reads']} pages. Review the results, then call submit_review.")
    messages = [{"role": "user", "content": msg}]
    usage = {"input": 0, "output": 0, "page_reads": 0, "model": cfg["model"]}
    nudges = 0
    for _ in range(int(cfg["max_turns"])):
        resp = _post(API_URL, headers, {"model": cfg["model"], "max_tokens": 16000, "system": system, "tools": tools,
                                        "tool_choice": {"type": "auto"}, "output_config": {"effort": cfg["effort"]},
                                        "fallbacks": "default", "messages": messages})
        u = resp.get("usage") or {}
        usage["input"] += u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        usage["output"] += u.get("output_tokens", 0)
        if resp.get("stop_reason") == "refusal":
            raise RuntimeError("The model declined the review: " + str((resp.get("stop_details") or {}).get("category")))
        content = resp.get("content") or []
        messages.append({"role": "assistant", "content": content})  # unchanged, thinking blocks included
        calls = [c for c in content if c.get("type") == "tool_use"]
        done = next((c for c in calls if c["name"] == "submit_review"), None)
        if done and usage["page_reads"] < min_checks and not pushed_back:
            pushed_back = True  # once: too few findings were checked against the live pages
            results = [{"type": "tool_result", "tool_use_id": c["id"], "is_error": True,
                        "content": f"Not accepted yet: you read {usage['page_reads']} pages. Check at least the top {min_checks} findings with read_page, "
                                   "update the review, then call submit_review again."} if c["name"] == "submit_review"
                       else {"type": "tool_result", "tool_use_id": c["id"], "is_error": True, "content": "Not run; read pages first."} for c in calls]
            messages.append({"role": "user", "content": results})
            continue
        if done:
            out = dict(done["input"])
            out["usage"] = usage
            return out
        if not calls:
            if resp.get("stop_reason") == "max_tokens" or nudges >= 2:
                raise RuntimeError(f"The review stopped without a result (stop reason: {resp.get('stop_reason')}).")
            nudges += 1
            messages.append({"role": "user", "content": "Call submit_review now with the complete review."})
            continue
        results = []
        for c in calls:
            if c["name"] != "read_page":
                results.append({"type": "tool_result", "tool_use_id": c["id"], "is_error": True, "content": f"Unknown tool {c['name']}."})
                continue
            if usage["page_reads"] >= int(cfg["max_page_reads"]):
                results.append({"type": "tool_result", "tool_use_id": c["id"], "is_error": True,
                                "content": "Page-read limit reached. Mark the remaining findings not_checked and call submit_review."})
                continue
            usage["page_reads"] += 1
            a = c.get("input") or {}
            print(f"  reading {a.get('url')}" + (f" for '{a['find']}'" if a.get("find") else ""), file=sys.stderr)
            try:
                txt = read_page(str(a.get("url", "")), str(a.get("find") or ""), bool(a.get("source")), d.get("site") or "")
                results.append({"type": "tool_result", "tool_use_id": c["id"], "content": txt})
            except Exception as ex:  # a bad page should not end the review
                results.append({"type": "tool_result", "tool_use_id": c["id"], "is_error": True, "content": f"{type(ex).__name__}: {ex}"})
        messages.append({"role": "user", "content": results})
    raise RuntimeError(f"The review did not finish within {cfg['max_turns']} turns.")


# ---------------------------------------------------------------- 4. output and delivery

def cost(usage: dict) -> float:
    pin, pout = PRICE.get(usage.get("model", ""), (0, 0))
    return round(usage.get("input", 0) / 1e6 * pin + usage.get("output", 0) / 1e6 * pout, 2)


def render_html(d: dict, rv: dict) -> str:
    e = html.escape
    h = d["headline"]
    pr = {"now": "bad", "next": "warn", "later": "na"}
    fixes = "".join(
        f"<tr><td><span class='pill {pr[f['priority']]}'>{e(f['priority'])}</span></td><td><b>{e(f['title'])}</b>"
        f"<div class='muted url'><a href='{e(f['url'])}'>{e(f['url'])}</a></div><div class='muted'>{e(f['evidence'])}</div></td>"
        f"<td>{e(f['fix'])}</td><td>{e(f['owner'])}</td><td>{'✓ checked' if f['status'] == 'confirmed' else 'not checked'}</td></tr>"
        for f in sorted(rv["fixes"], key=lambda f: ["now", "next", "later"].index(f["priority"])))
    dismissed = "".join(f"<li><b>{e(x['finding'])}</b>: {e(x['reason'])}</li>" for x in rv["dismissed"])
    changes = "".join(f"<li>{e(x)}</li>" for x in rv["changes_since_last_run"])
    u = rv.get("usage", {})
    css = """body{margin:0;background:#fff;color:#1b1b1f;font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}main{max-width:1000px;margin:0 auto;padding:28px 20px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:24px 0 8px;border-bottom:2px solid #1b1b1f;padding-bottom:4px}.muted{color:#5f6068;font-size:12px}
.url{overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #dcdce2;vertical-align:top}
th{font-size:11px;text-transform:uppercase;color:#5f6068}.pill{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:600}
.bad{color:#b42318;background:#fdecea}.warn{color:#9a6700;background:#fff4d6}.na{color:#5f6068;background:#eef0f2}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0}.tile{border:1px solid #dcdce2;border-radius:8px;padding:10px 12px}.tile b{display:block;font-size:22px}
pre{white-space:pre-wrap;background:#f6f6f8;padding:12px;border-radius:8px;font:13px/1.5 system-ui,sans-serif}@media (max-width:640px){.tiles{grid-template-columns:1fr}}"""
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>AI Readiness Review {e(d['run'])}</title><style>{css}</style></head><body><main>"
            f"<h1>AI readiness review</h1><div class='muted'>{e(d['site'])} · run {e(d['run'])} · reviewed by {e(u.get('model', ''))}, "
            f"{u.get('page_reads', 0)} pages read, about ${cost(u)}</div>"
            f"<div class='tiles'><div class='tile'><b>{h.get('key_pages_citable')} of {h.get('key_pages')}</b><span class='muted'>key pages citable</span></div>"
            f"<div class='tile'><b>{h.get('average_answer_quality')}</b><span class='muted'>average answer quality (of 100)</span></div>"
            f"<div class='tile'><b>{h.get('pages_passing_access')} of {h.get('pages_crawled')}</b><span class='muted'>pages AI can reach and read</span></div></div>"
            f"<p>{e(rv['summary'])}</p>"
            + (f"<h2>Since the last run</h2><ul>{changes}</ul>" if changes else "")
            + f"<h2>Fix list</h2><table><thead><tr><th>Priority</th><th>Finding</th><th>Fix</th><th>Owner</th><th>Checked</th></tr></thead><tbody>{fixes}</tbody></table>"
            + (f"<h2>Dismissed as false matches</h2><ul>{dismissed}</ul>" if dismissed else "")
            + f"<h2>Draft email to the web team</h2><p class='muted'>Review before sending.</p><p><b>Subject:</b> {e(rv['email_subject'])}</p><pre>{e(rv['email_body'])}</pre>"
            + "</main></body></html>")


def render_text(d: dict, rv: dict, folder: Path) -> str:
    h = d["headline"]
    lines = [f"AI readiness review, run {d['run']}",
             f"Key pages citable: {h.get('key_pages_citable')} of {h.get('key_pages')} · average answer quality {h.get('average_answer_quality')}",
             "", rv["summary"], ""]
    if rv["changes_since_last_run"]:
        lines += ["Since the last run:"] + [f"- {x}" for x in rv["changes_since_last_run"]] + [""]
    now = [f for f in rv["fixes"] if f["priority"] == "now"]
    if now:
        lines += ["Fix now:"] + [f"- {f['title']} ({f['owner']}): {f['url']}" for f in now] + [""]
    lines.append(f"Full review, draft email to the web team and reports: {folder}")
    return "\n".join(lines)


def send_email(cfg: dict, subject: str, text: str, html_body: str) -> str:
    to = [x for x in cfg.get("email_to") or [] if x]
    if not to or not cfg.get("smtp_host"):
        return "email not configured (agent.json: email_to, email_from, smtp_host)"
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = subject, cfg.get("email_from") or cfg.get("smtp_user"), ", ".join(to)
    m.set_content(text)
    m.add_alternative(html_body, subtype="html")
    port = int(cfg.get("smtp_port") or 587)
    ctx = ssl.create_default_context()
    with (smtplib.SMTP_SSL(cfg["smtp_host"], port, timeout=60, context=ctx) if port == 465 else smtplib.SMTP(cfg["smtp_host"], port, timeout=60)) as s:
        s.ehlo()
        if port != 465 and s.has_extn("starttls"):
            s.starttls(context=ctx)
            s.ehlo()
        pw = secret("AGENT_SMTP_PASSWORD", "smtp_password")
        if cfg.get("smtp_user") and pw:
            s.login(cfg["smtp_user"], pw)
        s.send_message(m)
    return f"emailed {', '.join(to)}"


def send_teams(text: str) -> str:
    hook = secret("AGENT_TEAMS_WEBHOOK", "teams_webhook")
    if not hook:
        return "Teams not configured (AGENT_TEAMS_WEBHOOK or keys.json teams_webhook)"
    card = {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4",
        "body": [{"type": "TextBlock", "text": text, "wrap": True}]}}]}
    req = urllib.request.Request(hook, data=json.dumps(card).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
        return f"posted to Teams (HTTP {r.status})"


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the checks, have Claude verify the findings, and send a summary.")
    ap.add_argument("--skip", default="", help="comma-separated steps to skip: access, crawl, compare, answers, findability")
    ap.add_argument("--review", nargs="?", const="latest",
                    help="review finished results instead of running new checks: a results bundle .zip, a folder, or nothing for the newest bundle")
    ap.add_argument("--dry-run", action="store_true", help="do not send email or Teams")
    a = ap.parse_args()
    cfg = load_config()
    skip = [x.strip() for x in a.skip.split(",") if x.strip()]
    if not secret("ANTHROPIC_API_KEY", "anthropic"):
        print("No Anthropic API key: set ANTHROPIC_API_KEY or add it to keys.json.", file=sys.stderr)
        return 2
    started = dt.datetime.now()
    if a.review:
        folder = find_run(a.review)
    else:
        print("1. Running the checks", file=sys.stderr)
        folder = run_checks(skip)
    if not a.review and "findability" not in skip:
        print("2. Findability", file=sys.stderr)
        run_findability(folder, cfg["findability"])
    print("3. Agent review", file=sys.stderr)
    d = digest(folder)
    (folder / "agent-digest.json").write_text(json.dumps(d, indent=2), encoding="utf-8")
    try:
        rv = review(d, previous_digest(folder), cfg)
    except Exception as ex:
        msg = f"The agent review failed: {type(ex).__name__}: {ex}. The check results are saved in {folder}."
        print(msg, file=sys.stderr)
        if not a.dry_run:
            print("  " + send_teams(msg), file=sys.stderr)
        return 1
    (folder / "agent-review.json").write_text(json.dumps(rv, indent=2), encoding="utf-8")
    page = render_html(d, rv)
    (folder / "agent-review.html").write_text(page, encoding="utf-8")
    text = render_text(d, rv, folder)
    print("\n" + text + f"\n\nReview cost about ${cost(rv['usage'])} ({rv['usage']['page_reads']} pages read); "
          f"total time {round((dt.datetime.now() - started).total_seconds() / 60)} min.", file=sys.stderr)
    if a.dry_run:
        print("Dry run: nothing sent.", file=sys.stderr)
        return 0
    print("4. Sending", file=sys.stderr)
    for fn in (lambda: send_email(cfg, f"AI readiness review: {d['run']}", text, page), lambda: send_teams(text)):
        try:
            print("  " + fn(), file=sys.stderr)
        except Exception as ex:
            print(f"  sending failed: {type(ex).__name__}: {ex}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
