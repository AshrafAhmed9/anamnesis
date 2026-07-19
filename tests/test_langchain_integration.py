from __future__ import annotations

import pytest

pytest.importorskip("langchain_core", reason="langchain integration is optional (pip install anamnesis-crdb[langchain])")


def test_add_and_read_messages_round_trips_through_real_anamnesis_writes(session_id):
    from anamnesis.integrations.langchain import AnamnesisChatMessageHistory

    history = AnamnesisChatMessageHistory(session_id=session_id)
    history.add_user_message("I prefer email over phone calls")
    history.add_ai_message("Got it, noted.")

    messages = history.messages
    assert len(messages) == 2
    assert messages[0].content == "I prefer email over phone calls"
    assert messages[0].__class__.__name__ == "HumanMessage"
    assert messages[1].content == "Got it, noted."
    assert messages[1].__class__.__name__ == "AIMessage"


def test_messages_are_real_anamnesis_episodic_writes(session_id):
    """Not a parallel store — verify the messages actually landed in
    episodic_memory via the normal Anamnesis.remember() path, auditable
    the same way any other write is.
    """
    from anamnesis.db.engine import session_scope
    from anamnesis.integrations.langchain import AnamnesisChatMessageHistory
    from sqlalchemy import text

    history = AnamnesisChatMessageHistory(session_id=session_id)
    history.add_user_message("integration test marker message")

    with session_scope() as db:
        row = db.execute(
            text("SELECT content FROM episodic_memory WHERE session_id = :sid"),
            {"sid": str(session_id)},
        ).fetchone()
    assert row is not None
    assert row.content == "integration test marker message"


def test_clear_is_deliberately_unsupported(session_id):
    from anamnesis.integrations.langchain import AnamnesisChatMessageHistory

    history = AnamnesisChatMessageHistory(session_id=session_id)
    with pytest.raises(NotImplementedError):
        history.clear()
