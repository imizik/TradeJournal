"""Owner-side adapter for the validated Check exchange configuration.

The app uses this adapter, matching jo_briefing_owner, rather than importing
the connector configuration module. MCP never imports owner adapters.
"""
from cloud_mcp_check_common import read_config


def read_binding(path):
    return read_config(path)
