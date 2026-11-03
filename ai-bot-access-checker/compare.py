"""Competitor comparison: runs the same bot access check and a sampled readiness crawl
on your site and each competitor, then compares them metric by metric.

Each site is crawled politely: same-host only, robots.txt respected, 0.5 s delay per worker,
2 workers, default 200 pages. Your site is re-crawled with the same limit so the comparison is fair.

CLI:  python3 compare.py https://www.methodist.edu https://www.campbell.edu https://www.uncfsu.edu --max 200 --out compare.html
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import sys
import threading
import time
from html import escape as e
from urllib.parse import urlsplit

from ai_bot_check import fully_blocked, run
from readiness import Crawl

# id, label, better ("high" | "low" | None for info only), formatter
METRICS = [
    ("pages", "Pages checked", None, "{}"),
    ("pct_ready", "Pages Ready (%)", "high", "{}%"),
    ("avg_score", "Average page score", "high", "{}"),
    ("area_AI access", "AI access", "high", "{}"),
    ("area_Technical SEO", "Technical SEO", "high", "{}"),
    ("area_On-page SEO", "On-page SEO", "high", "{}"),
    ("area_Structured data", "Structured data", "high", "{}"),
    ("area_Content (GEO/AEO)", "Content (GEO/AEO)", "high", "{}"),
    ("search_allowed_pct", "AI search bots allowed (%)", "high", "{}%"),
    ("training_blocked", "AI training bots blocked", None, "{}"),
    ("denied_blocked_pct", "Deny-list bots blocked (%)", "high", "{}%"),
    ("org_schema", "Valid organization schema on homepage", "high", "{}"),
    ("invalid_schema_pct", "Pages with invalid structured data (%)", "low", "{}%"),
    ("program_schema_pct", "Program pages with program schema (%)", "high", "{}%"),
    ("faq_pages", "Pages with FAQ schema", "high", "{}"),
    ("question_pct", "Key pages that answer questions (%)", "high", "{}%"),
    ("reading_grade", "Median reading grade", "low", "{}"),
    ("sitemap", "XML sitemap found", "high", "{}"),
    ("llms_txt", "llms.txt present", None, "{}"),
]


def _pct(a, b):
    return round(100 * a / b) if b else None


def site_metrics(c: Crawl, access: dict | None) -> dict:
    s = c.summary()
    n = s["pages"]
    cf = {x["id"]: x for x in s["check_failures"]}
    pages = list(c.results)
    m = {"site": urlsplit(c.start).netloc, "start": c.start, "pages": n,
         "pct_ready": _pct(s["grades"]["Ready"], n), "avg_score": s["avg_score"]}
    for a in s.get("areas", []):
        m["area_" + a["area"]] = a["score"]
    if access:
        bots = access["bots"]
        scanned = access.get("pages_scanned", 0)
        search = [b for b in bots if b["purpose"] in ("search", "user") and b["policy"] != "deny"]
        training = [b for b in bots if b["purpose"] == "training" and b["policy"] != "deny"]
        denied = [b for b in bots if b["policy"] == "deny"]
        m["search_allowed_pct"] = _pct(sum(not fully_blocked(b, scanned) for b in search), len(search))
        m["training_blocked"] = f"{sum(fully_blocked(b, scanned) for b in training)} of {len(training)}"
        m["denied_blocked_pct"] = _pct(sum(fully_blocked(b, scanned) for b in denied), len(denied))
        m["llms_txt"] = "yes" if access["policy_files"].get("/llms.txt") == "present" else "no"
        m["sitemap"] = "yes" if access.get("sitemaps") or access.get("pages_scanned") else "no"
    org = s.get("organization") or {}
    m["org_schema"] = "yes" if org.get("rows") and org["rows"][0]["pass"] else "no"
    m["invalid_schema_pct"] = cf["schema_valid"]["pct"] if "schema_valid" in cf else None
    si = s.get("site_issues") or {}
    m["program_schema_pct"] = _pct(si.get("program_schema_pages", 0), si.get("program_pages", 0))
    m["faq_pages"] = si.get("faq_pages", 0)
    q = [p["checks"].get("question_headings") for p in pages if p["checks"].get("question_headings") is not None]
    m["question_pct"] = _pct(sum(q), len(q))
    m["reading_grade"] = si.get("median_reading_grade")
    if "sitemap" not in m:
        m["sitemap"] = "yes" if si.get("sitemap", {}).get("urls") else "no"
    return m


def rank(rows: list[dict]) -> dict:
    """For each metric with a direction: which site(s) are best, and your site's rank (1 = best)."""
    out = {}
    for mid, _, better, _ in METRICS:
        if not better:
            continue
        vals = []
        for r in rows:
            v = r.get(mid)
            if v in ("yes", "no"):
                v = 1 if v == "yes" else 0
            if isinstance(v, (int, float)):
                vals.append((v, r["site"]))
        if not vals:
            continue
        if len({v for v, _ in vals}) == 1:
            out[mid] = {"best": [], "rank": None, "tie": True}  # every site has the same value: nobody leads
            continue
        ordered = sorted({v for v, _ in vals}, reverse=(better == "high"))
        best = ordered[0]
        mine = next((v for v, s in vals if s == rows[0]["site"]), None)
        out[mid] = {"best": [s for v, s in vals if v == best],
                    "rank": None if mine is None else 1 + sum(1 for v, _ in vals if (v > mine if better == "high" else v < mine))}
    return out


class Compare:
    def __init__(self, sites: list[str], max_pages: int = 200):
        self.sites = []
        for u in sites:
            u = u.strip()
            if not u:
                continue
            if "://" not in u:
                u = "https://" + u
            if u not in self.sites:
                self.sites.append(u)
        self.max_pages = max_pages
        self.rows: list[dict] = []
        self.current = ""
        self.current_crawl: Crawl | None = None
        self.state = "pending"
        self.error = ""
        self.started = time.time()
        self.finished: float | None = None
        self._stop = threading.Event()

    def run(self) -> None:
        self.state = "running"
        try:
            for i, u in enumerate(self.sites):
                if self._stop.is_set():
                    break
                self.current = u
                # your site keeps its institution settings; competitors get neutral settings
                own = i == 0
                c = Crawl(u, self.max_pages, subdomains=False, workers=2, delay=0.5,
                          official_name=None if own else "", city=None if own else "",
                          region=None if own else "", former_names=None if own else [])
                self.current_crawl = c
                t = threading.Thread(target=c.run, daemon=True)
                t.start()
                while t.is_alive():
                    if self._stop.is_set():
                        c.stop()
                    t.join(1)
                try:
                    access = run(c.start, probe=True, scan=100)
                except Exception:
                    access = None
                row = site_metrics(c, access)
                row["state"] = c.state
                self.rows.append(row)
            self.state = "stopped" if self._stop.is_set() else "done"
        except Exception as ex:
            self.state, self.error = "error", f"{type(ex).__name__}: {ex}"
        finally:
            self.current, self.current_crawl = "", None
            self.finished = time.time()

    def stop(self):
        self._stop.set()

    def status(self) -> dict:
        cc = self.current_crawl
        return {
            "state": self.state, "error": self.error, "sites": self.sites, "done": len(self.rows),
            "current": self.current, "current_pages": len(cc.results) if cc else 0, "max_pages": self.max_pages,
            "elapsed_s": round((self.finished or time.time()) - self.started),
            "metrics": [{"id": a, "label": b, "better": c} for a, b, c, _ in METRICS],
            "rows": self.rows, "ranks": rank(self.rows) if self.rows else {},
        }

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["metric"] + [r["site"] for r in self.rows])
        for mid, label, _, _ in METRICS:
            w.writerow([label] + ["" if r.get(mid) is None else r.get(mid) for r in self.rows])
        return buf.getvalue()

    def report(self) -> str:
        return build_compare_report(self.status())


def build_compare_report(st: dict) -> str:
    rows, ranks = st["rows"], st["ranks"]
    if not rows:
        return "<p>No results yet.</p>"
    me = rows[0]["site"]
    d = dt.date.today()
    lead, lag = [], []
    for mid, label, better, _ in METRICS:
        rk = ranks.get(mid)
        if not rk or rk["rank"] is None:
            continue
        if rk["rank"] == 1:
            lead.append(label)
        elif rk["rank"] == len(rows):
            lag.append(label)

    def cell(r, mid, fmt):
        v = r.get(mid)
        if v is None:
            return "-"
        txt = fmt.format(v)
        best = r["site"] in ranks.get(mid, {}).get("best", []) and len(rows) > 1
        return f"<b>{e(txt)}</b>" if best else e(txt)

    head = "".join(f"<th>{e(r['site'])}{' (you)' if i == 0 else ''}</th>" for i, r in enumerate(rows))
    body = "".join(
        f"<tr><td>{e(label)}</td><td class='rk'>{'tie' if ranks.get(mid, {}).get('tie') else '' if mid not in ranks or ranks[mid]['rank'] is None else ranks[mid]['rank']}</td>"
        + "".join(f"<td>{cell(r, mid, fmt)}</td>" for r in rows) + "</tr>"
        for mid, label, _, fmt in METRICS)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Competitor Comparison</title><style>
body{{margin:0;background:#fff;color:#1b1b1f;font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:32px 24px}} h1{{font-size:24px;margin:0}} h2{{font-size:16px;margin:24px 0 8px;border-bottom:2px solid #1b1b1f;padding-bottom:4px}}
.meta,.note{{color:#5f6068;font-size:12px}} table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #dcdce2;vertical-align:top}} th{{font-size:11px;text-transform:uppercase;color:#5f6068}}
td.rk{{text-align:center;color:#5f6068}} th:nth-child(3),td:nth-child(3){{background:#eef3ff}}
.bar{{position:sticky;top:0;background:#fff;border-bottom:1px solid #dcdce2;padding:10px 24px;text-align:right}}
.bar button{{padding:8px 16px;border:0;border-radius:6px;background:#2f5bd3;color:#fff;font-weight:600;cursor:pointer}}
@media print{{.bar{{display:none}} main{{padding:0}} @page{{margin:0.5in;size:landscape}}}}
</style></head><body><div class="bar"><button onclick="window.print()">Print / Save as PDF</button></div><main>
<h1>Competitor Comparison</h1>
<div class="meta">{e(me)} vs {len(rows) - 1} competitor(s) · {d:%B} {d.day}, {d.year} · up to {st['max_pages']} pages per site</div>
<h2>Summary</h2>
<ul>
<li><b>{e(me)} leads on {len(lead)} of {sum(1 for r in ranks.values() if not r.get('tie'))} ranked metrics</b>{': ' + e(', '.join(lead)) if lead else ''}.</li>
<li><b>{e(me)} trails every competitor on {len(lag)}</b>{': ' + e(', '.join(lag)) if lag else ''}.</li>
</ul>
<h2>Metrics</h2>
<table><thead><tr><th>Metric</th><th>Your rank</th>{head}</tr></thead><tbody>{body}</tbody></table>
<p class="note">Bold = best value. Rank 1 = best (ties share a rank). "tie" = every site has the same value. Metrics without a rank are informational. Every site was crawled the same way:
same host only, robots.txt respected, up to {st['max_pages']} pages from its sitemap and links, plus the same bot access check.
Competitors are scored without institution-specific name checks. A sample of pages is checked, not the whole site.</p>
</main></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare AI and search readiness: your site (first URL) vs competitors.")
    ap.add_argument("sites", nargs="+", help="your site first, then competitors")
    ap.add_argument("--max", type=int, default=200, help="pages per site (default 200)")
    ap.add_argument("--out", default="competitor-comparison.html")
    ap.add_argument("--csv")
    a = ap.parse_args()
    cmp_ = Compare(a.sites, a.max)
    t = threading.Thread(target=cmp_.run, daemon=True)
    t.start()
    try:
        while t.is_alive():
            t.join(2)
            st = cmp_.status()
            print(f"\r{st['done']}/{len(st['sites'])} sites · {st['current']} {st['current_pages']} pages   ", end="", file=sys.stderr)
    except KeyboardInterrupt:
        cmp_.stop()
        t.join()
    print(file=sys.stderr)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(cmp_.report())
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            f.write(cmp_.to_csv())
    print(f"wrote {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
