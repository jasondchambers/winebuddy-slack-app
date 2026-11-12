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

# Only the files the bot runs from (an allowlist, so tests, caches and stray files stay behind).
# --delete removes files dropped from these paths; anything else on the server, like its .venv, is left alone.
rsync -avz --delete \
  --include '/main.py' --include '/ask.py' --include '/run.sh' \
  --include '/pyproject.toml' --include '/uv.lock' --include '/.python-version' \
  --include '/deployment.env' --include '/deploy/' --include '/deploy/**' \
  --exclude '*' \
  ./ "root@${HOST}:${REMOTE_DIR}/"

echo "Syncing dependencies and restarting service..."
ssh "root@${HOST}" bash -c "'
  cd ${REMOTE_DIR}
  chown -R winebuddy:winebuddy ${REMOTE_DIR}
  su - winebuddy -c \"[ -d ~/.winebuddy ] || git clone https://github.com/jasondchambers/winebuddy.git ~/.winebuddy\"
  su - winebuddy -c \"cd ~/.winebuddy && git pull --ff-only\"
  su - winebuddy -c \"cd ${REMOTE_DIR} && /home/winebuddy/.local/bin/uv sync --locked --no-dev\"
  systemctl restart winebuddy
  systemctl status winebuddy --no-pager
'"

echo "Deploy complete."
