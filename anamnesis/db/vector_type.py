"""Minimal SQLAlchemy type for CockroachDB's VECTOR(n) columns.

We avoid depending on the pgvector package (which targets Postgres-specific
extension internals) since CockroachDB implements VECTOR natively. Values
are passed as Python lists of floats and rendered/read as the vector
literal syntax `[1,2,3]`.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dim: int):
        self.dim = dim

    def get_col_spec(self, **kw: Any) -> str:
        return f"VECTOR({self.dim})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            return "[" + ",".join(repr(float(v)) for v in value) + "]"

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, str):
                value = value.strip("[]")
                if not value:
                    return []
                return [float(v) for v in value.split(",")]
            return list(value)

        return process
