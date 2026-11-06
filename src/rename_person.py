"""Merge two spellings of a person, like "collin." into "Collin".

Usage: python src/rename_person.py OLD NEW [--yes]

Renames OLD wherever it is one of the people on a sticker, case-insensitively,
and keeps the others: OLD "jan l" and NEW "Jan L." turn "Jan L & Collin" into
"Jan L. & Collin", but leave "Jan Lippert" alone. Without --yes it only lists the
changes, so run it once to check, then again with --yes. Back up the database
first.
"""

import argparse
import sys

from sqlmodel import Session, col, create_engine, select

from config import config
from filters import has_person
from sticker import MAX_NAME_LENGTH, Sticker, split_people


def replace_person(name: str, old: str, new: str) -> str:
    """The name of a sticker with the person `old` as `new`. Changes no data.

    If `new` is on the sticker already, it stays there once. Everyone else stays as
    they are, but all of them are joined with " & ", so "Ana&jan l" becomes
    "Ana & Jan L.".
    """
    people: list[str] = []
    for person in split_people(name):
        if person.lower() == old.strip().lower():
            person = new
        if person.lower() == new.lower() and new.lower() in map(str.lower, people):
            continue
        people.append(person)
    return " & ".join(people)


def plan_renames(session: Session, old: str, new: str) -> list[tuple[Sticker, str]]:
    """The stickers with `old` on them and their new names. Changes nothing yet."""
    new = new.strip()
    if not new or split_people(new) != [new]:
        raise ValueError(f"{new!r} is not one person's name")
    stickers = session.exec(
        select(Sticker)
        .where(has_person(old))
        .order_by(col(Sticker.date), col(Sticker.id))
    ).all()
    renames = [(s, replace_person(s.name, old, new)) for s in stickers]
    for sticker, name in renames:
        if len(name) > MAX_NAME_LENGTH:
            raise ValueError(f"sticker {sticker.id} would be named {name!r}, too long")
    return [(s, name) for s, name in renames if name != s.name]


def save_renames(session: Session, renames: list[tuple[Sticker, str]]) -> None:
    for sticker, name in renames:
        sticker.name = name
        session.add(sticker)
    session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("old", help="the spelling to replace, in any case")
    parser.add_argument("new", help="the spelling to keep, as it should be written")
    parser.add_argument("--yes", action="store_true", help="really rename them")
    args = parser.parse_args()
    try:
        with Session(create_engine(config.db_url)) as session:
            renames = plan_renames(session, args.old, args.new)
            for s, name in renames:
                print(f"{s.id}\t{s.date}\t{s.name}\t-> {name}")
            if not renames:
                print("No stickers to rename.")
            elif args.yes:
                save_renames(session, renames)
                print(f"Renamed {len(renames)} stickers.")
            else:
                print(f"{len(renames)} stickers to rename. Run again with --yes.")
    except ValueError as error:
        sys.exit(f"Nothing renamed: {error}")


if __name__ == "__main__":
    main()
