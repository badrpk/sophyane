# Deal Broker Agents

Node.js prototype with three roles:

- **BuyerAgent**: protects buyer budget and requirements.
- **SellerAgent**: protects seller floor price and terms.
- **BrokerAgent**: checks overlap, suggests a deal, drafts next message.

The system is for decision support only. A human must approve any real offer, acceptance, or contract.

## Run

```bash
cd deal-broker-agents
npm run demo
```

Or use your own enquiry:

```bash
node src/index.js path/to/enquiry.json
```

## Enquiry format

```json
{
  "dealId": "example-001",
  "currency": "USD",
  "product": "Used laptops",
  "quantity": 50,
  "buyer": {
    "requirements": "i5 or better, delivery this week",
    "targetUnitPrice": 180,
    "maxUnitPrice": 210,
    "preferredPayment": "20% deposit, balance after inspection",
    "mustHave": ["delivery this week", "7 day return window"]
  },
  "seller": {
    "offerDetails": "Dell Latitude i5 laptops, delivery in 5 days",
    "askingUnitPrice": 220,
    "minUnitPrice": 195,
    "preferredPayment": "30% deposit, balance before dispatch",
    "canOffer": ["delivery in 5 days", "chargers included"]
  }
}
```

## Gmail real-world intent scanner

This scans your Gmail inbox, extracts buyer/seller intent, hides party emails, and ranks the top 5 brokerable deals.

```bash
cd deal-broker-agents
npm run gmail
```

It will prompt for the Gmail app password. You can also use environment variables:

```bash
GMAIL_USER=badrpk@gmail.com GMAIL_APP_PASSWORD='your-app-password' npm run gmail
```

Default rules:

- Buyer/seller email addresses are hidden in output.
- Seller is clearly told: **1% brokerage fee charged to seller on closed deals**.
- Quantity matching supports partial fulfillment.
- Logistics cost is estimated at 3% of seller unit price when a price exists.
- Escrow is offered for safety of both buyer and seller.
- No emails are sent automatically; it only creates draft messages and deal rankings.

## Next upgrades

- Send approved emails via Gmail SMTP.
- Add CSV/WhatsApp imports.
- Add database storage.
- Add AI model calls for better natural-language negotiation.
- Add approval workflow before sending any message.
