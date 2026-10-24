# SignalGate Provider Pilot Preflight

Run this **before unpausing the first real provider feed**. It is read-only: it makes only GET requests and does not create signals, subscriptions, credentials or commands.

## What it proves

The preflight checks:

- backend health responds;
- `demo_only_mode=true`;
- database readiness is green;
- the configured provider credential authenticates the expected provider;
- a deliberately wrong provider key is rejected with 401;
- provider feeds can be listed;
- before cohort start, every provider feed is still paused by default;
- provider overview is tenant-bound;
- provider evidence export is tenant-bound;
- the provider export contains none of the forbidden secret/raw fields:
  - API keys / key hashes;
  - customer licences / licence hashes;
  - invite/source tokens or token hashes;
  - raw signal text.

It computes a SHA-256 of the returned provider export but does **not** save that raw export, because the export can contain provider/subscriber personal data.

## Secret handling

The provider API key is accepted **only** through the environment:

```bash
export SIGNALGATE_PROVIDER_API_KEY='...'
```

Do not put it in shell arguments, GitHub issues, screenshots or committed files.

Other inputs:

```bash
export SIGNALGATE_BACKEND='https://api.example.com'
export SIGNALGATE_PROVIDER_ID='PROVIDER-...'
export SIGNALGATE_CANDIDATE_SHA='3b18bfc1ab56ca2c94f6ed9aaa5478d97a06d1a2'

python scripts/pilot_preflight.py
```

A non-local backend must use HTTPS. Credentials embedded in the URL are rejected.
The read-only preflight and operational snapshot share the same strict origin
validation: an explicit loopback `http://localhost`, `http://127.0.0.1`
or `http://[::1]` URL is allowed for local demos; every other origin must
use HTTPS. Whitespace, backslashes, percent-encoded authorities, any userinfo
(including empty userinfo), bad/empty ports, repeated path slashes, query or
fragment delimiters are rejected **before** an HTTP client can receive
credentials. This limits operator input ambiguity, but does not validate the
identity of the deployed backend or replace controlled TLS verification.
Both tools explicitly disable ambient HTTP proxy and CA-file overrides
(`httpx.Client(trust_env=False)`) and refuse HTTP redirects when using
provider/admin credentials. This avoids inheriting an unexpected
`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `SSL_CERT_FILE` or `SSL_CERT_DIR`;
HTTPS certificate verification stays enabled with the platform trust store.
If an environment requires a corporate proxy or private CA, configure and
review the trusted network/certificate route before running these tools;
these evidence collectors deliberately do not accept ambient overrides.

The receipt is written under `artifacts/pilot-preflight/`, which should remain outside Git.

The evidence directory is created with owner-only `0700` permissions. Both JSON
and Markdown receipt files are created atomically with owner-only `0600`
permissions, even if the operator's process umask is permissive. Keep these
receipts in controlled storage and never commit them to the repository.

## Failed or malformed responses

The preflight treats a successful HTTP status with malformed JSON, an unexpected
object/list shape, or an incorrectly typed provider identity as a failed check,
not proof of readiness. It issues a `FAIL` receipt when it can safely complete
the remaining read-only checks, rather than accepting an incorrect response.
A transport error remains an incomplete preflight requiring operator review.
For a CLI transport/validation/filesystem failure, stderr reports only the
exception **class**, not the exception message: third-party errors may embed
backend responses, private URLs, credentials or local paths. Diagnose these
failures through controlled operator procedures; do not copy raw errors into
public GitHub issues or CI logs. No FAIL/PASS receipt should be inferred if the
preflight exits before recording one.

To avoid storing unexpected provider/customer data, only nonnegative integer
export-summary counters from an explicit allowlist are copied into receipts;
the complete raw export remains in memory only and is not written to disk.

The same rule applies to the other response bodies: readiness and provider-auth
diagnostics record only Boolean match results/HTTP codes, never unexpected
backend-provided strings. Provider status is recorded only as ACTIVE or
INACTIVE_OR_UNKNOWN, pause fields must be Booleans if present, feed identifiers
must match the expected FED- operational-id format, and overview counters must
be nonnegative integers (not Booleans). Unexpected field types fail the
preflight and their raw values are omitted from the JSON and Markdown
receipts. A forbidden export key produces a count, not a potentially sensitive
nested key path. Receipt redaction is a defensive control, not a guarantee of
the external backend's security or pilot acceptance.

## Candidate identity limitation in RC2

RC2 does not expose a deployment build-id endpoint. Therefore this preflight records the candidate SHA **declared by the operator**, but cannot cryptographically prove the deployed backend is that SHA.

That limitation is explicit in the receipt as:

`candidate_sha_verified_by_backend: false`

Use deployment/container provenance plus the frozen release branch/CI receipts to establish which RC2 image was deployed. A future release can add a non-secret build-id to readiness/health if desired.

## Before versus during pilot

Before opening the cohort, the default preflight requires all provider feeds to be paused.

For a later read-only operational check after the pilot has intentionally started:

```bash
python scripts/pilot_preflight.py --allow-unpaused
```

That relaxes only the paused-feed assertion. All authentication, demo-only, readiness and export-privacy checks remain active.

## Receipt

The generated JSON/Markdown receipt contains:

- backend origin;
- provider id;
- operator-declared candidate SHA;
- each check and result;
- non-secret provider/feed/count metadata;
- hash and summary of the provider evidence export.

It does **not** contain the provider API key, customer licence, source/invite token, raw signal text or raw export.
