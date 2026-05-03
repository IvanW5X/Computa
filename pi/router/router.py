#!/usr/bin/env python3
# Target path on the Pi: /home/yelopi/router/router.py
#
# Identical to the existing /home/yelopi/router/router.py except for SQLite
# logging into /home/yelopi/dashboard/requests.db. The classifier, the
# keyword list, the Ollama /api/generate call, the NVIDIA NIM call, the
# SSE streaming response, the routes, and the listen socket are all
# unchanged.

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, request, Response
from dotenv import load_dotenv

load_dotenv("/home/yelopi/router/.env")

app = Flask(__name__)

OLLAMA = "http://127.0.0.1:11434"
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"
LOCAL_MODEL = "nemotron-mini:4b"

DB_PATH = os.getenv("ROUTER_DB_PATH", "/home/yelopi/dashboard/requests.db")


# ---------- SQLite logging (best-effort; never raises into chat()) --------

def _db_connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=2.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous  = NORMAL")
    return conn


def db_init():
    try:
        conn = _db_connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS requests (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp     TEXT    NOT NULL,
                    route         TEXT    NOT NULL CHECK (route IN ('local','cloud')),
                    model         TEXT    NOT NULL,
                    user_message  TEXT    NOT NULL,
                    latency_ms    INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_id_desc ON requests (id DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_route   ON requests (route)")
        finally:
            conn.close()
    except Exception as e:
        print(f"[router] db_init failed: {e}", flush=True)


def db_log(route, model, user_message, latency_ms):
    try:
        conn = _db_connect()
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
        # Most common: "database is locked" while the dashboard is reading.
        # Drop the row rather than block the bot reply.
        print(f"[router] db_log skipped (locked): {e}", flush=True)
    except Exception as e:
        print(f"[router] db_log failed: {e}", flush=True)


# ---------- Original logic, unchanged -------------------------------------

def extract_text(content):
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""

def classify(message):
    message = extract_text(message)
    complex_keywords = ["write", "implement", "create", "build", "code", "class", "function", "algorithm", "explain", "analyze", "compare", "design", "debug", "fix", "optimize"]
    msg_lower = message.lower()
    if any(k in msg_lower for k in complex_keywords):
        return "COMPLEX"
    try:
        r = requests.post(f"{OLLAMA}/api/generate", json={
            "model": "qwen2:0.5b",
            "prompt": f"You are a classifier. Reply with ONLY the word SIMPLE or COMPLEX. SIMPLE = greetings, math, short factual questions. COMPLEX = coding, writing, analysis, explanations. Message: {message}",
            "stream": False
        }, timeout=30)
        result = r.json().get("response", "COMPLEX").strip().upper()
        return "SIMPLE" if "SIMPLE" in result else "COMPLEX"
    except:
        return "COMPLEX"

def ask_local(messages, _trace=None):
    prompt = extract_text(messages[-1]["content"]) if messages else ""
    r = requests.post(f"{OLLAMA}/api/generate", json={
        "model": "nemotron-mini:4b",
        "prompt": prompt,
        "stream": False
    }, timeout=120)
    result = r.json().get("response", "")
    if not result.strip():
        if _trace is not None:
            _trace["fell_back"] = True
        return ask_nvidia(messages)
    return result

def ask_nvidia(messages):
    clean = [{"role": m["role"], "content": extract_text(m["content"])} for m in messages]
    r = requests.post(NVIDIA_URL, json={
        "model": NVIDIA_MODEL,
        "messages": clean,
        "max_tokens": 1024
    }, headers={
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }, timeout=30)
    return r.json()["choices"][0]["message"]["content"]

def stream_reply(reply, model="router"):
    chunk = {
        "id": "router-1",
        "object": "chat.completion.chunk",
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": reply},
            "finish_reason": None
        }]
    }
    yield f"data: {json.dumps(chunk)}\n\n"
    done = {
        "id": "router-1",
        "object": "chat.completion.chunk",
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop"
        }]
    }
    yield f"data: {json.dumps(done)}\n\n"
    yield "data: [DONE]\n\n"

@app.route("/v1/chat/completions", methods=["POST"])
@app.route("/chat/completions", methods=["POST"])
def chat():
    started = time.monotonic()
    body = request.json
    messages = body.get("messages", [])
    user_message = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    user_message = extract_text(user_message)
    route = classify(user_message)
    print(f"[router] {route}: {user_message[:60]}", flush=True)

    # Track which model actually answered, including the local->cloud
    # fallback that ask_local performs internally on an empty response.
    trace = {"fell_back": False}
    actual_route = "local" if route == "SIMPLE" else "cloud"
    actual_model = LOCAL_MODEL if route == "SIMPLE" else NVIDIA_MODEL

    try:
        if route == "SIMPLE":
            reply = ask_local(messages, _trace=trace)
            if trace["fell_back"]:
                actual_route = "cloud"
                actual_model = NVIDIA_MODEL
        else:
            reply = ask_nvidia(messages)
    except Exception as e:
        reply = f"Error: {str(e)}"

    latency_ms = int((time.monotonic() - started) * 1000)
    db_log(actual_route, actual_model, user_message, latency_ms)

    return Response(stream_reply(reply), mimetype="text/event-stream")

if __name__ == "__main__":
    db_init()
    app.run(host="127.0.0.1", port=11435)
