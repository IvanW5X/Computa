// ============================================================
// src/discord-handler.js
// ============================================================
// Role: Tier 2 — Orchestration
// Purpose: Builds the discord.js client, listens for
//          messageCreate events, ignores bots, only responds to
//          @mentions, opens a thread per response, sends typing,
//          persists turns to SQLite, and chunks replies over the
//          Discord 2000-char limit.
// Calls:   src/routing.js (classifyAndRoute, runPythonSkill),
//          src/memory.js (saveMessage, getHistory),
//          config/discord.json.
// Used by: src/index.js (via createClient()).
// ============================================================

const path = require('path');
const fs = require('fs');
const { Client, GatewayIntentBits, Partials, ChannelType } = require('discord.js');

const memory = require('./memory');
const { classifyAndRoute, runPythonSkill } = require('./routing');

const discordConfig = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'config', 'discord.json'), 'utf8')
);

const NIM_MODEL = 'nvidia/nemotron-3-super-120b-a12b';
const LOCAL_MODEL = 'nemotron-mini';
const CHUNK_SIZE = 1900;

function chunkText(text, size = CHUNK_SIZE) {
  const safe = String(text || '');
  if (safe.length <= size) return [safe];
  const out = [];
  let i = 0;
  while (i < safe.length) {
    out.push(safe.slice(i, i + size));
    i += size;
  }
  return out;
}

function stripMentions(content, clientUserId) {
  let cleaned = content || '';
  if (clientUserId) {
    const re = new RegExp(`<@!?${clientUserId}>`, 'g');
    cleaned = cleaned.replace(re, '');
  }
  return cleaned.replace(/<@!?\d+>/g, '').trim();
}

function makeThreadName(text) {
  const trimmed = (text || 'Conversation').replace(/\s+/g, ' ').trim();
  return trimmed.length > 90 ? `${trimmed.slice(0, 90)}…` : trimmed;
}

function createClient() {
  const client = new Client({
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildMessages,
      GatewayIntentBits.MessageContent,
    ],
    partials: [Partials.Message, Partials.Channel],
    presence: {
      status: 'online',
      activities: [{ name: 'COMPUTA!', type: 0 }],
    },
  });

  client.on('messageCreate', async (message) => {
    try {
      if (!message || message.author?.bot) return;
      if (!client.user || !message.mentions.has(client.user)) return;
      if (!message.guildId) return;

      const userContent = stripMentions(message.content, client.user.id);
      if (!userContent) return;

      let thread;
      const channel = message.channel;
      if (channel.isThread && channel.isThread()) {
        thread = channel;
      } else if (
        channel.type === ChannelType.GuildText ||
        channel.type === ChannelType.GuildAnnouncement
      ) {
        try {
          thread = await message.startThread({
            name: makeThreadName(userContent),
            autoArchiveDuration: discordConfig.autoArchiveMinutes || 60,
          });
        } catch (err) {
          console.error('[Discord] Could not create thread, replying inline:', err.message);
          thread = channel;
        }
      } else {
        thread = channel;
      }

      try {
        await thread.sendTyping();
      } catch (_) {
        /* ignore */
      }

      const sessionChannelId = thread?.id || channel.id;
      const sessionId = `${message.guildId}:${sessionChannelId}:${message.author.id}`;

      memory.saveMessage(sessionId, 'user', userContent);

      const classification = await classifyAndRoute(userContent);
      const history = memory.getHistory(sessionId, 10);

      let response;
      let modelUsed;

      if (classification.route === 'local') {
        console.log('[Skill] Running summarize_local.py...');
        response = await runPythonSkill('summarize_local.py', {
          message: userContent,
          history,
        });
        modelUsed = LOCAL_MODEL;
      } else {
        try {
          await thread.send('*Complex task detected — escalating to cloud Nemotron...*');
        } catch (_) {
          /* ignore */
        }
        console.log('[Skill] Running escalate_to_nim.py...');
        response = await runPythonSkill('escalate_to_nim.py', {
          message: userContent,
          history,
          classification,
        });
        console.log('[NIM] Response received');
        modelUsed = NIM_MODEL;
      }

      if (!response || !response.trim()) {
        response = '_The model returned an empty response. Please try rephrasing._';
      }

      memory.saveMessage(sessionId, 'assistant', response, modelUsed);

      const chunks = chunkText(response, CHUNK_SIZE);
      for (const piece of chunks) {
        await thread.send(piece);
      }
      console.log('[Discord] Response posted to thread');
    } catch (err) {
      console.error('[Discord] Error handling message:', err);
      try {
        await message.reply(
          'Something went wrong while processing your request. Check the bot logs for details.'
        );
      } catch (_) {
        /* ignore */
      }
    }
  });

  return client;
}

module.exports = { createClient, NIM_MODEL, LOCAL_MODEL };
