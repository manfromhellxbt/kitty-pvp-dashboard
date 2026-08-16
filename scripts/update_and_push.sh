#!/usr/bin/env bash
# Kitty PVP Dashboard — update data.json every 6h and push to GitHub Pages
set -euo pipefail

REPO="/opt/data/kitty-pvp-dashboard"
LOG="/opt/data/logs/kitty-pvp-update.log"
LOCK="/tmp/kitty-pvp-update.lock"
KEY_FILE="/opt/data/config/opensea_key.txt"
export HOME=/opt/data
export GIT_SSH_COMMAND="ssh -i /opt/data/.ssh/id_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=no"
export OPENSEA_API_KEY="$(cat "$KEY_FILE" 2>/dev/null || true)"

mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }

# prevent concurrent runs
exec 9>"$LOCK"
if ! flock -n 9; then
  log "already running, skip"
  exit 0
fi

cd "$REPO"
log "start update"

# pull latest in case of remote changes
git pull --ff-only origin main 2>&1 | tee -a "$LOG" || true

# fetch fresh data
if ! python3 scripts/fetch_data.py 2>&1 | tee -a "$LOG"; then
  log "ERROR: fetch_data.py failed"
  exit 1
fi

# only commit if data.json actually changed
if git diff --quiet -- data.json 2>/dev/null; then
  log "no data changes, skip commit"
  exit 0
fi

git add data.json
git -c user.email="hermes@local" -c user.name="Hermes Bot" commit -m "data: auto-update $(date -u +%Y-%m-%dT%H:%MZ)" 2>&1 | tee -a "$LOG"
git push origin main 2>&1 | tee -a "$LOG"
log "done"
