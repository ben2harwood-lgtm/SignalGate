# Dependency and Licence Inventory

SignalGate maintains dependency evidence for security review, open-source due diligence and eventual acquisition diligence.

After installing the hosted backend and bot dependencies in a clean environment:

    pip install -r backend/requirements-hosted.txt
    pip install -r telegram_bot/requirements.txt
    python scripts/generate_dependency_inventory.py --output dependency-inventory.json

The inventory records installed package name, version, available licence metadata and homepage. Retain it alongside the dependency-audit result for each release candidate.

This file is evidence support, not legal advice: missing or ambiguous package licence metadata must be reviewed rather than assumed permissive. Keep source-code/contractor IP assignments, domain/trademark ownership and third-party service terms separately in the due-diligence data room.
