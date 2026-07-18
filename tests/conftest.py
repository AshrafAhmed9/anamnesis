from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("ANAMNESIS_MOCK_LLM", "1")
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "cockroachdb+psycopg://root@localhost:26257/anamnesis_test?sslmode=disable"),
)

from anamnesis.db.engine import get_engine  # noqa: E402
from anamnesis.db.models import Base  # noqa: E402


@pytest.fixture(scope="session")
def db_engine():
    engine = get_engine()
    Base.metadata.create_all(engine)
    yield engine


@pytest.fixture(autouse=True)
def clean_tables(db_engine):
    with db_engine.begin() as conn:
        for table in ("memory_audit", "semantic_memory", "episodic_memory", "ops_log"):
            conn.exec_driver_sql(f"DELETE FROM {table}")
    yield


@pytest.fixture
def session_id():
    return uuid.uuid4()
