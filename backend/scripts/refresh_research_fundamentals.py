"""Refresh hard fundamentals in the AI Buildout research workspace from yfinance.

Fills each company's rev / gm / fcf (and corrects the cap bucket) from real
reported data instead of model recall. Re-runnable: always overwrites those
numeric fields with fresh feed values, never touches narrative fields, and
stamps each company with dataAsOf.

Usage:
    cd backend && .venv/bin/python scripts/refresh_research_fundamentals.py
"""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yfinance as yf
from sqlmodel import Session

from app.database import engine
from app.engine.research import get_or_create_workspace, save_workspace

SLUG = "ai-buildout"

# Sectors where gross margin is not a meaningful lens.
GM_NA_SECTORS = {"Financial Services", "Real Estate", "Utilities"}


def cap_bucket(mc: float | None) -> str | None:
    if not mc:
        return None
    b = mc / 1e9
    if b >= 200:
        return "mega"
    if b >= 10:
        return "large"
    if b >= 2:
        return "mid"
    if b >= 0.3:
        return "small"
    return "micro"


def fmt_money(x: float | None) -> str | None:
    if x is None:
        return None
    sign = "-" if x < 0 else ""
    a = abs(x)
    if a >= 1e9:
        return f"{sign}${a / 1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.0f}M"
    return f"{sign}${a:.0f}"


def fmt_pct_signed(x: float | None) -> str | None:
    return None if x is None else f"{x * 100:+.0f}%"


def fmt_pct(x: float | None) -> str | None:
    return None if x is None else f"{x * 100:.0f}%"


def fetch(ticker: str) -> dict | None:
    for attempt in (1, 2):
        try:
            info = yf.Ticker(ticker).info
            if not info or info.get("marketCap") is None and info.get("regularMarketPrice") is None:
                return None
            return info
        except Exception as e:  # noqa: BLE001 - per-ticker failures are tolerated
            if attempt == 2:
                print(f"  {ticker}: FAILED ({e})")
                return None
            time.sleep(1.5)
    return None


def main() -> None:
    today = date.today().isoformat()
    with Session(engine) as session:
        row = get_or_create_workspace(session, SLUG)
        if row is None:
            raise SystemExit("workspace not found")
        import json

        data = json.loads(row.data_json)
        companies = data.get("companies", {})
        updated = 0
        failed: list[str] = []

        for ticker in sorted(companies):
            info = fetch(ticker)
            if info is None:
                failed.append(ticker)
                continue
            c = companies[ticker]
            sector = info.get("sector") or ""

            rev = fmt_pct_signed(info.get("revenueGrowth"))
            total_rev = info.get("totalRevenue")
            if rev is None and total_rev is not None and total_rev < 5e7:
                rev = "pre-rev"

            gm = "n/a" if sector in GM_NA_SECTORS else fmt_pct(info.get("grossMargins"))
            # Statement figures come in the filing currency (TSM=TWD, ASML=EUR);
            # label non-USD instead of presenting them as dollars.
            fin_ccy = info.get("financialCurrency") or "USD"
            fcf = fmt_money(info.get("freeCashflow"))
            if fcf is not None and fin_ccy != "USD":
                fcf = f"{fcf.replace('$', '')} {fin_ccy}"
            cap = cap_bucket(info.get("marketCap"))

            if rev is not None:
                c["rev"] = rev
            if gm is not None:
                c["gm"] = gm
            if fcf is not None:
                c["fcf"] = fcf
            if cap is not None:
                c["cap"] = cap
            c["dataAsOf"] = today
            updated += 1
            print(f"  {ticker}: rev={c.get('rev','—')} gm={c.get('gm','—')} fcf={c.get('fcf','—')} cap={c.get('cap','—')}")
            time.sleep(0.4)

        save_workspace(session, row, data)
        print(f"\nUpdated {updated}/{len(companies)} companies (revision -> {row.revision})")
        if failed:
            print(f"No data for: {', '.join(failed)}")


if __name__ == "__main__":
    main()
