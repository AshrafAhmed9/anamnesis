"""The demo agent: a chat loop that reads/writes through Anamnesis memory."""
from __future__ import annotations

import uuid

from anamnesis.agent.bedrock import ChatMessage, get_client
from anamnesis.memory import Anamnesis

SYSTEM_PROMPT = """You are a helpful personal assistant with persistent memory.
You are given relevant past episodes and currently-held beliefs about the user
before each reply. Use them naturally; cite when you learned something if it's
relevant ("you mentioned this on ..."). If the user says something that seems
to contradict a belief you hold, ask a clarifying question instead of just
overwriting it silently."""

BELIEF_EXTRACTION_PROMPT = """Given this user message, does it state a durable
fact, preference, or belief about the user that's worth remembering long-term
(e.g. dietary restriction, preference, recurring fact)? If yes, respond with
just the belief as a short factual sentence. If no, respond with exactly: NONE

User message: {message}"""


class Agent:
    def __init__(self, session_id: uuid.UUID | None = None):
        self.session_id = session_id or uuid.uuid4()
        self.memory = Anamnesis()
        self.llm = get_client()

    def turn(self, user_message: str) -> str:
        self.memory.remember(self.session_id, "user", user_message)

        episodes, beliefs = self.memory.recall(user_message, k=5)
        context_lines = []
        if beliefs:
            context_lines.append("Currently held beliefs about the user:")
            context_lines += [f"- {b.belief} (confidence {b.confidence:.2f})" for b in beliefs]
        if episodes:
            context_lines.append("Relevant past episodes:")
            context_lines += [f"- [{e.created_at}] ({e.role}) {e.content}" for e in episodes]
        context = "\n".join(context_lines) or "(no memory yet)"

        reply = self.llm.chat(
            [ChatMessage(role="user", content=f"{context}\n\nUser: {user_message}")],
            system=SYSTEM_PROMPT,
        )
        self.memory.remember(self.session_id, "agent", reply)

        self._maybe_extract_belief(user_message)
        return reply

    def _maybe_extract_belief(self, user_message: str) -> None:
        candidate = self.llm.chat(
            [ChatMessage(role="user", content=BELIEF_EXTRACTION_PROMPT.format(message=user_message))]
        ).strip()
        if candidate and candidate.upper() != "NONE":
            self.memory.detect_and_resolve_contradiction(candidate, source_episode_ids=[])
