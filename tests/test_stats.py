from datetime import UTC, datetime

import pytest

from sticker import Sticker


def add(session, name, date=datetime(2024, 1, 1, 12), **fields):
    fields = {"latitude": 1, "longitude": 2, "timezone": "UTC", **fields}
    session.add(Sticker(name=name, date=date.replace(tzinfo=UTC), **fields))
    session.commit()


def counts(client, by, **params):
    response = client.get("/stats/counts", params={"by": by, **params})
    assert response.status_code == 200
    return [(c["key"], c["label"], c["count"]) for c in response.json()]


def test_summary_counts_people_cities_and_countries_once(client, session):
    add(session, "Lisa & Timo", city="Hamburg", country_code="DE")
    add(session, "timo", city="Hamburg", country_code="DE")
    add(session, "Ana", city="Wien", country_code="AT")
    add(session, "Ana", city="", country_code="")

    assert client.get("/stats/summary").json() == {
        "stickers": 4,
        "people": 3,
        "cities": 2,
        "countries": 2,
    }


def test_summary_takes_the_filters(client, session):
    add(session, "Timo", date=datetime(2024, 1, 31, 23))
    add(session, "Lisa", date=datetime(2024, 2, 1))

    summary = client.get(
        "/stats/summary",
        params={"since": "2024-02-01T00:00:00Z", "until": "2024-03-01T00:00:00Z"},
    ).json()

    assert summary["stickers"] == 1
    assert summary["people"] == 1


def test_summary_of_nothing_is_zero(client, session):
    assert client.get("/stats/summary").json() == {
        "stickers": 0,
        "people": 0,
        "cities": 0,
        "countries": 0,
    }


def test_countries_count_by_code_with_the_most_common_name(client, session):
    for country in ["Deutschland", "Deutschland", "Germany"]:
        add(session, "Malte", country=country, country_code="DE")
    add(session, "Malte", country="Österreich", country_code="AT")
    add(session, "Malte", country="", country_code="")

    assert counts(client, "country") == [
        ("DE", "Deutschland", 3),
        ("AT", "Österreich", 1),
    ]


def test_people_count_case_insensitively_most_first(client, session):
    for name in ["Timo", "Lisa & Timo", "timo", "Lisa", "Ana"]:
        add(session, name)

    assert counts(client, "person") == [
        ("timo", "Timo", 3),
        ("lisa", "Lisa", 2),
        ("ana", "Ana", 1),
    ]
    assert counts(client, "person", limit=1) == [("timo", "Timo", 3)]


def test_most_stickers_at_night(client, session):
    add(session, "Timo", date=datetime(2024, 1, 1, 23))
    add(session, "Timo", date=datetime(2024, 1, 2, 2))
    add(session, "Lisa", date=datetime(2024, 1, 1, 23))
    add(session, "Lisa", date=datetime(2024, 1, 1, 12))
    add(session, "Lisa", date=datetime(2024, 1, 1, 13))

    assert counts(client, "person", time_of_day="night") == [
        ("timo", "Timo", 2),
        ("lisa", "Lisa", 1),
    ]


def test_hours_are_local_and_in_order(client, session):
    # 21:00 UTC is 22:00 in Berlin in winter.
    add(session, "Malte", date=datetime(2024, 1, 1, 21), timezone="Europe/Berlin")
    add(session, "Malte", date=datetime(2024, 1, 1, 9))
    add(session, "Malte", date=datetime(2024, 1, 2, 9))

    assert counts(client, "hour") == [("09", "09", 2), ("22", "22", 1)]


def test_months_and_weekdays(client, session):
    # Monday, Sunday and a Monday in February
    for day in [datetime(2024, 1, 1), datetime(2024, 1, 7), datetime(2024, 2, 5)]:
        add(session, "Malte", date=day)

    assert counts(client, "month") == [
        ("2024-01", "2024-01", 2),
        ("2024-02", "2024-02", 1),
    ]
    assert counts(client, "weekday") == [("1", "1", 2), ("7", "7", 1)]


def test_counts_reject_an_unknown_grouping(client):
    assert client.get("/stats/counts", params={"by": "colour"}).status_code == 422


def test_farthest_comes_first_with_its_distance(client, session):
    add(session, "near", latitude=0, longitude=1)
    add(session, "antipode", latitude=0, longitude=180)
    add(session, "middle", latitude=0, longitude=90)

    response = client.get(
        "/stats/farthest", params={"latitude": 0, "longitude": 0, "limit": 2}
    )

    assert [(s["name"], s["distance_km"]) for s in response.json()] == [
        ("antipode", 20015.1),
        ("middle", 10007.5),
    ]
    assert response.json()[0]["people"] == ["antipode"]


def test_farthest_takes_the_filters(client, session):
    add(session, "Timo", latitude=0, longitude=180)
    add(session, "Lisa", latitude=0, longitude=90)

    response = client.get(
        "/stats/farthest", params={"latitude": 0, "longitude": 0, "name": "lisa"}
    )

    assert [s["name"] for s in response.json()] == ["Lisa"]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"latitude": 0},
        {"latitude": 91, "longitude": 0},
        {"latitude": 0, "longitude": 0, "limit": 101},
    ],
)
def test_farthest_needs_a_valid_place(client, params):
    assert client.get("/stats/farthest", params=params).status_code == 422
