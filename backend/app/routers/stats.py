from fastapi import APIRouter, Query

router = APIRouter()


@router.get("")
def get_stats(account: str | None = Query(None)):
    # Stubbed: return placeholder stats
    return {"realized_pnl": 0, "trade_count": 0}
