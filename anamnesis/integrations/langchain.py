"""LangChain integration: back a conversation's message history with
Anamnesis instead of an in-memory list or a plain key-value store.

Targets `BaseChatMessageHistory` (langchain_core.chat_history), the
current, actively-maintained integration point in LangChain — NOT the
older `BaseMemory`/`ConversationBufferMemory` classes, which are removed
in current langchain-core (verified against langchain-core 1.4.9 while
building this: `langchain_core.memory` does not exist as of this version).

Using this doesn't just replay stored turns — every `add_message` goes
through Anamnesis's real write path (anamnesis.memory.Anamnesis.remember),
so a LangChain-orchestrated agent gets the same transactional,
audited, contradiction-aware memory as the demo app, not a parallel
lightweight implementation.

Install: pip install "anamnesis-crdb[langchain]" (or langchain-core
directly; this module has no other new runtime dependency).

Example:
    from anamnesis.integrations.langchain import AnamnesisChatMessageHistory

    history = AnamnesisChatMessageHistory(session_id=my_session_id)
    history.add_user_message("I prefer email over phone calls")
    history.add_ai_message("Got it, I'll note that.")
    print(history.messages)  # replayed from CockroachDB, not in-process state
"""
from __future__ import annotations

import uuid

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from anamnesis.db.engine import session_scope
from anamnesis.memory import Anamnesis
from sqlalchemy import text

_ROLE_TO_LANGCHAIN = {"user": HumanMessage, "agent": AIMessage}
_LANGCHAIN_TO_ROLE = {HumanMessage: "user", AIMessage: "agent"}


class AnamnesisChatMessageHistory(BaseChatMessageHistory):
    """Chat history for one session, persisted as Anamnesis episodic memory.

    Each `add_message` call is a real `Anamnesis.remember()` write —
    embedded, stored, and audited in CockroachDB — so this session's
    turns are immediately available to Anamnesis's own recall/
    contradiction-detection/consolidation pipeline, not siloed in a
    LangChain-only store.
    """

    def __init__(self, session_id: uuid.UUID | str, mem: Anamnesis | None = None):
        self.session_id = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
        self.mem = mem or Anamnesis()

    @property
    def messages(self) -> list[BaseMessage]:
        with session_scope() as db:
            rows = db.execute(
                text(
                    """
                    SELECT role, content FROM episodic_memory
                    WHERE session_id = :sid
                    ORDER BY created_at ASC
                    """
                ),
                {"sid": str(self.session_id)},
            ).fetchall()
        return [_ROLE_TO_LANGCHAIN.get(row.role, HumanMessage)(content=row.content) for row in rows]

    def add_message(self, message: BaseMessage) -> None:
        role = _LANGCHAIN_TO_ROLE.get(type(message), "user")
        self.mem.remember(self.session_id, role, message.content)

    def clear(self) -> None:
        # Deliberately not implemented as a hard delete: Anamnesis's whole
        # design is that memory writes are durable and audited, not
        # silently erasable by a caller — "clearing" a LangChain history
        # in the usual sense (wiping the record) would contradict that.
        # Consumers that need this should use the underlying `mem.decay()`
        # / a real data-retention process instead of a one-line clear().
        raise NotImplementedError(
            "AnamnesisChatMessageHistory does not support clear() — memory writes "
            "are durable and audited by design. Use Anamnesis.decay() or a real "
            "retention/deletion process if you need to age out data."
        )
