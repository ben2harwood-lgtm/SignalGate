# SignalGate External Acceptance Handoff

Use this sequence after the machine-green release candidate. Do not skip a gate by relabelling repository evidence as external evidence. Track every receipt in `docs/ACCEPTANCE_EVIDENCE_INDEX.md` and use the blank templates in `docs/evidence/`.

## 1. Freeze the candidate

Record:

- named RC branch;
- exact candidate SHA;
- `docs/RELEASE_CANDIDATE_2026-09-19.md`;
- `docs/evidence/SECURITY_REVIEW_RECEIPT_TEMPLATE.md`;
- green GitHub Actions run;
- any accepted exception.

Do not change runtime code during an acceptance run. A runtime change creates a new candidate and invalidates receipts that depend on the old binary/source.

## 2. MetaEditor + MT5 demo acceptance

Primary instructions:

- `docs/MT5_ACCEPTANCE.md`
- `docs/evidence/MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md`
- `mt5_ea/README_MT5_SETUP.md`

Retain:

- MetaEditor/build version;
- broker/demo terminal version;
- exact candidate SHA;
- 0 errors / 0 warnings compile log or screenshot;
- scenario-by-scenario result;
- matching backend audit/ledger/reconciliation evidence;
- defect disposition for every failure.

Do not use real-money accounts.

## 3. Independent security review / penetration test

Provide the assessor:

- `docs/PENTEST_SCOPE.md`;
- `docs/SECURITY_OVERVIEW.md`;
- `docs/PRIVACY_DATA_MAP.md`;
- `docs/ARCHITECTURE.md`;
- `docs/THREAT_MODEL.md`;
- `docs/INCIDENT_RUNBOOKS.md`;
- `docs/RELEASE_CANDIDATE_2026-09-19.md`;
- candidate SHA and deployment/test-environment details.

Require a written report that identifies scope, dates, environment, methodology, findings, severity and retest status. Critical/high findings must be remediated or explicitly block expansion.

## 4. UK regulatory / financial-promotion review

Provide counsel:

- `docs/REGULATORY_COUNSEL_BRIEF.md`;
- `docs/REGULATORY_GATE.md`;
- current architecture and data-flow documentation;
- `docs/evidence/REGULATORY_PRIVACY_RECEIPT_TEMPLATE.md`;
- exact click-to-approve user journey;
- provider-facing commercial copy;
- intended customer/instrument/jurisdiction model.

Require the written advice to identify the architecture it analysed. Any later move toward automatic execution, different customer classes, instruments, distribution or white-label operating roles must be checked against that advice rather than assumed covered.

## 5. Privacy / contract review

Use:

- `docs/PRIVACY_DATA_MAP.md`;
- `docs/SECURITY_OVERVIEW.md`;
- `docs/DEPENDENCY_INVENTORY.md`;
- provider onboarding/pilot documents.

Resolve at least:

- controller/processor roles;
- lawful basis/notices;
- retention/deletion/export;
- subprocessor and international-transfer terms;
- breach/incident responsibilities;
- provider/customer responsibility allocation;
- pilot/service/support terms.

## 6. Controlled provider pilot

Use:

- `docs/BETA_ACCEPTANCE.md`;
- `docs/CONTROLLED_PROVIDER_PILOT.md`;
- `docs/PROVIDER_ONBOARDING.md`;
- `docs/FIRST_PROVIDER_RUNBOOK.md`;
- `docs/evidence/PILOT_OPERATIONS_LOG_TEMPLATE.md`;
- `scripts/provision_provider.py`;
- Provider Portal;
- provider evidence export.

Pilot rule:

- real provider;
- demo accounts only;
- small invited cohort;
- explicit subscriber feed consent;
- explicit per-transaction authorisation;
- measured onboarding/support/failure/reconciliation evidence;
- retained incident dispositions.

A pilot success is operating evidence, not investment-performance evidence.

## 7. Expansion decision

Only expand the operating mode after the evidence required for that next mode is complete.

In particular, do not infer permission for UK retail real-money or automatic copy execution from:

- green CI;
- successful demo execution;
- provider interest;
- a completed penetration test;
- disclaimers;
- demo pilot success.

Each changed operating model must satisfy the corresponding technical, security, legal, privacy and commercial gates.
