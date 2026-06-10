# MU Jira — React front end

A full Jira front end for Methodist University, built with React + Vite and
served by the same zero-dependency proxy (`dashboard/server.js`) that holds the
Jira API token server-side. The browser never sees credentials.

## Views

| View | What it does |
|---|---|
| **Portfolio** | The VPMO program dashboard: KPI cards, portfolio/risk charts, phase Kanban, sortable table, project detail with edit + comments, new work item. |
| **Changes** | ITIL change management: CR list with KPIs, CAB approval workflow (approve / reject / implement / close), approval history, new CR form. |
| **Issues** | Issue browser for any project: text/key search or raw JQL, paginated results, click through to detail. |
| **Issue detail** | Everything on an issue: inline summary/description edit, status transitions, assignee picker (user search), priority, due date, labels, sub-tasks, links, attachments (downloaded through the proxy), comments, VPMO fields. |
| **Board** | Drag-and-drop board built from the project's **real workflow statuses** (works for company- and team-managed, business and software projects). Dropping a card applies the matching workflow transition. |
| **Backlog** | Sprints + backlog via the Jira Software agile API; move issues between sprints and backlog. Business projects without a board get a friendly note. |

The project picker in the top bar scopes every view; the selection persists
across reloads. The original single-file dashboard remains available at
`/legacy`.

## Running

**Production (how `start.bat` works):** build once, then the proxy serves the
static build — no Node process for the front end at runtime.

```bash
cd app
npm install
npm run build        # outputs app/dist

# then start the proxy as usual; it auto-serves app/dist when present
node ../dashboard/server.js     # http://localhost:8787
```

`dashboard/start.ps1` does the install + build automatically on first run.
If `app/dist` is missing (e.g. npm unavailable), `server.js` falls back to
serving the legacy dashboard at `/` exactly as before.

**Development (hot reload):**

```bash
node dashboard/server.js   # terminal 1 — the API proxy on :8787
cd app && npm run dev      # terminal 2 — Vite on :5173, proxies /api → :8787
```

## How it talks to Jira

All requests go through `dashboard/server.js` (`/api/...`), which adds the
Basic auth header server-side:

- `/api/jira/projects` — project picker
- `/api/projects` — VPMO-mapped projects (Portfolio view), PATCH to edit, POST to create
- `/api/changes` — change requests + approval actions
- `/api/issues` — JQL search (paginated), `/api/issues/:key` GET/PUT, `/transition`
- `/api/users?q=` — assignee search
- `/api/board?project=` — workflow statuses + issues for the drag-drop board
- `/api/agile/...` — boards, sprints, backlog, and sprint/backlog moves
- `/api/attachments/:id/...` — attachment download proxy
