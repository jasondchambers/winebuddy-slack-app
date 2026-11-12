"""Answer a wine cellar question with Claude, which looks up the cellar through the winebuddy CLI.

Usage: python ask.py "<question>"
"""

from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
import logging
import os
import subprocess
import sys

import anthropic

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

QUERY_TOOL = {
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
            "sort": {"type": "string", "enum": ["vintage", "producer", "score", "price", "wine_name"],
                     "description": "Sort field; vintage is the usual order"},
            "desc": {"type": "boolean", "description": "Sort descending"},
            "limit": {"type": ["integer", "null"]},
        },
        "required": ["color", "varietal", "producer", "country", "region", "vintage", "vintage_min",
                     "vintage_max", "score_min", "in_stock", "ready", "sort", "desc", "limit"],
        "additionalProperties": False,
    },
}

DISCOVER_TOOL = {
    "name": "discover",
    "description": "List the distinct values of a field in the cellar (winebuddy.py discover), "
                   "e.g. to find the exact spelling of a region before filtering on it.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "field": {"type": "string",
                      "enum": ["colors", "varietals", "producers", "countries", "regions", "vintages"]},
        },
        "required": ["field"],
        "additionalProperties": False,
    },
}

# query_wines input -> winebuddy.py option, for the options that take a value
VALUE_OPTIONS = {
    "color": "--color", "varietal": "--varietal", "producer": "--producer", "country": "--country",
    "region": "--region", "vintage": "--vintage", "vintage_min": "--vintage-min",
    "vintage_max": "--vintage-max", "score_min": "--score-min", "sort": "--sort", "limit": "--limit",
}
FLAG_OPTIONS = {"in_stock": "--in-stock", "ready": "--ready", "desc": "--desc"}

REFRESH_CSV_MISSING = 255  # winebuddy.py --refresh exit code when cellar.csv is missing

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(timeout=120.0)


class CellarUnavailable(Exception):
    """The cellar can't be refreshed, so questions can't be answered."""


def winebuddy(*args: str) -> subprocess.CompletedProcess:
    """Run winebuddy.py with args (no shell) in its own repo and environment."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}  # let uv use winebuddy's own venv
    return subprocess.run(["uv", "run", "--quiet", "python", "winebuddy.py", *args], cwd=WINEBUDDY_DIR,
                          env=env, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)


def refresh() -> str:
    """Rebuild the cellar database if cellar.csv changed and return what the refresh reported.

    Raises CellarUnavailable if cellar.csv is missing or the refresh fails.
    """
    result = winebuddy("--refresh")
    output = result.stdout.strip()
    logger.info(f"refresh (exit {result.returncode}): {output[:200]}")
    if result.returncode not in (0, 1, 2):  # up to date, created, rebuilt
        detail = "cellar.csv is missing" if result.returncode == REFRESH_CSV_MISSING else result.stderr.strip()
        raise CellarUnavailable(f"the cellar couldn't be refreshed ({detail})")
    return output


def system_prompt() -> list[dict]:
    """The skill (without its front matter) plus the bot instructions, then today's date."""
    skill = (WINEBUDDY_DIR / "SKILL.md").read_text().split("---", 2)[2].strip()
    return [
        {"type": "text", "text": skill + "\n" + BOT_INSTRUCTIONS},
        {"type": "text", "text": f"Today's date is {date.today():%A, %B %-d, %Y}."},
    ]


def query_args(params: dict) -> list[str]:
    """The winebuddy.py arguments for a query_wines tool call."""
    args = ["query", "--format", "json"]
    for name, option in VALUE_OPTIONS.items():
        if params.get(name) is not None:
            args += [option, str(params[name])]
    args += [option for name, option in FLAG_OPTIONS.items() if params.get(name)]
    return args


def run_tool(block) -> dict:
    """Run a query_wines or discover tool call and return its tool_result block."""
    if block.name == "query_wines":
        args = query_args(block.input)
    else:
        args = ["discover", block.input["field"]]
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


def ask(question: str, on_text: Callable[[str], None] = lambda text: None,
        history: Sequence[dict] = ()) -> str:
    """Answer question from the cellar and return the answer.

    on_text is called with the answer so far as it streams in, for showing progress.
    history is the conversation so far, as alternating user/assistant messages starting with a user one.
    Raises CellarUnavailable if the cellar can't be refreshed, anthropic.APIError if the API call fails.
    """
    refresh_output = refresh()
    system = system_prompt()
    tools = [QUERY_TOOL, DISCOVER_TOOL]
    messages = [*history, {"role": "user", "content": f"<refresh_output>\n{refresh_output}\n</refresh_output>\n\n"
                                                      f"{question}"}]
    text = ""

    for _ in range(MAX_TOOL_ROUNDS):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # if Sonnet declines, the API retries on a fallback model
            output_config={"effort": "medium"},
            cache_control={"type": "ephemeral"},
            system=system,
            tools=tools,
            messages=messages,
        ) as stream:
            turn_text = ""
            for chunk in stream.text_stream:
                turn_text += chunk
                text = turn_text
                on_text(text)
            response = stream.get_final_message()

        usage = response.usage
        logger.info(f"{response.stop_reason}: {usage.input_tokens} in ({usage.cache_read_input_tokens} cached), "
                    f"{usage.output_tokens} out")

        if response.stop_reason == "refusal":
            return "Sorry, I can't help with that one."
        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if not tool_calls or response.stop_reason == "max_tokens":
            return text or "No response from Claude"

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": [run_tool(b) for b in tool_calls]})

    return (text + "\n\n" if text else "") + "_Stopped: that question needed too many lookups._"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    logging.basicConfig(level=logging.INFO)
    print(ask(sys.argv[1]))
