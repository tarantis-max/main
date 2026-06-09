# NCICU / Acadeum Transfer Portal — Methodist University Data Onboarding

**Date:** 2026-06-09
**Institution:** Methodist University
**Contact at Acadeum:** bhilton@acadeum.com
**Initiative:** NCICU Transfer Portal (statewide transfer exploration, program evaluation, degree planning)

---

## Overview

Acadeum has requested institutional data from Methodist University to support the NCICU Transfer Portal. Some data has already been submitted. Three datasets remain outstanding.

---

## Outstanding Datasets

| Dataset | Format Required | Status |
|---|---|---|
| Course Catalog | CSV or Excel preferred; HTML/JSON acceptable; **no PDF** | Outstanding |
| Program Inventory | CSV or Excel preferred | Outstanding |
| Program Requirements Breakdown | CSV or Excel preferred | Outstanding |

---

## Source Systems at Methodist University

| Data | System |
|---|---|
| Course Catalog | Colleague (via Ellucian Insights / Data Connect) |
| Program Inventory | Colleague (via Ellucian Insights / Data Connect) |
| Program Requirements | Colleague native degree audit (via Ellucian Insights / Data Connect) |
| Extraction method | PostgreSQL queries against Insights reporting layer + Data Connect pipelines |

> **Note:** Methodist uses Colleague's native degree audit module — not DegreeWorks or Banner CAPP. All three datasets can be sourced from a single system.

---

## Acadeum Data Dictionary — Required Fields

### Course Inventory

| Field | Type | Required |
|---|---|---|
| InstitutionIdentifier | String | Yes |
| CourseIdentifier | String | Yes |
| Subject | String | Yes |
| Number | String | Yes |
| Title | String | Yes |
| Description | String | No |
| CreditUnitType | String (Semester/Quarter/Noncredit) | Yes |
| CreditMinimumValue | Float | Yes |
| CreditMaximumValue | Float | Yes |
| RepeatabilityIndicator | Boolean | Yes |
| EffectiveDate | Date | No |
| ExpirationDate | Date | No |
| Status | Enum: Active/Inactive | No |
| RequisiteDescription | String | No |
| LearningOutcomes | String | No |
| GeneralEducationAssociationDescription | String | No |
| TermAvailabilityDescription | String | No |
| RepeatabilityMaximumCredit | Float | No |
| RepeatabilityMaximumNumber | Integer | No |
| SyllabusURL | String | No |
| StatewideArticulationNumber | String | No |
| AdditionalDetails | String | No |

### Program Inventory

| Field | Type | Required |
|---|---|---|
| InstitutionIdentifier | String | Yes |
| ProgramOfStudyIdentifier | String | Yes |
| CatalogVersion | String | Yes |
| RequiredCourses | String | Yes |
| Total Hours | Integer | Yes |
| Name | String | No |
| Description | String | No |
| Status | Enum: Active/Inactive | No |
| Level | String | No |
| Award | String | No |
| OfferingModality | Enum | No |
| CIP Code | String | No |
| SOCCode | String | No |
| Outcomes | String | No |
| Website | String | No |
| AccreditationAgencyName | String | No |
| EffectiveDate | Date | No |
| ExpirationDate | Date | No |

### Program Requirements

| Field | Type | Required |
|---|---|---|
| InstitutionIdentifier | String | Yes |
| Type | Enum: Pathway/Program | Yes |
| ProgramOfStudyIdentifier | String | Yes |
| ComponentName | String | Yes |
| ComponentReusabilityIndicator | Boolean | Yes |
| SubcomponentName | String | Yes |
| SubcomponentTitle | String | Yes |
| EquivalentCourseTitle | String | Yes |
| InstitutionName | String | No |
| CatalogVersion | String | No |
| Name | String | No |
| ComponentRequiredHours | Float | No |
| ComponentRequiredSubcomponents | Integer | No |
| SubcomponentRequiredHours | Float | No |
| EquivalentCourse | String | No |
| EquivalentCreditHours | Float | No |
| EquivalentCourseOperator | Enum: AND/OR | No |
| TransferCourse | String | No |
| TransferCourseTitle | String | No |
| TransferCreditHours | Float | No |
| TransferCourseOperator | String | No |

---

## Extraction Strategy

### Complexity by Dataset

| Dataset | Complexity | Notes |
|---|---|---|
| Course Catalog | Low | Standard catalog query; filter to active/current year |
| Program Inventory | Low-Medium | Join programs to degrees; derive catalog year from term code |
| Program Requirements | High | Must unnest block → subcomponent → course hierarchy; one row per course per requirement slot |

### Key Transformations Needed

- **Status codes:** Map Colleague `A`/`I` → Acadeum `Active`/`Inactive`
- **Catalog year:** Derive from term code (e.g., `2024FA` → `2024-2025`)
- **Credit hours:** Ensure separate min/max columns for variable-credit courses
- **Modality:** May need manual mapping if not stored cleanly in Colleague
- **Requirements:** Flatten nested block structure into one row per course per subcomponent

---

## Skeleton SQL Queries

> **Note:** Table and column names below are logical placeholders.
> Adapt to your actual Insights schema — browse available tables with:
> ```sql
> SELECT table_schema, table_name
> FROM information_schema.tables
> WHERE table_type = 'BASE TABLE'
>   AND table_schema NOT IN ('pg_catalog', 'information_schema')
> ORDER BY table_schema, table_name;
> ```

---

### Query 1: Course Catalog

```sql
SELECT
    'METHODIST'                          AS "InstitutionIdentifier",
    c.course_id                          AS "CourseIdentifier",
    c.effective_date                     AS "EffectiveDate",
    c.expiration_date                    AS "ExpirationDate",
    CASE WHEN c.status = 'A'
         THEN 'Active' ELSE 'Inactive'
    END                                  AS "Status",
    c.subject_code                       AS "Subject",
    c.course_number                      AS "Number",
    c.title                              AS "Title",
    c.description                        AS "Description",
    'Semester'                           AS "CreditUnitType",
    c.credit_hours_low                   AS "CreditMinimumValue",
    c.credit_hours_high                  AS "CreditMaximumValue",
    COALESCE(c.repeat_ind, FALSE)        AS "RepeatabilityIndicator",
    c.repeat_max_hours                   AS "RepeatabilityMaximumCredit",
    c.repeat_max_count                   AS "RepeatabilityMaximumNumber",
    c.prereq_description                 AS "RequisiteDescription",
    c.term_availability                  AS "TermAvailabilityDescription",
    c.learning_outcomes                  AS "LearningOutcomes",
    c.gen_ed_description                 AS "GeneralEducationAssociationDescription"

FROM courses c                           -- Colleague: COURSES file

WHERE c.status = 'A'
  AND c.effective_date <= CURRENT_DATE
  AND (c.expiration_date IS NULL OR c.expiration_date >= CURRENT_DATE)

ORDER BY c.subject_code, c.course_number;
```

---

### Query 2: Program Inventory

```sql
SELECT
    'METHODIST'                          AS "InstitutionIdentifier",
    p.program_id                         AS "ProgramOfStudyIdentifier",
    p.program_name                       AS "Name",
    p.description                        AS "Description",
    p.catalog_year                       AS "CatalogVersion",
    CASE WHEN p.status = 'A'
         THEN 'Active' ELSE 'Inactive'
    END                                  AS "Status",
    p.effective_date                     AS "EffectiveDate",
    p.expiration_date                    AS "ExpirationDate",
    p.degree_level                       AS "Level",
    d.degree_description                 AS "Award",
    p.program_url                        AS "Website",
    p.outcomes                           AS "Outcomes",
    p.modality                           AS "OfferingModality",
    p.cip_code                           AS "ClassificationOfInstructionalProgramCode",
    p.total_hours_required               AS "Total Hours"

FROM academic_programs p                 -- Colleague: ACAD.PROGRAMS
JOIN degrees d                           -- Colleague: DEGREES
    ON p.degree_code = d.degree_code

WHERE p.status = 'A'
  AND p.degree_level IN ('Bachelor', 'Associate')

ORDER BY p.program_name;
```

---

### Query 3: Program Requirements

```sql
WITH program_components AS (
    SELECT
        p.program_id,
        p.program_name,
        p.catalog_year,
        rb.block_id,
        rb.block_name                    AS component_name,
        rb.required_hours                AS component_required_hours,
        rb.required_subcomponents,
        rb.reusability_indicator
    FROM academic_programs p             -- Colleague: ACAD.PROGRAMS
    JOIN program_req_blocks rb           -- Colleague: requirement block join table
        ON p.program_id = rb.program_id
    WHERE p.status = 'A'
      AND p.degree_level IN ('Bachelor', 'Associate')
),

subcomponents AS (
    SELECT
        pc.program_id,
        pc.program_name,
        pc.catalog_year,
        pc.block_id,
        pc.component_name,
        pc.component_required_hours,
        pc.required_subcomponents,
        pc.reusability_indicator,
        rl.line_id,
        rl.line_name                     AS subcomponent_name,
        rl.line_description              AS subcomponent_title,
        rl.required_hours                AS subcomponent_required_hours
    FROM program_components pc
    JOIN requirement_lines rl            -- Colleague: requirement lines
        ON pc.block_id = rl.block_id
),

course_options AS (
    SELECT
        s.*,
        rc.course_code                   AS equivalent_course,
        rc.course_title                  AS equivalent_course_title,
        rc.credit_hours                  AS equivalent_credit_hours,
        rc.course_operator               AS equivalent_course_operator
    FROM subcomponents s
    JOIN requirement_courses rc          -- Colleague: courses within each req line
        ON s.line_id = rc.line_id
)

SELECT
    'METHODIST'                          AS "InstitutionIdentifier",
    'Methodist University'               AS "InstitutionName",
    'Program'                            AS "Type",
    co.program_id                        AS "ProgramOfStudyIdentifier",
    co.catalog_year                      AS "CatalogVersion",
    co.program_name                      AS "Name",
    co.component_name                    AS "ComponentName",
    co.component_required_hours          AS "ComponentRequiredHours",
    co.required_subcomponents            AS "ComponentRequiredSubcomponents",
    co.reusability_indicator             AS "ComponentReusabilityIndicator",
    co.subcomponent_name                 AS "SubcomponentName",
    co.subcomponent_title                AS "SubcomponentTitle",
    co.subcomponent_required_hours       AS "SubcomponentRequiredHours",
    co.equivalent_course                 AS "EquivalentCourse",
    co.equivalent_course_title           AS "EquivalentCourseTitle",
    co.equivalent_credit_hours           AS "EquivalentCreditHours",
    co.equivalent_course_operator        AS "EquivalentCourseOperator"

FROM course_options co

ORDER BY
    co.program_name,
    co.component_name,
    co.subcomponent_name,
    co.equivalent_course;
```

---

## Next Steps

- [ ] Confirm Methodist POC by emailing bhilton@acadeum.com
- [ ] Browse Insights schema to identify actual table/column names (see query above)
- [ ] Adapt and run Query 1 — Course Catalog; export to CSV
- [ ] Adapt and run Query 2 — Program Inventory; export to CSV
- [ ] Identify Colleague degree audit block/line/course tables in Insights schema
- [ ] Adapt and run Query 3 — Program Requirements; export to CSV
- [ ] Build Data Connect pipelines to automate delivery if recurring submissions needed
- [ ] Submit all three CSVs to Acadeum; confirm receipt with bhilton@acadeum.com

---

## Resources from Acadeum

| Resource | Description |
|---|---|
| Dataset Details | Technical guide covering all six data types, extraction methods by SIS |
| Acadeum Data Dictionary | xlsx with field-level schema for all six datasets |
| TES Export Guidance | Step-by-step for institutions using CollegeSource TES |

## Reference: Ellucian Insights Schema

The Insights PostgreSQL schema is proprietary and version-dependent. Consult:
- Ellucian Community: community.ellucian.com — search "Insights data dictionary"
- Ellucian documentation portal: resources.elluciancloud.com
- Your Insights instance directly via `information_schema.tables` / `information_schema.columns`
