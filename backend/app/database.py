from collections.abc import Generator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

db_path = Path(__file__).parent.parent / "data" / "trade_journal.db"
db_path.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
