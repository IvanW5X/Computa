// JSONL call log + non-blocking writer. Wraps OpenAI-compatible chat clients
// so every model call (local drafter or remote validator) appends one record.

const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");

const LOG_DIR = path.resolve(__dirname, "..", "logs");
const LOG_PATH = path.join(LOG_DIR, "calls.jsonl");

fs.mkdirSync(LOG_DIR, { recursive: true });

// Estimated completion length used in baseline cost — what the big model would
// have spent had we sent the prompt directly without local pre-processing.
const BASELINE_COMPLETION_TOKENS = 250;

let writeQueue = Promise.resolve();

function appendLine(obj) {
  const line = JSON.stringify(obj) + "\n";
  writeQueue = writeQueue
    .then(
      () =>
        new Promise((resolve) => {
          fs.appendFile(LOG_PATH, line, (err) => {
            if (err) console.error("[logger] write failed:", err.message);
            resolve();
          });
        })
    )
    .catch(() => {});
}

function newPromptId() {
  return randomUUID();
}

function preview(text) {
  if (!text) return "";
  const s = String(text).replace(/\s+/g, " ").trim();
  return s.length > 80 ? s.slice(0, 80) : s;
}

// Estimate tokens for arbitrary string when usage isn't returned. ~4 chars/token.
function estimateTokens(text) {
  if (!text) return 0;
  return Math.ceil(String(text).length / 4);
}

function logCall(record) {
  const row = {
    timestamp: new Date().toISOString(),
    prompt_id: record.prompt_id || newPromptId(),
    prompt_preview: preview(record.prompt_preview || ""),
    classification: record.classification || "unknown",
    route: record.route || "unknown",
    local_tokens_in: record.local_tokens_in | 0,
    local_tokens_out: record.local_tokens_out | 0,
    remote_tokens_in: record.remote_tokens_in | 0,
    remote_tokens_out: record.remote_tokens_out | 0,
    baseline_tokens_estimate: record.baseline_tokens_estimate | 0,
  };
  appendLine(row);
  return row;
}

// Wrap an OpenAI-compatible client so every chat.completions.create call
// returns the original response and emits a logger record. The wrapper
// itself never throws — log failures are swallowed.
function wrapChatClient(client, { role }) {
  if (!client?.chat?.completions?.create) {
    throw new Error("wrapChatClient: client missing chat.completions.create");
  }
  const orig = client.chat.completions.create.bind(client.chat.completions);
  client.chat.completions.create = async (params, opts) => {
    const res = await orig(params, opts);
    try {
      const userMsg =
        (params?.messages || [])
          .slice()
          .reverse()
          .find((m) => m.role === "user")?.content || "";
      const promptText =
        typeof userMsg === "string" ? userMsg : JSON.stringify(userMsg);
      const usage = res?.usage || {};
      const promptTok = usage.prompt_tokens | 0;
      const compTok = usage.completion_tokens | 0;
      const baseline =
        (promptTok || estimateTokens(promptText)) + BASELINE_COMPLETION_TOKENS;
      const isLocal = role === "local";
      logCall({
        prompt_id: params?._prompt_id, // optional pass-through for correlation
        prompt_preview: promptText,
        classification: params?._classification || "unknown",
        route: isLocal ? "local" : "escalated",
        local_tokens_in: isLocal ? promptTok : 0,
        local_tokens_out: isLocal ? compTok : 0,
        remote_tokens_in: isLocal ? 0 : promptTok,
        remote_tokens_out: isLocal ? 0 : compTok,
        baseline_tokens_estimate: baseline,
      });
    } catch (e) {
      console.error("[logger] wrap log failed:", e.message);
    }
    return res;
  };
  return client;
}

function readAllRecords() {
  if (!fs.existsSync(LOG_PATH)) return [];
  const txt = fs.readFileSync(LOG_PATH, "utf8");
  const out = [];
  for (const line of txt.split("\n")) {
    if (!line.trim()) continue;
    try {
      out.push(JSON.parse(line));
    } catch {}
  }
  return out;
}

module.exports = {
  LOG_PATH,
  BASELINE_COMPLETION_TOKENS,
  newPromptId,
  preview,
  estimateTokens,
  logCall,
  wrapChatClient,
  readAllRecords,
};
