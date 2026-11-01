import logging
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from geojson import FeatureCollection
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import String, any_, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, col, create_engine, select

from config import config
from sticker import Sticker, StickerCreate

logger = logging.getLogger("uvicorn.error")

# Migrations create the schema, see README.md.
engine = create_engine(config.db_url, pool_pre_ping=True)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


class StickerFormat(StrEnum):
    json = "json"
    geojson = "geojson"


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="HBG Sticker API", root_path=config.sticker_root_path)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.sticker_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Total-Count"],
)


@app.exception_handler(OperationalError)
def handle_database_outage(request: Request, error: OperationalError) -> JSONResponse:
    logger.error("Database unavailable: %s", error.orig)
    return JSONResponse(
        {"detail": "Database unavailable"},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.get("/health")
def read_health(session: SessionDep):
    session.scalar(select(1))
    return {"status": "ok"}


@app.get("/stickers", response_model=list[Sticker])
def read_stickers(
    session: SessionDep,
    response: Response,
    format: StickerFormat = StickerFormat.json,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    name: Annotated[str | None, Query(max_length=75)] = None,
):
    """Stickers newest first. X-Total-Count holds the count across all pages."""
    filters = []
    if name:
        # Matches one person in a shared name like "Lisa & Collin".
        names = func.regexp_split_to_array(
            func.lower(func.trim(Sticker.name)), r"\s*&\s*", type_=ARRAY(String)
        )
        filters.append(func.lower(name.strip()) == any_(names))

    total = session.scalar(select(func.count()).select_from(Sticker).where(*filters))
    stmt = (
        select(Sticker)
        .where(*filters)
        .order_by(col(Sticker.date).desc(), col(Sticker.id).desc())
        .limit(limit)
        .offset(offset)
    )
    stickers = session.scalars(stmt).all()
    response.headers["X-Total-Count"] = str(total)
    if format == StickerFormat.geojson:
        collection = FeatureCollection(
            features=[sticker.to_geojson() for sticker in stickers]
        )
        return JSONResponse(
            content=collection,
            headers=response.headers,
            media_type="application/geo+json",
        )
    return stickers


@app.post("/stickers", status_code=status.HTTP_201_CREATED, response_model=Sticker)
@limiter.limit(config.sticker_create_rate_limit)
def create_sticker(request: Request, sticker: StickerCreate, session: SessionDep):
    db_sticker = Sticker.model_validate(sticker)
    session.add(db_sticker)
    session.commit()
    session.refresh(db_sticker)
    return db_sticker
