const express = require('express');
const { getPool, sql } = require('../db');
const { verifyToken }  = require('../auth/middleware');

const router    = express.Router();
const ALL_ROLES = ['staff', 'it'];

// GET /api/students/:id/transcript
// Returns all course history rows joined to COURSE_CATALOG for titles.
// TRANSACTION_STS values vary by J1 installation — common set shown here.
// Run: SELECT DISTINCT TRANSACTION_STS FROM STUDENT_CRS_HIST
// on the archive to confirm the values used at your institution.
router.get('/:id/transcript', verifyToken(ALL_ROLES), async (req, res, next) => {
  try {
    const pool    = await getPool();
    const request = pool.request();
    request.input('id', sql.VarChar(20), req.params.id.toUpperCase());

    const result = await request.query(`
      SELECT
          RTRIM(h.YR_CDE)              AS year,
          RTRIM(h.TRM_CDE)             AS term,
          RTRIM(h.CRS_CDE)             AS course_code,
          RTRIM(c.CRS_TITLE)           AS course_title,
          h.CREDIT_HRS,
          RTRIM(h.GRADE_CDE)           AS grade,
          h.QUALITY_POINTS,
          RTRIM(h.TRANSACTION_STS)     AS transaction_sts,
          RTRIM(h.PASS_FAIL_AUDIT)     AS pass_fail_audit,
          RTRIM(h.SUBTERM_CDE)         AS subterm,
          RTRIM(h.ATTEND_DIV)          AS division,
          RTRIM(h.TRANSFER_COURSE_IND) AS transfer_ind
      FROM STUDENT_CRS_HIST h
      LEFT JOIN COURSE_CATALOG c
             ON RTRIM(c.CRS_CDE) = RTRIM(h.CRS_CDE)
      WHERE h.PEOPLE_CODE_ID = @id
      ORDER BY h.YR_CDE DESC, h.TRM_CDE DESC, h.CRS_CDE`);

    res.json(result.recordset);
  } catch (err) {
    next(err);
  }
});

module.exports = router;
