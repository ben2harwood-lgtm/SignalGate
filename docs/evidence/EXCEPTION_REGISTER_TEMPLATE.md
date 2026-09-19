# SignalGate Exception Register — TEMPLATE

Exceptions are explicit, time-bounded decisions. They do not convert a failed release gate into a pass.

| Exception id | Gate/control | Description | Risk | Owner | Approved by | Created | Expiry | Remediation | Status |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |

## Rules

- No exception may silently enable real-money retail trading.
- Critical/high security exceptions require explicit written approval and normally block provider expansion.
- An exception must identify the exact candidate/environment it applies to.
- Expired exceptions revert to open blockers.
- Retest evidence must reference the remediation SHA and original finding/exception id.
