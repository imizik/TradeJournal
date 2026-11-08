"""Where a copilot turn's wait goes (docs/copilot-lab.md § Where the wait goes): a round's reads run side by side and
come back in the order the model asked for them, each failure or timeout in its own place; the turn's metrics split
each round into model and tool time and each read into its parts; a live turn starts its symbol's quote (and, when the
owner names a price, its chart) while the owner context is read. Offline: scripted models and sleeping evidence."""
import asyncio
import threading
import time

from app.ai import copilot
from app.ai.copilot_answer import ANSWER_SHAPE
from app.ai.copilot_fixture import FixtureEvidence
from tests.test_copilot import NOW, _cfg

SLOW, FAST = 0.6, 0.3


class Sleepy(FixtureEvidence):
    """Fixture evidence whose peer read takes SLOW seconds and whose quote takes FAST: asked in that order, the first
    read finishes last."""

    def get_peer_moves(self, symbol):
        time.sleep(SLOW)
        return super().get_peer_moves(symbol)

    def get_quotes(self, symbols):
        time.sleep(FAST)
        return super().get_quotes(symbols)


class Asks:
    """Asks for ``calls`` in one round, then answers with a line; keeps every message it was sent."""
    model = "asks"

    def __init__(self, calls):
        self.calls, self.sent, self.started = calls, [], []

    async def stream_round(self, system, messages, tools, allow_tools=True):
        self.started.append(time.monotonic())
        self.sent.append([dict(m) for m in messages])
        if isinstance(messages[-1]["content"], list):
            yield "text", "Verdict: Wait — Read."
            yield "final", copilot.Round([{"type": "text", "text": "Verdict: Wait — Read."}], "end_turn", copilot._zero_usage())
            return
        content = [{"type": "tool_use", "id": f"c{i}", "name": name, "input": args} for i, (name, args) in enumerate(self.calls)]
        yield "final", copilot.Round(content, "tool_use", copilot._zero_usage())


def _run(adapter, evidence, *, cfg=None, symbol="NBIS", question="Is NBIS lagging?"):
    async def collect():
        return [e async for e in copilot.run_turn([{"role": "user", "content": question}], symbol, cfg or _cfg(), adapter, evidence, NOW)]
    return asyncio.run(collect())


def test_a_rounds_reads_run_side_by_side_and_come_back_in_the_order_asked():
    adapter = Asks([("get_peer_moves", {"symbol": "NBIS"}), ("get_quotes", {"symbols": ["NBIS"]})])
    events = _run(adapter, Sleepy())
    metrics = events[-1]["metrics"]
    first, answer = metrics["rounds_ms"]
    ran = {c["name"]: c["ms"] for c in metrics["tool_calls"] if c["name"] != "owner_context"}
    # Side by side: the round's reads take about as long as the slower one, not the two added up.
    assert ran["get_peer_moves"] >= SLOW * 1000 and ran["get_quotes"] >= FAST * 1000
    assert SLOW * 1000 <= first["tools_ms"] < (SLOW + FAST) * 1000 - 150
    assert "tools_ms" not in answer and answer["model_ms"] >= 0
    # The quote finished first; the results still follow the model's order, and the shape reminder is last.
    finished = [e["name"] for e in events if e["type"] == "tool" and e.get("status") == "ok" and e["name"] != "owner_context"]
    results = adapter.sent[1][-1]["content"]
    assert [b.get("tool_use_id") for b in results[:-1]] == ["c0", "c1"] and finished == ["get_peer_moves", "get_quotes"]
    assert results[-1] == {"type": "text", "text": ANSWER_SHAPE}


def test_a_failing_and_a_timed_out_read_keep_their_place_and_do_not_hold_the_round():
    class Broken(Sleepy):
        def get_quotes(self, symbols):
            raise RuntimeError("provider exploded with secret detail")

    adapter = Asks([("get_quotes", {"symbols": ["SPY"]}), ("get_peer_moves", {"symbol": "NBIS"}), ("get_symbol_news", {"symbol": "NBIS"})])
    events = _run(adapter, Broken(), cfg=_cfg(tool_timeout_s=0.2))
    results = adapter.sent[1][-1]["content"]
    assert [(b["tool_use_id"], b.get("is_error", False)) for b in results[:-1]] == [("c0", True), ("c1", True), ("c2", False)]
    assert results[0]["content"] == "Evidence source unavailable." and results[1]["content"] == "Evidence source timed out."
    assert results[-1] == {"type": "text", "text": ANSWER_SHAPE}
    tools_ms = events[-1]["metrics"]["rounds_ms"][0]["tools_ms"]
    assert tools_ms < SLOW * 1000  # the timeout ends the round's wait, not the slow read
    assert "secret detail" not in str(events)


def test_every_read_records_its_split_and_the_ui_rows_stay_as_they_were():
    events = _run(Asks([("get_quotes", {"symbols": ["NBIS"]})]), FixtureEvidence())
    calls = events[-1]["metrics"]["tool_calls"]
    assert [c["name"] for c in calls] == ["owner_context", "get_quotes"]
    for call in calls:
        assert set(call) == {"name", "status", "ms", *copilot.TIMING_KEYS} and call["status"] == "ok"
        assert call["feed_wait_ms"] == 0 and call["feed_ms"] == 0  # fixture evidence never reads the chart feed
    assert not any("timing" in e for e in events if e["type"] == "tool")
    assert events[-1]["metrics"]["prefetch"] == []  # fixture evidence is never prefetched


def test_a_read_through_the_chart_feed_reports_its_wait_and_provider_time():
    from app.engine.chart_timing import measured

    class Feed(FixtureEvidence):
        def get_quotes(self, symbols):
            with measured("tradier_queue"):
                time.sleep(0.05)
            with measured("tradier_provider"):
                time.sleep(0.1)
            return super().get_quotes(symbols)

    events = _run(Asks([("get_quotes", {"symbols": ["NBIS"]})]), Feed())
    [call] = [c for c in events[-1]["metrics"]["tool_calls"] if c["name"] == "get_quotes"]
    assert call["feed_wait_ms"] >= 50 and call["feed_ms"] >= 100 and call["ms"] >= call["feed_wait_ms"] + call["feed_ms"]


class LiveRecording(FixtureEvidence):
    """Live-labelled fixture evidence that notes when each read started; the owner context takes 0.2 s."""
    label = "live"

    def __init__(self):
        super().__init__()
        self.reads: list[tuple[str, tuple, float]] = []
        self.lock = threading.Lock()

    def _note(self, name, *args):
        with self.lock:
            self.reads.append((name, args, time.monotonic()))

    def owner_context(self, symbol, bounded=True):
        time.sleep(0.2)
        return super().owner_context(symbol, bounded)

    def get_quotes(self, symbols):
        self._note("get_quotes", symbols)
        return super().get_quotes(symbols)

    def get_chart_context(self, symbol, timeframe):
        self._note("get_chart_context", symbol, timeframe)
        return super().get_chart_context(symbol, timeframe)


def test_a_live_turn_starts_its_symbols_quote_while_the_owner_context_is_read():
    evidence, adapter = LiveRecording(), Asks([("get_peer_moves", {"symbol": "NBIS"})])
    events = _run(adapter, evidence, question="Is NBIS lagging its group?")
    assert events[-1]["metrics"]["prefetch"] == ["get_quotes"]
    [(name, args, at)] = evidence.reads
    assert (name, args) == ("get_quotes", (["NBIS"],)) and at < adapter.started[0]  # before the first model call


def test_a_named_price_also_starts_the_chart_and_nothing_starts_without_a_symbol():
    evidence, adapter = LiveRecording(), Asks([("get_peer_moves", {"symbol": "NBIS"})])
    events = _run(adapter, evidence, question="Should I take NBIS at 142.50?")
    assert events[-1]["metrics"]["prefetch"] == ["get_quotes", "get_chart_context"]
    assert sorted((n, a) for n, a, _ in evidence.reads) == [("get_chart_context", ("NBIS", copilot.PREFETCH_TIMEFRAME)),
                                                            ("get_quotes", (["NBIS"],))]
    assert all(at < adapter.started[0] for _, _, at in evidence.reads)
    quiet = LiveRecording()
    assert _run(Asks([]), quiet, symbol=None, question="What matters at 142.50?")[-1]["metrics"]["prefetch"] == []
    assert quiet.reads == []


def test_a_prefetch_that_fails_leaves_the_turn_and_the_models_own_call_alone():
    class Down(LiveRecording):
        def get_quotes(self, symbols):
            self._note("get_quotes", symbols)
            raise RuntimeError("quote provider down")

    evidence, adapter = Down(), Asks([("get_quotes", {"symbols": ["NBIS"]})])
    events = _run(adapter, evidence)
    assert [n for n, _, _ in evidence.reads] == ["get_quotes", "get_quotes"]  # the prefetch, then the model's own call
    assert adapter.sent[1][-1]["content"][0]["content"] == "Evidence source unavailable."
    assert events[-1]["type"] == "done"


def test_a_price_in_the_owners_words_is_told_from_times_dates_and_percents():
    named = ["take it at 140?", "break 142.50", "hold $142", "above 142.50.", "NVDA 600 level"]
    plain = ["what is NVDA doing", "at 9:45", "up 12%", "on 2026-11-08", "0DTE calls", "Q3 earnings", "11/8", "2 contracts",
             "the 5m chart", "1.5x volume"]
    assert all(copilot.LEVEL_IN_QUESTION.search(q) for q in named)
    assert not any(copilot.LEVEL_IN_QUESTION.search(q) for q in plain)
