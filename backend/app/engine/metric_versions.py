"""Calculation identities; legacy rows deliberately have no version."""

CONTEXT_VERSION = "entry-context-v3"
PATH_VERSION = "position-path-v3"


def underlying_direction(fill) -> bool | None:
    """Bullish/bearish exposure at an opening fill, independent of premium side."""
    if fill.instrument_type == "stock":
        return True if fill.side == "buy" else None
    if fill.side not in ("buy_to_open", "sell_to_open") or fill.option_type not in ("call", "put"):
        return None
    return (fill.option_type == "call") == (fill.side == "buy_to_open")
