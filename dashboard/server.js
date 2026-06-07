/**
 * MU VPMO Dashboard — Jira live proxy
 * ------------------------------------
 * A tiny zero-dependency Node server (Node 18+) that:
 *   1. Serves the static dashboard (index.html).
 *   2. Exposes GET /api/projects — pulls live from Jira, maps Jira fields to
 *      the dashboard's project shape, and returns JSON.
 *
 * It holds your Jira API token server-side so the browser never sees it and
 * there are no CORS problems (the page and the API are same-origin).
 *
 * ---- Setup -------------------------------------------------------------
 *   export JIRA_BASE_URL="https://methodist.atlassian.net"
 *   export JIRA_EMAIL="jgreene@methodist.edu"
 *   export JIRA_TOKEN="<your Atlassian API token>"   # id.atlassian.com/manage-profile/security/api-tokens
 *   export JIRA_PROJECT="ITPM"        # optional, default ITPM
 *   # or override the whole query:
 *   # export JIRA_JQL='project = ITPM ORDER BY created DESC'
 *   node dashboard/server.js
 *   # open http://localhost:8787
 * -----------------------------------------------------------------------
 */
"use strict";
const http = require("http");
const fs = require("fs");
const path = require("path");

const CONFIG = {
  port: Number(process.env.PORT || 8787),
  baseUrl: (process.env.JIRA_BASE_URL || "https://methodist.atlassian.net").replace(/\/$/, ""),
  email: process.env.JIRA_EMAIL || "",
  token: process.env.JIRA_TOKEN || "",
  project: process.env.JIRA_PROJECT || "ITPM",
  jql: process.env.JIRA_JQL || "",
  cacheMs: Number(process.env.CACHE_MS || 60000), // cache Jira responses for 60s
};

/* ---- field mapping ----------------------------------------------------
   Adjust these to match your Jira configuration if it changes.          */
const FIELDS = {
  startDate: "customfield_10015", // "Start date" picker in ITPM
  // RAG / Portfolio / Compliance are read from labels if present:
  //   rag:Red | rag:Yellow | rag:Green
  //   portfolio:Infrastructure   (underscores become spaces)
  //   compliance:GLBA;FERPA      (semicolon-separated)
};
// status name (or category) -> dashboard phase
const PHASE_MAP = {
  "to do": "Planning",
  "backlog": "Planning",
  "selected for development": "Planning",
  "in progress": "In-Flight",
  "in review": "In-Flight",
  "stabilization": "Stabilization",
  "done": "Closed",
  "canceled": "Closed",
  "cancelled": "Closed",
};
const CATEGORY_PHASE = { new: "Planning", indeterminate: "In-Flight", done: "Closed" };

/* ---- helpers ---------------------------------------------------------- */
function authHeader() {
  return "Basic " + Buffer.from(`${CONFIG.email}:${CONFIG.token}`).toString("base64");
}
function textToAdf(text) {
  if (!text || !text.trim()) return null;
  return {
    type: "doc", version: 1,
    content: text.split("\n").map(line => ({
      type: "paragraph",
      content: line.trim() ? [{ type: "text", text: line }] : [],
    })),
  };
}
function adfToText(node) {
  if (!node) return "";
  if (typeof node === "string") return node;
  if (node.text) return node.text;
  let out = "";
  if (Array.isArray(node.content)) {
    for (const c of node.content) {
      out += adfToText(c);
      if (c.type === "paragraph" || c.type === "heading" || c.type === "listItem") out += " ";
    }
  }
  return out;
}
function labelValue(labels, prefix) {
  const hit = (labels || []).find(l => l.toLowerCase().startsWith(prefix + ":"));
  return hit ? hit.slice(prefix.length + 1).replace(/_/g, " ").replace(/;/g, "; ") : "";
}
function phaseFor(status) {
  if (!status) return "Planning";
  const byName = PHASE_MAP[(status.name || "").toLowerCase()];
  if (byName) return byName;
  return CATEGORY_PHASE[(status.statusCategory && status.statusCategory.key) || "new"] || "Planning";
}
function deriveRag(p) {
  // honored label wins; otherwise derive from schedule + progress
  if (p.rag) return p.rag;
  if (p.phase === "Closed") return "Green";
  const end = p.end ? new Date(p.end + "T00:00:00") : null;
  if (end) {
    const days = Math.round((end - new Date()) / 86400000);
    if (days < 0) return "Red";
    if (days <= 30 && (p.pct == null || p.pct < 50)) return "Yellow";
  }
  return "Green";
}

/* ---- Jira fetch (paginated via enhanced search) ---------------------- */
async function jiraSearch(jql, fields) {
  const all = [];
  let nextPageToken = undefined;
  do {
    const res = await fetch(`${CONFIG.baseUrl}/rest/api/3/search/jql`, {
      method: "POST",
      headers: { "Authorization": authHeader(), "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ jql, fields, maxResults: 100, nextPageToken }),
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`Jira ${res.status}: ${body.slice(0, 300)}`);
    }
    const data = await res.json();
    (data.issues || []).forEach(i => all.push(i));
    nextPageToken = data.nextPageToken;
  } while (nextPageToken);
  return all;
}

/* ---- map Jira issues -> dashboard projects --------------------------- */
function mapIssues(issues) {
  // children grouped by parent key for % rollup
  const childrenByParent = {};
  for (const i of issues) {
    const pkey = i.fields.parent && i.fields.parent.key;
    if (pkey) (childrenByParent[pkey] = childrenByParent[pkey] || []).push(i);
  }
  const isDone = i => (i.fields.status && i.fields.status.statusCategory && i.fields.status.statusCategory.key) === "done";
  function pct(issue) {
    const kids = childrenByParent[issue.key];
    if (kids && kids.length) return Math.round(kids.filter(isDone).length / kids.length * 100);
    return isDone(issue) ? 100 : 0;
  }
  // "projects" = non-subtask issues that have no parent (epics + orphan stories/tasks)
  const tops = issues.filter(i => !(i.fields.issuetype && i.fields.issuetype.subtask) && !(i.fields.parent));
  return tops.map(i => {
    const f = i.fields;
    const labels = f.labels || [];
    const p = {
      id: i.key,
      name: f.summary || "",
      phase: phaseFor(f.status),
      portfolio: labelValue(labels, "portfolio") || (f.issuetype && f.issuetype.name) || "Unassigned",
      sponsor: labelValue(labels, "sponsor") || (f.reporter && f.reporter.displayName) || "",
      itOwner: (f.assignee && f.assignee.displayName) || "",
      start: f[FIELDS.startDate] || "",
      end: f.duedate || "",
      pct: pct(i),
      rag: labelValue(labels, "rag") || "",
      dependencies: (f.issuelinks || []).map(l => {
        const o = l.outwardIssue || l.inwardIssue; return o ? o.key : null;
      }).filter(Boolean).join("; "),
      compliance: labelValue(labels, "compliance") || "N/A",
      notes: adfToText(f.description).trim().slice(0, 800),
      url: `${CONFIG.baseUrl}/browse/${i.key}`,
    };
    p.rag = deriveRag(p);
    return p;
  });
}

/* ---- write-back: update Jira from dashboard edits ------------------- */
async function applyTransition(key, targetPhase) {
  const r = await fetch(`${CONFIG.baseUrl}/rest/api/3/issue/${key}/transitions`, {
    headers: { Authorization: authHeader(), Accept: "application/json" },
  });
  if (!r.ok) return null;
  const { transitions } = await r.json();
  // Prefer a name-keyword match; fall back to status-category match.
  const hints = {
    Planning:      ["to do", "backlog", "open", "new"],
    "In-Flight":   ["in progress"],
    Stabilization: ["on hold", "stabiliz", "review"],
    Closed:        ["done", "closed", "complete", "resolved"],
  }[targetPhase] || [];
  const catKey = { Planning: "new", "In-Flight": "indeterminate", Stabilization: "indeterminate", Closed: "done" }[targetPhase];
  const match =
    transitions.find(t => hints.some(h => t.name.toLowerCase().includes(h))) ||
    transitions.find(t => t.to.statusCategory.key === catKey);
  if (!match) return null;
  await fetch(`${CONFIG.baseUrl}/rest/api/3/issue/${key}/transitions`, {
    method: "POST",
    headers: { Authorization: authHeader(), "Content-Type": "application/json" },
    body: JSON.stringify({ transition: { id: match.id } }),
  });
  return match.name;
}

async function handlePatch(key, body) {
  // Fetch current labels so we preserve any non-VPMO ones.
  const r = await fetch(`${CONFIG.baseUrl}/rest/api/3/issue/${key}?fields=labels`, {
    headers: { Authorization: authHeader(), Accept: "application/json" },
  });
  if (!r.ok) throw new Error(`Could not fetch issue ${key}: ${r.status}`);
  const issue = await r.json();
  const VPMO = ["rag:", "portfolio:", "compliance:", "sponsor:"];
  let labels = (issue.fields.labels || []).filter(l => !VPMO.some(p => l.toLowerCase().startsWith(p)));
  if (body.rag)        labels.push(`rag:${body.rag}`);
  if (body.portfolio)  labels.push(`portfolio:${body.portfolio.trim().replace(/ /g, "_")}`);
  if (body.compliance && body.compliance !== "N/A")
    labels.push(`compliance:${body.compliance.trim().replace(/;\s*/g, ";")}`);

  const fields = { labels };
  if ("end"   in body) fields.duedate     = body.end   || null;
  if ("notes" in body) fields.description = textToAdf(body.notes);

  const pr = await fetch(`${CONFIG.baseUrl}/rest/api/3/issue/${key}`, {
    method: "PUT",
    headers: { Authorization: authHeader(), "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ fields }),
  });
  if (!pr.ok) {
    const err = await pr.text();
    throw new Error(`Jira field update ${pr.status}: ${err.slice(0, 300)}`);
  }

  const transitionApplied = "phase" in body ? await applyTransition(key, body.phase) : null;
  cache = { at: 0, data: null }; // bust cache so next GET is fresh
  return { transitionApplied };
}

/* ---- comments -------------------------------------------------------- */
async function getComments(key) {
  const r = await fetch(`${CONFIG.baseUrl}/rest/api/3/issue/${key}/comment?orderBy=created`, {
    headers: { Authorization: authHeader(), Accept: "application/json" },
  });
  if (!r.ok) throw new Error(`Jira comments ${r.status}`);
  const data = await r.json();
  return (data.comments || []).map(c => ({
    author: (c.author && c.author.displayName) || "Unknown",
    created: c.created,
    text: adfToText(c.body).trim(),
  }));
}
async function postComment(key, text) {
  if (!text || !text.trim()) throw new Error("Comment is empty.");
  const r = await fetch(`${CONFIG.baseUrl}/rest/api/3/issue/${key}/comment`, {
    method: "POST",
    headers: { Authorization: authHeader(), "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ body: textToAdf(text) }),
  });
  if (!r.ok) { const e = await r.text(); throw new Error(`Jira comment ${r.status}: ${e.slice(0, 300)}`); }
  const c = await r.json();
  return { author: (c.author && c.author.displayName) || "You", created: c.created, text };
}

let cache = { at: 0, data: null };
async function getProjects() {
  if (cache.data && Date.now() - cache.at < CONFIG.cacheMs) return cache.data;
  const jql = CONFIG.jql || `project = ${CONFIG.project} ORDER BY created DESC`;
  const fields = ["summary", "status", "issuetype", "assignee", "reporter",
    "duedate", "labels", "parent", "issuelinks", "description", FIELDS.startDate];
  const issues = await jiraSearch(jql, fields);
  const data = { asOf: new Date().toISOString().slice(0, 10), source: jql, projects: mapIssues(issues) };
  cache = { at: Date.now(), data };
  return data;
}

/* ---- HTTP server ----------------------------------------------------- */
const server = http.createServer(async (req, res) => {
  if (req.url.startsWith("/api/projects")) {
    if (!CONFIG.email || !CONFIG.token) {
      res.writeHead(500, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ error: "Set JIRA_EMAIL and JIRA_TOKEN environment variables." }));
    }
    // /api/projects/:key/comments  — read & post Jira comments
    const cm = req.url.match(/^\/api\/projects\/([^/?]+)\/comments/);
    if (cm) {
      const key = decodeURIComponent(cm[1]);
      if (req.method === "GET") {
        try {
          const comments = await getComments(key);
          res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
          res.end(JSON.stringify({ comments }));
        } catch (e) {
          res.writeHead(502, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: String(e.message || e) }));
        }
        return;
      }
      if (req.method === "POST") {
        let raw = "";
        req.on("data", d => raw += d);
        req.on("end", async () => {
          try {
            const comment = await postComment(key, JSON.parse(raw).body);
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ comment }));
          } catch (e) {
            res.writeHead(502, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: String(e.message || e) }));
          }
        });
        return;
      }
    }
    // PATCH /api/projects/:key  — write changes back to Jira
    if (req.method === "PATCH") {
      const key = req.url.replace(/^\/api\/projects\//, "").split("?")[0];
      let raw = "";
      req.on("data", d => raw += d);
      req.on("end", async () => {
        try {
          const result = await handlePatch(key, JSON.parse(raw));
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify(result));
        } catch (e) {
          res.writeHead(502, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: String(e.message || e) }));
        }
      });
      return;
    }
    // GET /api/projects
    try {
      const data = await getProjects();
      res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      res.end(JSON.stringify(data));
    } catch (e) {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: String(e.message || e) }));
    }
    return;
  }
  // static: serve index.html
  const file = req.url === "/" || req.url.startsWith("/?") ? "index.html" : req.url.split("?")[0].replace(/^\//, "");
  const full = path.join(__dirname, file);
  if (!full.startsWith(__dirname) || !fs.existsSync(full) || fs.statSync(full).isDirectory()) {
    res.writeHead(404); return res.end("Not found");
  }
  const ext = path.extname(full).toLowerCase();
  const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };
  res.writeHead(200, { "Content-Type": types[ext] || "application/octet-stream" });
  fs.createReadStream(full).pipe(res);
});

if (require.main === module) {
  server.listen(CONFIG.port, () => {
    console.log(`MU VPMO dashboard → http://localhost:${CONFIG.port}`);
    console.log(`Jira: ${CONFIG.baseUrl}  project=${CONFIG.project}  ${CONFIG.email ? "(auth set)" : "(NO AUTH — set JIRA_EMAIL/JIRA_TOKEN)"}`);
  });
}

// Exported for testing without a live Jira connection.
module.exports = { mapIssues, phaseFor, deriveRag, adfToText, textToAdf, labelValue, applyTransition, handlePatch, getComments, postComment };
