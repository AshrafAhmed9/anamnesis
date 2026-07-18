"""FastAPI app: chat endpoint + memory-introspection endpoints for the UI.

Runs standalone (`uvicorn app.main:app`) or wrapped for Lambda via Mangum
in app/lambda_handlers/api.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from anamnesis.agent.loop import Agent
from anamnesis.db.engine import session_scope
from anamnesis.memory import Anamnesis
from sqlalchemy import text

app = FastAPI(title="Anamnesis", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

_agents: dict[str, Agent] = {}


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str


class TimeTravelRequest(BaseModel):
    query: str
    as_of: datetime


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    agent = _agents.setdefault(session_id, Agent(session_id=uuid.UUID(session_id)))
    reply = agent.turn(req.message)
    return ChatResponse(session_id=session_id, reply=reply)


@app.get("/memory/beliefs")
def current_beliefs():
    with session_scope() as db:
        rows = db.execute(
            text(
                """
                SELECT id, belief, confidence, valid_from, valid_to, superseded_by
                FROM semantic_memory
                WHERE valid_to IS NULL
                ORDER BY valid_from DESC
                LIMIT 50
                """
            )
        ).fetchall()
    return [dict(r._mapping) for r in rows]


@app.get("/memory/audit")
def audit_stream(limit: int = 50):
    with session_scope() as db:
        rows = db.execute(
            text("SELECT id, action, memory_id, reason, at FROM memory_audit ORDER BY at DESC LIMIT :n"),
            {"n": limit},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


@app.post("/memory/asof")
def beliefs_asof(req: TimeTravelRequest):
    mem = Anamnesis()
    beliefs = mem.beliefs_asof(req.query, req.as_of)
    return [b.__dict__ for b in beliefs]


@app.post("/memory/consolidate")
def trigger_consolidation():
    mem = Anamnesis()
    ids = mem.consolidate()
    return {"consolidated_belief_ids": [str(i) for i in ids]}


@app.get("/health")
def health():
    return {"status": "ok"}
