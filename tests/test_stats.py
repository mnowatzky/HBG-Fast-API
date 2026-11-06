from datetime import UTC, datetime

import pytest
from geographiclib.geodesic import Geodesic

from stats import HOME
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


def test_counts_by_local_day_in_order(client, session):
    # 23:30 UTC is already the next day in Berlin.
    add(session, "Malte", date=datetime(2024, 1, 1, 23, 30), timezone="Europe/Berlin")
    add(session, "Malte", date=datetime(2024, 1, 1, 12))

    assert counts(client, "day") == [
        ("2024-01-01", "2024-01-01", 1),
        ("2024-01-02", "2024-01-02", 1),
    ]


NORDERSTEDT = HOME._asdict()

# On the equator, a degree of longitude is 111.2 km.
DEGREE_KM = 111.2


def people_stats(client, **params):
    response = client.get("/stats/people", params=params)
    assert response.status_code == 200
    return {person["key"]: person for person in response.json()}


def test_people_count_what_each_stickered_most_first(client, session):
    add(session, "Lisa & Timo", city="Hamburg", country_code="DE")
    add(session, "timo", city="Wien", country_code="AT")
    add(session, "Timo", city="", country_code="")

    response = client.get("/stats/people")

    assert [p["key"] for p in response.json()] == ["timo", "lisa"]
    timo = response.json()[0]
    assert (timo["label"], timo["stickers"], timo["countries"], timo["cities"]) == (
        "Timo",
        3,
        2,
        2,
    )
    assert timo["farthest"] is None


def test_people_count_nights_and_weekends_in_local_time(client, session):
    berlin = {"timezone": "Europe/Berlin"}
    # Saturday 22:30 in Berlin
    add(session, "Malte", date=datetime(2024, 1, 6, 21, 30), **berlin)
    # Sunday 23:30 in UTC, but Monday 0:30 in Berlin
    add(session, "Malte", date=datetime(2024, 1, 7, 23, 30), **berlin)
    # Monday noon
    add(session, "Malte", date=datetime(2024, 1, 8, 11), **berlin)

    malte = people_stats(client)["malte"]

    assert (malte["night"], malte["weekend"]) == (2, 1)


def test_people_travel_along_their_own_stickers_in_order(client, session):
    add(session, "Ana", date=datetime(2024, 1, 1), latitude=0, longitude=0)
    add(session, "Ana", date=datetime(2024, 1, 3), latitude=0, longitude=1)
    # Placed in between, so Ana went 2 degrees east and then 1 back.
    add(session, "Ana & Ben", date=datetime(2024, 1, 2), latitude=0, longitude=2)

    stats = people_stats(client)

    assert stats["ana"]["travelled_km"] == 3 * DEGREE_KM
    assert stats["ana"]["first"] == "2024-01-01T00:00:00Z"
    assert stats["ana"]["last"] == "2024-01-03T00:00:00Z"
    # A first sticker has no way to it, not one of half the globe.
    assert stats["ben"]["travelled_km"] == 0


def test_people_travel_only_between_the_filtered_stickers(client, session):
    add(session, "Ana", date=datetime(2024, 1, 1), latitude=0, longitude=90)
    add(session, "Ana", date=datetime(2024, 2, 1), latitude=0, longitude=0)
    add(session, "Ana", date=datetime(2024, 2, 2), latitude=0, longitude=1)

    ana = people_stats(client, since="2024-02-01T00:00:00Z")["ana"]

    assert (ana["stickers"], ana["travelled_km"]) == (2, DEGREE_KM)


def test_people_get_their_farthest_sticker_from_a_place(client, session):
    add(session, "Ana", latitude=0, longitude=1)
    add(session, "Ana & Ben", latitude=0, longitude=-2)

    stats = people_stats(client, latitude=0, longitude=0)

    assert stats["ana"]["farthest"]["longitude"] == -2
    assert stats["ana"]["farthest"]["distance_km"] == 2 * DEGREE_KM
    assert stats["ben"]["farthest"]["people"] == ["Ana", "Ben"]


@pytest.mark.parametrize("params", [{"latitude": 0}, {"longitude": 0}])
def test_people_need_both_coordinates_or_none(client, params):
    assert client.get("/stats/people", params=params).status_code == 422


def test_people_of_nothing_are_none(client, session):
    assert client.get("/stats/people", params=NORDERSTEDT).json() == []


def test_a_person_twice_on_a_sticker_counts_once(client, session):
    add(session, "Ana & ana", date=datetime(2024, 1, 6, 23))
    add(session, "Ana & Ben")

    assert people_stats(client)["ana"]["stickers"] == 2
    assert people_stats(client)["ana"]["night"] == 1
    assert people_stats(client)["ana"]["weekend"] == 1
    # "Ana" and "ana" are equally common, so the label could be either.
    assert [(key, n) for key, _, n in counts(client, "person")] == [
        ("ana", 2),
        ("ben", 1),
    ]
    assert client.get("/stats/summary").json()["people"] == 2
    assert [(keys, n) for keys, _, n in pairs(client)] == [(["ana", "ben"], 1)]


def test_days_filter_by_the_local_date(client, session):
    tokyo, new_york = {"timezone": "Asia/Tokyo"}, {"timezone": "America/New_York"}
    # 1 November in Tokyo, but still 31 October in UTC
    add(session, "Tokyo", date=datetime(2024, 10, 31, 20), **tokyo)
    # 31 October in New York, but already 1 November in UTC
    add(session, "New York", date=datetime(2024, 11, 1, 2), **new_york)
    add(session, "December", date=datetime(2024, 12, 1, 12))

    november = {"since_day": "2024-11-01", "until_day": "2024-12-01"}

    assert counts(client, "person", **november) == [("tokyo", "Tokyo", 1)]
    assert records(client, **november)["record_day"] == {
        "day": "2024-11-01",
        "count": 1,
    }
    assert counts(client, "month", **november) == [("2024-11", "2024-11", 1)]


def pairs(client, **params):
    response = client.get("/stats/pairs", params=params)
    assert response.status_code == 200
    return [(p["keys"], p["labels"], p["count"]) for p in response.json()]


def test_pairs_count_shared_stickers_most_first(client, session):
    for name in ["Lisa & Timo", "timo & lisa", "Timo & Ana", "Lisa & Timo & Ana"]:
        add(session, name)
    add(session, "Ana")
    # The same person twice is no pair.
    add(session, "Timo & timo")

    assert pairs(client) == [
        (["lisa", "timo"], ["Lisa", "Timo"], 3),
        (["ana", "timo"], ["Ana", "Timo"], 2),
        (["ana", "lisa"], ["Ana", "Lisa"], 1),
    ]
    assert pairs(client, limit=1) == [(["lisa", "timo"], ["Lisa", "Timo"], 3)]
    # Only the stickers with Ana, which include one of Lisa and Timo
    assert pairs(client, name="ana") == [
        (["ana", "timo"], ["Ana", "Timo"], 2),
        (["ana", "lisa"], ["Ana", "Lisa"], 1),
        (["lisa", "timo"], ["Lisa", "Timo"], 1),
    ]


def records(client, **params):
    response = client.get("/stats/records", params=params)
    assert response.status_code == 200
    return response.json()


def test_record_day_is_local_and_the_earliest_of_equals(client, session):
    berlin = {"timezone": "Europe/Berlin"}
    add(session, "Malte", date=datetime(2024, 1, 1, 12), **berlin)
    # 2 January in Berlin
    add(session, "Malte", date=datetime(2024, 1, 1, 23, 30), **berlin)
    add(session, "Malte", date=datetime(2024, 1, 2, 12), **berlin)
    add(session, "Malte", date=datetime(2024, 3, 1, 12), **berlin)
    add(session, "Malte", date=datetime(2024, 3, 1, 13), **berlin)

    assert records(client)["record_day"] == {"day": "2024-01-02", "count": 2}


def test_longest_streak_of_days_is_the_earliest_of_equals(client, session):
    for day in [1, 2, 3, 10, 11, 20, 21, 22]:
        add(session, "Malte", date=datetime(2024, 1, day, 12))
    # Twice on one day is still one day.
    add(session, "Malte", date=datetime(2024, 1, 2, 13))

    assert records(client)["longest_streak"] == {
        "start": "2024-01-01",
        "end": "2024-01-03",
        "days": 3,
    }


def test_streaks_run_across_months(client, session):
    for day in [datetime(2024, 1, 31), datetime(2024, 2, 1), datetime(2024, 2, 2)]:
        add(session, "Malte", date=day)

    assert records(client)["longest_streak"]["days"] == 3


def test_records_hold_the_stickers_at_the_ends_of_the_world(client, session):
    add(session, "north", latitude=69.6, longitude=18.9)
    add(session, "south", latitude=-39.1, longitude=173.9)
    add(session, "west", latitude=49.1, longitude=-123.9)
    add(session, "middle", latitude=0, longitude=0)

    found = records(client)

    assert [found[end]["name"] for end in ["north", "south", "east", "west"]] == [
        "north",
        "south",
        "south",
        "west",
    ]


def test_home_share_counts_stickers_within_25_km(client, session):
    # About 3 km and 14 km from home, and Berlin
    add(session, "Malte", latitude=53.70, longitude=10.00)
    add(session, "Malte", latitude=53.55, longitude=9.99)
    add(session, "Malte", latitude=52.52, longitude=13.40)

    share = records(client)["home_share"]

    assert share == {**NORDERSTEDT, "radius_km": 25.0, "within": 2, "total": 3}
    assert records(client, name="nobody")["home_share"]["total"] == 0


def test_records_of_nothing_are_none(client, session):
    found = records(client)

    assert [found[k] for k in ["record_day", "longest_streak", "north"]] == [None] * 3


def test_latest_are_the_two_newest_and_their_distance(client, session):
    add(session, "old", date=datetime(2024, 1, 1), latitude=0, longitude=50)
    add(session, "before", date=datetime(2024, 1, 2), latitude=0, longitude=0)
    add(session, "newest", date=datetime(2024, 1, 3), latitude=0, longitude=1)

    # It takes no filters, so the name changes nothing.
    latest = client.get("/stats/latest", params={"name": "old"}).json()

    assert [s["name"] for s in latest["stickers"]] == ["newest", "before"]
    assert latest["distance_km"] == DEGREE_KM


def test_latest_of_one_sticker_has_no_distance(client, session):
    add(session, "only")

    latest = client.get("/stats/latest").json()

    assert ([s["name"] for s in latest["stickers"]], latest["distance_km"]) == (
        ["only"],
        None,
    )


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
