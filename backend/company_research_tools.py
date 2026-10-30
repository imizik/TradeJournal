"""Opt-in research tools using the existing authenticated Check transport."""
import asyncio
from uuid import UUID
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

import company_research_exchange as exchange
from company_research_common import FindingBody


def register(server, config, authenticated, scopes, clock):
    root, outbox = config.market_watch_snapshots_dir, config.market_watch_outbox_dir

    def metadata(name):
        return {"securitySchemes": [{"type": "oauth2", "scopes": scopes(name)}]}

    @server.tool(meta=metadata("company_research_context"), annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def company_research_context(assignment_id: UUID) -> dict[str, Any]:
        """Read one owner-assigned frozen company question. No positions, journal or account data."""
        actor = (await authenticated("company_research_context")).claims["profile_id"]
        try:
            return await asyncio.to_thread(exchange.context, root, actor, str(assignment_id), clock())
        except (ValueError, OSError, KeyError):
            raise ToolError("Assignment unavailable, expired or not assigned to this actor") from None

    @server.tool(meta=metadata("company_research_submit"), annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    async def company_research_submit(assignment_id: UUID, result: FindingBody) -> dict[str, Any]:
        """Submit sourced research for one assignment; check the receipt before claiming an app save."""
        actor = (await authenticated("company_research_submit")).claims["profile_id"]
        try:
            return await asyncio.to_thread(exchange.submit, root, outbox, actor, str(assignment_id), result.model_dump(mode="json"), clock())
        except (ValueError, OSError, KeyError):
            raise ToolError("Research refused: check assignment, evidence, expiry and operation ID") from None

    @server.tool(meta=metadata("company_research_receipt"), annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def company_research_receipt(operation_id: str) -> dict[str, Any]:
        """Read this authenticated actor's receipt; pending_import is not saved."""
        actor = (await authenticated("company_research_receipt")).claims["profile_id"]
        try:
            return await asyncio.to_thread(exchange.receipt, root, actor, operation_id)
        except (ValueError, OSError, KeyError):
            raise ToolError("Receipt unavailable") from None
