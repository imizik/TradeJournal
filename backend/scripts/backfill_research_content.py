"""Backfill AI-drafted research content into the AI Buildout workspace.

Reads the content files in app/data/ (ai_buildout_content_*.json) and merges
them into the live workspace with strict only-if-empty semantics:

- company text fields fill only when currently blank
- company scores apply only when all seven are still 0
- layer fields fill only when blank
- moat clusters are added only if the cluster id doesn't exist yet
- deep dives are added only for tickers without one

Everything written is marked with aiDraft=True so AI-drafted rows are
distinguishable from human edits later. Re-runnable and safe: your edits win.

Usage:
    cd backend && .venv/bin/python scripts/backfill_research_content.py [--seed]

    --seed  also merge the content into app/data/ai_buildout_seed.json and bump
            its schema_version, so fresh databases seed with the content baked in.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session

from app.database import engine
from app.engine.research import get_or_create_workspace, save_workspace

SLUG = "ai-buildout"
DATA_DIR = Path(__file__).resolve().parent.parent / "app" / "data"
CONTENT_FILES = sorted(DATA_DIR.glob("ai_buildout_content_*.json"))
SEED_FILE = DATA_DIR / "ai_buildout_seed.json"

COMPANY_TEXT_FIELDS = ["thesis", "bear", "buy", "sell"]
SCORE_FIELDS = ["q", "ai", "up", "bsRisk", "valRisk", "ccRisk", "cxRisk"]
LAYER_FIELDS = ["what", "whyMoney", "whyFail", "bottleneck", "metrics", "redFlags"]


def load_content() -> dict:
    merged: dict = {"companies": {}, "layers": {}, "moat": {}, "deepDives": {}}
    for f in CONTENT_FILES:
        blob = json.loads(f.read_text())
        for key in merged:
            merged[key].update(blob.get(key, {}))
    return merged


def is_blank(v) -> bool:
    return not (v or "").strip() if isinstance(v, (str, type(None))) else False


def apply_content(data: dict, content: dict) -> dict:
    """Mutates and returns data; counts what changed."""
    stats = {"company_fields": 0, "company_scores": 0, "layer_fields": 0,
             "moat_clusters": 0, "deep_dives": 0}

    for ticker, patch in content["companies"].items():
        c = data.get("companies", {}).get(ticker)
        if not c:
            continue
        touched = False
        for f in COMPANY_TEXT_FIELDS:
            if f in patch and is_blank(c.get(f)):
                c[f] = patch[f]
                stats["company_fields"] += 1
                touched = True
        if all(not c.get(f) for f in SCORE_FIELDS) and any(f in patch for f in SCORE_FIELDS):
            for f in SCORE_FIELDS:
                if f in patch:
                    c[f] = patch[f]
            stats["company_scores"] += 1
            touched = True
        if touched:
            c["aiDraft"] = True

    for layer_id, patch in content["layers"].items():
        l = data.get("layers", {}).get(layer_id)
        if not l:
            continue
        touched = False
        for f in LAYER_FIELDS:
            if f in patch and is_blank(l.get(f)):
                l[f] = patch[f]
                stats["layer_fields"] += 1
                touched = True
        if touched:
            l["aiDraft"] = True

    moat = data.setdefault("moat", {})
    for cluster_id, cluster in content["moat"].items():
        if cluster_id not in moat:
            moat[cluster_id] = {**cluster, "aiDraft": True}
            stats["moat_clusters"] += 1

    dives = data.setdefault("deepDives", {})
    for ticker, dive in content["deepDives"].items():
        existing = dives.get(ticker)
        if existing and any((v or "").strip() for v in existing.values() if isinstance(v, str)):
            continue
        dives[ticker] = {**dive, "aiDraft": True}
        stats["deep_dives"] += 1

    return stats


def main() -> None:
    content = load_content()
    print(f"Loaded content: {len(content['companies'])} companies, "
          f"{len(content['layers'])} layers, {len(content['moat'])} moat clusters, "
          f"{len(content['deepDives'])} deep dives "
          f"from {len(CONTENT_FILES)} file(s)")

    with Session(engine) as session:
        row = get_or_create_workspace(session, SLUG)
        if row is None:
            raise SystemExit("workspace not found")
        data = json.loads(row.data_json)
        stats = apply_content(data, content)
        save_workspace(session, row, data)
        print(f"Live workspace updated (revision -> {row.revision}): {stats}")

    if "--seed" in sys.argv:
        seed = json.loads(SEED_FILE.read_text())
        seed_stats = apply_content(seed, content)
        seed["schema_version"] = int(seed.get("schema_version", 1)) + 1
        SEED_FILE.write_text(json.dumps(seed, indent=2) + "\n")
        print(f"Seed updated (schema_version -> {seed['schema_version']}): {seed_stats}")


if __name__ == "__main__":
    main()
