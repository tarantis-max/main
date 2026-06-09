'use strict';

require('dotenv').config();

const path = require('path');
const crypto = require('crypto');
const express = require('express');

const anet = require('./accept-hosted');
const { completeExternalTask } = require('./eip-client');

const app = express();
const PORT = process.env.PORT || 3000;
const PUBLIC_BASE_URL = process.env.PUBLIC_BASE_URL || `http://localhost:${PORT}`;

// Capture the RAW body on the webhook route (needed for signature verification),
// while using normal JSON parsing everywhere else. Mount raw before json.
app.use('/api/anet/webhook', express.raw({ type: '*/*' }));
app.use(express.json());

// Serve the embedded payment page + the iframe communicator (same origin).
app.use(express.static(path.join(__dirname, 'public')));

/**
 * Mint a hosted form token for the student's permit payment.
 * The amount is resolved server-side from the permit type.
 */
app.post('/api/permit/pay', async (req, res) => {
  try {
    const { reg, permit } = req.body || {};
    const result = await anet.mintHostedToken({
      registrationId: reg,
      permitType: permit,
      communicatorUrl: `${PUBLIC_BASE_URL}/IFrameCommunicator.html`
    });
    res.json(result);
  } catch (err) {
    console.error('[pay]', err.message);
    res.status(err.statusCode || 500).json({ error: err.message });
  }
});

/**
 * Browser-driven confirmation: the page relays the transId through the iframe
 * communicator; we re-verify server-side before signaling EIP.
 */
app.post('/api/permit/verify', async (req, res) => {
  try {
    const { reg, transId } = req.body || {};
    if (!transId) return res.status(400).json({ error: 'transId required' });

    const txn = await anet.getTransactionDetails(transId);
    const paid = anet.assertPaid(txn, transId);

    await completeExternalTask({
      registrationId: reg || paid.invoiceNumber,
      transId: paid.transId,
      invoiceNumber: paid.invoiceNumber,
      amount: paid.amount,
      status: paid.status
    });

    res.json({ ok: true, ...paid });
  } catch (err) {
    console.error('[verify]', err.message);
    res.status(err.statusCode || 500).json({ error: err.message });
  }
});

/**
 * Webhook backstop. Fires even if the student closes the browser before the
 * communicator relays the result, so a paid registration is never stranded.
 * Verify signature -> re-fetch the transaction -> complete the task
 * (idempotent with the browser-verify path above).
 */
app.post('/api/anet/webhook', async (req, res) => {
  try {
    const raw = Buffer.isBuffer(req.body) ? req.body.toString('utf8') : '';

    if (!verifySignature(raw, req.get('X-ANET-Signature'))) {
      return res.status(401).send('bad signature');
    }

    const event = JSON.parse(raw.replace(/^\uFEFF/, '').trim());
    if (event.eventType !== 'net.authorize.payment.authcapture.created') {
      // Ack non-target events so Authorize.net stops retrying.
      return res.status(200).send('ignored');
    }

    const transId = event.payload && event.payload.id;
    const txn = await anet.getTransactionDetails(transId);
    const paid = anet.assertPaid(txn, transId);

    await completeExternalTask({
      registrationId: paid.invoiceNumber,
      transId: paid.transId,
      invoiceNumber: paid.invoiceNumber,
      amount: paid.amount,
      status: paid.status
    });

    res.status(200).send('ok');
  } catch (err) {
    console.error('[webhook]', err.message);
    // Ack so Authorize.net does not retry an error we cannot fix by retrying.
    // Change to 500 if you want A.net to retry on transient failures.
    res.status(200).send('error-logged');
  }
});

/**
 * Verify the Authorize.net webhook signature.
 * Header format: "X-ANET-Signature: sha512=HEXDIGEST".
 * The Signature Key is a hex string; its decoded BYTES are the HMAC key.
 */
function verifySignature(rawBody, header) {
  const key = process.env.ANET_SIGNATURE_KEY;
  if (!key) {
    console.warn('[webhook] ANET_SIGNATURE_KEY not set; skipping signature check (set it before go-live)');
    return true;
  }
  if (!header) return false;

  const provided = (header.split('=')[1] || '').toLowerCase();
  const computed = crypto
    .createHmac('sha512', Buffer.from(key, 'hex'))
    .update(rawBody, 'utf8')
    .digest('hex')
    .toLowerCase();

  const a = Buffer.from(provided);
  const b = Buffer.from(computed);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

app.get('/health', (_req, res) => res.json({ ok: true, env: anet.ENV }));

app.listen(PORT, () => {
  console.log(`MU permit payment service listening on ${PORT} (${anet.ENV})`);
  console.log(`Open: ${PUBLIC_BASE_URL}/pay.html?reg=TEST-1001&permit=full-year`);
});
