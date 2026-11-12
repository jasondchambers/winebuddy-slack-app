#!/usr/bin/env bash
# Deploy WineBuddy to the LXC container via rsync + restart.
# Usage: ./deploy/deploy.sh <lxc-host>
# Example: ./deploy/deploy.sh 192.168.1.50
#          ./deploy/deploy.sh winebuddy.local

# Check to see if we are in the correct directory

if [[ $(basename "$PWD") != "winebuddy-slack-app" ]]; then
  echo "This script needs to be run from winebuddy-slack-app"
  exit 1
fi

set -euo pipefail

HOST="${1:?Usage: $0 <lxc-host>}"
REMOTE_DIR="/opt/winebuddy-slack-app"

echo "Deploying to ${HOST}:${REMOTE_DIR}..."

rsync -avz --delete \
  --exclude '.venv' \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.claude' \
  --exclude '*.png' \
  --exclude '*.pptx' \
  . "root@${HOST}:${REMOTE_DIR}/"

echo "Syncing dependencies and restarting service..."
ssh "root@${HOST}" bash -c "'
  cd ${REMOTE_DIR}
  chown -R winebuddy:winebuddy ${REMOTE_DIR}
  su - winebuddy -c \"[ -d ~/.winebuddy ] || git clone https://github.com/jasondchambers/winebuddy.git ~/.winebuddy\"
  su - winebuddy -c \"cd ~/.winebuddy && git pull --ff-only\"
  su - winebuddy -c \"cd ${REMOTE_DIR} && /home/winebuddy/.local/bin/uv sync\"
  systemctl restart winebuddy
  systemctl status winebuddy --no-pager
'"

echo "Deploy complete."
