import logging
import os
import re
from collections import defaultdict
from time import time, monotonic
import anthropic
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from ask import ask, CellarUnavailable

logging.basicConfig(level=logging.INFO)

MAX_MESSAGE_LENGTH = 2000
RATE_LIMIT_SECONDS = 5
MAX_HISTORY_MESSAGES = 20  # earlier thread messages sent with a question, to bound its context

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


def slack_bold(text: str) -> str:
    """Turn any markdown **bold** Claude writes into Slack's *bold*."""
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)


PENDING_TEXT = "WineBuddy is working on it..."


def thread_history(client, channel: str, thread_ts: str, before_ts: str) -> list[dict]:
    """The thread's messages before before_ts, as Claude messages for ask().

    The bot's messages are the assistant's and everyone else's the user's. Consecutive messages from one
    side are joined, since the roles must alternate, and only the last MAX_HISTORY_MESSAGES are kept.
    The bot's "working on it" placeholder is skipped, and the history must start with a user message, so
    one that starts with the bot's is introduced with a placeholder rather than losing what the bot said.
    """
    replies = client.conversations_replies(channel=channel, ts=thread_ts)["messages"]
    history = []
    for m in replies:
        if float(m["ts"]) >= float(before_ts) or not m.get("text"):
            continue
        role = "assistant" if m.get("bot_id") else "user"
        if role == "assistant" and m["text"] == PENDING_TEXT:
            continue
        if history and history[-1]["role"] == role:
            history[-1]["content"] += "\n\n" + m["text"]
        else:
            history.append({"role": role, "content": m["text"]})

    history = history[-MAX_HISTORY_MESSAGES:]
    if history and history[0]["role"] == "assistant":
        history.insert(0, {"role": "user", "content": "(WineBuddy posted this to the channel.)"})
    return history


# Initialize the app with your tokens
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))


# Event handler for messages
@app.event("message")
def handle_message(event, say, client, logger):
    """Ask Claude the message and reply with its answer in the message's thread.

    Each thread is a conversation: a reply in one is asked along with the thread so far.
    """

    # Ignore bot messages to prevent infinite loops
    if event.get("bot_id"):
        return

    user = event.get("user")
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event["ts"]

    # Check rate limit
    if is_rate_limited(user):
        logger.warning(f"Rate limited user {user}")
        say(f"Please wait {RATE_LIMIT_SECONDS} seconds between requests.", thread_ts=thread_ts)
        return

    # Get and sanitize the message text
    raw_text = event.get("text", "")
    text = sanitize_input(raw_text)

    if text is None:
        logger.warning(f"Invalid input from {user}: empty or too long")
        say("Sorry, your message was empty or too long (max 2000 characters).", thread_ts=thread_ts)
        return

    logger.info(f"Received message from {user}: {text}")

    # Send immediate feedback
    pending_message = say(PENDING_TEXT, thread_ts=thread_ts)
    ts = pending_message["ts"]

    # Ask Claude, updating the Slack message as the answer streams in
    STREAM_UPDATE_INTERVAL = 2.0  # seconds between Slack message updates
    t_start = time()
    last_update = monotonic()

    def show_progress(answer: str):
        nonlocal last_update
        if monotonic() - last_update >= STREAM_UPDATE_INTERVAL:
            client.chat_update(channel=channel, ts=ts, text=slack_bold(answer))
            last_update = monotonic()

    try:
        history = thread_history(client, channel, thread_ts, event["ts"]) if event.get("thread_ts") else []
        logger.info(f"Asking with {len(history)} earlier messages from the thread")
        response = ask(text, show_progress, history)
    except CellarUnavailable as e:
        logger.error(f"Cellar unavailable for user {user}: {e}")
        response = f"Sorry, {e}."
    except anthropic.APIError as e:
        logger.error(f"Claude API error for user {user}: {e}")
        response = "Sorry, I couldn't reach Claude. Please try again in a minute."
    except Exception as e:
        logger.error(f"Error invoking Claude: {e}")
        response = f"Error: {e}"

    logger.info(f"Claude took {time() - t_start:.2f}s for user {user}")

    # Final update with complete response
    client.chat_update(channel=channel, ts=ts, text=slack_bold(response))


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
