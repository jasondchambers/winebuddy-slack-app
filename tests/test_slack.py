"""Steps for slack_messages.feature and thread_history.feature (main.py), with Slack, Claude and the clock faked."""

from collections import defaultdict
import logging

import anthropic
import httpx2
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from conftest import unescape
import main
from ask import CellarUnavailable

scenarios("features/slack_messages.feature", "features/thread_history.feature")

CHANNEL = "C1"


# --- Fakes -----------------------------------------------------------------------------------------------------------

class FakeClock:
    """Stands in for time() and monotonic(); only moves when a step moves it."""

    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class FakeSlack:
    """The say() and client the handler is given, recording what the bot posts and updates."""

    def __init__(self):
        self.posts: list[dict] = []    # {"text", "thread_ts", "ts"}
        self.updates: list[dict] = []  # {"channel", "ts", "text"}
        self.thread: list[dict] = []   # what conversations.replies returns
        self._next_ts = 0

    def new_ts(self) -> str:
        self._next_ts += 1
        return f"{1_700_000_000 + self._next_ts}.000100"

    def say(self, text, thread_ts=None):
        ts = self.new_ts()
        self.posts.append({"text": text, "thread_ts": thread_ts, "ts": ts})
        return {"ts": ts}

    def chat_update(self, channel, ts, text):
        self.updates.append({"channel": channel, "ts": ts, "text": text})

    def conversations_replies(self, channel, ts):
        return {"messages": list(self.thread)}


class FakeAsk:
    """Stands in for ask.ask(): records each question and returns (or raises) what the scenario set up."""

    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.calls: list[tuple[str, list[dict]]] = []
        self.answer = "An answer."
        self.stream: list[tuple[float, str]] = []  # (seconds after asking, answer so far)
        self.error: Exception | None = None

    def __call__(self, question, on_text=lambda text: None, history=()):
        self.calls.append((question, list(history)))
        start = self.clock.now
        for seconds, text in self.stream:
            self.clock.now = start + seconds
            on_text(text)
        if self.error:
            raise self.error
        return self.answer


@pytest.fixture
def clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(main, "time", clock)
    monkeypatch.setattr(main, "monotonic", clock)
    monkeypatch.setattr(main, "user_last_request", defaultdict(float))
    return clock


@pytest.fixture
def slack():
    return FakeSlack()


@pytest.fixture
def fake_ask(monkeypatch, clock):
    fake = FakeAsk(clock)
    monkeypatch.setattr(main, "ask", fake)
    return fake


@pytest.fixture
def ctx():
    return {"thread_ts": None, "history": None}


def post(slack, user, text, thread_ts=None, bot=False) -> dict:
    """Deliver a message event to the handler, as Slack would."""
    event = {"channel": CHANNEL, "ts": slack.new_ts(), "text": text}
    event.update({"bot_id": "BOTHER"} if bot else {"user": user})
    if thread_ts:
        event["thread_ts"] = thread_ts
        slack.thread.append(event)  # conversations.replies includes the message being answered
    main.handle_message(event, slack.say, slack, logging.getLogger("test"))
    return event


def table_rows(datatable) -> list[dict]:
    header, *rows = datatable
    return [dict(zip(header, (unescape(c) for c in row))) for row in rows]


# --- Given -----------------------------------------------------------------------------------------------------------

@given(parsers.parse('Claude answers "{answer}"'))
def claude_answers(fake_ask, answer):
    fake_ask.answer = unescape(answer)


@given("Claude's answer streams in as:")
def answer_streams(fake_ask, datatable):
    fake_ask.stream = [(float(r["seconds"]), r["answer so far"]) for r in table_rows(datatable)]
    fake_ask.answer = fake_ask.stream[-1][1]


@given("the cellar can't be refreshed because cellar.csv is missing")
def cellar_missing(fake_ask):
    fake_ask.error = CellarUnavailable("the cellar couldn't be refreshed (cellar.csv is missing)")


@given("the Claude API can't be reached")
def api_down(fake_ask):
    fake_ask.error = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))


@given(parsers.parse('asking fails unexpectedly with "{error}"'))
def unexpected_error(fake_ask, error):
    fake_ask.error = OSError(error)


@given(parsers.parse('a thread where "{user}" asked "{question}" and the bot answered "{answer}"'))
def a_thread(slack, ctx, user, question, answer):
    root = {"channel": CHANNEL, "ts": slack.new_ts(), "user": user, "text": question}
    slack.thread += [root, {"channel": CHANNEL, "ts": slack.new_ts(), "bot_id": "BBOT", "text": answer,
                            "thread_ts": root["ts"]}]
    ctx["thread_ts"] = root["ts"]


@given("the thread has these messages:")
def thread_messages(slack, datatable):
    for n, row in enumerate(table_rows(datatable), start=1):
        sender = {"bot_id": "BBOT"} if row["from"] == "bot" else {"user": row["from"]}
        slack.thread.append({"ts": f"{n}.000000", "text": row["text"], **sender})


@given(parsers.parse('a thread of {count:d} messages taking turns between "{user}" and the bot'))
def long_thread(slack, count, user):
    for n in range(1, count + 1):
        sender = {"user": user} if n % 2 else {"bot_id": "BBOT"}
        slack.thread.append({"ts": f"{n}.000000", "text": f"message {n}", **sender})


# --- When ------------------------------------------------------------------------------------------------------------

@when(parsers.parse('"{user}" posts "{text}"'))
def user_posts(slack, ctx, fake_ask, user, text):
    ctx["thread_ts"] = post(slack, user, unescape(text))["ts"]


@when(parsers.parse('"{user}" posts "{text}" {seconds:g} seconds later'))
def user_posts_later(slack, ctx, fake_ask, clock, user, text, seconds):
    clock.now += seconds
    ctx["thread_ts"] = post(slack, user, unescape(text))["ts"]


@when(parsers.parse('"{user}" posts a message of {length:d} characters'))
def user_posts_long(slack, ctx, fake_ask, user, length):
    ctx["thread_ts"] = post(slack, user, "a" * length)["ts"]


@when(parsers.parse('"{user}" replies in the thread "{text}"'))
def user_replies(slack, ctx, fake_ask, user, text):
    post(slack, user, unescape(text), thread_ts=ctx["thread_ts"])


@when(parsers.parse('a bot posts "{text}"'))
def bot_posts(slack, fake_ask, text):
    post(slack, None, text, bot=True)


@when(parsers.parse("the history before message {n:d} is read"))
def history_before(slack, ctx, n):
    ctx["history"] = main.thread_history(slack, CHANNEL, "1.000000", f"{n}.000000")


@when("the history before a new message is read")
def history_before_new(slack, ctx):
    ctx["history"] = main.thread_history(slack, CHANNEL, "1.000000", f"{len(slack.thread) + 1}.000000")


# --- Then ------------------------------------------------------------------------------------------------------------

@then(parsers.parse('the bot posts "{text}" in the thread'))
def bot_posts_in_thread(slack, ctx, text):
    assert {"text": unescape(text), "thread_ts": ctx["thread_ts"]} in [
        {"text": p["text"], "thread_ts": p["thread_ts"]} for p in slack.posts], slack.posts


@then(parsers.parse('the last thing the bot posts is "{text}"'))
def last_post(slack, text):
    assert slack.posts[-1]["text"] == unescape(text)


@then("the bot posts nothing")
def posts_nothing(slack):
    assert slack.posts == [] and slack.updates == []


@then(parsers.parse('the error "{text}" is logged'))
def error_logged(caplog, text):
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(r.exc_info and text in str(r.exc_info[1]) for r in errors), errors


@then(parsers.parse('the reply is updated to "{text}"'))
def reply_updated(slack, text):
    pending = next(p for p in slack.posts if p["text"] == main.PENDING_TEXT)
    assert slack.updates[-1] == {"channel": CHANNEL, "ts": pending["ts"], "text": unescape(text)}


@then("the reply is updated in turn to:")
def reply_updated_in_turn(slack, datatable):
    assert [u["text"] for u in slack.updates] == [r["text"] for r in table_rows(datatable)]


@then(parsers.parse('Claude was asked "{question}" with no earlier messages'))
def asked_without_history(fake_ask, question):
    assert fake_ask.calls[-1] == (unescape(question), [])


@then(parsers.parse('Claude was asked "{question}" with these earlier messages:'))
def asked_with_history(fake_ask, question, datatable):
    assert fake_ask.calls[-1] == (unescape(question), table_rows(datatable))


@then("Claude was not asked")
def not_asked(fake_ask):
    assert fake_ask.calls == []


@then(parsers.re(r"Claude was asked (?P<times>\d+) times?"))
def asked_times(fake_ask, times):
    assert len(fake_ask.calls) == int(times)


@then("the history is:")
def history_is(ctx, datatable):
    assert ctx["history"] == table_rows(datatable)


@then(parsers.parse('the history has {count:d} messages, from "{first}" to "{last}"'))
def history_span(ctx, count, first, last):
    history = ctx["history"]
    assert (len(history), history[0]["content"], history[-1]["content"]) == (count, first, last)
