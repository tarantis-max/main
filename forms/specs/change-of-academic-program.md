# Change of Academic Program — Build Spec

**Priority:** P1 · **Complexity:** Simple · **Dept:** Forms and Documentation (Registrar)
**Tracker note:** renamed from "Degree Information Update Request Form".
**Purpose:** Student requests a change of major/minor/concentration or catalog year.

## Settings
- Respondents: students
- Availability: always open

## Sections & fields

### 1. Student Information (prefilled, read-only)
| Field | Type | Binding |
|---|---|---|
| Name / Student ID / Email | Label | Respondent (delivered) |
| Current program(s) | Label | Academic program (delivered) |

### 2. Requested Change
| Field | Type | Required | Notes |
|---|---|---|---|
| Change type | Multi choice: Add major / Drop major / Change major / Add-drop minor / Change concentration / Change catalog year | Yes | |
| New program | Dropdown | Cond. | Bind to academic program (delivered) data source |
| New minor / concentration | Dropdown or text | Cond. | Visibility rule on change type |
| Effective term | Dropdown | Yes | Academic period (delivered) |
| Reason (optional) | Long text | No | |

### 3. Acknowledgement
| Field | Type | Required |
|---|---|---|
| I understand this may change my degree requirements/advisor | Checkbox | Yes |
| Signature (typed name + date) | Text + Date | Yes |

## Routing / response handling
- Registrar processes in Colleague; advisor reassignment handled internally.
- View Response Data: Registrar role.

## Open questions
- Does a program change require current-advisor sign-off before Registrar processes?
- Should catalog-year change be a separate form?
