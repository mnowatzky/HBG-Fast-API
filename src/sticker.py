from datetime import UTC, datetime
from typing import Annotated

from geojson import Feature, Point
from pydantic import NaiveDatetime, StringConstraints
from sqlmodel import Field, SQLModel

MAX_NAME_LENGTH = 75

Trimmed = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Sticker(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    latitude: float = Field(index=True)
    longitude: float = Field(index=True)
    name: str = Field(index=True)
    # New stickers are in UTC, ones imported from MySQL in the old server's time.
    date: NaiveDatetime = Field(default_factory=utc_now, index=True)
    # Empty when reverse geocoding finds nothing, e.g. at sea.
    city: str = Field(default="", index=True)
    state: str = Field(default="", index=True)
    country: str = Field(default="", index=True)

    def to_geojson(self) -> Feature:
        return Feature(
            geometry=Point((self.longitude, self.latitude)),
            properties={
                "id": self.id,
                "name": self.name,
            },
        )


class StickerCreate(SQLModel):
    """What a client may set. The id and the date are assigned by the server."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_NAME_LENGTH
        ),
    ]
    city: Trimmed = ""
    state: Trimmed = ""
    country: Trimmed = ""
