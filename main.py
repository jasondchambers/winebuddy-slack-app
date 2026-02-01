import os
import subprocess
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Initialize the app with your tokens
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))


# Event handler for messages
@app.event("message")
def handle_message(event, say, logger):
    """Invoke Claude Code with the message and return the response"""

    # Ignore bot messages to prevent infinite loops
    if event.get("bot_id"):
        return

    # Get the message text
    text = event.get("text", "")
    user = event.get("user")

    logger.info(f"Received message from {user}: {text}")

    # Invoke Claude Code CLI
    try:
        result = subprocess.run(
            ["claude", "-p", text],
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
