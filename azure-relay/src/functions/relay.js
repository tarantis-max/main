/**
 * MU — Softdocs → Ellucian DataConnect relay
 * -------------------------------------------
 * Softdocs Etrieve Flow's HTTP step can't always control the Content-Type it
 * sends, and DataConnect HTTP-triggered pipelines reject anything that isn't
 * the type they expect. This function sits between the two:
 *
 *   Softdocs Etrieve ──POST──▶  this function  ──POST──▶ DataConnect pipeline
 *                               · rewrites Content-Type (OVERRIDE_CONTENT_TYPE)
 *                               · exchanges the Ethos API key for a JWT and
 *                                 attaches it as Authorization: Bearer <jwt>
 *                               · forwards method, query string, and raw body
 *                               · returns the pipeline's response unchanged
 *
 * Configuration — Function App ▸ Settings ▸ Environment variables:
 *   TARGET_URL             (required) DataConnect endpoint, e.g.
 *                          https://integrate.elluciancloud.com/api/<pipeline-api-name>
 *   OVERRIDE_CONTENT_TYPE  Content-Type to send upstream (default application/json)
 *   ETHOS_API_KEY          DataConnect application API key. When set, the relay
 *                          exchanges it for a JWT at ETHOS_AUTH_URL and caches it.
 *   ETHOS_AUTH_URL         default https://integrate.elluciancloud.com/auth
 *   EXTRA_HEADERS          optional JSON object of static headers to add, e.g.
 *                          {"Accept":"application/json"}
 *   FORWARD_HEADERS        optional comma-separated inbound header names to pass
 *                          through unchanged (e.g. "x-correlation-id")
 *
 * Security: authLevel is "function" — Softdocs must call with the function key
 * (?code=... or x-functions-key header). The Ethos API key never leaves Azure.
 */
"use strict";
const { app } = require("@azure/functions");

/* ---- Ethos token exchange (cached until shortly before expiry) ---------- */
let tokenCache = { jwt: null, exp: 0 };

function jwtExpiry(jwt) {
  // exp claim, with a fallback of 4 minutes when the token can't be decoded
  try {
    const payload = JSON.parse(Buffer.from(jwt.split(".")[1], "base64url").toString("utf8"));
    if (payload && typeof payload.exp === "number") return payload.exp * 1000;
  } catch { /* opaque token */ }
  return Date.now() + 4 * 60 * 1000;
}

async function ethosToken(context) {
  if (tokenCache.jwt && Date.now() < tokenCache.exp - 30000) return tokenCache.jwt;
  const authUrl = process.env.ETHOS_AUTH_URL || "https://integrate.elluciancloud.com/auth";
  const res = await fetch(authUrl, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.ETHOS_API_KEY}` },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Ethos auth failed (${res.status}): ${body.slice(0, 200)}`);
  }
  const jwt = (await res.text()).trim();
  tokenCache = { jwt, exp: jwtExpiry(jwt) };
  context.log(`Ethos token refreshed; valid until ${new Date(tokenCache.exp).toISOString()}`);
  return jwt;
}

/* ---- the relay ----------------------------------------------------------- */
async function relay(request, context) {
  const targetBase = process.env.TARGET_URL;
  if (!targetBase) {
    return { status: 500, jsonBody: { error: "TARGET_URL app setting is not configured." } };
  }

  // Build the upstream URL: TARGET_URL + inbound query string (minus the
  // Azure Functions auth code, which is ours, not the pipeline's).
  const target = new URL(targetBase);
  for (const [k, v] of new URL(request.url).searchParams) {
    if (k.toLowerCase() !== "code") target.searchParams.append(k, v);
  }

  // Outbound headers: start clean so nothing hop-by-hop or host-specific
  // leaks upstream, then set exactly what we mean to send.
  const headers = {};
  const contentType = process.env.OVERRIDE_CONTENT_TYPE || "application/json";

  for (const name of (process.env.FORWARD_HEADERS || "").split(",").map(s => s.trim()).filter(Boolean)) {
    const val = request.headers.get(name);
    if (val != null) headers[name] = val;
  }
  if (process.env.EXTRA_HEADERS) {
    try { Object.assign(headers, JSON.parse(process.env.EXTRA_HEADERS)); }
    catch { context.warn("EXTRA_HEADERS is not valid JSON — ignored."); }
  }
  if (process.env.ETHOS_API_KEY) {
    headers.Authorization = `Bearer ${await ethosToken(context)}`;
  }

  // Raw body, untouched — only the declared Content-Type changes.
  const method = request.method.toUpperCase();
  const hasBody = !["GET", "HEAD"].includes(method);
  let body;
  if (hasBody) {
    body = Buffer.from(await request.arrayBuffer());
    headers["Content-Type"] = contentType;
  }

  const inboundType = request.headers.get("content-type") || "(none)";
  context.log(`Relaying ${method} ${body ? body.length + "B" : "no body"} ` +
    `[Content-Type: ${inboundType} → ${hasBody ? contentType : "n/a"}] → ${target.origin}${target.pathname}`);

  let upstream;
  try {
    upstream = await fetch(target, { method, headers, body });
  } catch (e) {
    context.error(`Upstream unreachable: ${e.message}`);
    return { status: 502, jsonBody: { error: `Could not reach DataConnect: ${e.message}` } };
  }

  const respBody = Buffer.from(await upstream.arrayBuffer());
  context.log(`Upstream responded ${upstream.status} (${respBody.length}B)`);
  return {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") || "application/json" },
    body: respBody,
  };
}

app.http("relay", {
  methods: ["GET", "POST", "PUT", "PATCH", "DELETE"],
  authLevel: "function",
  handler: relay,
});

module.exports = { relay, jwtExpiry }; // exported for tests
