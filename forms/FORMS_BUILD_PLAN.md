# MU Ellucian Forms (EIP) Build Plan — Lane 2

Source: `MU_Forms_Tracker_Consolidated.xlsx` (June 2026) + Ellucian Forms documentation (March 2026).
Scope: the 37 forms tagged **Lane 2 — EIP (in-house)**, built in Ellucian Forms by Andrew Dunn / Austin Bogdany.
Machine-readable queue: [`lane2_eip_queue.csv`](lane2_eip_queue.csv).

## Status at a glance (as of June 10, 2026)

| Priority | Target | Forms | Status |
|---|---|---|---|
| P1 | Apr 1 | 8 | All still "In Progress" — **past target** |
| P3 | Jun 1 | 2 | In Progress (1 is a duplicate of a P1 form) — **past target** |
| P4 | Jul 1 | 27 | 23 TBD (DPT cluster), 4 Needed — **next deadline** |

## Effective build count: ~31 unique builds, fewer with templates

Several tracker rows collapse:

- **Parking/Traffic Citation Appeal** appears twice (P1 "Student Home" and P3 "Forms and Documentation") — one form, surfaced in two portal locations.
- **Change of Grade Request** (Fall 24-25, Spring 24-25, Summer 23-24) — tracker note: *"We may just need one form with settings to open and close on particular dates."* Build **one** form; Forms settings support availability windows. The term should be a field (academic period delivered data source), not three forms.
- **VA Request for Certification (Summer)** — tracker flags it as a duplicate of the prior-year variant. One form, term-driven.
- **17 DPT lab/cadaver release forms** — identical pattern (course number + release text + signature). Build **one template**, duplicate per course (Forms supports Duplicate), or evaluate a single form with a course picker if DPT agrees.

## Build waves

### Wave 1 — finish the overdue P1 set (8 forms, In Progress)

| Form | Dept | Complexity | Notes |
|---|---|---|---|
| Course Substitution Request | Forms & Documentation | Simple | |
| Change of Academic Program (was "Degree Information Update Request") | Forms & Documentation | Simple | Renamed per tracker |
| Course Overload Form | Registration | **Complex** | Discuss with Keri; likely needs GPA/credit-hour rules |
| Directed Study / Independent Study | Registration | Simple | |
| Parking/Traffic Citation Appeal | Student Home | Simple | Also satisfies the P3 row |
| VA Benefits Statement | Veteran Services | Simple | Signals work to Student Financial Services |
| Requirements for Receiving VA Benefits | Veteran Services | Simple | |
| VA Request for Certification of Educational Benefits | Veteran Services | Simple | One term-driven form; retire year-named variants |

### Wave 2 — remaining P3 + P4 registrar forms (by Jul 1)

| Form | Dept | Complexity |
|---|---|---|
| Faculty/Staff Vehicle Registration | Forms & Documentation | Simple |
| Change of Grade Request (single, term-driven) | Forms & Documentation | Simple |
| Incomplete Grade Request | Student | Simple |
| Transient Student Approval | Student | **Complex** |

### Wave 3 — DPT cluster (23 rows → ~7 distinct builds), owner Meredith Gronski

1. **Lab/Cadaver Release template** → duplicated for 17 courses (DPT 5200–7240)
2. Clinical Education Manual Acknowledgement (**Complex**)
3. Clinical Education Release of Information (**Complex**)
4. DPT 5200 Anatomy Lab Locker Use Acknowledgement
5. Photo and Video Release
6. Student Handbook Acknowledgement

All DPT rows are status TBD — confirm scope/requirements with Meredith Gronski before building.

## Data sources

Forms data sources are GET-only and come from delivered sources, Ethos APIs, or Data Connect **serverless API** pipelines (this repo). Delivered data sources cover most simple forms:

- **Respondent** (delivered) — name, ERP ID, email: every form
- **Academic period** (delivered) — term pickers: Change of Grade, VA Certification, Course Overload, Directed Study
- **Academic program** (delivered) — Change of Academic Program, Course Substitution

**Custom data sources already exist in the tenant.** Map them to fields during each build — typical bindings:

| Form need | Used by |
|---|---|
| Student current sections/courses | Course Substitution, Course Overload, Incomplete Grade, Change of Grade |
| Advisor lookup | Course Overload, Directed Study, Transient Student |
| Faculty sections taught | Change of Grade (faculty-facing) |

## Build conventions

1. **Forms roles/permissions** in Experience: decide who gets "View Response Data" per department (VA and DPT forms carry sensitive data — set field sensitivity levels accordingly).
2. **Export discipline**: after each form is published, export the JSON (`FormName_v1.0.0.json`) and commit it under `forms/exports/` in this repo so definitions are versioned and portable between environments.
3. **Per-form build specs** live in [`specs/`](specs/) — field-by-field designs to follow in the Forms Designer.

## Open questions

- Course Overload: requirements from Keri (what rules make it Complex?)
- DPT cluster: confirm with Meredith Gronski whether 17 release forms can be one template/picker
- Change of Grade: confirm single term-driven form replaces the three year-named rows
- Where do submissions land? Forms responses are viewable in-app; if data must flow to Colleague or a workflow, that's a separate destination decision per form (Actions require Experience Premium / IPA license)
