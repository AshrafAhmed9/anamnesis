"""A minimal, deliberately naive vector-store-only memory, for the
benchmark in scripts/benchmark.py. This is what "bolt a vector store onto
an agent and call it memory" looks like in practice: every statement is
embedded and stored in one flat table; recall is nearest-neighbor search;
there is no concept of a statement being superseded, no validity interval,
and therefore no way to answer "what's true now" versus "what was ever
said" other than "most similar to the query." This is the baseline
Anamnesis's design is compared against.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text

from anamnesis.agent.bedrock import BedrockClient
from anamnesis.db.engine import run_in_transaction, session_scope
from anamnesis.db.models import Base
from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from anamnesis.db.vector_type import Vector

EMBEDDING_DIM = 1024


class NaiveMemoryRow(Base):
    __tablename__ = "naive_vector_memory"
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic = Column(String, nullable=False)
    content = Column(String, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


@dataclass
class NaiveResult:
    content: str
    created_at: datetime


class NaiveVectorMemory:
    """Embed-and-store-everything baseline: no consolidation, no
    contradiction handling, no validity intervals. `current_answer()`
    returns the single nearest neighbor by embedding distance, which is
    the closest a pure vector store can get to "what do you believe now."
    """

    def __init__(self, llm: BedrockClient):
        self.llm = llm

    def remember(self, topic: str, content: str) -> None:
        embedding = self.llm.embed(content)

        def _do(db):
            db.add(NaiveMemoryRow(topic=topic, content=content, embedding=embedding))

        run_in_transaction(_do)

    def current_answer(self, query: str) -> NaiveResult | None:
        """The best a naive vector store can do for "what's true now":
        the single nearest neighbor to the query. No mechanism exists to
        prefer a newer statement over an older, semantically-similar one.
        """
        query_vec = self.llm.embed(query)
        with session_scope() as db:
            row = db.execute(
                text(
                    """
                    SELECT content, created_at FROM naive_vector_memory
                    ORDER BY embedding <-> :qv LIMIT 1
                    """
                ),
                {"qv": "[" + ",".join(repr(float(v)) for v in query_vec) + "]"},
            ).fetchone()
        return NaiveResult(row.content, row.created_at) if row else None

    def asof(self, query: str, as_of: datetime) -> NaiveResult | None:
        """A naive vector store has no validity intervals, so it cannot
        answer a time-travel query at all — the honest baseline behavior
        is that it can only ever return "the current nearest match,"
        regardless of `as_of`. Included so the benchmark can score this
        as a structural miss, not silently skip it.
        """
        return self.current_answer(query)
