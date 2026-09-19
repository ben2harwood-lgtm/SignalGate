# External Review Bundles

SignalGate can build deterministic, allowlisted ZIP packages for external acceptance work.

The builder deliberately does **not** crawl the repository. Each profile contains only explicit public files, which reduces the risk of accidentally packaging `.env`, credentials or unrelated material.

## Command

Check out the exact candidate first, then build from that checkout:

```bash
git checkout <candidate-branch-or-sha>
candidate_sha="$(git rev-parse HEAD)"
python scripts/build_acceptance_bundle.py \
  --profile mt5 \
  --candidate-sha "$candidate_sha"
```

By default the builder verifies that the checked-out Git HEAD exactly equals `--candidate-sha` and fails if it does not. This prevents a later working tree from being mislabeled as an older accepted candidate.

`--allow-unverified-source` exists only for deliberately exported/non-Git source trees. When used, the manifest records `source_tree_verified: false`; do not treat that bundle as candidate-bound evidence without an independent source-integrity receipt.

Profiles:

- `mt5` — EA source, MT5 setup/acceptance instructions and receipt template;
- `security` — architecture, threat/security/privacy material and pentest scope;
- `counsel` — architecture, provider/commercial model and UK regulatory/privacy brief;
- `pilot` — onboarding, beta, first-provider and operations material.

The command prints the bundle path and SHA-256 digest. The ZIP contains `MANIFEST.json` with:

- exact candidate SHA;
- bundle profile;
- path, SHA-256 and size for every included file.

ZIP entry ordering and timestamps are fixed, so identical inputs produce identical bundle bytes.

## Release discipline

Use the frozen candidate SHA relevant to the review. Do not quietly rebuild a bundle from later runtime code and call it the same receipt.

The public bundle may include blank receipt templates. Actual credentials, private provider/customer data, privileged legal advice and unredacted security reports must remain in the controlled data room.
