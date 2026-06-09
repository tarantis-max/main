-- Run each block one at a time and tell me what each returns.

-- STEP 1: confirm the resolved term
SELECT terms_id
FROM   dbo.ods_terms
WHERE  term_start_date <= CURRENT_DATE
  AND  (terms_id ILIKE '%FA' OR terms_id ILIKE '%SP' OR terms_id ILIKE '%SU')
ORDER BY term_start_date DESC
LIMIT 1;

-- STEP 2: how many student_terms rows exist for that term (any status)?
SELECT COUNT(*)
FROM   dbo.ods_student_terms
WHERE  sttr_term = '2026SU';   -- replace with STEP 1 result if different

-- STEP 3: does enrolled produce rows on its own?
SELECT COUNT(*)
FROM   dbo.ods_student_terms
WHERE  sttr_term            = '2026SU'   -- replace with STEP 1 result
  AND  sttr_current_status <> 'X';

-- STEP 4: does adding the ods_person join lose rows?
SELECT COUNT(*)
FROM   dbo.ods_student_terms st
JOIN   dbo.ods_person p ON p.id = st.sttr_student
WHERE  st.sttr_term            = '2026SU'   -- replace with STEP 1 result
  AND  st.sttr_current_status <> 'X';

-- STEP 5: does adding ods_students lose rows?
SELECT COUNT(*)
FROM   dbo.ods_student_terms st
JOIN   dbo.ods_person p   ON p.id          = st.sttr_student
JOIN   dbo.ods_students s ON s.students_id = st.sttr_student
WHERE  st.sttr_term            = '2026SU'   -- replace with STEP 1 result
  AND  st.sttr_current_status <> 'X';
