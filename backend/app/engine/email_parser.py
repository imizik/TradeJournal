"""
Robinhood options email parser.

Parses "Option order executed" emails from Robinhood into ParsedFill dataclasses.
All other email subjects are ignored — including stock fills, cancellations, etc.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Matches the core option fill line, e.g.:
#   "Your limit order to buy 1 contract of SNDK $620.00 Put 3/27"
#   "Your limit order to sell 2 contracts of SPY $657.00 Call 12/19"
_FILL_RE = re.compile(
    r"to (buy|sell) (\d+) contracts? of ([A-Z]+) \$([0-9.]+) (Call|Put) (\d{1,2}/\d{1,2})",
    re.IGNORECASE,
)

# Matches "average price of $175.00 per contract"
_PRICE_RE = re.compile(r"average price of \$([0-9.]+) per contract", re.IGNORECASE)

# Matches "on March 25, 2026 at 9:47 AM ET"
_DATETIME_RE = re.compile(
    r"on ([A-Za-z]+ \d{1,2}, \d{4}) at (\d{1,2}:\d{2} [AP]M) ET",
    re.IGNORECASE,
)

# Matches the account last4, e.g. "(•••8267)"
_ACCOUNT_RE = re.compile(r"\(•+(\d{4})\)")

OPTION_SUBJECT = "Option order executed"


@dataclass
class ParsedFill:
    ticker: str
    side: str           # "buy_to_open" | "sell_to_close" (heuristic — reconstructor corrects)
    contracts: int
    price: float        # per-contract premium in dollars
    executed_at: datetime   # tz-aware ET
    option_type: str    # "call" | "put"
    strike: float
    expiration: date
    raw_email_id: str   # IMAP UID
    account_last4: str  # e.g. "8267"


class EmailParseError(Exception):
    pass


def parse_option_email(subject: str, body: str, imap_uid: str) -> ParsedFill | None:
    """
    Parse a Robinhood email into a ParsedFill.

    Returns None if the subject is not "Option order executed" (stock fills,
    cancellations, confirmations, etc. are all silently ignored).

    Raises EmailParseError if the subject matches but parsing fails — this
    indicates a format change that needs investigation.
    """
    if subject.strip() != OPTION_SUBJECT:
        return None

    fill_match = _FILL_RE.search(body)
    price_match = _PRICE_RE.search(body)
    dt_match = _DATETIME_RE.search(body)

    if not fill_match:
        raise EmailParseError(f"Could not parse fill line from email uid={imap_uid!r}")
    if not price_match:
        raise EmailParseError(f"Could not parse price from email uid={imap_uid!r}")
    if not dt_match:
        raise EmailParseError(f"Could not parse datetime from email uid={imap_uid!r}")

    action = fill_match.group(1).lower()       # "buy" | "sell"
    contracts = int(fill_match.group(2))
    ticker = fill_match.group(3).upper()
    strike = float(fill_match.group(4))
    option_type = fill_match.group(5).lower()  # "call" | "put"
    exp_str = fill_match.group(6)              # "3/27" or "12/19"

    price = float(price_match.group(1))

    date_str = dt_match.group(1)   # "March 25, 2026"
    time_str = dt_match.group(2)   # "9:47 AM"
    executed_at = _parse_executed_at(date_str, time_str)

    expiration = _infer_expiration(exp_str, executed_at.date())

    # Heuristic: buys open positions, sells close them.
    # The reconstructor will correct this if the position state says otherwise.
    side = "buy_to_open" if action == "buy" else "sell_to_close"

    account_match = _ACCOUNT_RE.search(body)
    account_last4 = account_match.group(1) if account_match else ""

    return ParsedFill(
        ticker=ticker,
        side=side,
        contracts=contracts,
        price=price,
        executed_at=executed_at,
        option_type=option_type,
        strike=strike,
        expiration=expiration,
        raw_email_id=imap_uid,
        account_last4=account_last4,
    )


def _parse_executed_at(date_str: str, time_str: str) -> datetime:
    """Parse 'March 25, 2026' + '9:47 AM' into a tz-aware ET datetime."""
    dt = datetime.strptime(f"{date_str} {time_str}", "%B %d, %Y %I:%M %p")
    return dt.replace(tzinfo=ET)


def _infer_expiration(exp_str: str, execution_date: date) -> date:
    """
    Infer the expiration year from a 'M/DD' string.

    Uses the execution year if the resulting date is >= execution date,
    otherwise uses execution year + 1 (handles Dec execution / Jan expiry).
    """
    month, day = (int(x) for x in exp_str.split("/"))
    year = execution_date.year
    candidate = date(year, month, day)
    if candidate < execution_date:
        candidate = date(year + 1, month, day)
    return candidate
