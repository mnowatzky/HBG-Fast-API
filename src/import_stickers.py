"""Load an export of the legacy MySQL `locations` table into the sticker table.

Usage: python src/import_stickers.py locations.csv [--replace]

The file needs a header row with the columns id, latitude, longitude, name,
date, city, state and country, separated by semicolons, commas or tabs. The
import runs in one transaction, so any invalid row leaves the table untouched.
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, text
from sqlmodel import Session, create_engine, select

from config import config
from sticker import Sticker

COLUMNS = {"id", "latitude", "longitude", "name", "date", "city", "state", "country"}


def clean(value: str | None) -> str:
    value = (value or "").strip()
    return "" if value == "NULL" else value


def parse_row(row: dict[str, str]) -> Sticker:
    latitude = float(row["latitude"])
    longitude = float(row["longitude"])
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError(f"coordinates out of range: {latitude}, {longitude}")
    name = clean(row["name"])
    if not name:
        raise ValueError("name is empty")
    return Sticker(
        id=int(row["id"]),
        latitude=latitude,
        longitude=longitude,
        name=name,
        date=datetime.fromisoformat(clean(row["date"])),
        city=clean(row["city"]),
        state=clean(row["state"]),
        country=clean(row["country"]),
    )


def read_stickers(path: Path) -> list[Sticker]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        header = file.readline()
        delimiter = max(";,\t", key=header.count)
        file.seek(0)
        # `mysql --batch` writes tab-separated values and does not quote them.
        quoting = csv.QUOTE_NONE if delimiter == "\t" else csv.QUOTE_MINIMAL
        reader = csv.DictReader(file, delimiter=delimiter, quoting=quoting)
        missing = COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing columns: {', '.join(sorted(missing))}")
        stickers = []
        for row in reader:
            try:
                stickers.append(parse_row(row))
            except (TypeError, ValueError) as error:
                raise ValueError(f"line {reader.line_num}: {error}") from error
    if not stickers:
        raise ValueError("the file has no rows")
    return stickers


def import_stickers(session: Session, stickers: list[Sticker], replace: bool) -> None:
    existing = session.scalar(select(func.count()).select_from(Sticker))
    if existing and not replace:
        raise ValueError(
            f"the table already has {existing} stickers, use --replace to delete them"
        )
    session.exec(delete(Sticker))
    session.add_all(stickers)
    session.flush()
    # The ids come from the file, so the sequence has to catch up with them.
    session.exec(  # type: ignore
        text(
            "SELECT setval(pg_get_serial_sequence('sticker', 'id'), max(id)) FROM sticker"
        )
    )
    session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--replace", action="store_true", help="delete all existing stickers first"
    )
    args = parser.parse_args()
    try:
        stickers = read_stickers(args.file)
        with Session(create_engine(config.db_url)) as session:
            import_stickers(session, stickers, args.replace)
            newest = session.scalar(select(func.max(Sticker.date)))
    except (OSError, ValueError) as error:
        sys.exit(f"Nothing imported: {error}")
    print(f"Imported {len(stickers)} stickers, the newest from {newest}.")


if __name__ == "__main__":
    main()
