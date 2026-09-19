# Ben Next Stage Checklist

The repository build is no longer the bottleneck. The frozen demo-only release candidate is:

- branch target: `release/signalgate-demo-rc2-2026-09-19`
- RC2 runtime/tooling candidate: `852a6bc9ca9f0651b34e87b63e86c65669130767`
- final runtime/tooling CI: run **#134** / GitHub run `35459129106` — **PENDING_FINAL**
- RC1 remains preserved only as historical evidence.

Do not change the frozen RC while collecting acceptance evidence.

## 1. Run MetaEditor acceptance first

Use:

- `docs/MT5_ACCEPTANCE.md`
- `docs/evidence/MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md`

Compile the exact RC EA in the target MetaEditor and record 0 errors / 0 warnings before running broker-demo scenarios.

If the EA needs a source change, stop the acceptance run. Fix on a new branch, run full CI, cut a new RC and repeat the compiler receipt against that new candidate.

## 2. Run the full demo execution scenario pack

Use a demo account only.

Retain evidence for:

1. normal MARKET fill;
2. broker symbol suffix;
3. LIMIT refusal with no broker order;
4. broker rejection / market closed;
5. stop-loss attribution;
6. manual/unknown close attribution;
7. netting-account fallback;
8. lost callback recovery;
9. EA restart/open-position polling block;
10. reconciliation conflict failing closed.

Use `docs/evidence/MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md` as the single receipt.

## 3. Send the independent assurance pack

Security assessor:

- `docs/PENTEST_SCOPE.md`
- `docs/SECURITY_OVERVIEW.md`
- `docs/THREAT_MODEL.md`
- `docs/PRIVACY_DATA_MAP.md`
- `docs/ARCHITECTURE.md`
- `docs/INCIDENT_RUNBOOKS.md`
- `docs/RELEASE_CANDIDATE_2026-09-19.md`

UK financial-services counsel:

- `docs/REGULATORY_COUNSEL_BRIEF.md`
- `docs/REGULATORY_GATE.md`
- current architecture/data-flow documents;
- intended provider/customer/instrument/jurisdiction model;
- actual provider-facing marketing copy.

Do not represent either review as complete until the written report/advice exists.

## 4. Prepare the first provider

Use:

- `docs/FIRST_PROVIDER_RUNBOOK.md`
- `docs/BETA_ACCEPTANCE.md`
- `docs/CONTROLLED_PROVIDER_PILOT.md`
- `docs/PROVIDER_ONBOARDING.md`
- `scripts/provision_provider.py`

The first real provider remains demo-account only. The provider uses its own tenant, feed, credential, Telegram source binding and subscriber invites.

The old shared `/provider` invite-code / Nick-specific screenshot-provider setup is historical and must not be used for the hosted Provider Edition.

## 5. Capture every receipt

Use `docs/ACCEPTANCE_EVIDENCE_INDEX.md` as the control sheet and the templates in `docs/evidence/`.

Do not commit:

- raw API keys/licences;
- private provider/customer data;
- unredacted pentest exploit material;
- privileged legal advice;
- broker credentials.

Store those in the controlled data room and reference them from the index by identifier/date.

## 6. Pilot only after the entry gates are evidenced

The controlled pilot starts only when the beta-entry checklist is satisfied for the intended pilot mode.

During pilot, record:

- onboarding time;
- support time;
- readiness observations;
- signals/commands/rejections;
- reconciliation incidents/recoveries;
- duplicate/cross-tenant incidents;
- provider active days;
- subscriber participation;
- infrastructure/support cost;
- every incident and disposition.

The aim is to prove operability and reliability, not investment performance.
