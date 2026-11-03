# AI Access & Readiness

Local web app that answers two questions about a website (default: methodist.edu):

1. **Bot Access**: which AI crawlers can reach the site?
2. **Site Readiness**: how ready is each page to be found and cited by AI search?

Python 3.9+ standard library only. No installs.

## Run

```bash
cd ai-bot-access-checker
python3 app.py
```

The browser opens at http://localhost:8000. Use `--port 9000` to change the port. Press Ctrl+C to stop.

## Bot Access tab

Checks 38 AI crawlers (OpenAI, Anthropic, Google, Apple, Microsoft, Perplexity, Meta, Amazon, ByteDance, Common Crawl, Cohere, Mistral, and others). For each bot it reports:

| Column | Meaning |
|---|---|
| robots.txt | Allowed or blocked for the entered URL (RFC 9309 matching). |
| Site coverage | Share of sampled sitemap URLs the bot may crawl. |
| HTTP probe | Server response to the bot's User-Agent, compared to a browser. Detects User-Agent blocks only, not IP-verified blocks (e.g. Cloudflare). |
| Directives | `noai`, `noimageai`, `noindex` in meta tags or X-Robots-Tag. |

Click a row to see the exact robots.txt rules applied to that bot.

## Site Readiness tab

Crawls the site (sitemaps plus links, same host) and scores every HTML page on 19 pass/fail checks.

- **Score** = checks passed ÷ 19 × 100.
- **Ready**: score ≥ 80 and no critical fails.
- **Needs work**: score 50–79 and no critical fails.
- **Not ready**: score < 50, or any critical fail.

Critical checks: HTTP 200, AI search bots allowed, no noindex/noai, at least 150 words of server-rendered text. The full rule table is shown in the app.

Training-bot blocks are reported but not scored. Blocking training is a policy choice, not a readiness defect.

Name and date checks use the **Institution settings** (official name, city, state, former names). Defaults are set for Methodist University, Fayetteville, NC (former name: Methodist College). "Past" means before the current academic year, which starts July 1.

The tab also includes two site-level reports.

**Structured data report**
- Checks the homepage organization schema against the institution settings: type, name, url, logo, city, state and sameAs.
- When any check fails, it generates a ready-to-paste `CollegeOrUniversity` snippet. Replace every `REPLACE-WITH` value before using it.
- Lists every schema type found across the site.

**PDF report**
- Lists every linked PDF.
- **Key facts**: the file name or link text mentions tuition, fees, financial aid, deadlines, calendar, admission requirements or catalog. Put these facts on a web page too.
- **Past terms**: the file name or link text names a past academic year or term. Update, replace or unlink the file.
- PDFs are not downloaded. Only file names and link text are checked.

Crawler behavior: follows robots.txt for itself, 4 workers, 0.25 s delay per worker, skips non-HTML files, default 500 pages (max 20,000). Use the exclude regex to skip calendar or event pages that generate unlimited URLs. **Pages CSV** exports every page with each check marked PASS or FAIL. **PDFs CSV** exports the PDF report.

## Executive report

After a crawl finishes (or is stopped), click **Executive report** on the Site Readiness tab. It opens a printable report; use **Print / Save as PDF** to share it. Length: 2-4 printed pages.

Contents: overall verdict, key numbers, key findings, ranked actions with owners, priority pages (worst 10), AI bot access, method, and appendices (all checks, homepage schema failures, PDFs to review, up to 10).

Verdict rules:
- **Ready**: at least 80% of pages Ready, no AI search bot blocked, and every homepage organization schema check passes.
- **Partially ready**: at least 50% of pages Ready and no AI search bot blocked.
- **Not ready**: anything else.

## Command line

```bash
python3 ai_bot_check.py https://www.methodist.edu --scan 200
```

```bash
python3 readiness.py https://www.methodist.edu --max 2000 --csv pages.csv --pdf-csv pdfs.csv
```

```bash
python3 report.py https://www.methodist.edu --max 500 --out report.html
```
