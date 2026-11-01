"""Baseline for both new databases and ones made by the old create_all() startup.

The IF NOT EXISTS clauses make it safe on a database that already has the table.
It also drops a column that a CSV import tool left behind by accident.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

INDEXED_COLUMNS = ["latitude", "longitude", "name", "date", "city", "state", "country"]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sticker (
            id SERIAL PRIMARY KEY,
            latitude DOUBLE PRECISION NOT NULL,
            longitude DOUBLE PRECISION NOT NULL,
            name VARCHAR NOT NULL,
            date TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            city VARCHAR NOT NULL,
            state VARCHAR NOT NULL,
            country VARCHAR NOT NULL
        )
        """
    )
    op.execute(
        'ALTER TABLE sticker DROP COLUMN IF EXISTS "latitude;longitude;name;date;city;state;country"'
    )
    for column in INDEXED_COLUMNS:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_sticker_{column} ON sticker ({column})"
        )


def downgrade() -> None:
    raise NotImplementedError("The baseline cannot be downgraded.")
