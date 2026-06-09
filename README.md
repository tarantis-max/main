# MU Student Vehicle Permit — Authorize.net Accept Hosted

A small payment service for the Student Vehicle Registration form. The student
picks a permit type, pays the fee on Authorize.net's **Accept Hosted** form
(embedded in Ellucian Experience), and on success the **EIP / Intelligent
Processes** workflow's "Pay your fee" External Task is completed — passing the
invoice number and amount paid through so **Student Financial Services** is
notified and the workflow advances to the permit-pickup step.

**PCI scope: SAQ-A.** Card data is entered only on Authorize.net's hosted form
(inside an iframe served by A.net) and never touches MU systems or this service.

## Flow
1. The EIP workflow opens **`/pay.html?reg=<registrationId>&permit=<permitType>`** as the External Task.
2. `pay.html` calls **`POST /api/permit/pay`** → the service calls Authorize.net
   `getHostedPaymentPage` (with the server-side fee for that permit type) and
   returns a one-time **form token**.
3. The page POSTs the token into the A.net iframe; the student enters their card.
4. On completion, the **iframe communicator** relays the result to the page.
5. The page calls **`POST /api/permit/verify`** → the service runs
   `getTransactionDetails` to confirm, then calls **`completeExternalTask()`** to
   tell EIP the payment succeeded (stamping the transaction id, invoice number,
   and amount on the workflow response).

### Webhook backstop (reliability)
The iframe communicator handles the happy path, but if the student closes the
browser after paying and before step 4 fires, the workflow would otherwise be
left stranded — paid, but never advanced. So Authorize.net is **also** configured
to send a webhook:

6. **`POST /api/anet/webhook`** receives `net.authorize.payment.authcapture.created`,
   verifies the `X-ANET-Signature`, re-runs `getTransactionDetails`, and calls the
   same `completeExternalTask()`.

`completeExternalTask()` is **idempotent on the transaction id**, so whichever of
the browser path or the webhook arrives first wins and the second is a no-op.

## Files
| File | Purpose |
|------|---------|
| `accept-hosted.js` | A.net calls: `mintHostedToken`, `getTransactionDetails`, `assertPaid`, fee schedule |
| `eip-client.js` | `completeExternalTask()` — idempotent EIP signal (implement against your IP API) |
| `server.js` | Express service: `/api/permit/pay`, `/api/permit/verify`, `/api/anet/webhook`, serves `/public` |
| `public/pay.html` | The embedded payment page (lives inside the Experience External Task) |
| `public/IFrameCommunicator.html` | Required A.net relay page (same origin) |
| `.env.example` | Configuration |

## Run (sandbox)
```bash
cp .env.example .env      # fill in ANET_* from your Authorize.net SANDBOX account
npm install
npm start                 # http://localhost:3000
# open: http://localhost:3000/pay.html?reg=TEST-1001&permit=full-year
```
Authorize.net **sandbox test cards** (e.g. Visa `4111 1111 1111 1111`, any future
expiry, any CVV) are listed in the A.net testing guide.

> **Note on the communicator URL:** Authorize.net must be able to reach
> `PUBLIC_BASE_URL/IFrameCommunicator.html`, so a bare `localhost` works for the
> page itself but not for an end-to-end embedded test. Use an HTTPS tunnel
> (e.g. a dev tunnel) and set `PUBLIC_BASE_URL` to that HTTPS origin.

## Things to finish before go-live
1. **Set the real fee schedule** in `accept-hosted.js` (`FEE_SCHEDULE`).
2. **Implement `completeExternalTask()`** in `eip-client.js` against the Intelligent
   Processes task-advance API (set `EIP_TASK_COMPLETE_URL` / `EIP_API_TOKEN`).
3. **Register the webhook** in Authorize.net for `net.authorize.payment.authcapture.created`
   pointing at `PUBLIC_BASE_URL/api/anet/webhook`, and set `ANET_SIGNATURE_KEY` so
   signatures are verified (the service warns and skips verification if it is unset).
4. **Make idempotency durable.** `eip-client.js` dedupes in memory; for multiple
   instances or restarts, back it with a shared store or rely on the EIP API being
   idempotent on `transactionId`.
5. **Hosting:** deploy as a Node service or an **Azure Function**; the A.net keys
   stay server-side. The embed page + `IFrameCommunicator.html` must be the **same
   origin** as the service.
6. **GL posting (separate, Finance):** this service only signals the *workflow*.
   Posting the revenue to Colleague AR/GL is a separate Finance decision (settlement
   feed or AR charge) and does not block this build.
7. **Cash/check lane:** handled outside this service — Public Safety marks Paid in person.

## Reference
- Accept Hosted — https://developer.authorize.net/api/reference/features/accept-hosted.html
- Webhooks — https://developer.authorize.net/api/reference/features/webhooks.html
- Official sample app — https://github.com/AuthorizeNet/accept-sample-app
