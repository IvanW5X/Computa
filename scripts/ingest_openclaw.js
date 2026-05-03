// Tails OpenClaw session JSONL files and posts each assistant turn to the
// Computa dashboard /log endpoint. Classifies provider=ollama as the local
// drafter; everything else (anthropic/openai/etc.) counts as cloud validator.
//
// Usage:
//   node scripts/ingest_openclaw.js              # one-shot ingest of new lines
//   node scripts/ingest_openclaw.js --watch      # poll every 2s
//
// Cursors per file are tracked in data/openclaw_cursors.json so re-runs only
// pick up new lines.

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const http = require("node:http");

const SESSIONS_DIR =
  process.env.OPENCLAW_SESSIONS_DIR ||
  path.join(os.homedir(), ".openclaw/agents/main/sessions");
const DASHBOARD_URL = process.env.COMPUTA_DASHBOARD_URL || "http://localhost:3000";

const DATA_DIR = path.resolve(__dirname, "..", "data");
const CURSOR_PATH = path.join(DATA_DIR, "openclaw_cursors.json");
const POSTED_PATH = path.join(DATA_DIR, "openclaw_posted_ids.json");

fs.mkdirSync(DATA_DIR, { recursive: true });

const watchMode = process.argv.includes("--watch");
const intervalMs = Number(process.env.INGEST_INTERVAL_MS || 2000);

function loadJson(p, fallback) {
  try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch { return fallback; }
}
function saveJson(p, v) { fs.writeFileSync(p, JSON.stringify(v, null, 2)); }

const cursors = loadJson(CURSOR_PATH, {});
const postedIds = new Set(loadJson(POSTED_PATH, []));

function isLocalProvider(provider, model) {
  const p = (provider || "").toLowerCase();
  const m = (model || "").toLowerCase();
  return p === "ollama" || m.includes("nemotron") || m.includes("llama") || p === "local";
}

function postTurn(payload) {
  return new Promise((resolve) => {
    const data = JSON.stringify(payload);
    const url = new URL(DASHBOARD_URL + "/log");
    const req = http.request(
      {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname,
        method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) },
      },
      (res) => {
        res.on("data", () => {});
        res.on("end", () => resolve(res.statusCode));
      }
    );
    req.on("error", (e) => {
      console.error("dashboard post failed:", e.message);
      resolve(0);
    });
    req.write(data);
    req.end();
  });
}

function parseSessionFile(filePath) {
  const sessionId = path.basename(filePath, ".jsonl");
  const stat = fs.statSync(filePath);
  const lastSize = cursors[filePath] || 0;
  if (stat.size <= lastSize) return [];

  const fd = fs.openSync(filePath, "r");
  const len = stat.size - lastSize;
  const buf = Buffer.alloc(len);
  fs.readSync(fd, buf, 0, len, lastSize);
  fs.closeSync(fd);
  cursors[filePath] = stat.size;

  const turns = [];
  // Build user message lookup so we can pair preceding user text to assistant.
  // To keep this simple and self-contained, do a full scan of the file each
  // time and only post assistant rows whose id we haven't posted yet.
  const allLines = fs.readFileSync(filePath, "utf8").split("\n").filter(Boolean);
  const byId = new Map();
  for (const line of allLines) {
    try {
      const o = JSON.parse(line);
      if (o.type === "message" && o.id) byId.set(o.id, o);
    } catch {}
  }

  for (const o of byId.values()) {
    const msg = o.message;
    if (!msg || msg.role !== "assistant") continue;
    if (postedIds.has(o.id)) continue;

    const usage = msg.usage || {};
    const inputTok = Number(usage.input || 0);
    const outputTok = Number(usage.output || 0);
    if (inputTok === 0 && outputTok === 0) continue;

    const provider = msg.provider || o.provider;
    const model = msg.model || o.model;
    const local = isLocalProvider(provider, model);

    const parent = o.parentId ? byId.get(o.parentId) : null;
    const parentMsg = parent && parent.message;
    const userText =
      parentMsg && parentMsg.role === "user"
        ? extractText(parentMsg.content) || ""
        : "";
    const botText = extractText(msg.content) || "";

    turns.push({
      id: o.id,
      session_id: sessionId,
      user_msg: userText.slice(0, 500),
      bot_reply: botText.slice(0, 500),
      user_msg_tokens: Math.ceil(userText.length / 4),
      bot_reply_tokens: outputTok,
      local_prompt_tokens: local ? inputTok : 0,
      local_completion_tokens: local ? outputTok : 0,
      cloud_prompt_tokens: local ? 0 : inputTok,
      cloud_completion_tokens: local ? 0 : outputTok,
      escalated: !local,
      // Cloud-only baseline pays the full input context every turn at cloud
      // rates. We approximate it with the input the drafter consumed, since
      // a cloud-only pipeline would need that same context.
      baseline_cloud_prompt_tokens: inputTok,
      baseline_cloud_completion_tokens: outputTok,
    });
  }
  return turns;
}

function extractText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((c) => c && c.type === "text" && typeof c.text === "string")
    .map((c) => c.text)
    .join("\n");
}

async function tickOnce() {
  if (!fs.existsSync(SESSIONS_DIR)) {
    console.error("sessions dir not found:", SESSIONS_DIR);
    return 0;
  }
  const files = fs
    .readdirSync(SESSIONS_DIR)
    .filter((f) => f.endsWith(".jsonl") && !f.includes("trajectory"))
    .map((f) => path.join(SESSIONS_DIR, f));

  let posted = 0;
  for (const file of files) {
    const turns = parseSessionFile(file);
    for (const t of turns) {
      const code = await postTurn(t);
      if (code >= 200 && code < 300) {
        postedIds.add(t.id);
        posted++;
      }
    }
  }
  saveJson(CURSOR_PATH, cursors);
  saveJson(POSTED_PATH, [...postedIds]);
  return posted;
}

async function main() {
  if (!watchMode) {
    const n = await tickOnce();
    console.log(`Posted ${n} turn(s).`);
    return;
  }
  console.log(`Watching ${SESSIONS_DIR} → ${DASHBOARD_URL} every ${intervalMs}ms`);
  while (true) {
    const n = await tickOnce();
    if (n > 0) console.log(`[${new Date().toLocaleTimeString()}] posted ${n} turn(s)`);
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
