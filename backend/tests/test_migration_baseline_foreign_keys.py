"""Baseline adoption must not stamp orphan-permitting schemas as safe.

These inspection tests use a synthetic inspector; they never connect to or
mutate a broker, provider, hosted database or external service. CI separately
runs the real historical Alembic baseline check against PostgreSQL.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "verify_migration_baseline.py"
_SPEC = importlib.util.spec_from_file_location("signalgate_baseline_fk_guard", _SOURCE)
assert _SPEC is not None and _SPEC.loader is not None
verifier = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verifier)


class _Inspector:
    default_schema_name = "public"

    def __init__(self, *, missing=None, substitute=None, foreign_schema=None,
                 search_path_hidden_schema=None):
        self.missing = missing
        self.substitute = substitute
        self.foreign_schema = foreign_schema
        self.search_path_hidden_schema = search_path_hidden_schema
        self.foreign_key_calls = []

    def get_table_names(self):
        return list(verifier.EXPECTED_COLUMNS)

    def get_columns(self, table):
        return [{"name": name} for name in verifier.EXPECTED_COLUMNS[table]]

    def get_pk_constraint(self, table):
        return {"constrained_columns": ["id"]}

    def get_unique_constraints(self, table):
        return [
            {"column_names": list(cols)}
            for cols in verifier.EXPECTED_UNIQUE.get(table, ())
        ]

    def get_indexes(self, table):
        return []

    def get_foreign_keys(self, table, **kwargs):
        self.foreign_key_calls.append(kwargs)
        rows = []
        for relation in verifier.EXPECTED_FOREIGN_KEYS.get(table, ()):
            if (table, relation) == self.missing:
                continue
            local, referenced_table, remote = relation
            schema = None
            if (table, relation) == self.substitute:
                referenced_table = "unrelated_" + referenced_table
            if (table, relation) == self.foreign_schema:
                schema = "other_tenant"
            if (table, relation) == self.search_path_hidden_schema:
                # PostgreSQL's default reflection can conceal cross-schema
                # references when the target schema is in search_path.
                schema = ("other_tenant" if kwargs.get(
                    "postgresql_ignore_search_path") is True else None)
            rows.append({
                "constrained_columns": list(local),
                "referred_table": referenced_table,
                "referred_columns": list(remote),
                "referred_schema": schema,
            })
        return rows


def _run(monkeypatch, capsys, inspector):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/no_network")
    monkeypatch.setattr(verifier, "sqlalchemy_driver_url", lambda url: url)
    monkeypatch.setattr(verifier, "create_engine", lambda *_a, **_k: object())
    monkeypatch.setattr(verifier, "inspect", lambda _engine: inspector)
    code = verifier.main()
    output = capsys.readouterr()
    return code, output.out, output.err


def test_complete_historical_relations_pass_without_database_io(monkeypatch, capsys):
    assert sum(map(len, verifier.EXPECTED_FOREIGN_KEYS.values())) == 10
    code, stdout, stderr = _run(monkeypatch, capsys, _Inspector())
    assert code == 0
    assert "BASELINE VERIFICATION PASSED" in stdout
    assert not stderr


@pytest.mark.parametrize(
    ("table", "relation"),
    [
        ("approvals", (("signal_id",), "signals", ("id",))),
        ("approvals", (("user_id",), "users", ("id",))),
        ("commands", (("signal_id",), "signals", ("id",))),
        ("commands", (("approval_id",), "approvals", ("id",))),
        ("commands", (("user_id",), "users", ("id",))),
        ("executions", (("command_id",), "commands", ("id",))),
        ("executions", (("user_id",), "users", ("id",))),
        ("trade_management_events", (("command_id",), "commands", ("id",))),
        ("performance_ledger", (("signal_id",), "signals", ("id",))),
        ("performance_ledger", (("command_id",), "commands", ("id",))),
    ],
)
def test_each_missing_relation_refuses_stamping(
    monkeypatch, capsys, table, relation
):
    code, stdout, stderr = _run(
        monkeypatch, capsys, _Inspector(missing=(table, relation))
    )
    assert code == 1
    assert "BASELINE VERIFICATION FAILED" in stderr
    assert f"{table}: missing foreign key" in stderr
    assert "Safe next step" not in stdout


@pytest.mark.parametrize("bad_kind", ["wrong_target", "foreign_schema"])
def test_misbound_relation_cannot_satisfy_baseline(
    monkeypatch, capsys, bad_kind
):
    relation = ("commands", (("approval_id",), "approvals", ("id",)))
    inspector = _Inspector(**{("substitute" if bad_kind == "wrong_target"
                              else "foreign_schema"): relation})
    code, stdout, stderr = _run(monkeypatch, capsys, inspector)
    assert code == 1
    assert "commands: missing foreign key" in stderr
    assert "Safe next step" not in stdout


def test_foreign_search_path_does_not_conceal_wrong_schema(monkeypatch, capsys):
    # Without the PostgreSQL reflection option this corrupt relationship
    # appears to point into the default schema and wrongly passes the stamp.
    relation = ("commands", (("approval_id",), "approvals", ("id",)))
    inspector = _Inspector(search_path_hidden_schema=relation)
    code, stdout, stderr = _run(monkeypatch, capsys, inspector)
    assert code == 1
    assert "commands: missing foreign key" in stderr
    assert "Safe next step" not in stdout
    assert len(inspector.foreign_key_calls) == len(verifier.EXPECTED_FOREIGN_KEYS)
    assert all(
        options == {"postgresql_ignore_search_path": True}
        for options in inspector.foreign_key_calls
    )
