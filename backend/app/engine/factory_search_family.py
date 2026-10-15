"""Research-only S1 minute-signal adapter; factory/ledger only, never merge."""
from dataclasses import dataclass
from datetime import datetime
from app.engine import factory_rules as rules, scanner_rules
from app.engine.factory_data import ET

@dataclass
class ScannerFamily:
    """S1 underlying signals from SIP minutes, with factory exits/costs.

    Research proxy only: no options premiums/spreads, no live activation,
    cooldown or open-position scanner admission. Native scanner rules unchanged.
    """
    setup: str = 'orb'
    sides: str = 'both'
    defaults = {'timeframe': 5, 'exits': {'target_r': 2.0, 'max_minutes': 60, 'max_sessions': 1},
                'window': [945, 1500], 'limits': {'max_entries': 2, 'max_losses': 2}}

    def validate(self):
        if self.setup not in ('orb', 'fade') or self.sides != 'both':
            raise ValueError('scanner setup must be orb/fade, sides both')

    def baseline_stop(self):
        return rules.MATCHED

    def start(self, series):
        if series.timeframe != 5:
            raise ValueError('S1 research signals require 5-minute bars')
        from strategy_factory import AlpacaCache, BarStore, DEFAULT_OUT
        minute = BarStore(AlpacaCache(), DEFAULT_OUT).load(series.ticker, 1, series.days[-1])
        by_day = {}
        for b in minute.bars():
            by_day.setdefault(b.time.astimezone(ET).date(), []).append(
                dict(time=int(b.time.timestamp()), open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume))
        signals = {}
        index = {int(t.timestamp()): i for i, t in enumerate(series.time)}
        for session, day in enumerate(series.days):
            daily = [dict(high=b.high, low=b.low, close=b.close) for b in series.daily[:session]]
            atr = scanner_rules.atr14(daily)
            if atr is None:
                continue
            opening = int(datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET).timestamp())
            ending = int(datetime(day.year, day.month, day.day, 15, tzinfo=ET).timestamp())
            bars = scanner_rules.five_minute_bars(by_day.get(day, []), opening, ending)
            taken = set()
            while True:
                remaining = [s for s in scanner_rules.scan(bars, atr, opening, ending, taken)
                             if (s['setup'], s['bar_end']) not in taken]
                if not remaining:
                    break
                found = remaining[0]
                taken.add((found['setup'], found['bar_end']))
                if found['setup'] == self.setup and found['bar_start'] in index:
                    i = index[found['bar_start']]
                    signals[i] = rules.Signal(i, 1 if found['direction'] == 'long' else -1, found['stop'])
        class Run:
            def on_bar(self, i, ctx):
                candidate = signals.get(i)
                return candidate if candidate and ctx.flat and not ctx.halted and ctx.accept(candidate) else None
        return Run()

