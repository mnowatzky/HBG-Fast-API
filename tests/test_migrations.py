from alembic import command
from conftest import alembic_config
from sqlalchemy import create_engine, inspect, text

STRAY_COLUMN = "latitude;longitude;name;date;city;state;country"


def fresh_schema(database_url, name):
    """A database url whose connections use their own empty schema."""
    with create_engine(database_url).begin() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {name} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {name}"))
    return database_url.set(query={"options": f"-csearch_path={name}"})


def test_models_match_the_migrations(database_url):
    url = fresh_schema(database_url, "drift")
    config = alembic_config(url)

    command.upgrade(config, "head")

    command.check(config)  # raises if autogenerate would produce a new migration


def test_baseline_adopts_a_database_from_the_old_create_all(database_url):
    url = fresh_schema(database_url, "legacy")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                CREATE TABLE sticker (
                    id SERIAL PRIMARY KEY,
                    latitude DOUBLE PRECISION NOT NULL,
                    longitude DOUBLE PRECISION NOT NULL,
                    name VARCHAR NOT NULL,
                    date TIMESTAMP NOT NULL,
                    city VARCHAR NOT NULL,
                    state VARCHAR NOT NULL,
                    country VARCHAR NOT NULL,
                    "{STRAY_COLUMN}" VARCHAR(128)
                );
                CREATE INDEX ix_sticker_date ON sticker (date);
                INSERT INTO sticker (latitude, longitude, name, date, city, state, country)
                VALUES (1, 2, 'Malte', '2024-01-01', '', '', '');
                """
            )
        )

    command.upgrade(alembic_config(url), "head")

    inspector = inspect(engine)
    assert STRAY_COLUMN not in [c["name"] for c in inspector.get_columns("sticker")]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM sticker")) == "Malte"
