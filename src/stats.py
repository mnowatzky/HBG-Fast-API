"""Statistics computed in the database, all but /latest with the filters of /stickers."""

import datetime as dt
from enum import StrEnum
from typing import Annotated, NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy import (
    ColumnElement,
    Integer,
    Select,
    Subquery,
    case,
    cast,
    distinct,
    extract,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import distinct_on
from sqlmodel import Session, SQLModel, col

from db import SessionDep
from filters import FiltersDep, is_night, local_day, local_time, local_time_of, people
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


# The place in Norderstedt that "home" means, and how near to it counts as home.
HOME = Place(53.67549805330424, 9.980945457552263)
HOME_RADIUS_KM = 25.0

Latitude = Annotated[float, Query(ge=-90, le=90)]
Longitude = Annotated[float, Query(ge=-180, le=180)]


def place_query(latitude: Latitude, longitude: Longitude) -> Place:
    return Place(latitude, longitude)


def optional_place_query(
    latitude: Latitude | None = None, longitude: Longitude | None = None
) -> Place | None:
    if latitude is None and longitude is None:
        return None
    if latitude is None or longitude is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Give both latitude and longitude, or neither.",
        )
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
    day = "day"


# Times of day are in local time where the sticker is.
CHRONOLOGICAL = {CountBy.month, CountBy.weekday, CountBy.hour, CountBy.day}


class Count(SQLModel):
    key: str
    label: str
    count: int


class StickerDistance(StickerPublic):
    distance_km: float


class PersonStats(SQLModel):
    key: str
    label: str
    stickers: int
    countries: int
    cities: int
    night: int
    # On Saturdays and Sundays
    weekend: int
    # From each of the person's stickers to their next one
    travelled_km: float
    first: AwareDatetime
    last: AwareDatetime
    # Only when asked with a place to measure from
    farthest: StickerDistance | None = None


class Pair(SQLModel):
    keys: list[str]
    labels: list[str]
    count: int


class RecordDay(SQLModel):
    day: dt.date
    count: int


class Streak(SQLModel):
    start: dt.date
    end: dt.date
    days: int


class HomeShare(SQLModel):
    latitude: float
    longitude: float
    radius_km: float
    within: int
    total: int


class Records(SQLModel):
    record_day: RecordDay | None
    longest_streak: Streak | None
    north: StickerPublic | None
    south: StickerPublic | None
    east: StickerPublic | None
    west: StickerPublic | None
    home_share: HomeShare


class Latest(SQLModel):
    stickers: list[StickerPublic]
    distance_km: float | None


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


def with_distance(sticker: Sticker, km: float) -> StickerDistance:
    return StickerDistance(**sticker.model_dump(), distance_km=round(km, 1))


def people_rows(filters: list[ColumnElement[bool]], alias: str = "people") -> Subquery:
    """One row for each person on each sticker, with the sticker's columns.

    `key` is the name in lower case, which tells people apart. Someone on a sticker
    twice, as in "Ana & ana", is there once.
    """
    names = (
        select(
            Sticker.id,
            Sticker.latitude,
            Sticker.longitude,
            Sticker.date,
            Sticker.timezone,
            Sticker.city,
            Sticker.country_code,
            func.unnest(people()).label("name"),
        )
        .where(*filters)
        .subquery()
    )
    key = func.lower(names.c.name)
    return (
        select(names, key.label("key"))
        .ext(distinct_on(names.c.id, key))
        .order_by(names.c.id, key, names.c.name)
        .subquery(alias)
    )


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
    people_count = session.scalar(select(func.count(distinct(names.c.key))))
    return Summary(
        stickers=stickers, people=people_count, cities=cities, countries=countries
    )


def grouping(by: CountBy, filters: list[ColumnElement[bool]]) -> Select:
    """The filtered stickers as a key to count by and a label to show for it."""
    if by == CountBy.person:
        names = people_rows(filters)
        return select(names.c.key, names.c.name.label("label"))
    key, label = {
        CountBy.country: (Sticker.country_code, Sticker.country),
        CountBy.city: (Sticker.city, Sticker.city),
        # Sortable text: "2024-03", "1" for Monday to "7" for Sunday, "00" to "23",
        # and "2024-03-31".
        CountBy.month: (func.to_char(local_time, "YYYY-MM"),) * 2,
        CountBy.weekday: (func.to_char(local_time, "ID"),) * 2,
        CountBy.hour: (func.to_char(local_time, "HH24"),) * 2,
        CountBy.day: (func.to_char(local_time, "YYYY-MM-DD"),) * 2,
    }[by]
    return select(key.label("key"), label.label("label")).where(*filters)


@router.get("/counts", response_model=list[Count])
def read_counts(
    session: SessionDep,
    filters: FiltersDep,
    by: CountBy,
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
):
    """Stickers per person, country, city, month, weekday, hour of the day or day.

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
    return [with_distance(sticker, km) for sticker, km in rows]


def legs(filters: list[ColumnElement[bool]]) -> Subquery:
    """The rows of people_rows(), each with the person's sticker before it."""
    rows = people_rows(filters)
    own_order = {"partition_by": rows.c.key, "order_by": (rows.c.date, rows.c.id)}
    return select(
        rows,
        func.lag(rows.c.latitude).over(**own_order).label("previous_latitude"),
        func.lag(rows.c.longitude).over(**own_order).label("previous_longitude"),
    ).subquery("legs")


@router.get("/people", response_model=list[PersonStats])
def read_people(
    session: SessionDep,
    filters: FiltersDep,
    place: Annotated[Place | None, Depends(optional_place_query)],
):
    """What each person stickered, the most stickers first.

    A sticker of several people counts for each of them. With a latitude and a
    longitude, each person also gets their sticker farthest from that place.
    """
    rows = legs(filters)
    local = local_time_of(rows.c)
    leg = great_circle_km(
        Place(rows.c.previous_latitude, rows.c.previous_longitude), place_of(rows.c)
    )
    stickers = func.count()
    result = session.execute(
        select(
            rows.c.key,
            func.mode().within_group(rows.c.name).label("label"),
            stickers.label("stickers"),
            func.count(distinct(func.nullif(rows.c.country_code, ""))).label(
                "countries"
            ),
            func.count(distinct(func.nullif(rows.c.city, ""))).label("cities"),
            func.count().filter(is_night(local)).label("night"),
            func.count().filter(extract("isodow", local) >= 6).label("weekend"),
            func.coalesce(func.sum(leg), 0).label("travelled_km"),
            func.min(rows.c.date).label("first"),
            func.max(rows.c.date).label("last"),
        )
        .group_by(rows.c.key)
        .order_by(stickers.desc(), rows.c.key)
    )
    people_stats = [
        PersonStats(**{**row._mapping, "travelled_km": round(row.travelled_km, 1)})
        for row in result
    ]
    if place is not None:
        farthest = farthest_of_each(session, rows, place)
        for person in people_stats:
            person.farthest = farthest[person.key]
    return people_stats


def farthest_of_each(
    session: Session, rows: Subquery, place: Place
) -> dict[str, StickerDistance]:
    """Each person's sticker farthest from the place, by their key."""
    distance = great_circle_km(place, place_of(rows.c))
    farthest = session.execute(
        select(rows.c.key, rows.c.id, distance)
        .ext(distinct_on(rows.c.key))
        .order_by(rows.c.key, distance.desc(), rows.c.id.desc())
    ).all()
    ids = [sticker_id for _, sticker_id, _ in farthest]
    stickers = {
        sticker.id: sticker
        for sticker in session.scalars(select(Sticker).where(col(Sticker.id).in_(ids)))
    }
    return {key: with_distance(stickers[id_], km) for key, id_, km in farthest}


@router.get("/pairs", response_model=list[Pair])
def read_pairs(
    session: SessionDep,
    filters: FiltersDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """The two people who share the most stickers, and the next ones."""
    first, second = people_rows(filters, "first"), people_rows(filters, "second")
    count = func.count().label("count")
    rows = session.execute(
        select(
            first.c.key,
            second.c.key,
            func.mode().within_group(first.c.name),
            func.mode().within_group(second.c.name),
            count,
        )
        .join_from(
            first, second, (first.c.id == second.c.id) & (first.c.key < second.c.key)
        )
        .group_by(first.c.key, second.c.key)
        .order_by(count.desc(), first.c.key, second.c.key)
        .limit(limit)
    )
    return [
        Pair(keys=[key1, key2], labels=[label1, label2], count=n)
        for key1, key2, label1, label2, n in rows
    ]


@router.get("/records", response_model=Records)
def read_records(session: SessionDep, filters: FiltersDep):
    """The busiest day, the longest streak, the ends of the world and home.

    That is the day with the most stickers, the most days in a row with stickers,
    the stickers farthest north, south, east and west, and how many are near home.
    Days are local where the sticker is. Of equal records, the earliest counts.
    """

    def extreme(order: ColumnElement) -> StickerPublic | None:
        sticker = session.scalars(
            select(Sticker).where(*filters).order_by(order, col(Sticker.id)).limit(1)
        ).first()
        return StickerPublic.model_validate(sticker) if sticker else None

    within, total = session.execute(
        select(
            func.count().filter(distance_km(HOME) <= HOME_RADIUS_KM),
            func.count(),
        ).where(*filters)
    ).one()
    return Records(
        record_day=record_day(session, filters),
        longest_streak=longest_streak(session, filters),
        north=extreme(col(Sticker.latitude).desc()),
        south=extreme(col(Sticker.latitude)),
        east=extreme(col(Sticker.longitude).desc()),
        west=extreme(col(Sticker.longitude)),
        home_share=HomeShare(
            latitude=HOME.latitude,
            longitude=HOME.longitude,
            radius_km=HOME_RADIUS_KM,
            within=within,
            total=total,
        ),
    )


def record_day(
    session: Session, filters: list[ColumnElement[bool]]
) -> RecordDay | None:
    count = func.count()
    row = session.execute(
        select(local_day, count)
        .where(*filters)
        .group_by(local_day)
        .order_by(count.desc(), local_day)
        .limit(1)
    ).first()
    return RecordDay(day=row[0], count=row[1]) if row else None


def longest_streak(
    session: Session, filters: list[ColumnElement[bool]]
) -> Streak | None:
    days = select(local_day.label("day")).where(*filters).distinct().subquery()
    # Days in a row, less their position among all days, give the same date.
    position = cast(func.row_number().over(order_by=days.c.day), Integer)
    streaks = select(days.c.day, (days.c.day - position).label("streak")).subquery()
    start, end, length = (
        func.min(streaks.c.day),
        func.max(streaks.c.day),
        func.count(),
    )
    row = session.execute(
        select(start, end, length)
        .group_by(streaks.c.streak)
        .order_by(length.desc(), start)
        .limit(1)
    ).first()
    return Streak(start=row[0], end=row[1], days=row[2]) if row else None


@router.get("/latest", response_model=Latest)
def read_latest(session: SessionDep):
    """The two newest stickers, newest first, and the distance between them.

    Takes no filters. With fewer than two stickers, the distance is null.
    """
    stickers = session.scalars(
        select(Sticker)
        .order_by(col(Sticker.date).desc(), col(Sticker.id).desc())
        .limit(2)
    ).all()
    distance = None
    if len(stickers) == 2:
        newest, before = stickers
        km = session.scalar(select(great_circle_km(place_of(newest), place_of(before))))
        distance = round(km, 1)
    return Latest(
        stickers=[StickerPublic.model_validate(s) for s in stickers],
        distance_km=distance,
    )
