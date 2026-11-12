# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WineBuddy is a Slack bot application built with Python and slack-bolt, using Socket Mode for real-time communication.

## Development Commands

```bash
# Install dependencies
uv sync

# Run the app
uv run python main.py
```

## Required Environment Variables

- `SLACK_BOT_TOKEN` - Bot user OAuth token (xoxb-...)
- `SLACK_APP_TOKEN` - App-level token for Socket Mode (xapp-...)

## Architecture

Single-file Slack bot (`main.py`) using slack-bolt's Socket Mode adapter. The app listens for:
- `message` events - Asks Claude Code (`claude -p /winebuddy`) and replies in the message's thread (ignores bot messages to prevent loops). Each thread is a conversation: a reply in a thread is asked along with the thread so far (read back via `conversations.replies`, last `MAX_HISTORY_MESSAGES`), sent as a transcript in the prompt. Nothing is stored.
- `app_mention` events - Responds when the bot is @mentioned
