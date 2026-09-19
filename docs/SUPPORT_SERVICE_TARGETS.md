# SignalGate Support & Service Targets — Draft

**Draft for controlled beta/commercial review. Not a contractual SLA until accepted in signed terms and backed by the required staffing/monitoring.**

## Support window

Default early-stage support should be a defined UK business-hours window rather than a false 24/7 promise.

Suggested standard window:

- UK business days;
- 09:00–18:00 Europe/London;
- planned maintenance communicated in advance where practical.

A separately priced extended-support option can be introduced only when staffing and alerting support it.

## Severity

### P1 — execution/security containment

Examples:

- suspected cross-tenant access;
- duplicate/unexplained execution;
- reconciliation indicates broker position inconsistent with platform state;
- credential compromise;
- platform-wide inability to pause/contain.

**Target:** acknowledge within 1 business hour during support window; immediate containment action takes priority over feature/service restoration.

### P2 — provider operation materially blocked

Examples:

- provider cannot access portal;
- feed cannot submit otherwise-valid demo signals;
- subscriber join/onboarding broken;
- widespread EA connectivity failure without evidence of unsafe execution.

**Target:** acknowledge within 4 business hours.

### P3 — degraded/non-critical

Examples:

- reporting/display issue;
- isolated integration inconvenience;
- documentation/support request.

**Target:** acknowledge by next business day.

### P4 — enhancement

Feature requests and non-urgent improvements are triaged into the roadmap; no restoration target.

## Safety-first incident rule

SignalGate may pause a provider/feed/platform or otherwise fail closed while an execution/security discrepancy is investigated. Preserving safe state and broker truth takes precedence over availability.

## Availability target

The repository's pre-production target is >=99.9% provider/API availability over a measured 30-day production period. This is a **target, not historical performance or a contractual guarantee**.

Do not contract an availability SLA until:

- central telemetry and alert routing are live;
- exclusions/maintenance definition is agreed;
- incident ownership is staffed;
- at least a meaningful beta observation period exists.

## Support evidence

Retain ticket/incident timestamps, severity, response/restoration time, root cause, remediation and customer impact. These measurements become both SLA-design evidence and acquisition due-diligence material.
