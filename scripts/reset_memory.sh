# ============================================================
# scripts/reset_memory.sh
# ============================================================
# Role: Tier 2 — Orchestration (operational helper)
# Purpose: Deletes data/memory.db so the bot starts the next
#          session with no stored conversation history. Useful
#          before a demo or when debugging routing behavior.
# Calls:   filesystem (rm of data/memory.db and its WAL files).
# Used by: developers/operators manually.
# ============================================================
#!/usr/bin/env bash
set -euo pipefail
rm -f data/memory.db data/memory.db-wal data/memory.db-shm
echo "[reset_memory] data/memory.db removed."
