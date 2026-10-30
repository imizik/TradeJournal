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
