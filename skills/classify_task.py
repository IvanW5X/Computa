# ============================================================
# skills/classify_task.py
# ============================================================
# Role: Tier 1 — Local Inference (complexity router)
# Purpose: Sends the user message to nemotron-mini via Ollama and
#          returns a JSON complexity classification with keys
#          score, triggered_criteria, route, summary, and
#          complexity_reason. Forces JSON output and falls back
#          to a safe-escalate result on parse failure.
# Calls:   Ollama at http://localhost:11434/v1.
# Used by: src/routing.js (via child-process spawn);
#          skills/escalate_to_nim.py imports classify_task() when
#          the caller did not supply a classification.
# ============================================================
"""Complexity classifier skill.

Reads sys.argv[1] as a JSON string with key "message", asks the local
nemotron-mini model (via Ollama's OpenAI-compatible API) to score the task
on a 6-point rubric, and prints the resulting classification JSON to stdout.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from openai import OpenAI  # noqa: E402

OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "nemotron-mini"

CLASSIFIER_SYSTEM_PROMPT = """You are a task complexity router for a multi-tier AI agent pipeline.

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
- Score 0-1: Handle locally. Route = "local"
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


def _client() -> OpenAI:
    return OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


def _safe_extract_json(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


def _normalize(parsed: dict, user_message: str) -> dict:
    score = parsed.get("score")
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(6, score))

    route = parsed.get("route")
    if route not in ("local", "escalate"):
        route = "escalate" if score >= 2 else "local"

    triggered = parsed.get("triggered_criteria")
    if not isinstance(triggered, list):
        triggered = []

    summary = parsed.get("summary") or user_message[:100]
    reason = parsed.get("complexity_reason") or ""

    return {
        "score": score,
        "triggered_criteria": triggered,
        "route": route,
        "summary": str(summary),
        "complexity_reason": str(reason),
    }


def classify_task(user_message: str) -> dict:
    user_message = (user_message or "").strip()
    if not user_message:
        return {
            "score": 0,
            "triggered_criteria": ["EMPTY_INPUT"],
            "route": "local",
            "summary": "",
            "complexity_reason": "Empty input; nothing to classify.",
        }

    try:
        response = _client().chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.0,
            max_tokens=256,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        print(f"[classify_task] Ollama error: {e}", file=sys.stderr)
        return {
            "score": 3,
            "triggered_criteria": ["CLASSIFIER_ERROR"],
            "route": "escalate",
            "summary": user_message[:100],
            "complexity_reason": f"Classifier call failed: {e}",
        }

    raw = (response.choices[0].message.content or "").strip()
    parsed = _safe_extract_json(raw)
    if not parsed:
        return {
            "score": 3,
            "triggered_criteria": ["PARSE_FAILURE"],
            "route": "escalate",
            "summary": user_message[:100],
            "complexity_reason": "Classification parse failed; escalating by default.",
        }

    return _normalize(parsed, user_message)


def _parse_args() -> str:
    if len(sys.argv) < 2:
        return ""
    raw = sys.argv[1]
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return str(data.get("message", "") or "")
        return str(data)
    except json.JSONDecodeError:
        return raw


if __name__ == "__main__":
    message = _parse_args()
    result = classify_task(message)
    print(json.dumps(result))
