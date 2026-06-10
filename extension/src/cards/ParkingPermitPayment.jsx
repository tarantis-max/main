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
import PropTypes from 'prop-types';

import { useCardInfo, useData } from '@ellucian/experience-extension-utils';

const styles = () => ({
    card: {
        margin: `0 ${spacing40}`,
        display: 'flex',
        flexDirection: 'column',
        gap: spacing30
    }
});

// Display labels only. Prices are resolved server-side by the token pipeline's
// fee schedule; the amount shown to the student comes back with the token.
const PERMIT_TYPES = [
    { value: 'full-year', label: 'Full-Year Permit' },
    { value: 'fall', label: 'Fall Semester Permit' },
    { value: 'spring', label: 'Spring Semester Permit' },
    { value: 'summer', label: 'Summer Permit' },
    { value: 'motorcycle', label: 'Motorcycle Permit' }
];

const VERIFY_POLL_MS = 5000;
const VERIFY_POLL_MAX = 24; // ~2 minutes of polling after the pay tab opens

function ParkingPermitPayment({ classes }) {
    const { authenticatedEthosFetch } = useData();
    const { configuration: { tokenPipeline, verifyPipeline } = {} } = useCardInfo();

    const [registrationId, setRegistrationId] = useState('');
    const [permitType, setPermitType] = useState('');
    const [phase, setPhase] = useState('form'); // form | minting | paying | verifying | paid | error
    const [statusMessage, setStatusMessage] = useState('');
    const [receipt, setReceipt] = useState();
    const pollCount = useRef(0);

    // Serverless pipelines are invoked through the integration proxy by
    // resource name; 'application/json' selects the latest published version.
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

    // POST the one-time token to the Authorize.net hosted page in a new tab
    // (redirect mode: Authorize.net shows its own receipt page).
    function openHostedPaymentPage(token, formUrl) {
        const form = document.createElement('form');
        form.method = 'post';
        form.action = formUrl;
        form.target = '_blank';

        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'token';
        input.value = token;
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
                'This card will update automatically once the payment is confirmed.'
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
                setStatusMessage(result.message);
            }
        } catch (error) {
            setPhase('error');
            setStatusMessage(error.message);
        }
    }

    // While the student pays in the other tab, poll the verify pipeline so the
    // card flips to "paid" on its own. The verify pipeline is the authority;
    // nothing in this browser is trusted by the workflow.
    useEffect(() => {
        if (phase !== 'paying') {
            return undefined;
        }
        const timer = setInterval(async () => {
            pollCount.current += 1;
            if (pollCount.current > VERIFY_POLL_MAX) {
                clearInterval(timer);
                setStatusMessage(
                    'Still waiting on payment confirmation. Finish the payment in the other tab, then click Verify payment.'
                );
                return;
            }
            try {
                await verify();
            } catch (ignored) {
                // transient — keep polling
            }
        }, VERIFY_POLL_MS);
        return () => clearInterval(timer);
    }, [phase, verify]);

    if (phase === 'paid' && receipt) {
        return (
            <div className={classes.card}>
                <Typography variant="h3">Payment received</Typography>
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

    return (
        <div className={classes.card}>
            <Typography variant="h3">Pay your parking permit fee</Typography>
            <TextField
                label="Registration ID"
                value={registrationId}
                onChange={(e) => setRegistrationId(e.target.value)}
                disabled={phase === 'paying' || busy}
                required
            />
            <Dropdown
                label="Permit type"
                value={permitType}
                onChange={(e) => setPermitType(e.target.value)}
                disabled={phase === 'paying' || busy}
                required
            >
                {PERMIT_TYPES.map((p) => (
                    <DropdownItem key={p.value} label={p.label} value={p.value} />
                ))}
            </Dropdown>
            {statusMessage && <Typography>{statusMessage}</Typography>}
            {busy && <CircularProgress />}
            {phase !== 'paying' ? (
                <Button onClick={onPay} disabled={busy || !registrationId || !permitType}>
                    Pay with card
                </Button>
            ) : (
                <Button onClick={onVerifyNow}>Verify payment</Button>
            )}
        </div>
    );
}

ParkingPermitPayment.propTypes = {
    classes: PropTypes.object.isRequired
};

export default withStyles(styles)(ParkingPermitPayment);
