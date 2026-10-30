"""Explicitly configured connector publication; no grants are inferred."""
import os


def configuration():
    path = os.getenv("COMPANY_RESEARCH_CHECK_CONFIG", "")
    if not path:
        return None
    from cloud_mcp_check_common import read_config
    config = read_config(path)
    return config if config.company_research_enabled else None


def researchers():
    config = configuration()
    if config is None:
        return []
    return [{"id": p.id, "label": "Dots / Jo" if i == 0 else "Duet"}
            for i, p in enumerate(config.profiles) if p.enabled]


def revoke_company(db, identifier):
    """Remove published handoff copies when the owner archives a company."""
    from pathlib import Path
    from sqlmodel import select
    from app.company_research_models import ResearchAssignment
    from company_research_exchange import context_name
    config = configuration()
    if config is None:
        return
    for row in db.exec(select(ResearchAssignment).where(ResearchAssignment.company_id == identifier,
                                                      ResearchAssignment.actor != "manual")).all():
        (Path(config.market_watch_snapshots_dir) / context_name(row.actor, row.id)).unlink(missing_ok=True)
