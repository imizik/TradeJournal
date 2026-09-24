"""Change only synthetic alerts in Playwright's fixed, disposable database."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import Session, create_engine

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

from app.engine.tradingview import parse_alert_bytes  # noqa: E402
from app.engine.tradingview_alerts import persist_alert  # noqa: E402
from app.models import TradingViewAlert  # noqa: E402

DB = BACKEND / "data" / "e2e_seed.db"
assert DB.is_file(), "Playwright must seed its disposable database first"
ALERT_ID = "v1:1.0.0:SPY:5:1737561600000:e2e_break:long"
status = sys.argv[1]
assert status in {"reset", "pending", "running", "done", "skipped", "error"}
engine = create_engine(f"sqlite:///{DB}")

with Session(engine) as session:
    if status == "reset":
        session.exec(delete(TradingViewAlert).where(TradingViewAlert.alert_id == ALERT_ID))
        session.commit()
    else:
        payload = {
            "v": 1, "indicator_version": "1.0.0", "alert_id": ALERT_ID,
            "symbol": "SPY", "timeframe": "5", "setup": "e2e_break", "side": "long",
            "price": 214.32, "bar_time_ms": 1737561600000,
            "levels": {"or_high": 213.9}, "context": {"above_vwap": True},
        }
        raw_body = json.dumps(payload).encode()
        persist_alert(session, parse_alert_bytes(raw_body), raw_body)
        row = session.get(TradingViewAlert, ALERT_ID)
        assert row is not None
        row.analysis_status = status
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if status == "done":
            row.verdict = "long_scalp"
            row.confidence = "high"
            row.assessment_json = json.dumps({"assessment": {
                "verdict": "long_scalp", "confidence": "high", "bias": "bullish",
                "market_state": "open", "style": "scalp", "setup_score": 82,
                "liquidity_score": 90, "risk_score": 70,
                "reasons_for": ["Price reclaimed the opening range"],
                "reasons_against": [], "missing": [], "trigger": None,
                "invalidation": None, "targets": [],
            }})
        elif status == "skipped":
            row.analysis_error_code = "alpaca_not_configured"
            row.analysis_error = "Alpaca credentials are not configured"
        elif status == "error":
            row.analysis_error_code = "analysis_failed"
            row.analysis_error = "Synthetic scorer failure"
        session.add(row)
        session.commit()
