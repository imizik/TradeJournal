"""Pure, fixture-only examples of selection, quotes, exit ordering and accounting.

These are executable specification examples, not a real-data event processor.
In particular the test caller supplies complete, ordered observation batches and
explicit decision times. No service can import or activate this test package.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from .signal import ET, Session, Signal, aware, positive

D = Decimal
SECOND = timedelta(seconds=1)


@dataclass(frozen=True)
class Print:
    symbol: str
    source: datetime
    received: datetime
    price: D
    size: D = D(1)
    sequence: int | None = 1
    conditions_known: bool = True
    regular: bool = True
    cancelled: bool = False
    correction: bool = False
    feed: str = "fixture_consolidated_raw"

    def status(self, session, symbol):
        if self.symbol != symbol:
            return "irrelevant"
        if not self.conditions_known or self.feed != session.stock_feed:
            return "data_contract"
        if not self.regular or self.cancelled or self.correction:
            return "irrelevant"
        if (not positive(self.price) or not positive(self.size) or not aware(self.source)
                or not aware(self.received) or not session.opened <= self.source < session.closed
                or self.source > self.received):
            return "data_contract"
        return "stale" if self.received - self.source > 2 * SECOND else "valid"


def reference(prints, session, symbol, at):
    available = [p for p in prints if p.symbol == symbol and p.received <= at]
    if not available:
        return None
    # Irrelevant/cancelled prints do not displace an eligible last sale. Unknown
    # interpretation or stale eligible prints cannot silently become a fallback.
    relevant = [p for p in available if p.status(session, symbol) != "irrelevant"]
    if not relevant:
        return None
    latest_time = max(p.received for p in relevant)
    tied = [p for p in relevant if p.received == latest_time]
    if len(tied) > 1:
        seqs = [p.sequence for p in tied]
        if None in seqs or len(set(seqs)) != len(seqs):
            return None
        tied.sort(key=lambda p: p.sequence)
    p = tied[-1]
    return p if p.status(session, symbol) == "valid" and at - p.source <= 2 * SECOND else None


@dataclass(frozen=True)
class Contract:
    occ: str
    symbol: str
    expiry: date
    side: int
    strike: D
    root: str = "SPY"
    currency: str = "USD"
    multiplier: int | None = 100
    deliverable: str | None = "100 SPY"
    adjusted: bool = False

    def standard(self):
        return (self.root == self.symbol and self.currency == "USD" and self.multiplier == 100
                and self.deliverable == f"100 {self.symbol}" and not self.adjusted)

    def identity(self):
        return (self.side in (1, -1) and positive(self.strike)
                and self.strike * 1000 == int(self.strike * 1000)
                and self.occ == f"{self.symbol}{self.expiry:%y%m%d}{'C' if self.side == 1 else 'P'}{int(self.strike * 1000):08d}")


@dataclass(frozen=True)
class Chain:
    received: datetime
    contracts: tuple
    complete: bool = True


def select(signal, session, chains, prints, through):
    """Return (status, locked contract, intent time), pending until the deadline."""
    snapshots = sorted((c for c in chains if c.complete and signal.at < c.received <= min(through, signal.at + 10 * SECOND)),
                       key=lambda c: c.received)
    if not snapshots:
        return ("no_chain" if through >= signal.at + 10 * SECOND else "pending", None, None)
    chain = snapshots[0]
    if sum(c.received == chain.received for c in snapshots) != 1:
        return "ambiguous_chain", None, None
    ref = reference(prints, session, signal.symbol, chain.received)
    if ref is None:
        return "no_underlying_reference", None, None
    eligible = [c for c in chain.contracts if c.symbol == signal.symbol and c.side == signal.side
                and 2 <= (c.expiry - signal.at.astimezone(ET).date()).days <= 5 and not c.adjusted]
    # Conflicting identity fields cannot be trusted to locate a contract. For
    # otherwise consistent identities, metadata on a farther strike cannot
    # displace a confirmed nearer contract.
    if any(not c.identity() for c in eligible):
        return "contract_data_error", None, None
    if not eligible:
        return "no_expiry", None, None
    expiry = min(c.expiry for c in eligible)
    itm = [c for c in eligible if c.expiry == expiry and signal.side * (ref.price - c.strike) > 0]
    if not itm:
        return "no_itm", None, None
    strike = max(c.strike for c in itm) if signal.side == 1 else min(c.strike for c in itm)
    chosen = [c for c in itm if c.strike == strike]
    if len(chosen) != 1 or not chosen[0].standard():
        return "contract_data_error", None, None
    return "selected", chosen[0], chain.received


@dataclass(frozen=True)
class Quote:
    occ: str
    received: datetime
    bid_at: datetime
    ask_at: datetime
    bid: D
    ask: D
    bid_size: int = 1
    ask_size: int = 1
    feed: str = "fixture_consolidated_nbbo"

    @property
    def spread(self):
        return self.ask - self.bid

    def valid(self, contract, intent, session):
        return (self.occ == contract.occ and self.feed == session.option_feed
                and all(aware(t) for t in (self.received, self.bid_at, self.ask_at))
                and intent + 2 * SECOND <= self.received <= intent + 10 * SECOND
                and all(intent + 2 * SECOND <= t <= self.received and self.received - t <= 2 * SECOND
                        for t in (self.bid_at, self.ask_at))
                and positive(self.bid) and positive(self.ask) and self.ask >= self.bid
                and self.bid_size >= 1 and self.ask_size >= 1)


def first_quote(quotes, contract, intent, session, through):
    candidates = sorted((q for q in quotes if q.received <= through and q.valid(contract, intent, session)),
                        key=lambda q: q.received)
    if not candidates:
        return None
    # Without a quote sequence, conflicting simultaneous snapshots are ambiguous.
    first = candidates[0]
    if any(q != first and q.received == first.received for q in candidates[1:]):
        raise ValueError("ambiguous_quote_order")
    return first


@dataclass(frozen=True)
class Position:
    signal: Signal
    contract: Contract
    entry: Quote
    underlying: D

    @property
    def target(self):
        return self.underlying + D("1.5") * (self.underlying - self.signal.stop)

    @property
    def debit(self):
        return self.entry.ask * 100 + 1


def enter(signal, contract, intent, session, quotes, prints, through, healthy=True, ordering_known=True):
    if not session.eligible() or not healthy or not ordering_known:
        return "unfilled_health_or_order", None
    try:
        quote = first_quote(quotes, contract, intent, session, through)
    except ValueError:
        return "unfilled_quote_order", None
    end = quote.received if quote else min(through, intent + 10 * SECOND)
    seen = [p for p in prints if signal.at <= p.received <= end]
    for p in seen:
        status = p.status(session, signal.symbol)
        if status in ("stale", "data_contract"):
            return "unfilled_reference", None
        if status == "valid" and signal.side * (p.price - signal.stop) <= 0:
            return "stop_before_entry", None
    if quote is None:
        return ("unfilled_quote" if through >= intent + 10 * SECOND else "pending"), None
    if quote.spread > D("0.05") or quote.spread / ((quote.ask + quote.bid) / 2) > D("0.02"):
        return "spread_rejected", None
    if quote.received >= session.at(11, 0):
        return "unfilled_window", None
    ref = reference(prints, session, signal.symbol, quote.received)
    if ref is None or signal.side * (ref.price - signal.stop) <= 0:
        return "unfilled_reference", None
    return "entered", Position(signal, contract, quote, ref.price)


@dataclass
class ExitExample:
    position: Position
    session: Session
    intent: datetime | None = None
    reason: str | None = None
    unresolved: bool = False
    unresolved_reason: str | None = None
    last_received: datetime | None = None
    primary_exit: Quote | None = None

    def fail(self, reason):
        self.unresolved = True
        self.unresolved_reason = reason
        if self.intent is None:
            self.reason = reason

    def health(self, *, healthy, heartbeat_gap_seconds, halted=False):
        if self.primary_exit is not None:
            return
        if not healthy or heartbeat_gap_seconds > 5 or halted:
            self.fail("unresolved_health")

    def batch(self, at, prints=()):
        """One complete receipt-time batch; empty batches exercise the timer."""
        if self.intent is not None or self.unresolved:
            return
        p = self.position
        if (at < p.entry.received or self.last_received is not None and at <= self.last_received
                or any(t.received != at for t in prints)):
            self.fail("unresolved_event_order")
            return
        self.last_received = at
        due = min(p.entry.received + timedelta(minutes=15), self.session.at(11, 15))
        if at > due:
            # Fixture caller must deliver the timer; a missed timer is not
            # reconstructed from a later price or assigned an earlier fill.
            self.fail("unresolved_missing_timer")
            return
        crosses = []
        for trade in prints:
            status = trade.status(self.session, p.signal.symbol)
            if status in ("stale", "data_contract"):
                self.fail("unresolved_reference")
                return
            if status != "valid" or trade.source < p.entry.received:
                continue
            if p.signal.side * (trade.price - p.signal.stop) <= 0:
                crosses.append((trade.sequence, "stop"))
            elif p.signal.side * (trade.price - p.target) >= 0:
                crosses.append((trade.sequence, "target"))
        reasons = {reason for _, reason in crosses}
        if len(reasons) > 1:
            seq = [n for n, _ in crosses]
            if None in seq or len(set(seq)) != len(seq):
                self.fail("unresolved_event_order")
                return
            crosses.sort()
        reason = crosses[0][1] if crosses else ("time" if at == due else None)
        if reason:
            self.intent, self.reason = at, reason

    def liquidate(self, quotes, through):
        if self.primary_exit is not None:
            return "resolved", self.primary_exit
        if self.unresolved:
            return "unresolved", None
        if self.intent is None:
            return "open", None
        try:
            quote = first_quote(quotes, self.position.contract, self.intent, self.session, through)
        except ValueError:
            self.fail("unresolved_exit")
            return "unresolved", None
        if quote is not None:
            self.primary_exit = quote
            return "resolved", quote  # Deliberately no entry spread cap here.
        if through >= self.intent + 10 * SECOND:
            self.fail("unresolved_exit")
            return "unresolved", None
        return "pending", None


def accounting(position, exit_quote):
    a, b = position.entry.ask, exit_quote.bid
    stressed_a = a + position.entry.spread
    stressed_b = max(D(0), b - exit_quote.spread)
    net = 100 * (b - a) - 2
    stress = 100 * (stressed_b - stressed_a) - 2
    return {"net": net, "return_on_premium": net / (100 * a), "debit": position.debit,
            "stress_net": stress, "stress_return": stress / (100 * stressed_a)}


def unresolved_accounting(positions):
    return {"count": len(positions), "entry_debit_at_risk": sum((p.debit for p in positions), D(0)),
            "full_loss_sensitivity": -sum((100 * p.entry.ask + 2 for p in positions), D(0))}


@dataclass
class PortfolioExample:
    session: Session
    used: set = field(default_factory=set)
    state: str = "flat"
    reserved: str | None = None
    entries: int = 0
    dispositions: list = field(default_factory=list)

    def admit(self, signals):
        if len({s.symbol for s in signals}) != len(signals) or len({s.at for s in signals}) > 1:
            raise ValueError("one complete simultaneous batch required")
        accepted = None
        for signal in sorted(signals, key=lambda s: s.symbol != "SPY"):
            if signal.symbol not in ("SPY", "QQQ") or signal.side not in (1, -1):
                raise ValueError("invalid signal")
            if signal.symbol in self.used:
                reason = "already_used"
            else:
                self.used.add(signal.symbol)
                if not self.session.eligible() or not self.session.at(9, 45) <= signal.at < self.session.at(11, 0):
                    reason = "ineligible_session"
                elif accepted:
                    reason = "skipped_simultaneous"
                elif self.state != "flat" or self.entries >= 2:
                    reason = "skipped_busy"
                else:
                    accepted, self.reserved, self.state = signal, signal.symbol, "reserved"
                    reason = "reserved"
            self.dispositions.append((signal.symbol, reason))
        return accepted

    def entry_result(self, status):
        if self.state != "reserved":
            raise ValueError("no reservation")
        if status == "pending":
            return
        if status == "entered":
            self.state = "open"
            self.entries += 1
        elif status in {"no_chain", "ambiguous_chain", "no_underlying_reference", "no_expiry", "no_itm", "contract_data_error",
                       "unfilled_health_or_order", "unfilled_quote_order", "unfilled_reference", "stop_before_entry",
                       "unfilled_quote", "spread_rejected", "unfilled_window"}:
            self.state, self.reserved = "flat", None
        else:
            raise ValueError("unknown entry disposition")

    def exit_result(self, status):
        if self.state != "open":
            raise ValueError("no open position")
        if status == "resolved":
            self.state, self.reserved = "flat", None
        elif status == "unresolved":
            self.state = "unresolved"

    def next_session(self, session):
        if session.opened <= self.session.opened:
            raise ValueError("next exchange session required")
        self.session, self.used, self.entries = session, set(), 0
        # Never silently clear unresolved/pending/open exposure on a date reset.
        if self.state != "flat":
            self.state = "unresolved"
