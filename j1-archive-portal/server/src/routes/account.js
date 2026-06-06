const express = require('express');
const { getPool, sql } = require('../db');
const { verifyToken }  = require('../auth/middleware');

const router    = express.Router();
const ALL_ROLES = ['staff', 'it'];

// GET /api/students/:id/account
// Returns a balance summary and full AR transaction ledger.
//
// Table names assume standard Jenzabar CX schema:
//   ARTR      — individual AR transaction rows
//   ARACCTHIST — running account balance by year/term
//
// TRANS_TYPE codes vary by institution. Common values:
//   CHARGE / CHRG / C  = charge (tuition, fees, housing, etc.)
//   PAYMENT / PMNT / P = payment received
//   CREDIT / CRED      = credit adjustment
//   FINAID / FA        = financial aid credit
//   WAIVER / WAV       = waiver
//   REFUND / REF       = refund issued
//
// Run this on the archive to see what your institution uses:
//   SELECT DISTINCT RTRIM(TRANS_TYPE), COUNT(*) AS n FROM ARTR GROUP BY TRANS_TYPE ORDER BY n DESC
router.get('/:id/account', verifyToken(ALL_ROLES), async (req, res, next) => {
  try {
    const pool = await getPool();
    const id   = req.params.id.toUpperCase();

    // Balance summary — latest row per account from ARACCTHIST
    const summaryReq = pool.request();
    summaryReq.input('id', sql.VarChar(20), id);
    const summaryResult = await summaryReq.query(`
      SELECT TOP 1
          RTRIM(PEOPLE_CODE_ID)  AS student_id,
          BALANCE_AMT            AS balance,
          RTRIM(BALANCE_TYPE)    AS balance_type,
          AS_OF_DATE
      FROM ARACCTHIST
      WHERE PEOPLE_CODE_ID = @id
      ORDER BY AS_OF_DATE DESC, YR_CDE DESC, TRM_CDE DESC`);

    // Full transaction ledger from ARTR
    const txReq = pool.request();
    txReq.input('id', sql.VarChar(20), id);
    const txResult = await txReq.query(`
      SELECT
          RTRIM(YR_CDE)          AS year,
          RTRIM(TRM_CDE)         AS term,
          TRANS_DATE,
          RTRIM(TRANS_TYPE)      AS trans_type,
          RTRIM(DETAIL_CODE)     AS detail_code,
          RTRIM(TRANS_DESC)      AS description,
          TRANS_AMT              AS amount,
          RTRIM(TRANS_STS)       AS status,
          RTRIM(REFERENCE_NUM)   AS reference_num
      FROM ARTR
      WHERE PEOPLE_CODE_ID = @id
        AND RTRIM(TRANS_STS) <> 'V'   -- exclude voided transactions
      ORDER BY TRANS_DATE DESC, YR_CDE DESC, TRM_CDE DESC`);

    // Compute totals from the ledger in case ARACCTHIST is absent
    const transactions = txResult.recordset;
    const computedBalance = transactions.reduce((sum, t) => sum + (Number(t.amount) || 0), 0);

    res.json({
      balance: summaryResult.recordset[0]?.balance ?? computedBalance,
      balance_as_of: summaryResult.recordset[0]?.AS_OF_DATE ?? null,
      transactions,
    });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
