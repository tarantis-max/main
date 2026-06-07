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

## Export

**Export CSV** downloads the currently filtered set of projects as a CSV with the
original column headers — handy for sharing a slice (e.g. all Red projects).

## Source data

Generated from `MU_VPMO_Program_Plan_v4.xlsx` (data as of 2026-05-21).
