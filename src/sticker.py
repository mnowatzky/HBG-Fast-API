from datetime import datetime
from sqlmodel import Field, SQLModel

class Sticker(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    latitude: float = Field(default=None, index=True)
    longitude: float = Field(default=None, index=True)
    name: str = Field(index=True)
    date: datetime = Field(default=None, index=True)
    city: str = Field(default=None, index=True)
    state: str = Field(default=None, index=True)
    country: str = Field(default=None, index=True)

    def to_geojson(self) -> dict:
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [self.longitude, self.latitude],
            },
            "properties": {
                "name": self.name,
                "date": self.date.isoformat() if self.date else None,
                "city": self.city,
                "state": self.state,
                "country": self.country,
                "id": self.id,
            },
        }