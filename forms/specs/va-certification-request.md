# Request for Certification of Educational Benefits — Build Spec

**Priority:** P1 · **Complexity:** Simple · **Dept:** Veteran Services
**Tracker note:** year-named variants (Summer 2023-24, Summer 2024-25) are duplicates — build **one term-driven form** and retire the variants.
**Purpose:** Student requests the School Certifying Official certify enrollment to the VA for a term.

## Settings
- Respondents: students
- Availability: always open (term selected in-form)
- Sensitivity: restrict View Response Data to Veteran Services role; mark benefit fields sensitive.

## Sections & fields

### 1. Student Information (prefilled, read-only)
| Field | Type | Binding |
|---|---|---|
| Name / Student ID / Email | Label | Respondent (delivered) |
| Academic program | Label | Academic program (delivered) |

### 2. Certification Request
| Field | Type | Required | Notes |
|---|---|---|---|
| Term to certify | Dropdown | Yes | Academic period (delivered) — replaces year-named form titles |
| Benefit chapter | Single choice (same list as Benefits Statement) | Yes | |
| Enrolled courses for the term | Pre-populated multi-choice or read-only list | Yes | Bind to student sections/courses data source |
| Any courses NOT toward your degree? | Yes/No + explain | Yes | |
| Changed program or school since last certification? | Yes/No + explain | Yes | |

### 3. Acknowledgement
| Field | Type | Required |
|---|---|---|
| I will report schedule changes to the SCO | Checkbox | Yes |
| Signature (typed name + date) | Text + Date | Yes |

## Routing / response handling
- School Certifying Official processes in VA Enrollment Manager; Responses tab is the work queue.

## Open questions
- Submit once per term or once per year with term checkboxes?
- Ch 33: does SFS need a copy/notification for anticipated-payment posting?
