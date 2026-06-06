import { useMemo } from 'react';
import LoadingSpinner from '../shared/LoadingSpinner';
import { useStudent } from '../../hooks/useStudent';

function termLabel(year, term) {
  const names = { FA: 'Fall', SP: 'Spring', SU: 'Summer', WI: 'Winter' };
  return `${names[term] ?? term} ${year}`;
}

function gpaColor(grade) {
  if (!grade) return '';
  if (['A', 'A+', 'A-'].includes(grade)) return 'text-green-700';
  if (['D', 'D+', 'D-', 'F', 'WF'].includes(grade)) return 'text-red-600';
  return '';
}

export default function TranscriptTab({ studentId }) {
  const { data, loading, error } = useStudent(studentId, '/transcript');

  const grouped = useMemo(() => {
    if (!data) return [];
    const map = new Map();
    for (const row of data) {
      const key = `${row.year}-${row.term}`;
      if (!map.has(key)) map.set(key, { year: row.year, term: row.term, courses: [] });
      map.get(key).courses.push(row);
    }
    return [...map.values()];
  }, [data]);

  if (loading) return <LoadingSpinner label="Loading transcript…" />;
  if (error)   return <p className="text-sm text-red-600">{error}</p>;
  if (!data)   return null;

  if (!data.length) {
    return <p className="text-sm text-gray-500 py-6 text-center">No course history on record.</p>;
  }

  return (
    <div className="space-y-6">
      {grouped.map(({ year, term, courses }) => {
        const termCredits = courses.reduce((s, c) => s + (Number(c.CREDIT_HRS) || 0), 0);
        const termPoints  = courses.reduce((s, c) => s + (Number(c.QUALITY_POINTS) || 0), 0);
        const termGpa     = termCredits ? (termPoints / termCredits).toFixed(3) : null;

        return (
          <div key={`${year}-${term}`} className="card overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 bg-brand text-white text-sm">
              <span className="font-semibold">{termLabel(year, term)}</span>
              <span className="text-white/70 text-xs">
                {termCredits.toFixed(1)} credits
                {termGpa && <span className="ml-3">Term GPA: {termGpa}</span>}
              </span>
            </div>
            <table className="min-w-full">
              <thead>
                <tr>
                  <th className="th">Course</th>
                  <th className="th">Title</th>
                  <th className="th text-right">Credits</th>
                  <th className="th text-center">Grade</th>
                  <th className="th text-right">Pts</th>
                  <th className="th">Status</th>
                  <th className="th">Transfer</th>
                </tr>
              </thead>
              <tbody>
                {courses.map((c, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="td font-mono text-xs">{c.course_code}</td>
                    <td className="td">{c.course_title || '—'}</td>
                    <td className="td text-right">{c.CREDIT_HRS ?? '—'}</td>
                    <td className={`td text-center font-semibold ${gpaColor(c.grade)}`}>{c.grade || '—'}</td>
                    <td className="td text-right text-gray-500">{c.QUALITY_POINTS ?? '—'}</td>
                    <td className="td text-xs text-gray-400">{c.transaction_sts}</td>
                    <td className="td text-xs text-gray-400">{c.transfer_ind === 'Y' ? 'Transfer' : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
