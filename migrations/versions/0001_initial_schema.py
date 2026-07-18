"""initial memory schema: episodic, semantic, audit, ops_log + vector indexes

Revision ID: 0001
Revises:
Create Date: 2026-07-18
"""
from __future__ import annotations

import re
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = (Path(__file__).parents[2] / "anamnesis" / "db" / "schema.sql").read_text()

DROP_SQL = """
DROP TABLE IF EXISTS ops_log;
DROP TABLE IF EXISTS memory_audit;
DROP TABLE IF EXISTS semantic_memory;
DROP TABLE IF EXISTS episodic_memory;
"""


def _strip_line_comments(sql: str) -> str:
    return "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())


def upgrade() -> None:
    for statement in _strip_line_comments(SCHEMA_SQL).split(";"):
        statement = statement.strip()
        if statement:
            op.execute(statement)


def downgrade() -> None:
    for statement in DROP_SQL.split(";"):
        statement = statement.strip()
        if statement:
            op.execute(statement)
