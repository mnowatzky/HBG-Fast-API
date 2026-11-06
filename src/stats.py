"""Statistics, computed in the database. Each takes the filters of GET /stickers."""

from enum import StrEnum
from typing import Annotated, NamedTuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, Select, Subquery, case, distinct, func, select
from sqlmodel import SQLModel, col

from db import SessionDep
from filters import FiltersDep, local_time, people
from sticker import Sticker, StickerPublic

router = APIRouter(prefix="/stats", tags=["stats"])

# The mean radius of the Earth. A sphere with it is at most 0.5 % off the
# ellipsoid of WGS84, which GPS uses.
EARTH_RADIUS_KM = 6371.0088

# A number, or a column for one in SQL
Coordinate = float | ColumnElement[float]


class Place(NamedTuple):
    latitude: Coordinate
    longitude: Coordinate


def place_of(sticker=Sticker) -> Place:
    return Place(sticker.latitude, sticker.longitude)


Latitude = Annotated[float, Query(ge=-90, le=90)]
Longitude = Annotated[float, Query(ge=-180, le=180)]


def place_query(latitude: Latitude, longitude: Longitude) -> Place:
    return Place(latitude, longitude)


class Summary(SQLModel):
    stickers: int
    people: int
    cities: int
    countries: int


class CountBy(StrEnum):
    person = "person"
    country = "country"
    city = "city"
    month = "month"
    weekday = "weekday"
    hour = "hour"


# Times of day are in local time where the sticker is.
CHRONOLOGICAL = {CountBy.month, CountBy.weekday, CountBy.hour}


class Count(SQLModel):
    key: str
    label: str
    count: int


class StickerDistance(StickerPublic):
    distance_km: float


@router.get("/summary", response_model=Summary)
def read_summary(session: SessionDep, filters: FiltersDep):
    """How many stickers, and how many people, cities and countries they cover."""
    stickers, cities, countries = session.execute(
        select(
            func.count(),
            func.count(distinct(func.nullif(Sticker.city, ""))),
            func.count(distinct(func.nullif(Sticker.country_code, ""))),
        ).where(*filters)
    ).one()
    names = people_rows(filters)
    people_count = session.scalar(
        select(func.count(distinct(func.lower(names.c.name))))
    )
    return Summary(
        stickers=stickers, people=people_count, cities=cities, countries=countries
    )


def people_rows(filters: list[ColumnElement[bool]]) -> Subquery:
    """One row with the name of each person on each of the stickers."""
    return select(func.unnest(people()).label("name")).where(*filters).subquery()


def grouping(by: CountBy, filters: list[ColumnElement[bool]]) -> Select:
    """The filtered stickers as a key to count by and a label to show for it."""
    if by == CountBy.person:
        names = people_rows(filters)
        return select(
            func.lower(names.c.name).label("key"), names.c.name.label("label")
        )
    key, label = {
        CountBy.country: (Sticker.country_code, Sticker.country),
        CountBy.city: (Sticker.city, Sticker.city),
        # Sortable text: "2024-03", "1" for Monday to "7" for Sunday, "00" to "23".
        CountBy.month: (func.to_char(local_time, "YYYY-MM"),) * 2,
        CountBy.weekday: (func.to_char(local_time, "ID"),) * 2,
        CountBy.hour: (func.to_char(local_time, "HH24"),) * 2,
    }[by]
    return select(key.label("key"), label.label("label")).where(*filters)


@router.get("/counts", response_model=list[Count])
def read_counts(
    session: SessionDep,
    filters: FiltersDep,
    by: CountBy,
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
):
    """Stickers per person, country, city, month, weekday or hour of the day.

    People, countries and cities come most first, times in their order. A label is
    the most common spelling of its key, like "Deutschland" for "DE".
    """
    source = grouping(by, filters).subquery()
    count = func.count().label("count")
    order = [source.c.key] if by in CHRONOLOGICAL else [count.desc(), source.c.key]
    rows = session.execute(
        select(
            source.c.key,
            func.mode().within_group(source.c.label).label("label"),
            count,
        )
        .where(source.c.key != "")
        .group_by(source.c.key)
        .order_by(*order)
        .limit(limit)
    )
    return [Count(key=key, label=label, count=n) for key, label, n in rows]


def great_circle_km(start: Place, end: Place) -> ColumnElement[float]:
    """The distance between two places on the globe, by haversine.

    Every distance in the statistics comes from here.
    """
    half_lat = func.radians(end.latitude - start.latitude) / 2
    half_lon = func.radians(end.longitude - start.longitude) / 2
    a = func.power(func.sin(half_lat), 2) + func.cos(
        func.radians(start.latitude)
    ) * func.cos(func.radians(end.latitude)) * func.power(func.sin(half_lon), 2)
    # Rounding can push it past 1 near the antipode. Not LEAST(1, …): it skips NULL,
    # which would make a missing place half the globe away.
    root = func.sqrt(a)
    return 2 * EARTH_RADIUS_KM * func.asin(case((root > 1, 1), else_=root))


def distance_km(place: Place) -> ColumnElement[float]:
    """The distance of each sticker from the place."""
    return great_circle_km(place, place_of())


@router.get("/farthest", response_model=list[StickerDistance])
def read_farthest(
    session: SessionDep,
    filters: FiltersDep,
    place: Annotated[Place, Depends(place_query)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """The stickers farthest from a place, farthest first."""
    distance = distance_km(place).label("distance")
    rows = session.execute(
        select(Sticker, distance)
        .where(*filters)
        .order_by(distance.desc(), col(Sticker.id).desc())
        .limit(limit)
    )
    return [
        StickerDistance(**sticker.model_dump(), distance_km=round(km, 1))
        for sticker, km in rows
    ]
