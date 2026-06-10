import { NavLink, Route, Routes } from "react-router-dom";
import { useProject } from "./state.jsx";
import { ErrorBox } from "./components/ui.jsx";
import Portfolio from "./views/Portfolio.jsx";
import Changes from "./views/Changes.jsx";
import Issues from "./views/Issues.jsx";
import IssueDetail from "./views/IssueDetail.jsx";
import Board from "./views/Board.jsx";
import Backlog from "./views/Backlog.jsx";

const NAV = [
  { to: "/", label: "Portfolio", icon: "▦", end: true },
  { to: "/changes", label: "Changes", icon: "⇄" },
  { to: "/issues", label: "Issues", icon: "☰" },
  { to: "/board", label: "Board", icon: "▤" },
  { to: "/backlog", label: "Backlog", icon: "≡" },
];

export default function App() {
  const { projects, project, setProject, ready, error } = useProject();
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <h1>MU Jira</h1>
          <div className="sub">VPMO · Methodist University</div>
        </div>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}>
              <span aria-hidden>{n.icon}</span> {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="foot">
          <a href="/legacy" target="_blank" rel="noreferrer">Legacy dashboard ↗</a>
        </div>
      </aside>

      <div className="content">
        <div className="topbar">
          <label htmlFor="projSel" className="muted" style={{ fontSize: 12 }}>Project</label>
          <select
            id="projSel"
            value={project}
            onChange={(e) => setProject(e.target.value)}
            disabled={!projects.length}
            style={{ minWidth: 220 }}
          >
            {!projects.length && <option>{ready ? "No projects visible" : "Loading…"}</option>}
            {projects.map((p) => (
              <option key={p.key} value={p.key}>{p.key} — {p.name}</option>
            ))}
          </select>
          <span className="spacer" />
          <span className="muted" style={{ fontSize: 12 }}>
            {ready && !error ? "Connected to Jira" : ""}
          </span>
        </div>

        <main className="page">
          {error && (
            <ErrorBox error={`Jira connection failed: ${error} — start the proxy (start.bat / node dashboard/server.js) with JIRA_EMAIL and JIRA_TOKEN set, then reload.`} />
          )}
          <Routes>
            <Route path="/" element={<Portfolio />} />
            <Route path="/changes" element={<Changes />} />
            <Route path="/issues" element={<Issues />} />
            <Route path="/issues/:issueKey" element={<IssueDetail />} />
            <Route path="/board" element={<Board />} />
            <Route path="/backlog" element={<Backlog />} />
            <Route path="*" element={<div className="center-note">Page not found.</div>} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
