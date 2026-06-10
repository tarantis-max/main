import React from 'react';

import { Button, Typography } from '@ellucian/react-design-system/core';
import { spacing30, spacing40 } from '@ellucian/react-design-system/core/styles/tokens';
import { withStyles } from '@ellucian/react-design-system/core/styles';
import { useNavigate } from '@ellucian/experience-extension-utils';

const styles = () => ({
    card: {
        margin: `0 ${spacing40}`,
        display: 'flex',
        flexDirection: 'column',
        gap: spacing30
    }
});

// Teaser card shown in the Experience dashboard / task list.
// The full payment UI lives on the linked page (ParkingPermitPaymentPage).
// Deep links from the EIP form confirmation and workflow email go directly
// to that page (?reg=<registrationId>&permit=<permitType>), bypassing this card.
function ParkingPermitPayment({ classes }) {
    const { navigateToPage } = useNavigate();

    function onOpenPaymentPage() {
        navigateToPage({ route: '/parking-permit-payment' });
    }

    return (
        <div className={classes.card}>
            <Typography variant="h3">Parking permit payment due</Typography>
            <Typography>
                Your vehicle registration has been received. Complete your parking permit payment to finish the process.
            </Typography>
            <Button onClick={onOpenPaymentPage}>Pay now</Button>
        </div>
    );
}

export default withStyles(styles)(ParkingPermitPayment);
