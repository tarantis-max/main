/** Tiny fetch wrapper for the dashboard proxy API.
 *  Throws Error(message) on any non-2xx so views can show it directly. */
export async function api(path, opts = {}) {
  const init = { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) } };
  if (init.body !== undefined && typeof init.body !== "string") init.body = JSON.stringify(init.body);
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw new Error("Cannot reach the proxy — start it with start.bat or `node dashboard/server.js`.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export const fmtDate = (d) => (d ? String(d).slice(0, 10) : "—");

export const fmtAgo = (iso) => {
  if (!iso) return "—";
  const mins = Math.round((Date.now() - new Date(iso)) / 60000);
  if (mins < 60) return `${Math.max(mins, 0)}m ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 60 / 24)}d ago`;
};

export const fmtSize = (n) => {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
};
