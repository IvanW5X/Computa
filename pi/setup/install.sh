#!/usr/bin/env bash
# Target path on the Pi: /home/yelopi/setup/install.sh
#
# Idempotent installer for the AI metrics dashboard.
#
# Pre-conditions (already true on this Pi):
#   * user `yelopi` exists, home /home/yelopi
#   * /home/yelopi/router/router.py is the live router on :11435
#   * /home/yelopi/router/.env contains NVIDIA_API_KEY etc.
#   * ai-router.service and openclaw-gateway.service are running
#   * Python 3.13 is installed (Pi OS Lite Bookworm/Trixie)
#
# Run from the directory that contains this script's repo:
#   bash pi/setup/install.sh
#
# Re-run any time -- every step is safe to repeat.

set -Eeuo pipefail

# ---------- locate sources -------------------------------------------------

SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_REPO_DIR="$(cd "${SETUP_DIR}/.." && pwd)"
DASH_SRC="${PI_REPO_DIR}/dashboard"
ROUTER_SRC="${PI_REPO_DIR}/router"

YELOPI_HOME="/home/yelopi"
DASH_DIR="${YELOPI_HOME}/dashboard"
ROUTER_DIR="${YELOPI_HOME}/router"

log()  { printf '\n\033[1;36m[install]\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m[install WARN]\033[0m %s\n' "$*"; }

if [[ "${EUID}" -eq 0 ]]; then
  warn "Running as root. The script uses sudo where needed; running as yelopi is preferred."
fi

# ---------- 1. dashboard directory + files --------------------------------

log "Creating ${DASH_DIR}"
sudo install -d -o yelopi -g yelopi -m 0755 "${DASH_DIR}"

log "Copying server.py and schema.sql"
sudo install -o yelopi -g yelopi -m 0755 "${DASH_SRC}/server.py"   "${DASH_DIR}/server.py"
sudo install -o yelopi -g yelopi -m 0644 "${DASH_SRC}/schema.sql"  "${DASH_DIR}/schema.sql"

# ---------- 2. SQLite database --------------------------------------------

if [[ ! -f "${DASH_DIR}/requests.db" ]]; then
  log "Initialising ${DASH_DIR}/requests.db from schema.sql"
  sudo -u yelopi sqlite3 "${DASH_DIR}/requests.db" < "${DASH_DIR}/schema.sql"
else
  # CREATE TABLE IF NOT EXISTS makes this safe to re-apply.
  log "requests.db exists; re-applying schema (idempotent)"
  sudo -u yelopi sqlite3 "${DASH_DIR}/requests.db" < "${DASH_DIR}/schema.sql"
fi
sudo chown yelopi:yelopi "${DASH_DIR}/requests.db"

# ---------- 3. router.py with logging -------------------------------------

if [[ -f "${ROUTER_DIR}/router.py" ]]; then
  log "Backing up existing router.py to router.py.bak-$(date +%Y%m%dT%H%M%S)"
  sudo -u yelopi cp -a "${ROUTER_DIR}/router.py" \
    "${ROUTER_DIR}/router.py.bak-$(date +%Y%m%dT%H%M%S)"
fi

log "Installing router.py with SQLite logging into ${ROUTER_DIR}"
sudo install -d -o yelopi -g yelopi -m 0755 "${ROUTER_DIR}"
sudo install -o yelopi -g yelopi -m 0755 "${ROUTER_SRC}/router.py" "${ROUTER_DIR}/router.py"

# ---------- 4. systemd unit -----------------------------------------------

log "Installing /etc/systemd/system/ai-dashboard.service"
sudo install -m 0644 "${SETUP_DIR}/ai-dashboard.service" /etc/systemd/system/ai-dashboard.service

sudo systemctl daemon-reload
sudo systemctl enable --now ai-dashboard.service

# ---------- 5. restart router so logging takes effect ---------------------

if systemctl list-unit-files | grep -q '^ai-router\.service'; then
  log "Restarting ai-router.service to pick up the new router.py"
  sudo systemctl restart ai-router.service
else
  warn "ai-router.service not found. Restart your router process manually."
fi

# ---------- 6. verify ------------------------------------------------------

log "Verifying ai-dashboard.service status"
sudo systemctl --no-pager --full status ai-dashboard.service || true

log "Verifying /api/stats endpoint"
if curl -fsS "http://127.0.0.1:3000/api/stats" >/dev/null; then
  log "OK -- /api/stats responded."
else
  warn "/api/stats did not respond. Check: sudo journalctl -u ai-dashboard -e"
fi

PI_IP="$(hostname -I | awk '{print $1}')"
cat <<EOF

================================================================
  Dashboard install complete.
================================================================
  Open this from any device on the LAN:
      http://${PI_IP}:3000

  Logs:
      sudo journalctl -u ai-dashboard.service -f
      sudo journalctl -u ai-router.service -f
================================================================

EOF
