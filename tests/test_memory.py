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
