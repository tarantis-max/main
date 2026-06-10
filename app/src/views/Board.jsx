import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtDate } from "../api.js";
import { useProject } from "../state.jsx";
import { ErrorBox, Spinner, useToast } from "../components/ui.jsx";

/* Status board with HTML5 drag-and-drop. Columns are the project's real
   workflow statuses; dropping a card calls the matching workflow transition. */
export default function Board() {
  const { project, ready } = useProject();
  const toast = useToast();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [dragKey, setDragKey] = useState(null);
  const [overCol, setOverCol] = useState(null);

  const load = async () => {
    if (!project) return;
    setLoading(true); setError("");
    try { setData(await api(`/api/board?project=${encodeURIComponent(project)}`)); }
    catch (e) { setError(String(e.message || e)); }
    setLoading(false);
  };
  useEffect(() => { load(); }, [project]); // eslint-disable-line react-hooks/exhaustive-deps

  const byStatus = useMemo(() => {
    const m = {};
    for (const i of data?.issues || []) (m[i.statusId] = m[i.statusId] || []).push(i);
    return m;
  }, [data]);

  const drop = async (col) => {
    setOverCol(null);
    const key = dragKey;
    setDragKey(null);
    if (!key || !data) return;
    const issue = data.issues.find((i) => i.key === key);
    if (!issue || String(issue.statusId) === String(col.id)) return;
    // optimistic move, rolled back on failure
    const prev = data;
    setData({ ...data, issues: data.issues.map((i) => (i.key === key ? { ...i, statusId: col.id, status: col.name, statusCategory: col.category } : i)) });
    try {
      await api(`/api/issues/${encodeURIComponent(key)}/transition`, { method: "POST", body: { statusId: col.id, status: col.name } });
      toast(`${key} → ${col.name}`);
    } catch (e) {
      setData(prev);
      toast(`Could not move ${key}: ${e.message}`, true);
    }
  };

  if (!ready) return <Spinner />;
  return (
    <>
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Board</h2>
        <span className="muted" style={{ fontSize: 12 }}>drag cards between columns · done issues shown for 14 days</span>
        <span style={{ marginLeft: "auto" }} />
        <button className="btn" onClick={load} disabled={loading}>{loading ? <span className="spin">↻</span> : "⟳"} Refresh</button>
      </div>
      <ErrorBox error={error} />
      {loading && !data && <Spinner label="Loading board…" />}
      {data && (
        <div className="kanban" style={{ gridTemplateColumns: `repeat(${Math.max(data.columns.length, 1)}, minmax(230px, 1fr))`, overflowX: "auto" }}>
          {data.columns.map((col) => {
            const items = byStatus[col.id] || [];
            return (
              <div key={col.id}
                className={`kcol${overCol === col.id ? " drop-over" : ""}`}
                onDragOver={(e) => { e.preventDefault(); setOverCol(col.id); }}
                onDragLeave={() => setOverCol((c) => (c === col.id ? null : c))}
                onDrop={(e) => { e.preventDefault(); drop(col); }}>
                <div className="kcol-head">
                  <span className={`pill cat-${col.category}`}>{col.name}</span>
                  <span className="count">{items.length}</span>
                </div>
                <div className="kcol-body">
                  {items.map((i) => (
                    <div key={i.key} draggable
                      className={`kcard${dragKey === i.key ? " dragging" : ""}`}
                      onDragStart={() => setDragKey(i.key)}
                      onDragEnd={() => { setDragKey(null); setOverCol(null); }}
                      onClick={() => nav(`/issues/${i.key}`)}>
                      <div className="k-top">
                        <span className="key-link">{i.key}</span>
                        <span className="pill muted">{i.type}</span>
                      </div>
                      <div className="k-title">{i.summary}</div>
                      <div className="k-meta">
                        {i.assignee
                          ? <span className="avatar-cell">{i.assigneeAvatar && <img className="avatar" src={i.assigneeAvatar} alt="" />} {i.assignee}</span>
                          : <span>Unassigned</span>}
                        {i.duedate && <span>· due {fmtDate(i.duedate)}</span>}
                      </div>
                    </div>
                  ))}
                  {!items.length && <div className="muted" style={{ fontSize: 12, padding: 6 }}>—</div>}
                </div>
              </div>
            );
          })}
          {!data.columns.length && <div className="center-note">No workflow statuses found for this project.</div>}
        </div>
      )}
    </>
  );
}
