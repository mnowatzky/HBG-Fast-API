"""Time zones from coordinates, and country codes for the legacy country names."""

from collections.abc import Collection

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session
from tzfpy import get_tz


def known_timezones(db: Session | Connection) -> frozenset[str]:
    """The zone names PostgreSQL accepts, which can lag behind tzfpy's data."""
    return frozenset(db.scalars(text("SELECT name FROM pg_timezone_names")))


def timezone_at(latitude: float, longitude: float, known: Collection[str]) -> str:
    """The IANA zone at the place. At sea, tzfpy answers with an Etc/GMT zone."""
    name = get_tz(longitude, latitude)
    if name in known:
        return name
    # The nautical zone. Etc/GMT names count the other way round: -1 is UTC+1.
    return f"Etc/GMT{-round(longitude / 15):+d}"


# The old site stored Nominatim's country names in each visitor's language.
LEGACY_COUNTRIES = {
    "AL": ("Albanien", ["Albania"]),
    "AT": ("Österreich", ["Austria"]),
    "AU": ("Australien", ["Australia"]),
    "BE": ("Belgien", ["Belgium"]),
    "BG": ("Bulgarien", ["Bulgaria"]),
    "CA": ("Kanada", ["Canada"]),
    "CH": ("Schweiz", ["Switzerland"]),
    "CO": ("Kolumbien", ["Colombia"]),
    "CY": ("Zypern", ["Cyprus"]),
    "CZ": ("Tschechien", ["Czechia", "Czech Republic"]),
    "DE": ("Deutschland", ["Germany"]),
    "DK": ("Dänemark", ["Denmark"]),
    "EG": ("Ägypten", ["Egypt"]),
    "ES": ("Spanien", ["Spain"]),
    "ET": ("Äthiopien", ["Ethiopia"]),
    "FR": ("Frankreich", ["France"]),
    "GB": ("Vereinigtes Königreich", ["United Kingdom"]),
    "GI": ("Gibraltar", []),
    "GR": ("Griechenland", ["Greece"]),
    "HR": ("Kroatien", ["Croatia"]),
    "HU": ("Ungarn", ["Hungary"]),
    "ID": ("Indonesien", ["Indonesia"]),
    "IE": ("Irland", ["Ireland"]),
    "IT": ("Italien", ["Italy"]),
    "JP": ("Japan", []),
    "KG": ("Kirgisistan", ["Kyrgyzstan"]),
    "KR": ("Südkorea", ["South Korea"]),
    "MC": ("Monaco", []),
    "MT": ("Malta", []),
    "MX": ("Mexiko", ["Mexico"]),
    "MY": ("Malaysia", []),
    "NL": ("Niederlande", ["Netherlands"]),
    # Norja and Ruotsi are Finnish.
    "NO": ("Norwegen", ["Norway", "Norja"]),
    "NZ": ("Neuseeland", ["New Zealand"]),
    "PE": ("Peru", []),
    "PL": ("Polen", ["Poland"]),
    "PT": ("Portugal", []),
    "RO": ("Rumänien", ["Romania"]),
    "SE": ("Schweden", ["Sweden", "Ruotsi"]),
    "SI": ("Slowenien", ["Slovenia"]),
    "SK": ("Slowakei", ["Slovakia"]),
    "TH": ("Thailand", []),
    "TR": ("Türkei", ["Turkey", "Türkiye"]),
    "US": (
        "Vereinigte Staaten von Amerika",
        ["Vereinigte Staaten", "United States", "United States of America"],
    ),
}

_BY_NAME = {
    name.casefold(): (code, german)
    for code, (german, others) in LEGACY_COUNTRIES.items()
    for name in [german, *others]
}


def legacy_country(name: str) -> tuple[str, str]:
    """The code and German name for a legacy country name, or no code if unknown."""
    return _BY_NAME.get(name.strip().casefold(), ("", name))
