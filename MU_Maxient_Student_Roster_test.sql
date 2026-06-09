-- STEP 1: Run this first to find the correct column names in ods_room_assignments
-- Then replace the housing CTE below with the right names and run the full query.

SELECT column_name, data_type
FROM   information_schema.columns
WHERE  table_schema = 'dbo'
  AND  table_name   = 'ods_room_assignments'
ORDER BY ordinal_position;

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 2: Full roster query (housing columns stubbed out until Step 1 confirms
-- the real names — replace rmpr_assigned_person, rmpr_building, rmpr_room, and
-- rmpr_room_assignment_period with whatever Step 1 returns).
-- ─────────────────────────────────────────────────────────────────────────────

WITH

current_term AS (
    SELECT terms_id
    FROM   dbo.ods_terms
    WHERE  term_start_date <= CURRENT_DATE
      AND  (
               terms_id ILIKE '%FA'
            OR terms_id ILIKE '%SP'
            OR terms_id ILIKE '%SU'
           )
    ORDER BY term_start_date DESC
    LIMIT 1
),

enrolled AS (
    SELECT DISTINCT ON (sttr_student)
        sttr_student   AS person_id,
        sttr_student_load
    FROM   dbo.ods_student_terms
    WHERE  sttr_term           = (SELECT terms_id FROM current_term)
      AND  sttr_current_status = 'A'
    ORDER BY sttr_student
),

program AS (
    SELECT DISTINCT ON (stpr_student)
        stpr_student      AS person_id,
        stpr_acad_program AS major
    FROM   dbo.ods_student_programs
    WHERE  stpr_current_status = 'A'
    ORDER BY stpr_student, stpr_acad_program
)

SELECT
    e.person_id,
    TRIM(p.first_name)                                  AS first_name,
    TRIM(p.last_name)                                   AS last_name,
    COALESCE(TRIM(p.middle_name), '')                   AS middle_name,
    COALESCE(TRIM(p.preferred_name), '')                AS preferred_name,
    COALESCE(p.preferred_email_address, '')             AS email,
    COALESCE(TO_CHAR(p.birth_date, 'YYYY-MM-DD'), '')   AS date_of_birth,
    CASE p.gender
        WHEN 'M' THEN 'Male'
        WHEN 'F' THEN 'Female'
        ELSE ''
    END                                                 AS gender,
    ''                                                  AS classification,
    COALESCE(TRIM(pr.major), '')                        AS major,
    CASE TRIM(e.sttr_student_load)
        WHEN 'F' THEN 'Full-Time'
        WHEN 'P' THEN 'Part-Time'
        ELSE COALESCE(TRIM(e.sttr_student_load), '')
    END                                                 AS enrollment_type,
    COALESCE(TRIM(s.stu_current_home_location), '')     AS campus,
    -- Housing columns stubbed — fill in after Step 1 confirms real names
    ''                                                  AS residence_hall,
    ''                                                  AS room_number
FROM   enrolled e
JOIN   dbo.ods_person p    ON p.id          = e.person_id
JOIN   dbo.ods_students s  ON s.students_id = e.person_id
LEFT JOIN program pr       ON pr.person_id  = e.person_id
ORDER BY e.person_id
