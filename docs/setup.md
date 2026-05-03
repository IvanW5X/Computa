# Setup

## Prerequisites

- Node.js 20+
- Python 3.11+
- Ollama (https://ollama.com) running locally with the `nemotron-mini` model pulled
- A Discord bot application with the **Message Content Intent** enabled
- An NVIDIA API key from https://build.nvidia.com (required for escalation)

## Install Node dependencies

```bash
npm install
```

## Install Python dependencies

```bash
python -m venv venv
# PowerShell
venv\Scripts\Activate.ps1
# bash / zsh
source venv/bin/activate

pip install -r requirements.txt
```

The Node child-process layer auto-detects `venv/Scripts/python.exe` (Windows) or `venv/bin/python` (macOS/Linux); if neither exists it falls back to `python` / `python3` on PATH.

## Pull the local model

```bash
ollama pull nemotron-mini
ollama run nemotron-mini "warmup"   # optional warmup so the first response is fast
```

Verify the OpenAI-compatible endpoint:

```bash
curl http://localhost:11434/api/tags
```

## Configure credentials

Copy `.env.example` to `.env` and fill in real values:

```env
DISCORD_BOT_TOKEN=...
NVIDIA_API_KEY=nvapi-...
```

`data/memory.db` is created automatically on first run; the `data/` directory is git-ignored.

## Discord bot setup

1. https://discord.com/developers/applications → New Application → Bot → copy the token.
2. Under **Privileged Gateway Intents**, enable **Message Content Intent**.
3. OAuth2 → URL Generator → scopes `bot`, `applications.commands`. Bot permissions: Send Messages, Read Message History, Create Public Threads, Send Messages in Threads.
4. Invite the bot to your server with the generated URL.

## Run

```bash
npm start
```

Expected log lines:

```
[Bot] Logged in as <botname>
[Bot] Ollama reachable at http://localhost:11434/v1
[Bot] Ready.
```

Then `@mention` the bot in a server channel.
