"""Tiny SQLite-backed goal store.

One SQLite file, one table, no ORM. Keeps the demo easy to read and easy to
reset (delete data/goals.db).
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id           TEXT PRIMARY KEY,
    identity     TEXT NOT NULL,
    title        TEXT NOT NULL,
    why          TEXT NOT NULL DEFAULT '',
    deadline     TEXT NOT NULL DEFAULT '',
    first_step   TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_goals_identity ON goals(identity);

CREATE TABLE IF NOT EXISTS check_ins (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    identity   TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_check_ins_identity
    ON check_ins(identity, created_at DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    goal = dict(row)
    goal["id"] = str(goal["id"])
    return goal


class GoalStore:
    """Thread-safe enough for a single-process demo.

    Each operation opens its own short-lived connection, which avoids
    sqlite3's cross-thread restrictions entirely.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ read

    def list(self, identity: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM goals
                WHERE identity = ?
                ORDER BY (status = 'done') ASC, created_at DESC
                """,
                (identity,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get(self, identity: str, goal_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM goals WHERE identity = ? AND id = ?",
                (identity, goal_id),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def identities(self) -> list[str]:
        """Every dreamer who has saved at least one goal."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT identity FROM goals ORDER BY identity"
            ).fetchall()
        return [str(row["identity"]) for row in rows]

    def active_goals(self, identity: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM goals
                WHERE identity = ? AND status = 'active'
                ORDER BY created_at ASC
                """,
                (identity,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    # ------------------------------------------------------------- reminders

    def add_check_in(self, identity: str, message: str) -> dict[str, Any]:
        created_at = _now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO check_ins (identity, message, created_at) VALUES (?, ?, ?)",
                (identity, message, created_at),
            )
            check_in_id = cur.lastrowid
        return {"id": check_in_id, "identity": identity, "message": message, "created_at": created_at}

    def list_check_ins(self, identity: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM check_ins
                WHERE identity = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (identity, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    # ----------------------------------------------------------------- write

    def add(
        self,
        identity: str,
        title: str,
        why: str = "",
        deadline: str = "",
        first_step: str = "",
    ) -> dict[str, Any]:
        goal_id = uuid.uuid4().hex[:10]
        created_at = _now()
        title = title.strip()
        if not title:
            raise ValueError("Goal title cannot be empty")

        with self._lock, self._connect() as conn:
            # If the same dreamer already has an active goal with this exact
            # title, update it instead of creating a duplicate.
            existing = conn.execute(
                """
                SELECT id FROM goals
                WHERE identity = ? AND status = 'active' AND lower(title) = lower(?)
                """,
                (identity, title),
            ).fetchone()
            if existing:
                goal_id = existing["id"]
                conn.execute(
                    """
                    UPDATE goals
                    SET title = ?, why = ?, deadline = ?, first_step = ?
                    WHERE id = ? AND identity = ?
                    """,
                    (title, why.strip(), deadline.strip(), first_step.strip(), goal_id, identity),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO goals
                        (id, identity, title, why, deadline, first_step, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
                    """,
                    (
                        goal_id,
                        identity,
                        title,
                        why.strip(),
                        deadline.strip(),
                        first_step.strip(),
                        created_at,
                    ),
                )

        goal = self.get(identity, goal_id)
        assert goal is not None
        return goal

    def complete(self, identity: str, goal_id: str) -> dict[str, Any] | None:
        completed_at = _now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE goals SET status = 'done', completed_at = ?
                WHERE id = ? AND identity = ? AND status != 'done'
                """,
                (completed_at, goal_id, identity),
            )
            if cur.rowcount == 0:
                return None
        return self.get(identity, goal_id)

    def complete_by_title(self, identity: str, title: str) -> dict[str, Any] | None:
        title = title.strip()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM goals
                WHERE identity = ? AND status = 'active'
                  AND (lower(title) = lower(?) OR lower(title) LIKE lower(?))
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (identity, title, f"%{title}%"),
            ).fetchone()
        if not row:
            return None
        return self.complete(identity, row["id"])

    def remove(self, identity: str, goal_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM goals WHERE id = ? AND identity = ?",
                (goal_id, identity),
            )
        return cur.rowcount > 0

    def remove_by_title(self, identity: str, title: str) -> dict[str, Any] | None:
        """Remove one goal by (partial) title. Returns the removed goal."""
        title = title.strip()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM goals
                WHERE identity = ?
                  AND (lower(title) = lower(?) OR lower(title) LIKE lower(?))
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (identity, title, f"%{title}%"),
            ).fetchone()
        if not row:
            return None
        goal = _row_to_dict(row)
        self.remove(identity, goal["id"])
        return goal
