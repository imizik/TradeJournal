from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.models import Account

router = APIRouter()


@router.get("", response_model=list[Account])
async def get_accounts(session: Session = Depends(get_session)):
    return session.exec(select(Account)).all()
