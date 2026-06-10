import { useEffect, useMemo, useState } from "react";
import { api, fmtDate } from "../api.js";
import { useProject } from "../state.jsx";
import { ErrorBox, Modal, RiskPill, SortTh, Spinner, sortRows, useToast } from "../components/ui.jsx";

const PHASES = ["Planning", "In-Flight", "Stabilization", "Closed"];
const RISKS = ["Green", "Yellow", "Red"];

const daysUntil = (d) => (d ? Math.round((new Date(d + "T00:00:00") - new Date()) / 86400000) : null);

function DueBadge({ end, phase }) {
  if (!end || phase === "Closed") return null;
  const days = daysUntil(end);
  if (days < 0) return <span className="pill red">{-days}d overdue</span>;
  if (days <= 30) return <span className="pill yellow">due {days}d</span>;
  return null;
}

/* ---------- detail / edit modal ---------- */
function ProjectModal({ p, onClose, onSaved }) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({});
  const [comments, setComments] = useState(null);
  const [newComment, setNewComment] = useState("");
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    api(`/api/projects/${encodeURIComponent(p.id)}/comments`)
      .then((d) => setComments(d.comments || []))
      .catch(() => setComments([]));
  }, [p.id]);

  const startEdit = () => {
    setForm({ phase: p.phase, risk: p.risk, end: p.end, portfolio: p.portfolio, compliance: p.compliance, notes: p.notes });
    setEditing(true);
  };
  const save = async () => {
    const changed = {};
    const orig = { phase: p.phase, risk: p.risk, end: p.end, portfolio: p.portfolio, compliance: p.compliance, notes: p.notes };
    for (const k of Object.keys(form)) if (form[k] !== orig[k]) changed[k] = form[k];
    if (!Object.keys(changed).length) { setEditing(false); return; }
    setSaving(true);
    try {
      const r = await api(`/api/projects/${encodeURIComponent(p.id)}`, { method: "PATCH", body: changed });
      toast(`Saved to Jira${r.transitionApplied ? ` — status → ${r.transitionApplied}` : ""}${r.degradedToLabels ? " (stored as labels)" : ""}`);
      setEditing(false);
      onSaved();
    } catch (e) { toast("Save failed: " + e.message, true); }
    setSaving(false);
  };
  const postComment = async () => {
    if (!newComment.trim()) return;
    try {
      const { comment } = await api(`/api/projects/${encodeURIComponent(p.id)}/comments`, { method: "POST", body: { body: newComment } });
      setComments((c) => [...(c || []), comment]);
      setNewComment("");
    } catch (e) { toast("Comment failed: " + e.message, true); }
  };

  return (
    <Modal kicker={`${p.id}${p.projectId ? ` · ${p.projectId}` : ""}`} title={p.name} onClose={onClose} wide>
      {!editing ? (
        <>
          <div className="toolbar">
            <RiskPill risk={p.risk} />
            <span className="pill accent">{p.phase}</span>
            <span className="pill muted">{p.portfolio}</span>
            <span className="spacer" style={{ marginLeft: "auto" }} />
            <button className="btn sm" onClick={startEdit}>✎ Edit</button>
            {p.url && <a className="btn sm" href={p.url} target="_blank" rel="noreferrer">Open in Jira ↗</a>}
          </div>
          <div className="detail-grid">
            <div>
              <label>Notes / next milestone</label>
              <p style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{p.notes || <span className="muted">—</span>}</p>
              <div className="bar" style={{ marginBottom: 18 }}><div style={{ width: `${p.pct ?? 0}%` }} /></div>

              <label>Comments</label>
              {comments === null ? <Spinner label="Loading comments…" /> : (
                <div style={{ marginTop: 4 }}>
                  {!comments.length && <div className="muted" style={{ padding: "8px 0" }}>No comments yet.</div>}
                  {comments.map((c, i) => (
                    <div className="comment" key={i}>
                      <div className="c-head"><b>{c.author}</b> · {fmtDate(c.created)}</div>
                      <div className="c-body">{c.text}</div>
                    </div>
                  ))}
                  <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                    <input style={{ flex: 1 }} placeholder="Add a comment…" value={newComment}
                      onChange={(e) => setNewComment(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && postComment()} />
                    <button className="btn" onClick={postComment}>Post</button>
                  </div>
                </div>
              )}
            </div>
            <div className="panel panel-pad props">
              <div className="prop"><span className="k">Business sponsor</span><span className="v">{p.sponsor || "—"}</span></div>
              <div className="prop"><span className="k">IT owner</span><span className="v">{p.itOwner || "—"}</span></div>
              <div className="prop"><span className="k">Start</span><span className="v">{fmtDate(p.start)}</span></div>
              <div className="prop"><span className="k">Target end</span><span className="v">{fmtDate(p.end)} <DueBadge end={p.end} phase={p.phase} /></span></div>
              <div className="prop"><span className="k">% complete</span><span className="v">{p.pct ?? 0}%</span></div>
              <div className="prop"><span className="k">Compliance</span><span className="v">{p.compliance || "N/A"}</span></div>
              <div className="prop"><span className="k">Dependencies</span><span className="v">{p.dependencies || "—"}</span></div>
            </div>
          </div>
        </>
      ) : (
        <div className="form-grid">
          <div className="field"><label>Phase</label>
            <select value={form.phase} onChange={(e) => set("phase", e.target.value)}>{PHASES.map((x) => <option key={x}>{x}</option>)}</select></div>
          <div className="field"><label>Risk</label>
            <select value={form.risk} onChange={(e) => set("risk", e.target.value)}>{RISKS.map((x) => <option key={x}>{x}</option>)}</select></div>
          <div className="field"><label>Target end</label>
            <input type="date" value={form.end || ""} onChange={(e) => set("end", e.target.value)} /></div>
          <div className="field"><label>Portfolio</label>
            <input value={form.portfolio || ""} onChange={(e) => set("portfolio", e.target.value)} /></div>
          <div className="field full"><label>Compliance driver</label>
            <input value={form.compliance || ""} onChange={(e) => set("compliance", e.target.value)} placeholder="FERPA; GLBA; …" /></div>
          <div className="field full"><label>Notes / next milestone</label>
            <textarea value={form.notes || ""} onChange={(e) => set("notes", e.target.value)} /></div>
          <div className="form-actions full">
            <button className="btn primary" disabled={saving} onClick={save}>{saving ? <span className="spin">↻</span> : "Save to Jira"}</button>
            <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      )}
    </Modal>
  );
}

/* ---------- new work item modal ---------- */
function NewItemModal({ onClose, onCreated }) {
  const toast = useToast();
  const { project, current } = useProject();
  const types = current?.issueTypes?.length ? current.issueTypes : ["Task"];
  const [form, setForm] = useState({ issueType: types[0], phase: "Planning", risk: "Green" });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const submit = async () => {
    if (!form.name?.trim()) { toast("Name is required.", true); return; }
    setBusy(true);
    try {
      const r = await api(`/api/projects?project=${encodeURIComponent(project)}`, { method: "POST", body: form });
      toast(`Created ${r.key}`);
      onCreated();
      onClose();
    } catch (e) { toast("Create failed: " + e.message, true); setBusy(false); }
  };
  return (
    <Modal kicker={`New work item in ${project}`} title="Create in Jira" onClose={onClose}>
      <div className="form-grid">
        <div className="field full"><label>Name / summary *</label><input autoFocus value={form.name || ""} onChange={(e) => set("name", e.target.value)} /></div>
        <div className="field"><label>Issue type</label>
          <select value={form.issueType} onChange={(e) => set("issueType", e.target.value)}>{types.map((t) => <option key={t}>{t}</option>)}</select></div>
        <div className="field"><label>Phase</label>
          <select value={form.phase} onChange={(e) => set("phase", e.target.value)}>{PHASES.map((x) => <option key={x}>{x}</option>)}</select></div>
        <div className="field"><label>Risk</label>
          <select value={form.risk} onChange={(e) => set("risk", e.target.value)}>{RISKS.map((x) => <option key={x}>{x}</option>)}</select></div>
        <div className="field"><label>Portfolio</label><input value={form.portfolio || ""} onChange={(e) => set("portfolio", e.target.value)} /></div>
        <div className="field"><label>Business sponsor</label><input value={form.sponsor || ""} onChange={(e) => set("sponsor", e.target.value)} /></div>
        <div className="field"><label>Project ID</label><input value={form.projectId || ""} onChange={(e) => set("projectId", e.target.value)} placeholder="P-0xx" /></div>
        <div className="field"><label>Start date</label><input type="date" value={form.start || ""} onChange={(e) => set("start", e.target.value)} /></div>
        <div className="field"><label>Target end</label><input type="date" value={form.end || ""} onChange={(e) => set("end", e.target.value)} /></div>
        <div className="field full"><label>Compliance driver</label><input value={form.compliance || ""} onChange={(e) => set("compliance", e.target.value)} /></div>
        <div className="field full"><label>Notes</label><textarea value={form.notes || ""} onChange={(e) => set("notes", e.target.value)} /></div>
        <div className="form-actions full">
          <button className="btn primary" disabled={busy} onClick={submit}>{busy ? <span className="spin">↻</span> : "＋ Create in Jira"}</button>
          <button className="btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </Modal>
  );
}

/* ---------- main view ---------- */
export default function Portfolio() {
  const toast = useToast();
  const { project, ready } = useProject();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState("board");
  const [filters, setFilters] = useState({ q: "", portfolio: "", phase: "", risk: "" });
  const [sort, setSort] = useState({ col: "", dir: "asc" });
  const [openId, setOpenId] = useState(null);
  const [creating, setCreating] = useState(false);
  const setF = (k, v) => setFilters((f) => ({ ...f, [k]: v }));

  const load = async () => {
    if (!project) return;
    setLoading(true); setError("");
    try { setData(await api(`/api/projects?project=${encodeURIComponent(project)}`)); }
    catch (e) { setError(String(e.message || e)); }
    setLoading(false);
  };
  useEffect(() => { load(); }, [project]); // eslint-disable-line react-hooks/exhaustive-deps

  const projects = data?.projects || [];
  const list = useMemo(() => projects.filter((p) =>
    (!filters.q || `${p.id} ${p.name} ${p.sponsor} ${p.itOwner} ${p.notes}`.toLowerCase().includes(filters.q.toLowerCase())) &&
    (!filters.portfolio || p.portfolio === filters.portfolio) &&
    (!filters.phase || p.phase === filters.phase) &&
    (!filters.risk || p.risk === filters.risk)
  ), [projects, filters]);

  const portfolios = useMemo(() => [...new Set(projects.map((p) => p.portfolio))].sort(), [projects]);
  const active = projects.filter((p) => p.phase !== "Closed");
  const kpis = {
    total: projects.length,
    active: active.length,
    avgPct: active.length ? Math.round(active.reduce((s, p) => s + (p.pct || 0), 0) / active.length) : 0,
    red: active.filter((p) => p.risk === "Red").length,
    yellow: active.filter((p) => p.risk === "Yellow").length,
    overdue: active.filter((p) => p.end && daysUntil(p.end) < 0).length,
  };
  const byPortfolio = portfolios
    .map((pf) => ({ name: pf, n: active.filter((p) => p.portfolio === pf).length }))
    .filter((x) => x.n > 0).sort((a, b) => b.n - a.n);
  const maxPf = Math.max(1, ...byPortfolio.map((x) => x.n));

  const sorted = sortRows(list, sort, { pct: (r) => r.pct ?? 0 });
  const open = projects.find((p) => p.id === openId);

  if (!ready) return <Spinner />;
  return (
    <>
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Portfolio</h2>
        <span className="muted" style={{ fontSize: 12 }}>{data ? `as of ${data.asOf}` : ""}</span>
        <span style={{ marginLeft: "auto" }} />
        <button className="btn" onClick={load} disabled={loading}>{loading ? <span className="spin">↻</span> : "⟳"} Refresh</button>
        <button className="btn primary" onClick={() => setCreating(true)}>＋ New work item</button>
      </div>
      <ErrorBox error={error} />
      {loading && !data && <Spinner label="Loading from Jira…" />}
      {data && (
        <>
          <div className="kpis">
            <div className="kpi accent"><div className="label">Projects</div><div className="value">{kpis.total}</div></div>
            <div className="kpi accent"><div className="label">Active</div><div className="value">{kpis.active}</div></div>
            <div className="kpi green"><div className="label">Avg % complete</div><div className="value">{kpis.avgPct}%</div></div>
            <div className="kpi red"><div className="label">Red</div><div className="value">{kpis.red}</div></div>
            <div className="kpi yellow"><div className="label">Yellow</div><div className="value">{kpis.yellow}</div></div>
            <div className="kpi red"><div className="label">Overdue</div><div className="value">{kpis.overdue}</div></div>
          </div>

          <div className="charts-row">
            <div className="panel panel-pad">
              <label>Active by portfolio</label>
              <div className="mini-bars" style={{ marginTop: 10 }}>
                {byPortfolio.map((x) => (
                  <div className="mini-bar" key={x.name}
                    onClick={() => setF("portfolio", filters.portfolio === x.name ? "" : x.name)}>
                    <span className="name">{x.name}</span>
                    <span className="track"><span className="fill" style={{ width: `${(x.n / maxPf) * 100}%`, display: "block", opacity: !filters.portfolio || filters.portfolio === x.name ? 1 : 0.3 }} /></span>
                    <span>{x.n}</span>
                  </div>
                ))}
                {!byPortfolio.length && <div className="muted">No active projects.</div>}
              </div>
            </div>
            <div className="panel panel-pad">
              <label>Risk (active)</label>
              <div className="mini-bars" style={{ marginTop: 10 }}>
                {RISKS.map((r) => {
                  const n = active.filter((p) => p.risk === r).length;
                  const color = { Green: "var(--green)", Yellow: "var(--yellow)", Red: "var(--red)" }[r];
                  return (
                    <div className="mini-bar" key={r} onClick={() => setF("risk", filters.risk === r ? "" : r)}>
                      <span className="name">{r}</span>
                      <span className="track"><span className="fill" style={{ width: `${(n / Math.max(1, active.length)) * 100}%`, background: color, display: "block", opacity: !filters.risk || filters.risk === r ? 1 : 0.3 }} /></span>
                      <span>{n}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="toolbar">
            <input placeholder="Search projects…" value={filters.q} onChange={(e) => setF("q", e.target.value)} style={{ width: 230 }} />
            <select value={filters.portfolio} onChange={(e) => setF("portfolio", e.target.value)}>
              <option value="">All portfolios</option>{portfolios.map((x) => <option key={x}>{x}</option>)}
            </select>
            <select value={filters.phase} onChange={(e) => setF("phase", e.target.value)}>
              <option value="">All phases</option>{PHASES.map((x) => <option key={x}>{x}</option>)}
            </select>
            <select value={filters.risk} onChange={(e) => setF("risk", e.target.value)}>
              <option value="">All risk</option>{RISKS.map((x) => <option key={x}>{x}</option>)}
            </select>
            <span className="muted" style={{ fontSize: 12 }}>{list.length} of {projects.length}</span>
            <span style={{ marginLeft: "auto" }} />
            <div className="seg">
              <button className={view === "board" ? "active" : ""} onClick={() => setView("board")}>Board</button>
              <button className={view === "table" ? "active" : ""} onClick={() => setView("table")}>Table</button>
            </div>
          </div>

          {view === "board" ? (
            <div className="kanban" style={{ gridTemplateColumns: `repeat(${PHASES.length}, minmax(230px, 1fr))` }}>
              {PHASES.map((ph) => {
                const items = list.filter((p) => p.phase === ph);
                return (
                  <div className="kcol" key={ph}>
                    <div className="kcol-head">{ph} <span className="count">{items.length}</span></div>
                    <div className="kcol-body">
                      {items.map((p) => (
                        <div key={p.id} className={`kcard risk-${p.risk}`} onClick={() => setOpenId(p.id)}>
                          <div className="k-top"><span className="key-link">{p.id}</span><RiskPill risk={p.risk} /></div>
                          <div className="k-title">{p.name}</div>
                          <div className="k-meta">
                            <span>{p.portfolio}</span>
                            {p.end && <span>· due {fmtDate(p.end)}</span>}
                            <DueBadge end={p.end} phase={p.phase} />
                          </div>
                          <div className="bar"><div style={{ width: `${p.pct ?? 0}%` }} /></div>
                        </div>
                      ))}
                      {!items.length && <div className="muted" style={{ fontSize: 12, padding: 6 }}>—</div>}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="panel">
              <table className="data">
                <thead><tr>
                  <SortTh id="id" sort={sort} setSort={setSort}>Key</SortTh>
                  <SortTh id="name" sort={sort} setSort={setSort}>Name</SortTh>
                  <SortTh id="phase" sort={sort} setSort={setSort}>Phase</SortTh>
                  <SortTh id="portfolio" sort={sort} setSort={setSort}>Portfolio</SortTh>
                  <SortTh id="sponsor" sort={sort} setSort={setSort}>Sponsor</SortTh>
                  <SortTh id="itOwner" sort={sort} setSort={setSort}>IT owner</SortTh>
                  <SortTh id="end" sort={sort} setSort={setSort}>Target end</SortTh>
                  <SortTh id="pct" sort={sort} setSort={setSort}>%</SortTh>
                  <SortTh id="risk" sort={sort} setSort={setSort}>Risk</SortTh>
                </tr></thead>
                <tbody>
                  {sorted.map((p) => (
                    <tr key={p.id} onClick={() => setOpenId(p.id)}>
                      <td><span className="key-link">{p.id}</span></td>
                      <td>{p.name}</td>
                      <td>{p.phase}</td>
                      <td>{p.portfolio}</td>
                      <td>{p.sponsor}</td>
                      <td>{p.itOwner}</td>
                      <td>{fmtDate(p.end)} <DueBadge end={p.end} phase={p.phase} /></td>
                      <td style={{ minWidth: 90 }}><div className="bar"><div style={{ width: `${p.pct ?? 0}%` }} /></div></td>
                      <td><RiskPill risk={p.risk} /></td>
                    </tr>
                  ))}
                  {!sorted.length && <tr className="empty"><td colSpan={9}>No projects match.</td></tr>}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {open && <ProjectModal p={open} onClose={() => setOpenId(null)} onSaved={load} />}
      {creating && <NewItemModal onClose={() => setCreating(false)} onCreated={load} />}
    </>
  );
}
