# MU VPMO — Program Management Dashboard

> **There's now a full React front end in [`app/`](../app/README.md)** with a
> Portfolio view (this dashboard), Change Management, an issue browser with
> JQL, full issue detail/editing, a drag-and-drop workflow board, and
> sprints/backlog. `server.js` serves it automatically once it's built
> (`cd app && npm install && npm run build` — `start.bat` does this for you).
> This single-file dashboard remains available at **`/legacy`**, and is served
> at `/` whenever the app isn't built.

An interactive, single-file dashboard for the Methodist University VPMO program
plan. **Jira is the system of record:** the dashboard starts empty and loads
live from any Jira project you pick, and you can edit items and create new work
items straight from the page. A one-time spreadsheet import is also supported.

There's no build step and no dependencies — `index.html` is plain HTML/JS and
`server.js` is a zero-dependency Node proxy that holds your Jira token.

## What it shows

- **KPI cards** — total/active projects, average % complete (active), Red &
  Yellow counts, projects due within 90 days, and overdue projects.
- **Charts** — projects by phase, active projects by portfolio, and a Risk-status
  donut. Click any bar or legend item to filter the whole dashboard.
- **Board view** — a Kanban board grouped by phase (Planning → In-Flight →
  Stabilization → Closed), with Risk color-coding, progress bars, and
  overdue/due-soon badges.
- **Table view** — every column from the plan, sortable by clicking headers,
  with inline progress bars and dependency hints.
- **Project detail** — click any card or row for full sponsor, owner, dates,
  dependencies, compliance driver, and the latest notes / next milestone.
- **Filters** — search box plus portfolio, phase, Risk, and IT-owner dropdowns.
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
`IT Owner`, `Start Date`, `Target End`, `% Complete`, `Risk`, `Dependencies`,
`Compliance Driver`, `Notes / Next Milestone`.

- `% Complete` accepts a fraction (`0.55`) or a percent (`55`).
- Dates accept Excel serial numbers or any standard date string.
- `Phase` values: Planning, In-Flight, Stabilization, Closed.
- `Risk` values: Green, Yellow, Red.

## Live data from Jira

The dashboard pulls **live** from Jira via a tiny built-in proxy (`server.js`).
The proxy holds your Jira API token server-side, so the browser never sees
credentials and there are no CORS issues.

### Pulling from any project

When the proxy is running, a **project picker** appears in the header, populated
with every Jira project you can see. Pick one and the board reloads from it;
each project caches independently for 60s. The default selection comes from
`JIRA_PROJECT` (falls back to `ITPM`). "Projects" on the board are top-level
issues (Epics and any Story/Task without a parent); sub-tasks roll up into their
parent's percentage.

### Creating a work item

With the proxy running, click **New work item** to create an issue directly in
the selected project. Choose the issue type (the dropdown lists the types that
project actually offers), set name, phase, Risk, portfolio, sponsor, compliance,
Project ID, dates, and notes, then **Create in Jira**. The issue is created with
native fields first, then VPMO metadata is applied (custom fields where present,
labels otherwise), and the board refreshes so the new item appears.

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
| Name | issue `summary` |
| Key | issue key (used for write-back; shown in the detail header) |
| Notes | `description` (ADF flattened to text) |
| IT Owner | `assignee` |
| Start Date | `customfield_10015` ("Start date") |
| Target End | `duedate` |
| Phase | `status` → Planning / In-Flight / Stabilization / Closed |
| Dependencies | linked issues (`issuelinks`) |
| Risk | **VPMO field** → label `risk:…` → **derived** from schedule |
| Portfolio | **VPMO field** → label `portfolio:…` → issue type |
| Compliance | **VPMO field** → label `compliance:…` → `N/A` |
| Business Sponsor | **VPMO field** → label `sponsor:…` → `reporter` |
| Project ID | **VPMO field** (e.g. P-001), else blank |
| % Complete | child-issue rollup → **VPMO field** → status |

Each VPMO row uses a **fallback chain**: the custom field value wins; if it's
empty it reads the legacy label; if that's missing it derives a sensible default
(Risk from schedule — overdue → Red; due within 30 days and < 50% → Yellow; else
Green). This means the dashboard works at every stage of Jira buildout — no
fields, labels only, or full custom fields all render correctly.

### Using real custom fields instead of labels (one-time)

Jira has no native Risk / Portfolio / Compliance / Sponsor / Project ID fields,
so without setup the dashboard stores VPMO data as labels (`risk:Yellow`,
`portfolio:Infrastructure`, …). To use proper typed fields, pick the path that
matches your project type:

**Team-managed projects (ITPM is one)** — these only use fields created
*inside* the project; global custom fields can't be attached to them, and the
API can't create per-project fields. So it's a two-step:

1. In Jira: **ITPM → Project settings → Issue types**, and for *each* issue
   type add these custom fields (exact names matter):

   | Field name | Type |
   |---|---|
   | `Risk` | Dropdown — Green, Yellow, Red |
   | `Portfolio` | Short text |
   | `Compliance Driver` | Short text |
   | `Business Sponsor` | Short text |
   | `Project ID` | Short text |
   | `% Complete` | Number |
   | `Change Type` | Dropdown — Standard, Normal, Emergency |
   | `CR Impact` | Dropdown — Low, Medium, High |
   | `Affected Systems` | Short text |
   | `Rollback Plan` | Paragraph |

2. Then discover + map their IDs automatically:

   ```bash
   node dashboard/setup-jira-fields.js --map ITPM
   ```

   It scans the project's real fields by name, writes
   `dashboard/vpmo-fields.json`, and tells you exactly which fields are still
   missing (those keep using labels). Restart `server.js` to apply.

**Company-managed projects** — create the fields globally in one shot:

```bash
export JIRA_BASE_URL="https://methodist.atlassian.net"
export JIRA_EMAIL="jgreene@methodist.edu"
export JIRA_TOKEN="<Atlassian API token>"
node dashboard/setup-jira-fields.js
```

It creates the VPMO fields (skipping any that exist) and writes
`vpmo-fields.json`. Add them to the project's screens in Jira admin.

Either way, the proxy stays safe by design: writes go to the mapped custom
field first, and if a particular project rejects it (field not available
there) the write automatically retries as a label. Existing label data keeps
being read as the fallback, so nothing breaks mid-migration. Mappings can also
be edited by hand in `vpmo-fields.json` (e.g. to point `portfolio` at ITPM's
built-in **Category** field).

## Editing and commenting

When the dashboard is loaded **from Jira** (via the proxy), each project's detail
view becomes two-way — changes write straight back to the Jira issue. (These
controls are hidden in spreadsheet mode, since there's no issue to update.)

**Edit a work item** — click **Edit** in the detail header to change:

| Field | Writes to Jira as |
|---|---|
| Phase | a **status transition** (matched to your workflow by name, then status category) |
| Risk | VPMO Risk custom field, else `risk:` label |
| Target End | `duedate` |
| Portfolio | VPMO Portfolio custom field, else `portfolio:` label |
| Compliance | VPMO Compliance custom field, else `compliance:` label |
| Notes | `description` |

Click **Save to Jira**. Only fields you actually changed are sent (no needless
writes), existing non-VPMO labels are preserved, and the board/table update
immediately. The confirmation shows which workflow transition was applied
(e.g. *"Saved to Jira — status → Done"*). IT Owner is shown read-only because
changing it needs a Jira user-account lookup; edit it in Jira directly.

**Comment on a work item** — the **Comments** section lists existing Jira
comments (author + timestamp) and has a box to add a new one. Posting writes the
comment to the issue and refreshes the list.

## Export

**Export CSV** downloads the currently filtered set of projects as a CSV with the
original column headers — handy for sharing a slice (e.g. all Red projects).

## Data sources

- **Jira live** (primary): any project you select in the header picker, via the
  proxy. Defaults to `JIRA_PROJECT` (or `ITPM`).
- **Spreadsheet** (one-time import): use **Update from spreadsheet** to load an
  `.xlsx`/`.csv` export — handy for the initial migration before the data lives
  in Jira.

The intended workflow is: stand the dashboard up against Jira, run
`setup-jira-fields.js` once, import or create your projects, and from then on
Jira is the single source of record — the spreadsheet is no longer needed.
