# SignalGate Observability, SLO Targets and Alerts

These are **pre-production operating targets**, not historical uptime claims.

## Request telemetry

Every HTTP response carries `X-Request-Id`. The backend writes one structured JSON request log containing only:

- request id;
- HTTP method;
- URL path **without query string**;
- response status;
- latency in milliseconds.

Headers, query values, request/response bodies, licences and API keys are deliberately excluded.

## Protected metrics

`GET /admin/metrics` uses normal platform-admin authentication. It reports aggregate operational counts only:

- tenant/feed pause state;
- active subscriptions/accounts;
- parser rejects;
- pending, sent, failed and stale commands;
- failed executions/management;
- reconciliation, execution-report and replay conflicts;
- recovered lost execution callbacks.

It does not expose customer identities, signal text or credentials.

## Initial SLO targets for controlled beta

Measure these only after a deployed beta exists.

| Indicator | Target |
|---|---:|
| Provider/API availability | >= 99.9% over 30 days |
| Successful API requests latency | p95 < 500 ms excluding external broker latency |
| Unexplained duplicate executions caused by SignalGate | 0 |
| Cross-tenant data/execution incidents | 0 |
| Lost execution callback left undetected while broker position remains open | 0 |
| Restore drill success | 100% of scheduled drills |
| Critical/high known security findings past agreed remediation deadline | 0 |

## Alert rules

Treat these as defaults for the eventual monitoring backend.

### Page / immediate

- `/readyz` failing for 2 consecutive minutes.
- Any cross-tenant security test or production isolation control failure.
- Any `BROKER_RECONCILIATION_CONFLICT`.
- Any execution report claiming failure while broker reconciliation reports the position open.
- Any command duplicated at the broker for the same SignalGate command id.

### Urgent

- `commands_sent_to_ea_stale_60s > 0` for 2 checks.
- `execution_report_conflicts` increases.
- `management_failures` increases.
- Backup job failure or checksum failure.
- Restore drill failure.

### Investigate

- Parser rejection rate changes materially from the provider's baseline.
- Dependency audit newly fails.
- Provider or feed pause lasts longer than expected.
- Request error/latency rate materially changes.

## Dashboards

At minimum show:

1. readiness and request latency/error rate;
2. signal -> command -> execution counts;
3. stuck commands and reconciliation conflicts;
4. provider/feed pause state;
5. backup/restore evidence;
6. security/dependency scan status.

## Operator snapshot (read-only, not alerting)

`scripts/pilot_ops_snapshot.py` records a single, redacted observation from
`/readyz`, `/health` and authenticated `/admin/metrics`. Set
`SIGNALGATE_BACKEND`, `SIGNALGATE_ADMIN_ID`,
`SIGNALGATE_ADMIN_API_KEY` and `SIGNALGATE_CANDIDATE_SHA` **via private
environment configuration**, then run the script from the repository root.
No secret is accepted as a command-line flag. The local
`artifacts/pilot-ops/` receipt contains only read-only status, numeric
aggregate counters, and operator-declared candidate SHA; it excludes raw
credentials, user IDs, signal text and source exports.

Before attempting authenticated `/admin/metrics`, the snapshot first checks
unauthenticated `/readyz` and `/health`: both must be valid HTTP 200 JSON
objects reporting ready/healthy, and health must explicitly report
`demo_only_mode: true`. Otherwise **no admin credential is transmitted**,
`authenticated_metrics_attempted` is false, `admin_metrics` is null and the
receipt is `FAIL`. These public responses are **not proof of server identity
or the operator-declared candidate SHA**: independently verify the HTTPS
origin/deployed release; do not treat the preflight as authentication or
external acceptance.

A `REVIEW_REQUIRED` observation indicates nonzero *historical cumulative*
stale/conflict/failed-management counters to investigate, **not proof of a new
incident** or a live trading loss. A `FAIL` observation fails readiness,
demo-only, authorisation or metric-schema checks. The script cannot establish
time-series SLOs, persistent alert routing, broker truth, receipt provenance or
production monitoring. Use an independently configured central monitor and
the release acceptance index before marking G6 complete.

## Remaining production work

The current repository provides structured log events, correlation IDs and a protected metrics surface. A deployed environment still needs a central log/metrics backend, alert routing, retention rules, on-call ownership and measured SLO history before G6 is fully accepted.


## Release evidence to retain

For each candidate deployment retain:

- candidate git SHA;
- a redacted sample structured request log showing correlation id/path/status/latency;
- an authenticated `/admin/metrics` snapshot;
- readiness result;
- alert-route test receipt once alerting is connected;
- any non-zero reconciliation/execution/replay conflict counters with disposition.

A zero conflict count is evidence for that observation window only; it is not a guarantee that future conflicts cannot occur.
