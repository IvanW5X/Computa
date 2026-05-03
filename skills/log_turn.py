# Helper for OpenClaw skills: POSTs a turn record to the Computa dashboard
# (http://localhost:3000/log). Pass token counts straight from the model
# response usage block.

import os
import sys
import json
import urllib.request


DASHBOARD_URL = os.environ.get("COMPUTA_DASHBOARD_URL", "http://localhost:3000")


def log_turn(
    session_id: str,
    user_msg: str,
    bot_reply: str,
    user_msg_tokens: int = 0,
    bot_reply_tokens: int = 0,
    local_prompt_tokens: int = 0,
    local_completion_tokens: int = 0,
    cloud_prompt_tokens: int = 0,
    cloud_completion_tokens: int = 0,
    escalated: bool = False,
):
    payload = {
        "session_id": session_id,
        "user_msg": user_msg,
        "bot_reply": bot_reply,
        "user_msg_tokens": user_msg_tokens,
        "bot_reply_tokens": bot_reply_tokens,
        "local_prompt_tokens": local_prompt_tokens,
        "local_completion_tokens": local_completion_tokens,
        "cloud_prompt_tokens": cloud_prompt_tokens,
        "cloud_completion_tokens": cloud_completion_tokens,
        "escalated": bool(escalated),
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{DASHBOARD_URL}/log",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        return json.loads(resp.read())


if __name__ == "__main__":
    # CLI: python log_turn.py <json-payload>
    if len(sys.argv) < 2:
        print("usage: log_turn.py '<json>'", file=sys.stderr)
        sys.exit(2)
    print(log_turn(**json.loads(sys.argv[1])))
