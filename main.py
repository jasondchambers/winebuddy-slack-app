import os
import re
import subprocess
from collections import defaultdict
from time import time
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

MAX_MESSAGE_LENGTH = 2000
RATE_LIMIT_SECONDS = 5

# Track last request time per user
user_last_request: dict[str, float] = defaultdict(float)


def sanitize_input(text: str) -> str | None:
    """Sanitize and validate user input.

    Returns None if input is invalid, otherwise returns cleaned text.
    """
    if not text or len(text) > MAX_MESSAGE_LENGTH:
        return None

    # Strip control characters (except newlines and tabs)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    return text.strip() or None


def is_rate_limited(user_id: str) -> bool:
    """Check if user has exceeded rate limit.

    Returns True if rate limited, False otherwise.
    Updates the last request time if not limited.
    """
    now = time()
    if now - user_last_request[user_id] < RATE_LIMIT_SECONDS:
        return True
    user_last_request[user_id] = now
    return False


# Initialize the app with your tokens
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))


# Event handler for messages
@app.event("message")
def handle_message(event, say, logger):
    """Invoke Claude Code with the message and return the response"""

    # Ignore bot messages to prevent infinite loops
    if event.get("bot_id"):
        return

    user = event.get("user")

    # Check rate limit
    if is_rate_limited(user):
        logger.warning(f"Rate limited user {user}")
        say(f"Please wait {RATE_LIMIT_SECONDS} seconds between requests.")
        return

    # Get and sanitize the message text
    raw_text = event.get("text", "")
    text = sanitize_input(raw_text)

    if text is None:
        logger.warning(f"Invalid input from {user}: empty or too long")
        say("Sorry, your message was empty or too long (max 2000 characters).")
        return

    logger.info(f"Received message from {user}: {text}")

    # Invoke Claude Code CLI
    try:
        result = subprocess.run(
            ["claude", "-p", "/winebuddy Format output for Slack mrkdwn, not markdown."],
            input=text,
            capture_output=True,
            text=True,
            timeout=300,
        )
        response = result.stdout or result.stderr or "No response from Claude"
    except subprocess.TimeoutExpired:
        response = "Request timed out"
    except Exception as e:
        logger.error(f"Error invoking Claude: {e}")
        response = f"Error: {e}"

    say(response)


# Event handler for app mentions (@YourApp)
@app.event("app_mention")
def handle_mention(event, say, logger):
    """Respond when the app is mentioned"""

    text = event.get("text", "")
    user = event.get("user")

    logger.info(f"Mentioned by {user}: {text}")

    # Echo back with a friendly message
    response = f"<@{user}> You said: {text}"
    say(response)


# Start the app with Socket Mode
if __name__ == "__main__":
    # App-level token (xapp-...)
    app_token = os.environ.get("SLACK_APP_TOKEN")

    # Start Socket Mode handler
    handler = SocketModeHandler(app, app_token)

    print("⚡️ Chat app is running with Socket Mode!")
    handler.start()
