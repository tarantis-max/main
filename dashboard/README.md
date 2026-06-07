# MU VPMO — Program Management Dashboard

An interactive, single-file dashboard for the Methodist University VPMO program
plan. Open `dashboard/index.html` in any modern browser — no server, build step,
or internet connection required.

## What it shows

- **KPI cards** — total/active projects, average % complete (active), Red &
  Yellow counts, projects due within 90 days, and overdue projects.
- **Charts** — projects by phase, active projects by portfolio, and a RAG-status
  donut. Click any bar or legend item to filter the whole dashboard.
- **Board view** — a Kanban board grouped by phase (Planning → In-Flight →
  Stabilization → Closed), with RAG color-coding, progress bars, and
  overdue/due-soon badges.
- **Table view** — every column from the plan, sortable by clicking headers,
  with inline progress bars and dependency hints.
- **Project detail** — click any card or row for full sponsor, owner, dates,
  dependencies, compliance driver, and the latest notes / next milestone.
- **Filters** — search box plus portfolio, phase, RAG, and IT-owner dropdowns.
- **Edit & comment** (live Jira mode only) — change fields and post comments
  straight to the Jira issue. See [Editing and commenting](#editing-and-commenting).

## Updating from a spreadsheet

The dashboard ships with the current plan baked in, but stays current as the plan
evolves:

1. Click **Update from spreadsheet** (or drag-and-drop a file onto the page).
2. Choose an updated `.xlsx` or `.csv` export of the program plan.

The file is parsed entirely in your browser — nothing is uploaded anywhere.
`.xlsx` files are unzipped and read with the browser's built-in
`DecompressionStream`; the parser auto-detects the **Program Plan** sheet and
maps columns by header name, so it tolerates added/reordered columns.

### Expected columns

The header row should contain (names are matched case-insensitively):

`Project ID`, `Project Name`, `Phase`, `Portfolio`, `Business Sponsor`,
`IT Owner`, `Start Date`, `Target End`, `% Complete`, `RAG`, `Dependencies`,
`Compliance Driver`, `Notes / Next Milestone`.

- `% Complete` accepts a fraction (`0.55`) or a percent (`55`).
- Dates accept Excel serial numbers or any standard date string.
- `Phase` values: Planning, In-Flight, Stabilization, Closed.
- `RAG` values: Green, Yellow, Red.

## Live data from Jira

The dashboard can pull **live** from Jira via a tiny built-in proxy
(`server.js`). The proxy holds your Jira API token server-side, so the browser
never sees credentials and there are no CORS issues.

### Running it

**Windows — easiest:** double-click **`start.bat`**. It checks for Node, asks
for your Atlassian API token the first time, and offers to save it. The saved
token is **encrypted with Windows DPAPI** (`jira-token.dat`) so only your
Windows account on that PC can decrypt it — it is never stored in plaintext and
is git-ignored. Then it starts the server and opens your browser.

**Any platform — manual:**

```bash
export JIRA_BASE_URL="https://methodist.atlassian.net"
export JIRA_EMAIL="jgreene@methodist.edu"
export JIRA_TOKEN="<Atlassian API token>"   # id.atlassian.com/manage-profile/security/api-tokens
export JIRA_PROJECT="ITPM"                   # optional (default ITPM)
# optional full override: export JIRA_JQL='project = ITPM ORDER BY created DESC'

node dashboard/server.js
# open http://localhost:8787  →  click "Load from Jira"
```

Node 18+ required (uses built-in `fetch`). Responses are cached for 60s
(`CACHE_MS`). Each project links back to its Jira issue from the detail view.

### How Jira fields map to the dashboard

| Dashboard field | Jira source |
|---|---|
| Project / ID | issue `summary` / issue key |
| Notes | `description` (ADF flattened to text) |
| IT Owner | `assignee` |
| Business Sponsor | label `sponsor:Name`, else `reporter` |
| Start Date | `customfield_10015` ("Start date") |
| Target End | `duedate` |
| Phase | `status` → Planning / In-Flight / Stabilization / Closed |
| % Complete | rolled up from child-issue completion (else status) |
| Dependencies | linked issues (`issuelinks`) |
| RAG | label `rag:Red\|Yellow\|Green`, else **derived** from schedule |
| Portfolio | label `portfolio:Name`, else issue type |
| Compliance | label `compliance:FERPA;GLBA`, else `N/A` |

Jira has no native RAG / Portfolio / Compliance fields, so those are read from
**labels** if you add them (e.g. `portfolio:Infrastructure`, `rag:Yellow`,
`compliance:GLBA`). Until then, RAG is derived from schedule (overdue → Red;
due within 30 days and < 50% complete → Yellow; otherwise Green) and Portfolio
falls back to the issue type. "Projects" are top-level issues (Epics and any
Story/Task without a parent); child issues roll up into their parent's
percentage. Adjust the mapping in the `FIELDS` / `PHASE_MAP` blocks at the top
of `server.js`.

## Editing and commenting

When the dashboard is loaded **from Jira** (via the proxy), each project's detail
view becomes two-way — changes write straight back to the Jira issue. (These
controls are hidden in spreadsheet mode, since there's no issue to update.)

**Edit a work item** — click **Edit** in the detail header to change:

| Field | Writes to Jira as |
|---|---|
| Phase | a **status transition** (matched to your workflow by name, then status category) |
| RAG | `rag:` label |
| Target End | `duedate` |
| Portfolio | `portfolio:` label |
| Compliance | `compliance:` label |
| Notes | `description` |

Click **Save to Jira**. Only fields you actually changed are sent (no needless
writes), existing non-VPMO labels are preserved, and the board/table update
immediately. The confirmation shows which workflow transition was applied
(e.g. *"Saved to Jira — status → Done"*). IT Owner and Sponsor are shown
read-only because changing them needs a Jira user-account lookup; edit those in
Jira directly.

**Comment on a work item** — the **Comments** section lists existing Jira
comments (author + timestamp) and has a box to add a new one. Posting writes the
comment to the issue and refreshes the list.

## Export

**Export CSV** downloads the currently filtered set of projects as a CSV with the
original column headers — handy for sharing a slice (e.g. all Red projects).

## Data sources

- **Spreadsheet** (default, baked in): `MU_VPMO_Program_Plan_v4.xlsx`, data as of
  2026-05-21 — the curated VPMO executive view (42 projects).
- **Jira live** (`ITPM` via the proxy): the IT Project Management portfolio.

Note these are *different sets*: the spreadsheet is the curated program plan,
while ITPM holds IT infrastructure/security delivery work. The broader
Colleague / Element451 / EAB program epics live in the **EPM** project — set
`JIRA_PROJECT=EPM` (or a custom `JIRA_JQL`) to pull those instead.
