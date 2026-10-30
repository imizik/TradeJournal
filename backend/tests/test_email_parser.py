from decimal import Decimal

import pytest

from app.engine.email_parser import (
    EmailParseError,
    OPTION_PARTIAL_SUBJECT,
    OPTION_SUBJECT,
    ParsedRoll,
    ROLL_SUBJECT,
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


def test_option_email_before_price_format_switch_keeps_literal_price() -> None:
    """Pre-2026-09-18 emails quote the per-contract total; store it verbatim."""
    body = (
        "Hi Isaac,\n"
        "Your limit order to buy 2 contracts of NBIS $230.00 Call 9/25 in your Roth IRA (...8267) "
        "account executed at an average price of $785.00 per contract "
        "on September 17, 2026 at 9:34 AM ET."
    )

    parsed = parse_option_email(OPTION_SUBJECT, body, "uid-nbis-old-format")

    assert parsed is not None
    assert parsed.price == Decimal("785.00")


def test_option_email_after_price_format_switch_is_scaled_to_per_contract() -> None:
    """
    From 2026-09-18 Robinhood quotes the per-share premium in the same
    "per contract" sentence, so $3.30 means $330.00 for the contract.
    """
    body = (
        "Hi Isaac,\n"
        "Your limit order to buy 1 contract of NBIS $230.00 Call 9/25 in your Roth IRA (...8267) "
        "account executed at an average price of $3.30 per contract "
        "on September 18, 2026 at 10:00 AM ET."
    )

    parsed = parse_option_email(OPTION_SUBJECT, body, "uid-nbis-new-format")

    assert parsed is not None
    assert parsed.price == Decimal("330.00")
    assert parsed.contracts == Decimal("1")


ROLL_BODY = ("Hi Isaac, Your limit order for 2 CRWV 2-Option Strategies executed at an average price of $1.32 "
             "for a total of $264.00 on October 29, 2026 at 11:16 AM ET.")


def test_two_leg_email_becomes_a_roll_and_other_mail_with_that_subject_stays_ignored() -> None:
    roll = parse_option_email(ROLL_SUBJECT, ROLL_BODY, "uid-roll")
    assert isinstance(roll, ParsedRoll)
    assert (roll.ticker, roll.contracts, roll.net_per_contract, roll.credit_mentioned) == ("CRWV", Decimal("2"), Decimal("132"), False)
    assert parse_option_email(ROLL_SUBJECT, "Your limit order to sell 2 contracts of X", "uid-other") is None


def test_two_leg_email_with_a_total_that_disagrees_refuses_to_parse() -> None:
    with pytest.raises(EmailParseError):
        parse_option_email(ROLL_SUBJECT, ROLL_BODY.replace("$264.00", "$26.40"), "uid-bad")


def test_a_rounded_average_on_several_fills_still_parses_from_its_total() -> None:
    roll = parse_option_email(ROLL_SUBJECT, ROLL_BODY.replace("for 2", "for 3").replace("$1.32", "$1.33").replace("$264.00", "$398.00"), "uid-avg")
    assert roll.contracts == Decimal("3") and round(roll.net_per_contract, 2) == Decimal("132.67")


def test_a_two_leg_email_in_unknown_wording_is_logged_not_dropped() -> None:
    with pytest.raises(EmailParseError):
        parse_option_email(ROLL_SUBJECT, "Your order for 2 BRK.B 2-Option Strategies filled at a net debit of $1.32", "uid-new")
