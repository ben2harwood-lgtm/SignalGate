# SignalGate Release Gates

A gate is binary. "Mostly" does not pass.

## G0 — Baseline truth
- Canonical branch and status ledger exist.
- No untracked production assumptions.
- Demo/live boundary documented.

## G1 — Build integrity
- CI runs on every PR and integration push.
- Backend test suite passes.
- Python compile check passes.
- Dependency audit has zero known unresolved vulnerabilities or an explicitly accepted, time-bounded exception.
- Dependency update automation enabled.

## G2 — Identity and access
- Hosted mode fails closed without HTTPS, PostgreSQL and strong secrets.
- Admin/provider/bot/EA credentials are distinct.
- Provider identity cannot inherit admin authority.
- Secrets use constant-time comparison where applicable.
- No licence/API secret in URLs or audit payloads.
- Negative authentication tests pass.

## G3 — Execution safety
- EA callback is bound to the customer that owns the command.
- One command cannot be claimed by two PostgreSQL workers.
- Execution reports are retry-idempotent.
- Management reports are retry-idempotent.
- Terminal state cannot regress due to a late event.
- Global/provider/account kill paths are specified and tested.
- No unexplained execution in fault-injection tests.

## G4 — Adversarial ingestion
- Conflicting symbol/direction/SL/TP/entry values fail closed.
- Non-positive/impossible prices fail closed.
- Payload/image size limits enforced.
- Non-image uploads rejected at extractor boundary.
- Source-message replay does not create a second signal.
- Parser fuzz/adversarial corpus passes.

## G5 — Provider multi-tenancy
- Organisation/provider/feed/subscriber/account ownership exists in the data model.
- Every provider-scoped query is tenant filtered server-side.
- Cross-tenant read/write/execute tests exist.
- Provider users have roles; no ID/header is itself a credential.
- Tenant provisioning/deprovisioning and key rotation documented.
- Database migrations are versioned and reversible.

## G6 — Production operations
- Staging and production are separate.
- Reproducible deployment/infrastructure configuration.
- Structured logs, metrics, tracing and alerts.
- Health/readiness checks.
- Encrypted backups and a successful restore drill.
- Incident runbooks exercised.
- Defined SLOs and error budget.
- Dependency/secrets rotation procedure.

## G7 — Provider Edition
- Provider onboarding is self-contained.
- Provider can create/configure feeds and see subscribers/accounts.
- Provider can pause its own feed without platform admin access.
- Complete signal → command → execution → reconciliation history is visible.
- White-label configuration is isolated per tenant.
- Demo tenant demonstrates the full journey without real money.
- Documentation and support path complete.

## G8 — External assurance
- Independent application/security review complete.
- Penetration test complete; critical/high issues closed.
- UK regulatory-perimeter advice covers SignalGate, provider, broker and order-routing roles.
- Marketing/legal review completed for provider-facing and any retail-facing copy.
- Privacy/DPA/retention/security terms reviewed.

## G9 — Controlled provider beta
- Named providers onboard through sandbox first.
- Demo-account pilot only until assurance permits otherwise.
- Support load, onboarding time, failures and incidents measured.
- Exit criteria defined before expansion.

## G10 — Commercially saleable
- Paying provider contracts.
- MRR/ARR, churn, gross margin, support cost and concentration tracked.
- Clean IP/dependency/licence inventory.
- Security/regulatory evidence current.
- Data room complete.
- Product can be operated without founder-only knowledge.
