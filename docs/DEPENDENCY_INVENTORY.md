# Dependency and Licence Inventory

SignalGate maintains installed-environment dependency evidence for security review, open-source due diligence and eventual acquisition diligence.

In a fresh Python environment, after checking out the **exact** candidate commit and installing both the hosted backend and bot dependencies:

    pip install -r backend/requirements-hosted.txt
    pip install -r telegram_bot/requirements.txt
    python scripts/generate_dependency_inventory.py --output dependency-inventory-<candidate>.json

Replace `<candidate>` with the commit shorthand (without angle brackets in a shell); use a **new output filename each run**. The fully written JSON is published atomically without replacing existing files/symlinks, and on POSIX the output file is owner-readable only (0600). A failed/partial write leaves no final-name receipt. Keep this receipt private until its package metadata and intended recipients have been reviewed.

The v2 receipt records the actual Git HEAD and SHA-256 digests of the generator and three dependency requirement files **only if their working-tree bytes match the committed Git blobs**. A modified/untracked replacement of one of those tracked source inputs fails closed. It records installed distribution names, versions, available licence metadata and homepages.

**Important limitation:** the report is an observation of the currently selected Python interpreter's installed packages. It does **not** establish that the Python environment matches the committed requirements, that the installed runtime equals the deployed container, or that all dependencies are present. The explicit `installed_environment_match_status: NOT_VERIFIED` must remain until a separate reviewer validates candidate/container bindings, requirement coverage and dependency audits. It is not release acceptance or an SBOM attestation.

Retain the inventory alongside exact-candidate dependency audit/container provenance; resolve missing or ambiguous licence metadata manually. Keep source-code/contractor IP assignments, domain/trademark ownership and third-party service terms separately in the due-diligence data room.
