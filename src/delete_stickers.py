"""Delete spam or mistaken stickers. The API has no endpoint for this.

Usage: python src/delete_stickers.py [ID ...] [--since "YYYY-MM-DD HH:MM"] [--yes]

Selects the given ids, or every sticker saved at or after --since (UTC), or the
intersection of both. Without --yes it only lists the selection, so run it once
to check, then again with --yes. Back up the database first.
"""

import argparse
import sys
from datetime import datetime

from sqlalchemy import delete
from sqlmodel import Session, col, create_engine, select

from config import config
from sticker import Sticker


def select_stickers(
    session: Session, ids: list[int], since: datetime | None
) -> list[Sticker]:
    if not ids and since is None:
        raise ValueError("give at least one id or --since")
    stmt = select(Sticker).order_by(col(Sticker.date), col(Sticker.id))
    if ids:
        stmt = stmt.where(col(Sticker.id).in_(ids))
    if since is not None:
        stmt = stmt.where(Sticker.date >= since)
    return list(session.exec(stmt).all())


def delete_stickers(session: Session, stickers: list[Sticker]) -> None:
    session.exec(delete(Sticker).where(col(Sticker.id).in_([s.id for s in stickers])))
    session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ids", type=int, nargs="*", metavar="ID")
    parser.add_argument(
        "--since",
        type=datetime.fromisoformat,
        help="only stickers saved at or after this UTC time",
    )
    parser.add_argument("--yes", action="store_true", help="really delete them")
    args = parser.parse_args()
    try:
        with Session(create_engine(config.db_url)) as session:
            stickers = select_stickers(session, args.ids, args.since)
            for s in stickers:
                print(f"{s.id}\t{s.date}\t{s.name}\t{s.city}, {s.country}")
            if not stickers:
                print("No stickers match.")
            elif args.yes:
                delete_stickers(session, stickers)
                print(f"Deleted {len(stickers)} stickers.")
            else:
                print(f"{len(stickers)} stickers match. Run again with --yes.")
    except ValueError as error:
        sys.exit(f"Nothing deleted: {error}")


if __name__ == "__main__":
    main()
