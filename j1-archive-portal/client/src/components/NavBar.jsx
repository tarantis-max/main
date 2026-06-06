import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function NavBar() {
  const { auth, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => { logout(); navigate('/login'); };

  return (
    <nav className="bg-brand text-white shadow-md">
      <div className="max-w-7xl mx-auto px-4 flex items-center justify-between h-14">
        <div className="flex items-center gap-6">
          <Link to="/" className="font-bold text-brand-gold tracking-wide text-sm">
            MU J1 Archive
          </Link>
          <Link to="/" className="text-sm text-white/80 hover:text-white transition-colors">
            Student Search
          </Link>
          {auth?.role === 'it' && (
            <Link to="/query" className="text-sm text-white/80 hover:text-white transition-colors">
              SQL Query
            </Link>
          )}
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-white/70">{auth?.name}</span>
          <span className="px-2 py-0.5 rounded text-xs font-medium bg-white/10 uppercase tracking-wide">
            {auth?.role}
          </span>
          <button
            onClick={handleLogout}
            className="text-white/70 hover:text-white transition-colors ml-2"
          >
            Sign out
          </button>
        </div>
      </div>
    </nav>
  );
}
