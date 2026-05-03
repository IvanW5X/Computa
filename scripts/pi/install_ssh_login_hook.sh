#!/usr/bin/env bash
# Run once ON THE PI. Adds a one-time hook: first interactive SSH session runs
# ~/computa-openclaw-bootstrap.sh if present, then touches a marker so it
# does not run again.
#
# Usage (on Pi):
#   bash install_ssh_login_hook.sh
#   # or from repo:
#   bash scripts/pi/install_ssh_login_hook.sh

set -euo pipefail

MARKER="${HOME}/.config/computa/openclaw-ssh-bootstrap.done"
HOOK_LINE='# computa-openclaw-ssh-once (managed by Computa)'
SCRIPT="${HOME}/computa-openclaw-bootstrap.sh"
BLOCK=$(cat <<EOF
$HOOK_LINE
if [[ -n "\${SSH_CONNECTION:-}" && -f "$SCRIPT" && ! -f "$MARKER" ]]; then
  bash "$SCRIPT" && mkdir -p "$(dirname "$MARKER")" && touch "$MARKER"
fi
EOF
)

for rc in "$HOME/.bash_profile" "$HOME/.profile" "$HOME/.bashrc"; do
  [[ -f "$rc" ]] || continue
  if grep -qF "$HOOK_LINE" "$rc" 2>/dev/null; then
    echo "Hook already present in $rc"
    exit 0
  fi
done

TARGET="$HOME/.bashrc"
if [[ ! -f "$TARGET" ]]; then
  TARGET="$HOME/.profile"
  touch "$TARGET"
fi

printf '\n%s\n' "$BLOCK" >>"$TARGET"
echo "Appended one-time SSH bootstrap hook to $TARGET"
echo "Place $SCRIPT on the Pi (scp from scripts/pi/openclaw_bootstrap.sh) before your next SSH login."
echo "To re-run setup, remove $MARKER and log in again."
