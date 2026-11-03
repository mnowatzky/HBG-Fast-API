import re
from datetime import UTC, datetime
from typing import Annotated

from geojson import Feature, Point
from pydantic import AwareDatetime, StringConstraints, computed_field
from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel

MAX_NAME_LENGTH = 75

# "Lisa & Timo" is one sticker of two people. The SQL in filters.py splits alike.
PEOPLE_SEPARATOR = r"\s*&\s*"


def split_people(name: str) -> list[str]:
    return [person for person in re.split(PEOPLE_SEPARATOR, name.strip()) if person]


def utc_now() -> datetime:
    return datetime.now(UTC)


class StickerBase(SQLModel):
    latitude: float = Field(index=True)
    longitude: float = Field(index=True)
    name: str = Field(index=True)
    # When the sticker was placed, in UTC.
    date: AwareDatetime = Field(
        default_factory=utc_now, index=True, sa_type=DateTime(timezone=True)
    )
    # The address in German. Empty when reverse geocoding finds nothing, e.g. at sea.
    city: str = Field(default="", index=True)
    state: str = Field(default="", index=True)
    country: str = Field(default="", index=True)
    # ISO 3166-1 alpha-2, like "DE". Statistics count countries by it.
    country_code: str = Field(default="", index=True)
    # The IANA time zone at the sticker, for its local time of day.
    timezone: str = "UTC"


class Sticker(StickerBase, table=True):
    id: int | None = Field(default=None, primary_key=True)

    def to_geojson(self) -> Feature:
        return Feature(
            geometry=Point((self.longitude, self.latitude)),
            properties={
                "id": self.id,
                "name": self.name,
            },
        )


class StickerPublic(StickerBase):
    id: int

    @computed_field
    @property
    def people(self) -> list[str]:
        return split_people(self.name)


class StickerCreate(SQLModel):
    """What a client may set. The server adds the date, the address and the rest."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_NAME_LENGTH
        ),
    ]
