# ============================================================
# skills/summarize_local.py
# ============================================================
# Role: Tier 1 — Local Inference (handler for simple tasks)
# Purpose: Called when the classifier route is "local". Injects
#          a short system prompt and the recent conversation
#          history, calls nemotron-mini via Ollama, and prints
#          the response string to stdout.
# Calls:   Ollama at http://localhost:11434/v1.
# Used by: src/discord-handler.js (spawned as a child process via
#          src/routing.js → runPythonSkill).
# ============================================================
"""Local skill that handles simple tasks via nemotron-mini on Ollama.

Reads sys.argv[1] as a JSON string with keys "message" and "history",
calls the local Ollama API, and prints the model's reply to stdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from openai import OpenAI  # noqa: E402

OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "nemotron-mini"

LOCAL_SYSTEM_PROMPT = (
    "You are a helpful AI assistant running on a local edge device.\n"
    "Be concise, accurate, and friendly.\n"
    "For factual questions, answer directly.\n"
    "For tasks involving calculations or simple analysis, show your work briefly."
)


def _client() -> OpenAI:
    return OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


def _sanitize_history(history: list) -> list[dict]:
    out: list[dict] = []
    for m in history or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant", "system") and isinstance(content, str) and content:
            out.append({"role": role, "content": content})
    return out


def handle_local(user_message: str, history: list) -> str:
    safe_history = _sanitize_history(history)
    messages: list[dict] = [{"role": "system", "content": LOCAL_SYSTEM_PROMPT}]
    messages.extend(safe_history[-10:])

    if not messages or messages[-1].get("content") != user_message or messages[-1].get("role") != "user":
        messages.append({"role": "user", "content": user_message})

    try:
        response = _client().chat.completions.create(
            model=OLLAMA_MODEL,
            messages=messages,
            temperature=0.5,
            max_tokens=1024,
        )
    except Exception as e:
        print(f"[summarize_local] Ollama error: {e}", file=sys.stderr)
        return f"Local model unavailable: {e}"

    return (response.choices[0].message.content or "").strip()


if __name__ == "__main__":
    args: dict = {}
    if len(sys.argv) > 1:
        try:
            args = json.loads(sys.argv[1])
            if not isinstance(args, dict):
                args = {"message": str(args)}
        except json.JSONDecodeError:
            args = {"message": sys.argv[1]}

    message = str(args.get("message", "") or "")
    history = args.get("history") or []
    print(handle_local(message, history))
