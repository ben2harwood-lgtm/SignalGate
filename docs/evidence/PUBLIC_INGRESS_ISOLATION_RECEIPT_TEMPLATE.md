# Public Ingress / Local-Identity Isolation — Evidence Template (NOT RUN)

**Purpose:** Support independent, environment-specific review of the unresolved
[local-auth public-ingress HOLD #108](https://github.com/ben2harwood-lgtm/SignalGate/issues/108).
This is a blank assessor receipt, **not a test result or a release approval**.
Source/ASGI tests can show that known spoofed headers fail closed; they cannot
prove that a real proxy cannot strip those headers, rewrite Host to loopback and
forward an unauthorised request to a local-identity backend.

## Candidate and authority (fill before any testing)

- **Exact reviewed application SHA:** NOT RECORDED
- **CI run, migration head, and build/artifact digest:** NOT RECORDED
- **Assessor and assessment date:** NOT RECORDED
- **Authorised isolated environment / change approval:** NOT RECORDED
- **Public-facing edge/proxy product and configuration revision:** NOT RECORDED
- **Actual backend bind/interface and network route, privately evidenced:** NOT RECORDED
- **Mode verified from independent configuration:** NOT RECORDED
- **Synthetic admin / Provider A / Provider B test identities:** NOT RECORDED
- **Private evidence bundle, hash, and storage reference:** NOT RECORDED
- **Open exception, owner and expiry (if any):** NOT RECORDED

**Safety setup:** Only use an assessor-owned **isolated**, disposable environment
with synthetic credentials, accounts and data. Do not connect a broker, real
Telegram account, provider, customer, model API or paid service. Do not expose
an unlicensed local-identity backend to the public internet even temporarily.
The external-network tests below are a *plan* for a separately authorised
assessor-controlled environment; they are not permission to deploy one.
Store network traces, addresses, headers and unredacted logs in the controlled
data room, **never** in the public repository or issue comments.

## Assessor procedure

1. Pin the exact SHA, image/binary digest and migration head; establish that
   the test environment truly runs those bytes. Record the actual reverse-proxy
   hop(s), backend socket/listener, firewall and network path independently of
   operator-supplied `BACKEND_HOST` / `BACKEND_BASE_URL` strings.
2. Use an **outside-the-backend** test principal, not just an in-process
   FastAPI TestClient. Verify both the public edge and the private upstream.
   Keep the unauthorised test principal separate from any successful control.
   Prove that the **same target endpoint** is reachable with a separately
   authorised synthetic control; a denial from an unrelated route, dead
   backend or misrouted proxy is not positive proof of isolation.
3. For each scenario, record a redacted request/response pair (status,
   side effects, session identity and timestamp), an assessor-verified routing
   observation, and any application/security log event. A 401/403 alone is
   not enough if a proxy/network path or a different route was not tested.
4. Use a provider-scoped read-only or disposable non-execution endpoint and
   a synthetic admin-only read for authorisation probes. **Never** test by
   placing a trade, creating a real provider, changing a production setting
   or sending a subscriber card.
5. Retest failures against a new pinned candidate SHA and independently
   verify the new proxy configuration. Record old and new evidence separately.

## Mandatory negative and positive observations

| ID | Isolated-environment observation | Required outcome | Actual | Evidence ref |
| --- | --- | --- | --- | --- |
| NI-01 | Independently exercise **(a)** public configured `BACKEND_HOST`/`BACKEND_BASE_URL`, **(b)** unlicensed PostgreSQL schema initialization and **(c)** a nonloopback actual ASGI listener overridden independently of loopback configuration | **(a)** Startup refuses before DB initialization; **(b)** schema initialization refuses before any mutation; **(c)** privileged HTTP is refused before route dispatch. Record all three separately; the actual listener's network isolation still requires NI-02 | NOT_RUN | — |
| NI-02 | Attempt direct backend/upstream access from a distinct unauthorised network principal | No reachable privileged API; verify actual firewall/listener path, not only a DNS name | NOT_RUN | — |
| NI-03 | Through the authorised staging edge, present **identity-only** local admin/provider headers with no actual service or tenant credential | No privileged read or mutation; auth or edge denial, with no secret/user data in response | NOT_RUN | — |
| NI-04 | On a private assessor-owned test proxy that **rewrites Host to loopback and strips all Forwarded/X-Forwarded/other proxy-origin metadata**, repeat NI-03 | Local identity must **not** become authorisation merely because the upstream appears to be loopback. If it does, **FAIL/HOLD** | NOT_RUN | — |
| NI-05 | Send attacker-controlled forwarding/Host variants through the authorised staging edge | Spoofed/duplicate forwarding or Host data does not confer privileges or escape the actual edge policy | NOT_RUN | — |
| NI-06 | Use a correctly scoped *synthetic* hosted Provider A credential through the normal edge | Only permitted Provider A read succeeds; mismatched/revoked key and Provider B object access fail | NOT_RUN | — |
| NI-07 | Inspect upstream/edge request and denial logs for NI-01–06 | No secret, credential, sensitive response, raw personal data, or untrusted Host/header disclosure; trace links to tested SHA | NOT_RUN | — |

**NI-01 evidence interpretation:** Configured bind/URL validation occurs in
`backend/app/config.py::Settings.validate_startup`; unlicensed engine/schema
validation is in `backend/app/database.py::init_db`; actual ASGI listener and
Host rejection occurs **per HTTP request** in `backend/app/main.py`, not at
Uvicorn startup. A Uvicorn `--host` override can therefore start while requests
are blocked. Do **not** report that observation as a startup refusal, and do
**not** infer isolation merely from middleware HTTP 403. The distinct
out-of-process/network observation NI-02 is still required. Synthetic
`backend/tests/test_local_ingress_settings_guard.py` tests establish source
behaviour, not network acceptance. NI-01 remains **NOT_RUN** until all three
separate assessor observations have evidence.

**Critical interpretation:** NI-04 is the specific blind spot recorded in
issue #108. A passing in-process header test or an application-only 403
**cannot** close it. If the topology exposes an unlicensed backend behind a
stripping proxy, classify the environment as **HOLD**, remove that route and
retest; do not substitute a source-level assertion for independent network
evidence. If any scenario was not feasible, record **NOT_RUN**, not PASS.

## Source anchors for assessor review

At the draft integration candidate, inspect the exact SHA's
`backend/app/main.py` local-ingress middleware,
`backend/app/config.py` startup/bind validation,
`backend/app/security.py` local identity-header fallback and
`backend/app/database.py` schema-init boundary. These are review targets,
not claims that draft PRs have passed ingress acceptance.
Refer to `docs/HOSTED_DEPLOYMENT.md`, `docs/PENTEST_SCOPE.md` and
`docs/evidence/SECURITY_REVIEW_RECEIPT_TEMPLATE.md`; issue #108
owns the unresolved public-ingress gate.

## Independent decision (leave blank until actual receipts)

- [ ] Candidate and test-environment identity independently confirmed.
- [ ] All seven cases performed and evidence reviewed, including NI-04.
- [ ] No reachable unauthorised local-identity route.
- [ ] No unresolved critical/high ingress findings.
- [ ] Independent reviewer signs off with controlled evidence link.

**Reviewer, organisation, date and decision:** NOT RECORDED

**Current gate:** **HOLD / NOT TESTED**. This template does not satisfy G3,
G8, independent penetration testing, MT5 demo-broker acceptance or external
pilot entry. Frozen RC2 remains unchanged; its failed official MetaEditor
compile cannot be replaced by any result from this template. Real-money
trading and automatic copying remain blocked.
