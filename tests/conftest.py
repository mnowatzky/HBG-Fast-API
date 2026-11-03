import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlmodel import Session, create_engine
from testcontainers.community.postgres import PostgresContainer

ROOT = Path(__file__).parent.parent

RATE_LIMIT = 20

# No explicit driver, so that tests resolve the URL the same way production does.
postgres = PostgresContainer("postgres:17-bookworm", driver=None)
postgres.start()
url = make_url(postgres.get_connection_url())

# config.py reads these when it is first imported.
os.environ.update(
    STICKER_DB_HOST=url.host,
    STICKER_DB_PORT=str(url.port),
    STICKER_DB_USER=url.username,
    STICKER_DB_PASSWORD=url.password,
    STICKER_DB_NAME=url.database,
    STICKER_DB_TYPE=url.drivername,
    STICKER_ROOT_PATH="",
    STICKER_CORS_ORIGINS='["https://frontend.example"]',
    STICKER_CREATE_RATE_LIMIT=f"{RATE_LIMIT}/minute",
    # Nothing listens there. Tests that need an address use FakeGeocoder.
    STICKER_NOMINATIM_URL="http://127.0.0.1:9/reverse",
)


def pytest_sessionfinish():
    postgres.stop()


def alembic_config(database_url) -> Config:
    alembic_cfg = Config(ROOT / "alembic.ini")
    alembic_cfg.set_main_option("script_location", str(ROOT / "migrations"))
    alembic_cfg.attributes["url"] = database_url
    return alembic_cfg


@pytest.fixture(scope="session")
def database_url():
    return url


@pytest.fixture(scope="session")
def engine(database_url):
    command.upgrade(alembic_config(database_url), "head")
    return create_engine(database_url)


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        session.execute(text("TRUNCATE sticker RESTART IDENTITY"))
        session.commit()
        yield session


class FakeGeocoder:
    """Answers every place with `address` and records the places it was asked."""

    def __init__(self):
        from geocode import Address

        self.address = Address(
            city="Hamburg", state="Hamburg", country="Deutschland", country_code="DE"
        )
        self.places = []

    def reverse(self, latitude, longitude):
        self.places.append((latitude, longitude))
        return self.address


@pytest.fixture
def geocoder():
    return FakeGeocoder()


@pytest.fixture
def client(session, geocoder):
    from fastapi.testclient import TestClient

    from geocode import get_geocoder
    from main import app, limiter

    limiter.reset()
    app.dependency_overrides[get_geocoder] = lambda: geocoder
    yield TestClient(app)
    app.dependency_overrides.clear()
