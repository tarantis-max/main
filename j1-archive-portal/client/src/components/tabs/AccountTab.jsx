import { useMemo } from 'react';
import LoadingSpinner from '../shared/LoadingSpinner';
import { useStudent } from '../../hooks/useStudent';

// Classify a TRANS_TYPE code as charge, credit/payment, or other.
// Adjust these sets to match your institution's J1 TRANS_TYPE values.
const CHARGE_TYPES  = new Set(['CHARGE','CHRG','C','TUITION','FEE','HOUSING','HEALTH','PARKING','FINE','MISC']);
const CREDIT_TYPES  = new Set(['PAYMENT','PMNT','P','CREDIT','CRED','FINAID','FA','WAIVER','WAV','REFUND','REF','SCHOL']);

function classify(type) {
  const t = (type || '').toUpperCase().trim();
  if (CHARGE_TYPES.has(t))  return 'charge';
  if (CREDIT_TYPES.has(t))  return 'credit';
  return 'neutral';
}

function fmt$(n) {
  if (n == null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
}

function fmtDate(val) {
  if (!val) return '—';
  return new Date(val).toLocaleDateString('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric' });
}

function termLabel(year, term) {
  const names = { FA: 'Fall', SP: 'Spring', SU: 'Summer', WI: 'Winter' };
  return `${names[term] ?? term} ${year}`;
}

function BalanceCard({ balance, asOf }) {
  const isPositive = Number(balance) > 0;
  return (
    <div className={`card p-5 mb-6 flex items-center justify-between ${isPositive ? 'border-red-200 bg-red-50' : 'border-green-200 bg-green-50'}`}>
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wide font-semibold mb-0.5">Account Balance</p>
        <p className={`text-3xl font-bold ${isPositive ? 'text-red-700' : 'text-green-700'}`}>
          {fmt$(balance)}
        </p>
        {asOf && <p className="text-xs text-gray-400 mt-1">As of {fmtDate(asOf)}</p>}
      </div>
      <div className="text-right text-xs text-gray-400">
        {isPositive
          ? <span className="text-red-600 font-medium">Amount Due</span>
          : <span className="text-green-600 font-medium">Credit Balance</span>}
      </div>
    </div>
  );
}

export default function AccountTab({ studentId }) {
  const { data, loading, error } = useStudent(studentId, '/account');

  const grouped = useMemo(() => {
    if (!data?.transactions) return [];
    const map = new Map();
    for (const tx of data.transactions) {
      const key = tx.year && tx.term ? `${tx.year}-${tx.term}` : 'MISC';
      if (!map.has(key)) map.set(key, { year: tx.year, term: tx.term, rows: [] });
      map.get(key).rows.push(tx);
    }
    return [...map.values()];
  }, [data]);

  if (loading) return <LoadingSpinner label="Loading account…" />;
  if (error)   return <p className="text-sm text-red-600">{error}</p>;
  if (!data)   return null;

  return (
    <div>
      <BalanceCard balance={data.balance} asOf={data.balance_as_of} />

      {!data.transactions.length ? (
        <p className="text-sm text-gray-500 text-center py-6">No account transactions on record.</p>
      ) : (
        <div className="space-y-5">
          {grouped.map(({ year, term, rows }) => {
            const termNet = rows.reduce((s, r) => s + (Number(r.amount) || 0), 0);
            return (
              <div key={`${year}-${term}`} className="card overflow-hidden">
                <div className="flex items-center justify-between px-4 py-2.5 bg-gray-700 text-white text-sm">
                  <span className="font-semibold">
                    {year && term ? termLabel(year, term) : 'Miscellaneous / No Term'}
                  </span>
                  <span className={`text-xs font-medium ${termNet > 0 ? 'text-red-300' : termNet < 0 ? 'text-green-300' : 'text-white/60'}`}>
                    Term net: {fmt$(termNet)}
                  </span>
                </div>
                <table className="min-w-full">
                  <thead>
                    <tr>
                      <th className="th">Date</th>
                      <th className="th">Type</th>
                      <th className="th">Detail Code</th>
                      <th className="th">Description</th>
                      <th className="th text-right">Amount</th>
                      <th className="th">Ref #</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((tx, i) => {
                      const kind = classify(tx.trans_type);
                      return (
                        <tr key={i} className="hover:bg-gray-50">
                          <td className="td whitespace-nowrap">{fmtDate(tx.TRANS_DATE)}</td>
                          <td className="td text-xs font-mono">{tx.trans_type}</td>
                          <td className="td text-xs text-gray-400">{tx.detail_code || '—'}</td>
                          <td className="td">{tx.description || '—'}</td>
                          <td className={`td text-right font-medium tabular-nums ${
                            kind === 'charge'  ? 'text-red-600'   :
                            kind === 'credit'  ? 'text-green-700' : 'text-gray-700'
                          }`}>
                            {fmt$(tx.amount)}
                          </td>
                          <td className="td text-xs text-gray-400">{tx.reference_num || '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
