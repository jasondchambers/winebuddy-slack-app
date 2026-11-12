"""WineBuddy Slack bot: answers wine cellar questions in Slack threads, over Socket Mode."""

import logging
import os
import re
from collections import defaultdict
from collections.abc import Callable
from itertools import groupby
from operator import itemgetter
from time import monotonic, time

import anthropic
from anthropic.types.beta import BetaMessageParam
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from ask import CellarUnavailable, ask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 2000
RATE_LIMIT_SECONDS = 5
MAX_HISTORY_MESSAGES = 20  # earlier thread messages sent with a question, to bound its context
STREAM_UPDATE_INTERVAL = 2.0  # seconds between Slack message updates while an answer streams in

PENDING_TEXT = "WineBuddy is working on it..."
RATE_LIMITED_TEXT = f"Please wait {RATE_LIMIT_SECONDS} seconds between requests."
INVALID_INPUT_TEXT = f"Sorry, your message was empty or too long (max {MAX_MESSAGE_LENGTH} characters)."
BOT_STARTED_THREAD_TEXT = "(WineBuddy posted this to the channel.)"

# Track last request time per user
user_last_request: dict[str, float] = defaultdict(float)


def sanitize_input(text: str) -> str | None:
    """Sanitize and validate user input.

    Returns None if input is invalid, otherwise returns cleaned text.
    """
    if not text or len(text) > MAX_MESSAGE_LENGTH:
        return None

    # Strip control characters (except newlines and tabs)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

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


def is_earlier_turn(message: dict, before_ts: str) -> bool:
    """Tell whether a thread message is part of the conversation before before_ts.

    Messages without text and the bot's "working on it" placeholder aren't.
    """
    if float(message["ts"]) >= float(before_ts) or not message.get("text"):
        return False
    return not (message.get("bot_id") and message["text"] == PENDING_TEXT)


def join_consecutive(turns: list[tuple[str, str]]) -> list[BetaMessageParam]:
    """Make Claude messages from (role, text) turns, joining consecutive turns from one side.

    Claude needs the roles to alternate.
    """
    return [
        {"role": role, "content": "\n\n".join(text for _, text in group)}
        for role, group in groupby(turns, key=itemgetter(0))
    ]


def thread_history(client, channel: str, thread_ts: str, before_ts: str) -> list[BetaMessageParam]:
    """Return the thread's messages before before_ts, as Claude messages for ask().

    The bot's messages are the assistant's and everyone else's the user's, and only the last
    MAX_HISTORY_MESSAGES are kept. The history must start with a user message, so one that starts with
    the bot's is introduced with a placeholder rather than losing what the bot said.
    """
    replies = client.conversations_replies(channel=channel, ts=thread_ts)["messages"]
    turns = [("assistant" if m.get("bot_id") else "user", m["text"]) for m in replies if is_earlier_turn(m, before_ts)]
    history = join_consecutive(turns)[-MAX_HISTORY_MESSAGES:]
    if history and history[0]["role"] == "assistant":
        history.insert(0, {"role": "user", "content": BOT_STARTED_THREAD_TEXT})
    return history


def progress_updater(client, channel: str, ts: str) -> Callable[[str], None]:
    """Return an on_text callback that shows the answer so far, at most every STREAM_UPDATE_INTERVAL."""
    last_update = monotonic()

    def show_progress(answer: str) -> None:
        nonlocal last_update
        if monotonic() - last_update >= STREAM_UPDATE_INTERVAL:
            client.chat_update(channel=channel, ts=ts, text=slack_bold(answer))
            last_update = monotonic()

    return show_progress


def answer_question(client, event: dict, question: str, on_text: Callable[[str], None]) -> str:
    """Ask Claude the question, with the thread so far if it's a reply, and return the reply to post.

    Errors become a reply too: their details are logged, not posted.
    """
    user = event.get("user")
    started = time()
    try:
        thread_ts = event.get("thread_ts")
        history = thread_history(client, event["channel"], thread_ts, event["ts"]) if thread_ts else []
        logger.info(f"Asking with {len(history)} earlier messages from the thread")
        answer = ask(question, on_text, history)
    except CellarUnavailable as e:
        logger.exception(f"Cellar unavailable for user {user}")
        answer = f"Sorry, {e}."
    except anthropic.APIError:
        logger.exception(f"Claude API error for user {user}")
        answer = "Sorry, I couldn't reach Claude. Please try again in a minute."
    except Exception:
        # Log the details, but don't post them: they can include paths and commands from the server
        logger.exception(f"Unexpected error answering user {user}")
        answer = "Sorry, something went wrong. Please try again."
    logger.info(f"Claude took {time() - started:.2f}s for user {user}")
    return answer


app = App(token=os.environ.get("SLACK_BOT_TOKEN"))


@app.event("message")
def handle_message(event, say, client):
    """Ask Claude the message and reply with its answer in the message's thread.

    Each thread is a conversation: a reply in one is asked along with the thread so far.
    """
    if event.get("bot_id"):  # ignore bot messages, including our own, to prevent loops
        return

    user = event.get("user")
    thread_ts = event.get("thread_ts") or event["ts"]
    if is_rate_limited(user):
        logger.warning(f"Rate limited user {user}")
        say(RATE_LIMITED_TEXT, thread_ts=thread_ts)
        return

    question = sanitize_input(event.get("text", ""))
    if question is None:
        logger.warning(f"Invalid input from {user}: empty or too long")
        say(INVALID_INPUT_TEXT, thread_ts=thread_ts)
        return

    logger.info(f"Received message from {user}: {question}")
    channel = event.get("channel")
    ts = say(PENDING_TEXT, thread_ts=thread_ts)["ts"]
    answer = answer_question(client, event, question, progress_updater(client, channel, ts))
    client.chat_update(channel=channel, ts=ts, text=slack_bold(answer))


@app.event("app_mention")
def handle_mention(event, say):
    """Respond when the app is mentioned."""
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
