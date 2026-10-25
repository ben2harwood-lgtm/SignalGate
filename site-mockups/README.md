# SignalGate site mockups

## Active direction

`provider-edition.html` is the current provider-agnostic B2B direction.

The older `direction-*` and `site-*` pages were retail-trader concept work from
the July prototype. They are retained only as design history and **must not be
published as current product claims**. In particular, any sample performance,
audit, pricing or operator copy in those pages is placeholder material.

Before publishing Provider Edition:
- replace the placeholder contact;
- insert the real operating legal entity;
- pass Release Gate 8 regulatory/marketing review;
- remove the demo-hardening qualification only when the corresponding release
  gates have actually passed.

## Historical preview privacy safeguard (25 October 2026)

The legacy `site-2-editorial-transparency.html` contact form is now **an in-tab fictional design preview only**. It does not send contact information, use browser storage for form submissions or represent a genuine provider enquiry. It removes the old `signalgate_demo_requests` browser-storage key on page load (where accessible). Do not enter real names, contact details, accounts or provider information.

The loopback-only `site_server.py` returns HTTP 410 for `POST /api/demo-requests` and does **not** read or persist its body. It is not an intake, CRM, consent or pilot workflow. A real enquiry endpoint would need separate owner approval, privacy/retention controls, explicit consent and release-gate review.

**Existing historical data is not automatically deleted:** if the old preview was used, an operator must separately inspect and securely dispose of any previously created ignored `site-mockups/demo-requests.jsonl` and any stored browser copies. This change does not touch those local files or other users' browsers. The active Provider Edition page remains a static design mockup, not approved public marketing.
