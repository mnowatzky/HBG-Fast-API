from datetime import datetime

import pytest
from sqlmodel import select

from delete_stickers import delete_stickers, select_stickers
from sticker import Sticker


@pytest.fixture
def stickers(session):
    """Ids 1 to 3, one day apart."""
    for day, name in enumerate(["first", "second", "third"], start=1):
        session.add(
            Sticker(
                id=day, latitude=1, longitude=2, name=name, date=datetime(2024, 1, day)
            )
        )
    session.commit()


def names(stickers):
    return [s.name for s in stickers]


def test_select_by_ids(session, stickers):
    assert names(select_stickers(session, [3, 1], None)) == ["first", "third"]


def test_select_since(session, stickers):
    selected = select_stickers(session, [], datetime(2024, 1, 2))

    assert names(selected) == ["second", "third"]


def test_select_combines_ids_and_since(session, stickers):
    selected = select_stickers(session, [1, 3], datetime(2024, 1, 2))

    assert names(selected) == ["third"]


def test_select_refuses_an_empty_selection(session, stickers):
    with pytest.raises(ValueError, match="at least one id"):
        select_stickers(session, [], None)


def test_delete_removes_only_the_selection(session, stickers):
    delete_stickers(session, select_stickers(session, [2], None))

    assert session.scalars(select(Sticker.name)).all() == ["first", "third"]
