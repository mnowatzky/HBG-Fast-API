import pytest

from places import known_timezones, legacy_country, timezone_at


@pytest.fixture(scope="module")
def known(engine):
    with engine.connect() as connection:
        return known_timezones(connection)


@pytest.mark.parametrize(
    "latitude, longitude, zone",
    [
        (53.55, 9.99, "Europe/Berlin"),
        (13.75, 100.5, "Asia/Bangkok"),
        (40, -30, "Etc/GMT+2"),
    ],
)
def test_timezone_at(known, latitude, longitude, zone):
    assert timezone_at(latitude, longitude, known) == zone


def test_timezone_falls_back_to_the_nautical_zone_if_postgres_lacks_it():
    assert timezone_at(13.75, 100.5, known={"UTC"}) == "Etc/GMT-7"
    assert timezone_at(48.85, 2.35, known={"UTC"}) == "Etc/GMT+0"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Deutschland", ("DE", "Deutschland")),
        ("Germany", ("DE", "Deutschland")),
        ("norja", ("NO", "Norwegen")),
        (" Czechia ", ("CZ", "Tschechien")),
        ("Atlantis", ("", "Atlantis")),
        ("", ("", "")),
    ],
)
def test_legacy_country(name, expected):
    assert legacy_country(name) == expected
