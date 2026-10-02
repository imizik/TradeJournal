"""Provider-independent option chain models (Charts C4.1).

An adapter fills these and everything above it reads them, never a provider
field name. Today the one adapter is `options_chain.py` (Tradier). Pure: no
network, no database, no credentials, held that way by
`tests/test_import_boundaries.py` so the positioning engine and the recorder
can compute on chains without reaching a vendor client.

Every market number here is *observed*: a provider value passed through, never
filled in. None means the provider supplied no usable value. A zero is a real
zero (no open interest, nothing traded today); a placeholder a provider uses for
"not available" is turned into None by its adapter, never here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class OptionContract:
    symbol: str  # OCC, for example SPXW261016P07680000
    underlying: str  # SPX
    # SPX (AM-settled) and SPXW (PM-settled) share expiration dates and strikes
    # but are different contracts, so nothing that aggregates may merge roots.
    root: str
    expiration: date
    option_type: str  # "call" or "put"
    strike: float
    # Shares per contract. 100 unless the contract was adjusted for a corporate
    # action; None when the provider did not say, which is not a licence to assume 100.
    multiplier: int | None
    # Premiums are per share, as quoted.
    bid: float | None
    ask: float | None
    last: float | None
    bid_size: int | None
    ask_size: int | None
    volume: int | None  # contracts traded today so far
    # The provider's current figure. OCC publishes open interest once overnight,
    # so it describes the previous session's close, not live positions.
    open_interest: int | None
    # Provider event times, UTC.
    bid_time: datetime | None
    ask_time: datetime | None
    trade_time: datetime | None
    iv: float | None  # mid implied volatility, as a decimal (0.18 = 18%)
    iv_smoothed: float | None  # the provider's smoothed-surface volatility for this strike
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    # The provider's own as-of stamp for iv and the greeks, verbatim. Greeks are
    # refreshed on the provider's schedule (hourly for Tradier), not with the
    # quote, and the stamp's time zone is not documented, so it is not parsed.
    greeks_updated_at: str | None


@dataclass(frozen=True, slots=True)
class OptionChain:
    """Every contract one provider lists for one underlying and expiration date."""

    underlying: str
    expiration: date
    provider: str
    # When this process received the response, UTC. A capture time, not a
    # provider as-of: those are on each contract.
    fetched_at: datetime
    contracts: tuple[OptionContract, ...]
