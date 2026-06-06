const express = require('express');
const { getPool }        = require('../db');
const { verifyToken }    = require('../auth/middleware');
const { validateSelect } = require('../utils/selectGuard');

const router = express.Router();

// POST /api/adhoc  — IT role only
// Body: { sql: "SELECT ..." }
// Returns: { columns: [...], rows: [...], rowCount: N, capped: bool }
router.post('/', verifyToken(['it']), async (req, res, next) => {
  try {
    const rawSql = (req.body.sql || '').trim();
    if (!rawSql) {
      return res.status(400).json({ error: 'SQL query is required' });
    }

    const safeSql = validateSelect(rawSql);
    const capped  = safeSql !== rawSql;

    const pool   = await getPool();
    const result = await pool.request().query(safeSql);
    const rows   = result.recordset;

    const columns = rows.length
      ? Object.keys(rows[0])
      : result.recordsets[0]
        ? result.recordsets[0].columns
          ? Object.keys(result.recordsets[0].columns)
          : []
        : [];

    res.json({ columns, rows, rowCount: rows.length, capped });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
