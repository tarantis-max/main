import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fmtDate, fmtSize } from "../api.js";
import { ErrorBox, RiskPill, Spinner, StatusPill, useDebounce, useToast } from "../components/ui.jsx";

const PRIORITIES = ["Highest", "High", "Medium", "Low", "Lowest"];

/* Assignee picker backed by Jira user search */
function AssigneePicker({ issue, onAssigned }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [users, setUsers] = useState([]);
  const dq = useDebounce(q, 300);
  const boxRef = useRef();

  useEffect(() => {
    if (!open) return;
    api(`/api/users?q=${encodeURIComponent(dq)}`).then((d) => setUsers(d.users || [])).catch(() => setUsers([]));
  }, [dq, open]);

  useEffect(() => {
    const onClick = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const assign = async (accountId, name) => {
    try {
      await api(`/api/issues/${issue.key}`, { method: "PUT", body: { assigneeId: accountId } });
      toast(accountId ? `Assigned to ${name}` : "Unassigned");
      setOpen(false);
      onAssigned();
    } catch (e) { toast("Assign failed: " + e.message, true); }
  };

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      <button className="btn sm" onClick={() => setOpen((o) => !o)}>
        {issue.assignee ? (
          <span className="avatar-cell">
            {issue.assignee.avatar && <img className="avatar" src={issue.assignee.avatar} alt="" />}
            {issue.assignee.name}
          </span>
        ) : "Unassigned"} ▾
      </button>
      {open && (
        <div className="panel" style={{ position: "absolute", right: 0, top: "110%", width: 260, zIndex: 50, padding: 10 }}>
          <input autoFocus style={{ width: "100%" }} placeholder="Search people…" value={q} onChange={(e) => setQ(e.target.value)} />
          <div style={{ maxHeight: 220, overflowY: "auto", marginTop: 8 }}>
            <div className="comment" style={{ cursor: "pointer", padding: "7px 4px" }} onClick={() => assign(null)}>
              <span className="muted">Unassign</span>
            </div>
            {users.map((u) => (
              <div key={u.accountId} className="comment" style={{ cursor: "pointer", padding: "7px 4px" }}
                onClick={() => assign(u.accountId, u.name)}>
                <span className="avatar-cell">{u.avatar && <img className="avatar" src={u.avatar} alt="" />} {u.name}</span>
              </div>
            ))}
            {!users.length && <div className="muted" style={{ padding: 8, fontSize: 12 }}>Type to search…</div>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function IssueDetail() {
  const { issueKey } = useParams();
  const toast = useToast();
  const [issue, setIssue] = useState(null);
  const [error, setError] = useState("");
  const [editDesc, setEditDesc] = useState(null);   // null = not editing
  const [editSummary, setEditSummary] = useState(null);
  const [newLabel, setNewLabel] = useState("");
  const [newComment, setNewComment] = useState("");
  const [busy, setBusy] = useState("");

  const load = async () => {
    setError("");
    try { setIssue(await api(`/api/issues/${encodeURIComponent(issueKey)}`)); }
    catch (e) { setError(String(e.message || e)); }
  };
  useEffect(() => { setIssue(null); load(); }, [issueKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (body, label) => {
    setBusy(label);
    try {
      await api(`/api/issues/${encodeURIComponent(issueKey)}`, { method: "PUT", body });
      toast("Saved to Jira");
      await load();
    } catch (e) { toast("Save failed: " + e.message, true); }
    setBusy("");
  };

  const transition = async (id, name) => {
    setBusy("transition");
    try {
      await api(`/api/issues/${encodeURIComponent(issueKey)}/transition`, { method: "POST", body: { id } });
      toast(`Status → ${name}`);
      await load();
    } catch (e) { toast("Transition failed: " + e.message, true); }
    setBusy("");
  };

  const postComment = async () => {
    if (!newComment.trim()) return;
    setBusy("comment");
    try {
      await api(`/api/projects/${encodeURIComponent(issueKey)}/comments`, { method: "POST", body: { body: newComment } });
      setNewComment("");
      await load();
    } catch (e) { toast("Comment failed: " + e.message, true); }
    setBusy("");
  };

  if (error) return <><ErrorBox error={error} /><Link to="/issues">← Back to issues</Link></>;
  if (!issue) return <Spinner label={`Loading ${issueKey}…`} />;

  const vpmoRows = [
    ["Risk", issue.vpmo.risk && <RiskPill risk={issue.vpmo.risk} />],
    ["Portfolio", issue.vpmo.portfolio],
    ["Sponsor", issue.vpmo.sponsor],
    ["Compliance", issue.vpmo.compliance],
    ["Project ID", issue.vpmo.projectId],
    ["% complete", issue.vpmo.pctComplete != null ? `${issue.vpmo.pctComplete}%` : ""],
  ].filter(([, v]) => v);

  return (
    <>
      <div className="toolbar" style={{ marginBottom: 6 }}>
        <Link to="/issues" className="muted" style={{ fontSize: 12 }}>← Issues</Link>
        <span className="key-link">{issue.key}</span>
        <span className="pill muted">{issue.type}</span>
        {issue.parent && <span className="muted" style={{ fontSize: 12 }}>in <Link to={`/issues/${issue.parent.key}`}>{issue.parent.key}</Link></span>}
        <span style={{ marginLeft: "auto" }} />
        <a className="btn sm" href={issue.url} target="_blank" rel="noreferrer">Open in Jira ↗</a>
      </div>

      {editSummary === null ? (
        <h2 style={{ cursor: "text", marginBottom: 16 }} title="Click to edit" onClick={() => setEditSummary(issue.summary)}>{issue.summary}</h2>
      ) : (
        <div className="toolbar">
          <input autoFocus style={{ flex: 1, fontSize: 15, fontWeight: 600 }} value={editSummary} onChange={(e) => setEditSummary(e.target.value)} />
          <button className="btn primary sm" disabled={!!busy} onClick={async () => { await save({ summary: editSummary }, "summary"); setEditSummary(null); }}>Save</button>
          <button className="btn sm" onClick={() => setEditSummary(null)}>Cancel</button>
        </div>
      )}

      <div className="detail-grid">
        <div>
          <div className="toolbar">
            <StatusPill status={issue.status} category={issue.statusCategory} />
            {issue.transitions.map((t) => (
              <button key={t.id} className="btn sm" disabled={!!busy} onClick={() => transition(t.id, t.to)}>→ {t.to || t.name}</button>
            ))}
          </div>

          <label>Description</label>
          {editDesc === null ? (
            <p style={{ whiteSpace: "pre-wrap", marginTop: 6, cursor: "text" }} title="Click to edit" onClick={() => setEditDesc(issue.description)}>
              {issue.description || <span className="muted">No description — click to add.</span>}
            </p>
          ) : (
            <div style={{ marginTop: 6 }}>
              <textarea rows={6} value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
              <div className="form-actions">
                <button className="btn primary sm" disabled={!!busy} onClick={async () => { await save({ description: editDesc }, "desc"); setEditDesc(null); }}>Save</button>
                <button className="btn sm" onClick={() => setEditDesc(null)}>Cancel</button>
              </div>
            </div>
          )}

          {!!issue.subtasks.length && (
            <>
              <label>Sub-tasks</label>
              <div style={{ margin: "6px 0 14px" }}>
                {issue.subtasks.map((s) => (
                  <div key={s.key} className="comment" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <Link to={`/issues/${s.key}`} className="key-link">{s.key}</Link>
                    <span style={{ flex: 1 }}>{s.summary}</span>
                    <StatusPill status={s.status} category={s.statusCategory} />
                  </div>
                ))}
              </div>
            </>
          )}

          {!!issue.links.length && (
            <>
              <label>Linked issues</label>
              <div style={{ margin: "6px 0 14px" }}>
                {issue.links.map((l, i) => (
                  <div key={i} className="comment" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <span className="muted" style={{ fontSize: 12 }}>{l.direction}</span>
                    <Link to={`/issues/${l.key}`} className="key-link">{l.key}</Link>
                    <span style={{ flex: 1 }}>{l.summary}</span>
                    <span className="pill muted">{l.status}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {!!issue.attachments.length && (
            <>
              <label>Attachments</label>
              <div style={{ margin: "6px 0 14px" }}>
                {issue.attachments.map((a) => (
                  <div key={a.id} className="comment" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <a href={`/api/attachments/${a.id}/${encodeURIComponent(a.filename)}`} target="_blank" rel="noreferrer">{a.filename}</a>
                    <span className="muted" style={{ fontSize: 12 }}>{fmtSize(a.size)} · {a.author} · {fmtDate(a.created)}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          <label>Comments</label>
          <div style={{ marginTop: 4 }}>
            {!issue.comments.length && <div className="muted" style={{ padding: "8px 0" }}>No comments yet.</div>}
            {issue.comments.map((c, i) => (
              <div className="comment" key={i}>
                <div className="c-head"><b>{c.author}</b> · {fmtDate(c.created)}</div>
                <div className="c-body">{c.text}</div>
              </div>
            ))}
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <input style={{ flex: 1 }} placeholder="Add a comment…" value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && postComment()} />
              <button className="btn" disabled={busy === "comment"} onClick={postComment}>Post</button>
            </div>
          </div>
        </div>

        <div>
          <div className="panel panel-pad props">
            <div className="prop"><span className="k">Assignee</span><span className="v"><AssigneePicker issue={issue} onAssigned={load} /></span></div>
            <div className="prop"><span className="k">Reporter</span><span className="v">{issue.reporter?.name || "—"}</span></div>
            <div className="prop"><span className="k">Priority</span><span className="v">
              <select value={issue.priority || ""} disabled={!!busy} onChange={(e) => save({ priority: e.target.value }, "priority")}>
                {!issue.priority && <option value="">—</option>}
                {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
              </select></span></div>
            <div className="prop"><span className="k">Due date</span><span className="v">
              <input type="date" value={issue.duedate || ""} disabled={!!busy} onChange={(e) => save({ duedate: e.target.value }, "due")} /></span></div>
            <div className="prop"><span className="k">Created</span><span className="v">{fmtDate(issue.created)}</span></div>
            <div className="prop"><span className="k">Updated</span><span className="v">{fmtDate(issue.updated)}</span></div>
            <div className="prop" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
              <span className="k">Labels</span>
              <span className="labels-row">
                {issue.labels.map((l) => (
                  <span className="chip" key={l}>{l}
                    <button title="Remove" disabled={!!busy}
                      onClick={() => save({ labels: issue.labels.filter((x) => x !== l) }, "labels")}>✕</button>
                  </span>
                ))}
                <input style={{ width: 110, padding: "2px 8px", fontSize: 12 }} placeholder="+ add" value={newLabel}
                  onChange={(e) => setNewLabel(e.target.value)}
                  onKeyDown={async (e) => {
                    if (e.key === "Enter" && newLabel.trim()) {
                      await save({ labels: [...issue.labels, newLabel.trim().replace(/\s+/g, "_")] }, "labels");
                      setNewLabel("");
                    }
                  }} />
              </span>
            </div>
          </div>
          {!!vpmoRows.length && (
            <div className="panel panel-pad props" style={{ marginTop: 14 }}>
              <label style={{ paddingBottom: 6 }}>VPMO</label>
              {vpmoRows.map(([k, v]) => (
                <div className="prop" key={k}><span className="k">{k}</span><span className="v">{v}</span></div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
