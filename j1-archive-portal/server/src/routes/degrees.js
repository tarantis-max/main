const express = require('express');
const { getPool, sql } = require('../db');
const { verifyToken }  = require('../auth/middleware');

const router    = express.Router();
const ALL_ROLES = ['staff', 'it'];

// GET /api/students/:id/degrees
// Pulls conferred or pending-conferral degree records from ACADEMIC.
// DEGREE_STATUS 'C' = conferred is the most common J1 convention;
// adjust the WHERE if your institution uses different codes.
router.get('/:id/degrees', verifyToken(ALL_ROLES), async (req, res, next) => {
  try {
    const pool    = await getPool();
    const request = pool.request();
    request.input('id', sql.VarChar(20), req.params.id.toUpperCase());

    const result = await request.query(`
      SELECT
          RTRIM(ACADEMIC_YEAR)   AS academic_year,
          RTRIM(ACADEMIC_TERM)   AS academic_term,
          RTRIM(DEGREE)          AS degree,
          RTRIM(CURRICULUM)      AS curriculum,
          RTRIM(PROGRAM)         AS program,
          RTRIM(DEGREE_STATUS)   AS degree_status,
          COMMENCEMENT_DATE,
          RTRIM(ATTEND_DIV)      AS attend_div,
          RTRIM(ACADEMIC_FLAG)   AS academic_flag,
          CREDITS_EARNED,
          GPA
      FROM ACADEMIC
      WHERE PEOPLE_CODE_ID = @id
        AND (
            DEGREE_STATUS     IS NOT NULL
            OR COMMENCEMENT_DATE IS NOT NULL
        )
      ORDER BY COMMENCEMENT_DATE DESC, ACADEMIC_YEAR DESC`);

    res.json(result.recordset);
  } catch (err) {
    next(err);
  }
});

module.exports = router;
