# SignalGate Safety Rules — Current Demo-Only Scope

> **Read this as a safety-boundary map, not an acceptance certificate.** The prior
> July-prototype checklist on this path claimed that every v1 control was already
> enforced and included obsolete restrictions (such as no AI extraction, no provider
> portal and no public preview site). That checklist is **historical and superseded**.
> The current source of truth is [AGENTS.md](../AGENTS.md),
> [SIGNALGATE-STATUS.md](../SIGNALGATE-STATUS.md) and
> [Release Gates](RELEASE_GATES.md). See the repository history for the old v1 table.

## Non-negotiable demo-only boundaries

| Boundary | Required behaviour | Important evidence limit |
|---|---|---|
| Account mode | The EA refuses live/real-money accounts; **DEMO ONLY** remains mandatory. | An automated source assertion is not an actual MT5 broker-demo receipt. |
| Human authority | Every executable signal requires a subscriber's explicit, per-transaction YES; no unattended auto-copy. | A simulator callback is not proof of a broker fill or one-fill-only behaviour. |
| Signal integrity | Reject ambiguous and unsafe signals. Raw Telegram messages, screenshot text and extractor output must not directly authorise execution. | Screenshot extraction can exist upstream of the deterministic parser; synthetic/fake extraction is not genuine OCR evidence. |
| Identity | Bind commands, licences, provider credentials, feeds, subscribers and trading accounts to authenticated owners and tenants. | Header IDs alone are not credentials; preserve cross-tenant negative tests. |
| Retry and broker outcome | Duplicate callbacks cannot create new execution authority. An uncertain broker send/acknowledgement must **never** trigger blind resubmission. | Exact opening-deal versus position-ticket identity, multi-deal aggregation and rollback remain open in draft PR #60. |
| Pause and recovery | Account/provider/platform pauses must prevent new exposure without destroying reconciliation evidence. | Pauses do not establish broker-state truth; incidents require authoritative broker reconciliation. |
| Evidence and privacy | Keep provider/customer secrets and real account details out of public receipts, logs and the repository. | Machine tests and synthetic fixtures cannot satisfy security, privacy or regulatory assurance. |

The backend, EA, bot, deterministic parser, tenancy and hosted deployment are
distinct trust boundaries. A passing test at one boundary must not be used to
claim the others have been externally verified.

## Compiler and external acceptance are separate

- Frozen RC2 is `release/signalgate-demo-rc2-2026-09-19` at
  `3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2`. Its **exact-source**
  official MetaEditor compile [run 35464044898](https://github.com/ben2harwood-lgtm/SignalGate/actions/runs/35464044898)
  failed with **18 errors and 4 warnings**, despite earlier machine-green CI.
  **Do not use frozen RC2 for broker-demo acceptance.**
- A later source's clean MetaEditor compile (including the draft PR #60 branch)
  does not retroactively validate RC2. A successor needs its **own** approved
  exact source identity, clean compiler log, fresh EX5 and genuine controlled
  MT5 **DEMO** broker/backend scenario receipts.
- Draft [PR #60](https://github.com/ben2harwood-lgtm/SignalGate/pull/60)
  remains on **HOLD** for original-order multi-fill accounting, opening
  deal-versus-position identity, ambiguous acknowledgements/sends, split
  rollback and stage-specific exit attribution. Broker-demo evidence has **not**
  been collected for those held scenarios.
- **G3 external execution acceptance, G8 independent assurance and G9 pilot
  entry are NOT PASSED.** No real broker activation, real-money trading,
  automatic copying or external provider pilot is authorised by this document.
  A green CI matrix or simulated rehearsal cannot change those gates.

For actual checklists and controlled receipts use
[MT5 acceptance](MT5_ACCEPTANCE.md),
[acceptance evidence index](ACCEPTANCE_EVIDENCE_INDEX.md),
[external handoff](EXTERNAL_ACCEPTANCE_HANDOFF.md) and
[incident runbooks](INCIDENT_RUNBOOKS.md).
