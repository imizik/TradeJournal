"""Research workspace store — seed loading, schema-aware merge, get-or-create.

Backs the AI Buildout cockpit (and any future research theme). The workspace is
a single JSON blob per ``slug``; see :class:`app.models.ResearchWorkspace`.

The seed is generated from the original artifact's default data
(``app/data/ai_buildout_seed.json``). On first access a workspace row is created
from that seed. When the shipped seed's ``schema_version`` outranks a saved row,
:func:`deep_merge` folds new defaults (new companies, layers, fields) into the
saved data while preserving every user edit.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import ResearchWorkspace

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# slug -> seed filename. Only known slugs get seeded/created.
_SEEDS: dict[str, str] = {"ai-buildout": "ai_buildout_seed.json"}


@lru_cache(maxsize=None)
def _load_seed_file(filename: str) -> dict[str, Any]:
    with open(_DATA_DIR / filename, encoding="utf-8") as fh:
        return json.load(fh)


def load_seed(slug: str) -> dict[str, Any] | None:
    """Return a fresh copy of the seed for ``slug`` (schema_version + data),
    or None if the slug is unknown."""
    filename = _SEEDS.get(slug)
    if not filename:
        return None
    # Deep-copy via round-trip so callers can mutate without touching the cache.
    return json.loads(json.dumps(_load_seed_file(filename)))


def _array_key(default_list: list) -> str | None:
    """Match the artifact's dmerge: object-arrays keyed by 'ticker' then 'id'."""
    if default_list and isinstance(default_list[0], dict):
        if "ticker" in default_list[0]:
            return "ticker"
        if "id" in default_list[0]:
            return "id"
    return None


def deep_merge(default: Any, saved: Any) -> Any:
    """Merge ``saved`` over ``default`` (saved wins on scalars).

    Ported from the artifact's ``dmerge``:
    - Object-arrays are merged by identity key ('ticker'/'id'): matched items are
      recursively merged, default order is preserved, and saved-only items are
      appended. This is how new default companies/layers appear on schema bumps
      without dropping user-added rows.
    - Scalar arrays are replaced wholesale by ``saved``.
    - Dicts are merged key-by-key.
    """
    if isinstance(default, list):
        if not isinstance(saved, list):
            return default
        key = _array_key(default)
        if key:
            saved_by_key = {
                item[key]: item
                for item in saved
                if isinstance(item, dict) and item.get(key) is not None
            }
            out = [
                deep_merge(item, saved_by_key[item[key]])
                if isinstance(item, dict) and item.get(key) in saved_by_key
                else item
                for item in default
            ]
            default_keys = {
                item[key] for item in default if isinstance(item, dict)
            }
            for item in saved:
                if (
                    isinstance(item, dict)
                    and item.get(key) is not None
                    and item[key] not in default_keys
                ):
                    out.append(item)
            return out
        return saved
    if isinstance(default, dict):
        if not isinstance(saved, dict):
            return default
        out = dict(default)
        for k, sv in saved.items():
            out[k] = deep_merge(default[k], sv) if k in default else sv
        return out
    return default if saved is None else saved


def _reconcile(data: dict[str, Any]) -> dict[str, Any]:
    """Repair structural invariants after a merge. Ensures every layer present
    in ``layers`` also appears in ``order`` (a scalar array that dmerge would
    otherwise replace wholesale, hiding layers added by a newer seed)."""
    layers = data.get("layers")
    order = data.get("order")
    if isinstance(layers, dict) and isinstance(order, list):
        seen = set(order)
        for lid in layers:
            if lid not in seen:
                order.append(lid)
                seen.add(lid)
    return data


def get_or_create_workspace(session: Session, slug: str) -> ResearchWorkspace | None:
    """Return the workspace row for ``slug``, creating it from seed on first
    access and applying schema upgrades in place. Returns None for unknown slugs.
    """
    seed = load_seed(slug)
    if seed is None:
        return None

    seed_version = int(seed.get("schema_version", 1))
    seed_data = {k: v for k, v in seed.items() if k != "schema_version"}

    row = session.exec(
        select(ResearchWorkspace).where(ResearchWorkspace.slug == slug)
    ).first()

    if row is None:
        row = ResearchWorkspace(
            slug=slug,
            schema_version=seed_version,
            data_json=json.dumps(_reconcile(seed_data)),
            revision=0,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    if row.schema_version < seed_version:
        try:
            saved = json.loads(row.data_json)
        except (ValueError, TypeError):
            saved = {}
        merged = _reconcile(deep_merge(seed_data, saved))
        row.schema_version = seed_version
        row.data_json = json.dumps(merged)
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
        session.refresh(row)

    return row


def save_workspace(
    session: Session, row: ResearchWorkspace, data: dict[str, Any]
) -> ResearchWorkspace:
    """Persist new ``data`` for a workspace, bumping the revision."""
    row.data_json = json.dumps(data)
    row.revision += 1
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
