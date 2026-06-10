# Course Substitution Request — Build Spec

**Priority:** P1 · **Complexity:** Simple · **Dept:** Forms and Documentation (Registrar)
**Purpose:** Request that a completed/planned course satisfy a degree requirement in place of the required course.

## Settings
- Respondents: students (advisor-submitted variant — confirm with Registrar)
- Availability: always open

## Sections & fields

### 1. Student Information (prefilled, read-only)
| Field | Type | Binding |
|---|---|---|
| Name | Label | Respondent (delivered) |
| Student ID | Label | Respondent (delivered) |
| Email | Label | Respondent (delivered) |
| Academic Program / Catalog | Label | Academic program (delivered) |

### 2. Substitution Details
| Field | Type | Required | Notes |
|---|---|---|---|
| Degree requirement to be satisfied | Text | Yes | |
| Required course (subject, number, title) | Text | Yes | |
| Substitute course | Dropdown | Yes | Bind to student sections/courses data source; fall back to text if course not yet taken at MU |
| Substitute course credits | Number | Yes | |
| Where taken | Single choice: MU / Transfer | Yes | |
| Rationale | Long text | Yes | |

### 3. Acknowledgement
| Field | Type | Required |
|---|---|---|
| Advisor discussed (checkbox) | Checkbox | Yes |
| Signature (typed name + date) | Text + Date | Yes |

## Routing / response handling
- Registrar reviews via Responses tab (View Response Data: Registrar role only).
- Approval workflow (advisor → registrar) is outside Forms unless IPA/Actions is licensed — confirm.

## Open questions
- Who submits: student, advisor, or both?
- Does Registrar need transfer-course substitutions on the same form?
