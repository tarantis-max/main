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

Crawls the site (sitemaps plus links, same host) and scores every HTML page on 15 pass/fail checks.

- **Score** = checks passed ÷ 15 × 100.
- **Ready**: score ≥ 80 and no critical fails.
- **Needs work**: score 50–79 and no critical fails.
- **Not ready**: score < 50, or any critical fail.

Critical checks: HTTP 200, AI search bots allowed, no noindex/noai, at least 150 words of server-rendered text. The full rule table is shown in the app.

Training-bot blocks are reported but not scored. Blocking training is a policy choice, not a readiness defect.

Crawler behavior: follows robots.txt for itself, 4 workers, 0.25 s delay per worker, skips non-HTML files, default 500 pages (max 20,000). Use the exclude regex to skip calendar or event pages that generate unlimited URLs. Download CSV exports every page with each check marked PASS or FAIL.

## Command line

```bash
python3 ai_bot_check.py https://www.methodist.edu --scan 200
```

```bash
python3 readiness.py https://www.methodist.edu --max 2000 --csv readiness.csv
```
