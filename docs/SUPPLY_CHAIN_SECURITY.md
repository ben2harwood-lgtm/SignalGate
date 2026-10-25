# SignalGate Supply-Chain Security Checks

SignalGate's normal CI already runs Bandit and `pip-audit`. The deep-security workflow adds independent checks that cover different failure classes.

## Git history secret scan

`gitleaks/gitleaks-action@v3` scans full Git history (`fetch-depth: 0`) for credential/token material that may no longer exist in the current tree.

This matters because the repository has been public. A secret removed from the latest commit is still compromised if it remains reachable in public history.

A clean scan does not prove no secret was ever exposed through logs, issues, artifacts or another repository.

## Filesystem security scan

Trivy scans the repository for **fixable HIGH/CRITICAL** dependency and misconfiguration findings.

The normal Python `pip-audit` jobs remain authoritative for pinned Python requirement files; Trivy adds another dependency/configuration view.

## Hosted container scan

The workflow builds the actual SignalGate hosted image from the current branch, then Trivy scans the resulting image for **fixable HIGH/CRITICAL** OS/library vulnerabilities.

This catches base-image/package issues that source-only Python scans do not.

## Release interpretation

These checks are automated assurance, not a substitute for:

- independent penetration testing;
- cloud/deployment configuration review;
- secrets-manager/IAM review;
- provider/broker environment review;
- privacy/regulatory assurance.

A newly discovered critical/high issue blocks expansion until remediated or explicitly dispositioned under the release exception process.

## Versions

As introduced on 19 September 2026:

- Gitleaks GitHub Action v3;
- Trivy GitHub Action v0.36.0.

Dependabot should continue to surface action updates where supported.

## Local dotenv and evidence isolation

Repository ignore rules exclude local `.env` and `.env.*` variants at any depth, while
retaining the placeholder-only `.env.example` and `.env.hosted.example` templates.
New operator-generated `artifacts/` subdirectories are also ignored rather than
only a fixed list of known receipt locations. The Docker build context excludes
nested dotenv variants and artifacts independently of Git's ignore rules.

These are **accidental-inclusion safeguards**, not secret-management or assurance
controls. `git add -f` can override `.gitignore`, already-tracked files remain
tracked, and ignore rules cannot erase secrets from Git history or CI artifacts.
Review staged diffs and run the repository secret scan before every integration;
store real provider/customer data and detailed acceptance evidence outside the
public repository, using stable receipt identifiers in the public index.
