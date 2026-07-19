"""CockroachDB connection engine with retry handling for two distinct
transient-failure classes:

1. **Serialization conflicts** (SQLSTATE 40001 / "restart transaction") —
   CockroachDB uses SERIALIZABLE isolation for every transaction, and under
   contention the client is expected to retry the whole transaction.
2. **Lost/killed connections** — a dropped connection mid-transaction
   surfaces as a DBAPI-level error, not a SQLSTATE; SQLAlchemy marks these
   with `connection_invalidated=True` regardless of driver, which is what
   `pool_pre_ping` also relies on to evict dead connections from the pool.

Memory writes in Anamnesis are transactional by design (an episodic insert
+ a belief supersede + an audit row happen together, or not at all), so
both classes are retried rather than silently dropping data.

`run_in_transaction(fn)` is the retry-guaranteed primitive: `fn(session)`
is invoked with a *fresh* Session on every attempt, so both the reads and
the writes it performs are correctly redone from scratch on each retry —
this is CockroachDB's actual client-side retry contract. A plain
`with session_scope() as db: ...` context manager cannot honor this: once
its single `yield` has resumed the caller's `with`-block body, that body
has already run and cannot be silently re-executed by the context manager
if the later `commit()` fails, so `session_scope()` here is deliberately
non-retrying and meant only for straightforward reads.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

_RETRYABLE_SQLSTATE = "40001"
_MAX_ATTEMPTS = 5

T = TypeVar("T")


def _is_retryable(exc: BaseException) -> bool:
    if getattr(exc, "connection_invalidated", False):
        return True
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate:
        return sqlstate == _RETRYABLE_SQLSTATE
    return _RETRYABLE_SQLSTATE in str(exc)


_secrets_manager_url_cache: str | None = None


def _fetch_database_url_from_secrets_manager(secret_arn: str) -> str:
    """Resolve DATABASE_URL from AWS Secrets Manager instead of a
    plaintext environment variable — used in the deployed Lambda stack
    (infra/template.yaml sets DATABASE_SECRET_ARN, never DATABASE_URL
    directly) so the credential isn't visible via
    lambda:GetFunctionConfiguration or CloudFormation parameter history.
    Cached for the lifetime of the process (a Lambda cold start), so a
    warm invocation doesn't re-fetch on every call.
    """
    global _secrets_manager_url_cache
    if _secrets_manager_url_cache is not None:
        return _secrets_manager_url_cache

    import boto3

    client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION"))
    response = client.get_secret_value(SecretId=secret_arn)
    _secrets_manager_url_cache = response["SecretString"]
    return _secrets_manager_url_cache


def get_database_url() -> str:
    secret_arn = os.environ.get("DATABASE_SECRET_ARN")
    url = _fetch_database_url_from_secrets_manager(secret_arn) if secret_arn else os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Neither DATABASE_SECRET_ARN nor DATABASE_URL is set. For local dev, "
            "point DATABASE_URL at your CockroachDB cluster, e.g.\n"
            "  cockroachdb+psycopg://<user>:<password>@<host>:26257/anamnesis"
            "?sslmode=verify-full\n"
            "In the deployed Lambda stack, DATABASE_SECRET_ARN is set automatically "
            "by infra/template.yaml."
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


def run_in_transaction(fn: Callable[[Session], T], audit_retries: bool = True) -> T:
    """Execute `fn(session)` as a single retryable unit of work.

    On a serialization conflict or lost connection, `fn` is called again
    from scratch with a brand-new Session — this is the primitive every
    mutating operation in `anamnesis/memory.py` uses, so a belief write,
    its contradiction check, and its audit row either all land together or
    the whole thing is safely retried, never partially applied.
    """
    get_engine()
    assert _SessionFactory is not None

    for attempt in Retrying(
        reraise=True,
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=2),
        retry=retry_if_exception(_is_retryable),
    ):
        with attempt:
            session = _SessionFactory()
            try:
                result = fn(session)
                session.commit()
                return result
            except Exception as exc:
                session.rollback()
                if _is_retryable(exc) and audit_retries:
                    _log_retry(exc)
                raise
            finally:
                session.close()

    raise AssertionError("unreachable: Retrying always raises or returns")


@contextmanager
def session_scope() -> Iterator[Session]:
    """Plain, non-retrying Session for read-only queries.

    Reads have no side effects to lose on a transient failure, so they
    don't need `run_in_transaction`'s redo-from-scratch guarantee — a
    caller that needs a retried read can simply call again.
    """
    get_engine()
    assert _SessionFactory is not None
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _log_retry(exc: BaseException) -> None:
    """Best-effort audit row for a retry, in its own tiny transaction."""
    from anamnesis.db.models import MemoryAudit

    try:
        with _SessionFactory() as s:  # type: ignore[misc]
            s.add(MemoryAudit(action="RETRY", reason=str(exc)[:500]))
            s.commit()
    except Exception:
        pass
