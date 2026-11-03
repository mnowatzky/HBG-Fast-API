"""Store dates in UTC with their offset, and add country codes and local time zones.

Existing dates are taken as UTC, which new stickers already were. The export of
the old site is in that server's local time, and import_stickers.py converts it,
so import it after this migration. Existing stickers get their time zone and,
for the country names of the old site, a code and the German name.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

from places import known_timezones, legacy_country, timezone_at

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "sticker",
        "date",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(),
        existing_nullable=False,
        postgresql_using="date AT TIME ZONE 'UTC'",
    )
    op.add_column(
        "sticker",
        sa.Column("country_code", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "sticker",
        sa.Column("timezone", sa.String(), nullable=False, server_default="UTC"),
    )
    op.create_index("ix_sticker_country_code", "sticker", ["country_code"])

    connection = op.get_bind()
    known = known_timezones(connection)
    rows = connection.execute(
        sa.text("SELECT id, latitude, longitude, country FROM sticker")
    ).all()
    updates = []
    for id, latitude, longitude, country in rows:
        code, name = legacy_country(country)
        zone = timezone_at(latitude, longitude, known)
        updates.append({"id": id, "code": code, "name": name, "zone": zone})
    if updates:
        connection.execute(
            sa.text(
                "UPDATE sticker SET country_code = :code, country = :name, "
                "timezone = :zone WHERE id = :id"
            ),
            updates,
        )

    op.alter_column("sticker", "country_code", server_default=None)
    op.alter_column("sticker", "timezone", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_sticker_country_code", "sticker")
    op.drop_column("sticker", "timezone")
    op.drop_column("sticker", "country_code")
    op.alter_column(
        "sticker",
        "date",
        type_=sa.DateTime(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        postgresql_using="date AT TIME ZONE 'UTC'",
    )
