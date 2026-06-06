const express = require('express');
const { getPool, sql } = require('../db');
const { verifyToken }  = require('../auth/middleware');

const router    = express.Router();
const ALL_ROLES = ['staff', 'it'];

// GET /api/students/:id/academic
router.get('/:id/academic', verifyToken(ALL_ROLES), async (req, res, next) => {
  try {
    const pool    = await getPool();
    const request = pool.request();
    request.input('id', sql.VarChar(20), req.params.id.toUpperCase());

    const result = await request.query(`
      SELECT
          RTRIM(ACADEMIC_YEAR)        AS academic_year,
          RTRIM(ACADEMIC_TERM)        AS academic_term,
          RTRIM(PROGRAM)              AS program,
          RTRIM(DEGREE)               AS degree,
          RTRIM(CURRICULUM)           AS curriculum,
          RTRIM(ATTEND_DIV)           AS attend_div,
          RTRIM(ACADEMIC_FLAG)        AS academic_flag,
          RTRIM(DEGREE_STATUS)        AS degree_status,
          COMMENCEMENT_DATE,
          RTRIM(ACADEMIC_GOOD_STAND)  AS good_standing,
          GPA,
          CREDITS_ATTEMPTED,
          CREDITS_EARNED,
          QUALITY_POINTS
      FROM ACADEMIC
      WHERE PEOPLE_CODE_ID = @id
      ORDER BY ACADEMIC_YEAR DESC, ACADEMIC_TERM DESC`);

    res.json(result.recordset);
  } catch (err) {
    next(err);
  }
});

module.exports = router;
