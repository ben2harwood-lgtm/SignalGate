# SignalGate Regulatory Counsel Architecture Brief — UK

**For external UK financial-services counsel. This is factual engineering context, not a legal conclusion.**

## Current product mode

- SignalGate supplies execution infrastructure, not proprietary investment signals.
- A signal provider supplies its own signals/strategy and subscriber relationship.
- Current repository mode is demo-only; real-money retail mode is blocked.
- Signals are deterministically parsed/validated; ambiguous signals fail closed.
- Subscriber approval is currently explicit per signal before a command is created.
- A tenant-bound command is delivered to the subscriber/customer EA.
- The EA executes against MetaTrader 5 demo infrastructure and returns broker evidence.
- Provider/platform/customer actions are audit logged.

## Parties

Counsel should analyse separately:

1. SignalGate/FRM operating entity.
2. Signal provider.
3. Subscriber/end customer.
4. Broker/MetaTrader provider.
5. Any future white-label broker/prop-firm customer.

## Decision/execution path to analyse

Provider signal -> SignalGate validation -> subscriber YES/NO -> tenant-bound command -> customer EA -> broker -> execution/reconciliation evidence.

SignalGate currently does not choose the provider's signal, rank signals, optimise the customer's portfolio or remove the per-transaction subscriber decision.

## Architecture variants requiring separate advice

- current explicit click-to-approve model;
- any future automatic execution/copy mode;
- provider-facing B2B infrastructure only;
- broker/prop-firm embedded/white-label distribution;
- signal-provider SaaS with SignalGate onboarding end subscribers;
- UK vs non-UK providers/subscribers/instruments.

## Written questions for counsel

1. Under the exact current click-to-approve architecture, which regulated activities may be performed by SignalGate, the provider or the broker?
2. Does SignalGate receive/transmit an order or arrange a transaction in this flow?
3. What changes if the subscriber pre-authorises a rule and no longer clicks each transaction?
4. What permissions/authorisation/AR structures would be required for each variant?
5. What contractual responsibility should remain with the provider/broker?
6. Which communications from SignalGate are financial promotions, and who may approve them?
7. What restrictions apply to provider-facing B2B marketing vs end-user marketing?
8. What disclaimers are insufficient to change the regulatory substance?
9. Which instruments/customer classes/jurisdictions materially change the answer?
10. What records/retention/complaints/incident obligations should the product support?
11. Does provider white-labelling change responsibility or disclosure?
12. What product/UX wording should be avoided before authorisation analysis is complete?

## Evidence available

- architecture/release gates;
- threat model/security overview;
- provider onboarding and beta acceptance;
- API/data model;
- demo approval/execution audit trail;
- provider portal;
- incident/operations documentation.

## Product gate

No UK retail real-money or auto-copy launch, and no performance-led public promotion, passes G8 until counsel's written advice is received and the deployed implementation matches the analysed architecture.
