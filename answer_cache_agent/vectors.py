"""VectorStore protocol and the sqlite-vec implementation living in the application database."""
from __future__ import annotations

import sqlite3
from typing import Protocol, runtime_checkable

import sqlite_vec


@runtime_checkable
class VectorStore(Protocol):
    def upsert(self, item_id: str, scope_id: str, kind: str, model_id: str, vec: list[float]) -> None: ...
    def delete(self, item_id: str) -> None: ...
    def search(self, scope_id: str, kind: str, model_id: str, vec: list[float], k: int) -> list[tuple[str, float]]: ...


class SqliteVecStore:
    """vec0 table partitioned by scope; cosine distance; returns (item_id, similarity)."""

    TABLE = "vec_items"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @classmethod
    def create_table(cls, conn: sqlite3.Connection, dim: int) -> None:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {cls.TABLE} USING vec0("
            "  item_id TEXT PRIMARY KEY,"
            "  scope_id TEXT PARTITION KEY,"
            "  kind TEXT,"
            "  model_id TEXT,"
            f"  embedding FLOAT[{dim}] distance_metric=cosine"
            ")"
        )

    def upsert(self, item_id: str, scope_id: str, kind: str, model_id: str, vec: list[float]) -> None:
        self.delete(item_id)
        self.conn.execute(
            f"INSERT INTO {self.TABLE}(item_id, scope_id, kind, model_id, embedding) VALUES (?,?,?,?,?)",
            (item_id, scope_id, kind, model_id, sqlite_vec.serialize_float32(vec)),
        )

    def delete(self, item_id: str) -> None:
        self.conn.execute(f"DELETE FROM {self.TABLE} WHERE item_id = ?", (item_id,))

    def search(self, scope_id: str, kind: str, model_id: str, vec: list[float], k: int) -> list[tuple[str, float]]:
        rows = self.conn.execute(
            f"SELECT item_id, distance FROM {self.TABLE} "
            "WHERE embedding MATCH ? AND k = ? AND scope_id = ? AND kind = ? AND model_id = ? "
            "ORDER BY distance",
            (sqlite_vec.serialize_float32(vec), k, scope_id, kind, model_id),
        ).fetchall()
        return [(r[0], 1.0 - float(r[1])) for r in rows]
