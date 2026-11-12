"""Shared setup: lets main.py and ask.py be imported without real Slack or Anthropic credentials.

main.py builds its Slack App when imported, and the App checks its token with Slack (auth.test), so that
check is stubbed here. Nothing in the tests talks to Slack, the Claude API or the winebuddy CLI.
"""

import os
from unittest import mock

from slack_sdk import WebClient

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

with mock.patch.object(WebClient, "auth_test",
                       return_value={"ok": True, "user_id": "UBOT", "bot_id": "BBOT", "team_id": "T1"}):
    import main  # noqa: E402,F401  (imported here so every test module gets the stubbed App)


def unescape(text: str) -> str:
    r"""Turn backslash escapes written in a feature file (\n, \x00) into the characters they stand for."""
    return text.encode("latin-1", "backslashreplace").decode("unicode_escape")
