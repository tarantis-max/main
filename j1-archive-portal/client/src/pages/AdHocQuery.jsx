import { useState } from 'react';
import toast from 'react-hot-toast';
import NavBar from '../components/NavBar';
import DataTable from '../components/shared/DataTable';
import api from '../api/client';

const PLACEHOLDER = `-- SELECT-only queries. Results capped at 500 rows.
SELECT TOP 20
    p.PEOPLE_CODE_ID,
    RTRIM(p.FIRST_NAME) AS first_name,
    RTRIM(p.LAST_NAME)  AS last_name
FROM PEOPLE p
ORDER BY p.LAST_NAME`;

export default function AdHocQuery() {
  const [sql, setSql]       = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(null);

  const handleRun = async () => {
    if (!sql.trim()) { toast.error('Enter a query first'); return; }
    setLoading(true);
    setResult(null);
    const start = Date.now();
    try {
      const { data } = await api.post('/adhoc', { sql });
      setElapsed(Date.now() - start);
      setResult(data);
      if (data.capped) {
        toast('Results capped at 500 rows. Add TOP N to your SELECT for a smaller set.', { icon: '⚠️' });
      }
    } catch (err) {
      toast.error(err.response?.data?.error || 'Query failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen">
      <NavBar />
      <div className="max-w-7xl mx-auto px-4 py-6">
        <h1 className="text-xl font-semibold text-gray-900 mb-1">SQL Query</h1>
        <p className="text-sm text-gray-500 mb-4">
          SELECT-only &mdash; database is read-only. Results capped at 500 rows.
        </p>

        <div className="card p-4 mb-4">
          <textarea
            className="w-full font-mono text-sm border border-gray-200 rounded p-3 h-48 resize-y
                       focus:outline-none focus:ring-1 focus:ring-brand focus:border-brand bg-gray-50"
            value={sql}
            onChange={e => setSql(e.target.value)}
            placeholder={PLACEHOLDER}
            spellCheck={false}
          />
          <div className="flex items-center justify-between mt-3">
            <p className="text-xs text-gray-400">
              Query runs against the J1_Archive database as a read-only user.
            </p>
            <button onClick={handleRun} disabled={loading} className="btn-primary">
              {loading ? 'Running…' : 'Run Query'}
            </button>
          </div>
        </div>

        {result && (
          <div>
            <div className="flex items-center gap-3 mb-2 text-xs text-gray-500">
              <span>{result.rowCount} row{result.rowCount !== 1 ? 's' : ''}</span>
              {elapsed != null && <span>{elapsed}ms</span>}
              {result.capped && (
                <span className="text-amber-600 font-medium">⚠ Capped at 500 rows</span>
              )}
            </div>
            <DataTable
              columns={result.columns.length ? result.columns : Object.keys(result.rows[0] || {})}
              rows={result.rows}
            />
          </div>
        )}
      </div>
    </div>
  );
}
