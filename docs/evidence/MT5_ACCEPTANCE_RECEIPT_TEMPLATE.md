# MT5 Acceptance Receipt — TEMPLATE

**Receipt id:**  
**Date/time:**  
**Operator:**  
**Frozen candidate ref:**  
**Frozen candidate SHA:**  
**EA source SHA-256:**  
**Compile-harness/tooling SHA:**  
**MetaEditor build/version:**  
**MetaTrader terminal version:**  
**Broker/demo environment:**  
**Demo account identifier (redacted):**

## Compile receipt

- [ ] Candidate ref resolved to the recorded exact SHA
- [ ] Detached candidate worktree/source used
- [ ] EA SHA-256 recorded
- [ ] 0 compile errors
- [ ] 0 compile warnings
- [ ] Raw MetaEditor compiler log retained
- [ ] Automated receipt JSON/Markdown retained (when harness is used)

**Controlled evidence reference:**  

## Scenario matrix

| # | Scenario | Expected | Result | Backend/broker evidence reference | Notes / defect |
|---|---|---|---|---|---|
| 1 | Normal MARKET fill | One demo position; truthful execution report | | | |
| 2 | Broker symbol suffix | Correct broker symbol resolved | | | |
| 3 | LIMIT command | Refused; no broker order | | | |
| 4 | Broker rejection / market closed | Failure recorded; no fake success | | | |
| 5 | Stop-loss close | STOPPED_OUT/loss attribution | | | |
| 6 | Manual/unknown close | No fabricated TP attribution | | | |
| 7 | Netting account | Safe fallback behaviour | | | |
| 8 | Network loss after fill | Lost callback recovered from broker truth | | | |
| 9 | EA restart with open SG position | New polling blocked until reconciled/flat | | | |
| 10 | Conflicting broker snapshot | Conflict; history not rewritten | | | |

## Safety checks

- [ ] EA refuses real account
- [ ] Wrong customer licence rejected
- [ ] Duplicate execution callback does not duplicate state
- [ ] Reconciliation conflict is visible/audited

## Defects

List every failure with issue/reference, severity, owner, disposition and retest requirement.

## Decision

- [ ] PASS for this exact candidate/environment
- [ ] FAIL — new candidate/retest required
- [ ] PARTIAL — not accepted

**Signed/approved by:**  
**Date:**  
