#!/usr/bin/env bash
# One-time provisioning script for the WineBuddy LXC container.
# Run as root inside a fresh Debian 12 LXC.

set -euo pipefail

# 1. System packages
apt-get update && apt-get install -y curl git ca-certificates gnupg

# 2. Node.js 22.x (LTS) via NodeSource
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

# 3. Claude Code CLI
npm install -g @anthropic-ai/claude-code

# 4. uv (Python package manager — handles Python 3.14 install too)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 5. Doppler CLI
curl -sLf --retry 3 --tlsv1.2 --proto "=https" \
  'https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key' \
  | gpg --dearmor -o /usr/share/keyrings/doppler-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/doppler-archive-keyring.gpg] https://packages.doppler.com/public/cli/deb/debian any-version main" \
  | tee /etc/apt/sources.list.d/doppler-cli.list
apt-get update && apt-get install -y doppler

# 6. Create app user
useradd --system --create-home --shell /bin/bash winebuddy

# 7. Create app directory
mkdir -p /opt/winebuddy-slack-app
chown winebuddy:winebuddy /opt/winebuddy-slack-app

# 8. Install systemd unit
cp /opt/winebuddy-slack-app/deploy/winebuddy.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable winebuddy

echo "Setup complete. Next steps:"
echo "  1. rsync app code to /opt/winebuddy-slack-app/"
echo "  2. Run 'doppler login' as the winebuddy user"
echo "  3. Run 'doppler setup' in /opt/winebuddy-slack-app as the winebuddy user"
echo "  4. Start: systemctl start winebuddy"
