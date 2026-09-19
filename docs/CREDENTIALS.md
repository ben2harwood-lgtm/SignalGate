# SignalGate Credential Storage

## Provider credentials

Provider API keys are generated randomly, returned only at issuance/rotation, and stored as SHA-256 hashes. Rotation revokes previously active provider credentials.

## Customer EA licences

Customer EA licences are generated as human-readable random values, returned only at initial registration or explicit rotation, and stored as:

- SHA-256 hash for authentication;
- last four characters for operator identification;
- no recoverable raw value.

The historical `users.license_key` database column is retained only as a nullable migration bridge. Migration `20260919_0007` hashes every existing non-empty legacy value and sets that plaintext column to NULL.

Admin customer listings expose only whether a licence is configured and its last four characters. A lost licence must be rotated; it cannot be retrieved.

## Service credentials

Admin, registration/bot and EA service credentials are loaded from deployment secrets and must meet hosted startup strength requirements. Provider and customer credentials are sent in headers, not URLs.

## Logging rule

Credentials, authentication headers and request query values must never be included in structured request logs or audit payloads. Audit events may contain non-secret last-four metadata and credential ids for operational correlation.

## Rotation

- provider key: provider portal/API rotation revokes prior active provider keys;
- customer licence: admin rotation immediately invalidates the old licence;
- service secrets: rotate in the deployment secret store using the incident/runbook process.

A database downgrade across the customer-licence hashing migration cannot reconstruct old raw credentials. After such a rollback, customer licences must be reissued.
