"""Copilot Lab replay: a recorded Radar session read as if the clock were frozen (docs/copilot-lab.md).

Local-only. Reads a read-only copy of a Radar store at ``COPILOT_REPLAY_AT``
(New York time inside a recorded session). Nothing after that moment may reach
the model: Radar passes are cut at the frozen time by the existing comparison
code, quotes come from the last recorded pass at or before it, news is
filtered by publish time, and today's peer moves are refused.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.ai.copilot_tools import (compact_comparison, compact_events, compact_news, group_mismatch, investigation_changes,
                                  saved_research)
from app.engine.chart_math import ET
from app.engine.radar_comparison import compare_group, empty_comparison, iso
from app.engine.radar_store import RadarStore, load_universe


class ReplayUnavailable(ValueError):
    pass


def parse_at(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ReplayUnavailable("COPILOT_REPLAY_AT must look like 2026-10-23T11:12 (New York time).") from exc
    return moment.replace(tzinfo=ET) if moment.tzinfo is None else moment.astimezone(ET)


class ReplayEvidence:
    label = "replay"

    def __init__(self, store_path: str, at: datetime):
        path = Path(store_path)
        if not path.is_file():
            raise ReplayUnavailable("COPILOT_REPLAY_STORE is not a readable Radar snapshot file.")
        self.store = RadarStore(path, read_only=True)
        self.at, self.now, self.session = at, at.timestamp(), at.date().isoformat()
        self.passes = self.store.comparison_passes(self.session, iso(self.now), current_session=True)
        if not self.passes:
            raise ReplayUnavailable(f"The snapshot has no recorded passes on {self.session} at or before {at:%H:%M} ET.")

    def describe(self) -> dict:
        return {"at": self.at.isoformat(timespec="minutes"), "session": self.session,
                "passes_before": len(self.passes), "last_pass_at": self.passes[0]["started_at"]}

    def get_group_comparison(self, symbol: str, group: str | None = None) -> dict:
        universe = load_universe()
        if (mismatch := group_mismatch(symbol, group, universe)) is not None:
            return mismatch
        result = empty_comparison(symbol, group, universe, self.now)
        if result["group"] is None:
            return compact_comparison(result)
        # live=True: the frozen moment is "now" inside its own session, so no earlier session is carried.
        return compact_comparison(compare_group(self.store, result, today=self.session, now=self.now, live=True))

    def get_quotes(self, symbols: list[str]) -> dict:
        latest = self.passes[0]
        rows = self.store.pass_quotes([latest["id"]])[latest["id"]]
        return {"fetched_at": latest["started_at"], "state": "ok", "source_note": "last recorded Radar pass at or before the replay time",
                "prices": {s: rows[s]["last"] if s in rows else None for s in symbols},
                "not_recorded": [s for s in symbols if s not in rows]}

    def get_peer_moves(self, symbol: str) -> dict:
        return {"symbol": symbol, "state": "unavailable",
                "reason": "Peer moves read today's quotes, so they are off in replay. Use get_group_comparison for recorded peer returns."}

    def get_symbol_news(self, symbol: str, limit: int = 6) -> dict:
        from app.engine import symbol_info_news_feed
        raw = symbol_info_news_feed.symbol_news.view(symbol)
        kept = [a for a in raw.get("articles", []) if _epoch(a.get("published_at")) <= self.now]
        out = compact_news({**raw, "articles": kept}, limit)
        out.update(as_of=self.at.isoformat(timespec="minutes"), filtered_out_after_replay=len(raw.get("articles", [])) - len(kept))
        return out

    def get_investigation_changes(self, investigation_id: str) -> dict:
        return investigation_changes(investigation_id, before=self.at)  # nothing that happened after the frozen moment

    def get_saved_research(self, symbol: str, limit: int = 3) -> dict:
        return saved_research(symbol, limit, before=self.at)  # nothing saved after the frozen moment

    def get_symbol_events(self, symbol: str) -> dict:
        from app.engine import symbol_info_tradier
        out = compact_events(symbol_info_tradier.symbol_events.events(symbol, self.at.date()))
        out["recent_reports"] = [r for r in out["recent_reports"] if str(r.get("date", "")) < self.session]
        out["fetched_at"] = self.at.isoformat(timespec="minutes")  # the real fetch time would show today's date
        return out


def _epoch(value) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("inf")  # an unreadable time is treated as after the cutoff
