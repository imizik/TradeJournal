"""Shared scanner universe, isolated from the Charts workspace's default row."""

import hashlib
import json

from sqlmodel import Session

from app.engine import scanner_rules as rules
from app.models import ChartSettingsRecord

SETTINGS_KEY = "scanner-universe"
MAX_SYMBOLS = 12


def read_settings(db: Session) -> dict:
    row = db.get(ChartSettingsRecord, SETTINGS_KEY)
    return {
        "symbols": json.loads(row.data_json)["symbols"] if row else list(rules.UNIVERSE),
        "revision": row.revision if row else 0,
        "max_symbols": MAX_SYMBOLS,
    }


def identity(symbols: list[str]) -> tuple[str, str]:
    # Preserve the original baseline identity when its universe is unchanged.
    if set(symbols) == set(rules.UNIVERSE):
        return rules.VERSION, rules.PARAMS_HASH
    version = "s1-v2"
    params = {**rules.PARAMS, "version": version, "universe": sorted(symbols)}
    digest = hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return version, digest
