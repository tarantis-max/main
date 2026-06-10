# Directed Study / Independent Study — Build Spec

**Priority:** P1 · **Complexity:** Simple · **Dept:** Registration
**Purpose:** Request approval to take a course as directed/independent study.

## Settings
- Respondents: students
- Availability: always open (or registration windows — confirm)

## Sections & fields

### 1. Student Information (prefilled, read-only)
| Field | Type | Binding |
|---|---|---|
| Name / Student ID / Email | Label | Respondent (delivered) |
| Academic program | Label | Academic program (delivered) |

### 2. Study Details
| Field | Type | Required | Notes |
|---|---|---|---|
| Study type | Single choice: Directed Study / Independent Study | Yes | |
| Term | Dropdown | Yes | Academic period (delivered) |
| Course subject & number | Text | Yes | |
| Course title | Text | Yes | |
| Credit hours | Number | Yes | |
| Supervising instructor | Text or dropdown | Yes | Bind to faculty data source if available |
| Reason course is needed this way | Long text | Yes | e.g., not offered this term, schedule conflict, graduation requirement |
| Description of work / meeting plan | Long text | Yes | |

### 3. Acknowledgement
| Field | Type | Required |
|---|---|---|
| Signature (typed name + date) | Text + Date | Yes |

## Routing / response handling
- Needs instructor, department chair, and (confirm) dean approval — outside Forms unless IPA/Actions licensed. Registrar registers the student after approvals.
- View Response Data: Registrar role.

## Open questions
- Distinct policies/fees for directed vs independent study?
- Is a syllabus attachment required? (Confirm whether an upload field type is available/allowed.)
