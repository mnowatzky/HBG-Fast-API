from datetime import UTC, datetime

import pytest
from conftest import RATE_LIMIT
from limits import parse_many
from sqlalchemy.exc import OperationalError

from config import DotEnvConfig
from db import get_session
from geocode import Address
from main import app
from sticker import Sticker

HAMBURG = {"latitude": 53.55, "longitude": 9.99, "name": "Malte"}


def add_stickers(session, *names, **fields):
    """Oldest first, one day apart."""
    for day, name in enumerate(names, start=1):
        session.add(
            Sticker(
                latitude=1,
                longitude=2,
                name=name,
                date=datetime(2024, 1, day),
                **fields,
            )
        )
    session.commit()


def names(response):
    return [sticker["name"] for sticker in response.json()]


def test_create_returns_the_stored_sticker(client):
    response = client.post("/stickers", json=HAMBURG)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["name"] == "Malte"
    assert body["people"] == ["Malte"]
    assert datetime.fromisoformat(body["date"]).year >= 2026


def stored(client):
    return client.get("/stickers").json()[0]


def test_create_answers_before_the_address_is_known(client):
    body = client.post("/stickers", json=HAMBURG).json()

    assert body["city"] == ""
    assert body["country_code"] == ""


def test_create_adds_the_address_and_the_time_zone_of_the_place(client, geocoder):
    body = client.post(
        "/stickers", json={"latitude": 13.75, "longitude": 100.5, "name": "Timo"}
    ).json()

    assert body["timezone"] == "Asia/Bangkok"
    # The test client runs the background lookup before it returns.
    assert geocoder.places == [(13.75, 100.5)]
    sticker = stored(client)
    assert sticker["city"] == "Hamburg"
    assert sticker["country_code"] == "DE"
    assert sticker["timezone"] == "Asia/Bangkok"


def test_create_ignores_a_client_supplied_address(client):
    client.post("/stickers", json={**HAMBURG, "city": "Atlantis", "country": "Germany"})

    sticker = stored(client)
    assert sticker["city"] == "Hamburg"
    assert sticker["country"] == "Deutschland"


def test_create_ignores_a_client_supplied_date_and_id(client):
    body = client.post(
        "/stickers", json={**HAMBURG, "date": "2099-01-01T00:00:00Z", "id": 999}
    ).json()

    assert body["id"] == 1
    assert not body["date"].startswith("2099")


def test_create_saves_a_sticker_without_an_address(client, geocoder):
    geocoder.address = Address()

    response = client.post(
        "/stickers", json={"latitude": 0, "longitude": -30, "name": "Auf See"}
    )

    assert response.status_code == 201
    assert stored(client)["country"] == ""
    assert stored(client)["timezone"] == "Etc/GMT+2"


def test_create_trims_the_name(client):
    assert (
        client.post("/stickers", json={**HAMBURG, "name": "  Timo "}).json()["name"]
        == "Timo"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"latitude": 90.1},
        {"latitude": -90.1},
        {"longitude": 180.1},
        {"longitude": -180.1},
        {"latitude": "north"},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 76},
    ],
)
def test_create_rejects_invalid_input(client, change):
    assert client.post("/stickers", json={**HAMBURG, **change}).status_code == 422


def test_create_is_rate_limited_per_client(client):
    for _ in range(RATE_LIMIT):
        assert client.post("/stickers", json=HAMBURG).status_code == 201

    assert client.post("/stickers", json=HAMBURG).status_code == 429
    assert client.get("/stickers").status_code == 200


def test_default_rate_limit_has_a_minute_and_a_day_window():
    default = DotEnvConfig.model_fields["sticker_create_rate_limit"].default

    assert [limit.GRANULARITY.name for limit in parse_many(default)] == [
        "minute",
        "day",
    ]


def test_list_returns_full_stickers_newest_first(client, session):
    add_stickers(session, "first", "second")

    response = client.get("/stickers")

    assert response.status_code == 200
    assert names(response) == ["second", "first"]
    assert set(response.json()[0]) == {
        "id", "latitude", "longitude", "name", "date", "city", "state", "country",
        "country_code", "timezone", "people",
    }  # fmt: skip


def test_dates_are_sent_in_utc_with_the_offset(client, session):
    add_stickers(session, "Malte")

    assert client.get("/stickers").json()[0]["date"] == "2024-01-01T00:00:00Z"


def test_people_are_split_like_the_name_filter_splits_them(client, session):
    add_stickers(session, " Lisa &Timo & ")

    assert client.get("/stickers").json()[0]["people"] == ["Lisa", "Timo"]


def test_geojson_is_a_feature_collection_with_lng_lat_order(client, session):
    session.add(
        Sticker(latitude=53.55, longitude=9.99, name="Malte", date=datetime(2024, 1, 1))
    )
    session.commit()

    response = client.get("/stickers", params={"format": "geojson"})

    assert response.headers["content-type"] == "application/geo+json"
    assert response.json() == {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [9.99, 53.55]},
                "properties": {"id": 1, "name": "Malte"},
            }
        ],
    }


@pytest.mark.parametrize("format", ["json", "geojson"])
def test_total_count_covers_all_pages(client, session, format):
    add_stickers(session, "a", "b", "c")

    response = client.get("/stickers", params={"format": format, "limit": 1})

    assert response.headers["x-total-count"] == "3"


def test_pages_are_contiguous_when_dates_tie(client, session):
    tie = datetime(2024, 1, 1)
    session.add_all(
        Sticker(latitude=1, longitude=2, name=str(i), date=tie) for i in range(10)
    )
    session.commit()

    pages = [
        client.get("/stickers", params={"limit": 3, "offset": offset}).json()
        for offset in range(0, 12, 3)
    ]

    ids = [sticker["id"] for page in pages for sticker in page]
    assert ids == list(range(10, 0, -1))


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 5001},
        {"offset": -1},
        {"format": "xml"},
        {"name": "x" * 76},
        {"country": "DEU"},
        {"since": "yesterday"},
        {"time_of_day": "noon"},
    ],
)
def test_list_rejects_invalid_parameters(client, params):
    assert client.get("/stickers", params=params).status_code == 422


def test_name_filter_matches_whole_names_in_shared_stickers(client, session):
    add_stickers(session, "Timo", "Tim", "Lisa & Timo", "Timo&Collin", "timo", "Malte")

    response = client.get("/stickers", params={"name": "Timo"})

    assert names(response) == [
        "timo", "Timo&Collin", "Lisa & Timo", "Timo",
    ]  # fmt: skip
    assert response.headers["x-total-count"] == "4"


def test_name_filter_ignores_stray_whitespace_in_legacy_names(client, session):
    add_stickers(session, "Christoph ", " Lisa & Christoph  ", "Malte")

    response = client.get("/stickers", params={"name": "Christoph"})

    assert response.headers["x-total-count"] == "2"


def test_name_filter_treats_special_characters_literally(client, session):
    add_stickers(session, "Timo", "T.mo")

    assert names(client.get("/stickers", params={"name": "T.mo"})) == ["T.mo"]
    assert client.get("/stickers", params={"name": "%"}).json() == []


def test_country_and_city_filters_ignore_case(client, session):
    add_stickers(session, "Malte", city="Hamburg", country_code="DE")
    add_stickers(session, "Timo", city="Wien", country_code="AT")

    assert names(client.get("/stickers", params={"country": "de"})) == ["Malte"]
    assert names(client.get("/stickers", params={"city": "WIEN"})) == ["Timo"]


def test_since_includes_and_until_excludes_the_moment(client, session):
    add_stickers(session, "1st", "2nd", "3rd")

    params = {"since": "2024-01-02T00:00:00Z", "until": "2024-01-03T00:00:00"}

    assert names(client.get("/stickers", params=params)) == ["2nd"]


def test_since_respects_an_offset(client, session):
    add_stickers(session, "1st", "2nd")

    # Midnight in Berlin is 23:00 UTC the day before, when nothing was placed.
    params = {"since": "2024-01-02T00:00:00+01:00"}

    assert names(client.get("/stickers", params=params)) == ["2nd"]


def test_time_of_day_is_local_where_the_sticker_is(client, session):
    for name, hour, zone in [
        # 23:30 in Bangkok
        ("bangkok evening", 16, "Asia/Bangkok"),
        # 06:30 in Bangkok the next day
        ("bangkok morning", 23, "Asia/Bangkok"),
        ("berlin night", 3, "Europe/Berlin"),
    ]:
        date = datetime(2024, 1, 1, hour, 30, tzinfo=UTC)
        session.add(
            Sticker(latitude=1, longitude=2, name=name, date=date, timezone=zone)
        )
    session.commit()

    night = client.get("/stickers", params={"time_of_day": "night"})
    day = client.get("/stickers", params={"time_of_day": "day"})

    assert sorted(names(night)) == ["bangkok evening", "berlin night"]
    assert names(day) == ["bangkok morning"]


def test_large_responses_are_compressed(client, session):
    add_stickers(session, *["Malte"] * 25)

    response = client.get("/stickers", headers={"Accept-Encoding": "gzip"})

    assert response.headers["content-encoding"] == "gzip"


def test_cors_allows_only_the_configured_origin(client):
    allowed = client.get("/stickers", headers={"Origin": "https://frontend.example"})
    other = client.get("/stickers", headers={"Origin": "https://evil.example"})

    assert allowed.headers["access-control-allow-origin"] == "https://frontend.example"
    assert "x-total-count" in allowed.headers["access-control-expose-headers"].lower()
    assert "access-control-allow-origin" not in other.headers


def test_health_reports_a_reachable_database(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_outage_answers_503_and_hides_connection_details(client):
    def session_without_database():
        raise OperationalError("SELECT 1", {}, Exception("password=secret"))

    app.dependency_overrides[get_session] = session_without_database
    try:
        for path in ["/health", "/stickers", "/stats/summary"]:
            response = client.get(path)
            assert response.status_code == 503
            assert "secret" not in response.text
    finally:
        del app.dependency_overrides[get_session]
