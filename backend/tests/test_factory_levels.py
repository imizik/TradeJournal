"""Past levels are unchanged by unseen bars, including split/half sessions."""
import math
from datetime import date, timedelta

import pytest

from app.engine.factory_data import FEATURES, LEVEL_FEATURES, FeatureContext, Series, session_bars
from app.engine.factory_rules import MODEL_DEFAULT_FEATURES, parse_spec
from tests.test_factory import bar, weekdays


def history():
    days = weekdays(date(2025, 5, 1), 45)
    return [bar(d, m, 100, 101 + (k % 5 == 2), 99 - (k % 5 == 2), 100)
            for k, d in enumerate(days) for m in (570, 575, 580, 585)], days[-1] + timedelta(days=1)


def equal(a, b):
    for name in a:
        assert a[name] == pytest.approx(b[name], nan_ok=True), name


@pytest.mark.parametrize('day,split', [(date(2025, 7, 3), False), (date(2025, 7, 3), True)])
def test_prefix_causality_split_and_early_close(day, split):
    past, _ = history()
    scale = 10 if split else 1
    today = [bar(day, m, 100 / scale, 102 / scale, 98 / scale, 101 / scale)
             for m in (570, 575, 580, 585, 775)]
    # Post-close contamination must not enter the half-day daily levels.
    raw = past + today + [bar(day, 780, 1, 999, 0.1, 1)]
    bars = session_bars(raw)
    full = FeatureContext(Series.build('TEST', bars, 5), None)
    for i in range(len(past), len(bars)):
        prefix = FeatureContext(Series.build('TEST', bars[:i+1], 5), None)
        equal(full.at(i, 1, 9), prefix.at(i, 1, 9))
    first = len(past)
    assert math.isnan(full.at(first + 2, 1, 9)['opening_range_high'])
    values = full.at(first + 3, 1, 9)
    atr = full.daily.atr[full.series.session[first] - 1]
    assert values['prior_day_high'] == pytest.approx((101 / scale - 101 / scale) / atr)
    assert values['opening_range_high'] == pytest.approx(-1 / scale / atr)
    equal({n: -values[n] for n in LEVEL_FEATURES},
          {n: full.at(first + 3, -1, 9)[n] for n in LEVEL_FEATURES})
    tomorrow = day + timedelta(days=1)
    following = FeatureContext(Series.build('TEST', bars + [bar(tomorrow, 570, 101/scale, 102/scale, 100/scale, 101/scale)], 5), None)
    assert following.levels['prior_day_high'][-1] == (102 / scale,)


def test_daily_week_and_confirmed_swings_exclude_today():
    bars, day = history()
    i = len(bars)
    ctx = FeatureContext(Series.build('TEST', bars + [bar(day, 570, 100, 999, 1, 100)], 5), None)
    assert ctx.levels['prior_day_high'][i] == (101,)
    assert ctx.levels['prior_week_high'][i] == (102,)
    assert ctx.levels['prior_week_low'][i] == (98,)
    assert ctx.levels['swing_high'][i] == (102,) * 9
    assert ctx.levels['swing_low'][i] == (98,) * 9
    # Missing OR bar, or a timeframe straddling its end, stays unavailable.
    for minutes, timeframe in [((570, 580, 585), 5), ((570, 590), 20)]:
        s = Series.build('TEST', bars + [bar(day, m, 100, 101, 99, 100) for m in minutes], timeframe)
        assert math.isnan(FeatureContext(s, None).decision_at(len(s)-1)['opening_range_high'])


def test_append_only_catalog_and_explicit_models():
    assert tuple(FEATURES)[:14] == ('minutes', 'rvol', 'gap', 'day_move', 'trend', 'trend_slope',
        'rel_strength', 'spy_trend', 'spy_day', 'risk', 'vwap_distance', 'vol_ratio', 'spy_vol', 'open_trend')
    assert len(MODEL_DEFAULT_FEATURES) == 10
    for name in LEVEL_FEATURES:
        spec = parse_spec({'family': 'opening_range_breakout', 'filters': [{'feature': name, 'min': 0}],
                           'model': {'kind': 'logistic', 'features': [name]}})
        assert spec.model.features == (name,)
