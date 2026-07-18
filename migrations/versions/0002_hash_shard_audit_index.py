"""hash-shard the memory_audit(at) index to avoid a hotspot on this
monotonically-increasing timestamp column, per CockroachDB's own
time-series indexing guidance.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-18
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS memory_audit_at_idx")
    op.execute(
        "CREATE INDEX IF NOT EXISTS memory_audit_at_idx "
        "ON memory_audit (at DESC) USING HASH WITH (bucket_count = 8)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS memory_audit_at_idx")
    op.execute("CREATE INDEX IF NOT EXISTS memory_audit_at_idx ON memory_audit (at DESC)")
