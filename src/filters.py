"""The filters that GET /stickers and every statistic share, and the SQL they need."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import ColumnElement, Date, String, any_, cast, extract, func, or_
from sqlalchemy.dialects.postgresql import ARRAY

from sticker import MAX_NAME_LENGTH, PEOPLE_SEPARATOR, Sticker

# Local clock hours that count as night: from 22:00 to 05:59.
NIGHT_STARTS, NIGHT_ENDS = 22, 6


class TimeOfDay(StrEnum):
    day = "day"
    night = "night"


def people(name=Sticker.name) -> ColumnElement:
    """The people on a sticker as an array, like split_people() in sticker.py."""
    parts = func.regexp_split_to_array(
        func.btrim(name), PEOPLE_SEPARATOR, type_=ARRAY(String)
    )
    return func.array_remove(parts, "", type_=ARRAY(String))


def has_person(name: str) -> ColumnElement[bool]:
    """Whether one of the people on the sticker is `name`, case-insensitively."""
    return func.lower(name.strip()) == any_(people(func.lower(Sticker.name)))


def local_time_of(sticker=Sticker) -> ColumnElement:
    """The time on the clocks where the sticker was placed."""
    return func.timezone(sticker.timezone, sticker.date)


local_time = local_time_of()

# The date on the clocks where the sticker was placed.
local_day = cast(local_time, Date)


def is_night(local: ColumnElement) -> ColumnElement[bool]:
    hour = extract("hour", local)
    return or_(hour >= NIGHT_STARTS, hour < NIGHT_ENDS)


def as_utc(moment: datetime) -> datetime:
    """Times without an offset are taken as UTC."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def sticker_filters(
    name: Annotated[
        str | None,
        Query(
            max_length=MAX_NAME_LENGTH,
            description="One person, case-insensitively. Timo finds Lisa & Timo.",
        ),
    ] = None,
    country: Annotated[
        str | None,
        Query(pattern="^[A-Za-z]{2}$", description="ISO 3166-1 alpha-2, like DE."),
    ] = None,
    city: Annotated[
        str | None, Query(max_length=255, description="Case-insensitively.")
    ] = None,
    since: Annotated[
        datetime | None,
        Query(description="Placed at or after. In UTC without an offset."),
    ] = None,
    until: Annotated[
        datetime | None, Query(description="Placed before. In UTC without an offset.")
    ] = None,
    since_day: Annotated[
        date | None,
        Query(description="Placed on or after this day, local where the sticker is."),
    ] = None,
    until_day: Annotated[
        date | None,
        Query(description="Placed before this day, local where the sticker is."),
    ] = None,
    time_of_day: Annotated[
        TimeOfDay | None,
        Query(description="In local time where the sticker is. Night is 22 to 6."),
    ] = None,
) -> list[ColumnElement[bool]]:
    filters = []
    if name:
        filters.append(has_person(name))
    if country:
        filters.append(Sticker.country_code == country.upper())
    if city:
        filters.append(func.lower(Sticker.city) == city.strip().lower())
    if since:
        filters.append(Sticker.date >= as_utc(since))
    if until:
        filters.append(Sticker.date < as_utc(until))
    if since_day:
        filters.append(local_day >= since_day)
    if until_day:
        filters.append(local_day < until_day)
    if time_of_day:
        night = is_night(local_time)
        filters.append(night if time_of_day == TimeOfDay.night else ~night)
    return filters


FiltersDep = Annotated[list[ColumnElement[bool]], Depends(sticker_filters)]
