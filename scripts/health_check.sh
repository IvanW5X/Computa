# ============================================================
# scripts/health_check.sh
# ============================================================
# Role: Tier 1 + Tier 3 (operational helper)
# Purpose: Pings the local Ollama endpoint and the NVIDIA NIM
#          endpoint to verify both inference tiers are reachable
#          before running the bot.
# Calls:   http://localhost:11434/api/tags (Ollama),
#          https://integrate.api.nvidia.com/v1/models (NIM).
# Used by: developers/operators manually before `npm start`.
# ============================================================
#!/usr/bin/env bash
set -uo pipefail

echo "[health] Checking Ollama..."
if curl -fsS http://localhost:11434/api/tags >/dev/null; then
  echo "[health] Ollama: OK"
else
  echo "[health] Ollama: FAIL (is the daemon running?)"
fi

echo "[health] Checking NVIDIA NIM..."
if [ -z "${NVIDIA_API_KEY:-}" ]; then
  echo "[health] NIM: SKIP (NVIDIA_API_KEY not set)"
else
  if curl -fsS -H "Authorization: Bearer ${NVIDIA_API_KEY}" \
       https://integrate.api.nvidia.com/v1/models >/dev/null; then
    echo "[health] NIM: OK"
  else
    echo "[health] NIM: FAIL"
  fi
fi
