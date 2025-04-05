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
