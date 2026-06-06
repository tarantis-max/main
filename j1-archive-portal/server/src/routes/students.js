const express = require('express');
const { getPool, sql } = require('../db');
const { verifyToken }  = require('../auth/middleware');

const router    = express.Router();
const ALL_ROLES = ['staff', 'it'];

// GET /api/students/search?q=<name or ID>
router.get('/search', verifyToken(ALL_ROLES), async (req, res, next) => {
  try {
    const q = (req.query.q || '').trim();
    if (q.length < 2) {
      return res.status(400).json({ error: 'Query must be at least 2 characters' });
    }

    const pool    = await getPool();
    const request = pool.request();

    // ID search: starts with P followed by digits, or is all digits
    const isId = /^P?\d+$/i.test(q);

    let query;
    if (isId) {
      const normalized = q.toUpperCase().startsWith('P') ? q.toUpperCase() : `P${q}`;
      request.input('id', sql.VarChar(20), normalized + '%');
      query = `
        SELECT TOP 50
            PEOPLE_CODE_ID,
            RTRIM(FIRST_NAME)  AS first_name,
            RTRIM(LAST_NAME)   AS last_name,
            RTRIM(MIDDLE_NAME) AS middle_name,
            BIRTH_DATE
        FROM PEOPLE
        WHERE PEOPLE_CODE_ID LIKE @id
        ORDER BY LAST_NAME, FIRST_NAME`;
    } else {
      // "Last" or "First Last" or "Last, First"
      const parts = q.replace(',', '').split(/\s+/);
      const last  = parts.length >= 2 ? parts[parts.length - 1] : parts[0];
      const first = parts.length >= 2 ? parts[0] : '';
      request.input('last',  sql.VarChar(50), last + '%');
      request.input('first', sql.VarChar(50), (first || '') + '%');
      query = `
        SELECT TOP 50
            PEOPLE_CODE_ID,
            RTRIM(FIRST_NAME)  AS first_name,
            RTRIM(LAST_NAME)   AS last_name,
            RTRIM(MIDDLE_NAME) AS middle_name,
            BIRTH_DATE
        FROM PEOPLE
        WHERE RTRIM(LAST_NAME)  LIKE @last
          AND (RTRIM(FIRST_NAME) LIKE @first OR @first = '')
        ORDER BY LAST_NAME, FIRST_NAME`;
    }

    const result = await request.query(query);
    res.json(result.recordset);
  } catch (err) {
    next(err);
  }
});

// GET /api/students/:id  — profile
router.get('/:id', verifyToken(ALL_ROLES), async (req, res, next) => {
  try {
    const pool    = await getPool();
    const request = pool.request();
    request.input('id', sql.VarChar(20), req.params.id.toUpperCase());

    const result = await request.query(`
      SELECT
          PEOPLE_CODE_ID,
          RTRIM(FIRST_NAME)         AS first_name,
          RTRIM(LAST_NAME)          AS last_name,
          RTRIM(MIDDLE_NAME)        AS middle_name,
          RTRIM(PREFERRED_NAME)     AS preferred_name,
          BIRTH_DATE,
          RTRIM(GENDER)             AS gender,
          RTRIM(ETHNICITY)          AS ethnicity,
          RTRIM(CITIZEN_CODE)       AS citizen_code,
          RTRIM(MARITAL_STATUS)     AS marital_status,
          RTRIM(VETERAN_STATUS)     AS veteran_status,
          RTRIM(DISABILITY_STATUS)  AS disability_status
      FROM PEOPLE
      WHERE PEOPLE_CODE_ID = @id`);

    if (!result.recordset.length) {
      return res.status(404).json({ error: 'Student not found' });
    }
    res.json(result.recordset[0]);
  } catch (err) {
    next(err);
  }
});

module.exports = router;
