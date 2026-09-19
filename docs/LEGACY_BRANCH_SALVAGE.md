# Legacy Claude Branch Salvage Ledger

Source branch: `claude/signalgate-full-audit-bjh0tk` (55 commits ahead of the July `main` baseline).

This branch is **not** the September integration spine. Do not merge it wholesale. Selectively port capability only after comparing it with the current hardening code and rerunning current tests.

## Superseded — do not port wholesale

| Legacy commit/capability | Decision | Reason |
|---|---|---|
| `00badf1` public-hosting auth hardening | Superseded | September hosted auth, provider-specific hashed credentials, migration gates and tenancy isolation are stronger/different. |
| `3cde8a0` command lifecycle / ownership | Mostly superseded | September execution-safety branch adds DB uniqueness, retry conflict handling, per-command ownership and monotonic terminal handling with versioned migrations. Review any missing timeout/reset behaviour separately. |
| Old Nick-specific onboarding/marketing | Retire | Nick is no longer a product dependency or demand proof. |
| July launch/waitlist claims | Retire/rewrite | Commercial copy must match current demo-hardening state and Provider Edition positioning. |

## Valuable capability candidates — selectively salvage

| Legacy commit | Capability | Port rule |
|---|---|---|
| `c9758ce` | Forex pair parsing, optional symbol allowlist, broker symbol suffix resolution | Port parser/config/tests first; keep deterministic fail-closed parser semantics. MT5 resolver requires compile receipt. |
| `58b2a6c` | Screenshot preprocessing / zoomed price-scale crop | Port preprocessing + offline tests only if current extractor safety/human-confirmation boundary stays intact. External model call remains optional and separately configured. |
| `de6d099` | Read-only ledger endpoint + quick demo dry run | Low-risk candidate; keep admin/tenant access controls and truthful win/loss display. |
| `d2b5cf7` | MT5 retcode validation, authoritative stop-out handling, netting guard, LIMIT refusal | High-value safety candidate; merge carefully with September EA changes, then require MetaEditor 0-error/0-warning compile + demo scenarios. |
| `0242ff2` | Risk-based position sizing with round-down/min-lot safeguards | Valuable but execution-sensitive; port only after EA safety merge and compile/demo evidence. |

## Pending comparison items

- Stuck-command timeout/reset from `3cde8a0`.
- Ledger handling of unattributed FULLY_CLOSED events.
- Simulator stop-out scenario.
- Forex end-to-end parser → command → EA symbol mapping.
- Provider-facing screenshot flow now that tenancy credentials are DB-backed.

## Acceptance rule for salvage

A legacy feature is accepted only when:

1. it is rebased onto the current September hardening spine;
2. newer security/tenancy semantics are preserved;
3. automated tests cover the feature and negative cases;
4. schema changes, if any, use the Alembic chain;
5. MT5 changes have an actual MetaEditor compile receipt and demo-path evidence;
6. the canonical status ledger is updated.

