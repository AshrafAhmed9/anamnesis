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

    def recall(self, query: str, k: int = 5) -> tuple[list[RecalledEpisode], list[Belief]]:
        """Vector-similarity recall of recent episodes + currently-held beliefs."""
        query_vec = self.llm.embed(query)
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
        never deleted, only superseded), which is what the four demo
        scenarios need and is robust to connection pooling. For true
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
        for its lifetime once `AS OF SYSTEM TIME` is used, and reusing a
        pooled connection across different `AS OF SYSTEM TIME` values in
        different transactions can otherwise conflict on some drivers.
        """
        from anamnesis.db.engine import get_engine

        asof_literal = as_of.astimezone(timezone.utc).isoformat()
        engine = get_engine()
        with engine.connect() as conn:
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
        return [Belief(*row) for row in rows]

    # ------------------------------------------------------ contradictions

    def detect_and_resolve_contradiction(
        self, new_belief_text: str, source_episode_ids: list[uuid.UUID]
    ) -> Belief:
        """Check a new candidate belief against currently-held beliefs.

        If it semantically contradicts an existing belief (nearby in
        embedding space + LLM confirms the contradiction), the old belief
        is superseded and the new one recorded — atomically, with audit.
        """
        new_vec = self.llm.embed(new_belief_text)

        def _do(db):
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

            contradicted: Belief | None = None
            for row in candidates:
                existing_embedding = _parse_vec_literal(row.embedding)
                dist = _cosine_distance(new_vec, existing_embedding)
                if dist < CONTRADICTION_SIM_THRESHOLD and self._llm_confirms_contradiction(
                    row.belief, new_belief_text
                ):
                    contradicted = Belief(row.id, row.belief, row.confidence, row.valid_from, row.valid_to, row.superseded_by)
                    break

            new_belief = SemanticMemory(
                belief=new_belief_text,
                embedding=new_vec,
                confidence=0.8,
                source_episodes=source_episode_ids,
            )
            db.add(new_belief)
            db.flush()

            if contradicted is not None:
                old = db.get(SemanticMemory, contradicted.id)
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
        """
        def _do(db):
            query = select(EpisodicMemory).where(
                EpisodicMemory.consolidated.is_(False),
                EpisodicMemory.salience < DECAY_SALIENCE_THRESHOLD + 0.5,
            )
            if session_id is not None:
                query = query.where(EpisodicMemory.session_id == session_id)
            episodes = db.execute(query.order_by(EpisodicMemory.created_at)).scalars().all()

            if len(episodes) < min_cluster_size:
                return []

            transcript = "\n".join(f"- ({e.role}) {e.content}" for e in episodes)
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
            belief = SemanticMemory(
                belief=summary,
                embedding=summary_vec,
                confidence=0.6,
                source_episodes=[e.id for e in episodes],
            )
            db.add(belief)
            db.flush()

            for e in episodes:
                e.consolidated = True
                e.salience = max(0.0, e.salience - 0.3)

            db.add(
                MemoryAudit(
                    action="CONSOLIDATE",
                    memory_id=belief.id,
                    reason=f"folded {len(episodes)} episodes into belief",
                    metadata_={"episode_ids": [str(e.id) for e in episodes]},
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
