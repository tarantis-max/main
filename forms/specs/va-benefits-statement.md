# VA Benefits Statement — Build Spec

**Priority:** P1 · **Complexity:** Simple · **Dept:** Veteran Services
**Purpose:** Communicate benefits to the student and signal work to do in Student Financial Services.

## Settings
- Respondents: students
- Availability: always open
- Sensitivity: VA benefit data — restrict View Response Data to Veteran Services + SFS roles; mark benefit fields sensitive.

## Sections & fields

### 1. Student Information (prefilled, read-only)
| Field | Type | Binding |
|---|---|---|
| Name / Student ID / Email | Label | Respondent (delivered) |

### 2. Benefit Information
| Field | Type | Required | Notes |
|---|---|---|---|
| Benefit chapter | Single choice: Ch 33 Post-9/11 / Ch 30 MGIB / Ch 35 DEA / Ch 31 VR&E / Ch 1606 / Other | Yes | |
| Percentage of eligibility (Ch 33) | Number | Cond. | Visibility rule: only when Ch 33 selected |
| First term using benefits at MU | Dropdown | Yes | Academic period (delivered) |
| Are you also using Tuition Assistance? | Yes/No | Yes | |

### 3. Statement & Acknowledgement
| Field | Type | Required | Notes |
|---|---|---|---|
| Benefits statement text | Static text | — | Veteran Services provides the statement language |
| I have read and understand my benefits | Checkbox | Yes | |
| Signature (typed name + date) | Text + Date | Yes | |

## Routing / response handling
- Veteran Services certifies; SFS uses submission as the trigger for account work (deferment, anticipated aid).
- Confirm how SFS gets notified — shared View Response Data access, or scheduled review.

## Open questions
- Exact statement language from Veteran Services.
- Once per student, or per academic year?
