from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import URL
from sqlmodel import Session, SQLModel, create_engine, select

from config import Config
from sticker import Sticker

db_url = URL.create(
    Config.sticker_db_type,
    username=Config.sticker_db_user,
    password=Config.sticker_db_password,
    host=Config.sticker_db_host,
    port=Config.sticker_db_port,
    database=Config.sticker_db_name,
)
engine = create_engine(db_url, echo=True)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/stickers")
def read_stickers_geojson(session: SessionDep, format: str | None = None) -> JSONResponse:
    stickers = session.scalars(select(Sticker).order_by(Sticker.date.asc())).all()
    if format == "geojson":
        return {"type": "geojson", "data": {"type": "FeatureCollection", "features": [sticker.to_geojson() for sticker in stickers]}}
    else:
        return stickers

@app.post("/stickers")
def create_item(sticker: Sticker, session: SessionDep):
    session.add(sticker)
    session.commit()
    session.refresh(sticker)
    return sticker


@app.put("/items/{item_id}")
def update_item(item_id: int, sticker: Sticker):
    return {"item_name": sticker.name, "item_id": item_id}
