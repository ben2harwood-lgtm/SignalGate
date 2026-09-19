# UK Regulatory Perimeter Gate

**Engineering/commercial checklist only; obtain UK financial-services legal advice before launch.**

SignalGate must not infer that calling itself "software" places it outside regulation. The analysis depends on what the provider, SignalGate and broker actually do.

## Current FCA anchors (checked 18 September 2026)

1. FCA copy-trading guidance, last updated 27 July 2026:
   https://www.fca.org.uk/firms/copy-trading

   The FCA says automatic execution of third-party trade signals without further client intervention can constitute portfolio/investment management. Where client action is required before each transaction, that specific activity is not portfolio management, but other services may still be relevant, including investment advice and reception/transmission of orders.

2. FCA permissions guidance:
   https://www.fca.org.uk/firms/authorisation/wholesale-markets/permissions-asset-management

   Depending on the model, relevant regulated activities may include arranging, dealing as agent, advising and managing investments.

3. FCA financial-promotions guidance:
   https://www.fca.org.uk/firms/financial-promotions-and-adverts/approving-financial-promotions

   Websites, emails, adverts and social posts can be financial promotions when they invite or induce investment activity.

## Counsel must answer in writing

- Which legal entity operates SignalGate?
- Who is SignalGate's contractual customer: provider, end user, broker or a combination?
- Who decides whether each individual transaction occurs?
- Does SignalGate receive/transmit an order?
- Does SignalGate execute on behalf of the client?
- Does any party exercise discretion?
- Is any communication advice/personal recommendation/general recommendation?
- Which instruments/jurisdictions are in scope?
- Is the intended provider authorised, exempt, an appointed representative, or neither?
- Does SignalGate need authorisation/permissions or can it operate as a technical service provider under the exact architecture?
- What financial-promotion approvals/restrictions apply to B2B and retail marketing?
- What contractual responsibility must remain with each provider/broker?

## Release rule

No UK retail real-money mode, auto-copy mode or performance-led public promotion passes G8 until the written perimeter/marketing analysis is complete and the implementation matches the analysed model.
