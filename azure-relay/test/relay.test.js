/* Offline harness for the relay: fakes Softdocs's bad Content-Type, the Ethos
 * auth endpoint, and the DataConnect pipeline, then asserts on what arrives. */
"use strict";
const assert = require("assert");
const { relay, jwtExpiry } = require("../src/functions/relay.js");

const calls = [];
let ethosHits = 0;

// Fake upstream: Ethos auth + DataConnect pipeline
const fakeJwt = "x." + Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 300 })).toString("base64url") + ".y";
global.fetch = async (url, init = {}) => {
  const u = String(url);
  if (u.includes("/auth")) {
    ethosHits++;
    return new Response(fakeJwt, { status: 200 });
  }
  calls.push({ url: u, init });
  return new Response(JSON.stringify({ ok: true, pipeline: "started" }), {
    status: 200, headers: { "content-type": "application/json" },
  });
};

function fakeRequest({ method = "POST", url = "https://fn.azurewebsites.net/api/relay?code=FNKEY&studentId=123", headers = {}, body = "" } = {}) {
  const h = new Map(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
  return {
    method, url,
    headers: { get: (k) => h.get(k.toLowerCase()) ?? null },
    arrayBuffer: async () => Buffer.from(body),
  };
}
const ctx = { log: () => {}, warn: () => {}, error: () => {} };

(async () => {
  process.env.TARGET_URL = "https://integrate.elluciancloud.com/api/mu-softdocs-intake";
  process.env.OVERRIDE_CONTENT_TYPE = "application/json";
  process.env.ETHOS_API_KEY = "test-api-key";
  process.env.FORWARD_HEADERS = "x-correlation-id";
  process.env.EXTRA_HEADERS = '{"Accept":"application/json"}';

  // 1. Softdocs sends text/plain — relay must rewrite to application/json
  const res = await relay(fakeRequest({
    headers: { "content-type": "text/plain; charset=utf-8", "x-correlation-id": "abc-1", "x-functions-key": "secret" },
    body: '{"documentId":42}',
  }), ctx);
  const sent = calls[0];
  assert.strictEqual(sent.init.headers["Content-Type"], "application/json", "Content-Type rewritten");
  assert.strictEqual(sent.init.body.toString(), '{"documentId":42}', "body untouched");
  assert.strictEqual(sent.init.headers.Authorization, `Bearer ${fakeJwt}`, "Ethos JWT attached");
  assert.strictEqual(sent.init.headers["x-correlation-id"], "abc-1", "forwarded header kept");
  assert.strictEqual(sent.init.headers.Accept, "application/json", "extra header added");
  assert.strictEqual(sent.init.headers["x-functions-key"], undefined, "function key not leaked");
  const target = new URL(sent.url);
  assert.strictEqual(target.searchParams.get("studentId"), "123", "query passed through");
  assert.strictEqual(target.searchParams.get("code"), null, "auth code stripped");
  assert.strictEqual(res.status, 200);
  assert.strictEqual(JSON.parse(res.body.toString()).ok, true, "upstream body returned");

  // 2. Second call — cached token, no second auth round-trip
  await relay(fakeRequest({ body: "{}" }), ctx);
  assert.strictEqual(ethosHits, 1, "JWT cached across calls");

  // 3. jwtExpiry falls back gracefully on opaque tokens
  assert.ok(jwtExpiry("not-a-jwt") > Date.now(), "opaque token gets fallback expiry");

  // 4. Missing TARGET_URL → clean 500
  delete process.env.TARGET_URL;
  const bad = await relay(fakeRequest({}), ctx);
  assert.strictEqual(bad.status, 500);

  console.log("All relay tests passed ✔");
})().catch((e) => { console.error("TEST FAILED:", e.message); process.exit(1); });
