# WineBuddy Slack App — Deployment Guide

Deploy the WineBuddy Slack bot to a Proxmox LXC container running Debian 12.

## Prerequisites

- Proxmox host with access to create LXC containers
- Environment variables containing values for (see deployment.env file below)
  - `SLACK_BOT_TOKEN`
  - `SLACK_APP_TOKEN`
  - `ANTHROPIC_API_KEY`
- SSH access from your dev machine to the LXC

---

## One-Time LXC Setup

### 1. Create the LXC container in Proxmox

- Template: Debian 12
- CPU: 2 cores
- RAM: 2 GB
- Disk: 16 GB
- Network: bridge `vmbr0`, DHCP or static IP
- No inbound port forwarding needed (Socket Mode is outbound-only)

Enable SSH root login for initial setup (password or key-based).

### 2. Create the deployment.env file

During development, secrets are managed using 1Password via the 1Password CLI (op). They are stored in Environments which at the time of writing is a beta feature.

You will also need to create a service account in 1Password if not done so already.

To streamline things in the deployed environment, 1Password is not used. Instead
the deployment.env file must be generated from the secrets in 1Password and deployed
onto the target LXC container.

A local env file can be created from 1Password. It is a special file and so to create a regular file, it needs to be copied to create the deployment.env file.


### 3. Deploy the code to the LXC

Install `rsync` on the container first (not included in the base Debian template):

```bash
ssh root@<lxc-ip> "apt-get update && apt-get install -y rsync"
```

Then rsync the files the bot runs from (the same allowlist `deploy.sh` uses) from your dev machine:

```bash
rsync -avz --include '/main.py' --include '/ask.py' --include '/run.sh' --include '/pyproject.toml' \
  --include '/uv.lock' --include '/.python-version' --include '/deployment.env' \
  --include '/deploy/' --include '/deploy/**' --exclude '*' \
  ./ root@<lxc-ip>:/opt/winebuddy-slack-app/
```

### 4. Run the provisioning script

SSH into the LXC and run the setup script:

```bash
ssh root@<lxc-ip>
bash /opt/winebuddy-slack-app/deploy/setup-lxc.sh
```

This installs uv, creates the `winebuddy` system user, and enables the systemd unit.

**Note:** The setup script installs `uv` as root. It must also be installed for the `winebuddy` user:

```bash
su - winebuddy -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
```

### 5. Check the Claude API key

Once the cellar data is deployed (see below), check as the `winebuddy` user that the bot can reach the Claude
API with the key in deployment.env and look the cellar up:

```bash
cd /opt/winebuddy-slack-app
(set -a; source deployment.env; ~/.local/bin/uv run --no-dev python ask.py "What French wines do I have?")
```

### 6. Fix file ownership

Ensure the `winebuddy` user owns the app directory (including the `.venv` uv creates):

```bash
exit  # back to root
chown -R winebuddy:winebuddy /opt/winebuddy-slack-app
```

### 7. Start the service

```bash
systemctl start winebuddy
```

---

## Deploying Cellar Data

The wine cellar database (`cellar.csv`) is managed separately in the private repo `github.com/jasondchambers/cellar`. See that repo's deployment instructions for details on deploying cellar data to `/home/winebuddy/.winebuddy/cellar.csv`.

---

## Verification

### Check service status

```bash
systemctl status winebuddy
```

Should show `active (running)`.

### Watch logs

```bash
journalctl -u winebuddy -f
```

Look for: `Chat app is running with Socket Mode!`

### Functional test

Send a DM to the bot in Slack and verify it responds with wine recommendations.


---

## Subsequent Deploys

From your local dev machine:

```bash
./deploy/deploy.sh <lxc-ip>
```

This rsyncs the code, pulls the latest winebuddy (CLI and `SKILL.md`) into `~/.winebuddy`, runs `uv sync --no-dev`
(runtime dependencies only; the dev tools are for local checks and CI), and restarts the service.

---

## Troubleshooting

### Service fails to start

```bash
journalctl -u winebuddy --no-pager -n 50
```

Common causes:
- uv not on PATH — check `/home/winebuddy/.local/bin/uv` exists
- Permission denied on `.venv` — run `chown -R winebuddy:winebuddy /opt/winebuddy-slack-app` as root


### Winebuddy lookups not working

The bot reads `SKILL.md` and runs `winebuddy.py` from `~/.winebuddy`, which `deploy.sh` clones and pulls. Verify the `winebuddy` user has internet access and git works:

```bash
su - winebuddy -c "git ls-remote https://github.com/jasondchambers/winebuddy.git"
```

You can also pre-clone it manually:

```bash
su - winebuddy -c "git clone https://github.com/jasondchambers/winebuddy.git ~/.winebuddy"
```

## Debugging

You can view the log messages as follows
```bash
debug.sh
```


## Anthropic Cost Monitoring

Visit the [Claude Console](https://platform.claude.com/settings/billing) to manage billing and usage associated with the API key.
