#!/usr/bin/env bash

source deployment.env
export SLACK_BOT_TOKEN
export SLACK_APP_TOKEN
export ANTHROPIC_API_KEY
/home/winebuddy/.local/bin/uv run python main.py
