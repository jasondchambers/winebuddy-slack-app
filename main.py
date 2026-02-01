import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Initialize the app with your tokens
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))


# Event handler for messages
@app.event("message")
def handle_message(event, say, logger):
    """Echo back the message content"""

    # Ignore bot messages to prevent infinite loops
    if event.get("bot_id"):
        return

    # Get the message text
    text = event.get("text", "")
    user = event.get("user")
    channel = event.get("channel")

    logger.info(f"Received message from {user}: {text}")

    # Echo back the message
    response = f"Echo: {text}"
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
