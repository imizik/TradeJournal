"""The leak-moment replay (scripts/leak_replay.py): find the deep-red minutes, blind them, cap the spend, score the calls."""
from datetime import date, datetime
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import Account, Fill, Trade, TradeFill
from scripts import leak_replay

ROTH = uuid.UUID("00000000-0000-4000-8000-000000000001")
WED = date(2026, 11, 18)


def ny(hour: int, minute: int = 0, day: int = 17) -> datetime:
    return datetime(2026, 11, day, hour, minute)


def bar(hour: int, minute: int, close: float, day: int = 17) -> dict:
    return {"t": f"2026-11-{day}T{hour + 5:02d}:{minute:02d}:00Z", "c": close}


def buy(qty, price, at) -> dict:
    return {"role": "entry", "side": "buy_to_open", "contracts": qty, "price": price, "executed_at": at}


def sell(qty, price, at) -> dict:
    return {"role": "exit", "side": "sell_to_close", "contracts": qty, "price": price, "executed_at": at}


@pytest.fixture
def engine():
    found = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(found)
    with Session(found) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267"))
        db.commit()
    yield found
    found.dispose()


def trade(db, ticker, fills, expiration=WED, status="closed", pnl=0.0, account=ROTH):
    row = Trade(account_id=account, ticker=ticker, instrument_type="option", contracts=1, option_type="call", strike=100,
                expiration=expiration, opened_at=fills[0]["executed_at"], closed_at=fills[-1]["executed_at"], status=status,
                realized_pnl=pnl, avg_entry_premium=fills[0]["price"], total_premium_paid=fills[0]["price"],
                expired_worthless=status == "expired")
    db.add(row)
    db.flush()
    for i, f in enumerate(fills):
        fill = Fill(account_id=account, ticker=ticker, instrument_type="option", side=f["side"], contracts=f["contracts"],
                    price=f["price"], executed_at=f["executed_at"], raw_email_id=f"{ticker}-{i}", option_type="call",
                    strike=100, expiration=expiration)
        db.add(fill)
        db.flush()
        db.add(TradeFill(trade_id=row.id, fill_id=fill.id, role=f["role"]))
    db.commit()
    return row


def book(db) -> dict:
    # Two days: an earlier moment where cutting would have saved $140, then a later one where holding paid.
    trade(db, "MUXX", [buy(2, 200, ny(10, day=16)), sell(2, 60, ny(14, day=16))], expiration=date(2026, 11, 17), pnl=-280)
    trade(db, "NBXX", [buy(1, 200, ny(10)), sell(1, 300, ny(15))], pnl=100)
    trade(db, "AMXX", [buy(1, 100, ny(10)), sell(1, 140, ny(10, 30))], pnl=40)  # under the hour: no moment
    webull = uuid.uuid4()
    db.add(Account(id=webull, name="Webull", type="individual", last4="0001", broker="webull"))
    trade(db, "WBXX", [buy(1, 200, ny(10)), sell(1, 50, ny(14))], pnl=-150, account=webull)
    return {"MUXX": [bar(10, 30, 1.80, day=16), bar(11, 6, 1.30, day=16)],
            "NBXX": [bar(10, 40, 2.30), bar(11, 20, 1.20)], "WBXX": [bar(11, 20, 1.00)]}


def stock(ticker, day):
    return [bar(10, 0, 50.0, day=day.day), bar(11, 6, 49.0, day=day.day), bar(11, 20, 49.5, day=day.day)]


def test_moments_are_the_deep_red_minutes_with_only_point_in_time_facts(engine):
    with Session(engine) as db:
        bars = book(db)
        found = leak_replay.find_moments(db, lambda t: bars.get(t.ticker), stock)
    assert [(m["ticker"], m["at"], m["saved"]) for m in found] == [("MUXX", ny(11, 6, day=16), 140.0),
                                                                   ("NBXX", ny(11, 20), -180.0)]
    first, later = found[0]["facts"], found[1]["facts"]
    assert (first["position_pct"], first["minutes_held"], first["days_to_expiry"], first["best_pct_so_far"]) == (-35.0, 66, 1, -10.0)
    assert first["underlying_move_pct"] == -2.0  # 50 -> 49 on a call
    # Nothing had closed before the first moment; the second sees the first trade and the first moment only.
    assert first["record"]["short_dated_trades"] == 0 and first["record"]["earlier_moments_like_this"] == 0
    # MUXX (-280) and AMXX (+40, closed 10:30) had closed by 11:20; the Webull trade never counts.
    assert later["record"] == {"short_dated_trades": 2, "short_dated_win_rate": 0.5, "short_dated_total_pnl": -240,
                               "earlier_moments_like_this": 1, "earlier_moments_where_cutting_saved_money": 1,
                               "earlier_moments_net_dollars_cutting_would_have_kept": 140}


def test_a_prompt_names_no_ticker_date_or_outcome(engine):
    with Session(engine) as db:
        bars = book(db)
        found = leak_replay.find_moments(db, lambda t: bars.get(t.ticker), stock)
    for m in found:
        text = leak_replay.prompt(m) + leak_replay.SYSTEM
        assert m["ticker"] not in text
        assert "2026" not in text and "Nov" not in text
        assert "300" not in text and str(m["realized_pnl"]) not in text  # the exit price and P&L stay out


def _fake_client(results=None, status="ended"):
    created = []

    class Batches:
        def create(self, requests):
            created.append(requests)
            return SimpleNamespace(id="msgbatch_test")

        def retrieve(self, batch_id):
            return SimpleNamespace(processing_status=status)

        def results(self, batch_id):
            return iter(results or [])

    return SimpleNamespace(messages=SimpleNamespace(batches=Batches())), created


def _moments(n: int) -> list[dict]:
    record = {"short_dated_trades": 3, "short_dated_win_rate": 0.333, "short_dated_total_pnl": -50, "earlier_moments_like_this": 0,
              "earlier_moments_where_cutting_saved_money": 0, "earlier_moments_net_dollars_cutting_would_have_kept": 0}
    facts = {"side": "call", "days_to_expiry": 0, "minutes_held": 70, "contracts": 2, "avg_cost_per_contract": 200.0,
             "mark_per_contract": 120.0, "position_pct": -40.0, "best_pct_so_far": 5.0, "worst_pct_so_far": -40.0, "buys_so_far": 1,
             "time_et": "11:10", "underlying_move_pct": None, "record": record}
    return [{"trade_id": str(uuid.uuid4()), "at": datetime(2026, 7, 1, 11, 10), "closed": datetime(2026, 7, 1, 15),
             "ticker": "XX", "facts": facts, "saved": 50.0, "realized_pnl": -300.0} for _ in range(n)]


def test_submit_refuses_over_the_cap_and_never_calls_the_api(tmp_path):
    client, created = _fake_client()
    with pytest.raises(leak_replay.Refused, match="max-usd"):
        leak_replay.submit(client, _moments(5), max_usd=0.0001, out_dir=tmp_path)
    with pytest.raises(leak_replay.Refused, match="month"):
        leak_replay.submit(client, _moments(5), max_usd=20, budget_left=0.0, out_dir=tmp_path)
    with pytest.raises(leak_replay.Refused, match="No leak moments"):
        leak_replay.submit(client, [], max_usd=20, out_dir=tmp_path)
    assert created == []


def test_submit_sends_one_blinded_structured_request_per_moment(tmp_path):
    client, created = _fake_client()
    manifest = leak_replay.submit(client, _moments(3), max_usd=20, out_dir=tmp_path)
    assert manifest["batch_id"] == "msgbatch_test" and len(created[0]) == 3
    params = created[0][0]["params"]
    assert params["model"] == "claude-sonnet-5-5" and params["output_config"]["format"]["type"] == "json_schema"
    assert "XX" not in params["messages"][0]["content"]
    assert set(json.loads((tmp_path / "msgbatch_test.manifest.json").read_text())["moments"]) == {"m0", "m1", "m2"}
    assert 0 < manifest["estimate_usd"] < 0.05  # three short questions at half price


def _result(custom_id, call=None, ok=True):
    usage = SimpleNamespace(input_tokens=500, output_tokens=60, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    content = [SimpleNamespace(type="text", text=json.dumps({"call": call, "confidence": 0.7, "reason": "r"}))]
    result = SimpleNamespace(type="succeeded", message=SimpleNamespace(usage=usage, content=content)) if ok \
        else SimpleNamespace(type="errored")
    return SimpleNamespace(custom_id=custom_id, result=result)


def test_scoring_compares_the_calls_with_always_and_never_cut():
    rows = [{"call": "cut", "saved": 140.0, "at": "2026-05-01T11:00:00", "days_to_expiry": 0},
            {"call": "hold", "saved": -180.0, "at": "2026-05-02T11:00:00", "days_to_expiry": 2},
            {"call": "cut", "saved": -50.0, "at": "2026-07-01T11:00:00", "days_to_expiry": 1},
            {"call": "add", "saved": 30.0, "at": "2026-07-02T11:00:00", "days_to_expiry": 0},
            {"call": None, "saved": 99.0, "at": "2026-07-03T11:00:00", "days_to_expiry": 0}]
    out = leak_replay.score(rows)
    assert out["all"] | {} == {"moments": 5, "answered": 4, "cut": 2, "hold": 1, "add": 1, "hit_rate": 0.5,
                               "model_dollars_kept": 90.0, "always_cut_dollars_kept": -60.0, "never_cut_dollars_kept": 0.0,
                               "cutting_saved_money_in": 2}
    assert (out["before_holdout"]["answered"], out["holdout"]["answered"]) == (2, 2)
    assert out["holdout"]["model_dollars_kept"] == -50.0
    assert (out["by_dte"]["0dte"]["moments"], out["by_dte"]["1-3dte"]["moments"]) == (3, 2)


def test_collect_waits_for_the_batch_then_scores_and_records_its_half_price_cost(tmp_path):
    client, _ = _fake_client(status="in_progress")
    leak_replay.submit(client, _moments(3), max_usd=20, out_dir=tmp_path)
    assert leak_replay.collect(client, "msgbatch_test", out_dir=tmp_path) == {"batch_id": "msgbatch_test", "status": "in_progress"}
    done, _ = _fake_client([_result("m0", "cut"), _result("m1", ok=False), _result("m2", "hold")])
    recorded = []
    report = leak_replay.collect(done, "msgbatch_test", out_dir=tmp_path, record=lambda m, **kw: recorded.append((m, kw)))
    assert report["score"]["all"]["answered"] == 2 and report["score"]["all"]["model_dollars_kept"] == 50.0
    # 1,000 in and 120 out at Sonnet's $2/$10, halved.
    assert report["cost_usd"] == pytest.approx((1000 * 2 + 120 * 10) / 1e6 / 2)
    assert recorded[0][1] == {"kind": "research", "source": "api_runner"}
    assert recorded[0][0]["backend"] == "api_background"
    assert (tmp_path / "msgbatch_test.results.json").exists()


def test_the_dry_run_is_the_default_and_spends_nothing(monkeypatch, capsys, engine):
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(leak_replay, "_client", lambda: pytest.fail("the dry run must not build a client"))
    assert leak_replay.main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["moments"] == 0 and out["estimate_usd"] == 0
