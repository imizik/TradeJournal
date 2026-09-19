"""OCC option symbols: build one, parse one back.

The 21-character OCC form is `{root}{yymmdd}{C|P}{strike * 1000, 8 digits}`,
e.g. `TSLA260710C00250000`. Every market-data vendor this repository talks to
uses it, so the conversion was written three times independently -- in
`trade_path`, in `scalper`, and again the moment a third provider needed it.
This is the one copy.

Pure: no network, no database, no credentials. `tests/test_import_boundaries.py`
holds it that way.

`occ_symbol` strips non-alphanumeric characters from the root, so `BRK.B`
becomes `BRKB` -- which is what the exchanges use and what the vendors expect.
It returns None rather than guessing when the option type is not call or put;
callers that have already validated the type still have to say what they want
to do with None, which is the point.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

OCC_TAIL_LENGTH = 15  # yymmdd (6) + C/P (1) + strike (8)


def occ_symbol(
    ticker: str,
    expiration: date,
    option_type: str,
    strike: float,
) -> Optional[str]:
    """Build an OCC symbol, or None if the inputs cannot make a valid one."""
    root = "".join(ch for ch in ticker.upper() if ch.isalnum())
    if not root:
        return None

    normalized = option_type.lower().strip() if option_type else ""
    side = "C" if normalized == "call" else "P" if normalized == "put" else None
    if side is None:
        return None

    return f"{root}{expiration:%y%m%d}{side}{int(round(strike * 1000)):08d}"


def parse_occ(occ: str) -> Optional[dict]:
    """Split an OCC symbol into root/expiration/option_type/strike, or None."""
    if not occ or len(occ) <= OCC_TAIL_LENGTH:
        return None

    tail = occ[-OCC_TAIL_LENGTH:]
    exp_s, cp, strike_s = tail[:6], tail[6], tail[7:]
    if cp not in ("C", "P") or not exp_s.isdigit() or not strike_s.isdigit():
        return None

    try:
        expiration = date(2000 + int(exp_s[:2]), int(exp_s[2:4]), int(exp_s[4:6]))
    except ValueError:
        return None

    return {
        "root": occ[:-OCC_TAIL_LENGTH],
        "expiration": expiration,
        "option_type": "call" if cp == "C" else "put",
        "strike": int(strike_s) / 1000.0,
    }
