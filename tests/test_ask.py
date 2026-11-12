"""Steps for answering.feature and winebuddy_cli.feature (ask.py), with Claude and the winebuddy CLI faked."""

import copy
import json
import shlex
import subprocess
from datetime import date
from types import SimpleNamespace

import pytest
from conftest import table_rows, unescape
from pytest_bdd import given, parsers, scenarios, then, when

import ask

scenarios("features/answering.feature", "features/winebuddy_cli.feature")


# --- Fakes -----------------------------------------------------------------------------------------------------------


class FakeStream:
    """What client.beta.messages.stream() returns: streams a turn's text, then gives the whole message."""

    def __init__(self, turn: dict, number: int):
        self.turn, self.number = turn, number

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        yield from self.turn["chunks"]

    def get_final_message(self):
        text = "".join(self.turn["chunks"])
        content = [SimpleNamespace(type="text", text=text)] if text else []
        content += [
            SimpleNamespace(type="tool_use", id=f"toolu_{self.number}_{i}", name=name, input=params)
            for i, (name, params) in enumerate(self.turn["tool_calls"])
        ]
        stop_reason = self.turn["stop_reason"] or ("tool_use" if self.turn["tool_calls"] else "end_turn")
        usage = SimpleNamespace(input_tokens=100, cache_read_input_tokens=0, output_tokens=10)
        return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage)


class FakeClaude:
    """Stands in for ask.client: plays the scripted turns in order and records each request."""

    def __init__(self):
        self.turns: list[dict] = []
        self.repeat_last = False
        self.requests: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def add_turn(self, chunks=(), tool_calls=(), stop_reason=None):
        self.turns.append({"chunks": list(chunks), "tool_calls": list(tool_calls), "stop_reason": stop_reason})

    def stream(self, **request):
        self.requests.append(copy.deepcopy(request))  # ask() keeps appending to the same messages list
        n = len(self.requests) - 1
        assert n < len(self.turns) or self.repeat_last, "Claude was called more times than scripted"
        return FakeStream(self.turns[min(n, len(self.turns) - 1)], n)


class FakeWinebuddy:
    """Stands in for ask.winebuddy(): returns the output set up for each command line and records the calls."""

    def __init__(self):
        self.results: dict[tuple, subprocess.CompletedProcess | Exception] = {}
        self.calls: list[tuple] = []

    def set(self, args: str, returncode=0, stdout="", stderr=""):
        argv = tuple(shlex.split(args))
        self.results[argv] = subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    def __call__(self, *args):
        self.calls.append(args)
        result = self.results.get(args, subprocess.CompletedProcess(args, 0, "[]", ""))
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def claude(monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(ask, "claude", lambda: fake)
    return fake


@pytest.fixture
def cli(monkeypatch):
    fake = FakeWinebuddy()
    monkeypatch.setattr(ask, "winebuddy", fake)
    return fake


@pytest.fixture
def ctx():
    return {"answer": None, "error": None, "streamed": [], "args": None, "run": None}


def tool_results(claude) -> list[dict]:
    """Return the tool results sent back to Claude after its first turn."""
    assert len(claude.requests) > 1, "no tool results were sent back to Claude"
    return claude.requests[1]["messages"][-1]["content"]


def system_text(claude) -> str:
    return "\n".join(block["text"] for block in claude.requests[0]["system"])


# --- Given -----------------------------------------------------------------------------------------------------------


@given(parsers.parse('the skill file says "{text}"'))
def skill_file(tmp_path, monkeypatch, text):
    (tmp_path / "SKILL.md").write_text(f"---\nname: winebuddy\ndescription: The wine skill\n---\n\n{text}\n")
    monkeypatch.setattr(ask, "WINEBUDDY_DIR", tmp_path)


@given(parsers.parse('the cellar refresh reports "{report}"'))
def refresh_reports(cli, report):
    cli.set("--refresh", 0, report)


@given(parsers.re(r'the cellar refresh exits with (?P<code>\d+) reporting "(?P<report>.*)"'))
def refresh_exits(cli, code, report):
    cli.set("--refresh", int(code), report)


@given(parsers.parse('the cellar refresh fails with exit {code:d} and "{error}"'))
def refresh_fails(cli, code, error):
    cli.set("--refresh", code, "", error)


@given(parsers.re(r'Claude replies "(?P<text>.*)"'))
def claude_replies(claude, text):
    claude.add_turn([text] if text else [])


@given(parsers.parse("Claude replies in pieces {pieces}"))
def claude_replies_in_pieces(claude, pieces):
    claude.add_turn(json.loads(f"[{pieces}]"))


@given(parsers.parse("Claude calls query_wines with {params}"))
def claude_queries(claude, params):
    claude.add_turn(tool_calls=[("query_wines", json.loads(params))])


@given(parsers.parse('Claude calls discover for "{field}"'))
def claude_discovers(claude, field):
    claude.add_turn(tool_calls=[("discover", {"field": field})])


@given(parsers.parse('Claude calls discover for "{field}" and query_wines with {params}'))
def claude_discovers_and_queries(claude, field, params):
    claude.add_turn(tool_calls=[("discover", {"field": field}), ("query_wines", json.loads(params))])


@given(parsers.parse('Claude keeps calling discover for "{field}"'))
def claude_keeps_discovering(claude, field):
    claude.add_turn(tool_calls=[("discover", {"field": field})])
    claude.repeat_last = True


@given("Claude refuses")
def claude_refuses(claude):
    claude.add_turn(stop_reason="refusal")


@given(parsers.parse('Claude writes "{text}" and calls discover for "{field}"'))
def claude_writes_and_discovers(claude, text, field):
    claude.add_turn([text], [("discover", {"field": field})])


@given(parsers.parse('Claude writes "{text}" and calls discover for "{field}" but hits the token limit'))
def claude_hits_limit(claude, text, field):
    claude.add_turn([text], [("discover", {"field": field})], stop_reason="max_tokens")


@given(parsers.re(r"winebuddy outputs '(?P<output>.*)' for \"(?P<args>.+)\""))
def winebuddy_outputs(cli, output, args):
    cli.set(args, 0, output)


@given(parsers.parse('winebuddy fails with "{error}" for "{args}"'))
def winebuddy_fails(cli, error, args):
    cli.set(args, 1, "", error)


@given(parsers.parse('winebuddy times out for "{args}"'))
def winebuddy_times_out(cli, args):
    cli.results[tuple(shlex.split(args))] = subprocess.TimeoutExpired(["winebuddy.py"], ask.COMMAND_TIMEOUT_SECONDS)


@given("the bot is running in a virtual environment")
def bot_in_venv(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/opt/winebuddy-slack-app/.venv")


# --- When ------------------------------------------------------------------------------------------------------------


def ask_question(ctx, question, history=()):
    try:
        ctx["answer"] = ask.ask(question, ctx["streamed"].append, history)
    except ask.CellarUnavailable as e:
        ctx["error"] = e


@when(parsers.parse('I ask "{question}"'))
def i_ask(ctx, question):
    ask_question(ctx, question)


@when(parsers.parse('I ask "{question}" after this conversation:'))
def i_ask_in_conversation(ctx, question, datatable):
    ask_question(ctx, question, table_rows(datatable))


@when(parsers.parse("query_wines is called with {params}"))
def query_called(ctx, params):
    ctx["args"] = ask.query_args(json.loads(params))


@when(parsers.parse("winebuddy is run for {tool} with {params}"))
def winebuddy_run(ctx, monkeypatch, tool, params):
    def fake_run(argv, **kwargs):
        ctx["run"] = {"argv": argv, **kwargs}
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    monkeypatch.setattr(ask.subprocess, "run", fake_run)
    ask.run_tool(SimpleNamespace(id="toolu_1", name=tool, input=json.loads(params)))


# --- Then ------------------------------------------------------------------------------------------------------------


@then(parsers.parse('the answer is "{answer}"'))
def answer_is(ctx, answer):
    assert ctx["error"] is None, ctx["error"]
    assert ctx["answer"] == unescape(answer)


@then(parsers.parse('Claude was sent "{question}" after the refresh output "{report}"'))
def sent_question(claude, question, report):
    assert claude.requests[0]["messages"][-1] == {
        "role": "user",
        "content": f"<refresh_output>\n{report}\n</refresh_output>\n\n{question}",
    }


@then(parsers.parse("Claude was sent these messages before the question:"))
def sent_history(claude, datatable):
    assert claude.requests[0]["messages"][:-1] == table_rows(datatable)


@then(parsers.parse('the system prompt starts with "{text}"'))
def system_starts(claude, text):
    assert system_text(claude).startswith(text)


@then(parsers.parse('the system prompt includes "{text}"'))
def system_includes(claude, text):
    assert text in system_text(claude)


@then("the system prompt ends with today's date")
def system_ends_with_date(claude):
    today = date.today()
    assert system_text(claude).endswith(f"{today:%B} {today.day}, {today.year}.")


@then(parsers.parse('winebuddy was run with "{args}"'))
def winebuddy_was_run(cli, args):
    assert tuple(shlex.split(args)) in cli.calls, cli.calls


@then("winebuddy was only run to refresh the cellar")
def only_refreshed(cli):
    assert cli.calls == [("--refresh",)]


@then(parsers.re(r"Claude was sent the tool result '(?P<content>.*)'"))
def sent_tool_result(claude, content):
    assert [(r["content"], r["is_error"]) for r in tool_results(claude)] == [(content, False)]


@then(parsers.parse('Claude was sent the error "{content}"'))
def sent_error(claude, content):
    assert [(r["content"], r["is_error"]) for r in tool_results(claude)] == [(content, True)]


@then(parsers.parse("Claude was sent {count:d} tool results"))
def sent_tool_results(claude, count):
    results = tool_results(claude)
    tool_ids = [b.id for b in claude.requests[1]["messages"][-2]["content"] if b.type == "tool_use"]
    assert len(results) == count and [r["tool_use_id"] for r in results] == tool_ids


@then("the answer so far was passed on as:")
def streamed_as(ctx, datatable):
    assert ctx["streamed"] == [r["text"] for r in table_rows(datatable)]


@then(parsers.parse("Claude was called {count:d} times"))
def claude_called(claude, count):
    assert len(claude.requests) == count


@then(parsers.parse('asking fails with "{message}"'))
def asking_fails(ctx, message):
    assert str(ctx["error"]) == message


@then(parsers.parse('the winebuddy arguments are "{arguments}"'))
def arguments_are(ctx, arguments):
    assert ctx["args"] == shlex.split(arguments)


@then(parsers.parse('the command run is "{command}"'))
def command_run(ctx, command):
    assert ctx["run"]["argv"] == shlex.split(command)


@then("it was run without a shell, in the winebuddy directory, with a 30 second timeout")
def run_safely(ctx):
    run = ctx["run"]
    assert isinstance(run["argv"], list) and not run.get("shell", False)
    assert (run["cwd"], run["timeout"]) == (ask.WINEBUDDY_DIR, 30)


@then("VIRTUAL_ENV isn't passed on to winebuddy")
def no_virtual_env(ctx):
    env = ctx["run"]["env"]
    assert "VIRTUAL_ENV" not in env and "PATH" in env
