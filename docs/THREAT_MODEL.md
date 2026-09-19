# SignalGate Threat Model

## Protected assets

1. Customer account execution authority.
2. Provider/customer/command ownership mappings.
3. EA, provider, admin and bot credentials.
4. Signal and command integrity.
5. Execution and reconciliation history.
6. Audit evidence.
7. Availability of pause/kill/recovery controls.

## Trust boundaries

- Provider source → ingestion API/bot.
- Telegram bot → backend.
- Browser/provider UI → backend.
- Backend → database.
- EA/simulator → backend.
- Backend/EA → broker/MT5.
- Platform admin → tenant data.
- Logging/monitoring → operators.

## Highest-risk abuse cases

| Threat | Required control |
|---|---|
| Forged provider signal | authenticated provider identity; replay key; source allowlist |
| Provider A acts on Provider B | server-side tenant ownership on every object/query |
| Global EA key used against another account | per-customer licence + command ownership validation |
| Duplicate network retry opens/records twice | idempotency keys and DB uniqueness |
| Two workers claim same command | row lock / atomic queue claim |
| Late event reopens/regresses closed trade | monotonic state machine |
| Stolen credential | scoped credentials, rotation, revocation, audit |
| Secret leaked in URL/log | headers only; secret-redaction tests |
| Malformed/ambiguous signal | deterministic fail-closed parser |
| Replay of source message | feed-scoped source namespace + source-message unique replay key |
| Oversized image/body | request size and media-type limits |
| Database unavailable mid-command | fail closed + durable queue/reconciliation |
| Backend timeout after broker success | broker-side idempotency/reconciliation; never blindly resend |
| Compromised admin | MFA/SSO/RBAC, least privilege, privileged audit |
| Provider misconfiguration | bounded policy, validation, preview/change audit |
| Broken deployment | staged rollout, readiness checks, rollback |
| Data loss | encrypted backups + tested restore |

## Open high-priority threats

- Provider/organisation/feed/subscriber/account ownership is now implemented on the September hardening spine; keep cross-tenant tests mandatory for every provider-scoped change.
- Broker acknowledgement/reconciliation across timeout-after-success needs a durable production design.
- EA local processed-command memory is volatile across restart; backend/broker reconciliation must remain authoritative.
- No production SSO/MFA/RBAC dashboard exists yet.
- No independent penetration test has been completed.

These are release blockers, not footnotes.
