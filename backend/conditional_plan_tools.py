"""Opt-in Check tools for Jo's own saved conditional plans."""

import asyncio
import sqlite3
from typing import Annotated, Any, Literal

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from cloud_mcp_check_ledger import Conflict, NotFound
from conditional_plan_common import status
from conditional_plan_ledger import PlanLedger, export


def register(server, config, ledger, authenticated, scopes, clock):
    plans = PlanLedger(ledger)

    def meta(name):
        return {"securitySchemes": [{"type": "oauth2", "scopes": scopes(name)}]}

    errors = (ValueError, OSError, KeyError, TypeError, sqlite3.Error, NotFound)

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            openWorldHint=False,
            idempotentHint=True,
        ),
        meta=meta("conditional_plan_create"),
    )
    async def conditional_plan_create(
        operation_id: Annotated[str, Field(min_length=1, max_length=160)],
        source_kind: Literal["check", "stock_alert"],
        source_id: str,
        direction: Literal["long", "short"],
        trigger_price: float,
        invalidation_price: float,
        confirm_bars: Annotated[int, Field(ge=1, le=3)],
        expires_at: str,
        rationale: Annotated[str, Field(min_length=1, max_length=1000)],
    ) -> dict[str, Any]:
        """Save an advisory intraday price plan and request deterministic phone follow-through.
        First read a fresh own pre_trade_check or stock_alert. Finish ALL pending S1 shadow
        commits before this call. Long: N consecutive completed 1m closes strictly ABOVE
        trigger; one close strictly BELOW invalidation fails it (short reverses both).
        Only full minutes starting after commitment count. Expiry is exclusive, within
        four hours and today's verified regular close. Selected scanner tickers only.
        Do not translate vague 'higher low/looks stronger' into a claimed monitored condition:
        explicitly explain the numeric rule being saved. A trigger is NOT Go or an order.
        Monitoring continues after triggering until invalidation/expiry/cancellation.
        Exact retry recovers an uncertain save/export. Never change an existing plan's
        conditions silently. Return the plan ID and say pending until status.monitoring
        is true. No model/email wake is needed for these deterministic phone alerts."""
        checked = await authenticated("conditional_plan_create")
        request = dict(
            operation_id=operation_id,
            source_kind=source_kind,
            source_id=source_id,
            direction=direction,
            trigger_price=trigger_price,
            invalidation_price=invalidation_price,
            confirm_bars=confirm_bars,
            expires_at=expires_at,
            rationale=rationale,
        )
        try:
            plan = await asyncio.to_thread(
                plans.create,
                checked.claims["profile_id"],
                request,
                config.market_watch_snapshots_dir,
                clock,
                check_actor=checked.subject,
            )
        except Conflict as exc:
            raise ToolError(str(exc)) from None
        except (ValueError, NotFound) as exc:
            # Our own refusal reasons; no plan was saved. The bounded refusal receipt
            # goes to the app so the owner sees it without relying on Jo's reply.
            if getattr(exc, "refusal", None):
                try:
                    await asyncio.to_thread(export, config.market_watch_outbox_dir, exc.refusal)
                except errors:
                    pass
            raise ToolError(
                f"REFUSED, nothing saved: {exc}. Tell the owner you cannot watch "
                "this and why; do not promise monitoring."
            ) from None
        except errors:
            raise ToolError(
                "REFUSED or uncertain: the plan ledger could not be read. Do not promise "
                "monitoring. Retry identical content only to recover."
            ) from None
        try:
            await asyncio.to_thread(export, config.market_watch_outbox_dir, plan)
            return await asyncio.to_thread(
                status, config.market_watch_snapshots_dir, plan, clock()
            )
        except errors:
            raise ToolError(
                f"Plan {plan['plan_id']} is saved but its hand-off to the app monitor is "
                "uncertain. It is NOT being watched yet. Retry identical content (same "
                "operation_id) to recover; do not create a replacement."
            ) from None

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, openWorldHint=False
        ),
        meta=meta("conditional_plan_status"),
    )
    async def conditional_plan_status(plan_id: str) -> dict[str, Any]:
        """Read your own plan, exact conditions, immutable transitions, heartbeat and push receipts.
        monitoring=false means do not claim active coverage. An accepted push is not proof
        of phone display. unavailable means monitoring failed, not price invalidation.
        No provider call, trade/account read, or shadow-decision change."""
        checked = await authenticated("conditional_plan_status")
        try:
            plan = await asyncio.to_thread(
                plans.get, checked.claims["profile_id"], plan_id
            )
            return await asyncio.to_thread(
                status, config.market_watch_snapshots_dir, plan, clock()
            )
        except errors:
            raise ToolError(
                "Conditional plan/status unavailable for this actor"
            ) from None

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, openWorldHint=False
        ),
        meta=meta("conditional_plan_list"),
    )
    async def conditional_plan_list() -> dict[str, Any]:
        """List your latest 50 plans with their current monitoring and delivery state.
        Use this to recover plan IDs and report what you are waiting for, without
        creating replacement plans or polling providers. Older plans remain readable by ID."""
        checked = await authenticated("conditional_plan_list")
        try:

            def read():
                return {
                    "plans": [
                        status(config.market_watch_snapshots_dir, p, clock())
                        for p in plans.list(checked.claims["profile_id"])
                    ],
                    "limit": 50,
                }

            return await asyncio.to_thread(read)
        except errors:
            raise ToolError("Conditional plan list unavailable") from None

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            openWorldHint=False,
            idempotentHint=True,
        ),
        meta=meta("conditional_plan_cancel"),
    )
    async def conditional_plan_cancel(plan_id: str) -> dict[str, Any]:
        """Request cancellation of your own plan; repeat safely after an uncertain result.
        The next monitor pass acknowledges cancelled. A send already in flight cannot
        be recalled. Do not claim cancellation completed until status says cancelled.
        This stops advisory monitoring only; it never closes a position or order."""
        checked = await authenticated("conditional_plan_cancel")
        try:
            record = await asyncio.to_thread(
                plans.cancel, checked.claims["profile_id"], plan_id, clock
            )
            await asyncio.to_thread(export, config.market_watch_outbox_dir, record)
            return {"cancel_requested": True, "receipt": record}
        except errors:
            raise ToolError(
                "Cancellation unavailable or export uncertain; retry the same plan ID"
            ) from None
