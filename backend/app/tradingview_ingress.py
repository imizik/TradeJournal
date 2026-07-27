"""Minimal public application for TradingView webhook delivery.

Run this app on its own port and expose only that port through a tunnel or
restricted deployment. It deliberately imports neither ``app.main`` nor the
private alert-read router, and it has no docs, OpenAPI, CORS, journal routes,
or background market-data worker. ``/health`` is a readiness check: it fails
closed when authentication or the isolated database schema is unavailable.
"""

import logging
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.models import TradingViewAlert
from app.routers import tradingview_webhook
from app.tradingview_database import get_tradingview_session_factory


log = logging.getLogger(__name__)


def create_tradingview_ingress_app() -> FastAPI:
    ingress = FastAPI(
        title="Trade Journal TradingView Ingress",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )

    @ingress.get("/health", include_in_schema=False)
    async def health(
        session_factory: Callable[[], Session] = Depends(
            get_tradingview_session_factory
        ),
    ) -> dict[str, str]:
        token = tradingview_webhook._configured_webhook_token()
        if len(token.encode("utf-8")) < (
            tradingview_webhook.MIN_WEBHOOK_TOKEN_BYTES
        ):
            raise HTTPException(
                status_code=503,
                detail="TradingView ingress is not ready",
            )
        try:
            with session_factory() as session:
                session.exec(
                    # LIMIT 0 validates the full mapped schema without
                    # returning immutable evidence over the DB connection.
                    select(TradingViewAlert).limit(0)
                ).first()
        except SQLAlchemyError as exc:
            log.error(
                "TradingView readiness database check failed "
                "(error_type=%s)",
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="TradingView ingress is not ready",
            ) from exc
        return {"status": "ready"}

    ingress.include_router(
        tradingview_webhook.router,
        prefix="/tradingview",
        tags=["tradingview-webhook"],
    )
    return ingress


app = create_tradingview_ingress_app()
