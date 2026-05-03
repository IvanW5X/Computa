# Nemotron Swarm Agent — Complete Technical Implementation Guide

> **Hackathon Track:** NVIDIA "Best Use of Nemotron"  
> **Architecture:** OpenClaw → Ollama → Nemotron 4B (local) ↗ NVIDIA NIM Cloud Nemotron (escalation)  
> **Deployment:** Discord-native agentic pipeline

---

## Table of Contents

1. [Complete Tool and Dependency List](#1-complete-tool-and-dependency-list)
2. [Environment Setup](#2-environment-setup)
3. [Complexity Classification System](#3-complexity-classification-system)
4. [Escalation Payload Design](#4-escalation-payload-design)
5. [OpenClaw Skill Integration](#5-openclaw-skill-integration)
6. [Cloud Model Integration](#6-cloud-model-integration)
7. [Memory and Context Management](#7-memory-and-context-management)
8. [Discord Bot Configuration](#8-discord-bot-configuration)
9. [End-to-End Demo Scenario](#9-end-to-end-demo-scenario)
10. [Architecture Diagram](#10-architecture-diagram)
11. [Potential Failure Points and Mitigations](#11-potential-failure-points-and-mitigations)
12. [What Makes This Competitive for the NVIDIA Track](#12-what-makes-this-competitive-for-the-nvidia-track)

---

## 1. Complete Tool and Dependency List

### Local Environment

| Tool | Version | Purpose |
|------|---------|---------|
| Ollama | ≥ 0.3.x | Local model runtime; serves Nemotron 4B via OpenAI-compatible API |
| OpenClaw | latest (GitHub) | Agent framework; Discord integration, routing, memory, skill execution |
| Python | 3.11+ | Skill scripts, escalation logic |
| Node.js | 20 LTS | OpenClaw runtime |
| Git | any | Cloning OpenClaw and managing skills |
| curl | any | Verifying Ollama endpoint |

### Model

| Model | Source | Pull Command |
|-------|--------|-------------|
| Nemotron 4B | Ollama registry | `ollama pull nemotron-mini` |

> **Note:** The Ollama registry name for NVIDIA Nemotron 4B is `nemotron-mini`. Verify current tag at https://ollama.com/library/nemotron-mini before pulling.

### Python Packages (for skill scripts)

```
httpx>=0.27.0          # Async HTTP client for NIM API calls
openai>=1.30.0         # OpenAI-compatible client (works with both Ollama and NIM)
python-dotenv>=1.0.0   # Load .env credentials in skill scripts
pydantic>=2.0          # Payload validation
```

Install all at once:
```bash
pip install httpx openai python-dotenv pydantic
```

### Node Packages (installed by OpenClaw)

OpenClaw manages its own Node dependencies. After cloning:
```bash
cd openclaw && npm install
```
Key packages OpenClaw pulls in: `discord.js ≥14`, `openai`, `sqlite3` (for memory persistence).

### External APIs and Credentials

| Credential | Where to get it | Environment variable |
|-----------|----------------|---------------------|
| Discord Bot Token | Discord Developer Portal → New Application → Bot | `DISCORD_BOT_TOKEN` |
| Discord Guild ID | Discord → right-click server → Copy Server ID | `DISCORD_GUILD_ID` |
| NVIDIA API Key (NIM) | https://build.nvidia.com → Sign in → Get API Key | `NVIDIA_API_KEY` |

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM | 8 GB | 16 GB |
| VRAM | 4 GB (for 4B quantized) | 8 GB |
| GPU | NVIDIA GPU with CUDA 12+ | RTX 3080 / RTX 4070 or better |
| Disk | 10 GB free | 20 GB free |
| OS | Ubuntu 22.04 / macOS 14 / Windows 11 WSL2 | Ubuntu 22.04 |

> Ollama will fall back to CPU inference if no compatible GPU is detected. CPU inference for Nemotron 4B is ~5–10x slower but functional for development.

---

## 2. Environment Setup

### Step 1: Install Ollama

**Linux / WSL2:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**macOS:**
```bash
brew install ollama
```

**Verify the daemon is running:**
```bash
ollama serve &   # starts in background if not already running
curl http://localhost:11434/api/tags
# Expected: {"models":[...]}
```

### Step 2: Pull Nemotron 4B into Ollama

```bash
ollama pull nemotron-mini
```

Verify the model loaded correctly:
```bash
ollama run nemotron-mini "Hello, respond with one sentence."
```

Expected: a short response printed to stdout. Exit with `/bye`.

### Step 3: Verify Ollama's OpenAI-Compatible Endpoint

This is the endpoint OpenClaw will call:
```bash
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nemotron-mini",
    "messages": [{"role": "user", "content": "What is 2+2?"}]
  }'
```

Expected: a JSON response with `choices[0].message.content` containing the answer. If this works, Tier 1 of the stack is operational.

### Step 4: Clone and Install OpenClaw

```bash
git clone https://github.com/openclaw-ai/openclaw.git
cd openclaw
npm install
```

> **Note:** If the OpenClaw repository URL has changed, check the project's official documentation. The framework is open source and Discord integration is built in.

### Step 5: Configure OpenClaw to Point at Ollama

In the OpenClaw project root, create or edit `config/model.json`:

```json
{
  "provider": "ollama",
  "baseUrl": "http://localhost:11434/v1",
  "model": "nemotron-mini",
  "apiKey": "ollama",
  "temperature": 0.3,
  "maxTokens": 2048
}
```

> `apiKey: "ollama"` is a placeholder — Ollama's local endpoint does not require authentication, but the OpenAI client library requires the field to be non-empty.

### Step 6: Create the Discord Bot

1. Go to https://discord.com/developers/applications
2. Click **New Application** → name it `Nemotron Swarm Agent`
3. Navigate to **Bot** → click **Add Bot**
4. Under **Privileged Gateway Intents**, enable:
   - **Message Content Intent**
   - **Server Members Intent**
5. Copy the bot token and save it as `DISCORD_BOT_TOKEN`
6. Navigate to **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Read Message History`, `Create Public Threads`, `Send Messages in Threads`, `Use Slash Commands`
7. Open the generated URL in a browser and invite the bot to your server
8. Right-click your Discord server → **Copy Server ID** → save as `DISCORD_GUILD_ID`

### Step 7: Wire OpenClaw to Discord

Create `config/discord.json`:

```json
{
  "token": "${DISCORD_BOT_TOKEN}",
  "guildId": "${DISCORD_GUILD_ID}",
  "channelName": "nemotron-agent",
  "threadMode": true,
  "commandPrefix": "/"
}
```

Create a `.env` file in the project root:

```env
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_GUILD_ID=your_guild_id_here
NVIDIA_API_KEY=your_nvidia_api_key_here
```

### Step 8: Get an NVIDIA API Key for NIM

1. Go to https://build.nvidia.com
2. Sign in with (or create) an NVIDIA Developer account
3. Navigate to any hosted Nemotron model page (e.g., `nvidia/llama-3.1-nemotron-70b-instruct`)
4. Click **Get API Key** → copy the key
5. Save it as `NVIDIA_API_KEY` in your `.env` file

Free tier: NVIDIA provides a limited number of free API calls per month on build.nvidia.com — enough for development and demo use.

### Step 9: Start OpenClaw

```bash
npm run start
```

Expected output:
```
[OpenClaw] Connected to Discord as NemotronSwarmAgent#1234
[OpenClaw] Model provider: ollama @ http://localhost:11434/v1
[OpenClaw] Skills loaded: 3
[OpenClaw] Ready.
```

---

## 3. Complexity Classification System

### System Prompt for Nemotron 4B (Complexity Router)

Every user message is first processed with this system prompt prepended. The model outputs a structured classification before any further action is taken.

```python
CLASSIFIER_SYSTEM_PROMPT = """
You are a task complexity router for a multi-tier AI agent pipeline.

Your job is to evaluate every incoming user request and output a JSON classification object. Do not answer the question. Only classify it.

Use this scoring rubric. Add 1 point for each criterion that applies:

COMPLEXITY CRITERIA:
1. MULTI_STEP: The task requires more than two sequential reasoning steps or subtasks.
2. SYNTHESIS: The task requires combining information from multiple distinct sources or domains.
3. SPECIALIZED_DOMAIN: The task involves legal, medical, financial, engineering, or scientific expertise.
4. LONG_FORM: The task requires structured output longer than 500 words (reports, essays, code files).
5. AMBIGUOUS: The task is underspecified and requires judgment to interpret correctly.
6. WORLD_KNOWLEDGE: The task requires detailed factual knowledge beyond general conversation.

ROUTING RULES:
- Score 0–1: Handle locally. Route = "local"
- Score 2+: Escalate. Route = "escalate"

OUTPUT FORMAT (JSON only, no other text):
{
  "score": <integer 0-6>,
  "triggered_criteria": [<list of criterion names that scored>],
  "route": "local" | "escalate",
  "summary": "<one sentence describing what the task is asking for>",
  "complexity_reason": "<one sentence explaining why this score was assigned>"
}
"""
```

### Calling the Classifier from OpenClaw

The classification call is a separate, lightweight API call to Ollama before the actual task is handled. Here is the Python skill that implements it:

```python
# skills/classify_task.py
import json
import os
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"
)

CLASSIFIER_SYSTEM_PROMPT = """..."""  # full prompt from above

def classify_task(user_message: str) -> dict:
    """
    Returns a classification dict with keys:
    score, triggered_criteria, route, summary, complexity_reason
    """
    response = client.chat.completions.create(
        model="nemotron-mini",
        messages=[
            {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0.0,   # deterministic classification
        max_tokens=256,
        response_format={"type": "json_object"}
    )
    
    raw = response.choices[0].message.content
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # fallback: if the model didn't return clean JSON, default to escalate
        return {"score": 3, "route": "escalate", "triggered_criteria": ["PARSE_FAILURE"],
                "summary": user_message[:100], "complexity_reason": "Classification parse failed; escalating by default."}

if __name__ == "__main__":
    import sys
    result = classify_task(sys.argv[1])
    print(json.dumps(result, indent=2))
```

### How OpenClaw Reads the Classification and Routes

In OpenClaw's main message handler (typically `src/agent.js` or configured via `config/routing.json`), add a routing hook:

```javascript
// src/routing.js
const { execFile } = require('child_process');

async function classifyAndRoute(userMessage, conversationHistory) {
  return new Promise((resolve, reject) => {
    execFile('python3', ['skills/classify_task.py', userMessage], (err, stdout) => {
      if (err) return resolve({ route: 'escalate' }); // fail safe: escalate on error
      try {
        const classification = JSON.parse(stdout);
        resolve(classification);
      } catch {
        resolve({ route: 'escalate' });
      }
    });
  });
}

module.exports = { classifyAndRoute };
```

In the main agent loop:

```javascript
const { classifyAndRoute } = require('./routing');

async function handleMessage(discordMessage) {
  const classification = await classifyAndRoute(discordMessage.content);
  
  if (classification.route === 'local') {
    // Pass to Ollama for local handling
    const response = await localModel.chat(discordMessage.content, conversationHistory);
    discordMessage.reply(response);
  } else {
    // Build escalation payload and send to cloud NIM
    const payload = buildEscalationPayload(discordMessage.content, classification, conversationHistory);
    const response = await cloudModel.chat(payload);
    discordMessage.reply(`[Cloud Nemotron] ${response}`);
  }
}
```

---

## 4. Escalation Payload Design

### Payload Structure

When Nemotron 4B determines escalation is needed, it drafts a structured context package before handing off. This is not just the raw user message — it is an enriched problem framing that primes the cloud model to skip re-analysis and go straight to execution.

```python
# skills/build_escalation_payload.py
import json
from openai import OpenAI
from datetime import datetime, timezone

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

FRAMING_PROMPT = """
You are preparing a handoff package for a more powerful AI model.
Given the user's request and the conversation history, produce a structured JSON object 
that gives the receiving model full context to answer immediately, without needing 
to re-ask clarifying questions.

Output JSON only:
{
  "original_request": "<verbatim user message>",
  "task_type": "<one of: analysis | generation | reasoning | code | research | other>",
  "key_constraints": ["<list of explicit constraints or requirements from the user>"],
  "relevant_context": "<summary of relevant conversation history>",
  "suggested_approach": "<brief recommendation for how to tackle this task>",
  "expected_output_format": "<describe what the final answer should look like>",
  "priority_flags": ["<LONG_FORM | MULTI_STEP | SPECIALIZED_DOMAIN | etc — from classifier>"]
}
"""

def build_escalation_payload(user_message: str, classification: dict, history: list) -> dict:
    history_summary = "\n".join([
        f"{m['role'].upper()}: {m['content'][:200]}" 
        for m in history[-6:]  # last 3 turns
    ])
    
    framing_input = f"""
User request: {user_message}

Recent conversation:
{history_summary}

Classifier output:
{json.dumps(classification, indent=2)}
"""
    
    response = client.chat.completions.create(
        model="nemotron-mini",
        messages=[
            {"role": "system", "content": FRAMING_PROMPT},
            {"role": "user", "content": framing_input}
        ],
        temperature=0.1,
        max_tokens=512,
        response_format={"type": "json_object"}
    )
    
    framing = json.loads(response.choices[0].message.content)
    
    # Final payload wraps framing with metadata
    payload = {
        "schema_version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "framing": framing,
        "full_conversation_history": history,
        "originating_model": "nemotron-mini",
        "target_model": "nvidia/llama-3.1-nemotron-70b-instruct"
    }
    
    return payload
```

### How OpenClaw Packages and Sends It

The payload is converted into a structured messages array for the NIM API call. The cloud model receives the full framing as a system-level context injection:

```python
def payload_to_nim_messages(payload: dict) -> list:
    """Convert the escalation payload into the messages array for the NIM API call."""
    system_context = f"""
You are receiving a pre-analyzed task from a local Nemotron 4B edge model.

TASK FRAMING:
{json.dumps(payload['framing'], indent=2)}

COMPLEXITY ANALYSIS:
- Score: {payload['classification']['score']}/6
- Triggered criteria: {', '.join(payload['classification']['triggered_criteria'])}
- Reason: {payload['classification']['complexity_reason']}

Deliver a complete, high-quality response to the user's original request. 
Do not re-ask clarifying questions — all context has been pre-packaged for you.
"""
    
    messages = [{"role": "system", "content": system_context}]
    
    # Inject conversation history
    for msg in payload['full_conversation_history']:
        messages.append({"role": msg['role'], "content": msg['content']})
    
    # Final user message
    messages.append({
        "role": "user", 
        "content": payload['framing']['original_request']
    })
    
    return messages
```

---

## 5. OpenClaw Skill Integration

### How OpenClaw Skills Work

OpenClaw uses a directory-based skill loader. Any Python (`.py`) or Bash (`.sh`) script placed in the `skills/` directory is automatically registered as a callable tool when OpenClaw starts. Skills are invoked by name either by the agent's routing logic or directly via slash commands in Discord.

Each skill receives its arguments via command-line arguments (`sys.argv`) and must print its output to stdout. OpenClaw captures stdout and routes it back to Discord.

Skill registration in `config/skills.json`:
```json
{
  "skills": [
    {
      "name": "summarize_local",
      "file": "skills/summarize_local.py",
      "description": "Summarizes a short text or answers a simple question using the local Nemotron 4B model via Ollama.",
      "trigger": "local"
    },
    {
      "name": "escalate_to_nim",
      "file": "skills/escalate_to_nim.py", 
      "description": "Builds a structured escalation payload and sends it to the cloud Nemotron model via NVIDIA NIM.",
      "trigger": "escalate"
    }
  ]
}
```

---

### Skill 1: Local Handling via Ollama (Simple Tasks)

```python
# skills/summarize_local.py
"""
OpenClaw skill: summarize_local
Handles simple tasks entirely within the local Nemotron 4B model via Ollama.
Called when classifier route = "local".
"""
import sys
import json
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"
)

LOCAL_SYSTEM_PROMPT = """
You are a helpful AI assistant running on a local edge device.
Be concise, accurate, and friendly.
For factual questions, answer directly.
For tasks involving calculations or simple analysis, show your work briefly.
"""

def handle_local(user_message: str, conversation_history: list) -> str:
    messages = [{"role": "system", "content": LOCAL_SYSTEM_PROMPT}]
    messages.extend(conversation_history[-10:])  # last 5 turns
    messages.append({"role": "user", "content": user_message})
    
    response = client.chat.completions.create(
        model="nemotron-mini",
        messages=messages,
        temperature=0.5,
        max_tokens=1024
    )
    
    return response.choices[0].message.content

if __name__ == "__main__":
    # OpenClaw passes args as JSON string
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    user_message = args.get("message", "")
    history = args.get("history", [])
    
    result = handle_local(user_message, history)
    print(result)  # OpenClaw captures stdout and posts to Discord
```

---

### Skill 2: Escalation to Cloud NIM (Complex Tasks)

```python
# skills/escalate_to_nim.py
"""
OpenClaw skill: escalate_to_nim
Builds escalation payload via local Nemotron 4B, then sends to NVIDIA NIM.
Called when classifier route = "escalate".
"""
import sys
import json
import os
from openai import OpenAI
from build_escalation_payload import build_escalation_payload
from classify_task import classify_task

# Cloud NIM client — same OpenAI-compatible interface, different base URL and key
nim_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.environ["NVIDIA_API_KEY"]
)

NIM_MODEL = "nvidia/llama-3.1-nemotron-70b-instruct"

def escalate(user_message: str, history: list) -> str:
    # Step 1: Re-run classifier to get structured metadata
    classification = classify_task(user_message)
    
    # Step 2: Local Nemotron 4B drafts the escalation framing
    payload = build_escalation_payload(user_message, classification, history)
    
    # Step 3: Convert payload to NIM message format
    messages = payload_to_nim_messages(payload)
    
    # Step 4: Send to cloud NIM
    response = nim_client.chat.completions.create(
        model=NIM_MODEL,
        messages=messages,
        temperature=0.4,
        max_tokens=2048
    )
    
    answer = response.choices[0].message.content
    
    # Annotate response so Discord shows which model answered
    return f"**[Cloud Nemotron — Complexity Score {classification['score']}/6]**\n\n{answer}"

def payload_to_nim_messages(payload: dict) -> list:
    system_context = f"""
You are receiving a pre-analyzed task from a local Nemotron 4B edge model.

TASK FRAMING:
{json.dumps(payload['framing'], indent=2)}

COMPLEXITY ANALYSIS:
- Score: {payload['classification']['score']}/6
- Triggered criteria: {', '.join(payload['classification']['triggered_criteria'])}

Deliver a complete, high-quality response. Do not re-ask clarifying questions.
"""
    messages = [{"role": "system", "content": system_context}]
    for msg in payload['full_conversation_history'][-10:]:
        messages.append({"role": msg['role'], "content": msg['content']})
    messages.append({"role": "user", "content": payload['framing']['original_request']})
    return messages

if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    user_message = args.get("message", "")
    history = args.get("history", [])
    
    result = escalate(user_message, history)
    print(result)
```

---

## 6. Cloud Model Integration

### Primary: NVIDIA NIM Hosted API

The NIM endpoint exposes a fully OpenAI-compatible interface. This means the same `openai` Python client you use to talk to Ollama locally also works for NIM — just swap the `base_url` and `api_key`.

**Available Nemotron models on build.nvidia.com (as of mid-2025):**
- `nvidia/llama-3.1-nemotron-70b-instruct` — the strongest instruction-following Nemotron model
- `nvidia/nemotron-4-340b-instruct` — if listed, the flagship datacenter-scale model
- Check https://build.nvidia.com/explore/reasoning for current model catalog

```python
# Full cloud model call implementation
import os
from openai import OpenAI

nim_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.environ["NVIDIA_API_KEY"]
)

def call_nim(messages: list, model: str = "nvidia/llama-3.1-nemotron-70b-instruct") -> str:
    try:
        response = nim_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.4,
            max_tokens=2048,
            timeout=60
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[NIM ERROR] {e}", file=sys.stderr)
        raise
```

### Why NIM is the Right Choice for the NVIDIA Hackathon Track

This is not a close call. Here is the argument for judges:

1. **On-brand:** The NVIDIA track explicitly rewards "Best use of Nemotron." Using Nemotron at the cloud tier (via NIM) means Nemotron is deployed at every layer of the stack — edge (4B), orchestration reasoning (4B classification), and datacenter (large NIM-hosted model).

2. **Edge-to-datacenter coherence:** NVIDIA's architecture pitch is that Nemotron scales from embedded devices to data centers. This project embodies that pitch literally — the same OpenAI-compatible client talks to a local 4B Nemotron and a datacenter-class Nemotron with only the `base_url` and `api_key` swapped.

3. **NIM is purpose-built for this:** NIM (NVIDIA Inference Microservices) is NVIDIA's own inference platform. Using it demonstrates knowledge of the NVIDIA ecosystem beyond just Ollama.

4. **Consistent API surface:** Since NIM is OpenAI-compatible and so is Ollama, both tiers are called with identical Python code. The only differences are `base_url` and `api_key`. This is a strong demo point: "we swap one URL and key and the system scales from laptop to datacenter."

### Failure Behavior: NIM Only — No Fallback Model

If NIM is unavailable the system logs the error and returns a clean error message to the user in Discord. There is no fallback model.

```python
def call_cloud(messages: list) -> str:
    try:
        return call_nim(messages)
    except Exception as nim_error:
        print(f"[NIM ERROR] {nim_error}", file=sys.stderr)
        return (
            "**[Escalation failed]**\n\n"
            "The cloud Nemotron model on NVIDIA NIM is currently unavailable. "
            "Please try again in a moment."
        )
```

---

## 7. Memory and Context Management

### How OpenClaw Maintains Conversation History

OpenClaw ships with SQLite-backed persistent memory. Every message (user and assistant) is stored with a session ID tied to the Discord channel and user. This history is loaded and passed to every model call so neither the local Ollama model nor the cloud NIM model loses context across turns.

**Memory schema (OpenClaw internal):**
```sql
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,       -- "{guild_id}:{channel_id}:{user_id}"
  role TEXT NOT NULL,             -- "user" | "assistant" | "system"
  content TEXT NOT NULL,
  model_used TEXT,                -- "nemotron-mini" | "nvidia/llama-3.1-nemotron-70b-instruct"
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Loading history for a model call:**
```python
# skills/memory.py
import sqlite3
from pathlib import Path

DB_PATH = Path("data/memory.db")

def get_history(session_id: str, max_turns: int = 10) -> list:
    """Load the last N turns for a session as an OpenAI-compatible messages list."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, max_turns * 2)
    )
    rows = cursor.fetchall()
    conn.close()
    # Reverse to get chronological order
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def save_message(session_id: str, role: str, content: str, model_used: str = None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO messages (session_id, role, content, model_used) VALUES (?, ?, ?, ?)",
        (session_id, role, content, model_used)
    )
    conn.commit()
    conn.close()
```

### Context Window Management

The local Nemotron 4B model has a limited context window (~8K tokens). To avoid overflow:

1. **Classify with zero history** — the complexity classification call uses only the current message, no history. This keeps the classifier fast and deterministic.
2. **Pass last 10 messages (5 turns) to local model** — sufficient for conversational continuity.
3. **Pass last 20 messages (10 turns) to cloud NIM model** — cloud model has a much larger context window and can handle more history.
4. **Summarize if history exceeds threshold** — if a session exceeds 30 turns, generate a running summary using the local model and prepend it as a system message:

```python
def get_context_with_summary(session_id: str) -> list:
    all_history = get_history(session_id, max_turns=50)
    
    if len(all_history) <= 20:
        return all_history[-20:]
    
    # Summarize older turns
    older_turns = all_history[:-20]
    recent_turns = all_history[-20:]
    
    summary_prompt = f"Summarize this conversation history in 3–5 sentences:\n\n" + \
                     "\n".join([f"{m['role']}: {m['content']}" for m in older_turns])
    
    summary_response = client.chat.completions.create(
        model="nemotron-mini",
        messages=[{"role": "user", "content": summary_prompt}],
        max_tokens=256, temperature=0.1
    )
    summary = summary_response.choices[0].message.content
    
    return [{"role": "system", "content": f"Earlier conversation summary: {summary}"}] + recent_turns
```

---

## 8. Discord Bot Configuration

### Required Permissions and Intents

**Privileged Intents (must be enabled in Discord Developer Portal):**
- `MESSAGE_CONTENT` — to read user messages
- `GUILD_MEMBERS` — to identify users for session tracking

**Bot Permissions (set during OAuth2 invite URL generation):**
- `SEND_MESSAGES`
- `READ_MESSAGE_HISTORY`
- `CREATE_PUBLIC_THREADS`
- `SEND_MESSAGES_IN_THREADS`
- `USE_APPLICATION_COMMANDS`
- `EMBED_LINKS` (for rich response formatting)

### OpenClaw Discord Handler

OpenClaw's Discord integration is configured via `config/discord.json` (see Step 7 above). The framework handles connection, reconnection, and slash command registration automatically.

For custom behavior, extend the message handler in `src/discord-handler.js`:

```javascript
// src/discord-handler.js
const { Client, GatewayIntentBits, Partials } = require('discord.js');
const { classifyAndRoute } = require('./routing');
const memory = require('./memory');

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,  // privileged intent
  ],
  partials: [Partials.Message, Partials.Channel]
});

client.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  if (!message.mentions.has(client.user)) return;  // only respond when @mentioned
  
  const sessionId = `${message.guildId}:${message.channelId}:${message.author.id}`;
  const userContent = message.content.replace(/<@!?\d+>/g, '').trim();
  
  // Start a thread for this response to keep the channel clean
  const thread = await message.startThread({
    name: `Response — ${userContent.substring(0, 50)}`,
    autoArchiveDuration: 60
  });
  
  await thread.sendTyping();
  
  // Save user message to memory
  memory.saveMessage(sessionId, 'user', userContent);
  
  // Classify and route
  const classification = await classifyAndRoute(userContent);
  const history = memory.getHistory(sessionId, 10);
  
  let response;
  if (classification.route === 'local') {
    response = await runSkill('summarize_local', { message: userContent, history });
  } else {
    await thread.send('🔄 *Complex task detected — escalating to cloud Nemotron...*');
    response = await runSkill('escalate_to_nim', { message: userContent, history });
  }
  
  // Save assistant response
  const modelUsed = classification.route === 'local' ? 'nemotron-mini' : 'nvidia/llama-3.1-nemotron-70b-instruct';
  memory.saveMessage(sessionId, 'assistant', response, modelUsed);
  
  // Post response in thread (Discord has 2000 char limit per message)
  if (response.length > 1900) {
    const chunks = response.match(/.{1,1900}/gs);
    for (const chunk of chunks) await thread.send(chunk);
  } else {
    await thread.send(response);
  }
});

client.login(process.env.DISCORD_BOT_TOKEN);
module.exports = client;
```

### Threading Behavior

Every user query spawns a Discord thread. This keeps the main channel clean and lets multiple users query simultaneously without responses colliding. The thread name is set to the first 50 characters of the user's question. Threads auto-archive after 60 minutes of inactivity.

---

## 9. End-to-End Demo Scenario

### Setup for Judges

Before the demo, have these three windows visible:
1. **Discord** — the `#nemotron-agent` channel in your server
2. **Terminal 1** — `ollama ps` output showing `nemotron-mini` loaded
3. **Terminal 2** — OpenClaw logs (`npm run start` with verbose logging)

This shows the full stack is live and running locally.

---

### Demo Task A: Local Handling (Score 1/6)

**User types in Discord:**
> `@NemotronSwarmAgent What does TCP handshake mean?`

**What happens (visible in logs):**
```
[OpenClaw] Message received: "What does TCP handshake mean?"
[Classifier] Calling Ollama/nemotron-mini...
[Classifier] Result: {"score": 1, "route": "local", "triggered_criteria": ["WORLD_KNOWLEDGE"]}
[Router] Route: LOCAL
[Skill: summarize_local] Calling Ollama/nemotron-mini...
[Skill: summarize_local] Response received in 1.2s
[Discord] Posted response to thread
```

**What judges see in Discord:**
A thread opens instantly. Nemotron 4B answers from the local Ollama instance within ~2 seconds. No cloud call was made. The response includes no cloud model annotation.

**Why it's compelling:** Demonstrates edge-first intelligence. Simple questions never leave the device.

---

### Demo Task B: Escalation Path (Score 4/6)

**User types in Discord:**
> `@NemotronSwarmAgent Write me a detailed technical analysis of the tradeoffs between transformer-based and state-space model architectures for long-context inference, covering memory scaling, parallelism, training stability, and hardware utilization. Include a recommendation for production deployment.`

**What happens (visible in logs):**
```
[OpenClaw] Message received: [long technical request]
[Classifier] Calling Ollama/nemotron-mini...
[Classifier] Result: {
  "score": 4,
  "route": "escalate",
  "triggered_criteria": ["MULTI_STEP", "SYNTHESIS", "SPECIALIZED_DOMAIN", "LONG_FORM"],
  "complexity_reason": "Requires synthesis across ML architecture domains with structured long-form output."
}
[Router] Route: ESCALATE
[Framing] Calling Ollama/nemotron-mini to draft context package...
[Framing] Escalation payload built in 0.8s
[Skill: escalate_to_nim] Sending to nvidia/llama-3.1-nemotron-70b-instruct via NIM...
[Skill: escalate_to_nim] Response received in 8.4s
[Discord] Posted response to thread (3 chunks)
```

**What judges see in Discord:**

1. A thread opens.
2. The bot immediately posts: `🔄 Complex task detected — escalating to cloud Nemotron...`
3. ~9 seconds later, a comprehensive multi-section technical analysis appears with the header **[Cloud Nemotron — Complexity Score 4/6]**, covering all four requested topics with a structured recommendation.

**Why it's compelling:**

- The routing decision is transparent and visible in the Discord channel itself
- The response header identifies which model answered and why
- The local model contributed intelligently (drafting the framing package) even though it delegated the final answer
- Two Nemotron models collaborated seamlessly on one user request
- The user experience is seamless — they typed one message and got one answer

---

### Demo Task C: Multi-Turn Memory Test

After Demo B, the user follows up:
> `@NemotronSwarmAgent Based on your recommendation, which specific hardware configuration would you suggest for a 100B parameter SSM running production inference?`

This follow-up references "your recommendation" — testing that the system remembered the previous exchange.

**What happens:** OpenClaw loads the session history, the classifier scores this as 3/6 (SPECIALIZED_DOMAIN + SYNTHESIS + MULTI_STEP), escalates again, and the cloud model's response correctly references the specific SSM recommendation from the previous turn without the user re-explaining it.

**What judges see:** Seamless contextual awareness across a multi-turn technical conversation, with intelligent routing at every step.

---

## 10. Architecture Diagram

```
╔══════════════════════════════════════════════════════════════════════════╗
║                        NEMOTRON SWARM AGENT                             ║
║                    Three-Tier Agentic AI Pipeline                        ║
╚══════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────┐
│  USER                                                                   │
│  Discord Client (mobile / desktop / web)                                │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      │  Discord API (WebSocket / REST)
                      │  @mention or slash command
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  TIER 2 — AGENT FRAMEWORK                                               │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  OpenClaw (Node.js, runs locally)                               │   │
│  │                                                                 │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐  │   │
│  │  │ Discord      │  │ Memory       │  │ Skill Runner        │  │   │
│  │  │ Handler      │  │ Manager      │  │ (Python / Bash)     │  │   │
│  │  │ (discord.js) │  │ (SQLite)     │  │ skills/             │  │   │
│  │  └──────┬───────┘  └──────────────┘  └──────────┬──────────┘  │   │
│  │         │                                        │             │   │
│  │         └──────────────┬─────────────────────────┘             │   │
│  │                        │                                        │   │
│  │              Message Router                                     │   │
│  │              (classify → route → execute → respond)             │   │
│  └────────────────────────┬────────────────────────────────────────┘   │
└───────────────────────────┼─────────────────────────────────────────────┘
                            │
              OpenAI-compatible HTTP API
              POST http://localhost:11434/v1/chat/completions
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  TIER 1 — LOCAL INFERENCE STACK                                         │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Ollama  (local model runtime)                                   │  │
│  │  • Serves OpenAI-compatible API at localhost:11434               │  │
│  │  • Manages model loading, quantization, GPU memory               │  │
│  │  ┌────────────────────────────────────────────────────────────┐  │  │
│  │  │  Nemotron 4B  (nemotron-mini)                              │  │  │
│  │  │  • Complexity classifier  (temp=0.0, JSON output)          │  │  │
│  │  │  • Simple task handler    (temp=0.5, conversational)       │  │  │
│  │  │  • Escalation framer      (temp=0.1, structured JSON)      │  │  │
│  │  └────────────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
              Score ≥ 2: ESCALATE
                              │
              OpenAI-compatible HTTPS API
              POST https://integrate.api.nvidia.com/v1/chat/completions
              Header: Authorization: Bearer $NVIDIA_API_KEY
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  TIER 3 — CLOUD INFERENCE  (NVIDIA NIM)                                 │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  NVIDIA NIM  (build.nvidia.com)                                  │  │
│  │  ┌────────────────────────────────────────────────────────────┐  │  │
│  │  │  Nemotron 70B (nvidia/llama-3.1-nemotron-70b-instruct)     │  │  │
│  │  │  • Receives pre-structured escalation payload              │  │  │
│  │  │  • Heavy reasoning, long-form generation                   │  │  │
│  │  │  • Returns refined response to OpenClaw                    │  │  │
│  │  └────────────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  NIM only — no fallback model. If NIM is unavailable the bot logs       │
│  the error and posts a clean error message in Discord.                  │
└─────────────────────────────────────────────────────────────────────────┘

MESSAGE FLOW:
━━━━━━━━━━━
1. User @mentions bot in Discord
2. OpenClaw receives message via Discord WebSocket
3. OpenClaw calls Ollama → Nemotron 4B: complexity classification
4. Score 0–1: Nemotron 4B handles locally → OpenClaw posts to Discord thread
5. Score 2+:  Nemotron 4B drafts framing payload → OpenClaw sends to NIM
6.            NIM Nemotron 70B responds → OpenClaw posts to Discord thread

PROTOCOLS:
━━━━━━━━━
• Discord ←→ OpenClaw:     Discord API (WebSocket for events, REST for replies)
• OpenClaw ←→ Ollama:      HTTP, OpenAI-compatible REST (localhost:11434/v1)
• OpenClaw ←→ NIM:         HTTPS, OpenAI-compatible REST (integrate.api.nvidia.com/v1)
• OpenClaw → Skills:       Local process spawn (stdout capture)
• Memory:                  Local SQLite (data/memory.db)
```

---

## 11. Potential Failure Points and How to Handle Them

### 1. Ollama OOM / Model Load Failure

**Symptom:** Ollama crashes or returns 500 errors. The `ollama ps` command shows no models loaded.

**Root cause:** Nemotron 4B requires ~4–5 GB of VRAM. On a machine with limited GPU memory or other processes consuming VRAM, the model may fail to load.

**Prevention:**
- Before demo, run `ollama ps` and `nvidia-smi` to confirm the model is loaded and VRAM headroom is sufficient
- Run `ollama run nemotron-mini "test"` once before the demo to pre-load the model into GPU memory — Ollama keeps it loaded for 5 minutes after the last call by default
- Set `OLLAMA_KEEP_ALIVE=60m` in your environment to keep the model loaded during the demo

**Recovery:**
```bash
ollama stop nemotron-mini
ollama run nemotron-mini "warmup"  # reload and warm up
```

Add a health check in OpenClaw that pings Ollama at startup and exits with a clear error if it is unreachable:
```javascript
const { default: fetch } = require('node-fetch');
async function checkOllamaHealth() {
  const res = await fetch('http://localhost:11434/api/tags');
  if (!res.ok) throw new Error('Ollama not responding at localhost:11434');
  console.log('[Health] Ollama OK');
}
```

### 2. Nemotron 4B Slow First Response

**Symptom:** The first response after startup takes 15–30 seconds. Subsequent responses are fast.

**Root cause:** Ollama lazily loads model weights into VRAM on first inference.

**Prevention:** Run a warmup call immediately after starting Ollama:
```bash
# Add to your startup script
ollama run nemotron-mini "warmup" && echo "Model warmed up"
```

Or trigger it programmatically at OpenClaw startup via the health check skill.

### 3. NIM Rate Limits / Credit Exhaustion

**Symptom:** Cloud escalation calls return HTTP 429 (rate limited) or 402 (credits exhausted).

**Root cause:** Free NIM tier has request limits (~1000 requests/month depending on model).

**Prevention:**
- Check your NIM credit balance at https://build.nvidia.com before the demo
- Cache the last NIM response per session — if the same complex question is asked twice, return the cached answer without consuming another NIM credit
- Add a demo mode that uses a fixed NIM response from a JSON file if credits are exhausted

**Recovery (clean error message):**
NIM only — there is no fallback model. When the NIM call fails, the escalation skill logs the error to stderr and returns a short, user-readable message that the Discord handler posts to the thread (e.g. *"The cloud Nemotron model on NVIDIA NIM is currently unavailable. Please try again in a moment."*). The bot stays online and the next request is retried fresh.

```python
# Emergency: stub NIM with a pre-recorded response for the specific demo task
DEMO_CACHE = {
    "transformer vs ssm analysis": open("demo_cache/ssm_analysis.txt").read()
}

def call_nim_with_cache(messages: list) -> str:
    last_user_msg = messages[-1]['content'].lower()
    for key, cached in DEMO_CACHE.items():
        if key in last_user_msg:
            return f"**[Cloud Nemotron — Cached Demo Response]**\n\n{cached}"
    return call_nim(messages)
```

### 4. Discord Bot Permission Errors

**Symptom:** Bot can read messages but cannot create threads or post responses. Error in logs: `Missing Permissions`.

**Root cause:** The bot was invited without the correct permissions, or the channel has permission overrides that restrict the bot.

**Prevention:**
- Verify permissions before the demo: use `/permissions` if available, or check the bot's role in `Server Settings → Roles`
- The bot needs explicit permission to Create Threads in the target channel — this is not covered by global Send Messages permission in some server configurations
- Test the full message → thread → response flow in the demo channel the day before

**Quick fix:** In Discord, go to the target channel's settings → Permissions → add the bot's role with Create Public Threads, Send Messages in Threads enabled.

### 5. JSON Parse Failure in Classifier

**Symptom:** The classifier call returns text instead of valid JSON, causing the routing logic to crash.

**Root cause:** Even with `response_format: {"type": "json_object"}`, small models occasionally prepend text like "Here is the classification:" before the JSON.

**Prevention:** Always wrap the JSON parse in a try/catch with a safe escalation default (already implemented in `classify_task.py` above). Never let a parse failure cause an unhandled exception.

```python
# Robust JSON extraction even when model wraps it in text
import re

def safe_json_extract(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON object from surrounding text
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"score": 3, "route": "escalate", "triggered_criteria": ["PARSE_FAILURE"]}
```

### 6. Discord Connection Drop

**Symptom:** OpenClaw loses WebSocket connection to Discord mid-demo.

**Root cause:** Network instability or Discord rate limiting.

**Prevention:** `discord.js` handles automatic reconnection by default — OpenClaw will reconnect within 5–15 seconds. Keep a browser tab open to Discord during the demo to verify the bot is online.

---

## 12. What Makes This Competitive for the NVIDIA Track

### The Edge-to-Datacenter Story

NVIDIA's architecture narrative is that Nemotron scales continuously from edge devices to data centers. This project is that narrative made concrete and interactive:

- **Edge layer:** Nemotron 4B running on a consumer GPU via Ollama — this is what NVIDIA calls "single-GPU" or "workstation" deployment. It handles the majority of requests without any cloud dependency.
- **Datacenter layer:** NVIDIA NIM hosted on NVIDIA's own infrastructure, running a larger Nemotron model at datacenter scale. This is reached only when the edge model's own judgment determines the task exceeds local capacity.
- **The routing intelligence is itself a Nemotron capability:** The decision to escalate is made by Nemotron 4B, not by hardcoded rules. The local model reasons about its own limitations and delegates appropriately. This is a demonstration of model self-awareness and orchestration capability that judges can observe in real time.

### Nemotron at Every Tier

Most hackathon submissions using Nemotron will use it at exactly one tier — either locally or via the API. This architecture deploys Nemotron at three functional roles:
1. **Classifier** — Nemotron 4B as a task complexity evaluator
2. **Framing agent** — Nemotron 4B as a context-packaging reasoning agent
3. **Primary responder** — Nemotron 4B for local tasks; NIM-hosted Nemotron for complex ones

This means Nemotron's capabilities are being demonstrated at multiple scales and in multiple functional roles within a single demo.

### Agentic Routing as the Core Technical Differentiator

The routing behavior is not a wrapper or a thin API call. It is a genuine agentic capability: the local model reads an incoming task, reasons about its own capacity to handle it, and makes an autonomous escalation decision. This maps exactly onto what NVIDIA's Nemotron track criteria describe as "multi-step reasoning, tool use, and agent orchestration."

Specific angles to emphasize with judges:

1. **"The model decides, not the code."** Point at the classifier system prompt. The routing threshold is implemented as a language model reasoning task, not an if/else based on keywords. Show the classifier output JSON live.

2. **"Two Nemotron models collaborate on a single user query."** Walk judges through the escalation path: Nemotron 4B reads the request, writes the framing package, and hands it to Nemotron 70B. Both models contributed to the final answer.

3. **"This is production-realistic."** Running a 4B model locally for fast, cheap responses and escalating only when necessary is exactly how a real enterprise would deploy Nemotron to manage inference costs. The hackathon demo is also a deployment architecture.

4. **"The edge model adds value even when escalating."** The cloud model does not receive the raw user message. It receives a pre-analyzed, pre-structured framing package drafted by Nemotron 4B. The local model has already done cognitive work that makes the cloud model's response faster and better-calibrated.

5. **"Every component uses NVIDIA's stack."** Ollama with Nemotron 4B → NVIDIA NIM with Nemotron 70B. The only non-NVIDIA component is OpenClaw (the orchestration layer) and Discord (the interface). The AI stack is entirely NVIDIA-native.

### Presenting to Judges: Talking Points

- Open with the live demo first. Let judges see a simple question go local and a complex one escalate — before explaining anything technical.
- Show the classifier JSON output in the terminal log. Judges who understand LLMs will immediately recognize that a model is making the routing decision, not hardcoded logic.
- Use the phrase "autonomous complexity routing" — it's accurate and memorable.
- Have a slide that maps your three tiers explicitly to NVIDIA's edge / single-GPU / datacenter terminology. Make the alignment obvious.
- If asked about fallbacks: "NIM only — no fallback model. If NIM is unavailable the bot logs the error and posts a clean error message in Discord. The whole pipeline is Nemotron at both ends."

---

*End of Implementation Guide — Nemotron Swarm Agent*
