# Nemotron Swarm Agent

A three-tier agentic Discord bot:

1. **Tier 1 — Local edge model:** `nemotron-mini` running in Ollama at `http://localhost:11434/v1`. Classifies every incoming task and handles simple ones directly.
2. **Tier 2 — Orchestration (this repo):** Node.js + `discord.js` listens for `@mentions`, opens a thread per response, persists conversation history in SQLite, and spawns Python skills as child processes.
3. **Tier 3 — Cloud reasoning:** NVIDIA NIM (`nvidia/nemotron-3-super-120b-a12b`) called via the OpenAI-compatible endpoint at `https://integrate.api.nvidia.com/v1`. NIM only — there is no fallback model; if NIM is unavailable the bot logs the error and posts a clean error message to Discord.

See [docs/setup.md](docs/setup.md) for full setup. TL;DR:

```bash
# 1. Install deps
npm install
python -m venv venv
venv\Scripts\activate           # PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Pull and warm up the local model
ollama pull nemotron-mini

# 3. Add credentials to .env (copy .env.example as a template)
#    DISCORD_BOT_TOKEN, NVIDIA_API_KEY

# 4. Start the bot
npm start
```

When the bot starts you should see:

```
[Bot] Logged in as <botname>
[Bot] Ollama reachable at http://localhost:11434/v1
[Bot] Ready.
```

`@mention` the bot in any text channel of your server. The bot opens a thread, classifies the request, and either answers locally or escalates to NVIDIA NIM.
