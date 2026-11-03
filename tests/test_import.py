from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func
from sqlmodel import select

from import_stickers import import_stickers, read_stickers
from sticker import Sticker

HEADER = "id;latitude;longitude;name;date;city;state;country\n"
ROWS = (
    "60;49.35;16.02;Malte;2019-04-05 13:17:34;Brno;Südmähren;Tschechien\n"
    "2732;34.68;135.52;Lisa & Timo;2026-10-01 10:00:00;Ōsaka;NULL; \n"
)


def write_export(tmp_path, content):
    path = tmp_path / "locations.csv"
    path.write_text(content, encoding="utf-8")
    return path


def test_read_cleans_up_legacy_values(tmp_path):
    first, second = read_stickers(write_export(tmp_path, HEADER + ROWS))

    assert first.id == 60
    assert first.country_code == "CZ"
    assert second.city == "Ōsaka"
    assert second.state == ""
    assert second.country == ""
    assert second.country_code == ""


def test_read_converts_the_old_servers_time_to_utc(tmp_path):
    path = write_export(tmp_path, HEADER + ROWS)

    # Summer time in Berlin, UTC+2
    assert read_stickers(path)[0].date == datetime(2019, 4, 5, 11, 17, 34, tzinfo=UTC)
    assert read_stickers(path, ZoneInfo("UTC"))[0].date == datetime(
        2019, 4, 5, 13, 17, 34, tzinfo=UTC
    )


def test_read_gives_legacy_country_names_a_code_and_the_german_name(tmp_path):
    content = HEADER + "1;52.2;21.0;Timo;2024-01-01;Warschau;;Poland\n"

    [sticker] = read_stickers(write_export(tmp_path, content))

    assert (sticker.country_code, sticker.country) == ("PL", "Polen")


@pytest.mark.parametrize("delimiter", [",", "\t"])
def test_read_detects_the_delimiter(tmp_path, delimiter):
    content = (HEADER + ROWS.replace(" & ", "&")).replace(";", delimiter)

    assert len(read_stickers(write_export(tmp_path, content))) == 2


def test_read_keeps_quotes_in_mysql_batch_output(tmp_path):
    content = (HEADER + '1;1;2;"Der" Timo;2024-01-01;;;\n').replace(";", "\t")

    assert read_stickers(write_export(tmp_path, content))[0].name == '"Der" Timo'


@pytest.mark.parametrize(
    "content, message",
    [
        ("id;name\n1;Malte\n", "missing columns"),
        (HEADER, "no rows"),
        (HEADER + "1;91;2;Malte;2024-01-01;;;\n", "line 2: coordinates"),
        (HEADER + "1;x;2;Malte;2024-01-01;;;\n", "line 2"),
        (HEADER + "1;1;2; ;2024-01-01;;;\n", "line 2: name"),
        (HEADER + "1;1;2;Malte;NULL;;;\n", "line 2"),
    ],
)
def test_read_rejects_bad_files(tmp_path, content, message):
    with pytest.raises(ValueError, match=message):
        read_stickers(write_export(tmp_path, content))


def stored_count(session):
    return session.scalar(select(func.count()).select_from(Sticker))


def test_import_keeps_ids_and_new_stickers_continue_after_them(
    tmp_path, session, client
):
    import_stickers(
        session, read_stickers(write_export(tmp_path, HEADER + ROWS)), False
    )

    created = client.post(
        "/stickers", json={"latitude": 1, "longitude": 2, "name": "Neu"}
    )

    assert created.status_code == 201
    assert created.json()["id"] == 2733


def test_import_adds_the_time_zone_of_each_place(tmp_path, session):
    import_stickers(
        session, read_stickers(write_export(tmp_path, HEADER + ROWS)), False
    )

    zones = session.exec(select(Sticker.id, Sticker.timezone).order_by(Sticker.id))
    assert zones.all() == [(60, "Europe/Prague"), (2732, "Asia/Tokyo")]


def test_import_refuses_to_touch_existing_stickers_without_replace(tmp_path, session):
    stickers = read_stickers(write_export(tmp_path, HEADER + ROWS))
    import_stickers(session, stickers, False)

    with pytest.raises(ValueError, match="already has 2 stickers"):
        import_stickers(
            session, read_stickers(write_export(tmp_path, HEADER + ROWS)), False
        )

    assert stored_count(session) == 2


def test_import_with_replace_swaps_the_table_contents(tmp_path, session):
    session.add(Sticker(latitude=1, longitude=2, name="test"))
    session.commit()

    import_stickers(session, read_stickers(write_export(tmp_path, HEADER + ROWS)), True)

    names = session.scalars(select(Sticker.name)).all()
    assert sorted(names) == ["Lisa & Timo", "Malte"]
