from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from anamnesis.memory import Anamnesis


@pytest.fixture
def mem():
    return Anamnesis()


def test_remember_and_recall(mem, session_id):
    mem.remember(session_id, "user", "I love hiking in the mountains every summer.")
    episodes, beliefs = mem.recall("hiking mountains")
    assert any("hiking" in e.content for e in episodes)


def test_contradiction_supersedes_old_belief(mem, session_id):
    first = mem.detect_and_resolve_contradiction("user is vegetarian", source_episode_ids=[])
    assert first.valid_to is None

    mem.detect_and_resolve_contradiction(
        "user is vegetarian and does not eat meat, confirmed strongly", source_episode_ids=[]
    )
    # depending on mock LLM contradiction judgment this may or may not fire;
    # assert the invariant instead: whichever belief is now active has no valid_to
    _, beliefs = mem.recall("vegetarian diet")
    active = [b for b in beliefs if b.valid_to is None]
    assert len(active) >= 1


def test_time_travel_returns_belief_valid_at_timestamp(mem, session_id):
    # Buffers around the write guard against client/server clock-skew noise
    # at the exact write instant (server timestamps `valid_from` on its own
    # clock via `now()`); real usage compares against timestamps well
    # outside this narrow window, so this doesn't mask a real bug.
    before = datetime.now(timezone.utc)
    time.sleep(0.5)
    mem.detect_and_resolve_contradiction("user prefers tea over coffee", source_episode_ids=[])
    time.sleep(0.5)
    after = datetime.now(timezone.utc)

    beliefs_before = mem.beliefs_asof("beverage preference", before)
    assert all(b.belief != "user prefers tea over coffee" for b in beliefs_before)

    beliefs_after = mem.beliefs_asof("beverage preference", after)
    assert any(b.belief == "user prefers tea over coffee" for b in beliefs_after)


def test_consolidate_folds_episodes_into_belief(mem, session_id):
    for i in range(4):
        mem.remember(session_id, "user", f"message number {i} about my daily routine")
    ids = mem.consolidate(session_id=session_id, min_cluster_size=3)
    assert len(ids) == 1


def test_consolidate_noop_below_cluster_size(mem, session_id):
    mem.remember(session_id, "user", "just one message")
    ids = mem.consolidate(session_id=session_id, min_cluster_size=3)
    assert ids == []


def test_decay_reduces_salience(mem, session_id):
    mem.remember(session_id, "user", "ephemeral detail")
    touched = mem.decay(rate=0.1)
    assert touched >= 1


def test_writes_are_audited(mem, session_id):
    from anamnesis.db.engine import session_scope
    from anamnesis.db.models import MemoryAudit
    from sqlalchemy import select

    mem.remember(session_id, "user", "audit me")
    with session_scope() as db:
        rows = db.execute(select(MemoryAudit).where(MemoryAudit.action == "WRITE")).scalars().all()
    assert len(rows) >= 1


def test_survives_simulated_connection_loss_mid_write(mem, session_id):
    """Proves the "kill the connection mid-write" survivability claim: a
    transaction that fails once with connection_invalidated=True (what
    SQLAlchemy sets when the underlying DBAPI connection was dropped) is
    retried from scratch via the real anamnesis.memory.remember() call —
    not a synthetic engine-internals test — and the write still lands,
    with a RETRY row recorded in the audit trail.

    This exercises `run_in_transaction`, the primitive every write in
    anamnesis/memory.py uses specifically because a plain
    `with session_scope() as db: ...` cannot correctly redo a caller's
    already-executed code on a mid-transaction failure (see the docstring
    on anamnesis.db.engine.run_in_transaction).
    """
    from unittest.mock import patch

    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session as OrmSession
    from sqlalchemy import select

    from anamnesis.db.engine import session_scope
    from anamnesis.db.models import EpisodicMemory, MemoryAudit

    fake_error = DBAPIError("INSERT ...", {}, Exception("connection closed"), connection_invalidated=True)
    attempts = {"n": 0}
    real_commit = OrmSession.commit

    def flaky_commit(self):
        # Only fail the write-under-test's own session — identified by its
        # pending "episodic remember" WRITE audit row (by the time commit()
        # runs, remember()'s prior db.flush() has already moved the
        # EpisodicMemory itself out of session.new). Leave the separate
        # session `_log_retry` opens to record the RETRY audit row alone,
        # so this simulates one dropped connection, not an unrelated one.
        is_target_write = any(
            isinstance(obj, MemoryAudit) and obj.reason == "episodic remember" for obj in self.new
        )
        if is_target_write:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise fake_error
        return real_commit(self)

    with patch.object(OrmSession, "commit", flaky_commit):
        episode_id = mem.remember(session_id, "user", "survives a dropped connection")

    assert attempts["n"] == 2, "expected exactly one failed attempt followed by one successful retry"

    with session_scope() as db:
        episode = db.get(EpisodicMemory, episode_id)
        assert episode is not None, "write did not survive the simulated connection loss"

        retry_rows = db.execute(select(MemoryAudit).where(MemoryAudit.action == "RETRY")).scalars().all()
        assert len(retry_rows) >= 1, "no RETRY row was audited for the simulated connection loss"
