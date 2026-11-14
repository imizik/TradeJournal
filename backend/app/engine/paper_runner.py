"""The owner's paper book's minute (``paper_book.minute_pass``, docs/copilot-lab.md § Paper): working limit orders,
stop and target touches and automatic exits, once a minute in the regular session, in the API process.

Each pass runs a little after the minute turns, so the minute that just ended is a completed bar (``LATENESS``). It
reads nothing when there is nothing to watch; otherwise one minute-bar read per watched stock through the chart feed's
cached, budgeted ``today_minutes`` (the desk chart's own request) and one batched quote read for the working orders
and triggered exits. Outside the regular session it only ends day orders at the close.

Each paper event worth telling (a limit filled, an automatic exit, a stop or target touched with automatic exits off)
is one Telegram ping marked PAPER, through ``notification_policy.decide`` (kind ``paper``, its own small daily budget,
so it never spends Radar's or the position alerts'; a ticker he does not follow stays silent) and ``phone.send``. Never
an order anywhere; never Robinhood.
"""
from __future__ import annotations

import asyncio
import logging
import time

from sqlmodel import Session

from app.engine import paper_book

log = logging.getLogger(__name__)

PASS_OFFSET = 35  # seconds into each minute: the minute before is complete and past its lateness


def _minutes(symbol: str, now: float) -> list[dict]:
    from app.engine.chart_feed import chart_feed
    return chart_feed.today_minutes(symbol, now)


class PaperRunner:
    def __init__(self, engine, *, clock=time.time, minutes=_minutes, send=None):
        self.engine, self.clock, self.minutes, self._send = engine, clock, minutes, send
        self.last_error: str | None = None

    def run_once(self) -> list[dict]:
        now = self.clock()
        with Session(self.engine) as db:
            told = paper_book.minute_pass(db, now, self.minutes)
            for item in told:
                self.ping(db, item, now)
        return told

    def ping(self, db: Session, item: dict, now: float) -> None:
        """One PAPER ping for a paper event, judged by the notification policy; never twice for one event."""
        from app.engine import notification_policy, phone
        if self._send is None and not phone.configured():
            return
        try:
            ticket = notification_policy.decide(db, sender="paper", source_id=item["source"], kind="paper", title=item["title"],
                                                body=item["body"], now=now, symbol=item["symbol"])
            if ticket.held:
                return
            path = phone.desk_link("/copilot-lab", symbol=item["symbol"])
            if self._send is not None:
                self._send(item["title"], item["body"] + ticket.append, path=path)
            else:
                phone.send(item["title"], item["body"] + ticket.append, kind="paper", path=path)
            notification_policy.delivered(db, ticket, now)
            db.commit()
        except Exception:  # noqa: BLE001 -- recorded once, never retried: a failed push may still have arrived
            log.exception("paper ping failed")
            db.rollback()

    async def loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.run_once)
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception:
                self.last_error = "Paper runner pass failed"
                log.exception("Paper runner pass failed")
            now = time.time()
            await asyncio.sleep(60 - (now - PASS_OFFSET) % 60)
