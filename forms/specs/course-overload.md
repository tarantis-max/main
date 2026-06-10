# Course Overload Form — Build Spec

**Priority:** P1 · **Complexity:** Complex · **Dept:** Registration
**Tracker note:** *Discuss with Keri* — rules below are placeholders until confirmed.
**Purpose:** Student requests to register above the maximum credit-hour load for a term.

## Settings
- Respondents: students
- Availability: open during registration windows (set open/close dates per term)

## Sections & fields

### 1. Student Information (prefilled, read-only)
| Field | Type | Binding |
|---|---|---|
| Name / Student ID / Email | Label | Respondent (delivered) |
| Academic program | Label | Academic program (delivered) |
| Cumulative GPA | Label | Custom data source (confirm field availability) |
| Current registered hours | Label | Student sections/courses data source |

### 2. Overload Request
| Field | Type | Required | Notes |
|---|---|---|---|
| Term | Dropdown | Yes | Academic period (delivered) |
| Requested total credit hours | Number | Yes | |
| Course(s) to add (subject/number/title/credits) | Repeating text rows or long text | Yes | |
| Justification | Long text | Yes | |

### 3. Acknowledgement
| Field | Type | Required | Notes |
|---|---|---|---|
| Additional tuition charges acknowledgement | Checkbox | Yes | Confirm overload billing language with SFS |
| Signature (typed name + date) | Text + Date | Yes | |

## Rules to confirm with Keri (what makes this Complex)
- Max standard load and absolute overload cap (e.g., 18 → 21)?
- GPA threshold for eligibility, and is it enforced (visibility/validation rule on GPA field) or advisory?
- Approval chain: advisor → registrar? Dean for higher loads?
- Different limits for summer terms?

## Routing / response handling
- Registrar reviews via Responses tab; View Response Data: Registrar role.
