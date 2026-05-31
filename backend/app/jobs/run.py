import argparse
import logging
import uuid

from sqlmodel import Session

from app.database import engine
from app.engine.jobs import (
    JOB_ALPACA_ENRICH,
    JOB_POLYGON_ENRICH,
    JOB_TRADE_PATH,
    JOB_WEBULL_LISTENER,
    create_alpaca_enrichment_job,
    create_polygon_enrichment_job,
    create_trade_path_job,
    create_webull_listener_job,
    run_job,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Trade Journal durable jobs.")
    parser.add_argument("--job-id", help="Run an existing job_run row by UUID")
    parser.add_argument(
        "--type",
        choices=[JOB_POLYGON_ENRICH, JOB_ALPACA_ENRICH, JOB_TRADE_PATH, JOB_WEBULL_LISTENER],
        help="Create and run a new job of this type",
    )
    parser.add_argument("--range", default="week", choices=["day", "week", "month", "all"])
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--accounts",
        help="Comma-separated Webull broker_account_id values for --type webull_listener. "
             "If omitted, all local Webull accounts are used.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    if args.job_id:
        job_id = uuid.UUID(args.job_id)
    else:
        if not args.type:
            parser.error("Either --job-id or --type is required")
        with Session(engine) as session:
            if args.type == JOB_POLYGON_ENRICH:
                job = create_polygon_enrichment_job(session, range_value=args.range, force=args.force)
            elif args.type == JOB_ALPACA_ENRICH:
                job = create_alpaca_enrichment_job(session, range_value=args.range, force=args.force)
            elif args.type == JOB_WEBULL_LISTENER:
                from app.engine.webull import resolve_local_webull_accounts
                if args.accounts:
                    accounts = [a.strip() for a in args.accounts.split(",") if a.strip()]
                else:
                    accounts = resolve_local_webull_accounts(session)
                if not accounts:
                    parser.error(
                        "No Webull accounts to subscribe to. Pass --accounts <id[,id,...]> "
                        "or seed an Account row with broker='webull' first."
                    )
                job = create_webull_listener_job(session, accounts=accounts)
            else:
                job = create_trade_path_job(session, range_value=args.range, force=args.force)
            job_id = job.id

    enriched = run_job(job_id)
    print(f"job_id={job_id} enriched={enriched}")


if __name__ == "__main__":
    main()
