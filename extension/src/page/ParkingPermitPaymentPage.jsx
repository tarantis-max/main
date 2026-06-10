import React, { useCallback, useEffect, useRef, useState } from 'react';

import {
    Button,
    CircularProgress,
    Dropdown,
    DropdownItem,
    TextField,
    Typography
} from '@ellucian/react-design-system/core';
import { spacing30, spacing40 } from '@ellucian/react-design-system/core/styles/tokens';
import { withStyles } from '@ellucian/react-design-system/core/styles';

import { useCardInfo, useData } from '@ellucian/experience-extension-utils';

const styles = () => ({
    page: {
        maxWidth: 600,
        margin: `0 auto`,
        padding: `${spacing40}`,
        display: 'flex',
        flexDirection: 'column',
        gap: spacing30
    }
});

// Display labels only — prices are resolved server-side by the token pipeline.
const PERMIT_TYPES = [
    { value: 'full-year',   label: 'Full-Year Permit' },
    { value: 'fall',        label: 'Fall Semester Permit' },
    { value: 'spring',      label: 'Spring Semester Permit' },
    { value: 'summer',      label: 'Summer Permit' },
    { value: 'motorcycle',  label: 'Motorcycle Permit' }
];

const VERIFY_POLL_MS  = 5000;
const VERIFY_POLL_MAX = 24; // ~2 minutes

// Read a query-param from the page's URL (?reg=...&permit=...).
// Works whether Experience renders the page in an iframe or at a routed path.
function getQueryParam(name) {
    try {
        return new URLSearchParams(window.location.search).get(name) || '';
    } catch {
        return '';
    }
}

function ParkingPermitPaymentPage({ classes }) {
    const { authenticatedEthosFetch } = useData();
    const { configuration: { tokenPipeline, verifyPipeline } = {} } = useCardInfo();

    // Pre-fill from URL params when the student arrives via a deep link
    // (form confirmation, workflow email, or Experience task notification).
    const [registrationId, setRegistrationId] = useState(() => getQueryParam('reg'));
    const [permitType,     setPermitType]     = useState(() => getQueryParam('permit'));

    const [phase,         setPhase]         = useState('form'); // form|minting|paying|verifying|paid|error
    const [statusMessage, setStatusMessage] = useState('');
    const [receipt,       setReceipt]       = useState(null);
    const pollCount = useRef(0);

    const callPipeline = useCallback(async (pipeline, body) => {
        const response = await authenticatedEthosFetch(pipeline, {
            method: 'POST',
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(body)
        });
        if (!response.ok) {
            throw new Error(`${pipeline} returned HTTP ${response.status}`);
        }
        return response.json();
    }, [authenticatedEthosFetch]);

    // POST the one-time token to A.net's hosted page in a new tab.
    function openHostedPaymentPage(token, formUrl) {
        const form  = document.createElement('form');
        form.method = 'post';
        form.action = formUrl;
        form.target = '_blank';

        const input  = document.createElement('input');
        input.type   = 'hidden';
        input.name   = 'token';
        input.value  = token;
        form.appendChild(input);

        document.body.appendChild(form);
        form.submit();
        document.body.removeChild(form);
    }

    const verify = useCallback(async () => {
        const result = await callPipeline(verifyPipeline, { registrationId });
        if (result.paid) {
            setReceipt(result);
            setPhase('paid');
        }
        return result;
    }, [callPipeline, verifyPipeline, registrationId]);

    async function onPay() {
        try {
            setPhase('minting');
            setStatusMessage('Preparing secure payment…');
            const minted = await callPipeline(tokenPipeline, { registrationId, permitType });
            openHostedPaymentPage(minted.token, minted.formUrl);
            pollCount.current = 0;
            setPhase('paying');
            setStatusMessage(
                `Complete your $${minted.amount} ${minted.description} payment in the new tab. ` +
                'This page will update automatically once the payment is confirmed.'
            );
        } catch (error) {
            setPhase('error');
            setStatusMessage(error.message);
        }
    }

    async function onVerifyNow() {
        try {
            setPhase('verifying');
            setStatusMessage('Checking with Authorize.net…');
            const result = await verify();
            if (!result.paid) {
                setPhase('paying');
                setStatusMessage(result.message || 'Payment not yet confirmed — try again in a moment.');
            }
        } catch (error) {
            setPhase('error');
            setStatusMessage(error.message);
        }
    }

    // Poll the verify pipeline while the student is in the payment tab.
    useEffect(() => {
        if (phase !== 'paying') return undefined;
        const timer = setInterval(async () => {
            pollCount.current += 1;
            if (pollCount.current > VERIFY_POLL_MAX) {
                clearInterval(timer);
                setStatusMessage(
                    'Still waiting on payment confirmation. Finish the payment in the other tab, then click Verify payment.'
                );
                return;
            }
            try { await verify(); } catch { /* transient — keep polling */ }
        }, VERIFY_POLL_MS);
        return () => clearInterval(timer);
    }, [phase, verify]);

    if (phase === 'paid' && receipt) {
        return (
            <div className={classes.page}>
                <Typography variant="h2">Payment received</Typography>
                <Typography>
                    {`Your ${PERMIT_TYPES.find((p) => p.value === permitType)?.label || 'permit'} payment of `}
                    {`$${receipt.amount} is confirmed (transaction ${receipt.transId}).`}
                </Typography>
                <Typography>
                    Student Financial Services has been notified. Public Safety will contact you about permit pickup.
                </Typography>
            </div>
        );
    }

    const busy = phase === 'minting' || phase === 'verifying';
    const locked = phase === 'paying' || busy;

    return (
        <div className={classes.page}>
            <Typography variant="h2">Pay your parking permit fee</Typography>

            <TextField
                label="Registration ID"
                value={registrationId}
                onChange={(e) => setRegistrationId(e.target.value)}
                disabled={locked}
                required
            />

            <Dropdown
                label="Permit type"
                value={permitType}
                onChange={(e) => setPermitType(e.target.value)}
                disabled={locked}
                required
            >
                {PERMIT_TYPES.map((p) => (
                    <DropdownItem key={p.value} label={p.label} value={p.value} />
                ))}
            </Dropdown>

            {statusMessage && <Typography>{statusMessage}</Typography>}
            {busy && <CircularProgress />}

            {phase !== 'paying' ? (
                <Button
                    onClick={onPay}
                    disabled={busy || !registrationId || !permitType}
                >
                    Pay with card
                </Button>
            ) : (
                <Button onClick={onVerifyNow}>Verify payment</Button>
            )}
        </div>
    );
}

export default withStyles(styles)(ParkingPermitPaymentPage);
