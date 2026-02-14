#!/usr/bin/env bash
# Debug winebuddy on the LXC container by showing log messages
# Usage: ./deploy/debug.sh <lxc-host>
# Example: ./deploy/debug.sh 192.168.1.50


HOST="${1:?Usage: $0 <lxc-host>}"

echo "Running journalctl -u winebuddy -f"
ssh "root@${HOST}" bash -c "'journalctl -u winebuddy -f'"
