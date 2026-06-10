import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

/* ---- Spinner / loading / error ---- */
export const Spinner = ({ label = "Loading…" }) => (
  <div className="center-note"><span className="spin">↻</span> {label}</div>
);

export const ErrorBox = ({ error }) => (error ? <div className="error-box">{String(error)}</div> : null);

/* ---- Status pill (colored by Jira status category) ---- */
export const StatusPill = ({ status, category }) => (
  <span className={`pill cat-${category || "new"}`}>{status || "—"}</span>
);

export const RiskPill = ({ risk }) => {
  const cls = { Green: "green", Yellow: "yellow", Red: "red" }[risk] || "muted";
  return <span className={`pill ${cls}`}>{risk || "—"}</span>;
};

/* ---- Modal ---- */
export function Modal({ kicker, title, onClose, children, wide }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" style={wide ? { maxWidth: 920 } : undefined}>
        <div className="modal-head">
          <div>
            {kicker && <div className="m-kicker">{kicker}</div>}
            <h3>{title}</h3>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

/* ---- Toast ---- */
const ToastCtx = createContext(() => {});
export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null);
  const timer = useRef();
  const show = useCallback((msg, isError = false) => {
    clearTimeout(timer.current);
    setToast({ msg, isError });
    timer.current = setTimeout(() => setToast(null), isError ? 6000 : 3200);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {toast && <div className={`toast${toast.isError ? " err" : ""}`}>{toast.msg}</div>}
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/* ---- Debounced value ---- */
export function useDebounce(value, ms = 350) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/* ---- Sortable table header ---- */
export function SortTh({ id, sort, setSort, children }) {
  const active = sort.col === id;
  return (
    <th className="sortable" onClick={() => setSort({ col: id, dir: active && sort.dir === "asc" ? "desc" : "asc" })}>
      {children}{active ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
    </th>
  );
}

export function sortRows(rows, sort, getters = {}) {
  if (!sort.col) return rows;
  const get = getters[sort.col] || ((r) => r[sort.col]);
  return [...rows].sort((a, b) => {
    const av = get(a), bv = get(b);
    const cmp = typeof av === "number" && typeof bv === "number"
      ? av - bv
      : String(av ?? "").localeCompare(String(bv ?? ""));
    return sort.dir === "asc" ? cmp : -cmp;
  });
}
