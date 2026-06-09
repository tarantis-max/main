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
    WHERE  sttr_term             = (SELECT terms_id FROM current_term)
      AND  sttr_current_status  <> 'X'
    ORDER BY sttr_student
),

program AS (
    SELECT DISTINCT ON (stpr_student)
        stpr_student      AS person_id,
        stpr_acad_program AS major
    FROM   dbo.ods_student_programs
    WHERE  stpr_current_status <> 'X'
    ORDER BY stpr_student, stpr_acad_program
),

housing AS (
    SELECT
        rmas_person_id  AS person_id,
        rmas_bldg       AS residence_hall,
        rmas_room       AS room_number
    FROM   dbo.ods_room_assignments
    WHERE  rmas_term = (SELECT terms_id FROM current_term)
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
    COALESCE(TRIM(h.residence_hall), '')                AS residence_hall,
    COALESCE(TRIM(h.room_number), '')                   AS room_number
FROM   enrolled e
JOIN   dbo.ods_person p    ON p.id          = e.person_id
JOIN   dbo.ods_students s  ON s.students_id = e.person_id
LEFT JOIN program pr       ON pr.person_id  = e.person_id
LEFT JOIN housing h        ON h.person_id   = e.person_id
ORDER BY e.person_id
