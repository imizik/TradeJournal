"""
Robinhood email parser.

Handles two email types:
  - "Option order executed" -> ParsedFill with instrument_type="option"
  - "Your order has been executed" -> ParsedFill with instrument_type="stock"

All other subjects are silently ignored.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

_OPT_FILL_RE = re.compile(
    r"to (buy|sell) (\d+) contracts? of ([A-Z]+) \$([\d,]+\.?\d*) (Call|Put) (\d{1,2}/\d{1,2})",
    re.IGNORECASE,
)
_OPT_PRICE_RE = re.compile(r"average price of \$([\d,]+\.?\d*) per contract", re.IGNORECASE)

_STK_FILL_RE = re.compile(
    r"to (buy|sell) ([\d,]+\.?\d*) shares? of ([A-Z]+)",
    re.IGNORECASE,
)
_STK_DOLLAR_RE = re.compile(
    r"to (buy|sell) \$([\d,]+\.?\d*) of ([A-Z]+)",
    re.IGNORECASE,
)
_STK_PAID_SHARES_RE = re.compile(
    r"for ([\d,]+\.?\d*) shares",
    re.IGNORECASE,
)
_STK_PRICE_RE = re.compile(
    r"average price of \$([\d,]+\.?\d*)(?!\s*per contract)",
    re.IGNORECASE,
)

_DATETIME_RE = re.compile(
    r"on ([A-Za-z]+ \d{1,2}, \d{4}) at (\d{1,2}:\d{2} [AP]M) ET",
    re.IGNORECASE,
)

_ACCOUNT_LAST4_RE = re.compile(r"\([^0-9]*(\d{4})\)")
_ACCOUNT_TYPE_RE = re.compile(r"(Roth IRA|Individual|Traditional IRA|Brokerage)", re.IGNORECASE)

_ACCOUNT_TYPE_MAP = {
    "roth ira": "roth_ira",
    "individual": "individual",
    "traditional ira": "traditional_ira",
    "brokerage": "individual",
}

OPTION_SUBJECT = "Option order executed"
OPTION_PARTIAL_SUBJECT = "Option order partially executed"
STOCK_SUBJECT = "Your order has been executed"
OPTION_SUBJECTS = (OPTION_SUBJECT,)  # Skip partial-fill emails — they report cumulative
# counts that duplicate the complete-fill email. See scripts/find_phantoms.py.

_OPT_PARTIAL_FILLED_RE = re.compile(
    r"So far,\s*([\d,]+)\s+of\s+[\d,]+\s+contracts?\s+were filled",
    re.IGNORECASE,
)


@dataclass
class ParsedFill:
    ticker: str
    side: str
    contracts: Decimal
    price: Decimal
    executed_at: datetime
    instrument_type: str
    raw_email_id: str
    account_last4: str
    account_type: str
    option_type: str | None = None
    strike: Decimal | None = None
    expiration: date | None = None


class EmailParseError(Exception):
    pass


def _to_decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", ""))


def parse_option_email(subject: str, body: str, imap_uid: str) -> ParsedFill | None:
    s = subject.strip()
    if s in OPTION_SUBJECTS:
        return _parse_option(body, imap_uid, subject=s)
    if s == STOCK_SUBJECT:
        return _parse_stock(body, imap_uid)
    return None


def _parse_option(body: str, imap_uid: str, subject: str) -> ParsedFill:
    fill_match = _OPT_FILL_RE.search(body)
    price_match = _OPT_PRICE_RE.search(body)
    dt_match = _DATETIME_RE.search(body)

    if not fill_match:
        raise EmailParseError(f"Could not parse fill line from email uid={imap_uid!r}")
    if not price_match:
        raise EmailParseError(f"Could not parse price from email uid={imap_uid!r}")
    if not dt_match:
        raise EmailParseError(f"Could not parse datetime from email uid={imap_uid!r}")

    action = fill_match.group(1).lower()
    requested_contracts = _to_decimal(fill_match.group(2))
    ticker = fill_match.group(3).upper()
    strike = _to_decimal(fill_match.group(4))
    option_type = fill_match.group(5).lower()
    exp_str = fill_match.group(6)
    price = _to_decimal(price_match.group(1))

    contracts = requested_contracts
    if subject == OPTION_PARTIAL_SUBJECT:
        partial_match = _OPT_PARTIAL_FILLED_RE.search(body)
        if not partial_match:
            raise EmailParseError(f"Could not parse partial fill quantity from email uid={imap_uid!r}")
        contracts = _to_decimal(partial_match.group(1))

    executed_at = _parse_dt(dt_match)
    expiration = _infer_expiration(exp_str, executed_at.date())
    account_last4, account_type = _parse_account(body)
    side = "buy_to_open" if action == "buy" else "sell_to_close"

    return ParsedFill(
        ticker=ticker,
        side=side,
        contracts=contracts,
        price=price,
        executed_at=executed_at,
        instrument_type="option",
        option_type=option_type,
        strike=strike,
        expiration=expiration,
        raw_email_id=imap_uid,
        account_last4=account_last4,
        account_type=account_type,
    )


def _parse_stock(body: str, imap_uid: str) -> ParsedFill:
    fill_match = _STK_FILL_RE.search(body)
    dollar_match = _STK_DOLLAR_RE.search(body) if not fill_match else None
    price_match = _STK_PRICE_RE.search(body)
    dt_match = _DATETIME_RE.search(body)

    if not fill_match and not dollar_match:
        raise EmailParseError(f"Could not parse stock fill from email uid={imap_uid!r}")
    if not price_match:
        raise EmailParseError(f"Could not parse stock price from email uid={imap_uid!r}")
    if not dt_match:
        raise EmailParseError(f"Could not parse datetime from email uid={imap_uid!r}")

    if fill_match:
        action = fill_match.group(1).lower()
        shares = _to_decimal(fill_match.group(2))
        ticker = fill_match.group(3).upper()
    else:
        action = dollar_match.group(1).lower()  # type: ignore[union-attr]
        ticker = dollar_match.group(3).upper()  # type: ignore[union-attr]
        paid_match = _STK_PAID_SHARES_RE.search(body)
        shares = _to_decimal(paid_match.group(1)) if paid_match else Decimal("0")
    price = _to_decimal(price_match.group(1))

    executed_at = _parse_dt(dt_match)
    account_last4, account_type = _parse_account(body)
    side = "buy" if action == "buy" else "sell"

    return ParsedFill(
        ticker=ticker,
        side=side,
        contracts=shares,
        price=price,
        executed_at=executed_at,
        instrument_type="stock",
        raw_email_id=imap_uid,
        account_last4=account_last4,
        account_type=account_type,
    )


def _parse_dt(dt_match: re.Match) -> datetime:
    dt = datetime.strptime(f"{dt_match.group(1)} {dt_match.group(2)}", "%B %d, %Y %I:%M %p")
    return dt.replace(tzinfo=ET)


def _parse_account(body: str) -> tuple[str, str]:
    last4_match = _ACCOUNT_LAST4_RE.search(body)
    type_match = _ACCOUNT_TYPE_RE.search(body)
    account_type = _ACCOUNT_TYPE_MAP.get(type_match.group(1).lower(), "individual") if type_match else "unknown"
    account_last4 = last4_match.group(1) if last4_match else ""
    return account_last4, account_type


def _infer_expiration(exp_str: str, execution_date: date) -> date:
    month, day = (int(x) for x in exp_str.split("/"))
    year = execution_date.year
    candidate = date(year, month, day)
    if candidate < execution_date:
        candidate = date(year + 1, month, day)
    return candidate
