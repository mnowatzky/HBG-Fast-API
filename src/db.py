from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, create_engine

from config import config

# Migrations create the schema, see README.md. Dates come back in UTC.
engine = create_engine(
    config.db_url, pool_pre_ping=True, connect_args={"options": "-c timezone=UTC"}
)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
