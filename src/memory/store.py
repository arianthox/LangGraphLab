"""
memory/store.py — per-user conversation memory backed by SQLite.

The DB lives at ~/.langgraph_assistant/memory.db so it persists across
assistant restarts without any external service.

Public API
----------
init_db()                          — call once at startup
add_message(chat_id, role, text)   — persist a message
get_history(chat_id, limit)        — return last `limit` messages, oldest first
clear_history(chat_id)             — wipe a user's history
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".langgraph_assistant" / "memory.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)


def init_db() -> None:
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id   INTEGER NOT NULL,
                role      TEXT    NOT NULL,
                content   TEXT    NOT NULL,
                ts        DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_id ON messages (chat_id, ts)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id   INTEGER NOT NULL,
                text      TEXT    NOT NULL,
                remind_at DATETIME,
                done      INTEGER DEFAULT 0,
                created   DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    logger.info("Memory DB initialised at %s", DB_PATH)


def add_message(chat_id: int, role: str, content: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content),
        )


def get_history(chat_id: int, limit: int = 10) -> List[dict]:
    """Return the last `limit` messages in chronological order."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT role, content FROM messages
            WHERE chat_id = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def clear_history(chat_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
    logger.info("Cleared history for chat_id=%s", chat_id)


def add_reminder(chat_id: int, text: str, remind_at: str | None = None) -> int:
    """Store a reminder. Returns the new reminder ID."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (chat_id, text, remind_at) VALUES (?, ?, ?)",
            (chat_id, text, remind_at),
        )
        return cur.lastrowid


def list_reminders(chat_id: int) -> List[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, text, remind_at, created FROM reminders
            WHERE chat_id = ? AND done = 0
            ORDER BY created ASC
            """,
            (chat_id,),
        ).fetchall()
    return [
        {"id": r[0], "text": r[1], "remind_at": r[2], "created": r[3]}
        for r in rows
    ]


def mark_reminder_done(reminder_id: int) -> None:
    with _connect() as conn:
        conn.execute("UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,))
