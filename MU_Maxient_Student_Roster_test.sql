WITH

current_term AS (
    -- Most recently started FA, SP, or SU term whose start date is on or
    -- before today. Adjust the ILIKE filters if MU uses different term suffixes.
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
    -- One row per student who is actively registered in the current term.
    -- DISTINCT ON guards against duplicate sttr rows for the same student.
    SELECT DISTINCT ON (sttr_student)
        sttr_student       AS person_id,
        sttr_student_load
    FROM   dbo.ods_student_terms
    WHERE  sttr_term           = (SELECT terms_id FROM current_term)
      AND  sttr_current_status = 'A'
    ORDER BY sttr_student
),

program AS (
    -- Primary active academic program per student.
    SELECT DISTINCT ON (stpr_student)
        stpr_student      AS person_id,
        stpr_acad_program AS major
    FROM   dbo.ods_student_programs
    WHERE  stpr_current_status = 'A'
    ORDER BY stpr_student, stpr_acad_program
),

housing AS (
    -- Current-term room assignment, if any.
    -- Verify rmpr_building and rmpr_room column names against your ODS.
    SELECT
        rmpr_assigned_person          AS person_id,
        rmpr_building                 AS residence_hall,
        rmpr_room                     AS room_number
    FROM   dbo.ods_room_assignments
    WHERE  rmpr_room_assignment_period = (SELECT terms_id FROM current_term)
)

SELECT
    e.person_id,
    TRIM(p.first_name)                                        AS first_name,
    TRIM(p.last_name)                                         AS last_name,
    COALESCE(TRIM(p.middle_name), '')                         AS middle_name,
    COALESCE(TRIM(p.preferred_name), '')                      AS preferred_name,
    COALESCE(p.preferred_email_address, '')                   AS email,
    COALESCE(TO_CHAR(p.birth_date, 'YYYY-MM-DD'), '')         AS date_of_birth,
    CASE p.gender
        WHEN 'M' THEN 'Male'
        WHEN 'F' THEN 'Female'
        ELSE ''
    END                                                       AS gender,
    ''                                                        AS classification,
    COALESCE(TRIM(pr.major), '')                              AS major,
    CASE TRIM(e.sttr_student_load)
        WHEN 'F' THEN 'Full-Time'
        WHEN 'P' THEN 'Part-Time'
        ELSE COALESCE(TRIM(e.sttr_student_load), '')
    END                                                       AS enrollment_type,
    COALESCE(TRIM(s.stu_current_home_location), '')           AS campus,
    COALESCE(TRIM(h.residence_hall), '')                      AS residence_hall,
    COALESCE(TRIM(h.room_number), '')                         AS room_number
FROM   enrolled e
JOIN   dbo.ods_person p
         ON p.id          = e.person_id
JOIN   dbo.ods_students s
         ON s.students_id = e.person_id
LEFT JOIN program pr
         ON pr.person_id  = e.person_id
LEFT JOIN housing h
         ON h.person_id   = e.person_id
ORDER BY e.person_id
