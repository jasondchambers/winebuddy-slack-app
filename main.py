import json
import logging
import os
import re
import subprocess
from collections import defaultdict
from time import time, monotonic
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

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


def thread_history(client, channel: str, thread_ts: str, before_ts: str) -> list[dict]:
    """The thread's messages before before_ts, as {"role", "content"} turns.

    The bot's messages are the assistant's and everyone else's the user's. Consecutive messages from one
    side are joined, and only the last MAX_HISTORY_MESSAGES are kept. The bot's "working on it"
    placeholder is skipped, since it is not part of the conversation.
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
    return history[-MAX_HISTORY_MESSAGES:]


def build_prompt(text: str, history: list[dict]) -> str:
    """The question for Claude, preceded by the thread so far when it is a follow-up.

    Each Claude invocation is a fresh session, so the earlier conversation is sent as a transcript.
    """
    if not history:
        return text
    names = {"user": "User", "assistant": "WineBuddy"}
    transcript = "\n\n".join(f"{names[m['role']]}: {m['content']}" for m in history)
    return (
        "This is a follow-up in an ongoing Slack conversation. The conversation so far:\n\n"
        f"<conversation>\n{transcript}\n</conversation>\n\n"
        f"Answer the user's new message, using the conversation for context:\n\n{text}"
    )


PENDING_TEXT = "WineBuddy is working on it..."

# Initialize the app with your tokens
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))


# Event handler for messages
@app.event("message")
def handle_message(event, say, client, logger):
    """Invoke Claude Code with the message and reply with its answer in the message's thread.

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

    # Invoke Claude Code CLI with streaming JSON output
    STREAM_UPDATE_INTERVAL = 2.0  # seconds between Slack message updates
    t_start = time()
    response = ""

    proc = None
    try:
        history = thread_history(client, channel, thread_ts, event["ts"]) if event.get("thread_ts") else []
        logger.info(f"Asking with {len(history)} earlier messages from the thread")
        prompt = build_prompt(text, history)

        proc = subprocess.Popen(
            [
                "claude",
                "--model", "sonnet",
                "--allowedTools", "Bash(*)",
                "--output-format", "stream-json",
                "--verbose",
                "-p", "/winebuddy Format output for Slack mrkdwn, not markdown.",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Send input and close stdin
        proc.stdin.write(prompt)
        proc.stdin.close()

        # Parse streaming JSON events and update Slack with assistant text
        current_text = ""
        last_update = monotonic()
        proc_start = monotonic()

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            elapsed = monotonic() - proc_start
            event_type = event.get("type", "unknown")
            event_subtype = event.get("subtype", "")
            label = f"{event_type}/{event_subtype}" if event_subtype else event_type

            # Extract text from assistant messages as they arrive
            if event_type == "assistant":
                msg = event.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        current_text = block["text"]
                logger.info(f"[{elapsed:.1f}s] {label}: {current_text[:120]}")
            elif event_type == "result":
                current_text = event.get("result", current_text)
                logger.info(f"[{elapsed:.1f}s] {label}: {current_text[:120]}")
            else:
                logger.info(f"[{elapsed:.1f}s] {label}")

            # Periodically update Slack with progress
            now = monotonic()
            if current_text and now - last_update >= STREAM_UPDATE_INTERVAL:
                client.chat_update(channel=channel, ts=ts, text=current_text)
                last_update = now

        proc.wait(timeout=300)
        response = current_text or "No response from Claude"

        stderr_out = proc.stderr.read()
        if stderr_out:
            logger.warning(f"Claude stderr: {stderr_out}")

    except subprocess.TimeoutExpired:
        logger.error(f"Claude timed out for user {user}")
        if proc:
            proc.kill()
        response = "Request timed out"
    except Exception as e:
        logger.error(f"Error invoking Claude: {e}")
        response = f"Error: {e}"

    t_claude = time() - t_start
    logger.info(f"Claude subprocess took {t_claude:.2f}s for user {user}")

    # Final update with complete response
    client.chat_update(channel=channel, ts=ts, text=response)


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
