"""
One-off script to enrich all existing fills with underlying price, greeks,
and technical indicators via Polygon.

Run from backend/:
    python scripts/backfill_greeks.py [--force]

--force: re-enrich fills that already have underlying_price_at_fill set.
         Default: only enrich fills where underlying_price_at_fill is NULL.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, create_engine, select

from app.models import Fill
from app.engine.enricher import enrich_fills

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "trade_journal.db"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-enrich already-enriched fills")
    args = parser.parse_args()

    engine = create_engine(f"sqlite:///{DB_PATH}")

    with Session(engine) as session:
        query = select(Fill)
        if not args.force:
            query = query.where(Fill.underlying_price_at_fill == None)  # noqa: E711

        fills = session.exec(query).all()
        log.info("Found %d fills to enrich", len(fills))

        if not fills:
            log.info("Nothing to do.")
            return

        enriched = enrich_fills(list(fills), session)
        log.info("Done. Enriched %d fills.", enriched)


if __name__ == "__main__":
    main()
