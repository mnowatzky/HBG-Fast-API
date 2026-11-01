from datetime import datetime

import pytest
from conftest import RATE_LIMIT
from sqlalchemy.exc import OperationalError

from main import app, get_session
from sticker import Sticker

HAMBURG = {
    "latitude": 53.55,
    "longitude": 9.99,
    "name": "Malte",
    "city": "Hamburg",
    "state": "Hamburg",
    "country": "Deutschland",
}


def add_stickers(session, *names):
    """Oldest first, one day apart."""
    for day, name in enumerate(names, start=1):
        session.add(
            Sticker(latitude=1, longitude=2, name=name, date=datetime(2024, 1, day))
        )
    session.commit()


def test_create_returns_the_stored_sticker(client):
    response = client.post("/stickers", json=HAMBURG)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["name"] == "Malte"
    assert datetime.fromisoformat(body["date"]).year >= 2026


def test_create_ignores_a_client_supplied_date_and_id(client):
    body = client.post(
        "/stickers", json={**HAMBURG, "date": "2099-01-01T00:00:00Z", "id": 999}
    ).json()

    assert body["id"] == 1
    assert not body["date"].startswith("2099")


def test_create_accepts_a_sticker_without_an_address(client):
    response = client.post(
        "/stickers", json={"latitude": 0, "longitude": 0, "name": "Auf See"}
    )

    assert response.status_code == 201
    assert response.json()["country"] == ""


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
        {"city": "x" * 256},
    ],
)
def test_create_rejects_invalid_input(client, change):
    assert client.post("/stickers", json={**HAMBURG, **change}).status_code == 422


def test_create_is_rate_limited_per_client(client):
    for _ in range(RATE_LIMIT):
        assert client.post("/stickers", json=HAMBURG).status_code == 201

    assert client.post("/stickers", json=HAMBURG).status_code == 429
    assert client.get("/stickers").status_code == 200


def test_list_returns_full_stickers_newest_first(client, session):
    add_stickers(session, "first", "second")

    response = client.get("/stickers")

    assert response.status_code == 200
    assert [s["name"] for s in response.json()] == ["second", "first"]
    assert set(response.json()[0]) == {
        "id", "latitude", "longitude", "name", "date", "city", "state", "country",
    }  # fmt: skip


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
        {"limit": 501},
        {"offset": -1},
        {"format": "xml"},
        {"name": "x" * 76},
    ],
)
def test_list_rejects_invalid_parameters(client, params):
    assert client.get("/stickers", params=params).status_code == 422


def test_name_filter_matches_whole_names_in_shared_stickers(client, session):
    add_stickers(session, "Timo", "Tim", "Lisa & Timo", "Timo&Collin", "timo", "Malte")

    response = client.get("/stickers", params={"name": "Timo"})

    assert [s["name"] for s in response.json()] == [
        "timo", "Timo&Collin", "Lisa & Timo", "Timo",
    ]  # fmt: skip
    assert response.headers["x-total-count"] == "4"


def test_name_filter_ignores_stray_whitespace_in_legacy_names(client, session):
    add_stickers(session, "Christoph ", " Lisa & Christoph  ", "Malte")

    response = client.get("/stickers", params={"name": "Christoph"})

    assert response.headers["x-total-count"] == "2"


def test_name_filter_treats_special_characters_literally(client, session):
    add_stickers(session, "Timo", "T.mo")

    assert [
        s["name"] for s in client.get("/stickers", params={"name": "T.mo"}).json()
    ] == ["T.mo"]
    assert client.get("/stickers", params={"name": "%"}).json() == []


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
        for path in ["/health", "/stickers"]:
            response = client.get(path)
            assert response.status_code == 503
            assert "secret" not in response.text
    finally:
        app.dependency_overrides.clear()
