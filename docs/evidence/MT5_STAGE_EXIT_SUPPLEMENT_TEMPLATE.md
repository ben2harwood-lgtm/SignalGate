# MT5 Stage-Exit Attribution — Supplemental DEMO Receipt (BLANK)

This is a **supplement**, not a replacement, for `MT5_ACCEPTANCE_RECEIPT_TEMPLATE.md`.
It addresses the unresolved broker-exit attribution and stop-modification hold on
[PR #60](https://github.com/ben2harwood-lgtm/SignalGate/pull/60).
Do not use frozen RC2's failed exact-source MetaEditor compile as an accepted
binary. Use a separately reviewed, freshly compiled candidate; never modify RC2.

**Acceptance state: NOT_RUN.** This blank template does not evidence a compiler
pass, a broker connection, a pilot, or release approval. Broker-free simulations,
MQL static checks, a green GitHub CI run, and a prior candidate's receipts **cannot**
mark any scenario below PASS. All scenarios require an authorised **MT5 DEMO**
account, no real-money trading, no automatic copying and per-transaction human
approval. Keep unredacted IDs/logs in the controlled evidence room, not GitHub.

## Candidate and environment binding (required for each filled receipt)

- Receipt ID / UTC timestamp / operator and independent reviewer: **NOT_RUN**
- Candidate branch/ref and **full 40-character commit SHA**: **NOT_RUN**
- Exact `.mq5` SHA-256 and matching compiled `.ex5` controlled reference: **NOT_RUN**
- MetaEditor compiler version, compile log, **0 errors and 0 warnings**: **NOT_RUN**
- MT5 terminal build; broker/server; positively verified `ACCOUNT_TRADE_MODE_DEMO`: **NOT_RUN**
- Controlled base acceptance receipt ID and backend audit/ledger reference: **NOT_RUN**
- EA magic, tenant/account binding and consent test reference (redacted): **NOT_RUN**
- Evidence storage ID and tamper-checksum manifest: **NOT_RUN**

For every scenario retain the original command ID (redacted externally), intended
stage/child mapping, order/deal ticket and `DEAL_POSITION_ID`, exact symbol/magic,
`DEAL_ENTRY`, `DEAL_REASON`, exit time and volume, open positions **before and
after**, EA journal, server `ResultRetcode()` / description where applicable,
backend event/ledger state, and a matching receipt reference. Broker-mutated
comments/identifiers must be recorded as ambiguities, not guessed identities.
Do not classify a decrease in open-position count, a price touch, or an unrelated
TP exit as proof that a specific TP-stage child closed by TP.

## Mandatory stage-specific MT5 DEMO scenario matrix

| ID | Scenario | Required outcome / failure guard | Status | Controlled broker + backend evidence ref |
|---|---|---|---|---|
| S1 | TP1 child closes with its OWN `DEAL_REASON_TP` | `TP1_CLOSE_SUCCESS` at most once only after exact child/exit-deal match; remaining-SL move must have broker success + readback | NOT_RUN | |
| S2 | Manual/unknown partial close reduces open child count | No `TP1_REACHED`, `TP1_CLOSE_SUCCESS`, `TP2_REACHED` or SL-move success inferred from count alone; ambiguity requires fail-closed handling | NOT_RUN | |
| S3 | TP2 child closes after proven TP1 | `TP2_CLOSE_SUCCESS` at most once only for its own `DEAL_REASON_TP` exit and mapped position; stop adjustment reported only after broker confirmation | NOT_RUN | |
| S4 | Final child manually closed AFTER earlier child TP | No `TP3_CLOSE_SUCCESS` or fabricated TP3; earlier TP must not be reused to attribute the final deal | NOT_RUN | |
| S5 | Final child stop-loss closed AFTER earlier child TP | Specific final child `DEAL_REASON_SL` produces stop-loss attribution, not TP3; open/closed ledger remains consistent | NOT_RUN | |
| S6 | Unrelated historical TP deal exists | Different command, magic, symbol or position cannot satisfy this command's TP1/TP2/TP3 stages | NOT_RUN | |
| S7 | Broker rejects remaining-child stop modification | No `SL_MOVE_BREAKEVEN_SUCCESS` / `SL_MOVE_LOCK_PROFIT_SUCCESS` after rejected `PositionModify`; record failure, `ResultRetcode()` and unchanged broker SL | NOT_RUN | |
| S8 | Child position ID/comment missing or broker-mutated | No guessed ownership or TP/SL attribution; record reconciliation ambiguity and prevent unsafe new execution pending resolution | NOT_RUN | |
| S9 | Final TP3 child closes after earlier proven TP exits | Only the final mapped child with its OWN `DEAL_REASON_TP` may yield `TP3_CLOSE_SUCCESS`; prior child TP cannot substitute for final broker exit | NOT_RUN | |

## Evidence review and decision

For **each** S1–S9 row, the independent reviewer checks the original demo
terminal/broker deal history against the EA journal and backend audit receipts,
ensures negative scenarios generated **no** forbidden success event, and verifies
that the record belongs to this exact tested candidate and demo account.
A `NOT_RUN`, `FAIL`, `INCONCLUSIVE`, missing broker proof, missing reviewer, or
mixed candidate/environment makes the **whole supplement NOT ACCEPTED**.
No synthetic or source-only result may be reclassified as broker demo proof.

- Final decision: **NOT_ACCEPTED** (set to `ACCEPTED` only after all real demo rows PASS)
- Failed/inconclusive case IDs, issue links, owner and retest receipt refs: **NOT_RUN**
- Reviewer signature / UTC date / controlled evidence ID: **NOT_RUN**
- External application/security, legal/privacy and controlled-pilot gates: **OPEN**

This supplement is **not** permission for real accounts, automatic copying,
WhatsApp activation, unattended trading or commercial deployment.
