module.exports = {
    name: 'MU Parking Permit Payment',
    publisher: 'Methodist University',
    cards: [
        {
            type: 'ParkingPermitPaymentCard',
            source: './src/cards/ParkingPermitPayment.jsx',
            title: 'Parking Permit Payment',
            displayCardType: 'Parking Permit Payment',
            description: 'Pay the student vehicle permit fee via Authorize.net',
            // Opens the full payment page when the student clicks "Pay now"
            // or follows a deep link (?reg=<registrationId>&permit=<permitType>).
            pageRoute: {
                route: '/parking-permit-payment',
                pageName: 'ParkingPermitPaymentPage'
            },
            configuration: {
                client: [
                    {
                        key: 'tokenPipeline',
                        label: 'Token pipeline API name (e.g. mu-parkingpermit-getpaymenttoken)',
                        type: 'text',
                        required: true
                    },
                    {
                        key: 'verifyPipeline',
                        label: 'Verify pipeline API name (e.g. mu-parkingpermit-verifypayment)',
                        type: 'text',
                        required: true
                    }
                ]
            }
        }
    ],
    pages: [
        {
            type: 'ParkingPermitPaymentPage',
            source: './src/page/ParkingPermitPaymentPage.jsx',
            title: 'Parking Permit Payment'
        }
    ]
};
