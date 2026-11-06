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

## Run everything

The **Run everything** button at the top runs every check in order: bot access, full site crawl, competitor comparison, AI answer test. It then saves the results bundle and executive report to `results/<date-time>/`. A failed or skipped step does not stop the later ones. Stop saves whatever finished.

Settings (site, max pages, subdomains, competitors, providers) are in the panel under the button and are saved to `runall.json`. API keys are never stored there.

Scheduled runs (cron on Linux, Task Scheduler on Windows) use the same settings:

```bash
python3 runall.py
```

Skip steps with `--skip`, e.g. `python3 runall.py --skip compare,answers`. Exit code 0 means every step finished.

## Running on a dedicated VM

- Keep the app on 127.0.0.1 (the default). It has no login and holds API keys. Never expose it to the network.
- Reach it with an SSH tunnel (`ssh -L 8000:127.0.0.1:8000 you@vm`), or behind an IT-managed proxy with university sign-in.
- Set keys as environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `PERPLEXITY_API_KEY`, `GEMINI_API_KEY`), not in `keys.json`.
- Run `python3 app.py --no-browser` as a service (systemd on Linux, NSSM on Windows). Schedule `python3 runall.py` monthly.

## How pages are graded

Two parts:

- **Access** (every page): the page loads, AI search bots are allowed, there is no noindex/noai, and its text is in the HTML. Fail any and the page is **Not ready**.
- **Answer quality** (key student pages: the homepage, admissions, cost, aid, visit and program home pages, and the EAB priority pages), 0-100: direct answer 25, proof 25, structure 20, connections 10 (2 of School of Medicine, Admissions, Scholarships and aid, Outcomes and careers), authority 10 (named owner or author, and a date a reader can see), accurate and current facts 10.

Key pages are **Ready** at 70 or more and **Readable, not citable** below that. Other pages (news, directory, events) are Ready when they pass Access. The technical score (share of the 23 checks passed) is still in the Pages CSV and Appendix A. Broken structured data is reported site-wide, not as an Access failure, because AI still reads the page text.

**Site verdict:** Ready when 80% of key pages are citable, no AI search bot is blocked and the homepage organization schema passes; Readable, not citable when 80% of all pages pass Access; otherwise Not ready.

**Rescoring old runs** so trends compare:

```bash
python3 rescore.py old-bundle.zip --report-dir rescored
```

Runs from before version .24 had no outdated-wording check, so their accuracy points are over-credited.

## Page Check tab

Checks one page for everything the site crawl looks for and lists what it found, problems first: the 23 page checks, AI bot access in robots.txt for that page, structured data (and, on the homepage, the 8 organization schema checks), EAB's five priority-page elements, approved proof points and numbers, and outdated or off-brand wording. Takes a few seconds; no crawl.

From the command line:

```bash
python3 pagescan.py https://www.methodist.edu
```

Add `--json` for the full result, or `--report page-check.html` to also write a printable report. In the app, **Open report** and **Download report** appear after each check: a one-page summary with problems to fix (each with how to fix it and who owns it), items worth checking, what is working, and every check.

## Findability tab

Starts on one page and follows links up to 3 clicks to find the facts a student looks for. Two topic sets:

- **School of Medicine** (start pages under `/academics/medicine/`): tuition and cost, financial aid, application deadline, MCAT and GPA, Monarch Momentum, accreditation, class size, residency match.
- **Undergraduate (first-year)** (the homepage and undergraduate admissions pages): tuition and cost, aid and FAFSA, application deadline, GPA and test policy, number of majors, student-faculty ratio, first-year housing, job and graduate-school outcomes.

The set is picked from the start address, or chosen in the Topics menu. A set's facts count only on its own pages (School of Medicine pages; undergraduate admissions, Explore MU and housing pages), or elsewhere when the subject is named next to the fact. Starting from the homepage with the School of Medicine set therefore answers "how far is School of Medicine information from the homepage". The report warns when the start page is outside the set's pages or no set matched.

For each topic it reports the closest page that states the fact, the clicks, the path, and the status:

| Status | Meaning |
|---|---|
| OK | Stated in page text, on the start page or one click away through a link in page text. |
| Buried | Stated in page text, but 2 or more clicks away or reached only through menus. |
| PDF only | Not stated on any page reached; a PDF about it is linked (PDF contents not read). |
| No figure | A page about it was reached, but no page states the fact. |
| Not found | Nothing about it within the click limit. |

Rules: menus, headers, footers, sidebars and text inside video frames don't count as stating a fact. A page outside the section counts only when the medical school is named near the fact (so a history page's "$50,000 annually" or an undergraduate GPA rule is not counted). People, news and event pages are not counted, and a tuition match next to "remission", "scholarship" or "award" is skipped. Pages inside the start page's section are followed; pages outside it are read but not followed. Topics and their word patterns are in `messages.json` under `findability`; add a topic set for another section the same way. Open report gives a printable version.

Command line: `python3 findability.py https://www.methodist.edu/academics/medicine/ --report findability.html`

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

## WordPress check

If the site runs WordPress and exposes its public page list (`/wp-json/wp/v2/`), the crawl also reads every published page, post and media file. It then:

- crawls published pages that are not in the sitemap, and lists the ones no page links to ("hidden"). These go stale unnoticed.
- flags media addresses that look like an old page, such as `/academics/medicine-2/` opening `medicine.jpg` because `/academics/medicine/` is a page. These were usually real pages once, and search results may still show their old text.

If the list is turned off or blocked, the report says so and the crawl continues as normal. Competitor crawls skip this check.

## Outdated wording and manual actions

`messages.json` has two more lists:

- `outdated_phrases`: wording that was true once and is not now (LCME applicant/candidate status, School of Medicine "will open" or "pending approval", "MU College of Medicine", Fort Liberty, Pope Air Force Base, Twitter, COVID-era notices, old copyright years). The crawl lists every page that uses each one, separates news posts (add an update note) from live pages (rewrite), and marks phrases on nearly every page as a site-template fix. Results are in Appendix G and the Action plan.
- `manual_actions`: fixes found outside the crawl (for example a page no link points to). They are added to the Action plan; `"priority": "high"` puts them near the top.

## Ask the AIs tab

Type any question and send it to Claude, ChatGPT, Perplexity and Gemini at once, with web search on, the same way the answer test asks. Each answer appears as soon as that AI finishes, labeled with whether it names MU, whether it cites methodist.edu, the colleges it names and its sources. Every question and its answers are saved on this computer in `ask-history.jsonl` (never keys), and "Earlier questions" reopens them. Uses the keys saved on the AI Answers tab; each question costs about the same as one test question per AI.

## AI Answers tab

Sends a question bank to AI assistants with web search on and scores the answers. Needs API keys (Anthropic Console, OpenAI Platform, Perplexity API settings, Google AI Studio). Run any subset of providers. Keys are saved to `keys.json` on your computer only; it is gitignored and never enters the results bundle.

- `questions.json`: 41 branded questions (name MU) and 42 category questions (do not), from EAB's audit prompts, admitted-student survey themes, and new-medical-school FAQs (M01-M24; run them alone with "Medical school only"). Each can have `must_contain` / `must_not_contain` rules (regular expressions) for accuracy scoring.
- Per answer: **mentioned** (names MU), **cited** (a search result or citation is on methodist.edu), **accurate** (all required facts present, branded only), **confused** (mixed up with another "Methodist" school), peers named, other sources used.
- Summary: branded mention %, category mention %, citation rate, accuracy, confusions, who gets named on category questions, and which third-party sites the AIs relied on.
- Providers: Claude (`claude-sonnet-5-5`, Anthropic web search tool; switched from Opus 5.5 to cut cost, so Claude results from runs before version .38 are not strictly comparable), ChatGPT (OpenAI Responses API with web search), Perplexity (Agent API, `POST /v1/agent`; the model box takes an effort level, default `low` (Pro Search) or `fast` (like free Perplexity; often skips the search), or a model id such as `openai/gpt-6-luna`, which runs with the `web_search` tool; needs paid Agent API credit; per-run cost is reported) and Google Gemini (`gemini-2.5-flash` with Google Search grounding). Model names are editable under Keys; "List my models" fills the OpenAI and Gemini pickers from the key's own account. Gemini has a free tier; Google AI Overviews themselves have no API, so grounded Gemini is the closest stand-in.
- Cost: roughly a dollar or two per provider for a full run. "Quick test (2)" runs one branded and one category question. A full run is 83 questions per provider.
- Re-run monthly. The latest run goes into the results bundle (answers.json/csv/html) and Appendix I of the executive report.

```bash
python3 answers.py --out ai-answers.html --csv ai-answers.csv
```

Keys can also come from environment variables, which take precedence over keys saved in the app: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `PERPLEXITY_API_KEY`, `GEMINI_API_KEY`. To check one provider with a single minimal request (prints only the status, never the key):

```bash
python3 answers.py --smoke perplexity
```

## Branded, niche and broad questions

Every question has a `scope` in `questions.json`:

- **branded**: names MU. AI should name MU nearly every time; accuracy is scored here.
- **niche**: general, but only a few schools are right answers (PGA Golf Management, OT doctorate, Fayetteville, United Methodist, new medical schools). A high rate is expected.
- **broad**: general, with many possible answers (best value, financial aid, nursing, pre-med). **This is the number to grow.**

Reports show mention rates for all three, plus **citation share**: methodist.edu's share of all sources cited (EAB's measure), next to "cites methodist.edu" (share of answers citing it at all). The "Compared with EAB" table uses broad questions against the benchmarks in `questions.json`, and "Share of voice" ranks the EAB AI peer set on broad questions.

## Repeated key questions

The 30 School of Medicine and accuracy-rule questions (`"repeat": 3` in `questions.json`) are asked 3 times, with Claude at medium effort, because one answer can be a fluke. Headline rates use the first answer only, so runs stay comparable. The Consistency table shows, for each question and provider, how many of the 3 answers mentioned, cited and got it right, and marks any that changed between repeats. A full run is 143 answers per provider.

## Pages not graded

- App, login and donation pages (apply, donate, appointment, portals, help desk, file transfer, pages titled "Log in") are skipped and counted under "skipped".
- Filtered or paged copies (an address with "?" whose canonical tag points to another page) are not graded or counted in page totals; their links are still followed so deeper pages are found.
- In the report, a host that is entirely blocked or noindexed (an internal system) and sections that are entirely noindexed are left out of critical counts on page 1 and in Appendix A, with a note saying so.

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
