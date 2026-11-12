# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WineBuddy is a Slack bot application built with Python and slack-bolt, using Socket Mode for real-time communication. It answers wine cellar questions by calling the Claude API, with tools that run the winebuddy CLI.

## Development Commands

```bash
# Install dependencies
uv sync

# Run the app
uv run python main.py

# Ask a question the way the bot does, without Slack (needs ANTHROPIC_API_KEY)
uv run python ask.py "What French wines do I have?"
```

## Required Environment Variables

- `SLACK_BOT_TOKEN` - Bot user OAuth token (xoxb-...)
- `SLACK_APP_TOKEN` - App-level token for Socket Mode (xapp-...)
- `ANTHROPIC_API_KEY` - Claude API key
- `WINEBUDDY_DIR` - optional; the winebuddy repo with `winebuddy.py`, `SKILL.md` and `cellar.csv` (default `~/.winebuddy`)

## Architecture

Slack bot (`main.py`) using slack-bolt's Socket Mode adapter; `ask.py` holds the Claude side. The app listens for:
- `message` events - Passes the message to `ask.ask()` and replies in the message's thread (ignores bot messages to prevent loops). Each thread is a conversation: a reply in a thread is asked along with the thread so far (read back via `conversations.replies`, last `MAX_HISTORY_MESSAGES`), sent as earlier messages in the API request. Nothing is stored.
- `app_mention` events - Responds when the bot is @mentioned

`ask.ask()` runs `winebuddy.py --refresh` (rebuilds `cellar.db` if `cellar.csv` changed), then calls the Claude API (Sonnet) with `SKILL.md` from `WINEBUDDY_DIR` as the system prompt and two tools, `query_wines` and `discover`, which run `winebuddy.py` with an argument list (no shell), looping until Claude answers (at most `MAX_TOOL_ROUNDS`). Responses stream back and update the Slack message in place every 2 seconds.
