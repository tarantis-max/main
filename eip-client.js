'use strict';

/**
 * Signals the Ellucian EIP / Intelligent Processes workflow that the
 * "Pay your fee" external task is complete, passing the invoice number and
 * amount paid through so Student Financial Services is notified via the
 * workflow response (and the workflow advances to the permit-pickup step).
 *
 * TODO: wire completeExternalTask() to your Intelligent Processes external-task
 * completion API. The exact URL and payload contract come from your Workflow's
 * external-task definition; set EIP_TASK_COMPLETE_URL and EIP_API_TOKEN.
 */

// In-memory idempotency guard so the browser-verify path and the webhook
// backstop cannot advance the same payment twice. For multi-instance or
// restart-durable deployments, replace this with a shared store (Redis, a DB
// row, etc.) or rely on the workflow API being idempotent on transactionId.
const completed = new Set();

async function completeExternalTask({ registrationId, transId, invoiceNumber, amount, status }) {
  if (completed.has(transId)) {
    return { ok: true, deduped: true };
  }

  const url = process.env.EIP_TASK_COMPLETE_URL;
  const token = process.env.EIP_API_TOKEN;

  if (!url) {
    // Scaffold-safe: don't hard-fail in local/sandbox before the API is wired.
    console.warn(
      `[eip-client] EIP_TASK_COMPLETE_URL not set; would complete task ` +
      `reg=${registrationId} transId=${transId} invoice=${invoiceNumber} amount=${amount}`
    );
    completed.add(transId);
    return { ok: true, simulated: true };
  }

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify({
      registrationId,
      transactionId: transId,
      invoiceNumber,
      amountPaid: amount,
      transactionStatus: status,
      paidAt: new Date().toISOString()
    })
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`EIP task complete failed (${res.status}): ${detail}`);
  }

  completed.add(transId);
  return { ok: true };
}

module.exports = { completeExternalTask };
