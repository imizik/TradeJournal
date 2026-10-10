"""R1 hand-calculated event, causality, quality and source-boundary evidence."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.engine.factory_data import FEATURES
from app.engine.factory_rules import MODEL_DEFAULT_FEATURES
from app.engine.market_map import ET
from app.engine.research_studio import (
    DISCOVERY_END, DISCOVERY_START, FEATURE_UNITS, MARKET, WARMUP_START,
    Definition, Observations, Predicate, parse_definition, session_close, session_dates,
)
from app.engine.research_studio_data import DiscoveryCache, _decode

DAY = date(2023, 7, 10)
BACKEND = Path(__file__).resolve().parents[1]


def moment(day=DAY, minute=600):
    return datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=ET)


def rows(day, *, volume=200):
    return [{"t": moment(day, m).astimezone(timezone.utc).isoformat(),
             "o": 100, "h": 101, "l": 100, "c": 100, "v": volume}
            for m in range(570, session_close(day))]


def write_day(root, symbol, day, raw):
    folder = root / symbol
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (str(day) + ".json")
    path.write_text(json.dumps(raw))
    return path


@pytest.fixture
def cache_root(tmp_path):
    root = tmp_path / "sip"
    root.mkdir()
    return root


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("r1-hand-fixture") / "sip"
    root.mkdir()
    for symbol in ("MU", MARKET):
        for day in session_dates(DAY):
            raw = rows(day, volume=400 if day == DAY and symbol == "MU" else 200)
            if day == DAY:
                raw[29].update(c=98, l=98) if symbol == "MU" else raw[29].update(c=100.5)
            write_day(root, symbol, day, raw)
    snapshot = DiscoveryCache(root).snapshot(("MU",), through=DAY)
    return root, snapshot, Observations(snapshot)


def question(**kwargs):
    return Definition((Predicate("move_15m_atr", maximum=-1), Predicate("rvol", minimum=1.5)),
                      universe=("MU",), start=DAY, end=DAY, window_start=600, window_end=600, **kwargs)


def values(observations, minute=600):
    return observations.features("MU", moment(minute=minute))


def test_hand_calculated_features_have_price_direction_units_and_no_stop(prepared):
    _, _, observations = prepared
    row = values(observations)
    expected = {"minutes": 30, "rvol": 2, "gap": 0, "day_move": -2, "trend": -2,
                "trend_slope": 0, "rel_strength": -2.5, "spy_trend": .5, "spy_day": .5,
                "vol_ratio": 1, "spy_vol": 1, "open_trend": 0, "move_15m_atr": -2}
    for name, value in expected.items():
        assert row[name].value == pytest.approx(value)
        assert row[name].reasons == ()
    vwap = (5 * (301 / 3) + 297 / 3) / 6
    assert row["vwap_distance"].value is None  # fewer than 14 same-session chart bars
    later = values(observations, minute=640)
    assert later["vwap_distance"].value is not None
    # Direct shared value independently pins the ATR/VWAP calculation at 10:00.
    context = observations._contexts["MU"]
    i = observations._quality["MU"].index[moment(minute=595)]
    assert context.decision_at(i)["vwap_distance"] == pytest.approx((98 - vwap) / ((13 + 3) / 14))
    assert "risk" not in row and "risk" not in context.decision_at(i)
    assert "move_15m_atr" not in FEATURES and "move_15m_atr" not in MODEL_DEFAULT_FEATURES
    assert "ATR" in FEATURE_UNITS["move_15m_atr"] and "15-minute" in FEATURE_UNITS["move_15m_atr"]


def test_factory_wrapper_preserves_values_keys_and_side_semantics(prepared):
    _, _, observations = prepared
    context = observations._contexts["MU"]
    i = observations._quality["MU"].index[moment(minute=595)]
    for side in (1, -1):
        actual = context.at(i, side, 97)
        assert list(actual) == list(FEATURES)
        assert actual["risk"] == pytest.approx(1 / context.chart_atr[i])
        assert {k: v for k, v in actual.items() if k != "risk"} == context.decision_at(i, side)
        assert actual["day_move"] == -2 * side


def test_first_match_is_not_a_crossing_and_population_contains_no_outcomes(prepared):
    _, _, observations = prepared
    definition = Definition((Predicate("rvol", minimum=1),), universe=("MU",), start=DAY, end=DAY,
                            window_start=600, window_end=610)
    result = observations.preview(definition)
    assert result["eligible_moments"] == result["qualifying_moments"] == 3
    assert result["event_count"] == 1
    event = result["events"][0]
    assert event["decision_time"] == moment().astimezone(timezone.utc).isoformat()
    assert result["distinct_dates"] == result["distinct_calendar_weeks"] == 1
    assert result["largest_day_fraction"] == 1
    assert event["occurrence_id"] == "MU:" + event["decision_time"]
    assert not {"outcomes", "returns", "pnl", "baseline", "uncertainty"} & result.keys()
    assert not {"outcomes", "next_open", "future_path"} & event.keys()
    assert observations.preview(question())["event_count"] == 1


def test_zero_is_valid_but_missing_and_zero_denominators_are_unavailable(cache_root, prepared):
    _, snapshot, _ = prepared
    target = next(x for x in snapshot.symbols if x.symbol == "MU")
    bars = tuple(replace(b, volume=0) if b.time.astimezone(ET).date() == DAY else b for b in target.bars)
    sources = tuple(replace(s, bars=bars) if s.symbol == "MU" else s for s in snapshot.symbols)
    row = values(Observations(replace(snapshot, symbols=sources)))
    assert row["rvol"].value == 0
    assert row["vwap_distance"].value is None
    flat = tuple(replace(s, bars=tuple(replace(b, high=100, low=100, close=100, open=100) for b in s.bars))
                 for s in snapshot.symbols)
    row = values(Observations(replace(snapshot, symbols=flat)))
    assert row["move_15m_atr"].value is None and "undefined_value" in row["move_15m_atr"].reasons
    assert row["vol_ratio"].value is None
    raw = rows(DAY)
    raw[0]["v"] = 0
    assert _decode(json.dumps(raw).encode(), DAY)[1].complete
    del raw[1]["v"]
    assert not _decode(json.dumps(raw).encode(), DAY)[1].complete


def mutated(prepared, symbol, change):
    _, snapshot, _ = prepared
    sources = []
    for source in snapshot.symbols:
        if source.symbol == symbol:
            source = change(source)
        sources.append(source)
    return Observations(replace(snapshot, symbols=tuple(sources)))


def remove_minute(source, day, minute):
    coverage = tuple(replace(c, valid_minutes=c.valid_minutes & ~(1 << (minute - 570))) if c.day == day else c
                     for c in source.coverage)
    return replace(source, coverage=coverage)



def drop_bucket(source, day, minute):
    for m in range(minute, minute + 5):
        source = remove_minute(source, day, m)
    return replace(source, bars=tuple(b for b in source.bars if b.time != moment(day, minute)))

def test_partial_and_missing_buckets_never_form_a_15_minute_move(prepared):
    obs = mutated(prepared, "MU", lambda s: remove_minute(s, DAY, 586))
    assert "move_15m_history_gap" in values(obs)["move_15m_atr"].reasons
    assert "cumulative_volume_gap" in values(obs)["rvol"].reasons
    # A wholly absent bucket also cannot be bridged to an earlier close.
    obs = mutated(prepared, "MU", lambda s: drop_bucket(s, DAY, 585))
    assert values(obs)["move_15m_atr"].value is None
    assert values(obs, 575)["move_15m_atr"].value is None  # never crosses overnight
    obs = mutated(prepared, "MU", lambda s: remove_minute(s, DAY, 598))
    assert values(obs)["minutes"].value is None
    assert observations_exclusion(obs, question())["incomplete_decision_bucket"] == 1


def observations_exclusion(obs, definition):
    return obs.preview(definition)["exclusions"]


def test_daily_warmup_complete_lookbacks_and_exact_session_open(prepared):
    _, _, obs = prepared
    first = obs.features("MU", moment(DISCOVERY_START, 600))
    assert "daily_warmup" in first["trend_slope"].reasons
    assert first["trend"].value is not None
    gap = mutated(prepared, "MU", lambda s: remove_minute(s, date(2023, 7, 7), 800))
    assert "daily_history_gap" in values(gap)["move_15m_atr"].reasons
    assert values(gap)["trend"].value is None
    opening = mutated(prepared, "MU", lambda s: remove_minute(s, DAY, 570))
    assert "missing_session_open" in values(opening)["day_move"].reasons
    assert values(opening)["trend"].value is not None  # current session open is not its input
    # Remove the entire day, while keeping a roster gap; no nearby daily substitution.
    def missing_day(s):
        return replace(s, bars=tuple(b for b in s.bars if b.time.astimezone(ET).date() != date(2023, 7, 7)),
                       coverage=tuple(replace(c, state="missing", valid_minutes=0) if c.day == date(2023, 7, 7) else c
                                      for c in s.coverage))
    assert values(mutated(prepared, "MU", missing_day))["move_15m_atr"].value is None


def test_rvol_rejects_bad_retained_history_without_reweighting_it(prepared):
    obs = mutated(prepared, "MU", lambda s: remove_minute(s, date(2023, 7, 7), 576))
    assert "rvol_history_gap" in values(obs)["rvol"].reasons
    # A gap after the same clock does not invalidate cumulative history at 10:00.
    obs = mutated(prepared, "MU", lambda s: remove_minute(s, date(2023, 7, 7), 700))
    assert values(obs)["rvol"].value == 2
    _, snapshot, _ = prepared
    early = Observations(replace(snapshot, through=date(2023, 6, 7),
                                 manifest=tuple(x for x in snapshot.manifest if x[1] <= "2023-06-07"),
                                 symbols=tuple(replace(s, bars=tuple(b for b in s.bars if b.time.astimezone(ET).date() <= date(2023, 6, 7)),
                                                       coverage=tuple(c for c in s.coverage if c.day <= date(2023, 6, 7)))
                                               for s in snapshot.symbols)))
    assert early._quality["MU"].rvol_reasons[-1] == "rvol_warmup"


def test_spy_must_be_exact_complete_and_have_its_own_daily_history(prepared):
    def missing(s):
        return drop_bucket(s, DAY, 595)
    obs = mutated(prepared, MARKET, missing)
    row = values(obs)
    for name in ("spy_trend", "spy_day", "spy_vol", "rel_strength"):
        assert row[name].value is None and "missing_aligned_spy" in row[name].reasons
    assert row["move_15m_atr"].value == -2
    obs = mutated(prepared, MARKET, lambda s: remove_minute(s, DAY, 599))
    assert values(obs)["spy_day"].value is None
    obs = mutated(prepared, MARKET, lambda s: remove_minute(s, date(2023, 7, 7), 800))
    assert "spy_daily_history_gap" in values(obs)["spy_trend"].reasons
    assert values(obs)["day_move"].value == -2


def test_future_perturbation_changes_manifest_not_prior_decision_features(prepared):
    _, snapshot, obs = prepared
    def future(s):
        return replace(s, bars=tuple(replace(b, high=900, low=1, close=5, volume=999999) if b.time >= moment() else b
                                    for b in s.bars))
    changed = mutated(prepared, "MU", future)
    before, after = values(obs), values(changed)
    for name in before:
        assert after[name].value == pytest.approx(before[name].value) if before[name].value is not None else after[name].value is None
        assert after[name].reasons == before[name].reasons
    # Appending a future split cannot change normalized past feature values.
    later_day = date(2023, 7, 11)
    sources = []
    for source in snapshot.symbols:
        new_bars, cov = _decode(json.dumps(rows(later_day)).encode(), later_day)
        if source.symbol == "MU":
            new_bars = [replace(b, open=b.open / 10, high=b.high / 10, low=b.low / 10, close=b.close / 10, volume=b.volume * 10)
                        for b in new_bars]
        sources.append(replace(source, bars=source.bars + tuple(new_bars), coverage=source.coverage + (cov,)))
    manifest = snapshot.manifest + tuple((source.symbol, str(later_day), "fixture", 0) for source in sources)
    later = Observations(replace(snapshot, through=later_day, symbols=tuple(sources), manifest=manifest))
    for name, value in before.items():
        if value.value is not None:
            assert values(later)[name].value == pytest.approx(value.value)


def test_same_date_correction_changes_data_identity_and_prepared_values(cache_root):
    path = write_day(cache_root, "MU", DAY, rows(DAY))
    write_day(cache_root, MARKET, DAY, rows(DAY))
    source = DiscoveryCache(cache_root)
    before = source.snapshot(("MU",), through=DAY)
    raw = rows(DAY)
    raw[29].update(c=90, l=90)
    path.write_text(json.dumps(raw))
    after = source.snapshot(("MU",), through=DAY)
    assert before.identity != after.identity
    assert before.symbols[0].bars[5].close == 100
    assert after.symbols[0].bars[5].close == 90
    # Old immutable snapshot stays tied to the original content.
    assert source.snapshot(("MU",), through=DAY).identity == after.identity


@pytest.mark.parametrize("kwargs", [
    {"through": date(2024, 10, 1)}, {"through": date(2026, 4, 1)},
    {"through": DAY, "cursor": date(2024, 10, 1)}, {"through": DAY, "cursor": date(2023, 6, 30)},
    {"through": WARMUP_START - timedelta(days=1)}, {"through": DAY, "symbols": ("../SPY",)},
    {"through": DAY, "symbols": ("SPY",)},
])
def test_invalid_date_cursor_and_symbol_rejected_before_any_payload_read(cache_root, monkeypatch, kwargs):
    source = DiscoveryCache(cache_root)
    calls = []
    monkeypatch.setattr(source, "_read", lambda *args: calls.append(args))
    with pytest.raises(ValueError):
        source.snapshot(**dict({"symbols": ("MU",)}, **kwargs))
    assert calls == []


def test_cold_loader_never_opens_protected_files_or_existing_derived_cache(cache_root, monkeypatch):
    write_day(cache_root, "MU", date(2024, 10, 1), [{"forbidden": "confirmation"}])
    write_day(cache_root, "MU", date(2026, 4, 1), [{"forbidden": "exam"}])
    (cache_root / "MU" / "MU_5m.pkl").write_bytes(b"never deserialize")
    write_day(cache_root, "MU", DISCOVERY_END, rows(DISCOVERY_END))
    original = os.open
    opened = []
    def spy(path, *args, **kwargs):
        opened.append(str(path))
        assert str(path) not in ("2024-10-01.json", "2026-04-01.json", "MU_5m.pkl")
        return original(path, *args, **kwargs)
    source = DiscoveryCache(cache_root)
    monkeypatch.setattr(os, "open", spy)
    snapshot = source.snapshot(("MU",), through=DISCOVERY_END)
    assert snapshot.symbols[0].bars
    assert "2024-09-30.json" in opened
    # Direct read-date path has the same pre-open guard.
    opened.clear()
    with pytest.raises(ValueError):
        source._read("MU", date(2024, 10, 1))
    assert opened == []


@pytest.mark.parametrize("directory", [False, True])
def test_symlink_escape_fails_closed_before_payload_read(cache_root, tmp_path, directory):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / (str(DAY) + ".json")
    secret.write_text('[{"forbidden": true}]')
    if directory:
        (cache_root / "MU").symlink_to(outside, target_is_directory=True)
    else:
        (cache_root / "MU").mkdir()
        (cache_root / "MU" / secret.name).symlink_to(secret)
    with pytest.raises(OSError):
        DiscoveryCache(cache_root).snapshot(("MU",), through=DAY)


@pytest.mark.parametrize("stamp", ["2024-10-01T13:30:00Z", "2026-04-01T13:30:00Z", "2023-07-10T09:30:00"])
def test_mislabeled_or_naive_payload_timestamp_is_rejected(cache_root, stamp):
    raw = rows(DAY)
    raw[0]["t"] = stamp
    write_day(cache_root, "MU", DAY, raw)
    with pytest.raises(ValueError):
        DiscoveryCache(cache_root).snapshot(("MU",), through=DAY)


def test_missing_empty_duplicate_invalid_and_off_grid_are_distinct(cache_root):
    raw = rows(DAY)
    raw.append(dict(raw[0]))
    raw[1]["l"] = 200
    raw[2]["t"] = raw[2]["t"].replace(":00+", ":01+")
    _, cov = _decode(json.dumps(raw).encode(), DAY)
    assert cov.duplicate_minutes == cov.invalid_rows == cov.off_grid_rows == 1
    assert not cov.complete and not cov.bucket_complete(570)
    assert _decode(b"[]", DAY)[1].state == "empty"
    write_day(cache_root, "MU", DAY, [])
    snapshot = DiscoveryCache(cache_root).snapshot(("MU", "NBIS"), through=DAY)
    result = Observations(snapshot).preview(question())
    assert result["coverage"]["MU"]["empty_sessions"] == 1
    assert result["eligible_moments"] == 0
    assert result["unavailable_symbols"] == ["MU"]
    assert result["largest_day_fraction"] is None


def test_fixed_roster_and_early_close_do_not_turn_missing_day_into_holiday(cache_root):
    assert len(session_dates()) == 335
    assert date(2023, 7, 4) not in session_dates()
    early = date(2023, 7, 3)
    write_day(cache_root, "MU", early, rows(early))
    snapshot = DiscoveryCache(cache_root).snapshot(("MU",), through=early)
    assert snapshot.symbols[0].coverage[-1].complete
    assert len(snapshot.symbols[0].bars) == 42
    result = Observations(snapshot).preview(Definition((Predicate("minutes", minimum=0),), universe=("MU",),
                                                     start=early, end=early, window_start=780, window_end=960))
    assert result["examined_clock_buckets"] == result["event_count"] == 1
    assert result["events"][0]["features"]["minutes"]["value"] == 210
    assert snapshot.symbols[0].coverage[0].state == "missing"


def test_definition_identity_is_semantic_and_rejects_unbounded_inputs():
    a = Predicate("rvol", minimum=1)
    b = Predicate("day_move", maximum=-1)
    assert Definition((a, b), ("MU", "AMD")).identity == Definition((b, a), ("AMD", "MU")).identity
    assert parse_definition(Definition((a, b)).canonical()).identity == Definition((a, b)).identity
    assert Definition((a,)).identity != Definition((replace(a, minimum=2),)).identity
    assert Definition((Predicate("day_move", maximum=-0.0),)).identity == Definition((Predicate("day_move", maximum=0),)).identity
    for raw in ({"predicates": []}, {"predicates": [{"feature": "risk", "minimum": 1}]},
                {"predicates": [a.canonical()], "stop": 1},
                {"predicates": [a.canonical()], "end": "2024-10-01"},
                {"predicates": [a.canonical()], "start": "2023-06-30"},
                {"predicates": [a.canonical()], "window_start": 601},
                {"predicates": [a.canonical()], "version": True},
                {"predicates": [{"feature": "rvol", "minimum": float("nan")}]},
                {"predicates": [{"feature": "rvol", "minimum": True}]},
                {"predicates": [a.canonical()] * 4}):
        with pytest.raises(ValueError):
            parse_definition({"version": 1, **raw})
    with pytest.raises(ValueError):
        parse_definition({"predicates": [a.canonical()]})
    with pytest.raises(ValueError):
        parse_definition({**Definition((a,)).canonical(), "rule": "threshold_crossing"})


def test_cli_sharp_decline_preview_is_read_only_and_imports_no_integrations(prepared, tmp_path):
    root, _, _ = prepared
    definition = tmp_path / "question.json"
    definition.write_text(json.dumps({"version": 1, "universe": ["MU"], "start": str(DAY), "end": str(DAY),
                                      "window_start": 600, "window_end": 600,
                                      "predicates": [{"feature": "move_15m_atr", "maximum": -1},
                                                     {"feature": "rvol", "minimum": 1.5}]}))
    before = {str(p): p.read_bytes() for p in root.rglob("*.json")}
    result = subprocess.run([sys.executable, str(BACKEND / "scripts" / "research_studio.py"),
                             "--cache-root", str(root), "--definition", str(definition)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["event_count"] == 1
    assert before == {str(p): p.read_bytes() for p in root.rglob("*.json")}
    imports = subprocess.run([sys.executable, "-c", "import app.engine.research_studio_data; import sys; "
                              "assert not {'app.database','app.engine.alpaca','app.main','app.config'} & set(sys.modules)"],
                             cwd=BACKEND, capture_output=True, text=True, timeout=10)
    assert imports.returncode == 0, imports.stderr


def test_warmup_and_protected_derived_snapshots_cannot_be_research_events(prepared):
    _, snapshot, obs = prepared
    for day in (date(2023, 6, 30), date(2024, 10, 1), date(2026, 4, 1)):
        with pytest.raises(ValueError):
            obs.features("MU", moment(day))
    with pytest.raises(ValueError):
        replace(snapshot, through=date(2024, 10, 1))
    with pytest.raises(ValueError):
        replace(snapshot, manifest=snapshot.manifest + (("MU", "2024-10-01", "bad", 0),))
    source = snapshot.symbols[0]
    with pytest.raises(ValueError):
        replace(snapshot, symbols=(replace(source, bars=source.bars + (replace(source.bars[-1], time=moment(date(2024, 10, 1))),)),
                                   snapshot.symbols[1]))
    with pytest.raises(ValueError):
        obs.features("MU", moment(minute=601))


def test_first_match_and_ids_are_per_symbol_and_session(prepared):
    _, snapshot, _ = prepared
    mu = next(x for x in snapshot.symbols if x.symbol == "MU")
    amd = replace(mu, symbol="AMD")
    snapshot = replace(snapshot, symbols=snapshot.symbols + (amd,),
                       manifest=snapshot.manifest + tuple(("AMD", d, h, size) for name, d, h, size in snapshot.manifest if name == "MU"))
    definition = Definition((Predicate("minutes", minimum=0),), universe=("MU", "AMD"),
                            start=date(2023, 7, 7), end=DAY, window_start=600, window_end=610)
    result = Observations(snapshot).preview(definition)
    assert result["event_count"] == 4
    assert len({e["occurrence_id"] for e in result["events"]}) == 4
    assert result["qualifying_moments"] == 12
    assert result["distinct_dates"] == 2 and result["largest_day_fraction"] == .5


def test_source_cursor_crops_before_open_and_snapshot_inputs_are_immutable(cache_root, monkeypatch):
    from dataclasses import FrozenInstanceError
    cache = DiscoveryCache(cache_root)
    calls = []
    original = cache._read
    def read(symbol, day):
        calls.append(day)
        return original(symbol, day)
    monkeypatch.setattr(cache, "_read", read)
    snapshot = cache.snapshot(("MU",), through=DISCOVERY_END, cursor=DAY)
    assert max(calls) == DAY and snapshot.through == DAY
    with pytest.raises(FrozenInstanceError):
        snapshot.through = DISCOVERY_END
    obs = Observations(snapshot)
    with pytest.raises(FrozenInstanceError):
        obs.snapshot = snapshot
    with pytest.raises(ValueError):
        obs.preview(Definition((Predicate("minutes", minimum=0),)))


def test_nonregular_source_cannot_block_the_loader(cache_root):
    folder = cache_root / "MU"
    folder.mkdir()
    os.mkfifo(folder / (str(WARMUP_START) + ".json"))
    with pytest.raises(ValueError, match="regular file"):
        DiscoveryCache(cache_root).snapshot(("MU",), through=DAY)


def test_cli_cannot_read_a_protected_cache_file_as_definition(cache_root, monkeypatch):
    from scripts.research_studio import main
    path = write_day(cache_root, "MU", date(2024, 10, 1), [{"forbidden": True}])
    calls = []
    original = Path.read_bytes
    def read(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", read)
    monkeypatch.setattr(sys, "argv", ["research_studio", "--cache-root", str(cache_root), "--definition", str(path)])
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == 2
    assert calls == []


def test_prepared_grid_reuses_only_matching_input_shape_and_reselects_first_event(prepared, monkeypatch):
    obs = mutated(prepared, "MU", lambda s: replace(s, bars=tuple(replace(b, volume=4000) if b.time == moment(minute=600) else b
                                                                for b in s.bars)))
    calls = []
    original = Observations._prepare_grid
    def prepare(self, definition):
        calls.append(definition)
        return original(self, definition)
    monkeypatch.setattr(Observations, "_prepare_grid", prepare)
    base = Definition((Predicate("rvol", minimum=1.5),), universe=("MU",), start=DAY, end=DAY,
                      window_start=600, window_end=610)
    first = obs.preview(base)
    tight = replace(base, predicates=(Predicate("rvol", minimum=2.2),))
    second = obs.preview(tight)
    assert len(calls) == 1
    assert first["events"][0]["decision_time"] == moment().astimezone(timezone.utc).isoformat()
    assert second["events"][0]["decision_time"] == moment(minute=605).astimezone(timezone.utc).isoformat()
    assert first["data_id"] == second["data_id"] and first["population_id"] != second["population_id"]
    assert first == obs.preview(base)  # cached grids never overwrite prior result identity/content
    obs.preview(replace(base, window_end=605))
    assert len(calls) == 2
    obs.preview(base)
    assert len(calls) == 3  # only one grid retained
    both = replace(tight, predicates=tight.predicates + (Predicate("move_15m_atr", maximum=-1),))
    assert obs.preview(both)["event_count"] == 0
    assert len(calls) == 4  # a new feature needs its own quality masks


def test_approved_root_identity_survives_ancestor_symlink_replacement(tmp_path, monkeypatch):
    parent = tmp_path / "approved"
    root = parent / "sip"
    root.mkdir(parents=True)
    source = DiscoveryCache(root)
    foreign = tmp_path / "foreign"
    foreign_root = foreign / "sip"
    foreign_root.mkdir(parents=True)
    write_day(foreign_root, "MU", WARMUP_START, [{"forbidden": True}])
    parent.rename(tmp_path / "old-approved")
    parent.symlink_to(foreign, target_is_directory=True)
    from app.engine import research_studio_data
    def decode(*args):
        pytest.fail("foreign payload was read")
    monkeypatch.setattr(research_studio_data, "_decode", decode)
    with pytest.raises(ValueError, match="root directory changed"):
        source.snapshot(("MU",), through=DAY)


def test_cli_pins_source_before_definition_read(tmp_path, monkeypatch, capsys):
    from scripts import research_studio as cli
    parent = tmp_path.resolve() / "approved"
    root = parent / "sip"
    root.mkdir(parents=True)
    foreign = tmp_path.resolve() / "foreign"
    (foreign / "sip").mkdir(parents=True)
    write_day(foreign / "sip", "MU", WARMUP_START, [{"forbidden": True}])
    definition = tmp_path.resolve() / "question.json"
    definition.write_text(json.dumps({"version": 1, "universe": ["MU"],
                                      "start": str(DAY), "end": str(DAY),
                                      "predicates": [{"feature": "minutes", "minimum": 0}]}))
    original_read = cli.read_definition
    def read(path):
        payload = original_read(path)
        parent.rename(parent.with_name("old-approved"))
        parent.symlink_to(foreign, target_is_directory=True)
        return payload
    opened = []
    original_open = os.open
    def open_file(path, *args, **kwargs):
        opened.append(str(path))
        return original_open(path, *args, **kwargs)
    # Reader checks capability membership against the patched function as well.
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {open_file})
    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(cli, "read_definition", read)
    monkeypatch.setattr(sys, "argv", ["research_studio", "--cache-root", str(root), "--definition", str(definition)])
    with pytest.raises(SystemExit) as raised:
        cli.main()
    assert raised.value.code == 2
    assert "approved root directory changed" in capsys.readouterr().err
    assert "MU" not in opened  # refusal before even opening a foreign symbol directory
    assert not any(p.endswith("2023-06-01.json") for p in opened)


@pytest.mark.parametrize("replacement", ["ancestor", "file"])
def test_cli_definition_replacement_refuses_before_protected_open(tmp_path, monkeypatch, replacement, capsys):
    from scripts import research_studio as cli
    root = tmp_path.resolve() / "sip"
    root.mkdir()
    protected = write_day(root, "MU", date(2024, 10, 1), [{"forbidden": True}])
    external = tmp_path.resolve() / "external"
    external.mkdir()
    definition = external / protected.name
    definition.write_text('{"version":1}')
    original_resolve = Path.resolve
    def resolve(path, *args, **kwargs):
        resolved = original_resolve(path, *args, **kwargs)
        if path == definition:
            if replacement == "ancestor":
                external.rename(external.with_name("old-external"))
                external.symlink_to(protected.parent, target_is_directory=True)
            else:
                definition.unlink()
                definition.symlink_to(protected)
        return resolved
    opened = []
    original_open = os.open
    def open_file(path, *args, **kwargs):
        fd = original_open(path, *args, **kwargs)
        opened.append(os.fstat(fd).st_ino)
        return fd
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {open_file})
    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(sys, "argv", ["research_studio", "--cache-root", str(root), "--definition", str(definition)])
    with pytest.raises(SystemExit) as raised:
        cli.main()
    assert raised.value.code == 2
    assert "invalid event definition" not in capsys.readouterr().err
    assert protected.stat().st_ino not in opened  # no successful protected-file open


def test_constructor_replacement_refuses_before_foreign_symbol_open(tmp_path, monkeypatch):
    parent = tmp_path.resolve() / "approved"
    root = parent / "sip"
    root.mkdir(parents=True)
    foreign = tmp_path.resolve() / "foreign"
    (foreign / "sip").mkdir(parents=True)
    write_day(foreign / "sip", "MU", WARMUP_START, [])
    original_resolve = Path.resolve
    def resolve(path, *args, **kwargs):
        resolved = original_resolve(path, *args, **kwargs)
        if path == root:
            parent.rename(parent.with_name("old-approved"))
            parent.symlink_to(foreign, target_is_directory=True)
        return resolved
    opened = []
    original_open = os.open
    def open_file(path, *args, **kwargs):
        fd = original_open(path, *args, **kwargs)
        opened.append(str(path))
        return fd
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {open_file})
    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(OSError):
        DiscoveryCache(root).snapshot(("MU",), through=DAY)
    assert "MU" not in opened
