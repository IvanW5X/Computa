# ============================================================
# skills/memory.py
# ============================================================
# Role: Tier 2 — Orchestration (Python-side persistence)
# Purpose: SQLite helpers for skill scripts. Auto-creates
#          data/memory.db with the same schema as src/memory.js
#          so Python skills can read/write conversation history
#          using the same database file the Node layer uses.
# Calls:   data/memory.db (SQLite, schema created on connect).
# Used by: any skill that needs to load or persist history
#          directly from Python; mirrors src/memory.js.
# ============================================================
"""SQLite helpers for skill scripts. Mirrors src/memory.js."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "memory.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    model_used TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(_SCHEMA)
    return conn


def save_message(
    session_id: str,
    role: str,
    content: str,
    model_used: Optional[str] = None,
) -> None:
    if not session_id or not role or content is None:
        return
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, model_used) VALUES (?, ?, ?, ?)",
            (str(session_id), str(role), str(content), model_used),
        )
        conn.commit()


def get_history(session_id: str, max_turns: int = 10) -> list[dict]:
    if not session_id:
        return []
    limit = max(1, int(max_turns or 10)) * 2
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (str(session_id), limit),
        ).fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]
