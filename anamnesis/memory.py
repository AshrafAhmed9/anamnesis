"""Anamnesis: transactional, temporal, self-correcting agentic memory.

Public API: remember(), recall(), beliefs_asof(), consolidate(),
detect_and_resolve_contradiction().

Every write that changes what the agent believes happens inside a single
CockroachDB SERIALIZABLE transaction alongside its audit row, so memory
state and its audit trail can never diverge, and the whole unit of work is
retried from scratch on a serialization conflict or a lost connection
(see anamnesis.db.engine.run_in_transaction).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, text

from anamnesis.agent.bedrock import BedrockClient, ChatMessage, get_client
from anamnesis.db.engine import run_in_transaction, session_scope
from anamnesis.db.models import EpisodicMemory, MemoryAudit, SemanticMemory

DECAY_SALIENCE_THRESHOLD = 0.15
CONTRADICTION_SIM_THRESHOLD = 0.35  # cosine distance below which we ask the LLM to check


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 1.0
    return 1 - dot / (na * nb)


@dataclass
class RecalledEpisode:
    id: uuid.UUID
    content: str
    role: str
    created_at: datetime
    session_id: uuid.UUID


@dataclass
class Belief:
    id: uuid.UUID
    belief: str
    confidence: float
    valid_from: datetime
    valid_to: datetime | None
    superseded_by: uuid.UUID | None


class Anamnesis:
    """Facade over the memory layer for a single agent/tenant."""

    def __init__(self, llm: BedrockClient | None = None):
        self.llm = llm or get_client()

    # ---------------------------------------------------------------- write

    def remember(self, session_id: uuid.UUID, role: str, content: str) -> uuid.UUID:
        """Store a raw episodic event with its embedding. Audited."""
        embedding = self.llm.embed(content)

        def _do(db):
            episode = EpisodicMemory(
                session_id=session_id, role=role, content=content, embedding=embedding
            )
            db.add(episode)
            db.flush()
            db.add(MemoryAudit(action="WRITE", memory_id=episode.id, reason="episodic remember"))
            return episode.id

        return run_in_transaction(_do)

    # ----------------------------------------------------------------- read

    def recall(
        self, query: str, k: int = 5, stale_ok: bool = False
    ) -> tuple[list[RecalledEpisode], list[Belief]]:
        """Vector-similarity recall of recent episodes + currently-held beliefs.

        `stale_ok=True` uses CockroachDB follower reads
        (`AS OF SYSTEM TIME follower_read_timestamp()`, ~4.8s stale by
        default): the query is served by the nearest replica instead of
        requiring a round trip to the range's leaseholder, trading a few
        seconds of staleness for lower latency and less leaseholder load.
        Reasonable default for conversational recall, where "what did we
        talk about" doesn't need sub-second freshness; leave False for
        anything that must reflect a write from the last few seconds.
        """
        query_vec = self.llm.embed(query)

        if stale_ok:
            # AS OF SYSTEM TIME needs its own AUTOCOMMIT connection, not
            # the shared ORM session — see the identical fix and its
            # docstring on recall_as_of_system_time() below for why (a
            # pooled connection's pre-ping statement otherwise pins an
            # implicit transaction timestamp that conflicts with this).
            from anamnesis.db.engine import get_engine

            conn = get_engine().connect().execution_options(isolation_level="AUTOCOMMIT")
            try:
                episodes = conn.execute(
                    text(
                        """
                        SELECT id, content, role, created_at, session_id
                        FROM episodic_memory AS OF SYSTEM TIME follower_read_timestamp()
                        ORDER BY embedding <-> :qv
                        LIMIT :k
                        """
                    ),
                    {"qv": _vec_literal(query_vec), "k": k},
                ).fetchall()
                beliefs = conn.execute(
                    text(
                        """
                        SELECT id, belief, confidence, valid_from, valid_to, superseded_by
                        FROM semantic_memory AS OF SYSTEM TIME follower_read_timestamp()
                        WHERE valid_to IS NULL
                        ORDER BY embedding <-> :qv
                        LIMIT :k
                        """
                    ),
                    {"qv": _vec_literal(query_vec), "k": k},
                ).fetchall()
            finally:
                conn.invalidate()
        else:
            with session_scope() as db:
                episodes = db.execute(
                    text(
                        """
                        SELECT id, content, role, created_at, session_id
                        FROM episodic_memory
                        ORDER BY embedding <-> :qv
                        LIMIT :k
                        """
                    ),
                    {"qv": _vec_literal(query_vec), "k": k},
                ).fetchall()
                beliefs = db.execute(
                    text(
                        """
                        SELECT id, belief, confidence, valid_from, valid_to, superseded_by
                        FROM semantic_memory
                        WHERE valid_to IS NULL
                        ORDER BY embedding <-> :qv
                        LIMIT :k
                        """
                    ),
                    {"qv": _vec_literal(query_vec), "k": k},
                ).fetchall()

        return (
            [RecalledEpisode(*row) for row in episodes],
            [Belief(*row) for row in beliefs],
        )

    def beliefs_asof(self, query: str, as_of: datetime, k: int = 5) -> list[Belief]:
        """Time-travel recall: what did the agent believe at a point in time?

        This is *bitemporal* time-travel via the `valid_from`/`valid_to`
        validity-interval columns (application-level history — beliefs are
        never deleted, only superseded), which is what the demo scenarios
        need and is robust to connection pooling. For true
        MVCC-level system time-travel (recovering a row's exact historical
        physical state, or querying within CockroachDB's garbage-collection
        window regardless of application logic), use
        `recall_as_of_system_time()` below, which opens a dedicated
        connection scoped to a single `AS OF SYSTEM TIME` transaction as
        CockroachDB requires.
        """
        query_vec = self.llm.embed(query)
        with session_scope() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, belief, confidence, valid_from, valid_to, superseded_by
                    FROM semantic_memory
                    WHERE valid_from <= :asof AND (valid_to IS NULL OR valid_to > :asof)
                    ORDER BY embedding <-> :qv
                    LIMIT :k
                    """
                ),
                {"asof": as_of, "qv": _vec_literal(query_vec), "k": k},
            ).fetchall()
        return [Belief(*row) for row in rows]

    def recall_as_of_system_time(self, as_of: datetime, k: int = 20) -> list[Belief]:
        """True MVCC time-travel: read semantic_memory exactly as it
        physically existed at `as_of`, via CockroachDB `AS OF SYSTEM TIME`.

        Uses a fresh, dedicated connection (not the pooled session used
        elsewhere) because CockroachDB pins a transaction's read timestamp
        for its lifetime once `AS OF SYSTEM TIME` is used. The connection
        is explicitly invalidated after use (not just closed) so the pool
        never hands a later caller a connection carrying residual
        AS OF SYSTEM TIME state from a *different* timestamp — verified
        empirically: without this, a second call at a different `as_of`
        raised `FeatureNotSupported: inconsistent AS OF SYSTEM TIME
        timestamp` on the reused pooled connection.
        """
        from anamnesis.db.engine import get_engine

        asof_literal = as_of.astimezone(timezone.utc).isoformat()
        engine = get_engine()
        # AUTOCOMMIT: with the default transactional isolation level,
        # SQLAlchemy/psycopg's pool_pre_ping issues its own lightweight
        # statement on checkout, which — verified empirically — pins an
        # implicit transaction timestamp that then conflicts with our
        # explicit historical AS OF SYSTEM TIME on the very next
        # statement ("inconsistent AS OF SYSTEM TIME timestamp"), even on
        # a freshly checked-out connection. AUTOCOMMIT makes every
        # statement, including the pre-ping, its own independent
        # single-statement transaction, which avoids that.
        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            rows = conn.execute(
                text(
                    f"""
                    SELECT id, belief, confidence, valid_from, valid_to, superseded_by
                    FROM semantic_memory AS OF SYSTEM TIME '{asof_literal}'
                    ORDER BY valid_from DESC
                    LIMIT :k
                    """
                ),
                {"k": k},
            ).fetchall()
        finally:
            conn.invalidate()
        return [Belief(*row) for row in rows]

    # ------------------------------------------------------ contradictions

    def detect_and_resolve_contradiction(
        self, new_belief_text: str, source_episode_ids: list[uuid.UUID]
    ) -> Belief:
        """Check a new candidate belief against currently-held beliefs.

        If it semantically contradicts an existing belief (nearby in
        embedding space + LLM confirms the contradiction), the old belief
        is superseded and the new one recorded — atomically, with audit.

        The embedding call and the contradiction-judgment LLM call are both
        made *before* opening the write transaction — per CockroachDB's own
        application-transaction guidance, external network calls must not
        live inside a transaction body, since a retry would otherwise
        re-issue them (wasted latency/cost, and a non-deterministic LLM
        judgment could differ across retries). The transaction body only
        does deterministic reads/writes, so it's safe and cheap to redo
        from scratch on a retry.
        """
        new_vec = self.llm.embed(new_belief_text)

        with session_scope() as db:
            candidates = db.execute(
                text(
                    """
                    SELECT id, belief, confidence, valid_from, valid_to, superseded_by, embedding
                    FROM semantic_memory
                    WHERE valid_to IS NULL
                    ORDER BY embedding <-> :qv
                    LIMIT 3
                    """
                ),
                {"qv": _vec_literal(new_vec)},
            ).fetchall()

        is_contradiction = False
        for row in candidates:
            existing_embedding = _parse_vec_literal(row.embedding)
            dist = _cosine_distance(new_vec, existing_embedding)
            if dist < CONTRADICTION_SIM_THRESHOLD and self._llm_confirms_contradiction(
                row.belief, new_belief_text
            ):
                is_contradiction = True
                break

        def _do(db):
            new_belief = SemanticMemory(
                belief=new_belief_text,
                embedding=new_vec,
                confidence=0.8,
                source_episodes=source_episode_ids,
            )
            db.add(new_belief)
            db.flush()

            if is_contradiction:
                # Re-scan for ALL currently-active near-duplicate beliefs
                # inside this transaction — not just the one candidate the
                # pre-read outside the transaction happened to see — and
                # supersede every one of them. Under true concurrency
                # (multiple independent writers, not just retries of this
                # same call), other candidates can appear between the
                # pre-read and this write; trusting only the stale pre-read
                # id lets "at most one active belief" be violated (verified
                # by scripts/concurrency_test.py, which caught this as a
                # real bug before this fix). CockroachDB's SERIALIZABLE
                # isolation plus this in-transaction re-scan is what makes
                # "exactly one active belief" a real enforced invariant
                # rather than a best-effort check.
                # FOR UPDATE forces a real row lock on every currently-
                # active belief this transaction reads, so two concurrent
                # writers superseding the SAME existing belief genuinely
                # serialize (one blocks/retries) instead of relying on
                # CockroachDB's phantom-read detection, which — verified
                # empirically via scripts/concurrency_test.py — does NOT
                # catch this pattern for brand-new inserts that don't
                # overlap any existing row's lock.
                current_active = db.execute(
                    text(
                        """
                        SELECT id, embedding FROM semantic_memory
                        WHERE valid_to IS NULL AND id != :new_id
                        FOR UPDATE
                        """
                    ),
                    {"new_id": str(new_belief.id)},
                ).fetchall()
                for row in current_active:
                    dist = _cosine_distance(new_vec, _parse_vec_literal(row.embedding))
                    if dist < CONTRADICTION_SIM_THRESHOLD:
                        old = db.get(SemanticMemory, row.id)
                        old.valid_to = datetime.now(timezone.utc)
                        old.superseded_by = new_belief.id
                        db.add(
                            MemoryAudit(
                                action="SUPERSEDE",
                                memory_id=old.id,
                                reason=f"contradicted by new belief {new_belief.id}: {new_belief_text!r}",
                            )
                        )

            db.add(MemoryAudit(action="WRITE", memory_id=new_belief.id, reason="semantic belief recorded"))

            return Belief(
                new_belief.id, new_belief.belief, new_belief.confidence,
                new_belief.valid_from, new_belief.valid_to, new_belief.superseded_by,
            )

        return run_in_transaction(_do)

    def _llm_confirms_contradiction(self, old_belief: str, new_belief: str) -> bool:
        prompt = (
            f"Existing belief: {old_belief!r}\n"
            f"New statement: {new_belief!r}\n"
            "Does the new statement contradict or supersede the existing belief? "
            "Answer with exactly one word: YES or NO."
        )
        answer = self.llm.chat([ChatMessage(role="user", content=prompt)]).strip().upper()
        return answer.startswith("YES")

    # -------------------------------------------------------- consolidation

    def consolidate(self, session_id: uuid.UUID | None = None, min_cluster_size: int = 3) -> list[uuid.UUID]:
        """Fold low-salience, un-consolidated episodics into semantic beliefs.

        Groups un-consolidated episodes (optionally scoped to a session),
        asks the LLM to summarize each cluster into a belief statement, and
        writes the resulting semantic rows with provenance + audit — all in
        one transaction per cluster so a partial consolidation is never
        visible.

        Reading the candidate episodes and calling the LLM both happen
        before the write transaction opens, for the same reason as in
        `detect_and_resolve_contradiction`: a retried transaction must not
        re-issue an external LLM call. The write transaction re-filters to
        still-unconsolidated episodes so a race with a concurrent
        consolidation/decay is handled safely rather than assumed away.
        """
        with session_scope() as db:
            query = select(EpisodicMemory).where(
                EpisodicMemory.consolidated.is_(False),
                EpisodicMemory.salience < DECAY_SALIENCE_THRESHOLD + 0.5,
            )
            if session_id is not None:
                query = query.where(EpisodicMemory.session_id == session_id)
            episodes = db.execute(query.order_by(EpisodicMemory.created_at)).scalars().all()
            episode_ids = [e.id for e in episodes]
            transcript = "\n".join(f"- ({e.role}) {e.content}" for e in episodes)

        if len(episode_ids) < min_cluster_size:
            return []

        summary = self.llm.chat(
            [
                ChatMessage(
                    role="user",
                    content=(
                        "Summarize the following conversation snippets into one concise "
                        "belief statement about the user (a single sentence, factual, "
                        "no hedging):\n\n" + transcript
                    ),
                )
            ]
        ).strip()
        summary_vec = self.llm.embed(summary)

        def _do(db):
            current = db.execute(
                select(EpisodicMemory).where(
                    EpisodicMemory.id.in_(episode_ids), EpisodicMemory.consolidated.is_(False)
                )
            ).scalars().all()
            if len(current) < min_cluster_size:
                return []  # lost the race to a concurrent consolidation/decay

            belief = SemanticMemory(
                belief=summary,
                embedding=summary_vec,
                confidence=0.6,
                source_episodes=[e.id for e in current],
            )
            db.add(belief)
            db.flush()

            for e in current:
                e.consolidated = True
                e.salience = max(0.0, e.salience - 0.3)

            db.add(
                MemoryAudit(
                    action="CONSOLIDATE",
                    memory_id=belief.id,
                    reason=f"folded {len(current)} episodes into belief",
                    metadata_={"episode_ids": [str(e.id) for e in current]},
                )
            )
            return [belief.id]

        return run_in_transaction(_do)

    def decay(self, rate: float = 0.05) -> int:
        """Age out episodic salience; audit the sweep. Returns rows touched."""

        def _do(db):
            result = db.execute(
                text(
                    """
                    UPDATE episodic_memory
                    SET salience = GREATEST(0, salience - :rate)
                    WHERE consolidated = false
                    """
                ),
                {"rate": rate},
            )
            touched = result.rowcount
            db.add(MemoryAudit(action="DECAY", reason=f"salience -= {rate}", metadata_={"rows": touched}))
            return touched

        return run_in_transaction(_do)


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vec) + "]"


def _parse_vec_literal(value) -> list[float]:
    """Parse a VECTOR column value read back via a raw text() query.

    SQLAlchemy's Core `text()` queries don't apply column-type result
    processors (those require typed Core/ORM constructs), so CockroachDB's
    `[1,2,3]` vector literal comes back as a plain string here.
    """
    if isinstance(value, str):
        value = value.strip("[]")
        return [float(v) for v in value.split(",")] if value else []
    return list(value)
