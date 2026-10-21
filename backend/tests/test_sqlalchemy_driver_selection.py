"""Keep PostgreSQL engine/migration driver explicit across SQLAlchemy releases.

Production backup/restore consumes DATABASE_URL as a libpq URL, so the app must
not turn the operator's environment string into a SQLAlchemy-only driver URL.
"""
import pytest
from sqlalchemy.engine import make_url

from app.config import sqlalchemy_driver_url
from app.database import engine


@pytest.mark.parametrize(
    ("incoming", "expected"),
    [
        (
            "postgresql://test-user:masked@localhost:5432/signal?sslmode=require",
            "postgresql+psycopg2://test-user:masked@localhost:5432/signal?sslmode=require",
        ),
        (
            "postgres://test-user:masked@localhost:5432/signal",
            "postgresql+psycopg2://test-user:masked@localhost:5432/signal",
        ),
        (
            "postgresql+psycopg2://test-user:masked@localhost:5432/signal",
            "postgresql+psycopg2://test-user:masked@localhost:5432/signal",
        ),
        (
            "postgresql+psycopg://test-user:masked@localhost:5432/signal",
            "postgresql+psycopg://test-user:masked@localhost:5432/signal",
        ),
        ("sqlite:////tmp/signalgate-test.db", "sqlite:////tmp/signalgate-test.db"),
    ],
)
def test_explicit_psycopg2_for_unqualified_postgresql_without_mutating_fields(
    incoming, expected
):
    actual = sqlalchemy_driver_url(incoming)
    assert actual == expected
    if incoming.startswith(("postgres://", "postgresql://")):
        expected_url = make_url(actual)
        assert expected_url.drivername == "postgresql+psycopg2"
        assert expected_url.password == "masked"
        assert expected_url.query.get("sslmode") == (
            "require" if "sslmode=require" in incoming else None
        )


def test_actual_test_engine_selects_installed_postgres_driver():
    if engine.url.get_backend_name() == "postgresql":
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg2"
    else:
        assert engine.dialect.name == "sqlite"
