# ============================================================
# skills/escalate_to_nim.py
# ============================================================
# Role: Tier 3 — Cloud Inference (orchestration glue)
# Purpose: Builds the framing payload for a complex request and
#          sends it to NVIDIA NIM (nvidia/nemotron-3-super-120b-a12b)
#          via the OpenAI-compatible endpoint at
#          https://integrate.api.nvidia.com/v1. If NIM fails, logs
#          the error and returns a clean error message — there is
#          no fallback model.
# Calls:   build_escalation_payload.build_escalation_payload(),
#          classify_task.classify_task() (when classification is
#          missing), NVIDIA NIM REST API.
# Used by: src/discord-handler.js (spawned as a child process via
#          src/routing.js → runPythonSkill).
# ============================================================
"""Escalate a complex request to NVIDIA NIM.

Reads sys.argv[1] as a JSON string with keys "message", "history",
and optionally "classification". On NIM failure, returns a clean
error message to the caller; no fallback model is used.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
sys.path.insert(0, str(SKILLS_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from openai import OpenAI  # noqa: E402

from build_escalation_payload import build_escalation_payload  # noqa: E402
from classify_task import classify_task  # noqa: E402

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
NIM_MODEL = "nvidia/nemotron-3-super-120b-a12b"


def payload_to_nim_messages(payload: dict) -> list[dict]:
    framing = payload.get("framing") or {}
    classification = payload.get("classification") or {}

    triggered = ", ".join(classification.get("triggered_criteria") or []) or "none"
    score = classification.get("score", "?")
    reason = classification.get("complexity_reason", "")

    system_context = (
        "You are receiving a pre-analyzed task from a local Nemotron 4B edge model.\n\n"
        "TASK FRAMING:\n"
        f"{json.dumps(framing, indent=2)}\n\n"
        "COMPLEXITY ANALYSIS:\n"
        f"- Score: {score}/6\n"
        f"- Triggered criteria: {triggered}\n"
        f"- Reason: {reason}\n\n"
        "Deliver a complete, high-quality response to the user's original request. "
        "Do not re-ask clarifying questions — all context has been pre-packaged for you."
    )

    messages: list[dict] = [{"role": "system", "content": system_context}]

    history = payload.get("full_conversation_history") or []
    for m in history[-10:]:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant", "system") and isinstance(content, str) and content:
            messages.append({"role": role, "content": content})

    original_request = framing.get("original_request") or payload.get("user_message") or ""
    if original_request:
        if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != original_request:
            messages.append({"role": "user", "content": original_request})

    return messages


def call_nim(messages: list[dict]) -> str:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY not set in environment")

    client = OpenAI(base_url=NIM_BASE_URL, api_key=api_key)
    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=messages,
        temperature=0.4,
        max_tokens=2048,
    )
    return (response.choices[0].message.content or "").strip()


def escalate(user_message: str, history: list, classification: dict | None = None) -> str:
    if not classification:
        print("[escalate_to_nim] Classification missing; running classifier locally.", file=sys.stderr)
        classification = classify_task(user_message)

    print("[escalate_to_nim] Building framing payload via local Nemotron...", file=sys.stderr)
    payload = build_escalation_payload(user_message, classification, history)
    messages = payload_to_nim_messages(payload)

    score = classification.get("score", "?")

    try:
        print(f"[escalate_to_nim] Calling NIM model {NIM_MODEL}...", file=sys.stderr)
        answer = call_nim(messages)
        return f"**[Cloud Nemotron — Complexity Score {score}/6]**\n\n{answer}"
    except Exception as nim_err:
        print(f"[escalate_to_nim] NIM call failed: {nim_err}", file=sys.stderr)
        return (
            "**[Escalation failed]**\n\n"
            "The cloud Nemotron model on NVIDIA NIM is currently unavailable. "
            "Please try again in a moment.\n\n"
            f"Details: {nim_err}"
        )


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
    classification = args.get("classification")

    print(escalate(message, history, classification))
