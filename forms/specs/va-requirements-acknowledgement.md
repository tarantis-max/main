# Requirements for Receiving VA Benefits — Build Spec

**Priority:** P1 · **Complexity:** Simple · **Dept:** Veteran Services
**Purpose:** Student acknowledges responsibilities for maintaining VA education benefits.

## Settings
- Respondents: students
- Availability: always open
- Sensitivity: restrict View Response Data to Veteran Services role.

## Sections & fields

### 1. Student Information (prefilled, read-only)
| Field | Type | Binding |
|---|---|---|
| Name / Student ID / Email | Label | Respondent (delivered) |

### 2. Requirements (static text, provided by Veteran Services)
Typical items — confirm final language:
- Report all schedule changes (add/drop/withdrawal) to the School Certifying Official immediately
- Only courses required by the declared degree program can be certified
- Repeating a passed course is not certifiable
- Report changes of major or address
- Understand debt/overpayment consequences of non-attendance or withdrawal

### 3. Acknowledgement
| Field | Type | Required |
|---|---|---|
| I have read and agree to the requirements | Checkbox | Yes |
| Signature (typed name + date) | Text + Date | Yes |

## Routing / response handling
- Veteran Services keeps acknowledgement on file per student.

## Open questions
- Once per student, or re-acknowledged each academic year?
- Combine with the VA Benefits Statement form? They share respondent flow — confirm with Veteran Services whether one onboarding form would serve both.
