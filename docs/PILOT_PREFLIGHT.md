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

The receipt is written under `artifacts/pilot-preflight/`, which should remain outside Git.

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
