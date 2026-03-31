import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account, Fill

router = APIRouter()


class FillCreate(BaseModel):
    ticker: str
    side: str           # "buy_to_open" | "sell_to_close" | "buy_to_close" | "sell_to_open"
    contracts: int
    price: float
    executed_at: datetime
    option_type: str    # "call" | "put"
    strike: float
    expiration: date
    raw_email_id: str = ""


@router.get("", response_model=list[Fill])
async def get_fills(session: Session = Depends(get_session)):
    return session.exec(select(Fill).order_by(Fill.executed_at.desc())).all()


@router.post("", response_model=Fill)
async def create_fill(body: FillCreate, session: Session = Depends(get_session)):
    account = session.exec(select(Account)).first()
    if not account:
        raise HTTPException(status_code=400, detail="No account found — server not seeded")

    fill = Fill(
        id=uuid.uuid4(),
        account_id=account.id,
        **body.model_dump(),
    )
    session.add(fill)
    session.commit()
    session.refresh(fill)
    return fill


@router.post("/import")
async def import_fills():
    # IMAP polling wired in a later step (email_parser + APScheduler)
    return {"status": "not_implemented"}
