"""The address of a sticker, from Nominatim, so every sticker gets it in German."""

import json
import logging
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlmodel import SQLModel

from config import config

logger = logging.getLogger("uvicorn.error")

# The first key that Nominatim fills in wins.
CITY_KEYS = ["city", "town", "village", "municipality", "region", "county", "state"]
STATE_KEYS = ["state", "state_district", "county"]
CITY_STATES = {"Hamburg", "Bremen", "Berlin"}

USER_AGENT = "HBG-Sticker-API (+https://github.com/mnowatzky/HBG-Fast-API)"


class Address(SQLModel):
    city: str = ""
    state: str = ""
    country: str = ""
    country_code: str = ""


def first(address: dict[str, str], keys: list[str]) -> str:
    return next((address[key] for key in keys if address.get(key)), "")


def parse_address(address: dict[str, str]) -> Address:
    city = first(address, CITY_KEYS)
    return Address(
        city=city,
        state=city if city in CITY_STATES else first(address, STATE_KEYS),
        country=address.get("country", ""),
        country_code=address.get("country_code", "").upper(),
    )


class Nominatim:
    # The usage policy allows one request per second for the whole application.
    min_interval = 1.0

    def __init__(self, url: str, email: str, timeout: float = 3) -> None:
        self.url = url
        self.email = email
        self.timeout = timeout
        self._lock = threading.Lock()
        self._last_request = 0.0

    def reverse(self, latitude: float, longitude: float) -> Address:
        """The address at the place, or an empty one if Nominatim fails."""
        params = {
            "format": "jsonv2",
            "lat": latitude,
            "lon": longitude,
            "zoom": 10,
            "accept-language": "de",
        }
        if self.email:
            params["email"] = self.email
        request = Request(
            f"{self.url}?{urlencode(params)}", headers={"User-Agent": USER_AGENT}
        )
        try:
            with self._lock:
                time.sleep(
                    max(0, self._last_request + self.min_interval - time.monotonic())
                )
                self._last_request = time.monotonic()
            with urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except (OSError, ValueError) as error:
            logger.warning("Reverse geocoding failed: %s", error)
            return Address()
        # Places like the open sea have no address.
        return parse_address(body.get("address", {}))


nominatim = Nominatim(config.sticker_nominatim_url, config.sticker_nominatim_email)


def get_geocoder() -> Nominatim:
    return nominatim
