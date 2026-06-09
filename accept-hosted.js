'use strict';

/**
 * Authorize.net Accept Hosted helpers.
 *
 * Every call that uses the Transaction Key happens here, server-side only.
 * The browser never sees the API credentials and never handles card data
 * (that stays inside Authorize.net's hosted iframe) — keeping PCI scope at SAQ-A.
 */

const ENV = (process.env.ANET_ENV || 'sandbox').toLowerCase();

// API endpoint for getHostedPaymentPage / getTransactionDetails.
const API_URL = ENV === 'production'
  ? 'https://api.authorize.net/xml/v1/request.api'
  : 'https://apitest.authorize.net/xml/v1/request.api';

// Where the browser POSTs the form token to render the hosted form.
const FORM_URL = ENV === 'production'
  ? 'https://accept.authorize.net/payment/payment'
  : 'https://test.authorize.net/payment/payment';

/**
 * Server-side fee schedule. The amount is NEVER taken from the browser — it is
 * looked up here by permit type so a student cannot tamper with the price.
 *
 * TODO: replace with the real permit types and prices before go-live.
 */
const FEE_SCHEDULE = {
  'full-year':  { amount: '125.00', label: 'Full-Year Permit' },
  'fall':       { amount: '75.00',  label: 'Fall Semester Permit' },
  'spring':     { amount: '75.00',  label: 'Spring Semester Permit' },
  'summer':     { amount: '40.00',  label: 'Summer Permit' },
  'motorcycle': { amount: '50.00',  label: 'Motorcycle Permit' }
};

function merchantAuth() {
  return {
    name: process.env.ANET_API_LOGIN_ID,
    transactionKey: process.env.ANET_TRANSACTION_KEY
  };
}

// Authorize.net prepends a UTF-8 BOM on JSON responses; strip before parsing.
function parseAnet(text) {
  return JSON.parse(text.replace(/^\uFEFF/, '').trim());
}

async function postJson(body) {
  const res = await fetch(API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const text = await res.text();
  return parseAnet(text);
}

/**
 * Mint a one-time Accept Hosted form token for a permit payment.
 *
 * Embedded-iframe mode: showReceipt=false + an IFrameCommunicator URL, which is
 * what makes Authorize.net relay the result back through the communicator page
 * instead of rendering its own receipt.
 */
async function mintHostedToken({ registrationId, permitType, communicatorUrl }) {
  const fee = FEE_SCHEDULE[permitType];
  if (!fee) {
    const err = new Error(`Unknown permit type: ${permitType}`);
    err.statusCode = 400;
    throw err;
  }
  // invoiceNumber max length is 20 characters in Authorize.net.
  if (!registrationId || String(registrationId).length > 20) {
    const err = new Error('registrationId is required and must be <= 20 characters');
    err.statusCode = 400;
    throw err;
  }

  const settings = [
    {
      settingName: 'hostedPaymentReturnOptions',
      // Embedded in an iframe: suppress the receipt so the result is delivered
      // through the IFrameCommunicator instead of a receipt page.
      settingValue: JSON.stringify({ showReceipt: false })
    },
    {
      settingName: 'hostedPaymentButtonOptions',
      settingValue: JSON.stringify({ text: 'Pay' })
    },
    {
      settingName: 'hostedPaymentIFrameCommunicatorUrl',
      settingValue: JSON.stringify({ url: communicatorUrl })
    },
    {
      settingName: 'hostedPaymentOrderOptions',
      settingValue: JSON.stringify({
        show: true,
        merchantName: process.env.MERCHANT_NAME || 'Methodist University'
      })
    },
    {
      settingName: 'hostedPaymentBillingAddressOptions',
      settingValue: JSON.stringify({ show: true, required: false })
    }
  ];

  const body = {
    getHostedPaymentPageRequest: {
      merchantAuthentication: merchantAuth(),
      transactionRequest: {
        transactionType: 'authCaptureTransaction',
        amount: fee.amount,
        order: {
          invoiceNumber: String(registrationId),
          description: fee.label
        }
      },
      hostedPaymentSettings: { setting: settings }
    }
  };

  const data = await postJson(body);
  const resultCode = (data.messages && data.messages.resultCode) || '';
  if (resultCode.toLowerCase() !== 'ok' || !data.token) {
    const m = (data.messages && data.messages.message && data.messages.message[0]) || {};
    throw new Error(`getHostedPaymentPage failed: [${m.code}] ${m.text}`);
  }

  return { token: data.token, formUrl: FORM_URL, amount: fee.amount, description: fee.label };
}

/**
 * Authoritative, server-side confirmation of a transaction.
 * Never trust the browser-relayed transactResponse — re-fetch it here.
 */
async function getTransactionDetails(transId) {
  const body = {
    getTransactionDetailsRequest: {
      merchantAuthentication: merchantAuth(),
      transId: String(transId)
    }
  };
  const data = await postJson(body);
  const resultCode = (data.messages && data.messages.resultCode) || '';
  if (resultCode.toLowerCase() !== 'ok') {
    const m = (data.messages && data.messages.message && data.messages.message[0]) || {};
    throw new Error(`getTransactionDetails failed: [${m.code}] ${m.text}`);
  }
  return data.transaction;
}

/**
 * Assert a transaction is approved and captured. Returns a normalized summary
 * or throws (statusCode 402) if the payment is not confirmed.
 */
function assertPaid(txn, transId) {
  if (!txn) throw new Error(`No transaction returned for ${transId}`);

  const approved = String(txn.responseCode) === '1';
  const captured = txn.transactionStatus === 'capturedPendingSettlement'
    || txn.transactionStatus === 'settledSuccessfully';

  if (!approved || !captured) {
    const err = new Error(
      `Transaction ${txn.transId} not confirmed ` +
      `(responseCode=${txn.responseCode}, status=${txn.transactionStatus})`
    );
    err.statusCode = 402;
    throw err;
  }

  const order = txn.order || {};
  return {
    transId: String(txn.transId),
    invoiceNumber: order.invoiceNumber || '',
    description: order.description || '',
    amount: txn.settleAmount != null ? txn.settleAmount : txn.authAmount,
    status: txn.transactionStatus
  };
}

module.exports = {
  FEE_SCHEDULE,
  mintHostedToken,
  getTransactionDetails,
  assertPaid,
  FORM_URL,
  ENV
};
