"""Write-once whole-market 09:00 ET SIP rankings. Only market-data GETs."""
from __future__ import annotations

import time
from datetime import date, datetime, time as clock, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from app.engine.scalp_shortlist_store import publish_once


ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[2] / "data" / "premarket_archive"
MIN_PRICE = 2
MIN_DOLLARS = 1_000_000
BATCH = 600


def at(day, hour):
    return datetime.combine(day, clock(hour), ET)


def timestamp(row):
    value = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Missing bar timezone")
    return value.astimezone(ET)


def positive(value):
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError("Invalid market-data value")
    return result


class Market:
    def __init__(self, client, config):
        self.client = client
        self.sip = {"APCA-API-KEY-ID": config["ALPACA_API_KEY"],
                    "APCA-API-SECRET-KEY": config["ALPACA_API_SECRET"]}
        self.reference = {"Authorization": "Bearer " + config["POLYGON_API_KEY"]}

    def get(self, url, params, headers):
        for attempt in range(4):
            response = self.client.get(url, params=params, headers=headers)
            if response.status_code != 429 or attempt == 3:
                response.raise_for_status()
                return response.json()
            time.sleep(60)

    def calendar(self, start, end):
        rows = self.get("https://paper-api.alpaca.markets/v2/calendar",
                        {"start": start.isoformat(), "end": end.isoformat()}, self.sip)
        days = [date.fromisoformat(row["date"]) for row in rows]
        if not days or days != sorted(set(days)):
            raise ValueError("Missing or invalid exchange calendar")
        return days

    def symbols(self, day):
        """Date-effective published CS/ETF list, including subsequently delisted listings."""
        url = "https://api.polygon.io/v3/reference/tickers"
        symbols = set()
        for kind in ("CS", "ETF"):
            params = dict(date=day.isoformat(), market="stocks", active="true", type=kind, limit=1000)
            seen = set()
            while True:
                page = self.get(url, params, self.reference)
                if page["status"] != "OK" or not page["results"]:
                    raise ValueError("Incomplete listing reference")
                for row in page["results"]:
                    if (row["type"] != kind or row["market"] != "stocks" or row["locale"] != "us"
                            or not row["active"]):
                        raise ValueError("Unexpected listing record")
                    symbol = row["ticker"]
                    if symbol in symbols:
                        raise ValueError("Duplicate listing")
                    symbols.add(symbol)
                if not page.get("next_url"):
                    break
                cursor, = parse_qs(urlsplit(page["next_url"]).query)["cursor"]
                if cursor in seen:
                    raise ValueError("Repeated listing cursor")
                seen.add(cursor)
                params = {"cursor": cursor}
        return sorted(symbols)

    def splits(self, day):
        page = self.get("https://api.polygon.io/stocks/v1/splits",
                        dict(execution_date=day.isoformat(), limit=1000), self.reference)
        if page["status"] != "OK" or page.get("next_url"):
            raise ValueError("Incomplete split reference")
        factors = {}
        for row in page.get("results", []):
            if row["execution_date"] != day.isoformat() or row["ticker"] in factors:
                raise ValueError("Unexpected split record")
            factors[row["ticker"]] = positive(row["split_from"]) / positive(row["split_to"])
        return factors

    def snapshots(self, symbols):
        result = {}
        for i in range(0, len(symbols), BATCH):
            group = symbols[i:i+BATCH]
            page = self.get("https://data.alpaca.markets/v2/stocks/snapshots",
                            dict(symbols=",".join(group), feed="sip"), self.sip)
            if not page or page.keys() - set(group):
                raise ValueError("Unexpected SIP snapshots")
            result.update(page)
        return result

    def bars(self, group, timeframe, start, end, asof):
        params = dict(symbols=",".join(group), timeframe=timeframe, start=start.isoformat(),
                      end=end.isoformat(), feed="sip", adjustment="raw", asof=asof.isoformat(),
                      limit=10000, sort="asc")
        seen = set()
        while True:
            page = self.get("https://data.alpaca.markets/v2/stocks/bars", params, self.sip)
            rows = page["bars"]
            if rows.keys() - set(group):
                raise ValueError("Unrequested bar symbol")
            yield from rows.items()
            token = page.get("next_page_token")
            if not token:
                break
            if token in seen:
                raise ValueError("Repeated SIP page")
            seen.add(token)
            params["page_token"] = token


def read_minutes(market, symbols, start, end, totals):
    """Accumulate only fully closed minutes inside this specific request window."""
    for i in range(0, len(symbols), BATCH):
        for symbol, rows in market.bars(symbols[i:i+BATCH], "1Min", start, end, start.date()):
            for row in rows:
                when = timestamp(row)
                if not start <= when <= end or when.second or when.microsecond:
                    raise ValueError("Bar outside pre-market window")
                old_time, _, volume, dollars = totals.get(symbol, (None, None, 0, Decimal(0)))
                if old_time and when <= old_time:
                    raise ValueError("Repeated or unordered SIP minute")
                size = row["v"]
                if type(size) is not int or size <= 0:
                    raise ValueError("Invalid bar volume")
                totals[symbol] = when, positive(row["c"]), volume + size, dollars + size * positive(row["vw"])


def inputs(market, day, prior, symbols, through):
    factors = market.splits(day)
    closes = {}
    for i in range(0, len(symbols), BATCH):
        group = symbols[i:i+BATCH]
        for symbol, bars in market.bars(group, "1Day", at(prior, 0), at(prior, 23), day):
            for bar in bars:
                if timestamp(bar).date() != prior or symbol in closes:
                    raise ValueError("Invalid previous daily bar")
                closes[symbol] = positive(bar["c"]) * factors.get(symbol, 1)
    totals = {}
    read_minutes(market, symbols, at(day, 4), through, totals)
    return closes, totals


def rank_inputs(day, symbols, closes, totals, snapshots=None):
    rows = []
    without_close = 0
    for symbol, (when, price, volume, dollars) in totals.items():
        if dollars < MIN_DOLLARS:
            continue
        if snapshots is not None:
            # A stale/missing snapshot cannot establish even the price-floor decision.
            minute = (snapshots.get(symbol) or {}).get("minuteBar")
            if not minute or timestamp(minute) != when:
                raise ValueError("Snapshot does not confirm the last pre-market minute")
            price = positive(minute["c"])
        if price < MIN_PRICE:
            continue
        if symbol not in closes:
            without_close += 1
            continue
        close = closes[symbol]
        change = (price / close - 1) * 100
        rows.append(dict(symbol=symbol, price=float(price), prior_regular_close=float(close),
                         volume=volume, dollar_volume=float(dollars), pct_change=float(change)))
    if not rows:
        raise ValueError("No eligible market data")
    gainers = sorted((r for r in rows if r["pct_change"] > 0), key=lambda r: (-r["pct_change"], r["symbol"]))
    losers = sorted((r for r in rows if r["pct_change"] < 0), key=lambda r: (r["pct_change"], r["symbol"]))
    return dict(as_of=at(day, 9).isoformat(), feed="sip", whole_market=True,
                source="contemporaneous" if snapshots is not None else "reconstructed-sip",
                ranking_basis="pct_vs_prior_regular_close", universe_size=len(symbols), eligible=len(rows),
                missing_prior_close=without_close, min_price=MIN_PRICE, min_dollar_volume=MIN_DOLLARS,
                gainers=gainers[:25], losers=losers[:25])


def reconstruct(market, day, prior, symbols):
    closes, totals = inputs(market, day, prior, symbols, at(day, 9) - timedelta(minutes=1))
    return rank_inputs(day, symbols, closes, totals)


def save(root, day, record):
    return publish_once(root / f"{day.isoformat()}.json", record)


def baseline(record):
    out = {k: record[k] for k in ("as_of", "feed", "whole_market", "source", "ranking_basis")}
    for side in ("gainers", "losers"):
        if len(record[side]) < 10:
            raise ValueError("Fewer than ten eligible stocks on one side")
        out[side] = [row["symbol"] for row in record[side][:10]]
    return out
