// Local + remote OpenAI-compatible clients and the classify/route pipeline.
// Local: Nemotron Mini via Ollama. Remote: bigger Nemotron via NVIDIA NIM.
// Every call funnels through wrapChatClient so the JSONL log gets one row.

const OpenAI = require("openai");
const {
  wrapChatClient,
  logCall,
  newPromptId,
  preview,
  estimateTokens,
  BASELINE_COMPLETION_TOKENS,
} = require("./logger");

const LOCAL_BASE_URL = process.env.LOCAL_BASE_URL || "http://localhost:11434/v1";
const LOCAL_MODEL = process.env.LOCAL_MODEL || "nemotron-mini:4b";
const REMOTE_BASE_URL =
  process.env.REMOTE_BASE_URL || "https://integrate.api.nvidia.com/v1";
const REMOTE_MODEL =
  process.env.REMOTE_MODEL || "nvidia/llama-3.1-nemotron-70b-instruct";
const NVIDIA_API_KEY = process.env.NVIDIA_API_KEY || "";
const MOCK_MODE = process.env.MOCK_MODE === "1";

const localClient = wrapChatClient(
  new OpenAI({ baseURL: LOCAL_BASE_URL, apiKey: "ollama" }),
  { role: "local" }
);

const remoteClient = wrapChatClient(
  new OpenAI({
    baseURL: REMOTE_BASE_URL,
    apiKey: NVIDIA_API_KEY || "missing",
  }),
  { role: "remote" }
);

const CLASSIFIER_PROMPT = `You are a complexity classifier. Reply with EXACTLY one word: "simple" or "complex".

simple = small-talk, lookup, single-fact, short transformation, anything a 4B model can answer well.
complex = multi-step reasoning, specialized domain (legal/medical/finance/security/proofs/advanced math), long-form synthesis, anything where a tiny model would be unreliable.

Output: simple
or
Output: complex`;

const OPTIMIZER_PROMPT = `You compress the user's request into the tightest possible prompt for a larger validator model. Keep all intent and constraints. Drop chit-chat, repetition, and irrelevant context. Reply with ONLY the compressed prompt — no preamble.`;

function parseClassification(text) {
  const t = String(text || "").toLowerCase();
  if (/\bcomplex\b/.test(t)) return "complex";
  if (/\bsimple\b/.test(t)) return "simple";
  return "simple";
}

// Mock helper for offline demos. Produces deterministic-ish token counts so
// the dashboard has shape. Skipped when MOCK_MODE != "1".
function mockChat({ promptText, isComplex, role }) {
  const promptTok = estimateTokens(promptText);
  const compTok = isComplex ? 180 + (promptText.length % 80) : 40 + (promptText.length % 30);
  return {
    choices: [
      {
        message: {
          role: "assistant",
          content: isComplex
            ? `[mock ${role}] complex answer for: ${promptText.slice(0, 60)}`
            : `[mock ${role}] simple answer for: ${promptText.slice(0, 60)}`,
        },
      },
    ],
    usage: { prompt_tokens: promptTok, completion_tokens: compTok },
  };
}

async function classify(promptText, promptId) {
  if (MOCK_MODE) {
    const isComplex =
      /\b(prove|design|architect|legal|medical|derive|optimi[sz]e|migrate|compliance|theorem|algorithm|contract)\b/i.test(
        promptText
      ) || promptText.length > 220;
    const res = mockChat({ promptText, isComplex, role: "local" });
    logCall({
      prompt_id: promptId,
      prompt_preview: promptText,
      classification: isComplex ? "complex" : "simple",
      route: "local",
      local_tokens_in: res.usage.prompt_tokens,
      local_tokens_out: res.usage.completion_tokens,
      remote_tokens_in: 0,
      remote_tokens_out: 0,
      baseline_tokens_estimate:
        res.usage.prompt_tokens + BASELINE_COMPLETION_TOKENS,
    });
    return { classification: isComplex ? "complex" : "simple", reply: res.choices[0].message.content };
  }
  const res = await localClient.chat.completions.create({
    model: LOCAL_MODEL,
    messages: [
      { role: "system", content: CLASSIFIER_PROMPT },
      { role: "user", content: promptText },
    ],
    temperature: 0,
    max_tokens: 4,
    _prompt_id: promptId,
    _classification: "classifier",
  });
  return {
    classification: parseClassification(res.choices?.[0]?.message?.content),
    reply: res.choices?.[0]?.message?.content || "",
  };
}

async function answerLocal(promptText, promptId) {
  if (MOCK_MODE) {
    const res = mockChat({ promptText, isComplex: false, role: "local" });
    logCall({
      prompt_id: promptId,
      prompt_preview: promptText,
      classification: "simple",
      route: "local",
      local_tokens_in: res.usage.prompt_tokens,
      local_tokens_out: res.usage.completion_tokens,
      remote_tokens_in: 0,
      remote_tokens_out: 0,
      baseline_tokens_estimate:
        res.usage.prompt_tokens + BASELINE_COMPLETION_TOKENS,
    });
    return res.choices[0].message.content;
  }
  const res = await localClient.chat.completions.create({
    model: LOCAL_MODEL,
    messages: [
      { role: "system", content: "You are a concise local assistant." },
      { role: "user", content: promptText },
    ],
    temperature: 0.2,
    _prompt_id: promptId,
    _classification: "simple",
  });
  return res.choices?.[0]?.message?.content || "";
}

async function optimizeWithLocal(promptText, promptId) {
  if (MOCK_MODE) {
    const compressed = promptText.slice(0, Math.max(40, Math.floor(promptText.length * 0.4)));
    const res = mockChat({ promptText, isComplex: false, role: "local" });
    logCall({
      prompt_id: promptId,
      prompt_preview: promptText,
      classification: "complex",
      route: "local",
      local_tokens_in: res.usage.prompt_tokens,
      local_tokens_out: estimateTokens(compressed),
      remote_tokens_in: 0,
      remote_tokens_out: 0,
      baseline_tokens_estimate:
        res.usage.prompt_tokens + BASELINE_COMPLETION_TOKENS,
    });
    return compressed;
  }
  const res = await localClient.chat.completions.create({
    model: LOCAL_MODEL,
    messages: [
      { role: "system", content: OPTIMIZER_PROMPT },
      { role: "user", content: promptText },
    ],
    temperature: 0,
    _prompt_id: promptId,
    _classification: "complex",
  });
  return res.choices?.[0]?.message?.content?.trim() || promptText;
}

async function escalate(optimizedPrompt, promptId, originalPrompt) {
  if (MOCK_MODE) {
    const res = mockChat({ promptText: optimizedPrompt, isComplex: true, role: "remote" });
    logCall({
      prompt_id: promptId,
      prompt_preview: originalPrompt,
      classification: "complex",
      route: "escalated",
      local_tokens_in: 0,
      local_tokens_out: 0,
      remote_tokens_in: res.usage.prompt_tokens,
      remote_tokens_out: res.usage.completion_tokens,
      baseline_tokens_estimate:
        estimateTokens(originalPrompt) + BASELINE_COMPLETION_TOKENS,
    });
    return res.choices[0].message.content;
  }
  const res = await remoteClient.chat.completions.create({
    model: REMOTE_MODEL,
    messages: [
      { role: "system", content: "You are a careful expert assistant." },
      { role: "user", content: optimizedPrompt },
    ],
    temperature: 0.3,
    _prompt_id: promptId,
    _classification: "complex",
  });
  return res.choices?.[0]?.message?.content || "";
}

// Full pipeline: one user prompt in, final answer out, plus all telemetry rows.
async function routePrompt(userText) {
  const promptId = newPromptId();
  const cls = await classify(userText, promptId);
  if (cls.classification === "simple") {
    const answer = await answerLocal(userText, promptId);
    return { prompt_id: promptId, classification: "simple", route: "local", answer };
  }
  const optimized = await optimizeWithLocal(userText, promptId);
  const answer = await escalate(optimized, promptId, userText);
  return {
    prompt_id: promptId,
    classification: "complex",
    route: "escalated",
    optimized_prompt: optimized,
    answer,
  };
}

module.exports = {
  LOCAL_BASE_URL,
  LOCAL_MODEL,
  REMOTE_BASE_URL,
  REMOTE_MODEL,
  MOCK_MODE,
  localClient,
  remoteClient,
  classify,
  answerLocal,
  optimizeWithLocal,
  escalate,
  routePrompt,
};
