import { useEffect, useMemo, useState } from "react";
import { api, fmtDate } from "../api.js";
import { useProject } from "../state.jsx";
import { ErrorBox, Modal, SortTh, Spinner, sortRows, useToast } from "../components/ui.jsx";

const STATUS_CLS = {
  "Pending Review": "yellow", Approved: "green", Rejected: "red",
  Implemented: "accent", Closed: "muted", Draft: "muted",
};
const TYPE_CLS = { Emergency: "red", Normal: "accent", Standard: "muted" };
const CrStatus = ({ s }) => <span className={`pill ${STATUS_CLS[s] || "muted"}`}>{s}</span>;
const CrType = ({ t }) => <span className={`pill ${TYPE_CLS[t] || "muted"}`}>{t}</span>;

// Actions available from each CR status (any CAB member can approve)
const ACTIONS_FOR = {
  "Pending Review": [["approve", "✅ Approve", "good"], ["reject", "✕ Reject", "danger"]],
  Approved: [["implement", "✔ Mark implemented", ""], ["reject", "✕ Reject", "danger"]],
  Implemented: [["close", "🔒 Close", ""]],
  Rejected: [["close", "🔒 Close", ""]],
  Draft: [["approve", "✅ Approve", "good"], ["reject", "✕ Reject", "danger"]],
};

function CrModal({ cr, onClose, onChanged }) {
  const toast = useToast();
  const [comments, setComments] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api(`/api/projects/${encodeURIComponent(cr.id)}/comments`)
      .then((d) => setComments(d.comments || [])).catch(() => setComments([]));
  }, [cr.id]);

  const history = (comments || []).filter((c) => /\[(APPROVED|REJECTED|IMPLEMENTED|CLOSED)\]/.test(c.text));
  const discussion = (comments || []).filter((c) => !history.includes(c));

  const act = async (action) => {
    setBusy(action);
    try {
      await api(`/api/changes/${encodeURIComponent(cr.id)}/action`, { method: "POST", body: { action, note } });
      toast(`CR ${cr.id} ${action}d`);
      onChanged();
      onClose();
    } catch (e) { toast(`${action} failed: ${e.message}`, true); setBusy(""); }
  };
  const postComment = async () => {
    if (!note.trim()) return;
    try {
      const { comment } = await api(`/api/projects/${encodeURIComponent(cr.id)}/comments`, { method: "POST", body: { body: note } });
      setComments((c) => [...(c || []), comment]);
      setNote("");
    } catch (e) { toast("Comment failed: " + e.message, true); }
  };

  return (
    <Modal kicker={`Change request · ${cr.id}`} title={cr.title} onClose={onClose} wide>
      <div className="toolbar">
        <CrStatus s={cr.crStatus} /><CrType t={cr.type} />
        <span className="pill muted">Impact: {cr.impact}</span>
        <span style={{ marginLeft: "auto" }} />
        {cr.url && <a className="btn sm" href={cr.url} target="_blank" rel="noreferrer">Open in Jira ↗</a>}
      </div>
      <div className="detail-grid">
        <div>
          <label>Description / justification</label>
          <p style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{cr.description || <span className="muted">—</span>}</p>
          {cr.rollbackPlan && (<><label>Rollback plan</label>
            <p style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{cr.rollbackPlan}</p></>)}

          <label>Approval history</label>
          {comments === null ? <Spinner label="Loading…" /> : (
            <div style={{ marginTop: 4, marginBottom: 14 }}>
              {!history.length && <div className="muted" style={{ padding: "8px 0" }}>No decisions recorded yet.</div>}
              {history.map((c, i) => (
                <div className="comment" key={i}>
                  <div className="c-head"><b>{c.author}</b> · {fmtDate(c.created)}</div>
                  <div className="c-body">{c.text}</div>
                </div>
              ))}
            </div>
          )}
          {comments !== null && (
            <>
              <label>Discussion</label>
              {!discussion.length && <div className="muted" style={{ padding: "8px 0" }}>No comments.</div>}
              {discussion.map((c, i) => (
                <div className="comment" key={i}>
                  <div className="c-head"><b>{c.author}</b> · {fmtDate(c.created)}</div>
                  <div className="c-body">{c.text}</div>
                </div>
              ))}
            </>
          )}
        </div>
        <div>
          <div className="panel panel-pad props" style={{ marginBottom: 14 }}>
            <div className="prop"><span className="k">Requestor</span><span className="v">{cr.requestor || "—"}</span></div>
            <div className="prop"><span className="k">Affected systems</span><span className="v">{cr.affectedSystems || "—"}</span></div>
            <div className="prop"><span className="k">Submitted</span><span className="v">{fmtDate(cr.created)}</span></div>
            <div className="prop"><span className="k">Planned end</span><span className="v">{fmtDate(cr.plannedEnd)}</span></div>
          </div>
          <div className="field">
            <label>Note (attached to decision or posted as comment)</label>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional context…" />
          </div>
          <div className="form-actions" style={{ flexWrap: "wrap" }}>
            {(ACTIONS_FOR[cr.crStatus] || []).map(([action, label, cls]) => (
              <button key={action} className={`btn sm ${cls}`} disabled={!!busy} onClick={() => act(action)}>
                {busy === action ? <span className="spin">↻</span> : label}
              </button>
            ))}
            <button className="btn sm" disabled={!note.trim()} onClick={postComment}>Comment only</button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function NewCrModal({ onClose, onCreated }) {
  const toast = useToast();
  const { project, current } = useProject();
  const types = current?.issueTypes?.length ? current.issueTypes : ["Task"];
  const [form, setForm] = useState({ issueType: types.includes("Task") ? "Task" : types[0], type: "Normal", impact: "Medium" });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const submit = async () => {
    if (!form.title?.trim()) { toast("Title is required.", true); return; }
    if (!form.description?.trim()) { toast("Description is required.", true); return; }
    setBusy(true);
    try {
      const r = await api(`/api/changes?project=${encodeURIComponent(project)}`, { method: "POST", body: form });
      toast(`CR ${r.key} submitted`);
      onCreated(); onClose();
    } catch (e) { toast("Submit failed: " + e.message, true); setBusy(false); }
  };
  return (
    <Modal kicker={`New change request in ${project}`} title="Submit for CAB review" onClose={onClose}>
      <div className="form-grid">
        <div className="field full"><label>Title / summary *</label><input autoFocus value={form.title || ""} onChange={(e) => set("title", e.target.value)} /></div>
        <div className="field"><label>Issue type</label>
          <select value={form.issueType} onChange={(e) => set("issueType", e.target.value)}>{types.map((t) => <option key={t}>{t}</option>)}</select></div>
        <div className="field"><label>Change type</label>
          <select value={form.type} onChange={(e) => set("type", e.target.value)}><option>Standard</option><option>Normal</option><option>Emergency</option></select></div>
        <div className="field"><label>Impact</label>
          <select value={form.impact} onChange={(e) => set("impact", e.target.value)}><option>Low</option><option>Medium</option><option>High</option></select></div>
        <div className="field"><label>Planned end</label><input type="date" value={form.plannedEnd || ""} onChange={(e) => set("plannedEnd", e.target.value)} /></div>
        <div className="field full"><label>Affected systems</label><input value={form.affectedSystems || ""} onChange={(e) => set("affectedSystems", e.target.value)} placeholder="e.g. Colleague, Banner, Network" /></div>
        <div className="field full"><label>Description / justification *</label><textarea value={form.description || ""} onChange={(e) => set("description", e.target.value)} /></div>
        <div className="field full"><label>Rollback plan</label><textarea value={form.rollbackPlan || ""} onChange={(e) => set("rollbackPlan", e.target.value)} /></div>
        <div className="form-actions full">
          <button className="btn primary" disabled={busy} onClick={submit}>{busy ? <span className="spin">↻</span> : "＋ Submit CR"}</button>
          <button className="btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </Modal>
  );
}

export default function Changes() {
  const { project, ready } = useProject();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sort, setSort] = useState({ col: "created", dir: "desc" });
  const [openId, setOpenId] = useState(null);
  const [creating, setCreating] = useState(false);

  const load = async () => {
    if (!project) return;
    setLoading(true); setError("");
    try { setData(await api(`/api/changes?project=${encodeURIComponent(project)}`)); }
    catch (e) { setError(String(e.message || e)); }
    setLoading(false);
  };
  useEffect(() => { load(); }, [project]); // eslint-disable-line react-hooks/exhaustive-deps

  const changes = data?.changes || [];
  const count = (s) => changes.filter((c) => c.crStatus === s).length;
  const rows = useMemo(() => sortRows(changes, sort), [changes, sort]);
  const open = changes.find((c) => c.id === openId);

  if (!ready) return <Spinner />;
  return (
    <>
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Change Management</h2>
        <span style={{ marginLeft: "auto" }} />
        <button className="btn" onClick={load} disabled={loading}>{loading ? <span className="spin">↻</span> : "⟳"} Refresh</button>
        <button className="btn primary" onClick={() => setCreating(true)}>＋ New CR</button>
      </div>
      <ErrorBox error={error} />
      {loading && !data && <Spinner label="Loading change requests…" />}
      {data && (
        <>
          <div className="kpis">
            <div className="kpi accent"><div className="label">Total CRs</div><div className="value">{changes.length}</div></div>
            <div className="kpi yellow"><div className="label">Pending review</div><div className="value">{count("Pending Review")}</div></div>
            <div className="kpi green"><div className="label">Approved</div><div className="value">{count("Approved")}</div></div>
            <div className="kpi red"><div className="label">Rejected</div><div className="value">{count("Rejected")}</div></div>
            <div className="kpi accent"><div className="label">Implemented</div><div className="value">{count("Implemented")}</div></div>
          </div>
          <div className="panel">
            <table className="data">
              <thead><tr>
                <SortTh id="id" sort={sort} setSort={setSort}>Key</SortTh>
                <SortTh id="title" sort={sort} setSort={setSort}>Title</SortTh>
                <SortTh id="type" sort={sort} setSort={setSort}>Type</SortTh>
                <SortTh id="impact" sort={sort} setSort={setSort}>Impact</SortTh>
                <SortTh id="requestor" sort={sort} setSort={setSort}>Requestor</SortTh>
                <SortTh id="created" sort={sort} setSort={setSort}>Submitted</SortTh>
                <SortTh id="plannedEnd" sort={sort} setSort={setSort}>Planned end</SortTh>
                <SortTh id="crStatus" sort={sort} setSort={setSort}>Status</SortTh>
              </tr></thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} onClick={() => setOpenId(c.id)}>
                    <td><span className="key-link">{c.id}</span></td>
                    <td>{c.title}</td>
                    <td><CrType t={c.type} /></td>
                    <td>{c.impact}</td>
                    <td>{c.requestor}</td>
                    <td>{fmtDate(c.created)}</td>
                    <td>{fmtDate(c.plannedEnd)}</td>
                    <td><CrStatus s={c.crStatus} /></td>
                  </tr>
                ))}
                {!rows.length && <tr className="empty"><td colSpan={8}>No change requests yet — click <b>New CR</b> to submit one.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
      {open && <CrModal cr={open} onClose={() => setOpenId(null)} onChanged={load} />}
      {creating && <NewCrModal onClose={() => setCreating(false)} onCreated={load} />}
    </>
  );
}
