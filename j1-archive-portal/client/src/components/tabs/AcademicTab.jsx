import LoadingSpinner from '../shared/LoadingSpinner';
import DataTable from '../shared/DataTable';
import { useStudent } from '../../hooks/useStudent';

const COLS = [
  'academic_year','academic_term','program','degree','curriculum',
  'attend_div','academic_flag','degree_status','good_standing',
  'GPA','credits_attempted','credits_earned','quality_points','COMMENCEMENT_DATE',
];

export default function AcademicTab({ studentId }) {
  const { data, loading, error } = useStudent(studentId, '/academic');

  if (loading) return <LoadingSpinner label="Loading academic history…" />;
  if (error)   return <p className="text-sm text-red-600">{error}</p>;
  if (!data)   return null;

  return (
    <div>
      <p className="text-xs text-gray-400 mb-3">{data.length} record{data.length !== 1 ? 's' : ''}</p>
      <DataTable columns={COLS.filter(c => data.some(r => r[c] != null))} rows={data} />
    </div>
  );
}
