"""Check a call (docs/copilot-lab.md § Check a call): a trade call someone posted in the owner's Discord group, shared
to the Telegram bot or pasted on the desk, checked by the copilot and answered with one card.

The copilot does the reading and the judging as its own job (``ai/copilot_prompt.py`` ``CHECK``): it writes a Reading
line (ticker, expiry, strike, call or put, entry, stop, target, each a value or "?"), a Verdict line (Pass, Wait or
Draft), three or four Tile lines, Against, Changes if and, for a message with several calls, Also. Its facts come from
``get_call_facts`` (here: the underlying now, the contract's quote against the posted entry, the cost against the
owner's usual opening premium, his own record on trades like it). Nothing here is a parser of the call: ``confirm``
only blanks a value the model read that the message's text does not contain (a ticker, a number, a call or put marker,
an expiry), so nothing is ever guessed. A screenshot is read by the model alone.

Telling a call from a question (``classify``) is a routing rule for the Telegram bot, not a reading: a message that
starts with ``check`` is checked; otherwise its call markers are counted (a strike with c/p counts two; 0DTE, a
month/day, an entry word or ``@ price``, a stop/target/"hits" word, a $ price, a $TICKER one each). Two or more with no
question marker is a call; two or more with one, or one alone, is ambiguous (answered as a question, with a "Check as a
call" button); none is a question. Question markers: a closing "?", a first word such as what/why/should, or "my".

Every check is kept (``CallCheck``): when, what was read, the card, and the underlying's price and the contract's quote
at that moment, so the evening report can later score it from the check-time price, never from the posted one. Pass is
recorded on the row; "planned" means a pre-trade plan was saved with this check as its origin
(``TradeCapture.origin_kind == "checked_call"``): Plan it only opens the plan flow, never a ticket. No order, size or
"take it" anywhere.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

log = logging.getLogger(__name__)

FIELDS = ("ticker", "expiry", "strike", "side", "entry", "stop", "target")
BLANK_NAMES = {"ticker": "ticker", "expiry": "expiry", "strike": "strike", "side": "call or put", "entry": "entry price",
               "stop": "stop", "target": "target"}
VERDICTS = ("Pass", "Wait", "Draft")
RAW_MAX = 2000
TILES = 4
CHECK_HEAD = "Check this call."
NO_TICKER = "Could not read a ticker"
SCREENSHOT = "(screenshot)"
CONTEXT_MAX = 300  # frontend/lib/copilot.ts CONTEXT_MAX
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
MIN_RECORD = 10  # fewer trades than this: say the sample is small

# --------------------------------------------------------------------------- call or question

CONTRACT = re.compile(r"\b\d+(?:\.\d+)?\s?(?:c|p|calls?|puts?)\b", re.I)
DTE = re.compile(r"\b[o0]\s?dte\b", re.I)
MONTH_DAY = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?:/\d{2,4})?(?![\d/])")
ENTRY = re.compile(r"\b(?:entry|entered|entering|in at|bought|buying|grabbed|adding|added|starter|lotto|scalp)\b|@\s?\$?\d", re.I)
LEVELS = re.compile(r"\b(?:stop|sl|stop loss|target|targets|tp|pt|hits|trim)\b", re.I)
PRICE = re.compile(r"\$\d")
CASHTAG = re.compile(r"\$[a-z]{1,5}\b", re.I)
QUESTION_START = re.compile(r"^(?:what|whats|what's|why|how|hows|how's|should|is|are|can|could|do|does|did|when|where|which|"
                            r"who|will|would|explain|tell|show|give|any|was|were)\b", re.I)
QUESTION_WORDS = re.compile(r"\b(?:my|should i|do i|how's|hows|how is|what's|whats|why)\b", re.I)
FORCED = re.compile(r"^\s*check\b[\s:,.\-]*", re.I)


def classify(text: str) -> tuple[str, str]:
    """``(kind, text)``: ``call`` (check it now), ``maybe`` (answer it as a question, offer Check as a call) or
    ``question``; the text to check (``check`` prefix removed)."""
    text = (text or "").strip()
    if FORCED.match(text):
        return "call", FORCED.sub("", text, count=1).strip()
    score = (2 if CONTRACT.search(text) else 0) + sum(1 for rule in (DTE, MONTH_DAY, ENTRY, LEVELS, PRICE, CASHTAG) if rule.search(text))
    asked = text.endswith("?") or bool(QUESTION_START.match(text)) or bool(QUESTION_WORDS.search(text))
    if score >= 2 and not asked:
        return "call", text
    if score >= 2 or (score == 1 and not asked):
        return "maybe", text
    return "question", text


# --------------------------------------------------------------------------- the facts tool


def _number(value, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value < 1_000_000:
        raise ValueError(f"{name} must be a positive number")
    return float(value)


def facts_args(args: dict) -> dict:
    """``get_call_facts``' arguments, normalized; ValueError on a bad one."""
    symbol = str(args.get("symbol") or "").strip().lstrip("$").upper()
    if not SYMBOL.match(symbol):
        raise ValueError("symbol must be a ticker")
    out: dict = {"symbol": symbol}
    if args.get("side") is not None:
        if args["side"] not in ("call", "put"):
            raise ValueError("side must be call or put")
        out["side"] = args["side"]
    if args.get("expiry") is not None:
        try:
            out["expiry"] = date.fromisoformat(str(args["expiry"])).isoformat()
        except ValueError:
            raise ValueError("expiry must be YYYY-MM-DD") from None
    for key in ("strike", "entry", "stop", "target"):
        if (value := _number(args.get(key), key)) is not None:
            out[key] = value
    return out


def expiry_kind(days: int | None) -> str | None:
    if days is None:
        return None
    return "0DTE" if days <= 0 else "1-7 days" if days <= 7 else "longer"


def _summary(rows: list) -> dict:
    pnl = [float(r.realized_pnl) for r in rows]
    out = {"trades": len(pnl), "up": sum(p > 0 for p in pnl), "pnl": round(sum(pnl), 2)}
    if len(pnl) < MIN_RECORD:
        out["small_sample"] = True
    return out


def record_like(db, symbol: str, side: str | None, kind: str | None) -> dict:
    """The owner's closed option trades like the call: in the symbol, in it on that side, and on that side (or any side
    when unknown) with that kind of expiry. Webull is left out, as everywhere."""
    from sqlmodel import select
    from app.ai.copilot_book import _not_webull
    from app.models import Account, Trade
    rows = db.exec(select(Trade.ticker, Trade.option_type, Trade.expiration, Trade.opened_at, Trade.realized_pnl)
                   .join(Account, Account.id == Trade.account_id)
                   .where(Trade.instrument_type == "option", Trade.status != "open", Trade.realized_pnl.is_not(None))
                   .where(_not_webull())).all()

    def kind_of(row) -> str | None:
        return expiry_kind((row.expiration - row.opened_at.date()).days) if row.expiration and row.opened_at else None
    out = {"symbol": _summary([r for r in rows if r.ticker == symbol])}
    if side:
        out["symbol_side"] = _summary([r for r in rows if r.ticker == symbol and r.option_type == side])
    if kind:
        out["same_expiry_kind"] = {"kind": kind, "side": side or "any",
                                   **_summary([r for r in rows if kind_of(r) == kind and (not side or r.option_type == side)])}
    return out


def usual_premium(db) -> float | None:
    """His usual opening option premium per trade (the plan card's sizing line: ``setup_record``'s median), or None."""
    from app.engine import setup_record
    size = setup_record.record(setup_record.opening_trades(db), None, None).get("size")
    return size["usual"] if size else None


def _pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 2)


def combine(symbol: str, reading: dict, underlying: dict, contract: dict | None, usual: float | None, record: dict,
            today: date, as_of: str) -> dict:
    """The facts as the tool returns them, from reads already made (pure, so the live and simulated reads agree)."""
    last = underlying.get("last")
    out: dict = {"symbol": symbol, "state": "ok" if last else "partial", "as_of": as_of, "underlying": underlying}
    expiry = date.fromisoformat(reading["expiry"]) if reading.get("expiry") else None
    if expiry:
        days = (expiry - today).days
        out["expiry"] = {"date": expiry.isoformat(), "days_to_expiry": days, "kind": expiry_kind(days), "expired": days < 0}
    strike = reading.get("strike")
    if strike and last:
        out["to_strike_pct"] = _pct(strike, last)
    for key in ("stop", "target"):
        value = reading.get(key)
        if value and last:  # within half of the price it reads as a stock level; far under it, an option premium
            out[key] = ({"value": value, "reads_as": "stock level", "from_last_pct": _pct(value, last)} if abs(value / last - 1) <= 0.5
                        else {"value": value, "reads_as": "option premium"})
    missing = [k for k in ("expiry", "strike", "side") if not reading.get(k)]
    if missing:
        out["contract"] = {"state": "not_identified", "missing": missing}
    elif contract is not None:
        out["contract"] = contract
        mid, ask = contract.get("mid"), contract.get("ask")
        entry = reading.get("entry")
        if entry and mid:
            out["vs_posted_entry"] = {"entry": entry, "mid_now": mid, "move_pct": _pct(mid, entry), "past_entry": bool(ask and ask > entry)}
        if ask and usual:
            out["cost"] = {"one_contract_usd": round(ask * 100, 2), "usual_opening_premium_usd": usual,
                           "vs_usual": round(ask * 100 / usual, 2)}
    if usual and "cost" not in out:
        out["usual_opening_premium_usd"] = usual
    out["record"] = record
    return out


def _underlying(evidence, symbol: str) -> dict:
    read = evidence.get_quotes([symbol])
    quote = (read.get("quotes") or {}).get(symbol) or {}
    last = quote.get("last") or (read.get("prices") or {}).get(symbol)
    return {"last": last, "change_pct": quote.get("change_pct"), "day_high": quote.get("day_high"), "day_low": quote.get("day_low"),
            "prev_close": quote.get("prev_close"), "as_of": quote.get("trade_time") or read.get("fetched_at"),
            **({"extended": read["extended"]} if read.get("extended") else {})}


def contract_quote(symbol: str, expiry: date, strike: float, side: str) -> dict:
    """The contract's bid, ask and mid from the options feed's cache (the copilot's option candidates' read)."""
    from app.engine.options_feed import options_feed
    try:
        reads, issue = options_feed.chains(symbol, lambda live: [expiry] if expiry in live else [])
    except ValueError:
        return {"state": "unavailable", "reason": f"{symbol} is not an optionable symbol."}
    if not reads:
        return {"state": "unavailable" if issue else "not_listed", "reason": issue or f"No {symbol} {expiry:%m/%d} expiry is listed."}
    read = reads[0]
    found = next((c for c in read.value.contracts if c.option_type == side and abs(c.strike - strike) < 1e-6), None)
    if found is None:
        return {"state": "not_listed", "reason": f"No {symbol} {expiry:%m/%d} {strike:g} {side} is listed."}
    mid = round((found.bid + found.ask) / 2, 3) if found.bid is not None and found.ask is not None else None
    stamps = [t for t in (found.bid_time, found.ask_time) if t]
    at = max(stamps) if stamps else datetime.fromtimestamp(read.fetched, UTC)
    return {"state": "ok", "label": f"{symbol} {expiry:%m/%d} {strike:g}{side[0].upper()}", "bid": found.bid, "ask": found.ask,
            "mid": mid, "as_of": at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")}


def live_facts(symbol: str, **reading) -> dict:
    from sqlmodel import Session
    from app.ai.copilot_tools import LiveEvidence
    from app.database import engine
    from app.engine.chart_math import ET
    today = datetime.now(ET).date()
    underlying = _underlying(LiveEvidence(), symbol)
    contract = None
    if reading.get("expiry") and reading.get("strike") and reading.get("side"):
        contract = contract_quote(symbol, date.fromisoformat(reading["expiry"]), reading["strike"], reading["side"])
    kind = expiry_kind((date.fromisoformat(reading["expiry"]) - today).days) if reading.get("expiry") else None
    with Session(engine) as db:
        usual = usual_premium(db)
        record = record_like(db, symbol, reading.get("side"), kind)
    return combine(symbol, reading, underlying, contract, usual, record, today, _now())


def simulated_facts(symbol: str, **reading) -> dict:
    """SIMULATED facts for the fixture evidence (demos and tests): a price from the fixture's quotes or a fixed made-up
    one, a contract priced by a rule of thumb, a usual premium and record that are invented. Not market data."""
    from app.ai.copilot_fixture import AT, FixtureEvidence
    from app.engine.chart_math import ET
    today = datetime.now(ET).date()
    underlying = _underlying(FixtureEvidence(), symbol)
    if not underlying.get("last"):
        underlying.update(last=float(50 + sum(map(ord, symbol)) % 400), change_pct=0.6, as_of=AT)
    last = underlying["last"]
    contract = None
    if reading.get("expiry") and reading.get("strike") and reading.get("side"):
        days = max((date.fromisoformat(reading["expiry"]) - today).days, 0.3)
        strike = reading["strike"]
        intrinsic = max(last - strike, 0) if reading["side"] == "call" else max(strike - last, 0)
        mid = round(max(intrinsic + 0.012 * last * math.sqrt(days) * math.exp(-abs(strike / last - 1) * 8), 0.05), 2)
        contract = {"state": "ok", "label": f"{symbol} {reading['expiry'][5:].replace('-', '/')} {strike:g}{reading['side'][0].upper()}",
                    "bid": round(mid * 0.97, 2), "ask": round(mid * 1.03, 2), "mid": mid, "as_of": AT}
    kind = expiry_kind((date.fromisoformat(reading["expiry"]) - today).days) if reading.get("expiry") else None
    record = {"symbol": {"trades": 9, "up": 4, "pnl": -380.0, "small_sample": True}}
    if reading.get("side"):
        record["symbol_side"] = {"trades": 6, "up": 2, "pnl": -510.0, "small_sample": True}
    if kind:
        record["same_expiry_kind"] = {"kind": kind, "side": reading.get("side") or "any", "trades": 14, "up": 4, "pnl": -2140.0}
    return {**combine(symbol, reading, underlying, contract, 310.0, record, today, AT), "simulated": True}


def today() -> date:
    from app.engine.chart_math import ET
    return datetime.now(ET).date()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------- the answer, read back

READING_LINE = re.compile(r"^\**reading\**\s*:\s*(.+)$", re.I)
TILE_LINE = re.compile(r"^(?:[-*]\s+)?\**tile\**\s*:\s*(.+?)\s*\|\s*(.+)$", re.I)
AGAINST_LINE = re.compile(r"^(?:[-*]\s+)?\**against\**\s*:\s*(.+)$", re.I)
CHANGES_LINE = re.compile(r"^(?:[-*]\s+)?\**changes if\**\s*:\s*(.+)$", re.I)
ALSO_LINE = re.compile(r"^(?:[-*]\s+)?\**also\**\s*:\s*(.+)$", re.I)
NOT_A_CALL = re.compile(r"^\W*not a call\b", re.I)
EMPTY = {"", "?", "-", "—", "none", "n/a", "not stated", "unknown"}


def _value(key: str, text: str, today: date):
    text = text.strip().strip("*").strip()
    if text.lower() in EMPTY:
        return None
    if key == "ticker":
        symbol = text.lstrip("$").upper()
        return symbol if SYMBOL.match(symbol) else None
    if key == "side":
        low = text.lower()
        return "call" if low in ("call", "calls", "c") else "put" if low in ("put", "puts", "p") else None
    if key == "expiry":
        if re.fullmatch(r"(?:[o0]\s?dte|today)", text, re.I):
            return today.isoformat()
        with contextlib.suppress(ValueError):
            return date.fromisoformat(text[:10]).isoformat()
        return None
    try:
        number = float(text.replace("$", "").replace(",", ""))
    except ValueError:
        return None
    return number if 0 < number < 1_000_000 else None


def parse(text: str, today: date) -> dict:
    """The check's answer as parts: ``reading`` (every field, None when blank), ``verdict`` (None for any other word),
    ``headline``, ``tiles`` ([label, value]), ``against``, ``changes_if``, ``others`` and ``not_a_call``."""
    from app.ai.copilot_answer import VERDICT_LINE
    out = {"reading": dict.fromkeys(FIELDS), "verdict": None, "headline": None, "tiles": [], "against": None,
           "changes_if": None, "others": [], "not_a_call": False}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if NOT_A_CALL.match(line) and out["headline"] is None:
            out["not_a_call"] = True
        elif hit := READING_LINE.match(line):
            for part in re.split(r"\s*[|·]\s*", hit.group(1)):
                key, _, value = part.strip().partition(" ")
                key = key.lower().rstrip(":")
                if key in FIELDS:
                    out["reading"][key] = _value(key, value.lstrip(":"), today)
        elif hit := VERDICT_LINE.match(line):
            word = hit.group(1).capitalize()
            out["verdict"] = word if word in VERDICTS else None
            out["headline"] = hit.group(2).replace("**", "").strip()[:160]
        elif hit := TILE_LINE.match(line):
            if len(out["tiles"]) < TILES:
                out["tiles"].append([hit.group(1).strip("* ")[:40], hit.group(2).strip("* ")[:60]])
        elif hit := AGAINST_LINE.match(line):
            out["against"] = hit.group(1).strip("* ")[:240]
        elif hit := CHANGES_LINE.match(line):
            out["changes_if"] = hit.group(1).strip("* ")[:200]
        elif hit := ALSO_LINE.match(line):
            out["others"] = [p.strip() for p in hit.group(1).split(";") if p.strip()][:5]
    return out


# --------------------------------------------------------------------------- nothing guessed

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
CALL_MARK = re.compile(r"\d\s?c\b|\bcalls?\b|\bc\b", re.I)
PUT_MARK = re.compile(r"\d\s?p\b|\bputs?\b|\bp\b", re.I)
TODAY_MARK = re.compile(r"\b[o0]\s?dte\b|\btoday\b|\bsame[- ]day\b", re.I)


def _expiry_written(expiry: date, text: str, today: date) -> bool:
    if expiry == today and TODAY_MARK.search(text):
        return True
    for m, d in MONTH_DAY.findall(text):
        if (int(m), int(d)) == (expiry.month, expiry.day):
            return True
    if re.search(rf"\b{MONTHS[expiry.month - 1]}\w*\.?\s*0?{expiry.day}\b", text, re.I):
        return True
    return 0 <= (expiry - today).days <= 7 and expiry.weekday() < 5 and bool(re.search(rf"\b{WEEKDAYS[expiry.weekday()]}", text, re.I))


def confirm(reading: dict, text: str, today: date) -> dict:
    """The model's reading with every value the message's text does not hold left blank: a ticker it does not name, a
    number it does not write, a call or put it does not mark, an expiry it does not state. Only for a text message; a
    screenshot's reading is the model's own."""
    out = dict(reading)
    numbers = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))}
    if out.get("ticker") and not re.search(rf"(?<![A-Za-z0-9]){re.escape(out['ticker'])}(?![A-Za-z0-9])", text, re.I):
        out["ticker"] = None
    for key in ("strike", "entry", "stop", "target"):
        if out.get(key) is not None and not any(abs(out[key] - n) < 1e-9 for n in numbers):
            out[key] = None
    if out.get("side") and not (CALL_MARK if out["side"] == "call" else PUT_MARK).search(text):
        out["side"] = None
    if out.get("expiry") and not _expiry_written(date.fromisoformat(out["expiry"]), text, today):
        out["expiry"] = None
    return out


# --------------------------------------------------------------------------- one check


def question(raw: str, screenshot: bool) -> str:
    said = raw.replace('"""', '"')
    shot = " It came as a screenshot, attached; read the call from the image." if screenshot else ""
    return f'{CHECK_HEAD}{shot} The message, quoted as shared:\n"""\n{said}\n"""'


def quoted(prompt: str) -> str:
    """The shared message inside a check's question (the fake model reads it)."""
    hit = re.search(r'"""\n(.*)\n"""', prompt, re.S)
    return hit.group(1) if hit else ""


class CheckRefused(Exception):
    """The check could not run (the lab off, the budget spent, the model failed); its message is for the owner."""


async def run(raw: str, *, source: str, images: list[dict] | None = None, now: datetime | None = None, db_engine=None) -> dict:
    """One check: the copilot's turn (``check_call`` job, the turn and daily budgets, its ``copilot_turn`` row), the
    reading confirmed against the text, the facts at this moment, and the saved row. Returns ``view``'s dict, or
    ``{"not_a_call": True}`` for a screenshot that holds no call (nothing saved). Raises CheckRefused."""
    from app.ai import copilot, copilot_spend
    from app.engine.chart_math import ET
    raw = (raw or "").strip()[:RAW_MAX]
    cfg = copilot.settings()
    if not cfg.enabled:
        raise CheckRefused("Copilot Lab is off on this server, so there is no check here.")
    if not raw and not images:
        raise CheckRefused("Paste the call's text first.")
    if cfg.backend == "anthropic":
        if await asyncio.to_thread(copilot_spend.spent_today) >= cfg.daily_budget_usd:
            await asyncio.to_thread(copilot_spend.record_refused, kind="check_call", source=source, backend=cfg.backend,
                                    code="daily_budget")
            raise CheckRefused(f"Today's copilot API budget (${cfg.daily_budget_usd:.2f}) is spent.")
    try:
        adapter = await asyncio.to_thread(copilot.adapter_for, cfg)
        evidence = copilot.evidence_for(cfg)
    except copilot.CopilotError as exc:
        raise CheckRefused(exc.message) from None
    now = now or datetime.now(ET)
    today = now.astimezone(ET).date()
    parts, errors, turn_id = [], [], None
    try:
        turn = copilot_spend.recorded_turn([{"role": "user", "content": question(raw, bool(images))}], None, cfg, adapter, evidence,
                                           now, kind="check_call", source=source, images=images)
        async with contextlib.aclosing(turn) as events:
            async for event in events:
                if event.get("type") == "text":
                    parts.append(event.get("delta") or "")
                elif event.get("type") == "error":
                    errors.append(event.get("message") or "")
                elif event.get("type") == "done":
                    turn_id = event.get("turn_id")
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()
    answer = parse("".join(parts), today)
    if answer["not_a_call"] and images:
        return {"not_a_call": True}
    if answer["headline"] is None and not answer["reading"]["ticker"]:
        if errors:
            raise CheckRefused(" ".join(errors))
    reading = answer["reading"] if images else confirm(answer["reading"], raw, today)  # an image is read by the model alone
    quote = None
    if reading["ticker"]:
        try:
            quote = await asyncio.to_thread(evidence.get_call_facts, reading["ticker"],
                                            **{k: reading[k] for k in ("side", "expiry", "strike", "entry", "stop", "target") if reading[k]})
        except Exception:  # noqa: BLE001 - the check stands without its snapshot; the row says it is missing
            log.warning("call check snapshot failed", exc_info=True)
    card = {"headline": answer["headline"], "tiles": answer["tiles"], "against": answer["against"],
            "changes_if": answer["changes_if"], "others": answer["others"], "note": None}
    verdict = answer["verdict"]
    if not reading["ticker"]:
        verdict, card = None, {**card, "headline": NO_TICKER, "tiles": [], "against": None, "changes_if": None,
                               "note": "Nothing was guessed. Send it again with the ticker."}
    elif errors and not answer["headline"]:
        card["note"] = " ".join(errors)[:300]
    if quote and quote.get("simulated"):
        card["note"] = "Simulated: the demo model and fixture prices, not a real check."
    return await asyncio.to_thread(save, raw or SCREENSHOT, source, reading, verdict, card, quote, turn_id, now, db_engine)


def _snapshot(quote: dict | None) -> tuple[float | None, str | None]:
    if not quote:
        return None, None
    kept = {"as_of": quote.get("as_of"), "underlying": quote.get("underlying"), "contract": quote.get("contract"),
            **({"simulated": True} if quote.get("simulated") else {})}
    return (quote.get("underlying") or {}).get("last"), json.dumps(kept, default=str, separators=(",", ":"))


def save(raw: str, source: str, reading: dict, verdict: str | None, card: dict, quote: dict | None, turn_id: str | None,
         now: datetime, db_engine=None) -> dict:
    from sqlmodel import Session
    from app.database import engine
    from app.engine.chart_math import ET
    from app.models import CallCheck
    price, quote_json = _snapshot(quote)
    row = CallCheck(checked_at=now.astimezone(UTC).replace(tzinfo=None), day=now.astimezone(ET).date(), source=source,
                    raw_text=raw[:RAW_MAX], symbol=reading.get("ticker"), reading_json=json.dumps(reading),
                    verdict=verdict, card_json=json.dumps(card), underlying_price=price, quote_json=quote_json,
                    turn_id=turn_id)
    with Session(db_engine or engine) as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        return view(row, planned=False)


def _planned(db, ids: list[str]) -> set[str]:
    from sqlmodel import col, select
    from app.models import TradeCapture
    if not ids:
        return set()
    return set(db.exec(select(TradeCapture.origin_ref).where(TradeCapture.origin_kind == "checked_call",
                                                             col(TradeCapture.origin_ref).in_(ids))).all())


def view(row, planned: bool) -> dict:
    """A check as the desk, Telegram and a later report read it."""
    reading = json.loads(row.reading_json)
    out = {"id": str(row.id), "checked_at": row.checked_at.replace(tzinfo=UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
           "day": row.day.isoformat(), "source": row.source, "raw": row.raw_text, "symbol": row.symbol, "reading": reading,
           "verdict": row.verdict, "card": json.loads(row.card_json), "underlying_price": row.underlying_price,
           "quote": json.loads(row.quote_json) if row.quote_json else None, "outcome": row.outcome,
           "outcome_at": row.outcome_at.replace(tzinfo=UTC).isoformat(timespec="seconds").replace("+00:00", "Z") if row.outcome_at else None,
           "planned": planned}
    out["plan_href"] = plan_href(out)
    return out


def day_checks(db, day: date) -> list[dict]:
    """The day's checked calls, newest first, each with whether a plan was saved from it."""
    from sqlmodel import col, select
    from app.models import CallCheck
    rows = db.exec(select(CallCheck).where(CallCheck.day == day).order_by(col(CallCheck.checked_at).desc())).all()
    planned = _planned(db, [str(r.id) for r in rows])
    return [view(r, str(r.id) in planned) for r in rows]


def get(db, check_id: str) -> dict | None:
    from app.models import CallCheck
    key = _uuid(check_id)
    row = db.get(CallCheck, key) if key else None
    return view(row, str(row.id) in _planned(db, [str(row.id)])) if row else None


def pass_check(db, check_id: str) -> tuple[str, str | None]:
    """Pass on a checked call: recorded once. ``(reply, chosen label)``; the label None when the check is unknown."""
    from app.models import CallCheck
    key = _uuid(check_id)
    row = db.get(CallCheck, key) if key else None
    if row is None:
        return "That checked call is no longer in the journal.", None
    if row.outcome != "passed":
        row.outcome, row.outcome_at = "passed", datetime.now(UTC).replace(tzinfo=None)
        db.add(row)
        db.commit()
    return "Passed. It stays in today's checked calls.", "Passed"


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- how it reads


def _fmt(value) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) and not value.is_integer() else f"{value:g}"


def expiry_words(iso: str | None, day: str | None = None) -> str | None:
    if not iso:
        return None
    when = date.fromisoformat(iso)
    text = f"{when.month}/{when.day}"
    return f"{text} (0DTE)" if day and iso == day else text


def reading_line(check: dict) -> str:
    """"Read: QQQ · 11/11 (0DTE) · strike 660 · put · entry price: not stated · …": blanks named."""
    r = check["reading"]
    parts = [r.get("ticker") or "ticker: not read"]
    parts.append(expiry_words(r.get("expiry"), check.get("day")) or "expiry: not stated")
    parts.append(f"strike {_fmt(r['strike'])}" if r.get("strike") else "strike: not stated")
    parts.append(r.get("side") or "call or put: not stated")
    for key in ("entry", "stop", "target"):
        parts.append(f"{key} {_fmt(r[key])}" if r.get(key) else f"{BLANK_NAMES[key]}: not stated")
    return "Read: " + " · ".join(parts)


def telegram_text(check: dict) -> str:
    """The card as a phone-chat message: the verdict line, what was read with its blanks named, the tiles as short lines,
    Against, Changes if, the other calls; plain text."""
    card = check["card"]
    head = f"Verdict: {check['verdict']} — {card['headline']}" if check.get("verdict") else (card.get("headline") or NO_TICKER)
    lines = [head, reading_line(check)]
    lines += [f"{label}: {value}" for label, value in card.get("tiles") or []]
    if card.get("against"):
        lines.append(f"Against: {card['against']}")
    if card.get("changes_if"):
        lines.append(f"Changes if: {card['changes_if']}")
    if card.get("others"):
        lines.append("Also in the message, not checked: " + "; ".join(card["others"]))
    if card.get("note"):
        lines.append(card["note"])
    return "\n".join(lines)[:1500]


def plan_context(check: dict) -> str:
    """The plan form's context line: "Plan a trade: " and the call's levels as editable text, the poster's, not his."""
    r = check["reading"]
    contract = " ".join(filter(None, [r.get("ticker"), r.get("strike") and _fmt(r["strike"]), r.get("side"),
                                      expiry_words(r.get("expiry"), check.get("day"))]))
    levels = "; ".join(f"posted {key} {_fmt(r[key])}" for key in ("entry", "stop", "target") if r.get(key))
    text = f"Plan a trade: {contract}, from a Discord call I checked" + (f" ({levels})" if levels else "") + \
        ". My own entry trigger, invalidation and time stop:"
    return re.sub(r"\s+", " ", text).strip()[:CONTEXT_MAX]


def plan_href(check: dict) -> str | None:
    """The desk's plan flow for the call's symbol, its levels in the message box as editable text and the check as the
    plan's origin. A plan, never a ticket; None without a ticker."""
    if not check.get("symbol"):
        return None
    return "/copilot-lab?" + urlencode({"symbol": check["symbol"], "context": plan_context(check),
                                        "origin": f"checked_call:{check['id']}"})


# --------------------------------------------------------------------------- the scripted model's reading (demo only)

_NOT_TICKERS = frozenset("""i im i'm think entry entered odte 0dte dte hits hit p c stop target tp sl pt the at for and to in on a
an it is this my of with posted min mins ago exp call calls put puts buy sell long short lotto swing scalp starter size risk
today here we go next week fri friday mon tue wed thu am pm out trim new alert alerts check""".split())
_LOWER_TICKERS = frozenset("spy qqq iwm nvda tsla aapl amd meta msft amzn googl nbis mu orcl pltr avgo smci crwv".split())


def fake_reading(raw: str, today: date) -> dict:
    """The demo model's reading (``copilot.FakeAdapter`` only, labelled simulated): a few patterns, so the desk can be
    shown without the API. The real check is the model's reading; this is never used for one."""
    out = dict.fromkeys(FIELDS)
    words = re.findall(r"\$?[A-Za-z][A-Za-z.]{0,5}", raw)
    out["ticker"] = next((w.lstrip("$").upper() for w in words if (w.startswith("$") or w.isupper() or w.lower() in _LOWER_TICKERS)
                          and w.lstrip("$").lower() not in _NOT_TICKERS and len(w.lstrip("$")) >= 2), None)
    if hit := re.search(r"(\d+(?:\.\d+)?)\s?(c|p|calls?|puts?)\b", raw, re.I):
        out["strike"], out["side"] = float(hit.group(1)), "call" if hit.group(2)[0].lower() == "c" else "put"
    elif hit := re.search(r"\$(\d+(?:\.\d+)?)", raw):
        out["target" if re.search(r"\bhits?\b", raw, re.I) else "strike"] = float(hit.group(1))
    if DTE.search(raw):
        out["expiry"] = today.isoformat()
    elif hit := MONTH_DAY.search(raw):
        month, day = int(hit.group(1)), int(hit.group(2))
        with contextlib.suppress(ValueError):
            when = date(today.year, month, day)
            out["expiry"] = (when if when >= today else date(today.year + 1, month, day)).isoformat()
    for key, pattern in (("entry", r"(?:@|entry:?|in at)\s*\$?(\d+(?:\.\d+)?)"), ("stop", r"\b(?:stop|sl)\s*:?\s*\$?(\d+(?:\.\d+)?)"),
                         ("target", r"\b(?:target|tp|pt)\s*:?\s*\$?(\d+(?:\.\d+)?)")):
        if hit := re.search(pattern, raw, re.I):
            out[key] = float(hit.group(1))
    return out


def tool_input(reading: dict) -> dict:
    return {"symbol": reading["ticker"], **{k: reading[k] for k in ("side", "expiry", "strike", "entry", "stop", "target") if reading.get(k)}}


def fake_answer(reading: dict, facts: dict) -> str:
    """The demo model's card from the (simulated) facts: template text, not reasoning."""
    def field(key: str) -> str:
        value = reading.get(key)
        return "?" if value is None else value if isinstance(value, str) else _fmt(value)
    head = "Reading: " + " | ".join(f"{k} {field(k)}" for k in FIELDS)
    if not reading.get("ticker"):
        return f"{head}\nVerdict: Unclear — {NO_TICKER.lower()}"
    symbol, under = reading["ticker"], facts.get("underlying") or {}
    contract, record = facts.get("contract") or {}, facts.get("record") or {}
    like = record.get("same_expiry_kind") or record.get("symbol_side") or record.get("symbol") or {}
    tiles = [f"Tile: {symbol} now | ${under['last']:,.2f}" if under.get("last") else f"Tile: {symbol} now | no quote"]
    if contract.get("state") == "ok":
        tiles.append(f"Tile: {contract['label']} | {_fmt(contract['bid'])} × {_fmt(contract['ask'])}")
    elif facts.get("to_strike_pct") is not None or (facts.get("target") or {}).get("from_last_pct") is not None:
        move = facts.get("to_strike_pct") if facts.get("to_strike_pct") is not None else facts["target"]["from_last_pct"]
        tiles.append(f"Tile: To the {'strike' if reading.get('strike') else 'target'} | {move:+.1f}%")
    posted = facts.get("vs_posted_entry")
    if posted:
        tiles.append(f"Tile: Since the post | {posted['move_pct']:+.0f}%")
    pnl = like.get("pnl", 0)
    tiles.append(f"Tile: Your record like it | {like.get('trades', 0)} trades, {like.get('up', 0)} up, {'−' if pnl < 0 else '+'}${abs(pnl):,.0f}")
    if contract.get("state") != "ok":
        verdict = "Wait — simulated: no contract or entry to check yet"
        changes = "you name the contract; then cost and break-even can be checked."
    elif posted and posted["past_entry"] and posted["move_pct"] > 10:
        verdict = f"Pass — simulated: already {posted['move_pct']:.0f}% past the posted entry"
        changes = "it comes back to the posted entry."
    elif like.get("trades", 0) >= MIN_RECORD and like.get("pnl", 0) < 0:
        verdict = "Pass — simulated: your record on trades like it is net negative"
        changes = "a level holds that your record has not tested."
    else:
        verdict = "Draft — simulated: at the posted entry, cost within your usual"
        changes = "the underlying loses today's low."
    return "\n".join([head, f"Verdict: {verdict}", *tiles[:TILES], "Against: the demo model reads no news or flows.",
                      f"Changes if: {changes}"])
