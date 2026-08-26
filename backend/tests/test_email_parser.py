from decimal import Decimal

from app.engine.email_parser import (
    OPTION_PARTIAL_SUBJECT,
    OPTION_SUBJECT,
    parse_option_email,
)


def test_parse_stock_email_with_integer_shares_wording() -> None:
    body = (
        "Hi Isaac,\n"
        "Your order to sell 250 shares of RNXT through your Roth IRA (...8267) "
        "account was executed at an average price of $0.96 on March 16, 2026 at 2:46 PM ET. "
        "Funds available from this trade will be reflected in your withdrawable cash on Mar. 17, 2026."
    )

    parsed = parse_option_email("Your order has been executed", body, "uid-rnxt")

    assert parsed is not None
    assert parsed.instrument_type == "stock"
    assert parsed.ticker == "RNXT"
    assert parsed.side == "sell"
    assert parsed.contracts == Decimal("250")
    assert parsed.price == Decimal("0.96")
    assert parsed.account_last4 == "8267"
    assert parsed.account_type == "roth_ira"


def test_parse_stock_email_with_fractional_shares_keeps_precision() -> None:
    body = (
        "Hi Isaac,\n"
        "Your order to buy $80.00 of RCAT through your Roth IRA (...8267) account "
        "was executed at an average price of $8.17 on March 25, 2026 at 9:47 AM ET. "
        "You paid $80.00 for 9.78593 shares."
    )

    parsed = parse_option_email("Your order has been executed", body, "uid-rcat")

    assert parsed is not None
    assert parsed.instrument_type == "stock"
    assert parsed.ticker == "RCAT"
    assert parsed.side == "buy"
    assert parsed.contracts == Decimal("9.78593")
    assert parsed.price == Decimal("8.17")


def test_partial_execution_option_email_is_skipped() -> None:
    """
    Partial-fill option emails report *cumulative* filled counts, so a
    3-of-13 email followed by a 13-of-13 email would import 16 contracts.
    They are deliberately excluded from OPTION_SUBJECTS; only the final
    "Option order executed" email becomes a fill. See scripts/find_phantoms.py.
    """
    body = (
        "Hi Isaac,\n"
        "Your limit order to sell 13 contracts of COST $1,050.00 Call 2/20 in your Roth IRA (...8267) "
        "account executed on February 10, 2026 at 1:54 PM ET. "
        "So far, 1 of 13 contracts were filled for an average price of $60.00 per contract."
    )

    assert parse_option_email(OPTION_PARTIAL_SUBJECT, body, "uid-cost-partial") is None


def test_complete_option_email_still_parses() -> None:
    body = (
        "Hi Isaac,\n"
        "Your limit order to sell 13 contracts of COST $1,050.00 Call 2/20 in your Roth IRA (...8267) "
        "account executed on February 10, 2026 at 1:54 PM ET "
        "at an average price of $60.00 per contract."
    )

    parsed = parse_option_email(OPTION_SUBJECT, body, "uid-cost-complete")

    assert parsed is not None
    assert parsed.instrument_type == "option"
    assert parsed.ticker == "COST"
    assert parsed.side == "sell_to_close"
    assert parsed.contracts == Decimal("13")
    assert parsed.price == Decimal("60.00")
    assert parsed.strike == Decimal("1050.00")
    assert parsed.account_last4 == "8267"
