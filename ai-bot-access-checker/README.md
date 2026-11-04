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

Crawls the site (sitemaps plus links, same host) and scores every HTML page on pass/fail checks grouped into five areas: AI access, Technical SEO, On-page SEO, Structured data, and Content (GEO/AEO).

- **Score** = applicable checks passed ÷ applicable checks × 100. Checks that do not apply to a page (e.g. program schema on a non-program page) are N/A.
- **Area score** = share of applicable page checks passed in that area.
- **Error pages** (not HTTP 200) are scored only on HTTP 200.
- **Login/app pages** (with a password field) are skipped.
- **Rate-limited or timed-out pages** are retried 4 times, then listed as not checked and not graded.
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

## Bot policy (deny list)

`bot_policy.json` lists bots the school does not allow. Current criteria:
1. Operator based in a U.S. Commerce Dept. foreign-adversary country (15 CFR 791.4).
2. Does not honor robots.txt by default, or is publicly reported to evade blocks.
3. Crawls to build or sell datasets rather than run an AI product.

Rules:
- A denied bot is never counted as "should be allowed" and never fails a page check.
- A denied bot counts as blocked only when robots.txt blocks it on the homepage and every sampled sitemap page, or the server refuses it.
- If a denied bot is not blocked, the Bot Access tab and the report show a robots.txt block to add. Also block it at the CDN or firewall, because robots.txt is voluntary.

Edit the file to change the list, then restart the app.

## Site-level SEO and GEO findings

Shown on the Site Readiness tab and in the report: sitemap coverage, broken and noindex sitemap URLs, orphan pages, broken internal links, duplicate titles and descriptions, old or staging hosts, links to hosting-provider domains, sections that are entirely noindex, FAQ schema use, program schema coverage, median reading grade, and homepage trust signals (privacy, contact, address, accessibility). Former-name mentions are a review list, not scored.

The checks follow EAB's "Navigating Search Visibility in the AI Era" (2025). The report's Appendix E maps each guide item to the check that covers it, or marks it manual (Search Console, keyword tools, backlinks).

## Priority pages, message consistency and content inventory

These three reports are on the Site Readiness tab, in the executive report (Appendices F, G, H) and in the results bundle. They are driven by `messages.json`, pre-filled from the MU brand positioning statements and EAB's AI visibility audit. Edit it and restart the app.

**Priority pages (EAB's five-element standard).** Each page in the priority list (Institution settings) is crawled first and scored pass/fail on:

| Element | Pass when |
|---|---|
| Direct answer | First paragraph of the main content is 20-80 words and comes before the first H2 |
| Proof | Page states a number (%, $, count) and a year, and at least one approved proof point |
| Connections | Links to at least 3 of: School of Medicine, Admissions, Scholarships and aid, Outcomes and careers |
| Authority | Named owner, author or reviewer, plus published and updated dates (visible or in metadata) |
| Structure | 2+ H2s, a question heading or FAQPage, 150+ words of server-rendered text, mobile viewport, no invalid structured data |

Optimized = all five. The report also counts key student pages site-wide that meet all five.

**Message consistency.**
- Approved proof points: whether each appears on the homepage, the priority pages and the site.
- Approved numbers (clubs, NCAA teams, scholarships, aid %, online programs, enrollment, PGM placement years): every value stated on the site, and the pages that state a different value.
- Off-brand phrases: "best kept secret", "little engine that could", "liberal arts school/college/university".

**Content inventory.** Net price calculator, tuition/cost page, parents page, virtual tour (and whether it is linked from the admissions, academics, student life, housing and visit pages), Instagram/YouTube/TikTok on the homepage, and whether every program home page states an outcome.

## AI Answers tab

Sends a question bank to AI assistants with web search on and scores the answers. Needs API keys (Anthropic Console, OpenAI Platform, Perplexity API settings, Google AI Studio). Run any subset of providers. Keys are saved to `keys.json` on your computer only; it is gitignored and never enters the results bundle.

- `questions.json`: 20 branded questions (name MU) and 20 category questions (do not), from EAB's audit prompts and admitted-student survey themes. Each can have `must_contain` / `must_not_contain` rules (regular expressions) for accuracy scoring.
- Per answer: **mentioned** (names MU), **cited** (a search result or citation is on methodist.edu), **accurate** (all required facts present, branded only), **confused** (mixed up with another "Methodist" school), peers named, other sources used.
- Summary: branded mention %, category mention %, citation rate, accuracy, confusions, who gets named on category questions, and which third-party sites the AIs relied on.
- Providers: Claude (`claude-opus-5-5`, Anthropic web search tool), ChatGPT (OpenAI Responses API with web search), Perplexity (`sonar`, search built in) and Google Gemini (`gemini-2.5-flash` with Google Search grounding). Model names are editable under Keys; "List my models" fills the OpenAI and Gemini pickers from the key's own account. Gemini has a free tier; Google AI Overviews themselves have no API, so grounded Gemini is the closest stand-in.
- Cost: roughly a dollar or two per provider for a full run. "Quick test (2)" runs one branded and one category question.
- Re-run monthly. The latest run goes into the results bundle (answers.json/csv/html) and Appendix I of the executive report.

```bash
python3 answers.py --out ai-answers.html --csv ai-answers.csv
```

## Competitors tab

Enter your site and up to 10 competitors. Each site gets the Bot Access check and a readiness crawl of up to the page limit (default 200; same host only, robots.txt respected, 2 workers, 0.5 s delay). Your site is re-crawled with the same limit so the comparison is fair. The table ranks your site on each metric (1 = best, "tie" = all equal). **Comparison report** opens a printable page; **Comparison CSV** exports the table. The latest finished comparison is included in the results bundle.

```bash
python3 compare.py https://www.methodist.edu https://www.campbell.edu https://www.uncfsu.edu --max 200 --out compare.html
```

## Executive report

After a crawl finishes (or is stopped), click **Executive report** on the Site Readiness tab. It opens a printable report; use **Print / Save as PDF** to share it.

Structure:
- **Page 1, executive summary:** verdict, four key numbers, key findings, top 5 actions with owner and scope.
- **Details:** full action plan with steps, other findings, priority pages (worst 10), AI bot access including denied bots.
- **Method and appendices:** all checks, homepage schema failures, PDFs to review (up to 10), robots.txt block for denied bots.

Verdict rules:
- **Ready**: at least 80% of pages Ready, no AI search bot blocked, and every homepage organization schema check passes.
- **Partially ready**: at least 50% of pages Ready and no AI search bot blocked.
- **Not ready**: anything else.

## Results bundle

After a crawl finishes (or is stopped), click **Download results bundle** on the Site Readiness tab. It saves one zip:

| File | Contents |
|---|---|
| manifest.json | Tool version, date, start URL, crawl limits, institution settings, deny list, check rules |
| summary.json | Grades, check failure counts, organization schema, PDF counts |
| pages.json / pages.csv | Every page with every check result |
| pdfs.csv | Linked PDFs with key-fact and past-term flags |
| bot-access.json | Per-bot robots.txt, sitemap coverage, live probe and policy results |
| report.html | Executive report |

The bundle contains only public website data. Use it to share results or to get help tuning the checks.

## Command line

```bash
python3 ai_bot_check.py https://www.methodist.edu --scan 200
```

```bash
python3 readiness.py https://www.methodist.edu --max 2000 --csv pages.csv --pdf-csv pdfs.csv
```

```bash
python3 report.py https://www.methodist.edu --max 500 --out report.html --bundle results.zip
```
