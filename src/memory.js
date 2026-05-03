// SQLite helper: saves user and assistant messages to data/memory.db, loads
// conversation history by session ID, and records per-turn token telemetry
// (local vs cloud vs counterfactual cloud-only baseline) for the dashboard.

const path = require("node:path");
const fs = require("node:fs");
const Database = require("better-sqlite3");

const DATA_DIR = path.resolve(__dirname, "..", "data");
const DB_PATH = path.join(DATA_DIR, "memory.db");

fs.mkdirSync(DATA_DIR, { recursive: true });

const db = new Database(DB_PATH);
db.pragma("journal_mode = WAL");

db.exec(`
  CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    session_id TEXT NOT NULL,
    user_msg TEXT NOT NULL,
    bot_reply TEXT NOT NULL,
    user_msg_tokens INTEGER NOT NULL DEFAULT 0,
    bot_reply_tokens INTEGER NOT NULL DEFAULT 0,
    local_prompt_tokens INTEGER NOT NULL DEFAULT 0,
    local_completion_tokens INTEGER NOT NULL DEFAULT 0,
    cloud_prompt_tokens INTEGER NOT NULL DEFAULT 0,
    cloud_completion_tokens INTEGER NOT NULL DEFAULT 0,
    escalated INTEGER NOT NULL DEFAULT 0,
    baseline_cloud_prompt_tokens INTEGER NOT NULL DEFAULT 0,
    baseline_cloud_completion_tokens INTEGER NOT NULL DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, ts);
`);

const insertTurnStmt = db.prepare(`
  INSERT INTO turns (
    ts, session_id, user_msg, bot_reply,
    user_msg_tokens, bot_reply_tokens,
    local_prompt_tokens, local_completion_tokens,
    cloud_prompt_tokens, cloud_completion_tokens,
    escalated,
    baseline_cloud_prompt_tokens, baseline_cloud_completion_tokens
  ) VALUES (
    @ts, @session_id, @user_msg, @bot_reply,
    @user_msg_tokens, @bot_reply_tokens,
    @local_prompt_tokens, @local_completion_tokens,
    @cloud_prompt_tokens, @cloud_completion_tokens,
    @escalated,
    @baseline_cloud_prompt_tokens, @baseline_cloud_completion_tokens
  )
`);

const historyStmt = db.prepare(`
  SELECT user_msg, bot_reply FROM turns
  WHERE session_id = ? ORDER BY ts ASC LIMIT ?
`);

function recordTurn(t) {
  // Counterfactual: what would a cloud-only pipeline have spent this turn?
  // The drafter assembles full raw history into local_prompt_tokens, so a
  // cloud-only setup would have to send that same context to the big model.
  // Caller can override with explicit baseline_* if it has a better estimate.
  const localPromptTokens = t.local_prompt_tokens | 0;
  const botReplyTokens = t.bot_reply_tokens | 0;
  const localCompletionTokens = t.local_completion_tokens | 0;

  const baselinePromptTokens =
    t.baseline_cloud_prompt_tokens != null
      ? Number(t.baseline_cloud_prompt_tokens)
      : localPromptTokens;
  const baselineCompletionTokens =
    t.baseline_cloud_completion_tokens != null
      ? Number(t.baseline_cloud_completion_tokens)
      : botReplyTokens || localCompletionTokens;

  const row = {
    ts: Date.now(),
    session_id: t.session_id,
    user_msg: t.user_msg ?? "",
    bot_reply: t.bot_reply ?? "",
    user_msg_tokens: t.user_msg_tokens | 0,
    bot_reply_tokens: botReplyTokens,
    local_prompt_tokens: localPromptTokens,
    local_completion_tokens: localCompletionTokens,
    cloud_prompt_tokens: t.cloud_prompt_tokens | 0,
    cloud_completion_tokens: t.cloud_completion_tokens | 0,
    escalated: t.escalated ? 1 : 0,
    baseline_cloud_prompt_tokens: baselinePromptTokens,
    baseline_cloud_completion_tokens: baselineCompletionTokens,
  };
  const info = insertTurnStmt.run(row);
  return { id: info.lastInsertRowid, ...row };
}

function getHistory(session_id, limit = 50) {
  return historyStmt.all(session_id, limit);
}

module.exports = { db, recordTurn, getHistory, DB_PATH };
