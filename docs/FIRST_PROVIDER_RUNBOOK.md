# SignalGate First Provider Runbook

This is the operator sequence for the first real provider pilot. It is intentionally conservative and remains **demo-account only**.

## Entry condition

Do not begin the real-provider cohort until the applicable items in `docs/BETA_ACCEPTANCE.md` have retained evidence.

At minimum, confirm:

- named candidate and green CI;
- MT5 compile/demo acceptance for the environment being used;
- no unresolved internal critical/high issue;
- provider entity/contact and escalation route recorded;
- signed pilot/provider agreement and agreed data/privacy responsibilities;
- provider/feed can be paused immediately.

## 1. Provision tenant

Use `scripts/provision_provider.py` or the equivalent authenticated admin workflow.

The provisioning CLI creates the initial feed **paused** and no longer prints the raw provider credential to ordinary stdout. Choose the credential-delivery path **before** provisioning.

Recommended secret-file flow (write the file outside the repository and deliver it through the approved private channel):

```bash
python scripts/provision_provider.py \
  --organization-name "Provider Organisation" \
  --provider-name "Provider Name" \
  --credential-output /secure/private/provider-onboarding-secret.json
```

The secret file is created without overwrite and with owner-only mode where the operating system supports POSIX permissions. Delete it from the operator machine after confirmed secure delivery/rotation according to the agreed secret-handling process.

For an attended emergency/demo terminal only, `--show-secret` explicitly opts into displaying the one-time secret. Do not use that mode in captured CI/session logs.

Treat an unexpectedly unpaused new feed as a setup failure and pause it before continuing.

Record:

- organisation/provider ids;
- provider display name;
- feed ids;
- provisioning timestamp;
- operator;
- candidate/environment.

Never record the raw provider credential in the evidence index.

## 2. Deliver and rotate provider credential

1. Deliver the one-time initial credential through an approved private channel. Do not copy it into the evidence index, ticket, issue or shared chat.
2. Remove the operator's temporary credential file after confirmed delivery, subject to the approved onboarding/secret process.
3. Provider confirms portal access.
4. Provider immediately rotates the credential.
5. Confirm the original credential no longer authenticates.
6. Record only credential id/last-four metadata if available; never the secret.

## 3. Configure feed while paused

Configure:

- source/feed name;
- permitted symbols;
- expiry;
- default lot size;
- branding/support contact if used.

Keep provider/feed paused until the source and subscriber paths are verified.

## 4. Bind provider Telegram source

1. Generate a one-time source token for the intended feed.
2. Provider sends `/connectprovider <token>` from the intended Telegram identity.
3. Confirm binding is visible against the correct provider/feed.
4. Confirm token reuse fails.
5. If the wrong identity is bound, revoke it before proceeding.

## 5. Onboard first subscriber

1. Generate a one-time feed invite.
2. Send it privately to the intended demo subscriber.
3. Subscriber sends its own `/join sgi_...` command.
4. Confirm the subscription/trading account is created only after that acceptance.
5. Confirm the subscriber appears only inside the intended provider/feed.
6. Deliver the one-time EA licence through an approved channel.

Do not use the deprecated direct subscriber-attachment path.

## 6. Connect demo execution

Use the accepted demo MT5 setup or the simulator.

Before unpausing:

- confirm real-account refusal;
- confirm candidate/environment identifiers;
- confirm readiness endpoint;
- confirm account/licence ownership;
- confirm provider/feed pause works.

## 7. Mandatory pre-cohort scenarios

Run and retain receipts for:

- valid signal + YES;
- valid signal + NO;
- parser rejection;
- duplicate/replayed source message;
- expired signal;
- provider pause;
- feed pause;
- wrong provider credential;
- wrong customer licence;
- execution callback retry;
- lost-callback reconciliation;
- reconciliation conflict;
- stopped-out loss;
- manual/unattributed close.

Do not open the cohort if any safety-critical result is unexplained.

## 8. Start pilot

Record pilot start:

- provider;
- feed(s);
- number of invited subscribers;
- candidate/environment;
- support owner;
- incident contact;
- start timestamp;
- planned review/end date.

Start with the smallest useful invited cohort.

## 9. Daily operator routine

At least once per operating day:

- check readiness;
- check provider/feed pause state;
- review failed/stale commands;
- review execution/report/reconciliation conflicts;
- review security/tenant incidents;
- review support requests;
- export provider evidence;
- log support minutes and incidents;
- record any configuration change.

Use `docs/evidence/PILOT_OPERATIONS_LOG_TEMPLATE.md`.

## 10. Incident rule

Immediately pause the affected provider/feed for:

- unexplained duplicate broker execution;
- cross-tenant data/execution indication;
- unexplained reconciliation conflict;
- credential exposure;
- execution state inconsistent with broker truth.

Follow `docs/INCIDENT_RUNBOOKS.md`. Preserve evidence before remediation where safe.

## 11. Pilot close / expansion decision

Before expansion, reconcile:

- every incident;
- support burden;
- onboarding time;
- unexplained execution count;
- reconciliation exceptions;
- provider feedback;
- subscriber participation;
- infrastructure/support cost;
- external-assurance gates required for the next mode.

A successful demo pilot does not itself authorise real-money or automatic-copy operation.
