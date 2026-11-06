from datetime import datetime

import pytest
from sqlmodel import select

from rename_person import plan_renames, replace_person, save_renames
from sticker import Sticker


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Jan L", "Jan L."),
        ("jan l", "Jan L."),
        ("Jan L & Collin", "Jan L. & Collin"),
        ("Collin&jan l", "Collin & Jan L."),
        # Already there under the new spelling
        ("Jan L. & Jan L", "Jan L."),
        ("jan l & Jan L.", "Jan L."),
        # Only the renamed person is merged.
        ("Timo & timo & jan l", "Timo & timo & Jan L."),
        # Other people who only start alike
        ("Jan Lippert", "Jan Lippert"),
        ("Jan", "Jan"),
    ],
)
def test_replace_person_replaces_the_whole_person(name, expected):
    assert replace_person(name, "jan l", "Jan L.") == expected


@pytest.fixture
def stickers(session):
    for day, name in enumerate(["Jan L", "Collin & jan l", "Jan Lippert", "Jan L."], 1):
        session.add(
            Sticker(
                id=day, latitude=1, longitude=2, name=name, date=datetime(2024, 1, day)
            )
        )
    session.commit()


def names(session):
    return session.scalars(select(Sticker.name).order_by(Sticker.id)).all()


def test_plan_lists_only_what_changes_and_changes_nothing(session, stickers):
    renames = plan_renames(session, "Jan L", "Jan L.")

    assert [(s.id, name) for s, name in renames] == [
        (1, "Jan L."),
        (2, "Collin & Jan L."),
    ]
    assert names(session) == ["Jan L", "Collin & jan l", "Jan Lippert", "Jan L."]


def test_rename_saves_the_plan(session, stickers):
    save_renames(session, plan_renames(session, "jan l", "Jan L."))

    assert names(session) == ["Jan L.", "Collin & Jan L.", "Jan Lippert", "Jan L."]


def test_renaming_into_a_spelling_in_another_case(session, stickers):
    save_renames(session, plan_renames(session, "jan l.", "JAN L."))

    assert names(session)[3] == "JAN L."


@pytest.mark.parametrize("new", ["", "  ", "Jan & Collin"])
def test_the_new_name_must_be_one_person(session, stickers, new):
    with pytest.raises(ValueError, match="not one person"):
        plan_renames(session, "Jan L", new)


def test_a_name_must_not_grow_too_long(session, stickers):
    with pytest.raises(ValueError, match="too long"):
        plan_renames(session, "Collin", "C" * 80)
