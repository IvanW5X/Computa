#!/usr/bin/env bash
# From your laptop: SSH to the Pi, push the bootstrap script, and run it with a TTY
# so WhatsApp QR and pairing prompts work.
#
# Usage:
#   ./scripts/pi/ssh_openclaw_pi.sh pi@raspberrypi.local
#   DISCORD_BOT_TOKEN=... ./scripts/pi/ssh_openclaw_pi.sh pi@raspberrypi.local
#
# The remote script is installed as ~/computa-openclaw-bootstrap.sh and can be
# re-run anytime: ssh -t pi@host bash ~/computa-openclaw-bootstrap.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REMOTE_SCRIPT_SRC="$ROOT/scripts/pi/openclaw_bootstrap.sh"

usage() {
  echo "usage: $0 [ssh-options ...] -- user@hostname" >&2
  echo "example: $0 -p 2222 -- pi@raspberrypi.local" >&2
  echo "         DISCORD_BOT_TOKEN=... $0 -- pi@raspberrypi.local" >&2
  exit 1
}

SSH_EXTRA=()
if [[ $# -eq 1 ]]; then
  HOST="$1"
else
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--" ]]; then
      shift
      break
    fi
    SSH_EXTRA+=("$1")
    shift
  done
  [[ $# -ge 1 ]] || usage
  HOST="$1"
fi

if [[ ! -f "$REMOTE_SCRIPT_SRC" ]]; then
  echo "missing $REMOTE_SCRIPT_SRC" >&2
  exit 1
fi

scp "${SSH_EXTRA[@]}" "$REMOTE_SCRIPT_SRC" "$HOST:computa-openclaw-bootstrap.sh"

exec ssh -t "${SSH_EXTRA[@]}" "$HOST" bash -s <<EOF
export DISCORD_BOT_TOKEN=$(printf '%q' "${DISCORD_BOT_TOKEN:-}")
bash "\$HOME/computa-openclaw-bootstrap.sh"
EOF
