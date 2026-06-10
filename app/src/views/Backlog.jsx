import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtDate } from "../api.js";
import { useProject } from "../state.jsx";
import { ErrorBox, Spinner, StatusPill, useToast } from "../components/ui.jsx";

/* Sprint / backlog view via the Jira Software (agile) API. Business
   (work-management) projects have no agile boards — we show a friendly
   note instead. Issues move between sprints and backlog via the ⋯ menu. */

function IssueRow({ issue, destinations, onMove, onOpen }) {
  const [menu, setMenu] = useState(false);
  return (
    <div className="comment" style={{ display: "flex", gap: 10, alignItems: "center", position: "relative" }}>
      <span className="key-link" style={{ cursor: "pointer" }} onClick={onOpen}>{issue.key}</span>
      <span style={{ flex: 1, cursor: "pointer" }} onClick={onOpen}>{issue.summary}</span>
      <StatusPill status={issue.status} category={issue.statusCategory} />
      {issue.assignee && <span className="muted" style={{ fontSize: 12 }}>{issue.assignee}</span>}
      <button className="btn sm" onClick={() => setMenu((m) => !m)}>⋯</button>
      {menu && (
        <div className="panel" style={{ position: "absolute", right: 0, top: "100%", zIndex: 50, padding: 6, minWidth: 180 }}>
          {destinations.map((d) => (
            <div key={d.id ?? "backlog"} className="comment" style={{ cursor: "pointer", padding: "7px 8px" }}
              onClick={() => { setMenu(false); onMove(d); }}>
              → {d.name}
            </div>
          ))}
          {!destinations.length && <div className="muted" style={{ padding: 8, fontSize: 12 }}>No destinations</div>}
        </div>
      )}
    </div>
  );
}

export default function Backlog() {
  const { project, ready } = useProject();
  const toast = useToast();
  const nav = useNavigate();
  const [boards, setBoards] = useState(null);
  const [boardId, setBoardId] = useState(null);
  const [sprints, setSprints] = useState([]);
  const [sprintIssues, setSprintIssues] = useState({}); // sprintId -> issues
  const [backlog, setBacklog] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!project) return;
    setBoards(null); setBoardId(null); setError("");
    api(`/api/agile/boards?project=${encodeURIComponent(project)}`)
      .then((d) => {
        const list = d.boards || [];
        setBoards(list);
        if (list.length) setBoardId(list.find((b) => b.type === "scrum")?.id ?? list[0].id);
      })
      .catch((e) => { setBoards([]); setError(String(e.message || e)); });
  }, [project]);

  const loadBoard = async (id) => {
    setLoading(true); setError("");
    try {
      const [{ sprints: sp }, { issues: bl }] = await Promise.all([
        api(`/api/agile/board/${id}/sprints`),
        api(`/api/agile/board/${id}/backlog`),
      ]);
      setSprints(sp || []);
      setBacklog(bl || []);
      const bySprint = {};
      await Promise.all((sp || []).map(async (s) => {
        const { issues } = await api(`/api/agile/sprint/${s.id}/issues`);
        bySprint[s.id] = issues || [];
      }));
      setSprintIssues(bySprint);
    } catch (e) { setError(String(e.message || e)); }
    setLoading(false);
  };
  useEffect(() => { if (boardId != null) loadBoard(boardId); }, [boardId]); // eslint-disable-line react-hooks/exhaustive-deps

  const move = async (issue, dest) => {
    try {
      if (dest.id === null) await api("/api/agile/backlog", { method: "POST", body: { issues: [issue.key] } });
      else await api(`/api/agile/sprint/${dest.id}/issues`, { method: "POST", body: { issues: [issue.key] } });
      toast(`${issue.key} → ${dest.name}`);
      loadBoard(boardId);
    } catch (e) { toast(`Move failed: ${e.message}`, true); }
  };

  if (!ready || boards === null) return <Spinner />;
  if (!boards.length) {
    return (
      <>
        <h2>Backlog</h2>
        <ErrorBox error={error} />
        <div className="center-note">
          <b>{project}</b> has no Jira Software board, so sprints and backlog aren't available.<br />
          Business (work-management) projects don't support sprints — use the <a href="/board">Board</a> view instead.
        </div>
      </>
    );
  }

  const destFor = (currentSprintId) => [
    ...sprints.filter((s) => s.id !== currentSprintId).map((s) => ({ id: s.id, name: s.name })),
    ...(currentSprintId !== null ? [{ id: null, name: "Backlog" }] : []),
  ];

  return (
    <>
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Backlog</h2>
        {boards.length > 1 && (
          <select value={boardId ?? ""} onChange={(e) => setBoardId(Number(e.target.value))}>
            {boards.map((b) => <option key={b.id} value={b.id}>{b.name} ({b.type})</option>)}
          </select>
        )}
        <span style={{ marginLeft: "auto" }} />
        <button className="btn" onClick={() => loadBoard(boardId)} disabled={loading}>
          {loading ? <span className="spin">↻</span> : "⟳"} Refresh
        </button>
      </div>
      <ErrorBox error={error} />
      {loading && <Spinner label="Loading sprints…" />}
      {!loading && (
        <>
          {sprints.map((s) => (
            <div className="panel" style={{ marginBottom: 16 }} key={s.id}>
              <div className="kcol-head" style={{ borderBottom: "1px solid var(--border)" }}>
                <span className={`pill ${s.state === "active" ? "accent" : "muted"}`}>{s.state}</span>
                <b>{s.name}</b>
                {s.startDate && <span className="muted" style={{ fontSize: 12 }}>{fmtDate(s.startDate)} → {fmtDate(s.endDate)}</span>}
                {s.goal && <span className="muted" style={{ fontSize: 12 }}>· {s.goal}</span>}
                <span className="count" style={{ marginLeft: "auto" }}>{(sprintIssues[s.id] || []).length} issues</span>
              </div>
              <div className="panel-pad" style={{ paddingTop: 4, paddingBottom: 8 }}>
                {(sprintIssues[s.id] || []).map((i) => (
                  <IssueRow key={i.key} issue={i} destinations={destFor(s.id)}
                    onMove={(d) => move(i, d)} onOpen={() => nav(`/issues/${i.key}`)} />
                ))}
                {!(sprintIssues[s.id] || []).length && <div className="muted" style={{ padding: "10px 0" }}>No issues in this sprint.</div>}
              </div>
            </div>
          ))}
          {!sprints.length && <div className="muted" style={{ marginBottom: 16 }}>No active or future sprints on this board.</div>}

          <div className="panel">
            <div className="kcol-head" style={{ borderBottom: "1px solid var(--border)" }}>
              <b>Backlog</b><span className="count" style={{ marginLeft: "auto" }}>{backlog.length} issues</span>
            </div>
            <div className="panel-pad" style={{ paddingTop: 4, paddingBottom: 8 }}>
              {backlog.map((i) => (
                <IssueRow key={i.key} issue={i} destinations={destFor(null)}
                  onMove={(d) => move(i, d)} onOpen={() => nav(`/issues/${i.key}`)} />
              ))}
              {!backlog.length && <div className="muted" style={{ padding: "10px 0" }}>Backlog is empty.</div>}
            </div>
          </div>
        </>
      )}
    </>
  );
}
