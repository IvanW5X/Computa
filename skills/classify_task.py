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

CLASSIFIER_SYSTEM_PROMPT = """You are a task complexity router. Classify the user message; do not answer it.

Add 1 point for each criterion that clearly applies. Be strict — if it is borderline, do NOT count it.

1. MULTI_STEP: more than two sequential reasoning steps. A single calculation, lookup, or short answer is not multi-step.
2. SYNTHESIS: must combine information from multiple distinct sources or domains. Restating one fact is not synthesis.
3. SPECIALIZED_DOMAIN: requires deep professional expertise (law, medicine, finance, engineering, science). General-knowledge questions in these fields do not count.
4. LONG_FORM: the user explicitly asks for output longer than ~500 words.
5. AMBIGUOUS: genuinely underspecified; a reasonable model would have to guess at intent.
6. WORLD_KNOWLEDGE: requires obscure or detailed factual knowledge. Common facts, basic definitions, arithmetic, and greetings do not count.

ROUTING:
- Score 0-2 → "local"
- Score 3+  → "escalate"

Output one JSON object, no other text:
{"score": <0-6>, "triggered_criteria": [<names>], "route": "local"|"escalate", "summary": "<one sentence>", "complexity_reason": "<one sentence>"}
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
        route = "escalate" if score >= 5 else "local"
    elif route == "escalate" and score < 5:
        route = "local"
    elif route == "local" and score >= 5:
        route = "escalate"

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
