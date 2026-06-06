import LoadingSpinner from '../shared/LoadingSpinner';
import { useStudent } from '../../hooks/useStudent';

function fmtDate(val) {
  if (!val) return null;
  return new Date(val).toLocaleDateString('en-US', { timeZone: 'UTC', year: 'numeric', month: 'long', day: 'numeric' });
}

const STATUS_LABEL = { C: 'Conferred', P: 'Pending', G: 'Graduated', A: 'Applied' };

export default function DegreesTab({ studentId }) {
  const { data, loading, error } = useStudent(studentId, '/degrees');

  if (loading) return <LoadingSpinner label="Loading degrees…" />;
  if (error)   return <p className="text-sm text-red-600">{error}</p>;
  if (!data)   return null;

  if (!data.length) {
    return <p className="text-sm text-gray-500 py-6 text-center">No degree records on file.</p>;
  }

  return (
    <div className="space-y-4">
      {data.map((d, i) => (
        <div key={i} className="card p-5">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-semibold text-gray-900 text-base">{d.degree || '—'}</h3>
              <p className="text-sm text-gray-500 mt-0.5">{d.curriculum} {d.program ? `· ${d.program}` : ''}</p>
            </div>
            {d.degree_status && (
              <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${
                ['C','G'].includes(d.degree_status)
                  ? 'bg-green-100 text-green-800'
                  : 'bg-yellow-100 text-yellow-800'
              }`}>
                {STATUS_LABEL[d.degree_status] ?? d.degree_status}
              </span>
            )}
          </div>
          <dl className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <dt className="text-xs text-gray-400">Conferred</dt>
              <dd className="text-sm text-gray-800 mt-0.5">{fmtDate(d.COMMENCEMENT_DATE) || '—'}</dd>
            </div>
            <div>
              <dt className="text-xs text-gray-400">Term</dt>
              <dd className="text-sm text-gray-800 mt-0.5">
                {d.academic_term} {d.academic_year}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-gray-400">Credits Earned</dt>
              <dd className="text-sm text-gray-800 mt-0.5">{d.credits_earned ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-xs text-gray-400">GPA</dt>
              <dd className="text-sm text-gray-800 mt-0.5">{d.GPA ?? '—'}</dd>
            </div>
          </dl>
        </div>
      ))}
    </div>
  );
}
