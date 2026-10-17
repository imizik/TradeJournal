"""Network-free forecast tool handlers; caller identity is supplied by the MCP adapter."""
from datetime import datetime, timezone
import fcntl
from pathlib import Path

import advisor_forecast as core


class ForecastExchange:
    def __init__(self, snapshots, receipts, spec, *, enabled=False, clock=None):
        self.snapshots, self.receipts = Path(snapshots), Path(receipts)
        self.spec, self.enabled = spec, enabled
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def context(self, ticker):
        if not self.enabled or ticker not in self.spec["tickers"]:
            raise ValueError("study disabled or ticker unavailable")
        now = core.stamp(self.clock())
        day = now.date().isoformat()
        packet = core.read_json(self.snapshots / day / f"{ticker}.json")
        manifest = core.read_json(self.snapshots / day / "manifest.json")
        if set(manifest) != set(self.spec["tickers"]) or manifest[ticker] != core.digest(packet):
            raise ValueError("complete snapshot manifest required")
        if (packet["spec_hash"] != core.digest(self.spec) or packet["session"] != day
                or packet["ticker"] != ticker or core.stamp(packet["captured_at"]) > now):
            raise ValueError("snapshot provenance mismatch")
        return day, now, packet

    def get_forecast_snapshot(self, ticker):
        day, now, packet = self.context(ticker)
        if now > core.at(day, self.spec["snapshot"]["submission_deadline"]):
            raise ValueError("snapshot deadline passed")
        first_read = self.receipts / day / f"{ticker}-read.json"
        try:
            core.exclusive_json(first_read, {"at": now.isoformat(), "snapshot_hash": core.digest(packet)})
        except FileExistsError:
            pass
        return {"snapshot_hash": core.digest(packet), "snapshot": packet}

    def get_forecast_receipt(self, ticker, snapshot_hash):
        day, _, packet = self.context(ticker)
        if core.digest(packet) != snapshot_hash:
            raise ValueError("snapshot hash mismatch")
        path = self.receipts / day / f"{ticker}.json"
        return core.read_json(path) if path.exists() else None

    def save_forecast(self, ticker, snapshot_hash, forecast):
        day, _, packet = self.context(ticker)
        if snapshot_hash != core.digest(packet):
            raise ValueError("snapshot hash mismatch")
        first_read = core.read_json(self.receipts / day / f"{ticker}-read.json")
        if first_read["snapshot_hash"] != snapshot_hash:
            raise ValueError("read provenance mismatch")
        core.validate_prediction(forecast, packet)
        folder = self.receipts / day
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / f"{ticker}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = folder / f"{ticker}.json"
            if path.exists():
                original = core.read_json(path)
                if original["snapshot_hash"] != snapshot_hash or original["prediction"] != forecast:
                    raise ValueError("immutable forecast conflict")
                return original
            submission = {"snapshot_hash": snapshot_hash, "prediction": forecast}
            raw_path = folder / f"{ticker}-submission.json"
            if raw_path.exists():
                if core.read_json(raw_path) != submission:
                    raise ValueError("immutable submission conflict")
            else:
                core.exclusive_json(raw_path, submission)
            # Content has been fsynced before the authoritative server save time.
            saved = self.clock()
            result = core.receipt(packet, forecast, first_read["at"], saved, self.spec)
            core.exclusive_json(path, result)
            return result
