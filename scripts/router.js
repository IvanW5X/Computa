// Three-tier router sidecar. Watches OpenClaw session JSONL for new USER
// messages, asks local Nemotron to score complexity, and if the score crosses
// the threshold, escalates to Gemini and logs the cloud turn to the dashboard.
//
// The local Nemotron reply is already produced by OpenClaw and ingested by
// scripts/ingest_openclaw.js. This router only adds the validator pass.
//
// Usage:
//   GOOGLE_API_KEY=... node scripts/router.js --watch
//
// Env:
//   GOOGLE_API_KEY                 - Gemini key. If absent, falls back to
//                                    OpenClaw auth-profiles.json.
//   COMPUTA_DASHBOARD_URL          - default http://localhost:3000
//   OLLAMA_URL                     - default http://127.0.0.1:11434
//   LOCAL_MODEL                    - default nemotron-mini:4b
//   CLOUD_MODEL                    - default gemini-2.5-flash
//   COMPLEXITY_THRESHOLD           - default 4 (1-5 scale)
//   ROUTER_INTERVAL_MS             - default 2000

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const http = require("node:http");

const SESSIONS_DIR =
  process.env.OPENCLAW_SESSIONS_DIR ||
  path.join(os.homedir(), ".openclaw/agents/main/sessions");
const DASHBOARD_URL = process.env.COMPUTA_DASHBOARD_URL || "http://localhost:3000";
const OLLAMA_URL = process.env.OLLAMA_URL || "http://127.0.0.1:11434";
const LOCAL_MODEL = process.env.LOCAL_MODEL || "nemotron-mini:4b";
const CLOUD_MODEL = process.env.CLOUD_MODEL || "gemini-2.5-flash";
const THRESHOLD = Number(process.env.COMPLEXITY_THRESHOLD || 4);
const INTERVAL_MS = Number(process.env.ROUTER_INTERVAL_MS || 2000);
const watchMode = process.argv.includes("--watch");

const DATA_DIR = path.resolve(__dirname, "..", "data");
const CURSOR_PATH = path.join(DATA_DIR, "router_cursors.json");
const PROCESSED_PATH = path.join(DATA_DIR, "router_processed.json");
fs.mkdirSync(DATA_DIR, { recursive: true });

function loadJson(p, fb) { try { return JSON.parse(fs.readFileSync(p,"utf8")); } catch { return fb; } }
function saveJson(p, v) { fs.writeFileSync(p, JSON.stringify(v, null, 2)); }

const cursors = loadJson(CURSOR_PATH, {});
const processed = new Set(loadJson(PROCESSED_PATH, []));

function getGoogleKey() {
  if (process.env.GOOGLE_API_KEY) return process.env.GOOGLE_API_KEY;
  try {
    const p = path.join(os.homedir(), ".openclaw/agents/main/agent/auth-profiles.json");
    const j = JSON.parse(fs.readFileSync(p, "utf8"));
    return j?.profiles?.["google:default"]?.key || null;
  } catch { return null; }
}
const GOOGLE_KEY = getGoogleKey();
if (!GOOGLE_KEY) {
  console.error("No Google API key (set GOOGLE_API_KEY or have OpenClaw google:default profile).");
  process.exit(1);
}

const CLASSIFIER_PROMPT = `You are a complexity router for an AI assistant. Score the user's incoming message on these axes:
- Multi-step reasoning required?
- Cross-source synthesis?
- Specialized domain (legal, medical, financial, advanced math, security, formal proofs)?
- Long-form generation that needs nuance?

Output ONLY valid minified JSON, no prose, no code fences:
{"complexity": <1-5>, "reason": "<one short sentence>", "draft_payload": "<concise restatement of intent + parameters the validator should focus on, max 60 words>"}

Scale: 1=trivial, 2=easy, 3=moderate, 4=hard, 5=very hard.`;

function postJson(url, body) {
  return new Promise((resolve, reject) => {
    const data = typeof body === "string" ? body : JSON.stringify(body);
    const u = new URL(url);
    const req = http.request(
      {
        hostname: u.hostname, port: u.port || 80, path: u.pathname + (u.search||""),
        method: "POST", headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) },
      },
      (res) => {
        let buf = "";
        res.on("data", (c) => (buf += c));
        res.on("end", () => resolve({ status: res.statusCode, body: buf }));
      }
    );
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

async function classify(userText) {
  // Ollama chat API
  const res = await postJson(`${OLLAMA_URL}/api/chat`, {
    model: LOCAL_MODEL,
    stream: false,
    messages: [
      { role: "system", content: CLASSIFIER_PROMPT },
      { role: "user", content: userText },
    ],
    options: { temperature: 0 },
  });
  const j = JSON.parse(res.body);
  const content = j?.message?.content || "";
  // Extract JSON object from possibly noisy output
  const match = content.match(/\{[\s\S]*\}/);
  if (!match) {
    return { complexity: 1, reason: "parser fallback", draft_payload: userText, raw: content,
             usage: { input: j.prompt_eval_count || 0, output: j.eval_count || 0 } };
  }
  let parsed;
  try { parsed = JSON.parse(match[0]); } catch {
    parsed = { complexity: 1, reason: "json parse failed", draft_payload: userText };
  }
  return {
    ...parsed,
    raw: content,
    usage: { input: j.prompt_eval_count || 0, output: j.eval_count || 0 },
  };
}

async function callGemini(draftPayload, originalText) {
  // Gemini REST API
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${CLOUD_MODEL}:generateContent?key=${GOOGLE_KEY}`;
  const body = {
    contents: [{
      role: "user",
      parts: [{
        text:
          `You are the validator/refiner in a drafter-validator pipeline. ` +
          `The local drafter prepared this distilled payload:\n\n${draftPayload}\n\n` +
          `Original user message:\n${originalText}\n\n` +
          `Produce the final, polished answer. Be concise.`,
      }],
    }],
  };
  // node fetch is built-in in node 18+
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const j = await res.json();
  if (!res.ok) throw new Error(`Gemini ${res.status}: ${JSON.stringify(j).slice(0,400)}`);
  const text =
    j?.candidates?.[0]?.content?.parts?.map((p) => p.text).filter(Boolean).join("\n") || "";
  const usage = j?.usageMetadata || {};
  return {
    text,
    input_tokens: usage.promptTokenCount || 0,
    output_tokens: usage.candidatesTokenCount || 0,
  };
}

function logTurn(payload) {
  return postJson(`${DASHBOARD_URL}/log`, payload).catch((e) => {
    console.error("dashboard log failed:", e.message);
    return null;
  });
}

function extractText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((c) => c && c.type === "text" && typeof c.text === "string")
    .map((c) => c.text).join("\n");
}

async function processSessionFile(filePath) {
  const sessionId = path.basename(filePath, ".jsonl");
  const stat = fs.statSync(filePath);
  const lastSize = cursors[filePath] || 0;
  if (stat.size <= lastSize) return 0;
  cursors[filePath] = stat.size;

  const lines = fs.readFileSync(filePath, "utf8").split("\n").filter(Boolean);
  let escalated = 0;
  for (const line of lines) {
    let o;
    try { o = JSON.parse(line); } catch { continue; }
    if (o.type !== "message" || !o.id) continue;
    const m = o.message;
    if (!m || m.role !== "user") continue;
    if (processed.has(o.id)) continue;
    processed.add(o.id);

    const userText = extractText(m.content) || "";
    if (!userText.trim()) continue;

    let cls;
    try { cls = await classify(userText); }
    catch (e) { console.error("classify error:", e.message); continue; }

    const score = Number(cls.complexity || 0);
    console.log(
      `[${new Date().toLocaleTimeString()}] msg=${o.id.slice(0,8)} score=${score} ${score>=THRESHOLD?"→ ESCALATE":""} :: ${userText.slice(0,80)}`
    );

    if (score >= THRESHOLD) {
      try {
        const cloud = await callGemini(cls.draft_payload || userText, userText);
        await logTurn({
          session_id: sessionId,
          user_msg: `[validator] ${userText}`.slice(0, 500),
          bot_reply: cloud.text.slice(0, 500),
          user_msg_tokens: Math.ceil(userText.length / 4),
          bot_reply_tokens: cloud.output_tokens,
          local_prompt_tokens: 0,
          local_completion_tokens: 0,
          cloud_prompt_tokens: cloud.input_tokens,
          cloud_completion_tokens: cloud.output_tokens,
          escalated: true,
          // Cloud-only baseline = if no drafter, cloud would have processed
          // the raw user text plus full history. We approximate with the
          // cloud-side prompt tokens (Gemini's promptTokenCount already
          // includes our draft + original text).
          baseline_cloud_prompt_tokens: cloud.input_tokens,
          baseline_cloud_completion_tokens: cloud.output_tokens,
        });
        escalated++;
      } catch (e) {
        console.error("escalation error:", e.message);
      }
    }
  }
  return escalated;
}

async function tickOnce() {
  if (!fs.existsSync(SESSIONS_DIR)) {
    console.error("sessions dir missing:", SESSIONS_DIR);
    return 0;
  }
  const files = fs.readdirSync(SESSIONS_DIR)
    .filter((f) => f.endsWith(".jsonl") && !f.includes("trajectory"))
    .map((f) => path.join(SESSIONS_DIR, f));

  let total = 0;
  for (const f of files) total += await processSessionFile(f);
  saveJson(CURSOR_PATH, cursors);
  saveJson(PROCESSED_PATH, [...processed]);
  return total;
}

async function main() {
  console.log(`Router up. local=${LOCAL_MODEL} cloud=${CLOUD_MODEL} threshold=${THRESHOLD}`);
  if (!watchMode) { const n = await tickOnce(); console.log(`Escalated ${n} turn(s).`); return; }
  console.log(`Watching ${SESSIONS_DIR} every ${INTERVAL_MS}ms`);
  while (true) {
    try { await tickOnce(); } catch (e) { console.error("tick error:", e.message); }
    await new Promise((r) => setTimeout(r, INTERVAL_MS));
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
