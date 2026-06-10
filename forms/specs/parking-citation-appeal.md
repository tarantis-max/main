# Parking/Traffic Citation Appeal — Build Spec

**Priority:** P1 (Student Home) + P3 (Forms and Documentation) — one form, two portal placements
**Complexity:** Simple · **Dept:** Public Safety
**Purpose:** Student, faculty, or staff files an appeal for a parking/traffic citation.

## Settings
- Respondents: students, faculty, staff (all Experience users)
- Availability: always open

## Sections & fields

### 1. Appellant Information (prefilled, read-only)
| Field | Type | Binding |
|---|---|---|
| Name / ID / Email | Label | Respondent (delivered) |
| Affiliation | Single choice: Student / Faculty / Staff | — confirm if derivable from respondent data; otherwise ask |

### 2. Citation Details
| Field | Type | Required | Notes |
|---|---|---|---|
| Citation number | Text | Yes | |
| Date citation issued | Date | Yes | |
| Location of violation | Text | Yes | |
| Violation type (as written on citation) | Text | Yes | |
| Vehicle (make/model/color) | Text | Yes | |
| License plate | Text | Yes | |
| Parking permit number | Text | No | |

### 3. Appeal
| Field | Type | Required | Notes |
|---|---|---|---|
| Grounds for appeal | Long text | Yes | |
| Supporting evidence | Upload | No | Confirm upload field type availability; otherwise instruct to email Public Safety with citation number |

### 4. Certification
| Field | Type | Required |
|---|---|---|
| Statements are true and accurate | Checkbox | Yes |
| Signature (typed name + date) | Text + Date | Yes |

## Routing / response handling
- Public Safety / appeals committee reviews via Responses tab.
- View Response Data: Public Safety role only.
- Decision communicated by email — outside Forms.

## Open questions
- Appeal deadline (e.g., within X business days of citation)? State it in form intro text.
- Does Public Safety want the appeals committee to see appellant identity, or reviewed blind?
