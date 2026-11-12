"""Answer a wine cellar question with Claude, which looks up the cellar through the winebuddy CLI.

Usage: python ask.py "<question>"
"""

import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

import anthropic
from anthropic.types.beta import (
    BetaMessage,
    BetaMessageParam,
    BetaTextBlockParam,
    BetaToolParam,
    BetaToolResultBlockParam,
)

MODEL = "claude-sonnet-5-5"
MAX_TOOL_ROUNDS = 10  # caps the lookups (and cost) one question can run up
COMMAND_TIMEOUT_SECONDS = 30

# The winebuddy repo: its CLI (winebuddy.py), the cellar (cellar.csv/cellar.db) and the skill (SKILL.md)
WINEBUDDY_DIR = Path(os.environ.get("WINEBUDDY_DIR", "~/.winebuddy")).expanduser()

# How the bot differs from running the skill in Claude Code
BOT_INSTRUCTIONS = """
## Running as the Slack bot

You are answering in Slack. Ignore the instructions above about installing winebuddy and running shell
commands: winebuddy is already installed, and the cellar has already been refreshed for this question. Look
the cellar up with the query_wines and discover tools instead; query_wines always returns JSON.

The refresh output is given with each question. If it reports activity (new wines, removed wines, quantity
changes), include it in your answer; if it only says the database is up to date, don't mention it.

Format output for Slack mrkdwn. Never use markdown tables (no pipe/| syntax) or # headings; use bullet lists
and *bold* lines instead. Start each bullet with "• " (Slack shows a leading "-" as a literal dash).
Bold is *single asterisks*, never **double**; italics are _underscores_.
"""

QUERY_TOOL: BetaToolParam = {
    "name": "query_wines",
    "description": "Search the wine cellar (winebuddy.py query). All filters are optional (null to skip); "
    "text filters other than color and country are partial matches. Returns the matching "
    "wines as a JSON array.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "color": {"type": ["string", "null"], "description": "e.g. Red, White, Rosé"},
            "varietal": {"type": ["string", "null"], "description": "e.g. Pinot Noir"},
            "producer": {"type": ["string", "null"]},
            "country": {"type": ["string", "null"], "description": "e.g. Italy"},
            "region": {"type": ["string", "null"], "description": "e.g. Willamette"},
            "vintage": {"type": ["integer", "null"], "description": "Exact vintage year"},
            "vintage_min": {"type": ["integer", "null"]},
            "vintage_max": {"type": ["integer", "null"]},
            "score_min": {"type": ["number", "null"], "description": "Minimum professional or community score"},
            "in_stock": {"type": "boolean", "description": "Only wines with quantity > 0"},
            "ready": {"type": "boolean", "description": "Only wines within their drinking window"},
            "sort": {
                "type": "string",
                "enum": ["vintage", "producer", "score", "price", "wine_name"],
                "description": "Sort field; vintage is the usual order",
            },
            "desc": {"type": "boolean", "description": "Sort descending"},
            "limit": {"type": ["integer", "null"]},
        },
        "required": [
            "color",
            "varietal",
            "producer",
            "country",
            "region",
            "vintage",
            "vintage_min",
            "vintage_max",
            "score_min",
            "in_stock",
            "ready",
            "sort",
            "desc",
            "limit",
        ],
        "additionalProperties": False,
    },
}

DISCOVER_TOOL: BetaToolParam = {
    "name": "discover",
    "description": "List the distinct values of a field in the cellar (winebuddy.py discover), "
    "e.g. to find the exact spelling of a region before filtering on it.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "field": {
                "type": "string",
                "enum": ["colors", "varietals", "producers", "countries", "regions", "vintages"],
            },
        },
        "required": ["field"],
        "additionalProperties": False,
    },
}

# query_wines input -> winebuddy.py option, for the options that take a value
VALUE_OPTIONS = {
    "color": "--color",
    "varietal": "--varietal",
    "producer": "--producer",
    "country": "--country",
    "region": "--region",
    "vintage": "--vintage",
    "vintage_min": "--vintage-min",
    "vintage_max": "--vintage-max",
    "score_min": "--score-min",
    "sort": "--sort",
    "limit": "--limit",
}
FLAG_OPTIONS = {"in_stock": "--in-stock", "ready": "--ready", "desc": "--desc"}

REFRESH_OK = (0, 1, 2)  # winebuddy.py --refresh exit codes: up to date, created, rebuilt
REFRESH_CSV_MISSING = 255  # winebuddy.py --refresh exit code when cellar.csv is missing

REFUSAL_TEXT = "Sorry, I can't help with that one."
NO_RESPONSE_TEXT = "No response from Claude"
TOO_MANY_LOOKUPS_TEXT = "_Stopped: that question needed too many lookups._"

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(timeout=120.0)


class CellarUnavailable(Exception):
    """The cellar can't be refreshed, so questions can't be answered."""


def winebuddy(*args: str) -> subprocess.CompletedProcess:
    """Run winebuddy.py with args (no shell) in its own repo and environment."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}  # let uv use winebuddy's own venv
    return subprocess.run(
        ["uv", "run", "--quiet", "python", "winebuddy.py", *args],
        cwd=WINEBUDDY_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
    )  # the exit code is checked by the caller


def refresh() -> str:
    """Rebuild the cellar database if cellar.csv changed and return what the refresh reported.

    Raises CellarUnavailable if cellar.csv is missing or the refresh fails.
    """
    result = winebuddy("--refresh")
    output = result.stdout.strip()
    logger.info(f"refresh (exit {result.returncode}): {output[:200]}")
    if result.returncode not in REFRESH_OK:
        detail = "cellar.csv is missing" if result.returncode == REFRESH_CSV_MISSING else result.stderr.strip()
        raise CellarUnavailable(f"the cellar couldn't be refreshed ({detail})")
    return output


def system_prompt() -> list[BetaTextBlockParam]:
    """Return the skill (without its front matter) plus the bot instructions, then today's date."""
    skill = (WINEBUDDY_DIR / "SKILL.md").read_text().split("---", 2)[2].strip()
    return [
        {"type": "text", "text": skill + "\n" + BOT_INSTRUCTIONS},
        {"type": "text", "text": f"Today's date is {date.today():%A, %B %-d, %Y}."},
    ]


def query_args(params: dict) -> list[str]:
    """Return the winebuddy.py arguments for a query_wines tool call."""
    args = ["query", "--format", "json"]
    for name, option in VALUE_OPTIONS.items():
        if params.get(name) is not None:
            args += [option, str(params[name])]
    args += [option for name, option in FLAG_OPTIONS.items() if params.get(name)]
    return args


def run_tool(block) -> BetaToolResultBlockParam:
    """Run a query_wines or discover tool call and return its tool_result block."""
    args = query_args(block.input) if block.name == "query_wines" else ["discover", block.input["field"]]
    logger.info(f"{block.name}: {' '.join(args)}")
    try:
        result = winebuddy(*args)
        if result.returncode == 0:
            content, is_error = result.stdout.strip() or "(no output)", False
        else:
            content, is_error = f"error: {result.stderr.strip() or result.stdout.strip()}", True
    except subprocess.TimeoutExpired:
        content, is_error = "error: the lookup timed out", True
    return {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}


def stream_turn(
    system: list[BetaTextBlockParam], messages: list[BetaMessageParam], on_text: Callable[[str], None]
) -> tuple[BetaMessage, str]:
    """Ask Claude for its next turn, passing the turn's text to on_text as it streams in.

    Returns Claude's message and its text.
    """
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # if Sonnet declines, the API retries on a fallback model
        output_config={"effort": "medium"},
        cache_control={"type": "ephemeral"},
        system=system,
        tools=[QUERY_TOOL, DISCOVER_TOOL],
        messages=messages,
    ) as stream:
        text = ""
        for chunk in stream.text_stream:
            text += chunk
            on_text(text)
        response = stream.get_final_message()

    usage = response.usage
    logger.info(
        f"{response.stop_reason}: {usage.input_tokens} in ({usage.cache_read_input_tokens} cached), "
        f"{usage.output_tokens} out"
    )
    return response, text


def ask(
    question: str, on_text: Callable[[str], None] = lambda _: None, history: Sequence[BetaMessageParam] = ()
) -> str:
    """Answer question from the cellar and return the answer.

    on_text is called with the answer so far as it streams in, for showing progress.
    history is the conversation so far, as alternating user/assistant messages starting with a user one.
    Raises CellarUnavailable if the cellar can't be refreshed, anthropic.APIError if the API call fails.
    """
    refresh_output = refresh()
    system = system_prompt()
    messages: list[BetaMessageParam] = [
        *history,
        {"role": "user", "content": f"<refresh_output>\n{refresh_output}\n</refresh_output>\n\n{question}"},
    ]
    text = ""  # the latest text Claude wrote, kept if a later turn only looks things up

    for _ in range(MAX_TOOL_ROUNDS):
        response, turn_text = stream_turn(system, messages, on_text)
        text = turn_text or text
        if response.stop_reason == "refusal":
            return REFUSAL_TEXT
        if response.stop_reason != "tool_use":  # answered, or cut off (then its lookups aren't run)
            return text or NO_RESPONSE_TEXT

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": [run_tool(b) for b in response.content if b.type == "tool_use"]})

    return (text + "\n\n" if text else "") + TOO_MANY_LOOKUPS_TEXT


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 1:
        sys.exit(__doc__)
    logging.basicConfig(level=logging.INFO)
    print(ask(args[0]))
