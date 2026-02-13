#!/usr/bin/env bash
# Deploy WineBuddy to the LXC container via rsync + restart.
# Usage: ./deploy/deploy.sh <lxc-host>
# Example: ./deploy/deploy.sh 192.168.1.50
#          ./deploy/deploy.sh winebuddy.local

set -euo pipefail

HOST="${1:?Usage: $0 <lxc-host>}"
REMOTE_DIR="/opt/winebuddy-slack-app"

echo "Deploying to ${HOST}:${REMOTE_DIR}..."

rsync -avz --delete \
  --exclude '.venv' \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '*.png' \
  --exclude '*.pptx' \
  . "root@${HOST}:${REMOTE_DIR}/"

echo "Syncing dependencies and restarting service..."
ssh "root@${HOST}" bash -c "'
  cd ${REMOTE_DIR}
  chown -R winebuddy:winebuddy ${REMOTE_DIR}
  su - winebuddy -c \"cd ${REMOTE_DIR} && /home/winebuddy/.local/bin/uv sync\"
  systemctl restart winebuddy
  systemctl status winebuddy --no-pager
'"

echo "Deploy complete."
