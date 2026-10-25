# Provider Edition — 10-minute INTERNAL Simulator-Only Sales Rehearsal

> **Internal, synthetic demonstration only; not a broker-demo acceptance, provider
> pilot, production environment or release approval.** G3 execution acceptance,
> G8 external assurance and G9 pilot entry are NOT PASSED. Use only local,
> fictional provider/subscriber fixtures and an isolated broker-free simulator.
> **Do not connect MT5, any broker (including a real DEMO broker), real Telegram
> provider/customer identities, or external services while following this script.**
> Do not use customer data, real provider credentials or a paid service.

The goal is to show **control and labelled simulated evidence**, not investment
returns, fills confirmed by a broker, or permission to onboard customers. Keep
`docs/DEMO_SCRIPT.md` and `docs/MT5_ACCEPTANCE.md` separate: this sales
rehearsal cannot substitute for either external approval or formal MT5 receipts.

## Preconditions

1. Check current [canonical status](../SIGNALGATE-STATUS.md),
   [release gates](RELEASE_GATES.md) and outstanding draft
   [PR #60 safety HOLD](https://github.com/ben2harwood-lgtm/SignalGate/pull/60).
2. Use an **isolated local simulator** and entirely fabricated tenancy, subscriber,
   signals and credentials. No public backend, live Telegram bot, broker terminal,
   deployed API, networked provider or third-party account.
3. Keep the feed initially paused. Show how the controlled local fixture makes
   a human YES necessary before the simulated execution path can advance.
4. Clearly label every visual and exported artefact **SIMULATED / NOT BROKER
   VERIFIED**. Keep generated fixture receipts out of public customer evidence.

## Minute 0–1 — frame

"SignalGate is designed to sit between a provider's signal source and each
authorised subscriber account. This offline rehearsal illustrates proposed
controls; actual MT5 broker behaviour and external assurance are not accepted."

## 1–3 — signal ingestion

Submit a fabricated, clear signal to the local test path; display the parsed
fields and expiry. Submit a deliberately ambiguous fixture and show a rejection.
If a fake screenshot extractor is used locally, label its output **synthetic**:
it is not proof that real image extraction has succeeded.

## 3–5 — human authorisation

Show a synthetic subscriber trade card and an explicit **YES** on the local
fixture. Replay the same approval to demonstrate backend one-command semantics
only; **do not describe this as proof of a single real broker fill**. Show NO
and expiry refusal where possible.

## 5–7 — simulated execution (NOT MT5)

Use the broker-free simulator only. Display a structured, tenant-bound command,
a labelled **simulated** execution callback and a wrong-tenant/licence refusal.
Do not present the simulation's filled volume, price or ticket identifiers as
broker truth. PR #60 multi-deal fill accounting and deal/position identity are
still unresolved for real MT5 acceptance.

## 7–8 — safety and failure

Replay a synthetic callback and show that the backend rejects/handles duplicates.
Show platform and feed pauses in the isolated fixture. Explain that ambiguous
broker sends must never be blindly retried; this rehearsal does not prove
real-world reconciliation, restart recovery or split rollback.

## 8–9 — evidence (synthetic)

Display the locally generated signal → approval → command → execution and audit
timeline. Mark the entire timeline **SIMULATED / NOT BROKER VERIFIED**.

## 9–10 — provider operations (fictional tenant)

Show the local Provider Edition screen/fixture: feed pause, subscriber consent,
history, reconciliation/exception status and scoped export. Use only a
fabricated subscriber for any invitation/join walkthrough: never send a real
`/join` or `/connectprovider` token to Telegram as part of this rehearsal.

## Never claim or perform

- No actual MT5 compiler acceptance, broker order, broker-demo result, fill,
  profitability or product return is proved by this script.
- No real-money trading, unattended copying, real broker, real provider/customer
  onboarding, public activation or genuine customer identity/data.
- No regulatory clearance, penetration-test completion, production readiness
  or externally accepted provider pilot.
- No secrets in screenshots, URLs, fixture receipts or public logs.

A **separate, specifically authorised future acceptance** requires an approved
exact-source successor to failed frozen RC2 (official RC2 MetaEditor
[run 35464044898](https://github.com/ben2harwood-lgtm/SignalGate/actions/runs/35464044898)
returned **18 errors / 4 warnings**), successful source-bound MetaEditor build
and new EX5, independent review, resolution of PR #60 execution HOLDs,
controlled genuine MT5 **DEMO** broker/backend receipts and the applicable
security, privacy and legal gates. **This script does not grant that
authorisation**. Follow [external acceptance handoff](EXTERNAL_ACCEPTANCE_HANDOFF.md)
and [acceptance evidence index](ACCEPTANCE_EVIDENCE_INDEX.md).
