#!/usr/bin/env python3
# Target path on the Pi: /home/yelopi/router/router.py
#
# Hybrid AI gateway router for Raspberry Pi 5.
#
# Flow (unchanged from the existing service):
#   POST /chat/completions on :11435
#     -> qwen2:0.5b classifies the user message as SIMPLE or COMPLEX
#        (keyword pre-filter first, then LLM if no keyword hit)
#        SIMPLE  -> nemotron-mini:4b via local Ollama
#        COMPLEX -> NVIDIA NIM (nvidia/nemotron-3-super-120b-a12b)
#     -> returns OpenAI-shaped chat completion JSON
#     -> stdout still emits "[router] SIMPLE: ..." / "[router] COMPLEX: ..."
#
# What is NEW in this revision: SQLite logging to
# /home/yelopi/dashboard/requests.db. Logging is best-effort -- a DB write
# error never breaks a reply to the bot. Schema lives in
# /home/yelopi/dashboard/schema.sql; init once with sqlite3 < schema.sql.

from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, request

# ---------- Config ---------------------------------------------------------

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 11435

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://127.0.0.1:11434")

CLASSIFIER_MODEL = "qwen2:0.5b"
LOCAL_MODEL      = "nemotron-mini:4b"
NIM_MODEL        = "nvidia/nemotron-3-super-120b-a12b"

NIM_URL          = "https://integrate.api.nvidia.com/v1/chat/completions"
NIM_TIMEOUT_S    = 30.0
LOCAL_TIMEOUT_S  = 300.0
CLASSIFY_TIMEOUT = 15.0

DB_PATH = os.environ.get("ROUTER_DB_PATH", "/home/yelopi/dashboard/requests.db")

# Keyword pre-filter: things that are obviously SIMPLE without burning a
# qwen2 swap. Order matters; first match wins.
SIMPLE_PATTERNS = [
    re.compile(r"^\s*(hi|hey|hello|yo|sup|hola|howdy|gm|good\s+morning|good\s+night)\b", re.I),
    re.compile(r"^\s*(thanks|thank\s+you|thx|ty|cool|nice|great|ok|okay|got\s+it|cheers)\b", re.I),
    re.compile(r"^\s*(who|what|when|where)\s+(is|are|was|were)\s+\S{1,40}\??\s*$", re.I),
    re.compile(r"^\s*(define|explain)\s+\S{1,30}\??\s*$", re.I),
    re.compile(r"^\s*what\s+(is|are)\s+\d+\s*[\+\-\*x×\/÷]\s*\d+\??\s*$", re.I),
    re.compile(r"^\s*say\s+(hi|hello)\b", re.I),
]

# Keyword pre-filter for things that are obviously COMPLEX -- skip the
# classifier and go straight to cloud.
COMPLEX_PATTERNS = [
    re.compile(r"\b(write|generate|draft)\s+(a\s+)?(essay|report|article|story|poem|paper)\b", re.I),
    re.compile(r"\b(prove|derive|analy[sz]e|architect|refactor)\b", re.I),
    re.compile(r"\b(step[\s\-]?by[\s\-]?step|in\s+detail|comprehensive)\b", re.I),
]

# ---------- DB layer -------------------------------------------------------

_db_init_done = False


def _db_connect_rw() -> sqlite3.Connection:
    """Open the requests.db for write. Short timeout so a transient lock
    (the dashboard reading) does not stall the bot's reply."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=2.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous  = NORMAL")
    return conn


def _db_init() -> None:
    """Create the table if missing. Cheap; called lazily on first log."""
    global _db_init_done
    if _db_init_done:
        return
    try:
        conn = _db_connect_rw()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp     TEXT    NOT NULL,
                    route         TEXT    NOT NULL CHECK (route IN ('local','cloud')),
                    model         TEXT    NOT NULL,
                    user_message  TEXT    NOT NULL,
                    latency_ms    INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_requests_id_desc ON requests (id DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_requests_route ON requests (route)"
            )
        finally:
            conn.close()
        _db_init_done = True
    except Exception as e:
        sys.stderr.write(f"[router] db init failed (continuing without logging): {e}\n")


def db_log(route: str, model: str, user_message: str, latency_ms: int) -> None:
    """Best-effort log. NEVER raises into the request handler."""
    _db_init()
    try:
        conn = _db_connect_rw()
        try:
            conn.execute(
                "INSERT INTO requests (timestamp, route, model, user_message, latency_ms) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    route,
                    model,
                    (user_message or "")[:200],
                    int(latency_ms),
                ),
            )
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        # Most common: "database is locked" if the dashboard is mid-read on
        # microSD. Drop the row rather than block the reply.
        sys.stderr.write(f"[router] db_log skipped (locked): {e}\n")
    except Exception as e:
        sys.stderr.write(f"[router] db_log failed: {e}\n")


# ---------- Ollama / NIM clients ------------------------------------------

def ollama_chat(model: str, messages: list[dict], timeout: float,
                temperature: float = 0.4, num_predict: int = 512) -> str:
    """Call Ollama's /api/chat. Returns the assistant content as a string."""
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
        "keep_alive": "30s",
    }
    r = requests.post(f"{OLLAMA_BASE}/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return ((data.get("message") or {}).get("content") or "").strip()


def call_nim(user_message: str) -> str:
    api_key = (os.environ.get("NVIDIA_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not set in /home/yelopi/router/.env")

    body = {
        "model": NIM_MODEL,
        "messages": [{"role": "user", "content": user_message}],
        "max_tokens": 1024,
        "temperature": 0.4,
        "stream": False,
    }
    r = requests.post(
        NIM_URL,
        json=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=NIM_TIMEOUT_S,
    )
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


# ---------- Classification -------------------------------------------------

def _keyword_verdict(message: str) -> str | None:
    """Return 'SIMPLE' / 'COMPLEX' if a keyword pattern hits, else None."""
    for pat in SIMPLE_PATTERNS:
        if pat.search(message):
            return "SIMPLE"
    for pat in COMPLEX_PATTERNS:
        if pat.search(message):
            return "COMPLEX"
    return None


def classify(message: str) -> str:
    """SIMPLE or COMPLEX. Anything weird -> COMPLEX (safe escalate)."""
    kw = _keyword_verdict(message)
    if kw:
        return kw

    prompt = (
        "Classify this user message as SIMPLE or COMPLEX. "
        "SIMPLE = greetings, basic facts, short definitions, arithmetic, single-step questions. "
        "COMPLEX = multi-step reasoning, synthesis, deep domain expertise, long-form output. "
        "Reply with EXACTLY one word: SIMPLE or COMPLEX. "
        f"Message: {message}"
    )
    try:
        raw = ollama_chat(
            CLASSIFIER_MODEL,
            [{"role": "user", "content": prompt}],
            timeout=CLASSIFY_TIMEOUT,
            temperature=0.0,
            num_predict=4,
        )
    except Exception as e:
        sys.stderr.write(f"[router] classify failed, defaulting COMPLEX: {e}\n")
        return "COMPLEX"

    head = (raw or "").strip().upper().split()
    if not head:
        return "COMPLEX"
    token = head[0].strip(".,:;!?\"'()[]{}").upper()
    return "SIMPLE" if token == "SIMPLE" else "COMPLEX"


# ---------- Handlers -------------------------------------------------------

def handle_simple(message: str) -> str:
    return ollama_chat(
        LOCAL_MODEL,
        [{"role": "user", "content": message}],
        timeout=LOCAL_TIMEOUT_S,
        temperature=0.4,
        num_predict=512,
    ) or "_(local model returned empty)_"


def handle_complex(message: str) -> str:
    return call_nim(message)


def extract_user_text(messages: list[dict]) -> str:
    """Collapse the OpenAI messages array into a single user-side string,
    skipping system prompts. Mirrors what OpenClaw sends."""
    parts: list[str] = []
    for m in messages or []:
        if not isinstance(m, dict) or m.get("role") == "system":
            continue
        content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
    return "\n".join(p for p in parts if p).strip()


# ---------- Flask app ------------------------------------------------------

app = Flask(__name__)


@app.route("/healthz", methods=["GET"])
@app.route("/health",  methods=["GET"])
def healthz():
    return jsonify({"ok": True}), 200


@app.route("/chat/completions", methods=["POST"])
def chat_completions():
    started = time.monotonic()
    payload = request.get_json(silent=True) or {}
    user_text = extract_user_text(payload.get("messages") or [])

    if not user_text:
        return jsonify({"error": {"message": "no user message"}}), 400

    verdict = classify(user_text)

    if verdict == "SIMPLE":
        route_label = "local"
        model_id    = LOCAL_MODEL
        try:
            answer = handle_simple(user_text)
        except Exception as e:
            sys.stderr.write(f"[router] local generate failed: {e}\n")
            answer = "Sorry -- the local model is not reachable. Please retry."
        print(f"[router] SIMPLE: {user_text[:120]}", flush=True)
    else:
        route_label = "cloud"
        model_id    = NIM_MODEL
        try:
            answer = handle_complex(user_text)
        except Exception as e:
            sys.stderr.write(f"[router] NIM call failed, falling back to local: {e}\n")
            try:
                answer = handle_simple(user_text) + (
                    "\n\n_(cloud Nemotron 120B unavailable -- answered locally)_"
                )
            except Exception as e2:
                sys.stderr.write(f"[router] local fallback also failed: {e2}\n")
                answer = "The cloud and local models are both unavailable. Please retry shortly."
            route_label = "local"
            model_id    = LOCAL_MODEL
        print(f"[router] COMPLEX: {user_text[:120]}", flush=True)

    latency_ms = int((time.monotonic() - started) * 1000)

    db_log(route_label, model_id, user_text, latency_ms)

    return jsonify({
        "id": f"chatcmpl-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": answer},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens":     max(1, len(user_text) // 4),
            "completion_tokens": max(1, len(answer)    // 4),
            "total_tokens":      max(2, (len(user_text) + len(answer)) // 4),
        },
    }), 200


if __name__ == "__main__":
    _db_init()
    print(
        f"[router] listening on http://{LISTEN_HOST}:{LISTEN_PORT}  "
        f"db={DB_PATH}  ollama={OLLAMA_BASE}",
        flush=True,
    )
    app.run(host=LISTEN_HOST, port=LISTEN_PORT, threaded=True, use_reloader=False)
