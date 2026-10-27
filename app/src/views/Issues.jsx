import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtAgo, fmtDate } from "../api.js";
import { useProject } from "../state.jsx";
import { ErrorBox, Spinner, StatusPill, useDebounce } from "../components/ui.jsx";

export default function Issues() {
  const { project, ready } = useProject();
  const nav = useNavigate();
  const [mode, setMode] = useState("text"); // text | jql
  const [q, setQ] = useState("");
  const [jql, setJql] = useState("");
  const [issues, setIssues] = useState([]);
  const [pageToken, setPageToken] = useState(null);
  const [activeJql, setActiveJql] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const dq = useDebounce(q);

  const search = async (append = false, token = null) => {
    if (!project && mode === "text") return;
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams();
      if (mode === "jql" && jql.trim()) params.set("jql", jql.trim());
      else { params.set("project", project); if (dq.trim()) params.set("q", dq.trim()); }
      if (token) params.set("pageToken", token);
      const data = await api(`/api/issues?${params}`);
      setIssues((cur) => (append ? [...cur, ...data.issues] : data.issues));
      setPageToken(data.nextPageToken);
      setActiveJql(data.jql);
    } catch (e) { setError(String(e.message || e)); }
    setLoading(false);
  };

  useEffect(() => { if (mode === "text") search(); }, [project, dq, mode]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!ready) return <Spinner />;
  return (
    <>
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Issues</h2>
        <span style={{ marginLeft: "auto" }} />
        <div className="seg">
          <button className={mode === "text" ? "active" : ""} onClick={() => setMode("text")}>Search</button>
          <button className={mode === "jql" ? "active" : ""} onClick={() => setMode("jql")}>JQL</button>
        </div>
      </div>

      <div className="toolbar">
        {mode === "text" ? (
          <input style={{ flex: 1, maxWidth: 480 }} placeholder={`Search ${project || "…"} — text or an issue key like ${project || "ABC"}-12`}
            value={q} onChange={(e) => setQ(e.target.value)} />
        ) : (
          <>
            <input style={{ flex: 1, fontFamily: "ui-monospace, monospace", fontSize: 12.5 }}
              placeholder='e.g. assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC'
              value={jql} onChange={(e) => setJql(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()} />
            <button className="btn primary" onClick={() => search()} disabled={loading}>Run</button>
          </>
        )}
      </div>
      {activeJql && <div className="muted" style={{ fontSize: 11.5, marginBottom: 10 }}>JQL: <code>{activeJql}</code></div>}

      <ErrorBox error={error} />
      <div className="panel">
        <table className="data">
          <thead><tr>
            <th>Key</th><th>Type</th><th>Summary</th><th>Status</th><th>Assignee</th><th>Priority</th><th>Due</th><th>Updated</th>
          </tr></thead>
          <tbody>
            {issues.map((i) => (
              <tr key={i.key} onClick={() => nav(`/issues/${i.key}`)}>
                <td><span className="key-link">{i.key}</span></td>
                <td><span className="pill muted">{i.type}</span></td>
                <td>{i.summary}</td>
                <td><StatusPill status={i.status} category={i.statusCategory} /></td>
                <td>
                  {i.assignee ? (
                    <span className="avatar-cell">
                      {i.assigneeAvatar && <img className="avatar" src={i.assigneeAvatar} alt="" />}
                      {i.assignee}
                    </span>
                  ) : <span className="muted">Unassigned</span>}
                </td>
                <td>{i.priority || "—"}</td>
                <td>{fmtDate(i.duedate)}</td>
                <td className="muted">{fmtAgo(i.updated)}</td>
              </tr>
            ))}
            {!issues.length && !loading && <tr className="empty"><td colSpan={8}>No issues found.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="toolbar" style={{ marginTop: 14, justifyContent: "center" }}>
        {loading && <span className="muted"><span className="spin">↻</span> Loading…</span>}
        {!loading && pageToken && <button className="btn" onClick={() => search(true, pageToken)}>Load more</button>}
        {!loading && !!issues.length && <span className="muted" style={{ fontSize: 12 }}>{issues.length} loaded{pageToken ? "" : " (all)"}</span>}
      </div>
    </>
  );
}
