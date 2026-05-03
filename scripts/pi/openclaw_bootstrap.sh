#!/usr/bin/env bash
# Run on the Raspberry Pi (or any OpenClaw host). Idempotent: safe to re-run.
#
# - Ensures Discord is enabled with token from env (DISCORD_BOT_TOKEN) or
#   ~/.config/computa/openclaw.env
# - Ensures WhatsApp channel exists and DM policy is pairing
# - Walks through WhatsApp Web login (QR) when not linked
# - Lists pending pairing requests and can approve by code (WhatsApp / Discord)
#
# Env:
#   DISCORD_BOT_TOKEN   - Discord bot token (optional if already in openclaw.env)
#   COMPUTA_OPENCLAW_ENV - override path to env file (default ~/.config/computa/openclaw.env)
#   SKIP_WHATSAPP_LOGIN - if 1, skip interactive QR login
#   SKIP_PAIRING_PROMPT - if 1, do not prompt to approve pairing codes

set -euo pipefail

ENV_FILE="${COMPUTA_OPENCLAW_ENV:-$HOME/.config/computa/openclaw.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  set -a && source "$ENV_FILE" && set +a
fi

die() {
  echo "computa/openclaw_bootstrap: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing '$1' — install OpenClaw CLI (see https://docs.openclaw.ai)"
}

need_cmd openclaw

mkdir -p "$HOME/.config/computa"
if [[ -n "${DISCORD_BOT_TOKEN:-}" && ! -f "$ENV_FILE" ]]; then
  umask 077
  printf 'export DISCORD_BOT_TOKEN=%q\n' "$DISCORD_BOT_TOKEN" >"$ENV_FILE"
  echo "Wrote Discord token to $ENV_FILE (chmod 600). Sourcing for this session."
  # shellcheck source=/dev/null
  set -a && source "$ENV_FILE" && set +a
fi

if [[ -z "${DISCORD_BOT_TOKEN:-}" ]]; then
  echo "Note: DISCORD_BOT_TOKEN is not set. Add it to $ENV_FILE:"
  echo "  echo \"export DISCORD_BOT_TOKEN='your-bot-token'\" > $ENV_FILE && chmod 600 $ENV_FILE"
  echo "Discord gateway login will fail until this is set."
else
  echo "Discord token is available (DISCORD_BOT_TOKEN set)."
fi

echo "Applying OpenClaw channel defaults (Discord + WhatsApp pairing)..."
# Discord: match Computa's discord.patch.json5 — token via env
openclaw config set channels.discord.enabled true 2>/dev/null || true
openclaw config set channels.discord.dmPolicy pairing 2>/dev/null || true
openclaw config set 'channels.discord.token' '{"source":"env","provider":"default","id":"DISCORD_BOT_TOKEN"}' 2>/dev/null || {
  echo "Could not set channels.discord.token via CLI; ensure openclaw.json5 references env DISCORD_BOT_TOKEN."
}

# WhatsApp
openclaw config set channels.whatsapp.dmPolicy pairing 2>/dev/null || true
openclaw channels add --channel whatsapp 2>/dev/null || echo "(whatsapp channel already present or add skipped)"

if [[ "${SKIP_WHATSAPP_LOGIN:-0}" != "1" ]]; then
  if [[ -t 0 ]]; then
    echo ""
    echo "WhatsApp: link this gateway with WhatsApp Web (QR). Press Enter to start login, or Ctrl+C to skip."
    read -r _
    openclaw channels login --channel whatsapp || echo "WhatsApp login exited with an error — re-run: openclaw channels login --channel whatsapp"
  else
    echo "No TTY; skipping QR login. SSH with -t or run: openclaw channels login --channel whatsapp"
  fi
else
  echo "SKIP_WHATSAPP_LOGIN=1 — not running WhatsApp QR login."
fi

echo ""
echo "=== Pending pairing requests (approve new DMs) ==="
openclaw pairing list whatsapp 2>/dev/null || true
openclaw pairing list discord 2>/dev/null || true

if [[ "${SKIP_PAIRING_PROMPT:-0}" != "1" && -t 0 ]]; then
  echo ""
  read -r -p "Approve a pairing code now? Enter code (empty to skip): " code || true
  code="${code// /}"
  if [[ -n "$code" ]]; then
    openclaw pairing approve whatsapp "$code" 2>/dev/null && echo "Approved WhatsApp pairing $code" || true
    openclaw pairing approve discord "$code" 2>/dev/null && echo "Approved Discord pairing $code" || true
  fi
fi

echo ""
echo "Next: start the gateway (e.g. openclaw gateway) with DISCORD_BOT_TOKEN in the environment."
echo "Tip: source $ENV_FILE before starting the gateway, or use a systemd unit with EnvironmentFile=."
