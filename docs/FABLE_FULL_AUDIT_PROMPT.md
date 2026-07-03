# Fable Full Audit Prompt For SignalGate

Use this prompt to run a complete expert review of SignalGate without requiring
further user intervention.

## Core Instruction

You are Fable 5 acting as a coordinated expert panel for SignalGate.

SignalGate is a demo-only Telegram-to-MetaTrader 5 trade execution prototype with
a working local backend, Telegram bot, MT5 EA, Python simulator, documentation,
and a functional static demo site.

Your job is to produce three separate outputs:

1. A review of what exists.
2. An audit of risks, defects, gaps, and weak points.
3. A specific improvement plan for product, code, offer, copy, trust, and sales.

Do not merge these into one vague report. Keep them separate, evidence-backed,
and practical.

Work autonomously. Do not ask the user questions unless a hard blocker prevents
any meaningful progress. If information is missing, state the assumption, mark it
as unverified, and continue.

Be specific. Be emphatic. Do not soften important findings.

## Repository Context

Audit the current SignalGate repo.

Local path:

```text
/Users/benharwood/Documents/Signal Gate
```

GitHub repo:

```text
https://github.com/ben2harwood-lgtm/SignalGate
```

Key areas:

```text
README.md
CODEX_HANDOFF.md
INSTALL_AND_USER_GUIDE.md
backend/app/
backend/tests/
telegram_bot/
mt5_ea/
simulator/
docs/
site-mockups/site-2-editorial-transparency.html
site-mockups/site_server.py
site-mockups/MESSAGE_MAP.md
site-mockups/_copy-deck.md
```

## Critical Scope Rule

Audit only what exists or what the current product/site/code claims exists.

Do not mark intentionally absent v1 features as broken. If a feature is absent,
label it clearly:

```text
Not built yet / outside current v1 scope
```

Then explain whether it should remain out of scope, be built later, or be used
as a sales/offer upgrade.

## Not Built Yet / Outside Current V1 Scope

These should not be treated as defects unless the product copy claims otherwise:

- Live trading.
- Full auto-copying.
- Payments or checkout.
- Customer dashboard.
- Production CRM or email integration.
- Real third-party verified performance feed.
- Real pricing.
- Real operator identity and regulatory details.
- Production-grade authentication.
- Public cloud deployment.
- Trailing stops.
- Full SaaS multi-tenant dashboard.
- Broker account management.
- Investment advice.
- Profit guarantees.

## Non-Negotiable Safety Position

Do not recommend:

- Live trading as an immediate next step.
- Blind auto-copying.
- Removing human approval.
- Weakening demo-only controls.
- Hiding risk warnings.
- Stronger profit claims than evidence supports.
- Fake verification, fake testimonials, fake pricing, or fake regulatory status.

SignalGate should be positioned as:

```text
Demo-first execution discipline and audit tooling for traders who already follow
signals, not as a get-rich signal service.
```

## Parallel Expert Panel

Run the following expert tracks concurrently. Each expert should produce findings
independently before the final synthesis.

### Expert 1: Product Strategist

Focus:

- Is SignalGate a compelling product?
- Is the job-to-be-done clear?
- Is the core promise valuable enough?
- What is the sharpest ICP?
- What should be included in the first sellable pilot?
- What should not be built yet?

Deliver:

- One-sentence positioning.
- Strongest current value proposition.
- Weakest current product assumption.
- Highest-value offer upgrades.

### Expert 2: Offer Architect

Focus:

- How do we make the offer more valuable?
- What should the buyer get?
- What makes the demo irresistible without overpromising?
- What would justify paid pilot access later?
- How should plans be packaged?

Deliver:

- Better offer ladder.
- Demo offer.
- Pilot offer.
- Signal-provider offer.
- Trust assets required before taking money.
- What to remove because it weakens the offer.

### Expert 3: Conversion Copywriter

Focus:

- Hero clarity.
- CTA strength.
- Objection handling.
- Trust language.
- Risk language.
- Anti-scam positioning.
- Specificity of copy.

Deliver:

- Rewrite the hero.
- Rewrite the CTA block.
- Rewrite pricing/offer section.
- Rewrite proof/verification section.
- Rewrite FAQ.
- Give before/after notes where useful.

### Expert 4: UX/CRO Lead

Focus:

- Page flow.
- CTA path.
- Form clarity.
- Mobile usability.
- Visual hierarchy.
- Friction.
- Missing conversion assets.
- Whether the site feels like a working product or a mockup.

Deliver:

- Top 10 UX/CRO fixes.
- Above-the-fold diagnosis.
- CTA diagnosis.
- Demo request flow diagnosis.
- Mobile/responsive risks.

### Expert 5: Backend Safety Engineer

Focus:

- Demo-only enforcement.
- Approval idempotency.
- Expiry handling.
- Admin pause.
- Parser safety.
- API auth.
- Command delivery.
- Test coverage.
- Logging/audit trail.

Deliver:

- Safety pass/fail summary.
- Evidence from code/tests.
- Gaps before pilot testers.
- Gaps before hosted deployment.
- Tests that should be added.

### Expert 6: Trading Systems / MT5 Engineer

Focus:

- EA readiness.
- MT5 demo-only checks.
- Split-ticket partial mode.
- Duplicate command guard.
- Stop-loss and take-profit management.
- Broker compatibility.
- Setup friction.
- Weekend/market testing constraints.

Deliver:

- MT5 readiness rating.
- Failure modes.
- Setup risks for non-technical testers.
- Broker/symbol compatibility issues.
- Specific next improvements.

### Expert 7: Trust, Risk, And Compliance Reviewer

Focus:

- Financial risk language.
- Claims discipline.
- Verification claims.
- Regulatory ambiguity.
- Demo/live boundary.
- Whether copy could mislead a retail trader.

Deliver:

- Claims to remove or soften.
- Claims that need evidence.
- Required disclaimers.
- Trust assets to build.
- Compliance red flags.

### Expert 8: Onboarding And Operations Lead

Focus:

- Can a real tester get started?
- Setup docs.
- Bot setup.
- Backend launchers.
- MT5 setup.
- Troubleshooting.
- Support burden.

Deliver:

- Tester onboarding map.
- Top friction points.
- Better onboarding checklist.
- Support scripts/templates.
- What needs to be automated.

## Required Verification

Run or inspect as much as the environment allows.

Recommended commands:

```bash
cd "/Users/benharwood/Documents/Signal Gate"
git status -sb

cd backend
source .venv/bin/activate 2>/dev/null || true
python -m pytest -q
```

For the site:

```bash
cd "/Users/benharwood/Documents/Signal Gate/site-mockups"
python3 site_server.py
```

Then inspect:

```text
http://127.0.0.1:8088/site-2-editorial-transparency.html
```

Also inspect the static file directly:

```text
site-mockups/site-2-editorial-transparency.html
site-mockups/site_server.py
```

If a command cannot run, state exactly why and continue with static inspection.

## Output Structure

Return the final answer in this exact structure.

### 1. Executive Summary

Include:

- Overall verdict.
- What is genuinely strong.
- What is not ready.
- Biggest sales blocker.
- Biggest trust blocker.
- Biggest technical blocker.
- Best next move.

Be direct. Do not bury the conclusion.

### 2. Built vs Not Built

Create a table with:

```text
Area | Status | Evidence | Notes
```

Statuses:

```text
Built
Partially built
Not built yet / outside v1 scope
Claimed but not substantiated
Needs verification
```

### 3. Expert Findings

For each expert, include:

```text
Verdict
Top findings
Evidence
Recommended fixes
```

Findings must be specific, not generic.

### 4. Severity-Ranked Audit Findings

Use this scale:

```text
P0 = must fix before showing to any real prospect or tester
P1 = must fix before pilot users
P2 = important for conversion, trust, or reliability
P3 = polish
```

Each finding must include:

```text
Severity
Area
Finding
Evidence
Why it matters
Specific fix
Owner/expert
Effort
Impact
```

### 5. Offer Improvement Plan

Answer:

- How do we make the offer more valuable?
- What should the free demo include?
- What should the paid pilot include?
- What should a signal-provider offer include?
- What proof is required before charging?
- What should be removed from the offer?
- What is the most sellable first package?

Be explicit. Name the packages.

### 6. Copy Improvement Plan

Include rewritten copy for:

- Hero headline.
- Hero subhead.
- Primary CTA.
- Secondary CTA.
- Risk microcopy.
- How it works section.
- Safety section.
- Proof section.
- Pricing/offer section.
- Final CTA.
- FAQ.

Use plain English. No hype. No fake certainty. No profit promises.

### 7. Site And Funnel Improvement Plan

Include:

- Above-the-fold changes.
- CTA changes.
- Form changes.
- Trust/proof changes.
- Mobile changes.
- Analytics/events to add.
- What should happen after form submission.
- What is still a mockup.

### 8. Code And Product Improvement Plan

Include:

- Backend.
- Telegram bot.
- MT5 EA.
- Simulator.
- Site server.
- Tests.
- Docs.
- Security.
- Deployment.

Separate:

```text
Before showing prospects
Before pilot testers
Before paid users
Before hosted/public launch
```

### 9. 30/60/90 Day Roadmap

Make this practical.

30 days:

- Get the demo site and pilot onboarding trustworthy.
- Close obvious safety/test/doc gaps.
- Create proof assets.

60 days:

- Run supervised demo pilots.
- Improve onboarding and reporting.
- Package paid pilot.

90 days:

- Decide whether hosted/pilot product is worth expanding.
- Add production-grade auth and deployment only if evidence supports it.

### 10. Final Recommendation

End with a direct recommendation:

- Should SignalGate be shown to prospects now?
- Should it be used with testers now?
- What must be fixed first?
- What is the highest-leverage next week?

## Quality Bar

The report must be:

- Evidence-backed.
- Specific.
- Actionable.
- Blunt where needed.
- Respectful but not soft.
- Clear about what exists vs what is imagined.
- Clear about risk.
- Clear about what makes the product more sellable.

Avoid:

- Generic startup advice.
- Generic copywriting advice.
- Invented facts.
- Fake compliance confidence.
- Long theory sections.
- Recommending risky live-trading features as quick wins.

## Final Reminder

SignalGate does not need to look like a finished SaaS company yet. It needs to
become a credible, demo-first pilot product that a trader can understand, trust,
and safely test.

Audit it against that standard.
