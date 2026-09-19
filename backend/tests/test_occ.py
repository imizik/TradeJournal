"""OCC symbol building and parsing.

These moved out of test_scalper.py when the third copy of the conversion was
about to be written. The round-trip cases are the originals; the rest cover the
two behaviours that differed between the copies and are now settled:
a non-alphanumeric root, and an option type that is neither call nor put.
"""

from datetime import date

from app.engine.occ import occ_symbol, parse_occ


def test_occ_symbol_round_trip():
    occ = occ_symbol("TSLA", date(2026, 7, 10), "call", 250)
    assert occ == "TSLA260710C00250000"
    parsed = parse_occ(occ)
    assert parsed == {"root": "TSLA", "expiration": date(2026, 7, 10),
                      "option_type": "call", "strike": 250.0}

    occ = occ_symbol("nbis", date(2026, 12, 18), "put", 42.5)
    assert occ == "NBIS261218P00042500"
    parsed = parse_occ(occ)
    assert parsed["option_type"] == "put"
    assert parsed["strike"] == 42.5


def test_parse_occ_rejects_garbage():
    assert parse_occ("") is None
    assert parse_occ("TSLA") is None
    assert parse_occ("TSLA260710X00250000") is None
    # 15 characters is the tail with no root left for a symbol.
    assert parse_occ("260710C00250000") is None
    assert parse_occ("TSLA261332C00250000") is None  # month 13, day 32


def test_root_drops_non_alphanumeric_characters():
    # Exchanges and every vendor here write BRK.B's options against BRKB.
    assert occ_symbol("BRK.B", date(2026, 7, 10), "call", 500) == "BRKB260710C00500000"
    assert occ_symbol("", date(2026, 7, 10), "call", 500) is None
    assert occ_symbol(".", date(2026, 7, 10), "call", 500) is None


def test_unknown_option_type_is_not_guessed():
    # The old scalper copy mapped anything that was not "call" to a put.
    assert occ_symbol("TSLA", date(2026, 7, 10), "p", 250) is None
    assert occ_symbol("TSLA", date(2026, 7, 10), "", 250) is None
    assert occ_symbol("TSLA", date(2026, 7, 10), "CALL", 250) == "TSLA260710C00250000"


def test_fractional_strikes_survive_the_round_trip():
    for strike in (0.5, 7.25, 42.5, 123.125, 1234.0):
        occ = occ_symbol("SPY", date(2026, 1, 16), "put", strike)
        assert parse_occ(occ)["strike"] == strike
