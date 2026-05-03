// ============================================================
// src/memory.js
// ============================================================
// Role: Tier 2 — Orchestration (persistence layer)
// Purpose: better-sqlite3 helper that auto-creates data/memory.db
//          on first run and exposes saveMessage() / getHistory()
//          so the Discord handler can keep an OpenAI-compatible
//          messages array per session across turns.
// Calls:   data/memory.db (SQLite, schema created on import).
// Used by: src/discord-handler.js. Mirrors skills/memory.py,
//          which reads/writes the same database from Python.
// ============================================================

const path = require('path');
const fs = require('fs');
const Database = require('better-sqlite3');

const DATA_DIR = path.join(__dirname, '..', 'data');
const DB_PATH = path.join(DATA_DIR, 'memory.db');

if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

db.exec(`
  CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    model_used TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
`);

const insertStmt = db.prepare(
  'INSERT INTO messages (session_id, role, content, model_used) VALUES (?, ?, ?, ?)'
);

const historyStmt = db.prepare(
  'SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?'
);

function saveMessage(sessionId, role, content, modelUsed = null) {
  if (!sessionId || !role || content == null) return;
  insertStmt.run(String(sessionId), String(role), String(content), modelUsed || null);
}

function getHistory(sessionId, maxTurns = 10) {
  if (!sessionId) return [];
  const limit = Math.max(1, Number(maxTurns) || 10) * 2;
  const rows = historyStmt.all(String(sessionId), limit);
  return rows.reverse().map((r) => ({ role: r.role, content: r.content }));
}

module.exports = { saveMessage, getHistory, DB_PATH };
