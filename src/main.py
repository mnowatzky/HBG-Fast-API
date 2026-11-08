import logging
from enum import StrEnum
from typing import Annotated

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from geojson import FeatureCollection
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func, update
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, col, select

import stats
from config import config
from db import SessionDep, engine
from filters import FiltersDep
from geocode import Address, Nominatim, get_geocoder
from places import known_timezones, timezone_at
from sticker import Sticker, StickerCreate, StickerPublic

logger = logging.getLogger("uvicorn.error")


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
app.include_router(stats.router)


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


@app.get(
    "/stickers",
    response_model=list[StickerPublic],
    responses={
        200: {
            "description": "With format=geojson, a FeatureCollection of points "
            "with the id and the name.",
            "content": {"application/geo+json": {}},
        }
    },
)
def read_stickers(
    session: SessionDep,
    response: Response,
    filters: FiltersDep,
    format: StickerFormat = StickerFormat.json,
    limit: Annotated[int, Query(ge=1, le=5000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Stickers newest first. X-Total-Count holds the count across all pages."""
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


def add_address(
    sticker_id: int, latitude: float, longitude: float, geocoder: Nominatim
) -> None:
    """Looks up the address after the response, so saving does not wait for it."""
    address = geocoder.reverse(latitude, longitude)
    if address == Address():
        return
    with Session(engine) as session:
        session.execute(
            update(Sticker)
            .where(col(Sticker.id) == sticker_id)
            .values(**address.model_dump())
        )
        session.commit()


@app.post(
    "/stickers", status_code=status.HTTP_201_CREATED, response_model=StickerPublic
)
@limiter.limit(config.sticker_create_rate_limit)
def create_sticker(
    request: Request,
    sticker: StickerCreate,
    session: SessionDep,
    geocoder: Annotated[Nominatim, Depends(get_geocoder)],
    background_tasks: BackgroundTasks,
):
    """Saves a sticker. The server adds the date and the time zone, and the address
    right after it answers, so the response has no address yet."""
    zone = timezone_at(sticker.latitude, sticker.longitude, known_timezones(session))
    db_sticker = Sticker.model_validate(sticker, update={"timezone": zone})
    session.add(db_sticker)
    session.commit()
    session.refresh(db_sticker)
    assert db_sticker.id is not None
    background_tasks.add_task(
        add_address, db_sticker.id, sticker.latitude, sticker.longitude, geocoder
    )
    return db_sticker
