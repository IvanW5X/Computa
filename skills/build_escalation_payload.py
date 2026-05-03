# ============================================================
# skills/build_escalation_payload.py
# ============================================================
# Role: Tier 1 — Local Inference (escalation framing agent)
# Purpose: Uses nemotron-mini via Ollama to draft a structured
#          handoff package (original_request, task_type,
#          key_constraints, relevant_context, suggested_approach,
#          expected_output_format, priority_flags) so the cloud
#          model can answer immediately without re-asking
#          clarifying questions.
# Calls:   Ollama at http://localhost:11434/v1.
# Used by: skills/escalate_to_nim.py (import); also runnable as
#          a standalone script that prints the payload as JSON.
# ============================================================
"""Build a structured handoff payload for escalation to the cloud Nemotron model.

Imported by escalate_to_nim.py and also runnable as a standalone script.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from openai import OpenAI  # noqa: E402

OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "nemotron-mini"
TARGET_MODEL = "nvidia/nemotron-3-super-120b-a12b"

FRAMING_PROMPT = """You are preparing a handoff package for a more powerful AI model.
Given the user's request and the conversation history, produce a structured JSON object
that gives the receiving model full context to answer immediately, without needing
to re-ask clarifying questions.

Output JSON only, no other text:
{
  "original_request": "<verbatim user message>",
  "task_type": "<one of: analysis | generation | reasoning | code | research | other>",
  "key_constraints": ["<list of explicit constraints or requirements from the user>"],
  "relevant_context": "<summary of relevant conversation history>",
  "suggested_approach": "<brief recommendation for how to tackle this task>",
  "expected_output_format": "<describe what the final answer should look like>",
  "priority_flags": ["<LONG_FORM | MULTI_STEP | SPECIALIZED_DOMAIN | etc>"]
}
"""


def _client() -> OpenAI:
    return OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


def _safe_extract_json(raw: str) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return {}
    return {}


def _summarize_history(history: list) -> str:
    if not history:
        return "(no prior turns)"
    parts: list[str] = []
    for m in history[-6:]:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "")).upper()
        content = str(m.get("content", ""))[:200]
        if role and content:
            parts.append(f"{role}: {content}")
    return "\n".join(parts) or "(no prior turns)"


def build_escalation_payload(user_message: str, classification: dict, history: list) -> dict:
    classification = classification or {}
    history = history or []
    history_summary = _summarize_history(history)

    framing_input = (
        f"User request: {user_message}\n\n"
        f"Recent conversation:\n{history_summary}\n\n"
        f"Classifier output:\n{json.dumps(classification, indent=2)}"
    )

    framing: dict = {}
    try:
        response = _client().chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": FRAMING_PROMPT},
                {"role": "user", "content": framing_input},
            ],
            temperature=0.1,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""
        framing = _safe_extract_json(raw)
    except Exception as e:
        print(f"[build_escalation_payload] Framing call failed: {e}", file=sys.stderr)

    if not framing:
        framing = {
            "original_request": user_message,
            "task_type": "other",
            "key_constraints": [],
            "relevant_context": history_summary,
            "suggested_approach": "Answer the original request thoroughly with structured reasoning.",
            "expected_output_format": "Plain text response, well-structured.",
            "priority_flags": classification.get("triggered_criteria", []) or [],
        }
    else:
        framing.setdefault("original_request", user_message)
        framing.setdefault("task_type", "other")
        framing.setdefault("key_constraints", [])
        framing.setdefault("relevant_context", history_summary)
        framing.setdefault("suggested_approach", "")
        framing.setdefault("expected_output_format", "")
        framing.setdefault(
            "priority_flags", classification.get("triggered_criteria", []) or []
        )

    return {
        "schema_version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "framing": framing,
        "full_conversation_history": history,
        "originating_model": OLLAMA_MODEL,
        "target_model": TARGET_MODEL,
    }


if __name__ == "__main__":
    args: dict = {}
    if len(sys.argv) > 1:
        try:
            args = json.loads(sys.argv[1])
            if not isinstance(args, dict):
                args = {"message": str(args)}
        except json.JSONDecodeError:
            args = {"message": sys.argv[1]}

    payload = build_escalation_payload(
        str(args.get("message", "") or ""),
        args.get("classification") or {},
        args.get("history") or [],
    )
    print(json.dumps(payload))
