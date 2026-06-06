import { useState } from 'react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import NavBar from '../components/NavBar';
import LoadingSpinner from '../components/shared/LoadingSpinner';
import api from '../api/client';

function fmtDate(val) {
  if (!val) return '—';
  return new Date(val).toLocaleDateString('en-US', { timeZone: 'UTC' });
}

export default function StudentSearch() {
  const [query, setQuery]     = useState('');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleSearch = async e => {
    e.preventDefault();
    if (query.trim().length < 2) { toast.error('Enter at least 2 characters'); return; }
    setLoading(true);
    setResults(null);
    try {
      const { data } = await api.get('/students/search', { params: { q: query.trim() } });
      setResults(data);
      if (!data.length) toast('No students matched that search.', { icon: 'ℹ️' });
    } catch (err) {
      toast.error(err.response?.data?.error || 'Search failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen">
      <NavBar />
      <div className="max-w-4xl mx-auto px-4 py-8">
        <h1 className="text-xl font-semibold text-gray-900 mb-1">Student Search</h1>
        <p className="text-sm text-gray-500 mb-6">
          Search by student ID (e.g. P000012345) or by last name, or "First Last"
        </p>

        <form onSubmit={handleSearch} className="flex gap-2 mb-6">
          <input
            className="input flex-1"
            type="text"
            placeholder="Smith  /  Jane Smith  /  P000012345"
            value={query}
            onChange={e => setQuery(e.target.value)}
            autoFocus
          />
          <button type="submit" disabled={loading} className="btn-primary">
            Search
          </button>
        </form>

        {loading && <LoadingSpinner label="Searching…" />}

        {results && !loading && (
          <div className="card overflow-hidden">
            <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 text-xs text-gray-500">
              {results.length} result{results.length !== 1 ? 's' : ''} (max 50 shown — narrow your search for more)
            </div>
            <table className="min-w-full">
              <thead>
                <tr>
                  <th className="th">ID</th>
                  <th className="th">Last Name</th>
                  <th className="th">First Name</th>
                  <th className="th">Middle</th>
                  <th className="th">Date of Birth</th>
                </tr>
              </thead>
              <tbody>
                {results.map(s => (
                  <tr key={s.PEOPLE_CODE_ID} className="hover:bg-blue-50 cursor-pointer">
                    <td className="td font-mono">
                      <Link
                        to={`/students/${s.PEOPLE_CODE_ID}`}
                        className="text-brand hover:underline font-medium"
                      >
                        {s.PEOPLE_CODE_ID}
                      </Link>
                    </td>
                    <td className="td">
                      <Link to={`/students/${s.PEOPLE_CODE_ID}`} className="hover:underline">
                        {s.last_name}
                      </Link>
                    </td>
                    <td className="td">{s.first_name}</td>
                    <td className="td text-gray-400">{s.middle_name || '—'}</td>
                    <td className="td">{fmtDate(s.BIRTH_DATE)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
