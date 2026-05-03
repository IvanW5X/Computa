# ============================================================
# scripts/warmup.sh
# ============================================================
# Role: Tier 1 — Local Inference (operational helper)
# Purpose: Runs a throwaway inference call against Ollama so
#          nemotron-mini is loaded into VRAM before a demo and
#          the first real bot response is not slow.
# Calls:   Ollama CLI (`ollama run nemotron-mini`).
# Used by: developers/operators manually before `npm start`.
# ============================================================
#!/usr/bin/env bash
set -euo pipefail
ollama run nemotron-mini "warmup: respond with one short word." >/dev/null
echo "[warmup] nemotron-mini loaded into Ollama."
