"""Read-only ingress preflight, run before stopping a healthy release.

Only this short-lived helper reads both private and ingress configuration.
It never prints credentials and connects only as the restricted ingress role.
"""

import json
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from database import drop_to_service_account, target

RELEASE = Path(__file__).resolve().parents[1]
CONFIG = Path("/etc/tradejournal")
KEYS = {"TRADINGVIEW_INGRESS_ENABLED", "TRADINGVIEW_DATABASE_URL", "TRADINGVIEW_WEBHOOK_TOKEN"}


def validate_settings(settings: dict, private: dict) -> bool:
    enabled = (settings.get("TRADINGVIEW_INGRESS_ENABLED") or "false").lower()
    if enabled not in {"true", "false"}:
        raise ValueError("TRADINGVIEW_INGRESS_ENABLED must be true or false")
    if enabled == "false":
        return False
    if settings.keys() - KEYS:
        raise ValueError("Ingress configuration contains unexpected settings; use tradingview.env.example")
    if len((settings.get("TRADINGVIEW_WEBHOOK_TOKEN") or "").strip().encode("utf-8")) < 32:
        raise ValueError("Ingress token must contain at least 32 bytes")
    try:
        url = make_url(settings.get("TRADINGVIEW_DATABASE_URL") or "")
        app_url = make_url(private.get("DATABASE_URL") or "")
        valid = (
            url.drivername == "postgresql+psycopg"
            and bool(url.host and url.database and url.username and url.password)
            and target(url) == target(app_url)
            and url.username != app_url.username
        )
    except Exception:
        valid = False
    if not valid:
        raise ValueError("Ingress needs a separate PostgreSQL role on the application's database endpoint")
    if (private.get("TRADINGVIEW_ANALYSIS_AUTOSTART") or "").lower() != "true":
        raise ValueError("Enable TRADINGVIEW_ANALYSIS_AUTOSTART in backend.env before enabling ingress")
    if not all((private.get(name) or "").strip() for name in ("ALPACA_API_KEY", "ALPACA_API_SECRET")):
        raise ValueError("Configure the private Alpaca credentials before enabling ingress analysis")
    return True


def verify_database(url: str) -> None:
    # Reuse the exhaustive effective-privilege check used by setup_roles.
    # This is deployment preflight, never part of the public app's imports.
    sys.path.insert(0, str(RELEASE / "backend"))
    sys.path.insert(0, str(RELEASE / "backend/scripts"))
    from setup_roles import privilege_sweep
    from app.models import TradingViewAlert
    from sqlalchemy import select

    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            role = connection.execute(text("SELECT current_user")).scalar_one()
            unsafe = connection.execute(text("""
                SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls
                       OR has_schema_privilege(current_user, 'public', 'CREATE')
                       OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member = pg_roles.oid)
                  FROM pg_roles WHERE rolname = current_user
            """)).scalar_one()
            if unsafe or privilege_sweep(connection, role, is_ingress=True):
                raise ValueError("Ingress role is not restricted to tradingview_alert; verify database roles")
            connection.execute(select(TradingViewAlert).limit(0))
    finally:
        engine.dispose()


def main() -> None:
    path = CONFIG / "tradingview.env"
    if not path.is_file():
        print(json.dumps({"enabled": False}))
        return
    for config in (path, CONFIG / "backend.env"):
        info = config.stat()
        if info.st_uid != 0 or info.st_mode & 0o077:
            raise SystemExit("Deployment environment files must be root-owned and mode 0600")
    settings = dotenv_values(path, interpolate=False)
    private = dotenv_values(CONFIG / "backend.env", interpolate=False)
    try:
        enabled = validate_settings(settings, private)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if enabled:
        url = settings["TRADINGVIEW_DATABASE_URL"]
        # Do not inherit private/libpq/Python settings into the DB check.
        os.environ.clear()
        os.environ.update(PATH="/usr/bin:/bin", LANG="C.UTF-8", PYTHONDONTWRITEBYTECODE="1")
        drop_to_service_account("tradejournal-ingress")
        try:
            verify_database(url)
        except Exception:
            raise SystemExit("Ingress database/schema/role check failed; verify the restricted role and target") from None
    print(json.dumps({"enabled": enabled}))


if __name__ == "__main__":
    main()
