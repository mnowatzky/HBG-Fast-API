from datetime import UTC, datetime

import pytest
from geographiclib.geodesic import Geodesic

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
        ("middle", 10007.6),
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


NORDERSTEDT = {"latitude": 53.67549805330424, "longitude": 9.980945457552263}

# On the equator, a degree of longitude is 111.2 km.
DEGREE_KM = 111.2


@pytest.mark.parametrize(
    ("place", "latitude", "longitude"),
    [
        ("next street", 53.712214, 10.0187034),
        ("Tromsø", 69.6524868, 18.9588202),
        ("Kanazawa", 36.5571747, 136.6452179),
        ("Nanaimo", 49.1659709, -123.9389489),
        ("Oakura", -39.100663, 173.977806),
        ("almost the antipode", -53.6, -170.1),
    ],
)
def test_distances_are_on_the_globe(client, session, place, latitude, longitude):
    """Within 0.5 % of the ellipsoid that GPS uses, which a sphere can't beat."""
    add(session, place, latitude=latitude, longitude=longitude)
    exact = Geodesic.WGS84.Inverse(
        NORDERSTEDT["latitude"], NORDERSTEDT["longitude"], latitude, longitude
    )["s12"]

    [farthest] = client.get("/stats/farthest", params=NORDERSTEDT).json()

    assert farthest["distance_km"] == pytest.approx(exact / 1000, rel=0.005)


@pytest.mark.parametrize(
    ("first", "second", "km"),
    [
        # Across the date line, not around the world
        ((0, 179.5), (0, -179.5), DEGREE_KM),
        # Across the North Pole
        ((89.9, 0), (89.9, 180), DEGREE_KM / 5),
    ],
)
def test_distances_take_the_short_way(client, session, first, second, km):
    add(session, "Malte", latitude=second[0], longitude=second[1])
    place = {"latitude": first[0], "longitude": first[1]}

    [farthest] = client.get("/stats/farthest", params=place).json()

    assert farthest["distance_km"] == pytest.approx(km, abs=0.1)
