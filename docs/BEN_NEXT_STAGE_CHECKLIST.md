# Ben Next Stage Checklist

**24 October 2026 — DEMO-ONLY, BROKER ACCEPTANCE ON HOLD.** The frozen RC2 machine build passed, but its **exact EA did not compile** in official MetaEditor. A machine-green release candidate is not an accepted MT5 execution candidate.

- Frozen RC2 branch: `release/signalgate-demo-rc2-2026-09-19`; exact frozen SHA: `3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2`.
- Runtime/tooling candidate `852a6bc9ca9f0651b34e87b63e86c65669130767` passed CI #134 / run `35459129106`. This is machine evidence only.
- **Failed frozen-source MetaEditor receipt:** 18 errors / 4 warnings, [run 35464044898](https://github.com/ben2harwood-lgtm/SignalGate/actions/runs/35464044898). **Do not use frozen RC2 for broker-demo scenarios.**
- Repaired, different post-RC source from PR #55 compiled cleanly; that receipt does **not** retroactively pass frozen RC2 or clear later execution defects.
- **PR #60 remains DRAFT/HOLD**: broker-fill aggregation, ambiguous sends, partial rollback, and broker-exit attribution require independent review and real controlled MT5 DEMO evidence. No successor is automatically approved for broker-demo use.
- RC1 is historical and must remain preserved.

Do not alter frozen RC2 to hide the failure. Select and pin a separately reviewed successor only after the coordinator resolves applicable execution holds and obtains fresh exact-source build evidence. No real-money trading, automatic copying, real provider/customer activity, or external activation.

## 1. Resolve the compiler and execution HOLD before broker-demo acceptance

Use `docs/MT5_ACCEPTANCE.md` and `docs/evidence/MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md` as **planning/templates**, not proof of a pass. Draft PR #96 corrects the misleading RC2 command in the runbook; do not treat that unmerged change as integrated.

The frozen RC2 MetaEditor run **already failed**; do not repeat the failed-source command as a release pass or proceed to demo-broker execution with that EA. For a successor, the coordinator must first:

1. Resolve the relevant PR #60 execution-safety findings and obtain independent exact-head code/security review; keep the execution-critical PR unmerged until genuine demo-broker evidence permits integration.
2. Pin the separate candidate ref, full 40-character SHA, EA source SHA-256 and binary provenance; run its own full integration/security CI.
3. Obtain an official MetaEditor log showing **0 errors and 0 warnings** for that exact candidate and verify a newly generated, nonempty EX5 (a clean log alone is insufficient; draft PR #102 owns the stricter artifact verifier).
4. Record explicit approval for a controlled **DEMO-account-only** broker test and retain scenario-by-scenario broker/backend receipts. Synthetic tests and source assertions are not MT5 acceptance.

A source or runtime change invalidates dependent evidence and requires a new pinned candidate with appropriate retests. All external acceptance gates remain OPEN.

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

Treat the ten baseline cases as **NOT_RUN / not accepted** until executed on a positively identified MT5 DEMO account against an approved exact-source candidate. Use `docs/evidence/MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md` for baseline evidence, plus the stage-specific exit scenarios in draft PR #89 when adopted: manual/unknown partial close, TP1/TP2/TP3 child/deal identity, failed stop modification and historical-TP misattribution. PR #89 and PR #60 are not broker evidence; all these scenarios remain **NOT_RUN**. Do not describe the baseline template as the only required receipt while those safety holds exist.

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

Use `docs/ACCEPTANCE_EVIDENCE_INDEX.md` as the control sheet and the templates in `docs/evidence/`. Its current mainline RC2 compiler row needs the source-truth correction in draft PR #86; do not infer a compiler PASS from the old `Open` row or the machine-green CI entry. An unmerged draft is not a completed register update.

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
