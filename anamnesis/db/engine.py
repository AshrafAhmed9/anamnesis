"""CockroachDB connection engine with serialization-retry handling.

CockroachDB uses SERIALIZABLE isolation for every transaction. Under
contention this can surface as a retryable error (SQLSTATE 40001 /
"restart transaction"). Memory writes in Anamnesis are transactional by
design (an episodic insert + a belief supersede + an audit row happen
together, or not at all) so we wrap every write in a retry loop rather
than silently dropping data on a transient conflict.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

_RETRYABLE_SQLSTATE = "40001"


def _is_serialization_failure(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate:
        return sqlstate == _RETRYABLE_SQLSTATE
    return _RETRYABLE_SQLSTATE in str(exc)


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Point it at your CockroachDB cluster, e.g.\n"
            "  cockroachdb+psycopg://<user>:<password>@<host>:26257/anamnesis"
            "?sslmode=verify-full"
        )
    # Accept a plain postgresql:// URL too, but always dispatch through the
    # official CockroachDB SQLAlchemy dialect (sqlalchemy-cockroachdb), which
    # understands CRDB's version string and retryable-transaction semantics.
    if url.startswith("postgresql+psycopg://"):
        url = "cockroachdb+psycopg://" + url[len("postgresql+psycopg://"):]
    elif url.startswith("postgresql://"):
        url = "cockroachdb+psycopg://" + url[len("postgresql://"):]
    return url


_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine, _SessionFactory
    if _engine is None:
        _engine = create_engine(get_database_url(), pool_pre_ping=True, future=True)
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def retryable(fn):
    """Decorator: retry a callable on CockroachDB SQLSTATE 40001 with backoff."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=2),
        retry=retry_if_exception(_is_serialization_failure),
    )(fn)


@contextmanager
def session_scope(audit_retries: bool = True) -> Iterator[Session]:
    """Yield a Session inside a retryable, atomic transaction block.

    On SQLSTATE 40001 the whole block (including any prior statements
    in this transaction) is retried from scratch, per CockroachDB's
    client-side transaction retry contract.
    """
    get_engine()
    assert _SessionFactory is not None

    from tenacity import Retrying

    for attempt in Retrying(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=2),
        retry=retry_if_exception(_is_serialization_failure),
    ):
        with attempt:
            session = _SessionFactory()
            try:
                yield session
                session.commit()
                return
            except Exception as exc:
                session.rollback()
                if _is_serialization_failure(exc) and audit_retries:
                    _log_retry(session, exc)
                raise
            finally:
                session.close()


def _log_retry(session: Session, exc: BaseException) -> None:
    """Best-effort audit row for a serialization retry (own tiny transaction)."""
    from anamnesis.db.models import MemoryAudit

    try:
        with _SessionFactory() as s:  # type: ignore[misc]
            s.add(
                MemoryAudit(
                    action="RETRY",
                    reason=str(exc)[:500],
                )
            )
            s.commit()
    except Exception:
        pass
