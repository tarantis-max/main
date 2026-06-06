import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import NavBar from '../components/NavBar';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import ProfileTab from '../components/tabs/ProfileTab';
import AcademicTab from '../components/tabs/AcademicTab';
import TranscriptTab from '../components/tabs/TranscriptTab';
import DegreesTab from '../components/tabs/DegreesTab';
import { useStudent } from '../hooks/useStudent';

const TABS = [
  { label: 'Profile',          Component: ProfileTab },
  { label: 'Academic History', Component: AcademicTab },
  { label: 'Transcript',       Component: TranscriptTab },
  { label: 'Degrees',          Component: DegreesTab },
];

export default function StudentDetail() {
  const { id } = useParams();
  const [activeTab, setActiveTab] = useState(0);
  const { data: student, loading, error } = useStudent(id);

  const ActiveComponent = TABS[activeTab].Component;

  return (
    <div className="min-h-screen">
      <NavBar />
      <div className="max-w-6xl mx-auto px-4 py-6">
        <div className="mb-1">
          <Link to="/" className="text-xs text-brand hover:underline">← Back to search</Link>
        </div>

        {loading && <LoadingSpinner label="Loading student…" />}

        {error && (
          <div className="mt-8 text-center text-red-600 text-sm">{error}</div>
        )}

        {student && (
          <>
            <div className="mb-5 mt-3">
              <h1 className="text-2xl font-bold text-gray-900">
                {student.last_name}, {student.first_name}
                {student.middle_name ? ` ${student.middle_name}` : ''}
              </h1>
              <p className="text-sm text-gray-500 font-mono mt-0.5">{id}</p>
            </div>

            <div className="border-b border-gray-200 mb-6">
              <nav className="-mb-px flex gap-6">
                {TABS.map((tab, i) => (
                  <button
                    key={tab.label}
                    onClick={() => setActiveTab(i)}
                    className={`py-2 px-0.5 border-b-2 text-sm font-medium transition-colors ${
                      activeTab === i
                        ? 'border-brand text-brand'
                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </nav>
            </div>

            <ActiveComponent student={student} studentId={id} />
          </>
        )}
      </div>
    </div>
  );
}
