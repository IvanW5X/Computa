// ============================================================
// src/index.js
// ============================================================
// Role: Tier 2 — Orchestration (entry point)
// Purpose: Loads .env, reads config/model.json, builds the
//          Discord client, performs an Ollama health check at
//          startup, and logs the bot's ready state.
// Calls:   src/discord-handler.js (createClient),
//          config/model.json, Ollama at /api/tags.
// Used by: package.json `npm start` script.
// ============================================================

require('dotenv').config();

const fs = require('fs');
const path = require('path');

const { createClient } = require('./discord-handler');

const modelConfig = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'config', 'model.json'), 'utf8')
);

async function checkOllama(baseUrl) {
  const url = baseUrl.replace(/\/v1\/?$/, '') + '/api/tags';
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const models = (data.models || []).map((m) => m.name || m.model);
    if (modelConfig.model && !models.some((n) => n && n.startsWith(modelConfig.model))) {
      console.warn(
        `[Bot] Warning: model "${modelConfig.model}" not found in Ollama (loaded: ${models.join(', ') || 'none'}).`
      );
    }
    return true;
  } finally {
    clearTimeout(timeout);
  }
}

async function main() {
  const token = process.env.DISCORD_BOT_TOKEN;
  if (!token) {
    console.error(
      '[Bot] DISCORD_BOT_TOKEN is not set. Add it to .env (see .env.example) and restart.'
    );
    process.exit(1);
  }

  const client = createClient();

  client.once('ready', async () => {
    console.log(`[Bot] Logged in as ${client.user.tag}`);
    try {
      await checkOllama(modelConfig.baseUrl);
      console.log(`[Bot] Ollama reachable at ${modelConfig.baseUrl}`);
    } catch (e) {
      console.error(
        `[Bot] Ollama check failed at ${modelConfig.baseUrl}: ${e.message}. ` +
          'Local routing will fail until Ollama is running.'
      );
    }
    console.log('[Bot] Ready.');
  });

  client.on('error', (err) => console.error('[Bot] Client error:', err));
  client.on('shardError', (err) => console.error('[Bot] Shard error:', err));

  process.on('SIGINT', () => {
    console.log('[Bot] Shutting down...');
    client.destroy();
    process.exit(0);
  });

  await client.login(token);
}

main().catch((err) => {
  console.error('[Bot] Fatal error during startup:', err);
  process.exit(1);
});
