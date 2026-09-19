"""Static regression guards for backup encryption fail-closed behaviour."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKUP = (ROOT / "scripts" / "backup_postgres.sh").read_text(encoding="utf-8")
RESTORE = (ROOT / "scripts" / "restore_postgres.sh").read_text(encoding="utf-8")


def test_hosted_backup_requires_encryption_or_explicit_plaintext_escape():
    assert "BACKUP_AGE_RECIPIENT" in BACKUP
    assert "BACKUP_ALLOW_PLAINTEXT" in BACKUP
    assert "Refusing plaintext backup" in BACKUP
    assert "age --recipient" in BACKUP
    assert "sha256sum" in BACKUP


def test_encrypted_restore_requires_identity_and_checksum():
    assert "BACKUP_AGE_IDENTITY_FILE" in RESTORE
    assert "sha256sum --check" in RESTORE
    assert "age --decrypt" in RESTORE
    assert "BACKUP_ALLOW_PLAINTEXT_RESTORE" in RESTORE
    assert "Refusing plaintext restore" in RESTORE
